"""One-off moves outside a build, for spoken commands: "hand me a cube"
(pick a loose block, put it on the hand-over spot) and "put it there"
(move that block to where the person pointed).

Runs the builder's own Motion in a thread of its own, so the safety stop,
pause and the live view all work exactly as during a build. Never runs while
a build does, and a build can't start while a fetch runs (server.py checks).
"""
import math
import threading

from .catalog import block_yaw_from_long_axis


class Fetcher:
    def __init__(self, cfg, catalog, builder):
        self.cfg, self.catalog, self.b = cfg, catalog, builder
        self._worker = None
        self.last = None          # {"x", "y", "type", "color"}: the block we last put down
        self.result = None
        self.target = None        # for the map: {"block": tracked block, "place": (x, y), "label"} while running

    def busy(self):
        return self._worker is not None and self._worker.is_alive()

    # ---------------------------------------------------------------- finding blocks
    def _fits(self, blk, tid):
        """Could this tracked block be a `tid`? Colorless mode only has the footprint to go on."""
        if blk.get("type"):
            return blk["type"] == tid
        if self.cfg["use_color"] or not blk.get("size"):
            return False
        if blk.get("round") is not None and bool(blk["round"]) != self.catalog.round_(tid):
            return False
        fp = sorted(self.catalog.size(tid)[:2], reverse=True)
        tol = 1.5 + 0.3 * self.catalog.height(tid)       # the camera sees a tall block's sides too
        return abs(blk["size"][0] - fp[0]) <= tol and abs(blk["size"][1] - fp[1]) <= tol

    def guess_type(self, blk):
        if blk.get("type"):
            return blk["type"]
        size = blk.get("size") or [3.0, 3.0]

        def err(tid):
            fp = sorted(self.catalog.size(tid)[:2], reverse=True)
            e = abs(size[0] - fp[0]) + abs(size[1] - fp[1])
            if blk.get("round") is not None and bool(blk["round"]) != self.catalog.round_(tid):
                e += 3.0
            return e + 0.01 * self.catalog.height(tid)      # same outline: the shorter one first
        return min(self.catalog.types, key=err)

    def _reachable(self, x, y, h, z0=0.0):
        return all(self.b.body.solve([x, y, z])["reachable"]
                   for z in (self.cfg.grasp_z(z0, h), self.cfg.hover_z(z0, h)))

    def find(self, tid=None, color=None, avoid=(), near=None):
        """Nearest loose block (not on the build strip, not on an `avoid` spot) of that kind."""
        bx, by = near or self.cfg["layout"]["base"]
        best = None
        for blk in self.b.active_blocks():
            if self.cfg.in_build(blk["x"], blk["y"]) or blk.get("zone") == "build":
                continue
            if any(math.hypot(blk["x"] - ax, blk["y"] - ay) < 4.0 for ax, ay in avoid):
                continue
            if color and self.cfg["use_color"] and blk.get("color") != color:
                continue
            if tid and not self._fits(blk, tid):
                continue
            kind = tid or self.guess_type(blk)
            if not self._reachable(blk["x"], blk["y"], self.catalog.height(kind)):
                continue
            d = math.hypot(blk["x"] - bx, blk["y"] - by)
            if best is None or d < best[0]:
                best = (d, dict(blk, type=kind))
        return None if best is None else best[1]

    def block_at(self, x, y, radius=4.0):
        best = None
        for blk in self.b.active_blocks():
            d = math.hypot(blk["x"] - x, blk["y"] - y)
            if d <= radius and (best is None or d < best[0]):
                best = (d, blk)
        return None if best is None else best[1]

    def pointed(self, max_age=15.0):
        """Where the person last pointed (gestures set builder.pointed), if recent. -> (x, y) or None."""
        p = getattr(self.b, "pointed", None)
        if not p:
            return None
        if isinstance(p, dict):
            x, y, t = p.get("x"), p.get("y"), p.get("t")
        else:
            x, y, t = p[0], p[1], (p[2] if len(p) > 2 else None)
        if x is None or y is None:
            return None
        if t is not None and self.b.clock.time() - float(t) > max_age:
            return None
        return float(x), float(y)

    def free_spot(self, x, y, tid, clear=4.5):
        """(x, y), or the nearest free reachable spot around it if a block already sits there."""
        for dx, dy in ((0, 0), (-5, 0), (0, -5), (5, 0), (-5, -5), (5, -5), (-10, 0), (0, -10)):
            sx, sy = x + dx, y + dy
            if (dx or dy) and self.cfg.in_build(sx, sy, 2.0):
                continue
            if self.block_at(sx, sy, clear) is None and self.target_ok(sx, sy, tid):
                return sx, sy
        return None

    def target_ok(self, x, y, tid):
        return self.cfg.in_work_area(x, y) and self._reachable(x, y, self.catalog.height(tid))

    # ---------------------------------------------------------------- running
    def start(self, blk, target, label):
        """Pick `blk` (a tracked block with "type") and put it down at `target` (x, y)."""
        if self.busy() or self.b.busy():
            return False
        self._worker = threading.Thread(target=self._run, args=(dict(blk), tuple(target), label), daemon=True)
        self._worker.start()
        return True

    def pause(self):
        if not self.busy() or self.b.paused:
            return False
        self.b.paused = True
        self.b.abort.set()
        self.b.arm.stop()
        with self.b.lock:
            self.b.status["paused"] = True
        self.b.log("paused")
        return True

    def cancel(self):
        if not self.busy():
            return False
        self.b.cancel.set()
        self.b.abort.set()
        self.b.paused = False
        self.b.arm.stop()
        self.b.log("stop requested")
        return True

    def _run(self, blk, target, label):
        b, m = self.b, self.b.motion
        b.cancel.clear()
        b.paused = False
        if not b.safety_stopped:
            b.abort.clear()
        with b.lock:
            b.status.update({"result": None, "prompt": None, "paused": False})
        b.set_mode("building", label)
        b.log(label)
        tid = blk["type"]
        result = "error"
        try:
            for attempt in range(2):
                yaw = block_yaw_from_long_axis(blk.get("angle", 0.0), tid, self.catalog)
                blk.update(z=0.0, pose=0, yaw=yaw, color=blk.get("color") or "any")
                g = m.grip_for(yaw, "y", yaw, tid)
                self.target = {"block": dict(blk), "place": list(target), "label": label, "stage": "pick"}
                b.action(f"{label}: picking it up")
                r = m.pick(blk, g)
                if r == "ok":
                    break
                if r == "abort" or b.cancel.is_set():
                    break
                b.log(f"pick {r}; looking again")
                again = self.find(tid, blk.get("color"), avoid=[target], near=(blk["x"], blk["y"]))
                if again is None:
                    break
                blk = again
            if r != "ok":
                result = "stopped" if (r == "abort" or b.cancel.is_set()) else f"pick {r}"
            else:
                b.action(f"{label}: putting it down")
                self.target = dict(self.target or {}, stage="place")
                step = {"x": target[0], "y": target[1], "z": 0.0, "h": self.catalog.height(tid)}
                r = m.place(step, g)
                result = "done" if r == "ok" else ("stopped" if r == "abort" else f"place {r}")
                if r == "ok":
                    self.last = {"x": target[0], "y": target[1], "type": tid, "color": blk.get("color")}
            if not b.cancel.is_set():
                b.action("going home")
                m.home()                  # out of the way of the hand that takes it
        except Exception as e:            # keep the UI alive and tell the user
            result = "error"
            b.log(f"error: {e!r}")
        finally:
            if b.cancel.is_set() and not b.safety_stopped:
                b.abort.clear()
            b.cancel.clear()
            b.paused = False
            self.result = result
            self.target = None
            with b.lock:
                b.status["result"] = result
                b.status["paused"] = False
            b.set_mode("done" if result == "done" else "idle", f"{label}: {result}")
            b.log(f"{label}: {result}")

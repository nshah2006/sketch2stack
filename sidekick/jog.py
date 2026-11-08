"""Small moves the person asks for: "back off", "move up", "move down".

The caller pauses any running build/fetch first; a jog only ever moves the
claw a few cm and leaves the arm where it ends (paused until "go on").
Heights are clamped: never below 1.5 cm, never below block top + 1 cm near a
block the arm knows about (built so far or seen loose). While the safety stop
is on, only moves away from the hand (back off, up) are allowed.
"""
import math
import threading
import time

from .perception import claw_tip

STEP_CM = 3.0          # move up / move down
BACK_CM = 8.0          # back off: toward the arm base
BACK_LIFT_CM = 4.0     # back off: up first
MIN_Z = 1.5
BLOCK_CLEAR = 1.0


class _Flag:
    """Quacks like threading.Event for arm.move(abort=...)."""
    def __init__(self, fn):
        self.is_set = fn


class Jogger:
    def __init__(self, cfg, catalog, builder):
        self.cfg, self.catalog, self.b = cfg, catalog, builder
        self.lock = threading.Lock()
        fp = [max(catalog.size(t)[:2]) for t in catalog.types] or [3.0]
        self.near_r = max(fp) / 2 + 1.5        # "near a block": within its half length + 1.5 cm
        self.saved = None                      # pose a paused task was in before the first jog

    def restore(self):
        """Before a paused task goes on: back to where it was paused, from above
        (the interrupted move then carries on from its own start). -> ok"""
        if self.saved is None:
            return True
        b, saved = self.b, self.saved
        with self.lock:
            try:
                sx, sy, sz = (float(v) for v in b.body.forward(saved[:4])[0][:3])
                x, y, z = self.where()
                stop = _Flag(lambda: b.safety_stopped or b.cancel.is_set())
                over = self._reach((sx, sy, max(z, sz)))
                if over is not None and not b.arm.move(list(over["pulses"]) + list(b.arm.targets[4:6]), abort=stop):
                    return False
                if not b.arm.move(list(saved[:4]) + list(b.arm.targets[4:6]), abort=stop):
                    return False
                b.log("jog: back to where I paused")
                self.saved = None
                return True
            except Exception as e:
                b.log(f"jog restore failed: {e!r}")
                self.saved = None
                return True

    def busy(self):
        return self.lock.locked()

    def seen_tip(self):
        """Claw tip from the camera's last marker fix, or None."""
        c = self.b.claw
        if not c:
            return None
        t = claw_tip(dict(c), self.cfg["marker_to_fingertip"], self.cfg.get("marker_forward", 0.0),
                     self.cfg["layout"]["base"], self.cfg.get("claw_normal_bias"))
        return float(t["x"]), float(t["y"]), float(t["z"])

    def where(self):
        """Claw tip (x, y, z): the body model at the commanded pulses when that is
        inside its known space, else what the camera saw."""
        p = tuple(float(v) for v in self.b.body.forward(list(self.b.arm.targets[:4]))[0][:3])
        w, h = self.cfg["layout"]["work_area"]
        if -10 <= p[0] <= w + 10 and -10 <= p[1] <= h + 10 and -3 <= p[2] <= 45:
            return p
        return self.seen_tip() or p

    def floor(self, x, y):
        """Lowest safe tip height at (x, y)."""
        z = MIN_Z
        try:
            obs = self.b._obstacles()
        except Exception:
            obs = []
        for ox, oy, top in obs:
            if math.hypot(ox - x, oy - y) < self.near_r:
                z = max(z, top + BLOCK_CLEAR)
        return z + getattr(self.b.motion, "carry_h", 0.0)

    def _reach(self, p):
        s = self.b.body.solve(list(p))
        return s if s["reachable"] else None

    def _go(self, p, down=False):
        """Move the tip to p, wrist roll and claw unchanged. A move down gives up on a
        safety stop; any move gives up on Stop/cancel."""
        b = self.b
        s = self._reach(p)
        if s is None:
            return False
        stop = (lambda: b.safety_stopped or b.cancel.is_set()) if down else (lambda: b.cancel.is_set())
        return b.arm.move(list(s["pulses"]) + list(b.arm.targets[4:6]), abort=_Flag(stop))

    def plan(self, kind):
        """-> (list of tip points to go through, message) or (None, why not)."""
        x, y, z = self.where()
        if kind == "move_up":
            for dz in (STEP_CM, 2.0, 1.0):
                if self._reach((x, y, z + dz)):
                    return [(x, y, z + dz)], f"up {dz:.0f} cm to {z + dz:.1f} cm"
            return None, "I can't go any higher here."
        if kind == "move_down":
            lo = self.floor(x, y)
            nz = max(z - STEP_CM, lo)
            if nz > z - 0.5:
                return None, f"I can't go lower here: a block or the table is too close ({z:.1f} cm up)."
            if not self._reach((x, y, nz)):
                return None, "I can't reach lower here."
            return [(x, y, nz)], f"down {z - nz:.1f} cm to {nz:.1f} cm"
        if kind == "back_off":
            bx, by = self.cfg["layout"]["base"]
            dirs = [("toward the base", bx - x, by - y)]
            hands = list(getattr(self.b, "hands", None) or [])
            if hands:                                          # away from the nearest hand
                h = min(hands, key=lambda h: math.hypot(h["x"] - x, h["y"] - y))
                dirs.insert(0, ("away from your hand", x - h["x"], y - h["y"]))
            for lift in (BACK_LIFT_CM, 2.0, 0.0):
                up = (x, y, z + lift)
                if lift and not self._reach(up):
                    continue
                for name, vx, vy in dirs:
                    n = math.hypot(vx, vy)
                    if n < 0.5:
                        continue
                    for d in (BACK_CM, 6.0, 4.0, 2.5):
                        tx, ty = x + vx / n * d, y + vy / n * d
                        if math.hypot(tx - bx, ty - by) < 6.0:     # never into the base itself
                            continue
                        tz = max(z + lift, self.floor(tx, ty))
                        if self._reach((tx, ty, tz)):
                            pts = ([up] if lift else []) + [(tx, ty, tz)]
                            return pts, f"backed off {d:.0f} cm {name}, up {tz - z:.0f} cm"
            for dz in (BACK_CM, 6.0, 4.0, 2.0):                 # no room sideways: go up instead
                if self._reach((x, y, z + dz)):
                    return [(x, y, z + dz)], f"up {dz:.0f} cm (no room to back away)"
            return None, "I can't back away from here."
        return None, f"unknown jog {kind!r}"

    def run(self, kind, keep=False):
        """Do the jog now (the caller has paused any task; keep=True remembers the
        pose to go back to before it goes on). -> (ok, msg, info)"""
        b = self.b
        if b.safety_stopped and kind == "move_down":
            return False, "Not moving down while a hand is near the claw.", {}
        if not self.lock.acquire(blocking=False):
            return False, "Still moving from the last nudge.", {}
        try:
            before = self.where()
            pts, msg = self.plan(kind)
            if pts is None:
                b.log(f"jog {kind}: refused ({msg})")
                return False, msg, {"from": _r(before)}
            if keep and self.saved is None:
                self.saved = list(b.arm.targets)
            for i, p in enumerate(pts):
                if not self._go(p, down=(kind == "move_down")):
                    b.log(f"jog {kind}: interrupted")
                    return False, "Stopped partway.", {"from": _r(before), "to": _r(self.where())}
            time.sleep(0.1)
            after = self.where()
            b.log(f"jog {kind}: {msg}", x=round(after[0], 1), y=round(after[1], 1), z=round(after[2], 1))
            return True, msg, {"from": _r(before), "to": _r(after)}
        finally:
            self.lock.release()


def _r(p):
    return [round(v, 1) for v in p]

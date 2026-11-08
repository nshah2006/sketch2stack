"""Builder: runs a build plan on the arm (replaces the handbook coordinator).

Two threads:
  vision  every frame: observation -> block types -> tracker -> hands ->
          safety check -> shared state. Only the safety stop may touch the
          arm from here.
  worker  the only thread that moves the arm: for each planned step, find a
          matching loose block in a supply zone (or ask for one), pick it,
          turn it, place it, check it with the camera.

Safety, every frame, first: a hand within stop_distance of the claw while the
claw is low -> stop the arm at once; resume after the area is clear for
resume_after seconds. The claw unseen for over 1 s while moving with a hand
in the work area also stops it.
"""
import collections
import json
import math
import threading
import time

from . import config as C
from .catalog import block_yaw_from_long_axis, fold180
from .motion import Motion
from .perception import BlockTracker, classify, claw_tip
from .planner import plan as make_plan

LED = {"idle": 0, "building": 1, "waiting": 2, "done": 3, "stopped": 4}


class Builder:
    def __init__(self, cfg, catalog, source, arm, body, feeder=None, log_dir=None):
        self.cfg, self.catalog, self.source, self.arm, self.body = cfg, catalog, source, arm, body
        self.clock = arm.clock
        self.feeder = feeder                     # sim person (auto-feed) or None (ask the user)
        self.tracker = BlockTracker(cfg)
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.abort = threading.Event()           # safety stop: interrupts the current move
        self.cancel = threading.Event()          # user pressed Stop: end the build
        self._quit = threading.Event()
        self.obs = None
        self.blocks = []
        self.hands = []
        self.claw = None
        self.claw_seen_t = 0.0
        self.claw_seq = 0
        self.claw_hist = collections.deque(maxlen=20)
        self.safety_stopped = False
        self._clear_since = None
        self.mode = "idle"
        self.status = {"mode": "idle", "action": "", "step": 0, "total": 0, "prompt": None,
                       "steps": [], "log": [], "safety": False, "fps": 0.0, "result": None,
                       "run_id": 0, "paused": False}
        self.plan_steps = []
        self._revision = None      # steps waiting to be swapped in at a step boundary
        self._fps_t, self._fps_n = time.monotonic(), 0
        self._worker = None
        self._start_lock = threading.Lock()      # two Build clicks can't both start a run
        self.run_id = 0                          # every build gets a new id; the UI ignores other runs
        self.paused = False                      # user pause (separate from the safety stop)
        self.motion = Motion(cfg, arm, body, catalog, self.read_claw, self.active_blocks,
                             self.abort, self.wait_resume, log=self.log)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.log_path = C.path("logs", log_dir) / f"run_{stamp}.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._vision = threading.Thread(target=self._vision_loop, daemon=True)
        self._vision.start()

    # ================================================================ logging/status
    def log(self, msg, **extra):
        rec = {"t": round(self.clock.time(), 2), "mode": self.mode, "msg": msg, **extra}
        with open(self.log_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        with self.lock:
            self.status["log"] = (self.status["log"] + [msg])[-40:]

    def set_mode(self, mode, action=None):
        self.mode = mode
        with self.lock:
            self.status["mode"] = mode
            if action is not None:
                self.status["action"] = action
        if self.cfg["leds"] or self.cfg["use_sim"]:
            try:
                self.arm.led(LED.get(mode, 0))
            except Exception:
                pass

    def action(self, text):
        with self.lock:
            self.status["action"] = text

    def snapshot(self):
        with self.lock:
            s = dict(self.status)
            s["blocks"] = [dict(b) for b in self.blocks]
            s["hands"] = list(self.hands)
            s["claw"] = self.claw
            s["plan"] = list(self.plan_steps)
            return s

    # ================================================================ vision thread
    def _vision_loop(self):
        while not self._quit.is_set():
            obs = self.source.read(timeout=0.5)
            if obs is None:
                continue
            classify(obs.detections, self.catalog, getattr(self.source, "calib", None))
            blocks = self.tracker.update(obs.detections, obs.t)
            for b in blocks:
                if b.get("type"):
                    b["yaw"] = block_yaw_from_long_axis(b.get("angle", 0.0), b["type"], self.catalog)
            self._safety(obs)
            with self.cond:
                self.obs, self.blocks, self.hands = obs, blocks, obs.hands
                if obs.claw is not None:
                    self.claw = obs.claw
                    self.claw_seen_t = obs.t
                    self.claw_seq += 1
                    self.claw_hist.append(obs.claw)
                self.cond.notify_all()
            self._fps_n += 1
            now = time.monotonic()
            if now - self._fps_t >= 1.0:
                with self.lock:
                    self.status["fps"] = self._fps_n / (now - self._fps_t)
                self._fps_t, self._fps_n = now, 0

    def _safety(self, obs):
        claw = obs.claw
        if claw is None and self.claw is not None and obs.t - self.claw_seen_t < 0.5:
            claw = self.claw            # briefly hidden (e.g. by the hand itself)
        danger = False
        if claw is not None and claw["z"] < self.cfg["stop_claw_height"]:
            for h in obs.hands:
                if math.hypot(h["x"] - claw["x"], h["y"] - claw["y"]) < self.cfg["stop_distance"]:
                    danger = True
        if (obs.claw is None and self.arm.moving and obs.hands
                and obs.t - self.claw_seen_t > self.cfg["claw_unseen_stop"]):
            if any(self.cfg.in_work_area(h["x"], h["y"]) for h in obs.hands):
                danger = True
        if danger:
            self._clear_since = None
            if not self.safety_stopped:
                self.arm.stop()
                self.abort.set()
                self.safety_stopped = True
                with self.lock:
                    self.status["safety"] = True
                self.log("SAFETY STOP: hand near the claw")
                if self.cfg["leds"] or self.cfg["use_sim"]:
                    self.arm.led(LED["stopped"])
        elif self.safety_stopped:
            if self._clear_since is None:
                self._clear_since = obs.t
            elif obs.t - self._clear_since >= self.cfg["resume_after"]:
                self.safety_stopped = False
                if not self.paused:
                    self.abort.clear()
                with self.lock:
                    self.status["safety"] = False
                self.log("clear: resuming")
                self.set_mode(self.mode)

    # ================================================================ helpers for motion
    def active_blocks(self):
        with self.lock:
            return [dict(b) for b in self.blocks]

    def read_claw(self, n=5, timeout=1.5):
        end = self.clock.time() + timeout
        with self.cond:
            start = self.claw_seq
            while self.claw_seq - start < n:
                left = end - self.clock.time()
                if left <= 0:
                    break
                self.cond.wait(self.clock.real(min(left, 0.2)))
            got = min(n, self.claw_seq - start)
            if got < 2:
                return None
            recent = list(self.claw_hist)[-got:]
        avg = {k: sum(c.get(k, 0.0) for c in recent) / len(recent) for k in ("x", "y", "z", "nx", "ny", "down")}
        return claw_tip(avg, self.cfg["marker_to_fingertip"])

    def wait_resume(self):
        """Called by motion while the safety stop or a user pause is active."""
        self.action("paused" if self.paused and not self.safety_stopped else "paused: hand near the arm")
        while self.abort.is_set():
            if self.cancel.is_set() or self._quit.is_set():
                return False
            self.clock.sleep(0.1)
        return not self.cancel.is_set()

    # ================================================================ build
    def busy(self):
        return self._worker is not None and self._worker.is_alive()

    def start_build(self, design):
        """-> (ok, problems, run_id)"""
        with self._start_lock:
            if self.busy():
                return False, [{"level": "error", "msg": "the arm is already building; stop it first"}], self.run_id
            steps, probs = make_plan(design, self.cfg, self.catalog, self.body)
            errors = [p for p in probs if p["level"] == "error"]
            if errors:
                return False, probs, self.run_id
            self.cancel.clear()
            self.paused = False
            if not self.safety_stopped:
                self.abort.clear()               # a leftover Stop must not block the next build
            self.run_id += 1
            self.plan_steps = steps
            with self.lock:
                self.status.update({"run_id": self.run_id, "step": 0, "total": len(steps), "result": None,
                                    "prompt": None, "paused": False,
                                    "log": [],     # each build starts with a fresh log
                                    "steps": [{"label": self._step_label(s), "state": "todo",
                                               "index": s["index"]} for s in steps]})
            self._worker = threading.Thread(target=self._run, args=(steps, self.run_id), daemon=True)
            self._worker.start()
            return True, probs, self.run_id

    def pause(self):
        if not self.busy() or self.paused:
            return False
        self.paused = True
        self.abort.set()
        self.arm.stop()
        with self.lock:
            self.status["paused"] = True
        self.log("paused")
        return True

    def resume(self):
        if not self.paused:
            return False
        self.paused = False
        with self.lock:
            self.status["paused"] = False
        if not self.safety_stopped:
            self.abort.clear()
        self.log("resumed")
        return True

    def _step_label(self, s):
        name = self.catalog.types[s["type"]]["name"]
        pose = self.catalog.pose_name(s["type"], s.get("pose", 0))
        label = (f"{s['color']} {name}" if self.cfg["use_color"] else name)
        if pose != self.catalog.POSE_NAMES[0]:
            label += f", {pose}"
        if s["z"] > 0:
            label += f", on top ({s['z']:.1f} cm up)"
        return label

    def clear_log(self):
        with self.lock:
            self.status["log"] = []

    def stop_build(self):
        self.arm.stop()
        if not self.busy():
            self.log("stopped")
            return
        self.cancel.set()
        self.abort.set()
        self.paused = False
        self.log("stop requested")

    def _resync_steps(self, steps, done_upto):
        """Redraw the step list after a revision, keeping what is already built."""
        with self.lock:
            old = self.status["steps"]
            self.status["steps"] = [
                old[k] if k < done_upto and k < len(old)
                else {"label": self._step_label(s), "state": "todo", "index": s["index"]}
                for k, s in enumerate(steps)]
            self.status["total"] = len(steps)

    def revise(self, steps):
        """Replace the blocks that have not been placed yet.

        Only the future is ours to change: the arm can pick from a supply zone
        and place, but it has no way to take a block back off the build, so a
        step already done is a fact. -> (ok, message)
        """
        if not self.busy():
            return False, "the arm is not building"
        with self.lock:
            done = sum(1 for s in self.status["steps"] if s["state"] in ("done", "failed"))
            active = next((k for k, s in enumerate(self.status["steps"]) if s["state"] == "active"), None)
        # the step in the claw right now is already committed too
        fixed = max(done, (active + 1) if active is not None else 0)
        if len(steps) < fixed:
            return False, f"{fixed} blocks are already placed; they cannot be taken back off"
        with self.lock:
            self._revision = list(steps[fixed:])
        return True, f"will change the {len(steps) - fixed} blocks still to come"

    def remaining(self):
        """The steps not yet placed, and how many are already committed."""
        with self.lock:
            done = sum(1 for s in self.status["steps"] if s["state"] in ("done", "failed"))
            active = next((k for k, s in enumerate(self.status["steps"]) if s["state"] == "active"), None)
        fixed = max(done, (active + 1) if active is not None else 0)
        return list(self.plan_steps[fixed:]), fixed

    def _gesture(self, name):
        """A nod or a head-shake at the person. Never lets a build fail over it:
        gestures refuse themselves while carrying a block or during a stop."""
        if not self.cfg.get("gestures", True):
            return
        try:
            getattr(self.motion, name)()
        except Exception as e:
            self.log(f"gesture {name} skipped: {e!r}")

    def _step_state(self, i, state):
        with self.lock:
            self.status["steps"][i]["state"] = state
            self.status["step"] = i + (1 if state == "done" else 0)

    def _run(self, steps, run_id=None):
        self.set_mode("building", "starting")
        self.log(f"build started: {len(steps)} blocks")
        result = "done"
        try:
            self.motion.home()
            i = 0
            while i < len(steps):
                if self.cancel.is_set():
                    result = "stopped"
                    break
                # Swap in a revision only here, between two placements. Never
                # while the claw is moving, and never over a step already done.
                with self.lock:
                    pending, self._revision = self._revision, None
                if pending is not None:
                    steps = list(steps[:i]) + list(pending)
                    self.plan_steps = steps
                    self._resync_steps(steps, i)
                    self.log(f"plan revised: {len(steps) - i} blocks left")
                    self._gesture("nod")  # "got it"
                    if i >= len(steps):
                        break
                st = steps[i]
                self._step_state(i, "active")
                r = self._do_step(i, st)
                self._step_state(i, "done" if r == "ok" else "failed")
                if r == "cancel":
                    result = "stopped"
                    break
                if r != "ok":
                    result = "incomplete"
                i += 1
            if not self.cancel.is_set():
                if not self.safety_stopped and not self.paused:
                    self.abort.clear()
                self.action("going home")
                self.motion.home()
        except Exception as e:      # keep the UI alive and tell the user
            result = "error"
            self.log(f"error: {e!r}")
        finally:
            self.paused = False
            if self.cancel.is_set() and not self.safety_stopped:
                self.abort.clear()
            with self.lock:
                self.status["result"] = result
                self.status["prompt"] = None
                self.status["paused"] = False
            self.set_mode("done" if result == "done" else "idle", f"build {result}")
            self.log(f"build {result}")

    def _at_pickup(self, st, exclude=()):
        """Colorless mode: whatever block sits on the pickup spot is the one we asked for."""
        px, py = self.cfg["layout"]["pickup"]
        for b in self.active_blocks():
            if b["id"] in exclude or math.hypot(b["x"] - px, b["y"] - py) > 3.0:
                continue
            b = dict(b)
            b["type"], b["color"] = st["type"], st["color"]
            b["z"] = 0.0
            b["pose"] = st.get("pose", 0)
            b["yaw"] = block_yaw_from_long_axis(b.get("angle", 0.0), st["type"], self.catalog, b["pose"])
            if b.get("size"):
                fp = sorted(self.catalog.size(st["type"], b["pose"])[:2], reverse=True)
                if abs(b["size"][0] - fp[0]) > 1.5 or abs(b["size"][1] - fp[1]) > 1.5:
                    # clearly the wrong block (e.g. left over from a stopped build): don't build with it
                    msg = (f"Wrong block on the pickup spot. Swap it for a "
                           f"{self.catalog.types[st['type']]['name'].lower()}.")
                    with self.lock:
                        fresh = self.status.get("prompt") != msg
                        if fresh:
                            self.status["prompt"] = msg
                            self.status["log"] = (self.status["log"] + [msg])[-40:]
                    if fresh:
                        self._gesture("refuse")     # only on the first look, not every frame
                    return None
            return b
        return None

    def _find_supply(self, st, exclude=()):
        if not self.cfg["use_color"]:
            return self._at_pickup(st, exclude)
        best = None
        for b in self.active_blocks():
            if b.get("type") != st["type"] or b["color"] != st["color"] or b["id"] in exclude:
                continue
            if b.get("zone") == "build" or not b.get("zone"):
                continue
            if not self._pick_reachable(b):
                continue
            d = math.hypot(b["x"] - st["x"], b["y"] - st["y"])
            if best is None or d < best[0]:
                best = (d, b)
        return best[1] if best else None

    def _pick_reachable(self, b):
        key = (b["id"], round(b["x"]), round(b["y"]))
        cache = self.__dict__.setdefault("_reach_cache", {})
        if key not in cache:
            h = self.catalog.height(b["type"], b.get("pose", 0))
            z0 = float(b.get("z") or 0.0)
            cache[key] = all(self.body.solve([b["x"], b["y"], z])["reachable"]
                             for z in (self.cfg.grasp_z(z0, h), self.cfg.hover_z(z0, h)))
        return cache[key]

    def _hand_clear(self, b, radius=15.0, still=1.0):
        """No hand near the block, and the block has sat still for `still` seconds."""
        now = self.obs.t if self.obs is not None else self.clock.time()
        if any(math.hypot(h["x"] - b["x"], h["y"] - b["y"]) < radius for h in self.hands):
            self._hand_seen_t = now
            return False
        if now - getattr(self, "_hand_seen_t", -99) < still:
            return False
        return now - b.get("first_seen", now) >= still

    def _wait_for_block(self, st):
        """Ask for a block (sim person, or a prompt in the UI) and wait for it."""
        name = self.catalog.types[st['type']]['name'].lower()
        pose = self.catalog.pose_name(st["type"], st.get("pose", 0))
        if pose != self.catalog.POSE_NAMES[0]:
            name += f" ({pose})"
        msg = (f"Place a {st['color']} {name} in a supply zone" if self.cfg["use_color"]
               else f"Place a {name} on the pickup spot")
        with self.lock:
            self.status["prompt"] = msg
        self.set_mode("waiting", msg)
        self.log(msg)
        self.action("moving out of the way")
        self.motion._move(list(self.cfg["park"]))       # stay clear of the person's hand
        self._gesture("listen")                         # "this one is for you"
        self.action(msg)
        if self.feeder is not None:
            self.feeder.request(st["type"], st["color"], st.get("pose", 0))
        t0 = self.clock.time()
        while not self.cancel.is_set():
            b = self._find_supply(st)
            if b is not None and self._hand_clear(b):
                self.clock.sleep(1.0)                 # let the hand clear first
                b = self._find_supply(st)
                if b is not None and not self.safety_stopped and self._hand_clear(b):
                    with self.lock:
                        self.status["prompt"] = None
                    self.set_mode("building")
                    return b
            if self.clock.time() - t0 > 300:
                return None
            self.clock.sleep(0.3)
        return None

    def _do_step(self, i, st):
        tried = set()
        for attempt in range(3):
            if self.cancel.is_set():
                return "cancel"
            blk = self._find_supply(st, tried)
            if blk is not None and not self._hand_clear(blk):
                blk = None
            blk = blk or self._wait_for_block(st)
            if blk is None:
                return "cancel" if self.cancel.is_set() else "fail"
            yaw = blk.get("yaw", 0.0)
            g_pick = self.motion.grip_for(yaw, st["grip"], st["yaw"], st["type"], st.get("pose", 0))
            # the same block axis at the place: fingers along target yaw (+90 if gripping across d)
            across_d = abs(fold180(g_pick - yaw - 90)) < 45
            g_place = fold180(st["yaw"] + (90.0 if across_d else 0.0))
            self.action(f"step {i + 1}: picking {st['color']} {st['type']}")
            self.log("pick", step=i, block=blk["id"], x=round(blk["x"], 1), y=round(blk["y"], 1))
            r = self.motion.pick(blk, g_pick)
            if r == "abort":
                return "cancel"
            if r != "ok":
                self.log(f"pick {r}; retrying")
                if self.cfg["use_color"]:
                    tried.add(blk["id"])      # try another block; on the pickup spot, retry the same one
                continue
            self.action(f"step {i + 1}: placing" + (f" on top, {st['z']:.1f} cm up" if st["z"] > 0 else ""))
            r = self.motion.place(st, g_place)
            if r == "abort":
                return "cancel"
            if r != "ok":
                return "fail"
            self.clock.sleep(0.4)
            ok, err = self._verify(st)
            self.log("placed" if ok else "placed (not confirmed)", step=i, err=err)
            return "ok"
        return "fail"

    def _verify(self, st):
        best = None
        for b in self.active_blocks():
            if self.cfg["use_color"] and (b["color"] != st["color"] or b.get("type") != st["type"]):
                continue
            x, y = b["x"], b["y"]
            if b.get("px") is not None and hasattr(self.source, "calib"):
                p = self.source.calib.pixel_to_table(*b["px"], st["z"] + st["h"])
                if p:
                    x, y = p
            d = math.hypot(x - st["x"], y - st["y"])
            best = d if best is None else min(best, d)
        return (best is not None and best < 1.5), (None if best is None else round(best, 2))

    def close(self):
        self.cancel.set()
        self._quit.set()
        self._vision.join(timeout=1)

"""Corrected moves, pick and place (handbook 2I, adapted for building).

Every move checks the abort signal. If the safety stop fires mid-move,
the move waits until it's safe again and then repeats itself, so a pick or
place resumes where it left off instead of starting over.
"""
import math

from .catalog import fold180


class Motion:
    def __init__(self, cfg, arm, body, catalog, read_claw, get_blocks, abort, wait_resume, log=print):
        self.cfg, self.arm, self.body, self.catalog = cfg, arm, body, catalog
        self.read_claw = read_claw          # () -> {x, y, z, down} or None
        self.get_blocks = get_blocks        # () -> active tracked blocks
        self.abort = abort                  # threading.Event set by the safety check
        self.wait_resume = wait_resume      # () -> True when safe again, False to give up
        self.log = log
        self.clock = arm.clock
        self.roll = 1500
        self.claw = cfg["claw_open"]

    # ---------------------------------------------------------------- helpers
    def base_yaw(self, x, y):
        bx, by = self.cfg["layout"]["base"]
        return math.degrees(math.atan2(x - bx, -(y - by)))

    def roll_for(self, grip_axis, x, y):
        """Wrist-roll pulse that lines the fingers up with `grip_axis` (table deg) at (x, y)."""
        roll_deg = fold180(grip_axis - self.base_yaw(x, y))
        p = 1500 + self.cfg["roll_direction"] * roll_deg * self.cfg["us_per_degree"]
        return int(min(max(p, self.cfg["joint_min"][4]), self.cfg["joint_max"][4]))

    def _move(self, pulses):
        """Move; on a safety stop, wait until safe and send the same move again."""
        while True:
            if self.abort.is_set():
                if not self.wait_resume():
                    return False
                continue
            done = self.arm.move(pulses, abort=self.abort)
            if done:
                return True
            if not self.abort.is_set():
                self.log("move timed out")
                return True

    # ---------------------------------------------------------------- go to point
    def go_to(self, x, y, z, claw=None, roll=None, correct=True):
        """-> "ok" | "unreachable" | "abort" """
        claw = self.claw if claw is None else claw
        correct = correct and self.cfg.get("camera_correct", True)
        roll = self.roll if roll is None else roll
        target = (x, y, z)
        aim = list(target)
        sol = self.body.solve(aim)
        if not sol["reachable"]:
            self.log(f"unreachable ({x:.1f}, {y:.1f}, {z:.1f}): predicted {sol['error']:.1f} cm off")
            return "unreachable"
        for attempt in range(4):
            if not self._move(sol["pulses"] + [roll, claw]):
                return "abort"
            self.claw, self.roll = claw, roll
            if not correct:
                return "ok"
            self.clock.sleep(0.25)
            m = self.read_claw()
            if m is None:
                self.log("claw marker not visible; accepting the move")
                return "ok"
            ex, ey, ez = target[0] - m["x"], target[1] - m["y"], target[2] - m["z"]
            if math.hypot(ex, ey) <= 0.4 and abs(ez) <= 1.0:
                return "ok"
            if attempt == 3:
                self.log(f"still {math.hypot(ex, ey):.1f} cm off after 3 corrections; continuing")
                return "ok"
            aim = [aim[0] + ex, aim[1] + ey, aim[2] + ez]
            sol = self.body.solve(aim)
        return "ok"

    def set_claw(self, pulse):
        t = list(self.arm.targets)
        t[5] = pulse
        ok = self._move(t)
        self.claw = pulse
        return ok

    # ---------------------------------------------------------------- pick
    def grip_for(self, block_yaw, table_grip, place_yaw, tid, pose=0):
        """Pick-time grip axis so the fingers end up along `table_grip` at the place.
        Fingers closing across the block's d side run along block_yaw + 90."""
        # which block axis lines up with the wanted table axis once the block sits at place_yaw
        want_block_axis = "y" if (table_grip == "y") == (int(round(place_yaw)) % 180 == 0) else "x"
        axes = self.catalog.grippable_axes(tid, pose) or ["y"]
        if want_block_axis not in axes:
            want_block_axis = axes[0]
        return fold180(block_yaw + (90.0 if want_block_axis == "y" else 0.0))

    def pick(self, blk, grip_axis):
        """blk: tracked block {x, y, type, color, z?}. -> "ok" | "miss" | "unreachable" | "abort" """
        z0 = float(blk.get("z") or 0.0)
        h = self.catalog.height(blk["type"], blk.get("pose", 0))
        dx, dy = self.cfg.get("pick_offset", [0.0, 0.0])      # hand-tuned camera bias, cm
        x, y = blk["x"] + dx, blk["y"] + dy
        self.log(f"block seen at ({blk['x']:.1f}, {blk['y']:.1f}); reaching for ({x:.1f}, {y:.1f}) "
                 f"[pick_offset {dx:+.1f}, {dy:+.1f}]")
        roll = self.roll_for(grip_axis, x, y)
        open_, closed = self.cfg["claw_open"], self.cfg["claw_closed"]
        hover = self.cfg.hover_z(z0, h)
        r = self.go_to(x, y, hover, claw=open_, roll=roll)
        if r != "ok":
            return r
        r = self.go_to(x, y, self.cfg.grasp_z(z0, h), claw=open_, roll=roll)
        if r != "ok":
            return r
        if self.cfg["force_sensors"]:
            p = open_
            step = 30 if closed > open_ else -30
            while (p - closed) * step < 0:
                p += step
                self.set_claw(p)
                if self.arm.holding():
                    self.set_claw(p + 2 * step)
                    break
        else:
            self.set_claw(closed)
        r = self.go_to(x, y, hover, claw=self.claw, roll=roll, correct=False)
        if r != "ok":
            return r
        # verify
        if self.cfg["force_sensors"]:
            ok = bool(self.arm.holding())
        else:
            self.clock.sleep(0.3)
            same = (lambda b: True) if not self.cfg["use_color"] else (
                lambda b: b["color"] == blk["color"] and b.get("type") == blk.get("type"))
            ok = not any(same(b) and math.hypot(b["x"] - x, b["y"] - y) < 2.5 for b in self.get_blocks())
        if not ok:
            self.set_claw(open_)
            return "miss"
        return "ok"

    # ---------------------------------------------------------------- place
    def place(self, step, grip_axis_at_place):
        x, y, z0, h = step["x"], step["y"], step["z"], step["h"]
        roll = self.roll_for(grip_axis_at_place, x, y)
        hover = self.cfg.hover_z(z0, h)
        r = self.go_to(x, y, hover, roll=roll)
        if r != "ok":
            return r
        r = self.go_to(x, y, self.cfg.grasp_z(z0, h) + 0.3, roll=roll)   # release a hair above
        if r != "ok":
            return r
        self.set_claw(self.cfg["claw_open"])
        self.clock.sleep(0.2)
        return self.go_to(x, y, hover, roll=roll, correct=False)

    def home(self):
        return self._move(list(self.cfg["ready"]))

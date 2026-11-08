"""Corrected moves, pick and place (handbook 2I, adapted for building),
plus the short acknowledgement gestures in gestures.py.

Every move checks the abort signal. If the safety stop fires mid-move,
the move waits until it's safe again and then repeats itself, so a pick or
place resumes where it left off instead of starting over.
"""
import math

from . import gestures
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
        open_, closed = self.cfg["claw_open"], self.cfg["claw_closed"]
        hover = self.cfg.hover_z(z0, h)
        if self.cfg.get("pick_track", True):
            r = self._look_and_follow(blk, x, y, hover, grip_axis, open_)
            if r[0] != "ok":
                return r[0]
            _, x, y, grip_axis = r
        roll = self.roll_for(grip_axis, x, y)
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
            # A long block in the claw (roof, plank) sticks out past the blanked circle
            # around the claw and still looks like "a block on the pick spot". Slide
            # toward the build strip first: a held block comes along, a missed one stays.
            x0, x1, y0, y1 = self.cfg["layout"]["build_area"]
            vx, vy = (x0 + x1) / 2 - x, (y0 + y1) / 2 - y
            n = math.hypot(vx, vy) or 1.0
            moved = self.go_to(x + 4 * vx / n, y + 4 * vy / n, hover, claw=self.claw, roll=roll,
                               correct=False) == "ok"
            self.clock.sleep(0.3)
            same = (lambda b: True) if not self.cfg["use_color"] else (
                lambda b: b["color"] == blk["color"] and b.get("type") == blk.get("type"))
            near = 2.0 if moved else 2.5
            ok = not any(same(b) and math.hypot(b["x"] - x, b["y"] - y) < near for b in self.get_blocks())
        if not ok:
            self.set_claw(open_)
            return "miss"
        return "ok"

    # ---------------------------------------------------------------- live tracking
    def _locate(self, blk, x, y, radius=10.0):
        """Fresh camera fix on the block we're after: the nearest loose block of the
        same kind within `radius` cm of where we last saw it (it may have been bumped)."""
        best = None
        for b in self.get_blocks():
            if b.get("zone") == "build" or self.cfg.in_build(b["x"], b["y"]):
                continue
            if self.cfg["use_color"] and (b["color"] != blk.get("color") or b.get("type") != blk.get("type")):
                continue
            d = math.hypot(b["x"] - x, b["y"] - y)
            if d <= radius and (best is None or d < best[0]):
                best = (d, b)
        return None if best is None else best[1]

    def _look_and_follow(self, blk, x, y, hover, grip_axis, claw):
        """Stop short of the block where the camera sees both it and the claw (right
        above it, the claw hides it), take a fresh fix, and follow the block if it
        moved. -> ("ok", x, y, grip_axis) | ("moved"|"unreachable"|"abort",)"""
        stand = self.cfg.get("pick_look_cm", 7.0)
        yaw = blk.get("yaw", 0.0)
        dx, dy = self.cfg.get("pick_offset", [0.0, 0.0])      # fixes are raw camera positions
        for look in range(3):
            bx, by = self.cfg["layout"]["base"]
            vx, vy = bx - x, by - y                        # stop short on the arm's side: links stay out of view
            n = math.hypot(vx, vy) or 1.0
            sx, sy = x + stand * vx / n, y + stand * vy / n
            if not self.body.solve([sx, sy, hover])["reachable"]:
                return ("ok", x, y, grip_axis)             # can't stand off here: go straight in
            r = self.go_to(sx, sy, hover, claw=claw, roll=self.roll_for(grip_axis, x, y))
            if r != "ok":
                return (r,)
            self.clock.sleep(self.cfg.get("pick_look_s", 0.6))   # a few fresh frames for the tracker
            fix = self._locate(blk, x - dx, y - dy)
            if fix is None:
                self.log(f"lost the block near ({x - dx:.1f}, {y - dy:.1f}); looking again")
                return ("moved",)
            moved = math.hypot(fix["x"] + dx - x, fix["y"] + dy - y)
            turn = fold180(fix.get("yaw", yaw) - yaw)
            if moved <= 0.6 and abs(turn) <= 8:
                return ("ok", x, y, grip_axis)
            self.log(f"block moved {moved:.1f} cm, turned {turn:+.0f} deg; following it")
            x, y, yaw = fix["x"] + dx, fix["y"] + dy, fix.get("yaw", yaw)
            grip_axis = fold180(grip_axis + turn)
        return ("ok", x, y, grip_axis)

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

    # ---------------------------------------------------------------- gestures
    def carrying(self):
        """True when the claw may have a block in it. Gestures must never risk
        shaking one loose, so they refuse while this is true."""
        held = self.arm.holding()
        if held is not None:                       # force sensors fitted: they know
            return held
        open_, closed = self.cfg["claw_open"], self.cfg["claw_closed"]
        return abs(self.claw - open_) > abs(closed - open_) / 2

    def nod(self):
        """-> "ok" | "busy" | "abort" (see gestures.run)"""
        return gestures.nod(self)

    def refuse(self):
        return gestures.refuse(self)

    def listen(self):
        return gestures.listen(self)

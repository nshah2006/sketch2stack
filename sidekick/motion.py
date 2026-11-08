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
        self.obstacles = lambda: []         # builder sets: [(x, y, top cm)] the claw must not sweep through
        self.carry_h = 0.0                  # height of the block in the claw (it hangs below the tips)

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
    def _transit(self, x, y, z, claw, roll):
        """Long moves: rise above everything along the way first. A straight joint move
        can dip the claw (or the block it carries) through a tower it passes."""
        if not self.cfg.get("transit_lift", True):
            return "ok"
        try:
            cx, cy, cz = (float(v) for v in self.body.forward(list(self.arm.targets[:4]))[0][:3])
        except Exception:
            return "ok"
        if math.hypot(x - cx, y - cy) < self.cfg.get("transit_min_cm", 5.0):
            return "ok"
        margin = self.cfg.get("transit_margin_cm", 4.0)
        top = 0.0
        for ox, oy, otop in self.obstacles():
            if _seg_dist((ox, oy), (cx, cy), (x, y)) < margin:
                top = max(top, otop)
        need = top + self.cfg.get("transit_clearance", 1.5) + self.carry_h / 2
        low = max(z, cz)
        if need <= low + 0.3:
            return "ok"                                 # already high enough the whole way
        for zz in (need, need - 1.5, need - 3.0):
            if zz <= low:
                break
            if self.body.solve([cx, cy, zz])["reachable"] and self.body.solve([x, y, zz])["reachable"]:
                self.log(f"lifting to {zz:.1f} cm to clear {top:.1f} cm along the way")
                r = self.go_to(cx, cy, zz, claw=claw, roll=roll, correct=False)
                if r != "ok":
                    return r
                return self.go_to(x, y, zz, claw=claw, roll=roll, correct=False)
        self.log(f"can't lift above {top:.1f} cm here; going the direct way")
        return "ok"

    def go_to(self, x, y, z, claw=None, roll=None, correct=True):
        """-> "ok" | "unreachable" | "abort" """
        claw = self.claw if claw is None else claw
        correct = correct and self.cfg.get("camera_correct", True)
        roll = self.roll if roll is None else roll
        r = self._transit(x, y, z, claw, roll)
        if r != "ok":
            return r
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
        before = len(self._loose_near(blk, x - dx, y - dy))     # seen with the claw out of the way
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
            # Count the loose blocks around the pick spot with the claw moved off to the
            # side (right above, the claw hides them; a long block in the claw would
            # also look like one still lying there). A real pick leaves one fewer, even
            # if the block got pushed before the claw closed.
            stand = self._stand_point(x, y, hover)
            if stand is not None:
                self.go_to(*stand, hover, claw=self.claw, roll=roll, correct=False)
            self.clock.sleep(self.cfg.get("pick_look_s", 0.6))
            after = len(self._loose_near(blk, x - dx, y - dy))
            ok = after < before if before else after == 0
            if not ok:
                self.log(f"pick check: {before} block(s) near the spot before, {after} after: missed")
        if not ok:
            self.set_claw(open_)
            return "miss"
        self.carry_h = h
        return "ok"

    # ---------------------------------------------------------------- live tracking
    def _loose_near(self, blk, x, y, radius=6.0):
        """Loose blocks of the same kind within `radius` cm (never the ones already built)."""
        out = []
        for b in self.get_blocks():
            if b.get("zone") == "build" or self.cfg.in_build(b["x"], b["y"]):
                continue
            if self.cfg["use_color"] and (b["color"] != blk.get("color") or b.get("type") != blk.get("type")):
                continue
            if math.hypot(b["x"] - x, b["y"] - y) <= radius:
                out.append(b)
        return out

    def _stand_point(self, x, y, z):
        """A reachable point `pick_look_cm` from (x, y) from where the camera sees the
        spot clear of the claw: toward the base first (links out of view), then
        toward the build strip, then either side."""
        stand = self.cfg.get("pick_look_cm", 10.0)
        bx, by = self.cfg["layout"]["base"]
        x0, x1, y0, y1 = self.cfg["layout"]["build_area"]
        dirs = []
        for vx, vy in ((bx - x, by - y), ((x0 + x1) / 2 - x, (y0 + y1) / 2 - y)):
            n = math.hypot(vx, vy) or 1.0
            dirs.append((vx / n, vy / n))
        ux, uy = dirs[0]
        dirs += [(-uy, ux), (uy, -ux), ((ux - uy) / 1.414, (uy + ux) / 1.414), ((ux + uy) / 1.414, (uy - ux) / 1.414)]
        for ux, uy in dirs:
            sx, sy = x + stand * ux, y + stand * uy
            if self.cfg.in_work_area(sx, sy) and self.body.solve([sx, sy, z])["reachable"]:
                return sx, sy
        return None

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
        # the camera blanks ~5 cm around the claw marker: stand off far enough that the
        # whole block is outside that circle, or its outline (and centre) comes out clipped
        yaw = blk.get("yaw", 0.0)
        dx, dy = self.cfg.get("pick_offset", [0.0, 0.0])      # fixes are raw camera positions
        for look in range(3):
            stand = self._stand_point(x, y, hover)
            if stand is None:
                self.log("no place to look from here; going straight in")
                return ("ok", x, y, grip_axis)
            r = self.go_to(*stand, hover, claw=claw, roll=self.roll_for(grip_axis, x, y))
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
        self.carry_h = 0.0
        self.clock.sleep(0.2)
        r = self.go_to(x, y, hover, roll=roll, correct=False)
        if r == "ok" and self.cfg.get("pick_track", True):
            stand = self._stand_point(x, y, hover)      # step aside so the camera can check the placement
            if stand is not None:
                self.go_to(*stand, hover, roll=roll, correct=False)
                self.clock.sleep(self.cfg.get("pick_look_s", 0.6))
        return r

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

    def express(self, name, **kw):
        """Any emotion in gestures.EMOTIONS ("happy", "confused", "look_at", x=.., y=..)."""
        return gestures.express(self, name, **kw)

    def __getattr__(self, name):
        # Builder._gesture("happy") looks emotions up by name
        if name in gestures.EMOTIONS:
            return lambda **kw: gestures.express(self, name, **kw)
        raise AttributeError(name)


def _seg_dist(p, a, b):
    """2-D distance from point p to segment a-b."""
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    t = ((p[0] - ax) * vx + (p[1] - ay) * vy) / (vx * vx + vy * vy or 1.0)
    t = min(1.0, max(0.0, t))
    return math.hypot(p[0] - (ax + t * vx), p[1] - (ay + t * vy))

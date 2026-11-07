"""Level 1 simulator (handbook Phase 2S).

Plugs in at the same interfaces as the real hardware:
  * FakeSerial + FirmwareEmulator speak the exact serial protocol, so arm.py
    is unchanged.
  * SimCamera produces the same Observation objects that perception.py
    produces from real images, so everything above perception is unchanged.

The arm model is deliberately imperfect (gain/offset errors, backlash,
droop, speed limit) so the learning code is tested on a flawed arm.
"""
import math
import queue
import threading
from dataclasses import dataclass

import numpy as np

from .clock import SimClock
from .perception import Observation

DEG_PER_US = 0.135


# ===================================================================== firmware
class FirmwareEmulator:
    """Python copy of sidekick_firmware.ino. Same rules, same timing."""

    HARD_MIN, HARD_MAX = 600, 2400
    TICK, REPORT, WATCHDOG = 0.020, 0.040, 1.0

    def __init__(self, clock):
        self.clock = clock
        now = clock.time()
        self.cur = [1500] * 6
        self.target = [1500] * 6
        self.jmin = [self.HARD_MIN] * 6
        self.jmax = [self.HARD_MAX] * 6
        self.attached = [False] * 6
        self.step_us = 8
        self.frozen = False
        self.led = 0
        self.analog = [0, 0, 0]
        self.last_msg = now
        self.next_tick = now
        self.next_report = now
        self.busy_until = now          # emulates the blocking 400 ms attach delays
        self.attach_plan = []          # (time, joint)
        self.inbox = []
        self.out = queue.Queue()
        self.lock = threading.Lock()

    # ---- input from the fake port
    def receive(self, line):
        with self.lock:
            self.inbox.append(line)

    def _clamp(self, i, v):
        return min(max(int(v), self.jmin[i]), self.jmax[i])

    @staticmethod
    def _ints(parts, want):
        if len(parts) != want:
            return None
        try:
            return [int(p) for p in parts]
        except ValueError:
            return None

    def _handle(self, line, now):
        self.frozen = False
        self.last_msg = now
        cmd, rest = line[0], line[1:].split()
        if line == "?":
            self.out.put("OK sidekick 1")
        elif cmd == "P":
            v = self._ints(rest, 6)
            if v:
                for i in range(6):
                    if not self.attached[i]:
                        self.cur[i] = self.target[i] = self._clamp(i, v[i])
        elif line == "A":
            t = now
            for i in range(6):
                if not self.attached[i]:
                    t += 0.4
                    self.attach_plan.append((t, i))
            self.busy_until = t
        elif line == "D":
            self.attached = [False] * 6
        elif cmd == "J":
            v = self._ints(rest, 6)
            if v:
                self.target = [self._clamp(i, v[i]) for i in range(6)]
        elif line == "S":
            self.target = list(self.cur)
        elif cmd == "C":
            v = self._ints(rest, 3)
            if v and 0 <= v[0] < 6:
                lo, hi = max(v[1], self.HARD_MIN), min(v[2], self.HARD_MAX)
                if lo < hi:
                    i = v[0]
                    self.jmin[i], self.jmax[i] = lo, hi
                    self.target[i] = self._clamp(i, self.target[i])
                    if not self.attached[i]:
                        self.cur[i] = self._clamp(i, self.cur[i])
        elif cmd == "V":
            v = self._ints(rest, 1)
            if v and 1 <= v[0] <= 30:
                self.step_us = v[0]
        elif cmd == "L":
            v = self._ints(rest, 1)
            if v and 0 <= v[0] <= 4:
                self.led = v[0]
        # "H" and malformed lines: alive, nothing else

    def update(self, now):
        """Advance to `now`: attach plan, input, watchdog, ticks, reports."""
        while self.attach_plan and self.attach_plan[0][0] <= now:
            _, i = self.attach_plan.pop(0)
            self.attached[i] = True
            if not self.attach_plan:
                self.last_msg = self.busy_until
        if now < self.busy_until:
            return                      # firmware is inside delay(400): nothing runs
        with self.lock:
            lines, self.inbox = self.inbox, []
        for line in lines:
            if line:
                self._handle(line, now)
        if not self.frozen and now - self.last_msg > self.WATCHDOG:
            self.target = list(self.cur)
            self.led = 4
            self.frozen = True
        while self.next_tick <= now:
            self.next_tick += self.TICK
            for i in range(6):
                d = max(-self.step_us, min(self.step_us, self.target[i] - self.cur[i]))
                self.cur[i] += d
        while self.next_report <= now:
            self.next_report += self.REPORT
            moving = int(self.cur != self.target)
            a0, a1, a2 = (int(a) for a in self.analog)
            self.out.put(f"F {a0} {a1} {a2} {moving} {int(all(self.attached))}")


class FakeSerial:
    """In-memory serial port in front of the emulator (pyserial-like)."""

    def __init__(self, emulator, clock):
        self.emu = emulator
        self.clock = clock
        self._buf = ""
        self.closed = False

    def write(self, data):
        self._buf += data.decode()
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.emu.receive(line.strip())

    def readline(self):
        try:
            return (self.emu.out.get(timeout=0.1) + "\n").encode()
        except queue.Empty:
            return b""

    def close(self):
        self.closed = True


# ===================================================================== arm model
class ArmModel:
    """Pulse widths -> claw pose, with realistic flaws."""

    def __init__(self, cfg, rng):
        g = cfg["sim_arm"]
        self.base = np.array(cfg["layout"]["base"], dtype=float)
        self.h0 = g["shoulder_height"]
        self.l1, self.l2 = g["upper"], g["fore"]
        self.lm, self.lf = g["marker_past_wrist"], g["finger_past_wrist"]
        self.gain = rng.uniform(0.97, 1.03, size=4)
        self.offset = rng.uniform(-4.0, 4.0, size=4)
        self.backlash = 0.5
        self.droop = 0.02
        self.max_speed = 60.0 / 0.2          # deg per second
        self.phys = None                     # physical joint angles, deg
        self.claw_pulse = 1500

    def commanded_deg(self, pulses):
        p = np.asarray(pulses[:4], dtype=float)
        return (p - 1500.0) * DEG_PER_US * self.gain + self.offset

    def update(self, pulses, dt):
        cmd = self.commanded_deg(pulses)
        if self.phys is None:
            self.phys = cmd.copy()
        # backlash: the shaft only moves once the play is taken up, so it ends
        # up half the play short of the command, on the side it came from.
        half = self.backlash / 2
        err = cmd - self.phys
        want = np.where(err > half, cmd - half, np.where(err < -half, cmd + half, self.phys))
        # speed limit
        self.phys = self.phys + np.clip(want - self.phys, -self.max_speed * dt, self.max_speed * dt)
        self.claw_pulse = pulses[5]

    def pose_from_angles(self, ang):
        a0, a1, a2, a3 = np.radians(ang)
        d = np.array([math.sin(a0), -math.cos(a0)])        # base faces the human at 1500
        s1, s12, s123 = a1, a1 + a2, a1 + a2 + a3
        sh = np.array([0.0, self.h0])                       # (reach, height)
        el = sh + self.l1 * np.array([math.sin(s1), math.cos(s1)])
        wr = el + self.l2 * np.array([math.sin(s12), math.cos(s12)])
        u = np.array([math.sin(s123), math.cos(s123)])
        mk = wr + self.lm * u
        fg = wr + self.lf * u

        def to3(p):
            r = p[0]
            xy = self.base + r * d
            z = p[1] - self.droop * abs(r)
            return np.array([xy[0], xy[1], z])

        down = -u[1]   # vertical part of the marker's facing direction
        normal = np.array([-u[0] * d[0], -u[0] * d[1], -u[1]])   # marker faces away from the fingers
        return {"marker": to3(mk), "finger": to3(fg), "wrist": to3(wr),
                "elbow": to3(el), "down": float(down), "normal": normal}

    def pose(self):
        return self.pose_from_angles(self.phys)


# ===================================================================== blocks
@dataclass
class Block:
    id: int
    type: str
    color: str
    x: float
    y: float
    yaw: float = 0.0        # angle of the block's w side, degrees
    z: float = 0.0          # bottom height, cm
    w: float = 3.0          # cm along its own x
    d: float = 3.0
    h: float = 3.0
    round_: bool = False
    pose: int = 0
    held: bool = False
    rel: float = 0.0        # yaw relative to the claw's grip axis while held

    def contains(self, x, y, margin=0.0):
        a = math.radians(self.yaw)
        dx, dy = x - self.x, y - self.y
        u = dx * math.cos(a) + dy * math.sin(a)
        v = -dx * math.sin(a) + dy * math.cos(a)
        return abs(u) <= self.w / 2 + margin and abs(v) <= self.d / 2 + margin


# ===================================================================== person
class SimPerson:
    """Feeds blocks into the supply zones on request, and sometimes reaches
    into the work area (to test the safety freeze)."""

    def __init__(self, world, rng, reach_rate=0.0, pause_cm=5.0):
        self.w = world
        self.rng = rng
        self.reach_rate = reach_rate          # random reaches per second (safety tests)
        self.pause_cm = pause_cm              # a person doesn't push into the claw
        self.requests = []                    # (type, color) the builder asked for
        self.state = "away"
        self.hand = None
        self.open = True
        self.path = None
        self.t_path = 0.0
        self.dur = 1.0
        self.home = None
        self.carry = None
        self.drop_at = None
        self.reaches = 0
        self.blocked_for = 0.0
        self.blocked_total = 0.0
        self.waiting_for_spot = 0.0

    def request(self, tid, color, pose=0):
        self.requests.append((tid, color, pose))

    def _start(self, end, state):
        start = np.asarray(self.hand, float)
        end = np.asarray(end, float)
        v = end - start
        n = np.array([-v[1], v[0]]) / (np.linalg.norm(v) + 1e-9)
        ctrl = (start + end) / 2 + n * self.rng.uniform(-5, 5)
        s = np.linspace(0, 1, 30)[:, None]
        self.path = (1 - s) ** 2 * start + 2 * (1 - s) * s * ctrl + s ** 2 * end
        self.t_path, self.dur, self.state = 0.0, self.rng.uniform(0.6, 1.2), state

    def _pos_at(self, f):
        idx = f * (len(self.path) - 1)
        i = int(min(idx, len(self.path) - 2))
        a = idx - i
        return self.path[i] * (1 - a) + self.path[i + 1] * a

    def step(self, dt, now):
        if self.state == "away":
            if self.requests:
                tid, color, pose = self.requests.pop(0)
                spot = self.w.free_supply_spot() if self.w.cfg["use_color"] else self.w.pickup_spot()
                if spot is None:
                    self.requests.insert(0, (tid, color, pose))
                    self.waiting_for_spot += dt
                    if self.waiting_for_spot > 3.0 and not self.w.cfg["use_color"]:
                        self.w.clear_pickup()          # a person would just take the old block off
                        self.waiting_for_spot = 0.0
                    return
                self.waiting_for_spot = 0.0
                self.carry, self.drop_at, self.blocked_total = (tid, color, pose), spot, 0.0
                self.home = np.array([self.rng.uniform(10, 40), self.rng.uniform(-10, 0)])
                self.hand = self.home.copy()
                self.reaches += 1
                self._start(spot, "feed")
            elif self.reach_rate and self.rng.random() < self.reach_rate * dt:
                self.home = np.array([self.rng.uniform(10, 40), self.rng.uniform(-10, 0)])
                self.hand = self.home.copy()
                self.reaches += 1
                b = self.w.cfg["layout"]["build_area"]
                self._start((self.rng.uniform(b[0], b[1]), self.rng.uniform(b[2] - 3, b[3])), "poke")
            return
        claw = self.w.truth()
        if claw["finger"][2] < 20 and self.state != "poke":
            nxt = self._pos_at(min(1.0, (self.t_path + dt) / self.dur))
            if np.hypot(*(nxt - claw["finger"][:2])) < self.pause_cm:
                self.blocked_for += dt                 # wait for the arm...
                self.blocked_total += dt
                if self.blocked_total > 6.0:
                    if self.state == "feed":
                        self.requests.insert(0, self.carry)  # give up for now; try again later
                        self.carry = None
                    self.blocked_total = 0.0
                    self._start(self.home, "back")
                    return
                if self.blocked_for > 1.5:             # ...then walk around it
                    self.blocked_for = 0.0
                    end = self.path[-1]
                    away = self.hand - claw["finger"][:2]
                    away = away / (np.linalg.norm(away) + 1e-9)
                    start = np.asarray(self.hand, float)
                    ctrl = start + away * 12
                    s_ = np.linspace(0, 1, 30)[:, None]
                    self.path = (1 - s_) ** 2 * start + 2 * (1 - s_) * s_ * ctrl + s_ ** 2 * end
                    self.t_path = 0.0
                return
        self.blocked_for = 0.0
        self.t_path += dt
        f = min(1.0, self.t_path / self.dur)
        self.hand = self._pos_at(f) + self.rng.normal(0, 0.3, 2)
        if f < 1.0:
            return
        if self.state == "feed":
            tid, color, pose = self.carry
            self.w.add_block(tid, color, *self.drop_at, yaw=float(self.rng.uniform(-30, 30)), pose=pose)
            self.carry = None
            self._start(self.home, "back")
        elif self.state == "poke":
            self.state, self.palm_until = "linger", now + 1.5     # hold still a moment, then leave
        elif self.state == "linger":
            if now >= self.palm_until:
                self._start(self.home, "back")
        elif self.state == "back":
            self.state, self.hand = "away", None


# ===================================================================== world
class World:
    """Arm + blocks + person + camera, stepped at 60 Hz in one thread."""

    DT = 1 / 60

    def __init__(self, cfg, catalog=None, speed=None, seed=None, camera_fps=60, reach_rate=0.0):
        from .catalog import Catalog
        self.cfg = cfg
        self.catalog = catalog or Catalog.load()
        seed = cfg.get("sim_seed") if seed is None else seed
        self.rng = np.random.default_rng(seed)
        self.clock = SimClock(speed if speed is not None else cfg["sim_speed"])
        self.emu = FirmwareEmulator(self.clock)
        self.arm = ArmModel(cfg, self.rng)
        self.blocks = []
        self._next_id = 0
        self.person = SimPerson(self, self.rng, reach_rate=reach_rate)
        self.camera_fps = camera_fps
        self.lock = threading.RLock()
        self._frames = queue.Queue(maxsize=4)
        self._stop = threading.Event()
        self._thread = None
        self._t = self.clock.time()
        self._next_frame = self._t
        self._closed_before = False
        self.contacts = 0
        self._in_contact = False
        self.table_hits = 0

    # ---- wiring
    def serial_port(self):
        return FakeSerial(self.emu, self.clock)

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    close = stop

    def _run(self):
        while not self._stop.is_set():
            now = self.clock.time()
            while self._t + self.DT <= now:
                self._t += self.DT
                self._step(self._t)
            self.clock.sleep(self.DT / 2)

    # ---- claw geometry
    def _claw_fraction(self):
        o, c = self.cfg["claw_open"], self.cfg["claw_closed"]
        return (self.emu.cur[5] - o) / (c - o) if c != o else 0.0

    def grip_axis(self):
        """Table angle (deg) of the line the fingers close along."""
        roll = (self.emu.cur[4] - 1500) * DEG_PER_US * self.cfg["roll_direction"]
        return float(self.arm.phys[0] + roll) if self.arm.phys is not None else 0.0

    def _covered(self, b):
        return any(o is not b and not o.held and abs(o.z - (b.z + b.h)) < 0.4 and o.contains(b.x, b.y, -0.3)
                   for o in self.blocks)

    def _rest_height(self, b):
        """Where a released block comes to rest: on the highest block under its footprint."""
        tops = []
        a = math.radians(b.yaw)
        pts = [(b.x + u * math.cos(a) - v * math.sin(a), b.y + u * math.sin(a) + v * math.cos(a))
               for u in (-b.w / 2 + 0.3, 0, b.w / 2 - 0.3) for v in (-b.d / 2 + 0.3, 0, b.d / 2 - 0.3)]
        for o in self.blocks:
            if o is b or o.held:
                continue
            if any(o.contains(px, py) for px, py in pts):
                tops.append(o.z + o.h)
        return max(tops) if tops else 0.0

    def _step(self, t):
        with self.lock:
            self.emu.update(t)
            self.arm.update(self.emu.cur, self.DT)
            pose = self.arm.pose()
            fx, fy, fz = pose["finger"]
            if fz < -0.3:
                self.table_hits += 1
            frac = self._claw_fraction()
            closed_now, open_now = frac >= 0.9, frac <= 0.5
            if closed_now and not self._closed_before:
                g = self.grip_axis()
                for b in self.blocks:
                    if b.held or self._covered(b):
                        continue
                    if math.hypot(b.x - fx, b.y - fy) > 1.0 or abs(fz - (b.z + b.h / 2)) > 1.0:
                        continue
                    # fingers must close across a side the claw can span, roughly square to it
                    ok = False
                    if b.round_:
                        ok = b.d <= self.catalog.max_grip + 0.2
                    for side_angle, axis in ((b.yaw + 90, "y"), (b.yaw, "x")):
                        diff = abs(((g - side_angle) + 90) % 180 - 90)
                        if diff <= 20 and axis in self.catalog.grippable_axes(b.type, b.pose):
                            ok = True
                    if ok:
                        b.held, b.rel = True, b.yaw - g
                        break
            if open_now and self._closed_before:
                for b in self.blocks:
                    if b.held:
                        b.held = False
                        b.x, b.y = float(fx), float(fy)
                        b.yaw = ((self.grip_axis() + b.rel) + 90) % 180 - 90
                        b.z = self._rest_height(b)
            if closed_now:
                self._closed_before = True
            elif open_now:
                self._closed_before = False
            for b in self.blocks:
                if b.held:
                    b.x, b.y = float(fx), float(fy)
                    b.yaw = ((self.grip_axis() + b.rel) + 90) % 180 - 90
            self.person.step(self.DT, t)
            hand = self.person.hand
            contact = False
            if hand is not None:
                hp = np.array([hand[0], hand[1], self.cfg["hand_height"]])
                contact = _seg_dist(hp, pose["wrist"], pose["finger"]) < 3.0
            if contact and not self._in_contact:
                self.contacts += 1
            self._in_contact = contact
            if t >= self._next_frame:
                self._next_frame += 1.0 / self.camera_fps
                obs = self._observe(t, pose)
                if self._frames.full():
                    try:
                        self._frames.get_nowait()
                    except queue.Empty:
                        pass
                self._frames.put(obs)

    def _observe(self, t, pose):
        rng = self.rng
        claw = None
        if pose["down"] > 0.3:
            m = pose["marker"] + rng.normal(0, 0.2, 3)
            nrm = pose["normal"] + rng.normal(0, 0.01, 3)
            nrm = nrm / np.linalg.norm(nrm)
            claw = {"x": float(m[0]), "y": float(m[1]), "z": float(m[2]),
                    "nx": float(nrm[0]), "ny": float(nrm[1]), "down": float(nrm[2])}
        dets = []
        for b in self.blocks:
            if b.held or self._covered(b) or rng.random() < 0.02:
                continue
            L, S = max(b.w, b.d), min(b.w, b.d)
            long_axis = b.yaw if b.w >= b.d else b.yaw + 90
            dets.append({"color": b.color if self.cfg["use_color"] else "any",
                         "x": b.x + rng.normal(0, 0.3), "y": b.y + rng.normal(0, 0.3),
                         "angle": float(((long_axis + rng.normal(0, 2)) + 90) % 180 - 90),
                         "size": [L + rng.normal(0, 0.15), S + rng.normal(0, 0.15)],
                         "round": b.round_, "z": b.z})
        hands = []
        if self.person.hand is not None:
            hx, hy = self.person.hand + rng.normal(0, 0.3, 2)
            hands.append({"x": float(hx), "y": float(hy), "open": bool(self.person.open)})
        return Observation(t=t, claw=claw, detections=dets, hands=hands)

    # ---- API used by the builder, tests and the viewer
    def truth(self):
        return self.arm.pose()

    def read(self, timeout=1.0):
        try:
            return self._frames.get(timeout=self.clock.real(timeout))
        except queue.Empty:
            return None

    def add_block(self, tid, color, x, y, yaw=0.0, z=0.0, pose=0):
        w, d, h = self.catalog.size(tid, pose)
        with self.lock:
            b = Block(self._next_id, tid, color, float(x), float(y), float(yaw), float(z), w, d, h,
                      self.catalog.round_(tid), int(pose))
            self._next_id += 1
            self.blocks.append(b)
        return b

    def pickup_spot(self):
        """The taped pickup square, if nothing is on it."""
        px, py = self.cfg["layout"]["pickup"]
        if any(math.hypot(b.x - px, b.y - py) < 3.0 and not b.held for b in self.blocks):
            return None
        return (px + float(self.rng.normal(0, 0.4)), py + float(self.rng.normal(0, 0.4)))

    def clear_pickup(self):
        px, py = self.cfg["layout"]["pickup"]
        with self.lock:
            self.blocks = [b for b in self.blocks if b.held or math.hypot(b.x - px, b.y - py) >= 3.0]

    def clear_blocks(self):
        with self.lock:
            self.blocks = [b for b in self.blocks if b.held]

    def free_supply_spot(self, spacing=5.5):
        """A reachable, empty spot in a supply zone."""
        for _ in range(400):
            name = list(self.cfg["layout"]["supply"])[self.rng.integers(len(self.cfg["layout"]["supply"]))]
            x0, x1, y0, y1 = self.cfg["layout"]["supply"][name]
            x, y = self.rng.uniform(x0 + 1.6, x1 - 1.6), self.rng.uniform(y0 + 1.6, y1 - 1.6)
            if all(math.hypot(x - b.x, y - b.y) >= spacing for b in self.blocks):
                return (float(x), float(y))
        return None

    def fill_supply(self, items):
        """items: [(type, color)] placed directly (no person) where they fit.
        Colorless mode only uses the pickup spot, so nothing is pre-placed."""
        if not self.cfg["use_color"]:
            return []
        placed = []
        for tid, color in items:
            spot = self.free_supply_spot()
            if spot is None:
                break
            placed.append(self.add_block(tid, color, *spot, yaw=float(self.rng.uniform(-30, 30))))
        return placed


def _seg_dist(p, a, b):
    ab = b - a
    t = float(np.clip(np.dot(p - a, ab) / (np.dot(ab, ab) + 1e-9), 0, 1))
    return float(np.linalg.norm(p - (a + t * ab)))


def make_world(cfg, catalog=None, speed=None, seed=None, camera_fps=60, reach_rate=0.0):
    return World(cfg, catalog=catalog, speed=speed, seed=seed, camera_fps=camera_fps,
                 reach_rate=reach_rate).start()

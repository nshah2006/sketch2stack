"""Driver for the Hiwonder xArm 1S (bus servos, its own controller board, USB HID).

Same interface as arm.Arm, so the rest of the stack doesn't change. Joint
values stay in our microseconds (500-2500); the xArm uses units 0-1000
(500 = center, 4 units per degree): units = (us - 500) / 2.

Needs: pip install xarm hidapi   (hidapi, not hid)
Select it with "arm_type": "xarm" in sidekick_data/config.json.
"""
import threading

from .clock import RealClock

DEFAULT_PARK = [1500, 1500, 1500, 1500, 1500, 1300]


class ArmError(RuntimeError):
    pass


def to_units(us):
    return int(round(min(max((us - 500) / 2.0, 0), 1000)))


def to_us(units):
    return int(round(units * 2 + 500))


class XArm:
    def __init__(self, cfg, clock=None, verbose=True):
        self.cfg = cfg
        self.clock = clock or RealClock()
        self.verbose = verbose
        self.ids = cfg["xarm_ids"]          # our joint i -> xArm servo id
        self.port_name = None
        self.dev = None
        self.lock = threading.Lock()
        self._halt = threading.Event()
        self.targets = list(cfg["home"])
        self.step_us = cfg["step_us"]
        self.force = [0, 0]
        self.battery_v = None
        self.moving = False
        self.attached = False
        self.report_time = -1.0
        self.reports = 0

    # ------------------------------------------------------------ connect
    def connect(self):
        try:
            import xarm
        except ImportError as e:
            raise ArmError("xArm needs `pip install xarm hidapi` (hidapi, not hid).") from e
        try:
            self.dev = xarm.Controller("USB")
        except Exception as e:
            raise ArmError(f"No xArm on USB ({e}). Power adapter on? USB data cable plugged in?") from e
        self.port_name = "xArm USB"
        self.battery_v = self._call(self.dev.getBatteryVoltage)
        if self.battery_v is not None and self.battery_v < 6.0:
            raise ArmError(f"xArm supply reads {self.battery_v:.1f} V. Plug in and switch on the 7.5 V adapter.")
        return self

    def _call(self, fn, *a, **k):
        with self.lock:
            return fn(*a, **k)

    def read(self):
        """Actual joint positions in our microseconds (bus servos report them)."""
        out = []
        for sid in self.ids:
            u = self._call(self.dev.getPosition, sid)
            out.append(to_us(u) if u is not None else None)
        self.report_time = self.clock.time()
        self.reports += 1
        return out

    # ------------------------------------------------------------ moves
    def clamp(self, pulses):
        lo, hi = self.cfg["joint_min"], self.cfg["joint_max"]
        return [int(round(min(max(p, lo[i]), hi[i]))) for i, p in enumerate(pulses)]

    def _clamp_hard(self, pulses):
        return [int(round(min(max(p, 500), 2500))) for p in pulses]   # the xArm's full 0-1000

    def _go(self, pulses):
        """Command all joints; returns the time the move takes (s).
        Speed limit: step_us per 20 ms, like the Uno firmware."""
        biggest = max(abs(p - t) for p, t in zip(pulses, self.targets))
        secs = max(0.25, biggest / (self.step_us * 50.0))
        pairs = [[sid, to_units(p)] for sid, p in zip(self.ids, pulses)]
        self._call(self.dev.setPosition, pairs, duration=int(secs * 1000), wait=False)
        self.targets = list(pulses)
        self.attached = True
        return secs

    def start(self, pose=None):
        """Don't jump anywhere: take the current position as the target."""
        now = self.read()
        if any(p is None for p in now):
            raise ArmError(f"Some servos didn't answer: {now}. Check the daisy-chain cables.")
        self.targets = now
        if self.verbose:
            print("xArm connected. Joints now:", now)

    def send_targets(self, pulses):
        self._halt.clear()
        self._go(self.clamp(pulses))
        return self.targets

    def move(self, pulses, timeout=15.0, abort=None):
        """Move and wait until it should have arrived. False on abort/stop."""
        self._halt.clear()
        secs = self._go(self.clamp(pulses))
        self.moving = True
        end = self.clock.time() + min(secs + 0.15, timeout)
        try:
            while self.clock.time() < end:
                if (abort is not None and abort.is_set()) or self._halt.is_set():
                    self.stop()
                    return False
                self.clock.sleep(0.02)
            return True
        finally:
            self.moving = False

    def set_joint(self, i, pulse, wait=True, abort=None):
        t = list(self.targets)
        t[i] = pulse
        return self.move(t, abort=abort) if wait else self.send_targets(t)

    def set_claw(self, pulse, wait=True, abort=None):
        return self.set_joint(5, pulse, wait, abort)

    def stop(self):
        """Freeze where it is now."""
        self._halt.set()
        try:
            now = self.read()
            now = [n if n is not None else t for n, t in zip(now, self.targets)]
            pairs = [[sid, to_units(p)] for sid, p in zip(self.ids, now)]
            self._call(self.dev.setPosition, pairs, duration=100, wait=False)
            self.targets = now
        finally:
            self.moving = False

    def led(self, n):
        pass                                   # no LEDs on the xArm board

    def speed(self, step_us):
        self.step_us = max(1, min(30, int(step_us)))

    def detach(self):
        """Servos go limp. The arm will drop: hold it first."""
        self._call(self.dev.servoOff)
        self.attached = False

    def park(self, abort=None):
        return self.move(self.cfg["park"], abort=abort)

    def park_and_detach(self):
        # Only park once a park pose was measured with jog; never go limp on exit
        # (bus servos holding torque is safer than the arm falling).
        if list(self.cfg["park"]) != DEFAULT_PARK:
            self.park()

    def holding(self):
        return None

    def battery_state(self):
        try:
            self.battery_v = self._call(self.dev.getBatteryVoltage)
        except Exception:
            return "unknown"
        if self.battery_v is None:
            return "unknown"
        if self.battery_v < 6.5:
            return "critical"
        if self.battery_v < 7.0:
            return "low"
        return "ok"

    # jog speaks the Uno protocol through _send; translate the few lines it uses
    def _send(self, line):
        p = line.split()
        if not p:
            return
        if p[0] == "J":
            self._halt.clear()
            self._go(self._clamp_hard([int(x) for x in p[1:7]]))
        elif p[0] == "A":
            self._go(list(self.targets))
        elif p[0] == "D":
            self.detach()
        elif p[0] == "S":
            self.stop()
        elif p[0] == "V":
            self.speed(int(p[1]))
        # "C" (limits), "H", "L", "P", "?" have no xArm equivalent

    def close(self):
        self.dev = None

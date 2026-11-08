"""Arm driver (handbook 2D). Talks the shared serial protocol to the Uno,
or to the simulator's firmware emulator through an in-memory fake port.
The driver code is identical for both.
"""
import threading

from .clock import RealClock

REPORT_FRESH = 0.09   # a report must be this much newer than a command to count


def find_port():
    from serial.tools import list_ports
    keys = ("arduino", "ch340", "usbmodem", "ttyacm", "wchusbserial", "usbserial")
    for p in list_ports.comports():
        text = f"{p.device} {p.description} {p.hwid}".lower()
        if any(k in text for k in keys):
            return p.device
    return None


class ArmError(RuntimeError):
    pass


class Arm:
    def __init__(self, cfg, transport=None, clock=None, verbose=True):
        self.cfg = cfg
        self.transport = transport
        self.clock = clock or RealClock()
        self.verbose = verbose
        self.port_name = None
        self.ser = None
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._reply = None
        self._reply_event = threading.Event()
        self.targets = list(cfg["home"])
        # latest report
        self.force = [0, 0]
        self.battery_v = None
        self.moving = False
        self.attached = False
        self.report_time = -1.0
        self.reports = 0
        self._threads = []

    # ------------------------------------------------------------ connect
    def connect(self):
        if self.transport is not None:
            self.ser = self.transport
            self.port_name = "simulator"
        else:
            import serial
            port = self.cfg["serial_port"]
            if port == "auto":
                port = find_port()
                if port is None:
                    raise ArmError("No Uno found. Plug it in, or set serial_port in config.json.")
            self.port_name = port
            try:
                self.ser = serial.Serial(port, self.cfg["baud"], timeout=0.1)
            except Exception as e:
                raise ArmError(f"Could not open {port}: {e}") from e
            self.clock.sleep(2.0)   # the Uno resets when the port opens
        self._start_threads()
        if not self.ping():
            self.close()
            raise ArmError(f"No 'OK sidekick 1' reply on {self.port_name}. "
                           "Is the Sidekick firmware uploaded and the Serial Monitor closed?")
        for i in range(6):
            self._send(f"C {i} {int(self.cfg['joint_min'][i])} {int(self.cfg['joint_max'][i])}")
        self._send(f"V {int(self.cfg['step_us'])}")
        return self

    def ping(self, timeout=2.0):
        self._reply_event.clear()
        self._send("?")
        end = self.clock.time() + timeout
        while self.clock.time() < end:
            if self._reply_event.wait(self.clock.real(0.05)):
                if self._reply == "OK sidekick 1":
                    return True
                self._reply_event.clear()
        return False

    def _start_threads(self):
        self._stop.clear()
        for fn in (self._reader, self._heartbeat):
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self._threads.append(t)

    # ------------------------------------------------------------ threads
    def _reader(self):
        while not self._stop.is_set():
            try:
                raw = self.ser.readline()
            except Exception:
                if self._stop.is_set():
                    return
                continue
            if not raw:
                continue
            line = raw.decode(errors="ignore").strip()
            if line.startswith("F "):
                parts = line.split()
                if len(parts) == 6:
                    try:
                        a0, a1, a2, mv, at = (int(p) for p in parts[1:])
                    except ValueError:
                        continue
                    self.force = [a0, a1]
                    self.battery_v = a2 * 5.0 / 1023.0 * 2.0
                    self.moving = bool(mv)
                    self.attached = bool(at)
                    self.report_time = self.clock.time()
                    self.reports += 1
            elif line:
                self._reply = line
                self._reply_event.set()

    def _heartbeat(self):
        while not self._stop.is_set():
            self._send("H")
            self.clock.sleep(0.3)

    def _send(self, line):
        with self.lock:
            try:
                self.ser.write((line + "\n").encode())
            except Exception as e:
                if not self._stop.is_set():
                    raise ArmError(f"Serial write failed: {e}") from e
        self.last_send = self.clock.time()

    # ------------------------------------------------------------ functions
    def clamp(self, pulses):
        lo, hi = self.cfg["joint_min"], self.cfg["joint_max"]
        return [int(round(min(max(p, lo[i]), hi[i]))) for i, p in enumerate(pulses)]

    def start(self, pose=None):
        """Send the starting pose, then switch servos on one at a time."""
        pose = self.clamp(pose or self.cfg["home"])
        if self.verbose and self.port_name != "simulator":
            print("Pose the arm near home by hand, then switch the battery ON.")
        self._send("P " + " ".join(str(p) for p in pose))
        self.targets = list(pose)
        self._send("A")
        self.clock.sleep(3.0)

    def send_targets(self, pulses):
        self.targets = self.clamp(pulses)
        self._send("J " + " ".join(str(p) for p in self.targets))
        return self.targets

    def move(self, pulses, timeout=15.0, abort=None):
        """Send targets and wait until the Uno reports it stopped moving.
        Returns True when done, False on abort or timeout."""
        self.send_targets(pulses)
        sent = self.clock.time()
        end = sent + timeout
        while self.clock.time() < end:
            if abort is not None and abort.is_set():
                return False
            if self.report_time > sent + REPORT_FRESH and not self.moving:
                return True
            self.clock.sleep(0.02)
        return False

    def set_joint(self, i, pulse, wait=True, abort=None):
        t = list(self.targets)
        t[i] = pulse
        return self.move(t, abort=abort) if wait else self.send_targets(t)

    def set_claw(self, pulse, wait=True, abort=None):
        return self.set_joint(5, pulse, wait, abort)

    def stop(self):
        self._send("S")

    def led(self, n):
        self._send(f"L {int(n)}")

    def speed(self, step_us):
        self._send(f"V {int(step_us)}")

    def detach(self):
        self._send("D")

    def park(self, abort=None):
        return self.move(self.cfg["park"], abort=abort)

    def park_and_detach(self):
        self.park()
        self.detach()

    def holding(self):
        if not self.cfg["force_sensors"]:
            return None
        return max(self.force) > self.cfg["force_grip_threshold"]

    def battery_state(self):
        if not self.cfg["battery_monitor"] or self.battery_v is None:
            return "unknown"
        if self.battery_v < self.cfg["battery_stop"]:
            return "critical"
        if self.battery_v < self.cfg["battery_warn"]:
            return "low"
        return "ok"

    def close(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1.0)
        self._threads = []
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass


def make_arm(cfg, world=None, clock=None):
    """Real Uno when use_sim is false, otherwise the simulator's fake port."""
    if cfg["use_sim"]:
        if world is None:
            raise ArmError("use_sim is true but no simulator world was given")
        return Arm(cfg, transport=world.serial_port(), clock=world.clock)
    if cfg.get("arm_type") == "xarm":
        from .xarm_driver import XArm
        return XArm(cfg, clock=clock)
    return Arm(cfg, clock=clock)

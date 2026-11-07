"""Talk to the Uno (firmware v2). All calibration lives here, not on the Uno.

Angles are PHYSICAL degrees measured from each servo's center:
    0 = center, + one way, - the other way.
    180 deg servo: -90 .. +90      270 deg servo: -135 .. +135
"""
import time

DRY_RUN = False

# One entry per joint. Fix offset/direction after assembly:
#   offset_deg: add this so 0 deg means "arm straight" for that joint
#   direction:  flip to -1 if + moves the wrong way
JOINTS = [
    {"name": "base",       "range_deg": 180, "offset_deg": 0, "direction": 1},
    {"name": "shoulder",   "range_deg": 270, "offset_deg": 0, "direction": 1},
    {"name": "elbow",      "range_deg": 270, "offset_deg": 0, "direction": 1},
    {"name": "wrist_p",    "range_deg": 180, "offset_deg": 0, "direction": 1},
    {"name": "wrist_r",    "range_deg": 180, "offset_deg": 0, "direction": 1},
    {"name": "gripper",    "range_deg": 180, "offset_deg": 0, "direction": 1},
]
CENTER_US, SPAN_US = 1500, 2000   # 500..2500 us covers the full range


def deg_to_us(i, deg):
    j = JOINTS[i]
    half = j["range_deg"] / 2
    d = max(-half, min(half, j["direction"] * deg + j["offset_deg"]))
    return int(round(CENTER_US + d * SPAN_US / j["range_deg"]))


class Arm:
    def __init__(self, port, baud=115200, dry_run=DRY_RUN):
        self.dry_run = dry_run
        self.ser = None
        if not dry_run:
            import serial
            self.ser = serial.Serial(port, baud, timeout=0.1)
            time.sleep(2)                     # Uno resets when the port opens
            self._wait_for("READY", timeout=6)  # startup attaches servos slowly

    def _send(self, line):
        if self.dry_run:
            print("[DRY]", line)
            return
        self.ser.write((line + "\n").encode())

    def _wait_for(self, word, timeout=10):
        if self.dry_run:
            return True
        end = time.time() + timeout
        while time.time() < end:
            line = self.ser.readline().decode(errors="ignore").strip()
            if not line:
                continue
            if line not in ("OK",):
                print("[UNO]", line)
            if line == word:
                return True
            if line in ("ERR", "STOPPED", "ESTOP"):
                return False
        print(f"[WARN] timed out waiting for {word}")
        return False

    # --- motion, in physical degrees ---
    def move_all(self, degs, wait=True):
        assert len(degs) == 6
        self._send("P," + ",".join(str(deg_to_us(i, d)) for i, d in enumerate(degs)))
        return self._wait_for("DONE") if wait else True

    def move_joint(self, i, deg, wait=True):
        self._send(f"J,{i},{deg_to_us(i, deg)}")
        return self._wait_for("DONE") if wait else True

    def stream(self, degs):
        """Send a target without waiting. Call at 20-50 Hz for live motion."""
        self.move_all(degs, wait=False)

    # --- raw / utility ---
    def move_joint_us(self, i, us, wait=True):
        self._send(f"J,{i},{int(us)}")
        return self._wait_for("DONE") if wait else True

    def center(self):
        self._send("C")
        return self._wait_for("DONE")

    def set_speed(self, us_per_tick):
        self._send(f"V,{int(us_per_tick)}")

    def stop(self):
        self._send("X")

    def resume(self):
        self._send("R")

    def close(self):
        if self.ser:
            self.ser.close()

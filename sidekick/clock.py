"""One time source for everything, so the simulator can run faster than real time.

RealClock is plain wall time. SimClock is wall time multiplied by `speed`:
every component (driver threads, firmware emulator, simulated camera,
coordinator) sleeps through the clock, so the same threaded code runs
at 1x for watching or at 10-50x for training and tests.
"""
import time


class RealClock:
    speed = 1.0

    def time(self):
        return time.monotonic()

    def sleep(self, seconds):
        if seconds > 0:
            time.sleep(seconds)

    def real(self, seconds):
        """Convert clock seconds to wall seconds (for queue timeouts)."""
        return seconds


class SimClock:
    def __init__(self, speed=1.0):
        self.speed = float(speed)
        self._t0_real = time.monotonic()
        self._t0_virtual = 0.0

    def time(self):
        return self._t0_virtual + (time.monotonic() - self._t0_real) * self.speed

    def sleep(self, seconds):
        if seconds > 0:
            time.sleep(seconds / self.speed)

    def real(self, seconds):
        return seconds / self.speed

    def set_speed(self, speed):
        now = self.time()
        self._t0_virtual = now
        self._t0_real = time.monotonic()
        self.speed = float(speed)

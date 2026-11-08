"""Newest-frame webcam reader (handbook 2E).

A background thread reads continuously and keeps only the newest frame and
its timestamp, so read() never returns a stale image.
"""
import sys
import threading
import time

import cv2


class Camera:
    def __init__(self, index=0, width=1280, height=720, fps=60):
        backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(index, backend)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera {index}. Try another camera_index "
                               "(0 is often the laptop camera). On Mac, allow Terminal "
                               "in System Settings > Privacy > Camera.")
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.frame = None
        self.t = 0.0
        self.count = 0
        self.fps = 0.0
        self._served = 0
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._wait_first(8.0):
            self.close()
            raise RuntimeError(f"Camera {index} opened but sends no images. On Mac: allow Terminal "
                               "(or VS Code) in System Settings > Privacy & Security > Camera, then quit "
                               "and reopen it. Close Photo Booth/Zoom. Or try another camera_index.")

    def _wait_first(self, timeout):
        with self._cond:
            return self._cond.wait_for(lambda: self.count > 0, timeout=timeout)

    @classmethod
    def from_config(cls, cfg):
        return cls(cfg["camera_index"], cfg["camera_width"], cfg["camera_height"], cfg["camera_fps"])

    def _run(self):
        t0, n0 = time.monotonic(), 0
        while not self._stop.is_set():
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            now = time.monotonic()
            with self._cond:
                self.frame, self.t = frame, now
                self.count += 1
                self._cond.notify_all()
            if now - t0 >= 1.0:
                self.fps = (self.count - n0) / (now - t0)
                t0, n0 = now, self.count

    def read(self, timeout=1.0):
        """Wait for a frame newer than the last one returned. -> (frame, t) or (None, None)."""
        with self._cond:
            if not self._cond.wait_for(lambda: self.count > self._served, timeout=timeout):
                return None, None
            self._served = self.count
            return self.frame.copy(), self.t

    def size(self):
        return (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    def close(self):
        self._stop.set()
        self._thread.join(timeout=1)
        self.cap.release()

"""Find colored Mega Bloks in the camera frame.

Run directly to tune: python color_detect.py
  - Shows each detected block's center pixel.
  - Press 't' to open HSV sliders and tune the color under your lighting.
"""
import cv2
import numpy as np

# HSV ranges (OpenCV hue is 0-179). Tune these under your actual lighting.
COLORS = {
    "red":    [((0, 120, 70), (10, 255, 255)), ((170, 120, 70), (179, 255, 255))],
    "blue":   [((100, 120, 60), (130, 255, 255))],
    "green":  [((40, 80, 60), (85, 255, 255))],
    "yellow": [((20, 120, 120), (35, 255, 255))],
}
MIN_AREA = 400  # pixels; raise if you get noise


def detect_blocks(frame):
    """Return {color: [(cx, cy, area), ...]} sorted largest first."""
    hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)
    kernel = np.ones((5, 5), np.uint8)
    found = {}
    for name, ranges in COLORS.items():
        mask = None
        for lo, hi in ranges:
            m = cv2.inRange(hsv, np.array(lo), np.array(hi))
            mask = m if mask is None else mask | m
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        blobs = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < MIN_AREA:
                continue
            M = cv2.moments(c)
            blobs.append((int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]), area))
        if blobs:
            found[name] = sorted(blobs, key=lambda b: -b[2])
    return found


def nearest_block(found, px, py):
    """Which block is closest to a pixel (e.g. where the hand pinched)."""
    best, best_d = None, float("inf")
    for name, blobs in found.items():
        for cx, cy, _ in blobs:
            d = (cx - px) ** 2 + (cy - py) ** 2
            if d < best_d:
                best, best_d = (name, cx, cy), d
    return best, best_d ** 0.5


def draw_blocks(frame, found):
    for name, blobs in found.items():
        for cx, cy, _ in blobs:
            cv2.circle(frame, (cx, cy), 8, (255, 255, 255), 2)
            cv2.putText(frame, f"{name} ({cx},{cy})", (cx + 10, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)


def tuner(cap):
    win = "HSV tuner (press q to close)"
    cv2.namedWindow(win)
    for n, v in [("H lo", 0), ("H hi", 179), ("S lo", 100), ("S hi", 255), ("V lo", 60), ("V hi", 255)]:
        cv2.createTrackbar(n, win, v, 255 if n[0] != "H" else 179, lambda x: None)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        g = lambda n: cv2.getTrackbarPos(n, win)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array((g("H lo"), g("S lo"), g("V lo"))),
                           np.array((g("H hi"), g("S hi"), g("V hi"))))
        cv2.imshow(win, cv2.bitwise_and(frame, frame, mask=mask))
        if cv2.waitKey(1) & 0xFF == ord("q"):
            print("Range:", (g("H lo"), g("S lo"), g("V lo")), (g("H hi"), g("S hi"), g("V hi")))
            break
    cv2.destroyWindow(win)


if __name__ == "__main__":
    cap = cv2.VideoCapture(0)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        found = detect_blocks(frame)
        draw_blocks(frame, found)
        cv2.imshow("blocks (t = tune, q = quit)", frame)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord("t"):
            tuner(cap)
    cap.release()
    cv2.destroyAllWindows()

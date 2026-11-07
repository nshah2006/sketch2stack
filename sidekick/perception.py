"""Blocks, block tracking, hands (handbook 2G).

Both the real camera pipeline (RealVision) and the simulator produce the same
Observation; the BlockTracker and everything above it never know which.
"""
import math
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Observation:
    t: float
    claw: dict = None              # {x, y, z, down} or None if the marker is unseen
    detections: list = field(default_factory=list)   # [{color, x, y, angle}]
    hands: list = field(default_factory=list)        # [{x, y, open, px?}]
    image: object = None
    markers: dict = None           # {id: corners px} (real camera only)
    claw_px: tuple = None


def claw_tip(claw, marker_to_fingertip):
    """Fingertip position from a claw-marker reading. The marker faces away from
    the fingers, so the tips sit marker_to_fingertip cm behind its face normal.
    Works even when the claw isn't pointing straight down."""
    if claw is None:
        return None
    nx, ny, nz = claw.get("nx", 0.0), claw.get("ny", 0.0), claw["down"]
    k = marker_to_fingertip
    return {"x": claw["x"] - k * nx, "y": claw["y"] - k * ny, "z": claw["z"] - k * nz, "down": nz}


# ===================================================================== blocks (real images)
def color_mask(hsv, ranges):
    mask = None
    for lo, hi in ranges:
        m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
        mask = m if mask is None else (mask | m)
    return mask


def detect_blocks(image, cfg, calib, markers=None, claw_px=None, hands_px=None):
    hsv = cv2.cvtColor(cv2.GaussianBlur(image, (5, 5), 0), cv2.COLOR_BGR2HSV)
    blank = np.zeros(image.shape[:2], np.uint8)
    for pts in hands_px or []:              # skin is "not white" too: never call a hand a block
        hull = cv2.convexHull(np.asarray(pts, np.int32))
        cv2.fillConvexPoly(blank, hull, 255)
    if hands_px:
        blank = cv2.dilate(blank, np.ones((41, 41), np.uint8))
    for corners in (markers or {}).values():
        c = corners.mean(axis=0)
        grown = ((corners - c) * 1.3 + c).astype(np.int32)
        cv2.fillConvexPoly(blank, grown, 255)
    if claw_px is not None:
        cv2.circle(blank, (int(claw_px[0]), int(claw_px[1])), int(cfg["claw_blank_px"]), 255, -1)
    k = np.ones((5, 5), np.uint8)
    h = 3.0      # reference top height; classify() re-projects at the true height
    out = []
    if cfg["use_color"]:
        masks = [(color, color_mask(hsv, ranges)) for color, ranges in cfg["colors"].items()]
    else:
        # anything clearly not white board (shadows are grey, so low saturation)
        fg = (hsv[:, :, 1] >= cfg["fg_min_saturation"]).astype(np.uint8) * 255
        masks = [("any", fg)]
    for color, m in masks:
        m[blank > 0] = 0
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)     # remove specks
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)    # fill holes
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            a = cv2.contourArea(cnt)
            if not (cfg["block_area_min"] <= a <= cfg["block_area_max"]):
                continue
            rect = cv2.minAreaRect(cnt)
            (cx, cy) = rect[0]
            p = calib.pixel_to_table(cx, cy, h)
            if p is None:
                continue
            # measure the footprint on the table (top face at block height)
            box = [calib.pixel_to_table(float(u), float(v), h) for u, v in cv2.boxPoints(rect)]
            if any(b is None for b in box):
                continue
            e1 = (box[1][0] - box[0][0], box[1][1] - box[0][1])
            e2 = (box[2][0] - box[1][0], box[2][1] - box[1][1])
            l1, l2 = math.hypot(*e1), math.hypot(*e2)
            long_e = e1 if l1 >= l2 else e2
            ang = math.degrees(math.atan2(long_e[1], long_e[0]))
            perim = cv2.arcLength(cnt, True)
            circ = 4 * math.pi * a / (perim * perim) if perim > 0 else 0
            out.append({"color": color, "x": p[0], "y": p[1], "angle": fold180(ang),
                        "size": [max(l1, l2), min(l1, l2)], "round": bool(circ > 0.84),
                        "px": (float(cx), float(cy)),
                        "box_px": [[float(u), float(v)] for u, v in cv2.boxPoints(rect)]})
    return out


def fold180(a):
    """Fold an angle into -90..90 degrees."""
    return (a + 90.0) % 180.0 - 90.0


def classify(detections, catalog, calib=None):
    """Add the block type to each detection from its color, outline and footprint.
    With a camera calibration, re-measure position and size at the block's
    true top height (the first pass assumed 3 cm)."""
    for d in detections:
        if "size" not in d or "type" in d:
            continue
        tid = (catalog.classify(d["color"], d["size"][0], d["size"][1], d.get("round"))
               if d["color"] != "any" else None)
        d["type"] = tid
        if tid and calib is not None and d.get("px") is not None and "z" not in d:
            top = catalog.height(tid)
            p = calib.pixel_to_table(*d["px"], top)
            if p:
                d["x"], d["y"] = p
            if d.get("box_px"):
                box = [calib.pixel_to_table(u, v, top) for u, v in d["box_px"]]
                if all(box):
                    l1 = math.hypot(box[1][0] - box[0][0], box[1][1] - box[0][1])
                    l2 = math.hypot(box[2][0] - box[1][0], box[2][1] - box[1][1])
                    d["size"] = [max(l1, l2), min(l1, l2)]
    return detections


# ===================================================================== tracker
class BlockTracker:
    """Match detections to the nearest track of the same color within 3 cm."""

    def __init__(self, cfg, match_cm=3.0, max_missed=10, alpha=0.5):
        self.cfg = cfg
        self.match_cm = match_cm
        self.max_missed = max_missed
        self.alpha = alpha
        self.tracks = {}
        self._next = 0

    def update(self, detections, t):
        pairs = []
        for di, d in enumerate(detections):
            for tid, tr in self.tracks.items():
                if tr["color"] != d["color"]:
                    continue
                if tr.get("type") and d.get("type") and tr["type"] != d["type"]:
                    continue
                dist = math.hypot(tr["x"] - d["x"], tr["y"] - d["y"])
                if dist <= self.match_cm:
                    pairs.append((dist, di, tid))
        pairs.sort()
        used_d, used_t = set(), set()
        for _, di, tid in pairs:
            if di in used_d or tid in used_t:
                continue
            used_d.add(di)
            used_t.add(tid)
            tr, d = self.tracks[tid], detections[di]
            a = self.alpha
            tr["x"] = (1 - a) * tr["x"] + a * d["x"]
            tr["y"] = (1 - a) * tr["y"] + a * d["y"]
            tr["angle"] = d.get("angle", 0.0)
            for k in ("type", "size", "z", "px", "round"):
                if d.get(k) is not None:
                    tr[k] = d[k]
            tr["missed"] = 0
            tr["last_seen"] = t
        for tid, tr in list(self.tracks.items()):
            if tid not in used_t:
                tr["missed"] += 1
                if tr["missed"] > self.max_missed:
                    del self.tracks[tid]
        for di, d in enumerate(detections):
            if di not in used_d:
                self.tracks[self._next] = {"id": self._next, "color": d["color"], "x": d["x"], "y": d["y"],
                                           "angle": d.get("angle", 0.0), "type": d.get("type"),
                                           "size": d.get("size"), "z": d.get("z"),
                                           "px": d.get("px"), "missed": 0,
                                           "first_seen": t, "last_seen": t}
                self._next += 1
        for tr in self.tracks.values():
            tr["zone"] = ("build" if self.cfg.in_build(tr["x"], tr["y"], 1.0)
                          else self.cfg.in_supply(tr["x"], tr["y"]))
        return self.active()

    def active(self):
        """Blocks seen in the last 3 frames."""
        return [dict(tr) for tr in self.tracks.values() if tr["missed"] < 3]

    def get(self, tid):
        tr = self.tracks.get(tid)
        return dict(tr) if tr and tr["missed"] < 3 else None


def primary_hand(hands, blocks):
    """The hand nearest any block (every hand still counts for safety)."""
    if not hands:
        return None
    if not blocks:
        return hands[0]
    return min(hands, key=lambda h: min(math.hypot(h["x"] - b["x"], h["y"] - b["y"]) for b in blocks))


# ===================================================================== hands (real images)
class HandTracker:
    """MediaPipe Hand Landmarker in video mode, up to 2 hands, on a 640x360 copy."""

    FINGERS = [(8, 5), (12, 9), (16, 13), (20, 17)]   # (tip, base)
    PALM = [0, 5, 9, 13, 17]

    def __init__(self, model_path, cfg):
        import mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
        self.mp = mp
        opts = vision.HandLandmarkerOptions(
            base_options=mpt.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO, num_hands=2)
        self.landmarker = vision.HandLandmarker.create_from_options(opts)
        self.cfg = cfg
        self._last_ms = -1

    def process(self, image, t_seconds, calib):
        h, w = image.shape[:2]
        small = cv2.resize(image, (640, 360))
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        ms = int(t_seconds * 1000)
        if ms <= self._last_ms:
            ms = self._last_ms + 1                    # strictly increasing timestamps
        self._last_ms = ms
        res = self.landmarker.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb), ms)
        hands = []
        for lms in res.hand_landmarks or []:
            pts = np.array([[p.x * w, p.y * h] for p in lms])
            palm = pts[self.PALM].mean(axis=0)
            tab = calib.pixel_to_table(palm[0], palm[1], self.cfg["hand_height"])
            if tab is None:
                continue
            wrist = pts[0]
            n_open = sum(np.linalg.norm(pts[tip] - wrist) > 1.5 * np.linalg.norm(pts[base] - wrist)
                         for tip, base in self.FINGERS)
            hands.append({"x": tab[0], "y": tab[1], "open": bool(n_open >= 3),
                          "px": pts.tolist()})
        return hands


# ===================================================================== real pipeline
class RealVision:
    """Camera frame -> markers -> claw -> blocks -> hands -> Observation."""

    def __init__(self, cfg, camera, calib, hand_tracker=None):
        from .calibration import detect_markers
        self._detect = detect_markers
        self.cfg, self.camera, self.calib, self.hands = cfg, camera, calib, hand_tracker

    def read(self, timeout=1.0):
        frame, t = self.camera.read(timeout)
        if frame is None:
            return None
        markers = self._detect(frame)
        claw, claw_px = None, None
        cid = self.cfg["layout"]["claw_marker_id"]
        if cid in markers and self.calib.has_table:
            claw = self.calib.claw_pose(markers[cid], self.cfg["claw_marker_size"])
            claw_px = tuple(markers[cid].mean(axis=0))
        hands = self.hands.process(frame, t, self.calib) if (self.hands and self.calib.has_table) else []
        dets = (detect_blocks(frame, self.cfg, self.calib, markers, claw_px, [h["px"] for h in hands])
                if self.calib.has_table else [])
        return Observation(t=t, claw=claw, detections=dets, hands=hands, image=frame,
                           markers=markers, claw_px=claw_px)

    def close(self):
        self.camera.close()

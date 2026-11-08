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


def arm_heading(x, y, base):
    """Turntable heading (deg) of a point, as seen from the arm's base."""
    return math.degrees(math.atan2(x - base[0], -(y - base[1])))


def unbias_normal(n, bias):
    """Rotate a measured marker normal by the fixed rotation that takes `bias`
    (the normal measured with the claw truly vertical) to straight up."""
    if not bias:
        return np.asarray(n, float)
    b = np.asarray(bias, float)
    b = b / np.linalg.norm(b)
    z = np.array([0.0, 0.0, 1.0])
    axis = np.cross(b, z)
    s, c = np.linalg.norm(axis), float(np.dot(b, z))
    if s < 1e-9:
        return np.asarray(n, float)
    axis = axis / s
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    R = np.eye(3) + s * K + (1 - c) * (K @ K)
    return R @ np.asarray(n, float)


def claw_tip(claw, marker_to_fingertip, forward=0.0, base=None, bias=None):
    """Fingertip position from a claw-marker reading. The marker faces away from
    the fingers, so the tips sit marker_to_fingertip cm behind its face normal.
    forward: how far the marker sits out in front of the tips (cm), measured
    away from the arm's base (a marker card that sticks out past the wrist).
    Works even when the claw isn't pointing straight down."""
    if claw is None:
        return None
    if bias is not None and len(bias) == 4 and base is not None:
        # the tilt bias turns with the arm: rotate it from the heading it was measured at
        d = math.radians(arm_heading(claw["x"], claw["y"], base) - bias[3])
        bx, by, bz = bias[:3]
        bias = [bx * math.cos(d) - by * math.sin(d), bx * math.sin(d) + by * math.cos(d), bz]
    elif bias is not None and len(bias) == 4:
        bias = bias[:3]
    nx, ny, nz = unbias_normal([claw.get("nx", 0.0), claw.get("ny", 0.0), claw["down"]], bias)
    k = marker_to_fingertip
    x, y, z = claw["x"] - k * nx, claw["y"] - k * ny, claw["z"] - k * nz
    if forward and base is not None:
        r = np.array([claw["x"] - base[0], claw["y"] - base[1], 0.0])
        n = np.array([nx, ny, nz])
        f = r - np.dot(r, n) * n                 # outward direction, in the marker's plane
        norm = np.linalg.norm(f)
        if norm > 1e-6 and np.linalg.norm(r) > 3.0:
            f /= norm
            x, y, z = x - forward * f[0], y - forward * f[1], z - forward * f[2]
    return {"x": float(x), "y": float(y), "z": float(z), "down": nz}


def tip_from_pixel(calib, cfg, u, v, h, base, tilt=0.0):
    """Tips from the marker's pixel, given the tips' height h and the claw's outward
    tilt (deg, from the arm model). Tipping the claw outward swings the marker,
    which sits k cm up the claw from the tips, back toward the base by k*sin(tilt)."""
    k, fwd = cfg["marker_to_fingertip"], cfg.get("marker_forward", 0.0)
    t = math.radians(tilt)
    hit = calib.pixel_to_table(u, v, z=h + k * math.cos(t) + fwd * math.sin(t))
    if hit is None:
        return None
    x, y = hit
    out = fwd * math.cos(t) - k * math.sin(t)       # marker sits this far out past the tips
    r = math.hypot(x - base[0], y - base[1])
    if out and r > 3.0:
        x, y = x - out * (x - base[0]) / r, y - out * (y - base[1]) / r
    return float(x), float(y)


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
            # the blob is the top face plus the sides the camera can see, so its centre
            # sits over the block's mid-height, not its top
            p = calib.pixel_to_table(cx, cy, h / 2)
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
                        "box_px": [[float(u), float(v)] for u, v in cv2.boxPoints(rect)],
                        "cnt": cnt})                # outline (px), for the silhouette fit
    return out


def fold180(a):
    """Fold an angle into -90..90 degrees."""
    return (a + 90.0) % 180.0 - 90.0


# ===================================================================== silhouette fit
# From 60 cm up the camera sees a block's top AND the sides facing away from the
# nadir, so the blob is the hull of the projected bottom and top outlines. A tall
# block (pillar, tall cylinder) throws a longer blob than its short twin (cube,
# short cylinder) everywhere but right under the camera. Fitting each candidate
# type's projected silhouette to the blob tells them apart, gives the centre and
# yaw without the perspective bias, and flags blobs no single block explains
# (touching blocks), which are then split.
FIT_OK = 0.80          # IoU for "this one block explains the blob"
FIT_PART = 0.72        # score for one block inside a split blob
FIT_PAD = 12           # px around the blob


def _outline(catalog, tid, pose=0):
    """3D points (block frame, cm, bottom at z=0) whose image hull is the silhouette."""
    w, d, h = catalog.size(tid, pose)
    shape = catalog.types[tid]["shape"]
    if shape == "cylinder":
        ring = [(w / 2 * math.cos(a), d / 2 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 20, endpoint=False)]
        return np.array([(x, y, z) for z in (0.0, h) for x, y in ring])
    base = [(sx * w / 2, sy * d / 2, 0.0) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    top = [(0.0, -d / 2, h), (0.0, d / 2, h)] if shape == "roof" else [(x, y, h) for x, y, _ in base]
    return np.array(base + top)


def _silhouette(calib, pts, x, y, yaw):
    a = math.radians(yaw)
    c, s = math.cos(a), math.sin(a)
    w = np.column_stack([x + c * pts[:, 0] - s * pts[:, 1], y + s * pts[:, 0] + c * pts[:, 1], pts[:, 2]])
    px, _ = cv2.projectPoints(w.astype(np.float64), calib.rvec, calib.tvec, calib.K, calib.dist)
    return cv2.convexHull(px.reshape(-1, 2).astype(np.float32))


def _fit_type(calib, catalog, tid, target, blob, off, angle, refine=True):
    """Best placement of one `tid` block on `target` (mask). -> (score, x, y, yaw).
    blob: the whole blob mask (for a split part the block may cover neighbour
    pixels of the same blob, but nothing outside it)."""
    pts = _outline(catalog, tid)
    h = catalog.height(tid)
    m = cv2.moments(target, binaryImage=True)
    if m["m00"] <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    cu, cv_ = m["m10"] / m["m00"] + off[0], m["m01"] / m["m00"] + off[1]
    p0 = calib.pixel_to_table(cu, cv_, h / 2)
    if p0 is None:
        return (0.0, 0.0, 0.0, 0.0)
    w, d, _ = catalog.size(tid)
    yaw0 = fold180(angle if w >= d else angle + 90.0)
    yaws = [yaw0] if (catalog.round_(tid) or abs(w - d) < 0.3) else [yaw0 - 5, yaw0, yaw0 + 5]
    n_t = float(target.sum())
    part = blob is not target
    best = (0.0, p0[0], p0[1], yaw0)
    pm = np.zeros_like(target)
    for yaw in yaws:
        x, y = p0
        for _ in range(2):                 # recentre: predicted blob centroid onto the measured one
            hull = _silhouette(calib, pts, x, y, yaw)
            hm = cv2.moments(hull)
            if hm["m00"] <= 0:
                break
            du, dv = cu - hm["m10"] / hm["m00"], cv_ - hm["m01"] / hm["m00"]
            if abs(du) + abs(dv) < 0.3:
                break
            c0 = calib.table_to_pixel(x, y, h / 2)
            q = calib.pixel_to_table(c0[0] + du, c0[1] + dv, h / 2)
            if q is None:
                break
            x, y = q
        shifts = [(0, 0)] if not (part and refine) else [(i, j) for i in (-3, 0, 3) for j in (-3, 0, 3)]
        hull = _silhouette(calib, pts, x, y, yaw)
        for su, sv in shifts:
            pm[:] = 0
            poly = (hull.reshape(-1, 2) - np.array(off, np.float32) + (su, sv)).round().astype(np.int32)
            cv2.fillConvexPoly(pm, poly, 1)
            n_p = float(pm.sum())
            if n_p <= 0:
                continue
            inter = float((pm & target).sum())
            if part:   # inside the blob, and explaining this part of it
                score = min(float((pm & blob).sum()) / n_p, inter / n_t)
            else:
                score = inter / (n_p + n_t - inter)
            if score > best[0]:
                xx, yy = x, y
                if su or sv:
                    c0 = calib.table_to_pixel(x, y, h / 2)
                    q = calib.pixel_to_table(c0[0] + su, c0[1] + sv, h / 2)
                    xx, yy = q if q else (x, y)
                best = (score, xx, yy, yaw)
    return best


def _split(blob, min_px=40):
    """Touching blocks: erode until the blob falls apart, then give every pixel to
    its nearest core. -> [part masks] (empty if it never splits)."""
    for r in range(2, 30, 2):
        core = cv2.erode(blob, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(core)
        keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_px]
        if len(keep) >= 2:
            src = np.full(blob.shape, 255, np.uint8)
            for i in keep:
                src[lab == i] = 0
            _, near = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_CCOMP)
            parts = []
            for i in keep:
                ys, xs = np.nonzero(lab == i)
                parts.append((blob & (near == near[ys[0], xs[0]])).astype(np.uint8))
            return parts
        if len(keep) == 0:
            return []
    return []


def fit_blob(d, catalog, calib):
    """Silhouette-fit one color blob. -> [detections]: the blob itself with its
    best type (or type None when nothing fits), or its parts when it is two or
    more touching blocks. Each gets "fit" (score) and "alts" {type: score}."""
    cnt = np.asarray(d["cnt"]).reshape(-1, 2)
    x0, y0 = cnt.min(axis=0) - FIT_PAD
    x1, y1 = cnt.max(axis=0) + FIT_PAD
    off = (int(x0), int(y0))
    blob = np.zeros((int(y1 - y0) + 1, int(x1 - x0) + 1), np.uint8)
    cv2.fillPoly(blob, [(cnt - off).astype(np.int32)], 1)
    tids = [t for t, v in catalog.types.items() if d["color"] in v["colors"]]

    def best_of(target, angle, part=False):
        res = {t: _fit_type(calib, catalog, t, target, blob, off, angle) if part
               else _fit_type(calib, catalog, t, target, target, off, angle) for t in tids}
        return res

    def as_det(src, res, parts=False):
        tid = max(res, key=lambda t: res[t][0]) if res else None
        ok = tid is not None and res[tid][0] >= (FIT_PART if parts else FIT_OK)
        out = dict(src)
        out.pop("cnt", None)
        out["alts"] = {t: round(v[0], 3) for t, v in res.items()}
        out["fit"] = round(res[tid][0], 3) if tid else 0.0
        if not ok:
            out["type"] = None
            return out
        sc, x, y, yaw = res[tid]
        w, dd, _ = catalog.size(tid)
        out.update({"type": tid, "x": x, "y": y, "angle": fold180(yaw if w >= dd else yaw - 90.0),
                    "size": sorted(catalog.size(tid)[:2], reverse=True)})
        return out

    res = best_of(blob, d.get("angle", 0.0))
    one = as_det(d, res)
    if one["type"] is not None or not tids:
        return [one]
    out = []
    for pmask in _split(blob):
        m = cv2.moments(pmask, binaryImage=True)
        if m["m00"] <= 0:
            continue
        cnts, _ = cv2.findContours(pmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        (cu, cv_), _, _ = rect = cv2.minAreaRect(max(cnts, key=cv2.contourArea))
        box = [calib.pixel_to_table(u + off[0], v + off[1], 1.5) for u, v in cv2.boxPoints(rect)]
        ang = d.get("angle", 0.0)
        if all(box):
            e1 = (box[1][0] - box[0][0], box[1][1] - box[0][1])
            e2 = (box[2][0] - box[1][0], box[2][1] - box[1][1])
            le = e1 if math.hypot(*e1) >= math.hypot(*e2) else e2
            ang = fold180(math.degrees(math.atan2(le[1], le[0])))
        src = dict(d, px=(float(cu + off[0]), float(cv_ + off[1])), angle=ang, split=True)
        part = as_det(src, best_of(pmask, ang, part=True), parts=True)
        if part["type"] is not None:
            out.append(part)
    if not out:
        one["merged"] = True             # several blocks, can't tell which: never pick it
        return [one]
    return out


def classify(detections, catalog, calib=None):
    """Add the block type to each detection from its color, outline and footprint.
    With a camera calibration and the blob outline: fit each type's projected
    silhouette (see above). Otherwise re-measure position and size at the
    block's true top height (the first pass assumed 3 cm)."""
    out = []
    for d in detections:
        if ("size" in d and "type" not in d and d["color"] != "any" and calib is not None
                and d.get("cnt") is not None and getattr(calib, "rvec", None) is not None):
            out += fit_blob(d, catalog, calib)
            continue
        out.append(d)
    detections[:] = out
    for d in detections:
        d.pop("cnt", None)
        if "size" not in d or "type" in d:
            continue
        tid = (catalog.classify(d["color"], d["size"][0], d["size"][1], d.get("round"))
               if d["color"] != "any" else None)
        d["type"] = tid
        if tid and calib is not None and d.get("px") is not None and "z" not in d:
            top = catalog.height(tid)
            p = calib.pixel_to_table(*d["px"], top / 2)
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
                dist = math.hypot(tr["x"] - d["x"], tr["y"] - d["y"])
                if dist <= self.match_cm:
                    # a different type is a weaker match (a neighbour), not a different
                    # block outright: a frame's fit can flip cube <-> pillar near the nadir
                    differ = tr.get("type") and d.get("type") and tr["type"] != d["type"]
                    pairs.append((dist + (1.0 if differ else 0.0), di, tid))
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
            for k in ("size", "z", "px", "round", "fit"):
                if d.get(k) is not None:
                    tr[k] = d[k]
            self._vote(tr, d)
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
                                           "px": d.get("px"), "missed": 0, "fit": d.get("fit"),
                                           "first_seen": t, "last_seen": t, "votes": {}}
                self._vote(self.tracks[self._next], d)
                self._next += 1
        for tr in self.tracks.values():
            tr["zone"] = ("build" if self.cfg.in_build(tr["x"], tr["y"], 1.0)
                          else self.cfg.in_supply(tr["x"], tr["y"]))
        return self.active()

    def _vote(self, tr, d, keep=0.85):
        """The track's type is the (decaying) majority of its frames' types, so one
        odd frame can't turn a pillar into a cube. Unfit / merged frames vote "?"."""
        v = tr.setdefault("votes", {})
        for k in v:
            v[k] *= keep
        key = d.get("type") or ("?" if "fit" in d else None)
        if key is None:                       # no silhouette fit (sim / colorless): take it as is
            tr["type"] = d.get("type") or tr.get("type")
            return
        v[key] = v.get(key, 0.0) + 1.0
        top = max(v, key=v.get)
        tr["type"] = None if top == "?" else top
        tr["sure"] = round(v[top] / sum(v.values()), 2)    # 1.0 = every recent frame agreed
        tr["merged"] = bool(d.get("merged"))

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
            hand = {"x": tab[0], "y": tab[1], "open": bool(n_open >= 3), "px": pts.tolist()}
            self._add_sign(hand, pts, calib)
            hands.append(hand)
        return hands

    def _add_sign(self, hand, pts, calib):
        """hand["sign"] (hand_signs.classify), and for "point" also where it points."""
        if not self.cfg.get("hand_signs", True):
            return
        from . import hand_signs
        hand["sign"] = hand_signs.classify(pts)
        if hand["sign"] == "point":
            hz = self.cfg["hand_height"]
            mcp, tip = (calib.pixel_to_table(pts[i][0], pts[i][1], hz) for i in (5, 8))
            if mcp is not None and tip is not None:
                lm = {5: mcp, 8: tip}
                at = hand_signs.point_target(lm, self.cfg.get("point_extend_cm", 0.0))
                hand["point_at"] = (float(at[0]), float(at[1]))
                hand["point_dir"] = hand_signs.point_ray(lm)[1]


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

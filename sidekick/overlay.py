"""Live view drawing (handbook 2N, adapted): zones, blocks, plan ghosts,
hands, claw and status, either on the real camera image or on a plain
top-down picture of the table (simulator)."""
import math

import cv2
import numpy as np

BGR = {"red": (60, 60, 220), "blue": (220, 140, 40), "green": (80, 190, 60),
       "yellow": (40, 210, 235), "wood": (140, 180, 215)}
MODE_COLOR = {"idle": (160, 160, 160), "building": (80, 190, 60), "waiting": (40, 200, 230),
              "done": (220, 140, 40), "stopped": (60, 60, 220)}


class TopDown:
    """Table cm -> pixels for a plain top-down view (human side at the bottom)."""

    def __init__(self, cfg, scale=14.0, margin=20):
        self.cfg, self.s, self.m = cfg, scale, margin
        w, h = cfg["layout"]["work_area"]
        self.size = (int(w * scale + 2 * margin), int((h + 6) * scale + 2 * margin))
        self.h = h + 6

    def __call__(self, x, y, z=0.0):
        return (int(self.m + x * self.s), int(self.m + (self.h - y) * self.s))

    def blank(self):
        img = np.full((self.size[1], self.size[0], 3), 245, np.uint8)
        w, h = self.cfg["layout"]["work_area"]
        for gx in range(0, int(w) + 1, 5):
            cv2.line(img, self(gx, 0), self(gx, h), (228, 228, 228), 1)
        for gy in range(0, int(h) + 1, 5):
            cv2.line(img, self(0, gy), self(w, gy), (228, 228, 228), 1)
        cv2.rectangle(img, self(0, h), self(w, 0), (200, 200, 200), 1)
        return img


class CameraProjector:
    def __init__(self, calib):
        self.calib = calib

    def __call__(self, x, y, z=0.0):
        u, v = self.calib.table_to_pixel(x, y, z)
        return (int(u), int(v))


def _rect_pts(proj, x, y, w, d, yaw, z=0.0):
    a = math.radians(yaw)
    pts = []
    for u, v in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)):
        pts.append(proj(x + u * math.cos(a) - v * math.sin(a), y + u * math.sin(a) + v * math.cos(a), z))
    return np.array(pts, np.int32)


def _zone(img, proj, rect, color, label):
    x0, x1, y0, y1 = rect
    pts = np.array([proj(x0, y0), proj(x1, y0), proj(x1, y1), proj(x0, y1)], np.int32)
    over = img.copy()
    cv2.fillPoly(over, [pts], color)
    cv2.addWeighted(over, 0.18, img, 0.82, 0, img)
    cv2.polylines(img, [pts], True, color, 1)
    cv2.putText(img, label, tuple(pts[3] + [3, 14]), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)


def draw(img, proj, cfg, catalog, state):
    """state: Builder.snapshot()"""
    lay = cfg["layout"]
    _zone(img, proj, lay["build_area"], (90, 150, 60), "build")
    for name, r in lay["supply"].items():
        _zone(img, proj, r, (60, 140, 200), f"supply {name}")
    bx, by = lay["base"]
    cv2.circle(img, proj(bx, by), 10, (90, 90, 90), 2)
    # plan ghosts
    done = {i for i, s in enumerate(state.get("steps", [])) if s["state"] == "done"}
    for i, st in enumerate(state.get("plan", [])):
        if i in done:
            continue
        fx, fy = catalog.footprint(st["type"], 0)
        col = BGR.get(st["color"], (120, 120, 120))
        top = st["z"] + st["h"]
        if catalog.round_(st["type"]):
            c, e = proj(st["x"], st["y"], top), proj(st["x"] + fx / 2, st["y"], top)
            cv2.circle(img, c, max(3, abs(e[0] - c[0])), col, 1, cv2.LINE_AA)
            anchor = (c[0] - 4, c[1] + 4)
        else:
            pts = _rect_pts(proj, st["x"], st["y"], fx, fy, st["yaw"], top)
            cv2.polylines(img, [pts], True, col, 1, cv2.LINE_AA)
            anchor = tuple(int(v) for v in pts[0] + [2, -3])
        cv2.putText(img, str(i + 1), anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.35, col, 1)
    # blocks
    for b in state.get("blocks", []):
        col = BGR.get(b["color"], (120, 120, 120))
        tid = b.get("type")
        top = (b.get("z") or 0) + (catalog.height(tid) if tid else 3.0)
        if tid and catalog.round_(tid):
            r = catalog.size(tid)[0] / 2
            c = proj(b["x"], b["y"], top)
            e = proj(b["x"] + r, b["y"], top)
            cv2.circle(img, c, max(3, abs(e[0] - c[0])), col, -1, cv2.LINE_AA)
        else:
            w, d = (catalog.size(tid)[:2] if tid else (3, 3))
            pts = _rect_pts(proj, b["x"], b["y"], w, d, b.get("yaw", 0.0), top)
            cv2.fillPoly(img, [pts], col, cv2.LINE_AA)
            cv2.polylines(img, [pts], True, (40, 40, 40), 1, cv2.LINE_AA)
        label = catalog.types[tid]["name"] if tid else "?"
        cv2.putText(img, label, proj(b["x"] - 1.5, b["y"] - 2.4, top), cv2.FONT_HERSHEY_SIMPLEX, 0.33,
                    (50, 50, 50), 1)
    # hands
    for h in state.get("hands", []):
        c = proj(h["x"], h["y"], cfg["hand_height"])
        e = proj(h["x"] + cfg["stop_distance"], h["y"], cfg["hand_height"])
        cv2.circle(img, c, abs(e[0] - c[0]), (60, 60, 220) if state.get("safety") else (150, 150, 150), 1)
        cv2.circle(img, c, 7, (40, 120, 230), -1)
    # claw
    c = state.get("claw")
    if c:
        p = proj(c["x"], c["y"], c["z"])
        cv2.drawMarker(img, p, (30, 30, 30), cv2.MARKER_CROSS, 16, 2)
        cv2.putText(img, f"z {c['z']:.1f}", (p[0] + 8, p[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (30, 30, 30), 1)
    # status bar
    mode = state.get("mode", "idle")
    col = MODE_COLOR.get("stopped" if state.get("safety") else mode, (160, 160, 160))
    cv2.rectangle(img, (0, 0), (img.shape[1], 24), col, -1)
    txt = ("SAFETY STOP - hand near the arm" if state.get("safety")
           else f"{mode.upper()}  {state.get('action', '')}")
    cv2.putText(img, txt[:90], (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def render(builder, cfg, catalog, topdown=None):
    """One live-view frame for the UI."""
    state = builder.snapshot()
    obs = builder.obs
    if obs is not None and obs.image is not None and getattr(builder.source, "calib", None) is not None \
            and builder.source.calib.has_table:
        img = obs.image.copy()
        proj = CameraProjector(builder.source.calib)
    else:
        topdown = topdown or TopDown(cfg)
        img = topdown.blank()
        proj = topdown
    return draw(img, proj, cfg, catalog, state)

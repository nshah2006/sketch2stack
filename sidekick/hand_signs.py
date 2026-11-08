"""Hand signs from MediaPipe's 21 hand landmarks (pixel points).

    palm       all four fingers straight: "stop / pause"
    thumbs_up  thumb out, the four fingers curled: "go / resume / done"
    point      index straight, the other three curled: "there / that one"
    fist       everything curled

Only ratios of distances between landmarks are used, so a sign reads the same
at any scale or rotation in the image (the camera looks straight down, so
"up" means nothing there). No MediaPipe import: plain lists of (x, y) work.

Landmarks: 0 wrist; thumb 1-4 (CMC, MCP, IP, tip); index 5-8, middle 9-12,
ring 13-16, pinky 17-20 (MCP, PIP, DIP, tip).
"""
import math

FINGERS = {"index": (5, 6, 7, 8), "middle": (9, 10, 11, 12),
           "ring": (13, 14, 15, 16), "pinky": (17, 18, 19, 20)}
SIGNS = ("palm", "thumbs_up", "point", "fist")
PRIORITY = {"palm": 0, "thumbs_up": 1, "point": 2, "fist": 3}   # several hands: the stop wins


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def finger_state(pts, finger):
    """-> "out", "curled" or None (in between)."""
    mcp, pip, dip, tip = (pts[i] for i in FINGERS[finger])
    w = pts[0]
    bones = _d(mcp, pip) + _d(pip, dip) + _d(dip, tip)
    straight = _d(mcp, tip) / (bones + 1e-9)            # 1.0 = a straight finger
    if straight > 0.8 and _d(w, tip) > 1.1 * _d(w, pip):
        return "out"
    if _d(w, tip) < _d(w, pip):                          # the tip folded back toward the wrist
        return "curled"
    return None


def thumb_out(pts):
    """Thumb stretched away from the hand (not tucked over the fingers)."""
    palm = _d(pts[0], pts[9]) + 1e-9                     # wrist -> middle knuckle: the hand's size
    mcp, ip, tip = pts[2], pts[3], pts[4]
    straight = _d(mcp, tip) / (_d(mcp, ip) + _d(ip, tip) + 1e-9)
    return (straight > 0.85 and _d(tip, pts[5]) > 0.45 * palm
            and _d(pts[0], tip) > _d(pts[0], ip))           # tip still heading away from the wrist


def classify(pts):
    """21 (x, y) landmark points -> "palm" | "thumbs_up" | "point" | "fist" | None."""
    if pts is None or len(pts) < 21:
        return None
    s = {f: finger_state(pts, f) for f in FINGERS}
    thumb = thumb_out(pts)
    if all(v == "out" for v in s.values()):
        return "palm"
    rest = all(s[f] == "curled" for f in ("middle", "ring", "pinky"))
    if rest and s["index"] == "out":
        return "point"
    if rest and s["index"] == "curled":
        return "thumbs_up" if thumb else "fist"
    return None


def point_ray(table_pts):
    """Landmarks already on the table plane (cm) -> (tip, unit direction) of the index finger."""
    mcp, tip = table_pts[5], table_pts[8]
    dx, dy = tip[0] - mcp[0], tip[1] - mcp[1]
    n = math.hypot(dx, dy)
    if n < 1e-6:
        return (float(tip[0]), float(tip[1])), None
    return (float(tip[0]), float(tip[1])), (dx / n, dy / n)


def point_target(table_pts, extend_cm=0.0):
    """Where the index points: the fingertip, pushed `extend_cm` further along the finger."""
    tip, u = point_ray(table_pts)
    if u is None or not extend_cm:
        return tip
    return (tip[0] + u[0] * extend_cm, tip[1] + u[1] * extend_cm)


def pointed_block(at, blocks, direction=None, max_off=4.0, max_ahead=40.0):
    """The block the finger means: nearest to the ray from `at` along `direction`
    (within `max_off` cm of it), or simply the nearest one to `at`."""
    best = None
    for b in blocks:
        dx, dy = b["x"] - at[0], b["y"] - at[1]
        if direction is not None:
            ahead = dx * direction[0] + dy * direction[1]
            if ahead < -3.0 or ahead > max_ahead:
                continue
            off = abs(-dx * direction[1] + dy * direction[0])
            if off > max_off:
                continue
            score = off + 0.1 * max(ahead, 0.0)
        else:
            score = math.hypot(dx, dy)
            if score > max_off * 2:
                continue
        if best is None or score < best[0]:
            best = (score, b)
    return best[1] if best else None


def pick(hands):
    """The hand whose sign matters most this frame -> (sign, hand) or (None, None)."""
    best = None
    for h in hands or []:
        s = h.get("sign")
        if s in PRIORITY and (best is None or PRIORITY[s] < PRIORITY[best[0]]):
            best = (s, h)
    return best or (None, None)


class SignFilter:
    """A sign fires once after it has been held `hold_s` seconds over consecutive
    frames (gaps up to `gap_s` forgiven, e.g. one missed frame), with the hand
    staying within `still_cm` of where it started (a hand dropping a block
    passes through "palm" but does not hold still). It re-arms when the sign
    changes or goes away."""

    def __init__(self, hold_s=0.5, gap_s=0.25, still_cm=4.0):
        self.hold_s, self.gap_s, self.still_cm = hold_s, gap_s, still_cm
        self.sign = None          # the sign being held now
        self.since = None
        self.last_seen = None
        self.at = None            # where the hand was when the sign began
        self.fired = False

    @property
    def active(self):
        """The sign that fired and is still being held, else None."""
        return self.sign if self.fired else None

    def update(self, sign, t, pos=None):
        """-> the sign on the frame it fires, else None."""
        if sign is None:
            if self.sign is not None and t - self.last_seen > self.gap_s:
                self.sign, self.fired = None, False
            return None
        moved = (pos is not None and self.at is not None and self.still_cm is not None
                 and math.hypot(pos[0] - self.at[0], pos[1] - self.at[1]) > self.still_cm)
        if sign != self.sign or moved or t - self.last_seen > self.gap_s:
            self.sign, self.since, self.fired = sign, t, False
            self.at = pos
        self.last_seen = t
        if not self.fired and t - self.since >= self.hold_s:
            self.fired = True
            return sign
        return None


# ---- synthetic hands (tests, and anyone wanting to try the classifier)
def synth(sign, cx=320.0, cy=240.0, scale=1.0, angle_deg=0.0):
    """21 pixel landmarks of a hand making `sign` (fingers along +y before rotation)."""
    def chain(base, ang, lens):
        out, (x, y) = [], base
        for a, L in zip(ang, lens):
            x, y = x + L * math.sin(math.radians(a)), y + L * math.cos(math.radians(a))
            out.append((x, y))
        return out

    # straight finger: every bone along the finger's direction; curled: folds back
    straight = [0, 0, 0]
    curled = [20, 170, 190]
    pts = [(0.0, 0.0)]
    thumb = sign == "thumbs_up"
    t_ang = [-50, -55, -60] if (thumb or sign == "palm") else [-10, 50, 130]   # out, or tucked in
    pts += chain((0.0, 0.0), [-35] + t_ang, [30, 25, 20, 18])     # thumb CMC, MCP, IP, tip
    bases = [(-22, 90), (-7, 95), (8, 92), (22, 85)]
    for k, (bx, by) in enumerate(bases):
        out = sign == "palm" or (sign == "point" and k == 0)
        spread = (k - 1.5) * 6 if out else 0
        angs = [spread + a for a in (straight if out else curled)]
        pts.append((float(bx), float(by)))
        pts += chain((bx, by), angs, [38, 24, 20])
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    return [(cx + scale * (x * c - y * s), cy + scale * (x * s + y * c)) for x, y in pts]

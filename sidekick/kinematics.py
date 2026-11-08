"""Kinematic model of the real arm (Hiwonder xArm 1S): a turntable plus a planar
shoulder-elbow-wrist chain. Replaces the babbled neural body model on the
real arm: link lengths come from a ruler, the joint zero offsets and the base
position are fitted to a few "touch points" (claw pointing down, tips on the
paper, position measured by the camera).

Same interface as body_model.BodyModel: solve(target) and reachable(x, y).

Angles (degrees, measured from straight up, positive = leaning toward the work
area), from the servo pulses J (us, 8 us per degree on the xArm):
    a1 = -(J1 - o1) / 8                 shoulder link
    a2 = a1 + (J2 - o2) / 8             forearm
    a3 = a2 - (J3 - o3) / 8             claw (180 = pointing straight down)
    heading = s0 * (J0 - o0) / 8        turntable, 0 = facing the human (-y)
"""
import json
import math

import numpy as np

from . import config as C

US_PER_DEG = 8.0
FIT_KEYS = ["o0", "o1", "o2", "o3", "A", "bx", "by"]


def default_params(cfg, lengths):
    A, B, Cl, D = lengths
    base = cfg["layout"]["base"]
    return {"A": A, "B": B, "C": Cl, "D": D, "bx": float(base[0]), "by": float(base[1]),
            "o0": 1488.0, "o1": 1466.0, "o2": 1700.0, "o3": 1426.0, "s0": 1.0}


class KinematicBody:
    def __init__(self, params, jmin, jmax):
        self.p = dict(params)
        self.jmin = np.asarray(jmin[:4], float)
        self.jmax = np.asarray(jmax[:4], float)
        self.fit_error = self.p.get("fit_error")

    # ---- persistence
    def save(self, path=None):
        path = path or C.path("kinematic")
        with open(path, "w") as f:
            json.dump(self.p, f, indent=2)
        return path

    @classmethod
    def load(cls, cfg, path=None):
        path = path or C.path("kinematic")
        with open(path) as f:
            p = json.load(f)
        return cls(p, cfg["joint_min"], cfg["joint_max"])

    # ---- forward
    def angles(self, pulses):
        J = np.asarray(pulses, float).reshape(-1, 4)
        p = self.p
        a1 = -(J[:, 1] - p["o1"]) / US_PER_DEG
        a2 = a1 + (J[:, 2] - p["o2"]) / US_PER_DEG
        a3 = a2 - (J[:, 3] - p["o3"]) / US_PER_DEG
        hd = p["s0"] * (J[:, 0] - p["o0"]) / US_PER_DEG
        return hd, a1, a2, a3

    def forward(self, pulses):
        """-> N x 4 array: fingertip x, y, z (cm, table frame) and down-ness."""
        p = self.p
        hd, a1, a2, a3 = (np.radians(v) for v in self.angles(pulses))
        r = p["B"] * np.sin(a1) + p["C"] * np.sin(a2) + p["D"] * np.sin(a3)
        z = p["A"] + p["B"] * np.cos(a1) + p["C"] * np.cos(a2) + p["D"] * np.cos(a3)
        x = p["bx"] + r * np.sin(hd)
        y = p["by"] - r * np.cos(hd)
        return np.stack([x, y, z, -np.cos(a3)], axis=1)

    # ---- inverse
    def solve(self, target, **_):
        """Pulses for J0-J3 that put the fingertips at target (x, y, z), claw pointing
        straight down if the wrist allows, else tilted up to 25 degrees.
        -> {"pulses", "pred", "error", "down", "reachable"}"""
        best = None
        for tilt in (0, 5, 10, 15, 20, 25, -5, -10, -15, -20, -25):
            out = self._solve_at(target, 180.0 - tilt)
            if out["reachable"]:
                return out
            if best is None or out["error"] < best["error"]:
                best = out
        return best

    def _solve_at(self, target, a3):
        p = self.p
        x, y, z = (float(v) for v in target)
        dx, dy = x - p["bx"], y - p["by"]
        r = math.hypot(dx, dy)
        hd = math.degrees(math.atan2(dx, -dy))
        t = math.radians(a3)
        rw, zw = r - p["D"] * math.sin(t), z - p["D"] * math.cos(t) - p["A"]     # wrist point
        L = math.hypot(rw, zw)
        B, Cl = p["B"], p["C"]
        ok = abs(B - Cl) + 0.5 < L < B + Cl - 0.2
        L = min(max(L, abs(B - Cl) + 0.5), B + Cl - 0.2)
        ce = (L * L - B * B - Cl * Cl) / (2 * B * Cl)
        e = math.degrees(math.acos(min(1.0, max(-1.0, ce))))      # elbow bend, forward = +
        a1 = math.degrees(math.atan2(rw, zw)) - math.degrees(math.atan2(Cl * math.sin(math.radians(e)),
                                                                           B + Cl * math.cos(math.radians(e))))
        a2 = a1 + e
        J = np.array([p["o0"] + p["s0"] * hd * US_PER_DEG,
                      p["o1"] - a1 * US_PER_DEG,
                      p["o2"] + e * US_PER_DEG,
                      p["o3"] - (a3 - a2) * US_PER_DEG])
        inside = bool(np.all(J >= self.jmin) and np.all(J <= self.jmax))
        J = np.clip(J, self.jmin, self.jmax)
        pulses = [int(round(v)) for v in J]
        pred = self.forward(pulses)[0]
        err = float(np.linalg.norm(pred[:3] - np.array([x, y, z])))
        return {"pulses": pulses, "pred": pred.tolist(), "error": err, "down": float(pred[3]),
                "reachable": bool(ok and inside and err <= 1.0)}

    def reachable(self, x, y):
        return self.solve([x, y, 2.0])["reachable"] and self.solve([x, y, 8.0])["reachable"]


# ---------------------------------------------------------------- fitting
def _residuals(body, pts, w_down=0.15):
    P = np.array([q["p"] for q in pts], float)
    T = np.array([[q["x"], q["y"], 0.0] for q in pts], float)
    f = body.forward(P)
    _, _, _, a3 = body.angles(P)
    res = (f[:, :3] - T).ravel()
    return np.concatenate([res, w_down * (a3 - 180.0)])    # claw was pointing down at each touch


def fit(params, pts, jmin, jmax, iters=200):
    """Least squares (Levenberg-Marquardt) over the joint offsets, shoulder height
    and base position, for both turntable directions. -> (body, rms_cm, worst_cm)"""
    best = None
    for s0 in (1.0, -1.0):
        p = dict(params, s0=s0)
        x = np.array([p[k] for k in FIT_KEYS], float)
        lam = 1e-2

        def resid(xv):
            return _residuals(KinematicBody(dict(p, **dict(zip(FIT_KEYS, xv))), jmin, jmax), pts)

        r = resid(x)
        for _ in range(iters):
            Jm = np.zeros((len(r), len(x)))
            for i in range(len(x)):
                h = 1e-3 * max(1.0, abs(x[i]))
                xh = x.copy()
                xh[i] += h
                Jm[:, i] = (resid(xh) - r) / h
            A = Jm.T @ Jm
            g = Jm.T @ r
            step = np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-9), -g)
            xn = x + step
            rn = resid(xn)
            if rn @ rn < r @ r:
                x, r, lam = xn, rn, max(lam / 3, 1e-7)
                if np.linalg.norm(step) < 1e-6:
                    break
            else:
                lam *= 4
                if lam > 1e8:
                    break
        p.update(dict(zip(FIT_KEYS, x.tolist())))
        body = KinematicBody(p, jmin, jmax)
        pos = body.forward(np.array([q["p"] for q in pts], float))[:, :3]
        tgt = np.array([[q["x"], q["y"], 0.0] for q in pts])
        d = np.linalg.norm(pos - tgt, axis=1)
        rms, worst = float(np.sqrt(np.mean(d ** 2))), float(d.max())
        if best is None or rms < best[1]:
            best = (body, rms, worst)
    body, rms, worst = best
    body.p["fit_error"] = rms
    body.fit_error = rms
    return body, rms, worst


def load_points(path=None):
    path = path or C.path("touch")
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]

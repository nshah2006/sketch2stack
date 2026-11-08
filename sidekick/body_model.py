"""Body model: learns how the arm moves (handbook 2H).

Everything here is in FINGERTIP coordinates: each camera reading of the claw
marker is converted to where the fingertips are (perception.claw_tip), so a
claw that is a little tilted still lands its fingers on the target.

1. babble(): random walk over J0-J3 while the camera records the claw marker.
2. train(): small neural net, pulses -> marker x, y, z, down-ness.
3. BodyModel.solve(): gradient search through the net for the pulses that
   put the marker at a target with the claw pointing down.

Deviation from the handbook: babbling starts from (and returns to) the
`ready` pose instead of `home`. At home the claw points up, so the marker
faces away from the camera and babbling could never get its first reading.
"""
import json
import time

import numpy as np
import torch
from torch import nn

from . import config as C
from .perception import claw_tip

torch.set_num_threads(1)


# ===================================================================== reading the claw
def read_claw(source, n=5, timeout=1.5, marker_to_fingertip=9.0, forward=0.0, base=None):
    """Average n claw readings from an observation source (sim world or real vision).
    Returns the fingertip {x, y, z, down} or None if the marker was not seen."""
    got = []
    clock = getattr(source, "clock", None)
    t_end = (clock.time() if clock else time.monotonic()) + timeout
    misses = 0
    while len(got) < n:
        now = clock.time() if clock else time.monotonic()
        if now > t_end:
            break
        obs = source.read(timeout=0.5)
        if obs is None:
            continue
        if obs.claw is None:
            misses += 1
            if misses >= 2 * n:
                break
            continue
        got.append(obs.claw)
    if len(got) < max(2, n // 2):
        return None
    avg = {k: float(np.mean([g.get(k, 0.0) for g in got])) for k in ("x", "y", "z", "nx", "ny", "down")}
    return claw_tip(avg, marker_to_fingertip, forward, base)


# ===================================================================== babbling
def babble(arm, source, cfg, n=None, out_path=None, progress=None, stop=None, rng=None):
    """Random walk over J0-J3 (roll centered, claw open). Appends one JSON line per
    sample immediately, so it can be stopped and resumed."""
    n = n or cfg["babble_samples"]
    rng = rng or np.random.default_rng()
    out_path = out_path or C.babble_path(cfg)
    have = 0
    if out_path.exists():
        with open(out_path) as f:
            have = sum(1 for _ in f)
    ready = list(cfg["ready"])
    ready[4], ready[5] = 1500, cfg["claw_open"]
    lo, hi = list(cfg["joint_min"]), list(cfg["joint_max"])
    rng_us = cfg.get("babble_range", 0)
    if rng_us:                                   # stay in a box around ready (real arm: keeps it off the table)
        for j in range(4):
            lo[j], hi[j] = max(lo[j], ready[j] - rng_us), min(hi[j], ready[j] + rng_us)
    clock = arm.clock
    arm.move(ready)
    cur = list(ready)
    unseen, last_z, in_area = 0, None, 0
    with open(out_path, "a") as f:
        while have < n:
            if stop is not None and stop.is_set():
                break
            if last_z is not None and last_z < cfg["babble_min_height"]:
                if rng_us:                             # too low: straight back to ready
                    cur = list(ready)
                else:                                  # pull shoulder and elbow halfway home
                    for j in (1, 2):
                        cur[j] = cur[j] + (cfg["home"][j] - cur[j]) / 2
            else:
                for j in range(4):
                    cur[j] = float(np.clip(cur[j] + rng.normal(0, cfg["babble_step"]), lo[j], hi[j]))
            cur[4], cur[5] = 1500, cfg["claw_open"]
            arm.move(cur)
            clock.sleep(cfg["babble_settle"])
            m = read_claw(source, 5, marker_to_fingertip=cfg["marker_to_fingertip"],
                          forward=cfg.get("marker_forward", 0.0), base=cfg["layout"]["base"])
            if m is None:
                unseen += 1
                last_z = None
                if unseen >= 4:
                    arm.move(ready)
                    cur, unseen = list(ready), 0
                continue
            unseen = 0
            last_z = m["z"]
            line = {"p": [int(round(c)) for c in cur[:4]], "x": m["x"], "y": m["y"], "z": m["z"],
                    "down": m["down"], "t": clock.time()}
            f.write(json.dumps(line) + "\n")
            f.flush()
            have += 1
            if cfg.in_work_area(m["x"], m["y"]) and m["down"] > 0.8:
                in_area += 1
            if progress:
                progress(have, n, in_area, m["z"])
    arm.move(ready)
    return have


def load_samples(path=None):
    path = path or C.path("babble")
    P, Y = [], []
    with open(path) as f:
        for line in f:
            d = json.loads(line)
            P.append(d["p"])
            Y.append([d["x"], d["y"], d["z"], d["down"]])
    return np.array(P, np.float32), np.array(Y, np.float32)


# ===================================================================== network
class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.f = nn.Sequential(nn.Linear(4, 128), nn.SiLU(), nn.Linear(128, 128), nn.SiLU(),
                               nn.Linear(128, 128), nn.SiLU(), nn.Linear(128, 4))

    def forward(self, x):
        return self.f(x)


def train(P, Y, cfg, steps=3000, seed=0, log=print):
    """Train the forward model. Returns (BodyModel, held-out mean position error cm)."""
    g = torch.Generator().manual_seed(seed)
    torch.manual_seed(seed)
    n = len(P)
    idx = torch.randperm(n, generator=g).numpy()
    n_tr = int(round(n * 0.85))
    tr, te = idx[:n_tr], idx[n_tr:]
    X = (P - 1500.0) / 1000.0
    y_mean, y_std = Y[tr].mean(0), Y[tr].std(0) + 1e-6
    Ys = (Y - y_mean) / y_std
    Xt, Yt = torch.tensor(X), torch.tensor(Ys)
    net = Net()
    opt = torch.optim.Adam(net.parameters(), lr=3e-3)
    sched = torch.optim.lr_scheduler.ExponentialLR(opt, gamma=(0.1) ** (1 / steps))
    w = torch.tensor([1.0, 1.0, 1.0, 0.5])
    for s in range(steps):
        opt.zero_grad()
        loss = (((net(Xt[tr]) - Yt[tr]) ** 2) * w).mean()
        loss.backward()
        opt.step()
        sched.step()
        if log and (s + 1) % 1000 == 0:
            log(f"  step {s + 1}/{steps}  loss {loss.item():.4f}")
    body = BodyModel(net, y_mean, y_std, cfg["joint_min"][:4], cfg["joint_max"][:4], P, Y)
    err = None
    if len(te):
        pred = body.forward(P[te])
        err = float(np.mean(np.linalg.norm(pred[:, :3] - Y[te, :3], axis=1)))
    return body, err


class BodyModel:
    def __init__(self, net, y_mean, y_std, jmin, jmax, P, Y):
        self.net = net.eval()
        self.y_mean = np.asarray(y_mean, np.float32)
        self.y_std = np.asarray(y_std, np.float32)
        self.jmin = np.asarray(jmin, np.float32)
        self.jmax = np.asarray(jmax, np.float32)
        self.P = np.asarray(P, np.float32)
        self.Y = np.asarray(Y, np.float32)
        self._ym = torch.tensor(self.y_mean)
        self._ys = torch.tensor(self.y_std)

    # ---- persistence
    def save(self, path=None):
        path = path or C.path("body")
        torch.save({"state": self.net.state_dict(), "y_mean": self.y_mean, "y_std": self.y_std,
                    "jmin": self.jmin, "jmax": self.jmax, "P": self.P, "Y": self.Y}, path)
        return path

    @classmethod
    def load(cls, path=None):
        path = path or C.path("body")
        d = torch.load(path, weights_only=False)
        net = Net()
        net.load_state_dict(d["state"])
        return cls(net, d["y_mean"], d["y_std"], d["jmin"], d["jmax"], d["P"], d["Y"])

    # ---- prediction
    def forward(self, pulses):
        x = torch.tensor((np.asarray(pulses, np.float32).reshape(-1, 4) - 1500.0) / 1000.0)
        with torch.no_grad():
            y = self.net(x) * self._ys + self._ym
        return y.numpy()

    def solve(self, target, steps=150, starts=8):
        """Pulses for J0-J3 that put the marker at target (x, y, z) pointing down.
        -> {"pulses", "pred", "error", "down", "reachable"}"""
        target = np.asarray(target, np.float32)
        key = (tuple(np.round(target, 1).tolist()), steps, starts)
        cache = self.__dict__.setdefault("_cache", {})
        if key in cache:                        # planning asks about the same points a lot
            return dict(cache[key])
        d = np.linalg.norm(self.Y[:, :3] - target, axis=1)
        near = np.argsort(d)[:starts]
        lo = torch.tensor((self.jmin - 1500) / 1000)
        hi = torch.tensor((self.jmax - 1500) / 1000)
        q = torch.tensor((self.P[near] - 1500) / 1000, requires_grad=True)
        tgt = torch.tensor(target)
        opt = torch.optim.Adam([q], lr=0.05)
        margin = 0.05     # 50 us in scaled units
        best_loss = torch.full((len(near),), float("inf"))
        best_q = q.detach().clone()
        for _ in range(steps):
            opt.zero_grad()
            y = self.net(q) * self._ys + self._ym
            pos_err = ((y[:, :3] - tgt) ** 2).sum(1)
            down_pen = 30.0 * (1.0 - y[:, 3]) ** 2
            lim = torch.relu(margin - (q - lo)) + torch.relu(margin - (hi - q))
            lim_pen = 400.0 * (lim ** 2).sum(1)
            loss = pos_err + down_pen + lim_pen
            better = loss.detach() < best_loss
            best_loss = torch.where(better, loss.detach(), best_loss)
            best_q[better] = q.detach()[better]
            loss.sum().backward()
            opt.step()
            with torch.no_grad():
                q.data = torch.max(torch.min(q.data, hi), lo)
        i = int(torch.argmin(best_loss))
        pulses = (best_q[i].numpy() * 1000 + 1500).round().astype(int)
        pred = self.forward(pulses)[0]
        err = float(np.linalg.norm(pred[:3] - target))
        out = {"pulses": pulses.tolist(), "pred": pred.tolist(), "error": err,
               "down": float(pred[3]), "reachable": bool(err <= 1.5 and pred[3] >= 0.85)}
        if len(cache) > 20000:
            cache.clear()
        cache[key] = out
        return dict(out)

    def reachable(self, x, y):
        """Yes only if a babbled sample pointing down lies within 4 cm horizontally."""
        ok = self.Y[:, 3] > 0.8
        if not ok.any():
            return False
        dd = np.hypot(self.Y[ok, 0] - x, self.Y[ok, 1] - y)
        return bool(dd.min() <= 4.0)

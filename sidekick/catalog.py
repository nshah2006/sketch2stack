"""Block catalog: the real wooden blocks the team owns.

Measure the real blocks and edit sidekick_data/blocks.json (created by
`python -m sidekick.main setup`). Every block stands in one fixed upright
pose; the arm can turn it about the vertical axis (rot 0 or 90) but never
tips it over.

  size   [w, d, h] cm: w along x (left-right in the front view) at rot 0,
         d front-to-back, h height
  shape  box | cylinder | arch | roof   (front-view outline; cylinders look
         round from above)
  top    true if something can sit on it (a roof can't hold anything)
"""
import copy
import json

from . import config as C

DEFAULT_CATALOG = {
    "max_grip": 5.0,        # widest side the claw can close across, cm (about 70% of its opening)
    "types": [
        {"id": "cube", "name": "Cube", "shape": "box", "size": [3.0, 3.0, 3.0], "top": True,
         "colors": {"red": 2}},
        {"id": "pillar", "name": "Pillar", "shape": "box", "size": [3.0, 3.0, 6.0], "top": True,
         "colors": {"orange": 2}},
        {"id": "plank", "name": "Plank", "shape": "box", "size": [7.0, 3.0, 1.4], "top": True,
         "colors": {"red": 2}},
        {"id": "bar", "name": "Long bar", "shape": "box", "size": [10.0, 3.0, 1.4], "top": True,
         "colors": {"green": 2}},
        {"id": "cyl_short", "name": "Short cylinder", "shape": "cylinder", "size": [3.0, 3.0, 3.0],
         "top": True, "colors": {"blue": 2}},
        {"id": "cyl_tall", "name": "Tall cylinder", "shape": "cylinder", "size": [3.0, 3.0, 6.0],
         "top": True, "colors": {"red": 2}},
        {"id": "arch", "name": "Arch", "shape": "arch", "size": [6.0, 3.0, 3.0], "top": True,
         "colors": {"green": 2}},
        {"id": "roof", "name": "Roof", "shape": "roof", "size": [6.0, 3.0, 3.0], "top": False,
         "colors": {"yellow": 2}},
    ],
}


def fold180(a):
    """Fold an angle (deg) into -90..90 (rectangles look the same turned 180)."""
    return (a + 90.0) % 180.0 - 90.0


def angle_diff(a, b):
    return abs(fold180(a - b))


class Catalog:
    def __init__(self, data):
        self.data = data
        self.max_grip = float(data["max_grip"])
        self.types = {t["id"]: t for t in data["types"]}

    @classmethod
    def load(cls, data_dir=None):
        p = C.path("config", data_dir).parent / "blocks.json"
        if p.exists():
            with open(p) as f:
                return cls(json.load(f))
        return cls(copy.deepcopy(DEFAULT_CATALOG))

    def save(self, data_dir=None):
        p = C.path("config", data_dir).parent / "blocks.json"
        with open(p, "w") as f:
            json.dump(self.data, f, indent=2)
        return p

    # ---- geometry
    def size(self, tid):
        w, d, h = self.types[tid]["size"]
        return float(w), float(d), float(h)

    def footprint(self, tid, rot=0):
        """(along x, along y) in cm after turning by rot (0 or 90)."""
        w, d, _ = self.size(tid)
        return (d, w) if int(rot) % 180 == 90 else (w, d)

    def height(self, tid):
        return self.size(tid)[2]

    def round_(self, tid):
        return self.types[tid]["shape"] == "cylinder"

    def flat_top(self, tid):
        return bool(self.types[tid].get("top", True))

    # ---- detection
    def classify(self, color, long_cm, short_cm, round_=None, tol=0.9):
        """Match a measured top-view footprint + color to a type. -> id or None.
        If two types share color and footprint, returns the first and
        `ambiguities()` reports it at setup."""
        best, best_err = None, tol
        for tid, t in self.types.items():
            if color not in t["colors"]:
                continue
            if round_ is not None and round_ != self.round_(tid):
                continue
            w, d, _ = self.size(tid)
            err = max(abs(max(w, d) - long_cm), abs(min(w, d) - short_cm))
            if err < best_err:
                best, best_err = tid, err
        return best

    def ambiguities(self):
        """Pairs the overhead camera can't tell apart (same color, outline and footprint)."""
        out = []
        ids = list(self.types)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if self.round_(a) != self.round_(b):
                    continue
                wa, da, _ = self.size(a)
                wb, db, _ = self.size(b)
                same_fp = abs(max(wa, da) - max(wb, db)) < 0.9 and abs(min(wa, da) - min(wb, db)) < 0.9
                common = set(self.types[a]["colors"]) & set(self.types[b]["colors"])
                if same_fp and common:
                    out.append((a, b, sorted(common)))
        return out

    # ---- gripping
    def grippable_axes(self, tid):
        """Block axes the claw can close across: 'y' (across d) and/or 'x' (across w).
        Arches and roofs only have flat vertical faces front and back."""
        w, d, _ = self.size(tid)
        shape = self.types[tid]["shape"]
        axes = []
        if d <= self.max_grip:
            axes.append("y")
        if w <= self.max_grip and shape not in ("arch", "roof"):
            axes.append("x")
        return axes

    def count(self, tid):
        """How many of this shape the team owns (all colors)."""
        t = self.types[tid]
        return int(t.get("count", sum(t["colors"].values())))

    def public(self):
        return {"max_grip": self.max_grip,
                "types": [{"id": t["id"], "name": t.get("name", t["id"]), "shape": t["shape"],
                           "size": t["size"], "top": t.get("top", True), "colors": t["colors"],
                           "count": self.count(t["id"])}
                          for t in self.data["types"]]}


def block_yaw_from_long_axis(long_axis_deg, tid, catalog):
    """A detection reports the angle of its long side; convert to the block's
    yaw (angle of its w side). Square and round blocks: same thing."""
    w, d, _ = catalog.size(tid)
    return fold180(long_axis_deg if w >= d else long_axis_deg + 90.0)

"""Turn the user's front-view drawing into an ordered 3D build plan.

Design JSON (what the UI sends):
  {"blocks": [{"type": "cube", "color": "red", "x": 3.0, "depth": 0, "rot": 0, "z_hint": 0}, ...]}

  x       left edge, cm from the left end of the build strip
  depth   front-to-back slot (0 = front, human side); each slot is depth_slot cm
  rot     0: the block's w side runs left-right; 90: turned a quarter
  z_hint  where the user dropped it (cm); only used to settle blocks in order

How height and depth are worked out:
  * Height: gravity. Blocks settle in z_hint order; each one comes to rest on
    the highest block under its footprint, or the table. So the user only
    places blocks left-right and the planner finds every block's height.
  * Depth: a front view can't show depth, so every block starts in the front
    slot (a wall) and the user can push one back a slot. The planner then
    works in true 3D footprints, so a block in the back slot is supported only
    by blocks that are really under it.
"""

def _rect(b, cfg, catalog):
    """Footprint rectangle in strip coordinates: (x0, x1, y0, y1) in cm."""
    fx, fy = catalog.footprint(b["type"], b.get("rot", 0))
    x0 = float(b["x"])
    y0 = int(b.get("depth", 0)) * cfg["depth_slot"]
    return (x0, x0 + fx, y0, y0 + fy)


def _overlap(a, b):
    ox = min(a[1], b[1]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[2], b[2])
    return max(0.0, ox) * max(0.0, oy) if ox > 0.2 and oy > 0.2 else 0.0


def settle(design, cfg, catalog):
    """Gravity. -> list of {i, rect, z, h, supports:[i], area_supported}"""
    blocks = design.get("blocks", [])
    order = sorted(range(len(blocks)), key=lambda i: (float(blocks[i].get("z_hint", 0)), i))
    placed = []
    by_i = {}
    for i in order:
        b = blocks[i]
        if b.get("type") not in catalog.types:
            continue
        r = _rect(b, cfg, catalog)
        h = catalog.height(b["type"])
        under = [(p, _overlap(r, p["rect"])) for p in placed]
        under = [(p, a) for p, a in under if a > 0]
        z = max((p["z"] + p["h"] for p, _ in under), default=0.0)
        supports = [p for p, a in under if abs(p["z"] + p["h"] - z) < 0.3]
        area = sum(_overlap(r, p["rect"]) for p in supports)
        rec = {"i": i, "rect": r, "z": z, "h": h, "supports": [p["i"] for p in supports],
               "area": (r[1] - r[0]) * (r[3] - r[2]), "supported": area}
        placed.append(rec)
        by_i[i] = rec
    return by_i


def validate(design, cfg, catalog):
    """-> (settled, problems). problem: {"index", "level": "error"|"warn", "msg"}"""
    x0, x1, yf, yb = cfg["layout"]["build_area"]
    width, depth = x1 - x0, yb - yf
    blocks = design.get("blocks", [])
    probs = []
    for i, b in enumerate(blocks):
        t = catalog.types.get(b.get("type"))
        if t is None:
            probs.append({"index": i, "level": "error", "msg": f"unknown block type {b.get('type')}"})
        elif b.get("color") not in t["colors"]:
            probs.append({"index": i, "level": "error", "msg": f"no {b.get('color')} {t['name']} blocks"})
    st = settle(design, cfg, catalog)
    for i, s in st.items():
        b = blocks[i]
        rx0, rx1, ry0, ry1 = s["rect"]
        if rx0 < -0.01 or rx1 > width + 0.01:
            probs.append({"index": i, "level": "error", "msg": "sticks out of the build strip (left/right)"})
        if ry1 > depth + 0.01:
            probs.append({"index": i, "level": "error", "msg": "too far back for the build strip"})
        if s["z"] + s["h"] > cfg["max_build_height"] + 0.01:
            probs.append({"index": i, "level": "error",
                          "msg": f"stack too tall (over {cfg['max_build_height']:.0f} cm)"})
        if s["z"] > 0:
            for j in s["supports"]:
                if not catalog.flat_top(blocks[j]["type"]):
                    probs.append({"index": i, "level": "error",
                                  "msg": f"can't sit on a {catalog.types[blocks[j]['type']]['name'].lower()}"})
            frac = s["supported"] / s["area"]
            if frac < 0.25 or not _center_supported(s, st):
                probs.append({"index": i, "level": "error", "msg": "would tip over: center isn't supported"})
            elif frac < 0.5:
                probs.append({"index": i, "level": "warn", "msg": "less than half supported; may wobble"})
    need = {}
    for b in blocks:
        k = (b.get("type"), b.get("color"))
        need[k] = need.get(k, 0) + 1
    for (tid, color), n in need.items():
        have = catalog.types.get(tid, {}).get("colors", {}).get(color, 0)
        if n > have:
            probs.append({"index": None, "level": "error",
                          "msg": f"needs {n} {color} {tid} but only {have} owned"})
    return st, probs


def _center_supported(s, st):
    cx = (s["rect"][0] + s["rect"][1]) / 2
    cy = (s["rect"][2] + s["rect"][3]) / 2
    xs, ys = [], []
    for j in s["supports"]:
        r = st[j]["rect"]
        xs += [r[0], r[1]]
        ys += [r[2], r[3]]
    if not xs:
        return False
    return min(xs) - 0.2 <= cx <= max(xs) + 0.2 and min(ys) - 0.2 <= cy <= max(ys) + 0.2


def plan(design, cfg, catalog, body=None):
    """Ordered placements: lower blocks first; at the same height, back slots
    first (the claw never reaches over a finished front row), then left to right.
    -> (steps, problems)"""
    st, probs = validate(design, cfg, catalog)
    blocks = design.get("blocks", [])
    x0, _, yf, _ = cfg["layout"]["build_area"]
    order = sorted(st, key=lambda i: (round(st[i]["z"], 1), -st[i]["rect"][2], st[i]["rect"][0]))
    steps = []
    done = []
    for i in order:
        b, s = blocks[i], st[i]
        rx0, rx1, ry0, ry1 = s["rect"]
        x, y = x0 + (rx0 + rx1) / 2, yf + (ry0 + ry1) / 2
        yaw = 90.0 if int(b.get("rot", 0)) % 180 == 90 else 0.0
        grip = choose_grip(b, s, [st[j] for j in done], catalog)
        step = {"index": i, "type": b["type"], "color": b["color"], "x": round(x, 2), "y": round(y, 2),
                "z": round(s["z"], 2), "h": s["h"], "yaw": yaw, "grip": grip}
        if body is not None:
            for name, z in (("place", cfg.grasp_z(s["z"], s["h"])), ("hover", cfg.hover_z(s["z"], s["h"]))):
                sol = body.solve([x, y, z])
                if not sol["reachable"]:
                    probs.append({"index": i, "level": "error",
                                  "msg": f"arm can't reach the {name} point ({sol['error']:.1f} cm off)"})
                    break
        steps.append(step)
        done.append(i)
    return steps, probs


def choose_grip(block, s, placed, catalog):
    """Which table axis the fingers close along: 'y' (fingers in front and
    behind the block) or 'x' (left and right). Prefer a side with no block
    already standing next to it, so a finger doesn't hit a neighbour."""
    axes = catalog.grippable_axes(block["type"])
    rot = int(block.get("rot", 0)) % 180 == 90
    table_axes = [("x" if a == "y" else "y") if rot else a for a in axes] or ["y"]
    r, z0, z1 = s["rect"], s["z"], s["z"] + s["h"]

    def blocked(axis):
        for p in placed:
            if p["z"] >= z1 - 0.2 or p["z"] + p["h"] <= z0 + 0.2:
                continue                       # not at the same height
            q = p["rect"]
            if axis == "y":                    # fingers front/back: neighbour directly in front or behind
                xo = min(r[1], q[1]) - max(r[0], q[0]) > 0.2
                gap = min(abs(q[2] - r[3]), abs(r[2] - q[3]))
                if xo and gap < 1.5:
                    return True
            else:
                yo = min(r[3], q[3]) - max(r[2], q[2]) > 0.2
                gap = min(abs(q[0] - r[1]), abs(r[0] - q[1]))
                if yo and gap < 1.5:
                    return True
        return False

    for a in table_axes:
        if not blocked(a):
            return a
    return table_axes[0]


def grid_info(cfg):
    x0, x1, yf, yb = cfg["layout"]["build_area"]
    return {"width": x1 - x0, "depth": yb - yf, "slots": max(1, int((yb - yf) // cfg["depth_slot"])),
            "max_height": cfg["max_build_height"], "depth_slot": cfg["depth_slot"]}

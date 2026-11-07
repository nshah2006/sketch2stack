"""Glue between the 3D web app (frontend/) and the planner.

The app describes a build as blocks in "block units" with y up:
    {id, x, y, z, size: [w, h, d], color, shape, type, pose, rot}
    x, y, z = min corner; 1 unit = UNIT cm; z = depth (0 = front row)
The planner uses a front-view design in cm (planner.py). This module converts
between the two, scores stability, and turns a sketch into candidate builds.

A sketch can be read at two scales (see _fit):
  fixed  the sketch board IS the build strip, so the size drawn is the size
         built and the board's ruler is true. This is the default.
  fit    the drawing is scaled up until it fills the strip, so only its aspect
         ratio survives. Handy for a quick doodle.
"""
import math

import cv2
import numpy as np

from . import dictation, planner, presets

UNIT = 3.0   # cm per app block unit (one cube)

SHAPE = {"cube": "cube", "pillar": "cube", "plank": "plank", "bar": "brick",
         "cyl_short": "cylinder", "cyl_tall": "cylinder", "arch": "arch", "roof": "triangle"}


# ===================================================================== conversion
def design_to_build(design, cfg, catalog, bid, name, blurb, source, body=None):
    settled = planner.settle(design, cfg, catalog)
    steps, probs = planner.plan(design, cfg, catalog, body)
    blocks = []
    for i, b in enumerate(design["blocks"]):
        if i not in settled:
            continue
        s = settled[i]
        x0, x1, y0, y1 = s["rect"]
        blocks.append({
            "id": f"{bid}-{i}", "x": round(x0 / UNIT, 3), "y": round(s["z"] / UNIT, 3), "z": round(y0 / UNIT, 3),
            "size": [round((x1 - x0) / UNIT, 3), round(s["h"] / UNIT, 3), round((y1 - y0) / UNIT, 3)],
            "color": b.get("color") or next(iter(catalog.types[b["type"]]["colors"]), "red"),
            "shape": SHAPE.get(b["type"], "cube"), "type": b["type"],
            "pose": int(b.get("pose", 0)), "rot": int(b.get("rot", 0)),
        })
    return {"id": bid, "name": name, "blurb": blurb, "source": source,
            "stability": stability(settled, probs), "blocks": blocks,
            "problems": probs, "order": [st["index"] for st in steps]}


def build_to_design(build):
    """App build -> planner design. Block i of the design is block i of the build,
    so the planner's step indexes map straight back to the app's block ids."""
    out = []
    for blk in build.get("blocks", []):
        if not blk.get("type"):
            raise ValueError("This build has no robot block types (made by the old mock "
                             "generator). Regenerate it from the sketch.")
        out.append({"type": blk["type"], "color": blk.get("color"), "pose": int(blk.get("pose", 0)),
                    "rot": int(blk.get("rot", 0)), "x": float(blk["x"]) * UNIT,
                    "depth": int(round(float(blk.get("z", 0)) * UNIT / 3.0)),
                    "z_hint": float(blk.get("y", 0)) * UNIT})
    return {"blocks": out}


def stability(settled, probs):
    """0-100: errors sink it, wobbles and tall narrow stacks cost points."""
    if any(p["level"] == "error" for p in probs):
        return 0
    score = 100.0 - 10 * sum(p["level"] == "warn" for p in probs)
    if settled:
        top = max(s["z"] + s["h"] for s in settled.values())
        xs = [v for s in settled.values() for v in s["rect"][:2]]
        width = max(xs) - min(xs)
        score -= max(0.0, top / max(width, 1.0) - 1.0) * 12      # taller than wide
        score -= 2.0 * sum(1 for s in settled.values() if s["z"] > 0)
    return int(max(5, min(99, round(score))))


# ===================================================================== sketch -> silhouette
def raster_size(cfg, w=240):
    """Raster size matching the build strip's aspect, so one pixel is square in
    cm and the sketch board can be the strip 1:1."""
    gi = planner.grid_info(cfg)
    return w, max(1, int(round(w * gi["max_height"] / gi["width"])))


def silhouette(strokes, w=240, h=144):
    """Rasterize normalized strokes; fill closed shapes. -> uint8 mask (or None)."""
    ink = np.zeros((h, w), np.uint8)
    for s in strokes or []:
        pts = np.array([[p[0] * w, p[1] * h] for p in s.get("points", [])], np.int32)
        if len(pts) == 0:
            continue
        thick = max(2, int(round(s.get("width", 4) * w / 500)))
        color = 0 if s.get("erase") else 255
        if s.get("erase"):
            thick *= 3
        cv2.polylines(ink, [pts.reshape(-1, 1, 2)], False, color, thick)
        if len(pts) == 1:
            cv2.circle(ink, tuple(pts[0]), thick, color, -1)
    if ink.max() == 0:
        return None
    closed = cv2.dilate(ink, np.ones((7, 7), np.uint8))          # close small gaps between lines
    outside = np.zeros((h + 2, w + 2), np.uint8)
    flood = closed.copy()
    cv2.floodFill(flood, outside, (0, 0), 128)
    mask = np.where(flood == 128, 0, 255).astype(np.uint8)      # ink + everything it encloses
    if mask.sum() < closed.sum() * 1.3:                          # nothing closed: use thick ink
        mask = cv2.dilate(ink, np.ones((15, 15), np.uint8))
    return mask


def _fit(mask, cfg, fit_strip=False):
    """Crop to the drawing. -> (cropped mask, cm per pixel)

    fit_strip False: fixed scale. The whole board is the build strip, so the
                     size the user drew is the size that gets built.
    fit_strip True:  scale the drawing up until it fills the strip, so only its
                     aspect ratio survives.
    """
    ys, xs = np.nonzero(mask)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    gi = planner.grid_info(cfg)
    if fit_strip:
        s = min(gi["width"] / crop.shape[1], gi["max_height"] / crop.shape[0])
    else:
        s = gi["width"] / mask.shape[1]
    return crop, s


def _cell(crop, s, x0, x1, z0, z1):
    """Fraction of a cm rectangle (x right, z up from the table) that is drawn."""
    H = crop.shape[0]
    c0, c1 = int(x0 / s), max(int(x0 / s) + 1, int(x1 / s))
    r1, r0 = H - int(z0 / s), H - max(int(z0 / s) + 1, int(z1 / s))
    r0, r1 = max(0, r0), min(H, r1)
    c0, c1 = max(0, c0), min(crop.shape[1], c1)
    if r1 <= r0 or c1 <= c0:
        return 0.0
    return float(crop[r0:r1, c0:c1].mean() / 255.0)


# ===================================================================== tiling
def _cover(length, pieces, stock):
    """Pick pieces (name, width) whose widths add up closest to `length`,
    using at most stock[name] of each. -> list of names"""
    best = ([], length)
    items = [(n, wd) for n, wd in pieces if stock.get(n, 0) > 0]

    def rec(i, left, used, chosen):
        nonlocal best
        if abs(left) < abs(best[1]) - 1e-6 or (abs(abs(left) - abs(best[1])) < 1e-6 and len(chosen) < len(best[0])):
            if left > -1.6:                                    # may overhang by half a cube at most
                best = (list(chosen), left)
        if i >= len(items) or left < 1.4:
            return
        n, wd = items[i]
        for k in range(min(stock[n] - used.get(n, 0), int(left // wd) + 1), -1, -1):
            if k:
                used[n] = used.get(n, 0) + k
                chosen.extend([n] * k)
            rec(i + 1, left - k * wd, used, chosen)
            if k:
                used[n] -= k
                del chosen[len(chosen) - k:]
    rec(0, length, {}, [])
    return best[0]


def tile(mask, cfg, catalog, style="closest", fit_strip=False):
    """Front-view mask -> design built from rows of 3 cm tall pieces, an arch
    over a doorway gap, and a roof on a pointed top."""
    crop, s = _fit(mask, cfg, fit_strip)
    width_cm, height_cm = crop.shape[1] * s, crop.shape[0] * s
    stock = {tid: catalog.count(tid) for tid in catalog.types}
    # Per-colour stock, so a build only asks for blocks we actually have. The
    # first colour listed for a type is often nearly out (1 orange pillar) while
    # most of the pile is unpainted, so always reach for the fullest pile.
    left = {tid: dict(t["colors"]) for tid, t in catalog.types.items()}

    def take(tid):
        """Reserve one block of this type; -> the colour to ask the human for."""
        pool = left.get(tid) or {}
        best = max(pool, key=pool.get, default=None)
        if best is None or pool[best] <= 0:
            return next(iter(catalog.types[tid]["colors"]), "red")   # out of stock: name it anyway
        pool[best] -= 1
        return best
    # 3 cm tall pieces for a row: (name, width) with how to place them
    row_pieces = {
        "closest": [("bar", 10.0), ("plank", 7.0), ("pillar", 6.0), ("cube", 3.0), ("cyl_short", 3.0)],
        "simple": [("cube", 3.0), ("cyl_short", 3.0), ("pillar", 6.0)],
    }[style]
    place = {"bar": (1, 0), "plank": (1, 0), "pillar": (1, 90), "cube": (0, 0), "cyl_short": (0, 0)}  # (pose, rot)
    rows = max(1, min(int(round(height_cm / 3.0)), int(cfg["max_build_height"] // 3)))
    cell = 1.5
    ncell = int(math.floor(width_cm / cell + 1e-6))
    blocks, support = [], None
    for r in range(rows):
        z0 = r * 3.0
        occ = [_cell(crop, s, c * cell, (c + 1) * cell, z0, z0 + 3.0) >= 0.45 for c in range(ncell)]
        if support is not None:
            occ = [o and support[c] for c, o in enumerate(occ)]
        runs, c = [], 0
        while c < ncell:
            if occ[c]:
                c1 = c
                while c1 < ncell and occ[c1]:
                    c1 += 1
                runs.append((c * cell, c1 * cell))
                c = c1
            else:
                c += 1
        if not runs:
            break
        # pointed top: the upper half of this row is much narrower than the lower half
        lower = sum(_cell(crop, s, c * cell, (c + 1) * cell, z0, z0 + 1.5) >= 0.45 for c in range(ncell))
        upper = sum(_cell(crop, s, c * cell, (c + 1) * cell, z0 + 1.5, z0 + 3.0) >= 0.45 for c in range(ncell))
        last = r == rows - 1 or not any(_cell(crop, s, c * cell, (c + 1) * cell, z0 + 3.0, z0 + 6.0) >= 0.45
                                        for c in range(ncell))
        if last and stock.get("roof", 0) and lower >= 3 and upper <= 0.65 * lower:
            a, b = max(runs, key=lambda t: t[1] - t[0])
            rw = catalog.size("roof")[0]
            x = max(0.0, min(width_cm - rw, (a + b) / 2 - rw / 2))
            blocks.append({"type": "roof", "color": take("roof"), "x": round(x * 2) / 2, "z_hint": z0})
            stock["roof"] -= 1
            break
        new_support = [False] * ncell
        # doorway: a short gap in the bottom row bridged by the row above -> arch
        if r == 0 and stock.get("arch", 0) and len(runs) >= 2:
            aw = catalog.size("arch")[0]
            for (a0, a1), (b0, b1) in zip(runs, runs[1:]):
                gap = b0 - a1
                above = all(_cell(crop, s, x, x + cell, 3.0, 6.0) >= 0.45 for x in np.arange(a1, b0, cell))
                if 0 < gap <= 3.5 and above and stock["arch"]:
                    cx = (a1 + b0) / 2
                    ax = round((cx - aw / 2) * 2) / 2
                    blocks.append({"type": "arch", "color": take("arch"), "x": ax, "z_hint": 0})
                    stock["arch"] -= 1
                    for c in range(ncell):
                        if ax - 0.01 <= c * cell < ax + aw - 0.01:
                            new_support[c] = True
                    runs = [(x0, min(x1, ax)) if x0 < ax else (max(x0, ax + aw), x1) for x0, x1 in runs]
                    runs = [(x0, x1) for x0, x1 in runs if x1 - x0 >= 1.4]
                    break
        for a, b in runs:
            names = _cover(b - a, row_pieces, stock)
            x = a + max(0.0, ((b - a) - sum(dict(row_pieces)[n] for n in names)) / 2)
            for n in names:
                pose, rot = place[n]
                wd = catalog.footprint(n, rot, pose)[0]
                blocks.append({"type": n, "color": take(n), "pose": pose, "rot": rot,
                               "x": round(x * 2) / 2, "z_hint": z0})
                stock[n] -= 1
                for c in range(ncell):
                    if x - 0.01 <= c * cell + cell / 2 <= x + wd + 0.01:
                        new_support[c] = True
                x += wd
        support = new_support
    for b in blocks:
        b.setdefault("depth", 0)
        b.setdefault("pose", 0)
        b.setdefault("rot", 0)
    return {"blocks": blocks}


def _valid(design, cfg, catalog, body):
    _, probs = planner.plan(design, cfg, catalog, body)
    return not any(p["level"] == "error" for p in probs)


def _trim(design, cfg, catalog, body):
    """Drop blocks from the top until the planner accepts the build."""
    d = {"blocks": list(design["blocks"])}
    while d["blocks"] and not _valid(d, cfg, catalog, body):
        st = planner.settle(d, cfg, catalog)
        top = max(st, key=lambda i: st[i]["z"])
        d["blocks"].pop(top)
    return d


def _iou(a, b):
    a = cv2.resize(a, (64, 48)) > 127
    b = cv2.resize(b, (64, 48)) > 127
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 0.0


def preset_mask(design, cfg, catalog):
    """Front-view silhouette of a design (for matching a sketch to presets)."""
    st = planner.settle(design, cfg, catalog)
    if not st:
        return None
    k = 10
    W = int(max(s["rect"][1] for s in st.values()) * k) + 2
    H = int(max(s["z"] + s["h"] for s in st.values()) * k) + 2
    m = np.zeros((H, W), np.uint8)
    for i, s in st.items():
        x0, x1 = int(s["rect"][0] * k), int(s["rect"][1] * k)
        z0, z1 = int(s["z"] * k), int((s["z"] + s["h"]) * k)
        if design["blocks"][i]["type"] == "roof":
            pts = np.array([[x0, H - z0], [x1, H - z0], [(x0 + x1) // 2, H - z1]], np.int32)
            cv2.fillConvexPoly(m, pts, 255)
        else:
            m[H - z1:H - z0, x0:x1] = 255
    ys, xs = np.nonzero(m)
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def generate(strokes, prompt, cfg, catalog, body=None, limit=4, fit_strip=False):
    """Sketch -> up to `limit` buildable interpretations, best first.

    fit_strip False (default): the board is the strip, so what the user drew at
    6 cm is built at 6 cm. True: scale the drawing up to fill the strip."""
    mask = silhouette(strokes, *raster_size(cfg))
    out = []
    if mask is not None:
        crop, _ = _fit(mask, cfg, fit_strip=True)   # shape only, for preset matching
        for style, name, blurb in (
                ("closest", "Closest to your sketch", "Rows of the longest pieces that fit your outline."),
                ("simple", "Simple blocks", "Only cubes, cylinders and pillars; easiest for the arm.")):
            d = _trim(tile(mask, cfg, catalog, style, fit_strip), cfg, catalog, body)
            if d["blocks"] and not any(_same(d, o["_design"]) for o in out):
                out.append({"_design": d, "name": name, "blurb": blurb, "source": "sketch",
                            "score": 1.0 if style == "closest" else 0.9})
        ranked = sorted(presets.PRESETS, key=lambda p: -_iou(crop, preset_mask(p, cfg, catalog)))
    else:
        ranked = list(presets.PRESETS)
    words = (prompt or "").lower()
    ranked.sort(key=lambda p: 0 if p["name"].lower() in words or p["id"] in words else 1)
    for p in ranked:
        if len(out) >= limit:
            break
        if _valid(p, cfg, catalog, body):
            out.append({"_design": p, "name": f"Preset: {p['name']}", "blurb": p["desc"], "source": "preset",
                        "score": 0.5})
    builds = []
    for k, o in enumerate(out[:limit]):
        bid = f"{o['source']}-{k}-{abs(hash(str(o['_design']['blocks']))) % 10**6}"
        builds.append(design_to_build(o["_design"], cfg, catalog, bid, o["name"], o["blurb"], o["source"], body))
    return builds


def _same(a, b):
    key = lambda d: sorted((x["type"], round(x["x"], 1), round(x.get("z_hint", 0), 1)) for x in d["blocks"])
    return key(a) == key(b)


def preset_builds(cfg, catalog, body=None):
    return [design_to_build(p, cfg, catalog, f"preset-{p['id']}", p["name"], p["desc"], "preset", body)
            for p in presets.PRESETS]


def dictate(text, build, cfg, catalog, body=None):
    """Typed/spoken request -> {"reply", "builds": [app build]} (empty builds = nothing to show).
    `build` is the app build on screen, for edits like "taller"."""
    current = build_to_design(build) if build and build.get("blocks") else None

    def simpler(cur):
        # preset_mask is a cropped silhouette, not a full sketch board, so the
        # fixed scale doesn't apply: scale it to fit and keep the design's shape.
        mask = preset_mask(cur, cfg, catalog)
        return _trim(tile(mask, cfg, catalog, "simple", fit_strip=True),
                     cfg, catalog, body) if mask is not None else None

    res = dictation.parse(text, catalog, cfg, current, body, simpler)
    d = res["design"]
    if not d or not d["blocks"]:
        return {"reply": res["reply"], "builds": []}
    kept = _trim(d, cfg, catalog, body)
    _, probs = planner.plan(d, cfg, catalog, body)
    why = next((p["msg"] for p in probs if p["level"] == "error"), "it doesn't fit")
    reply = res["reply"]
    if not kept["blocks"]:
        return {"reply": f"That can't be built: {why}", "builds": []}
    if len(kept["blocks"]) < len(d["blocks"]):
        names = {}
        for b in kept["blocks"]:
            nm_ = catalog.types[b["type"]].get("name", b["type"]).lower()
            names[nm_] = names.get(nm_, 0) + 1
        have = ", ".join(f"{n} {k}" + ("s" if n > 1 else "") for k, n in names.items())
        reply = (f"That doesn't fully fit ({why}). I kept {have} and dropped "
                 f"{len(d['blocks']) - len(kept['blocks'])}.")
    bid = f"voice-{abs(hash(str(kept['blocks']))) % 10**6}"
    return {"reply": reply, "builds": [design_to_build(kept, cfg, catalog, bid, "From your request",
                                                       text.strip()[:80], "sketch", body)]}

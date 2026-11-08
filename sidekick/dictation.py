"""Typed/spoken request -> design. Small keyword grammar, no network.

  "a plank and a roof on top"   a plank, then a roof sitting on it
  "two cubes with a roof on top"  roof centered over both cubes
  "a roof on top of a cube"     same idea, base named second
  "make a house"                a preset (only when no block words are used)
  "taller" / "fewer blocks" / "swap red for blue" / "why"   edits of the current build

Counts come from the catalog (blocks.json: types[].colors = {color: count}), never
from this file. "wood"/"wooden"/"brown"/"plain"/"natural" mean natural, the unpainted wood (orange is paint).
The result is a planner design; webapi turns it into app blocks and checks it.
"""
import json
import re
import urllib.error
import urllib.request

from . import envfile, planner, presets

NOUNS = {   # catalog id -> words that name it (plural 's' is handled)
    "cube": ["cube", "block", "square", "box", "boxes"],
    "pillar": ["pillar", "column", "post"],
    "plank": ["plank", "board"],
    "bar": ["bar", "beam"],
    "cyl_short": ["cylinder", "can", "barrel"],
    "cyl_tall": ["tall cylinder", "tall can"],
    "arch": ["arch", "arches", "gate", "doorway"],
    "roof": ["roof", "triangle"],
}
COLORS = ["red", "orange", "green", "blue", "yellow", "purple", "natural", "white", "pink"]
COLOR_ALIAS = {"wood": "natural", "wooden": "natural", "brown": "natural", "plain": "natural", "violet": "purple"}
NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "pair": 2, "couple": 2, "three": 3, "few": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
        "nineteen": 19, "twenty": 20}
GAP = 0.0                    # cm between blocks placed side by side


class Stock:
    """Remaining blocks per (type, color), from the catalog. Colors fill natural (wood) first."""

    def __init__(self, catalog, design=None):
        self.left = {(tid, c): int(n) for tid, t in catalog.types.items() for c, n in t["colors"].items()}
        for b in (design or {}).get("blocks", []):
            k = (b["type"], b.get("color"))
            if k in self.left:
                self.left[k] -= 1

    def colors(self, tid):
        return [c for (t, c) in self.left if t == tid]

    def take(self, tid, color=None):
        """-> color or None. A named color is exact; otherwise natural (wood) first, then the fullest."""
        if color:
            if self.left.get((tid, color), 0) > 0:
                self.left[(tid, color)] -= 1
                return color
            return None
        opts = sorted(self.colors(tid), key=lambda c: (c != "natural", -self.left[(tid, c)]))
        for c in opts:
            if self.left[(tid, c)] > 0:
                self.left[(tid, c)] -= 1
                return c
        return None

    def total(self, tid, color=None):
        return sum(max(0, n) for (t, c), n in self.left.items() if t == tid and (color in (None, c)))


def _noun_re(catalog):
    words = []
    for tid, ws in NOUNS.items():
        if tid in catalog.types:
            words += [(w, tid) for w in ws]
    words.sort(key=lambda p: -len(p[0]))     # "tall cylinder" before "cylinder"
    pat = "|".join(re.escape(w) + "s?" for w, _ in words)
    return re.compile(r"\b(" + pat + r")\b"), dict(words)


def _count_color(seg):
    """Count and color named in the few words just before a noun."""
    words = re.findall(r"[a-z0-9]+", seg.lower())[-4:]
    n, color, plural_hint = None, None, False
    for w in words:
        if w.isdigit():
            n = int(w)
        elif w in NUMS:
            n = NUMS[w]
        elif w in COLORS:
            color = w
        elif w in COLOR_ALIAS:
            color = COLOR_ALIAS[w]
    return n, color


def _entries(text, catalog):
    """Text -> (items, conns). item = {tid, n, color, ref}; conns[i] joins item i to i+1:
    side (next to), on_next (i sits on i+1, with everything side-joined to i), on_prev (i+1 sits on i).
    ref = "the plank": points at a block already named, not a new one."""
    rx, table = _noun_re(catalog)
    found = list(rx.finditer(text))
    if not found:
        return [], []
    segs = [text[:found[0].start()]] + [text[found[i].end():found[i + 1].start()] for i in range(len(found) - 1)] \
        + [text[found[-1].end():]]
    items, seen = [], set()
    for i, m in enumerate(found):
        word = m.group(1)
        base = word[:-1] if word.endswith("s") and word not in table else word
        tid = table.get(word) or table.get(base) or table[word.rstrip("s")]
        n, color = _count_color(segs[i])
        if n is None:
            n = 2 if word not in table and word.endswith("s") else 1
        tall = re.search(r"\btall\b", segs[i][-12:])
        if tid == "cube" and tall and "pillar" in catalog.types:
            tid = "pillar"
        if tid == "cyl_short" and tall and "cyl_tall" in catalog.types:
            tid = "cyl_tall"
        ref = bool(re.search(r"\bthe\b(\s+\w+)?\s*$", segs[i])) and tid in seen
        seen.add(tid)
        items.append({"tid": tid, "n": max(1, min(n, 20)), "color": color, "ref": ref})

    def norm(t):
        t = re.sub(r"\b(?:on|to|at) the (left|right)(?: side)?(?: of)?\b", lambda m: f" {m.group(1).upper()}OF ", t)
        t = re.sub(r"\b(left|right) of\b", lambda m: f" {m.group(1).upper()}OF ", t)
        t = re.sub(r"\bon top of\b", " ONOF ", t)
        t = re.sub(r"\bon top\b", " ONTOP ", t)
        return re.sub(r"\b(onto|over|above|atop|upon|on)\b", " ONOF ", t)

    conns = []
    for i in range(len(items) - 1):
        t = norm(segs[i + 1])
        if "RIGHTOF" in t:              # "X to the right of Y": X goes after Y
            conns.append("beside_r")
        elif "LEFTOF" in t:             # "X to the left of Y": X before Y, which is the natural order
            conns.append("side")
        elif "ONOF" in t:
            conns.append("on_next")
        elif re.search(r"\b(under|below|beneath|underneath)\b", t):
            conns.append("on_prev")
        elif re.search(r"\b(with|topped|holding)\b", t):
            conns.append("on_prev")
        else:
            conns.append("side")
    for i in range(len(items)):          # "... a roof on top": that item sits on the one before
        if "ONTOP" in norm(segs[i + 1]) and i > 0 and conns[i - 1] == "side":
            conns[i - 1] = "on_prev"
    return items, conns


def _block(catalog, tid, color, x, z, depth=0):
    return {"type": tid, "color": color, "x": round(x * 2) / 2, "depth": depth, "rot": 0, "pose": 0, "z_hint": z}


def layout(items, conns, catalog, stock, sup_given=None, beside=None, max_width=None, multi=None):
    """Items + connectors -> (blocks, notes, summary). Stacks sit side by side, left to right."""
    n = len(items)
    sup = list(sup_given) if sup_given is not None else [None] * n
    for i, c in enumerate(conns if sup_given is None else []):
        if c == "on_prev":
            sup[i + 1] = i
        elif c == "on_next":
            tgt = items[i + 1]
            prev = [j for j in range(i + 1) if items[j]["tid"] == tgt["tid"] and j != i] if tgt["ref"] else []
            if prev:                    # "... over the plank": only this item goes on that earlier plank
                sup[i] = prev[-1]
                continue
            k = i
            while k >= 0 and sup[k] is None and (k == i or conns[k] == "side"):
                sup[k] = i + 1
                k -= 1
    for i in range(n if sup_given is None else 0):   # a supporter that is just "the X" means the X already named
        t = sup[i]
        if t is not None and items[t]["ref"]:
            prev = [j for j in range(t) if items[j]["tid"] == items[t]["tid"] and not items[j]["ref"]]
            if prev:
                sup[i] = prev[-1]
    beside = list(beside) if beside else [None] * n
    multi = [m if m and len(m) > 1 else None for m in (multi or [None] * n)]
    for i, c in enumerate(conns):       # rule parser: "X to the right of Y"
        if c == "beside_r":
            beside[i] = (i + 1, "right")
    order = list(range(n))              # left-to-right order of the ground stacks

    def root(j):
        for _ in range(n):
            if sup[j] is None:
                break
            j = sup[j]
        return j
    for i in range(n):
        if beside[i] and sup[i] is None:
            j = root(beside[i][0])
            if j != i and j in order:
                order.remove(i)
                order.insert(order.index(j) + (1 if beside[i][1] == "right" else 0), i)
    notes, blocks, made = [], [], {}
    top = {}                    # id(block) -> z of the free top surface

    alloc = {}                  # stock is handed out in the order things were said, not left to right
    for i in range(n):
        it = items[i]
        name = catalog.types[it["tid"]].get("name", it["tid"]).lower()
        got = []
        for _ in range(it["n"]):
            c = stock.take(it["tid"], it["color"])
            if c is None:
                break
            got.append(c)
        if len(got) < it["n"]:
            pl = name + ("es" if name.endswith(("ch", "s", "x")) else "s")
            what = f"{it['color']} {pl}" if it["color"] else pl
            have = sorted(stock.colors(it["tid"]))
            hint = f" ({name} comes in {', '.join(have)})" if not got and it["color"] and it["color"] not in have else ""
            notes.append(f"I only have {len(got)} {what} for that" if got else f"I have no {what} left{hint}")
        alloc[i] = got

    def make(i, where):
        """Create the blocks of item i from `where(j, count) -> (x, z)`; returns them."""
        tid = items[i]["tid"]
        out = []
        for j, c in enumerate(alloc[i]):
            x, z = where(j, len(alloc[i]))
            b = _block(catalog, tid, c, x, z)
            b["_w"] = catalog.footprint(tid)[0]
            top[id(b)] = z + catalog.height(tid)
            out.append(b)
        return out

    def place_children(i, depth=0):
        def mine(k):            # k rests on i alone, or across several stacks once all of them exist
            if k in made:
                return False
            if multi[k]:
                return i in multi[k] and all(j in made for j in multi[k])
            return sup[k] == i
        kids = [k for k in range(n) if mine(k)]
        if not kids or i not in made or depth > 6:
            return
        order_ = sorted(kids, key=lambda k: not catalog.flat_top(items[k]["tid"]) and 1 or 0)
        total = sum(items[k]["n"] for k in order_ if not multi[k])
        idx = 0
        for k in order_:
            parents = sorted((b for j in multi[k] for b in made[j]), key=lambda b: b["x"]) if multi[k] else made[i]
            if not parents:
                continue
            span0 = min(b["x"] for b in parents)
            span1 = max(b["x"] + b["_w"] for b in parents)
            w = catalog.footprint(items[k]["tid"])[0]
            h_ = catalog.height(items[k]["tid"])
            alone = items[k]["n"] == 1 if multi[k] else total == 1

            def where(j, cnt, w=w, parents=parents, span0=span0, span1=span1, alone=alone, h_=h_):
                nonlocal idx
                if alone and len(parents) > 1:
                    return (span0 + span1) / 2 - w / 2, max(top[id(b)] for b in parents)
                p = parents[idx % len(parents)]
                idx += 1
                z = top[id(p)]
                top[id(p)] = z + h_
                return p["x"] + p["_w"] / 2 - w / 2, z
            made[k] = make(k, where)
            blocks.extend(made[k])
        for k in order_:
            place_children(k, depth + 1)

    cursor = 0.5
    for i in order:
        if sup[i] is not None or i in made:
            continue
        if items[i]["ref"] and any(items[j]["tid"] == items[i]["tid"] for j in range(i)):
            continue                                    # "the plank" with nothing left to say about it

        def ground(j, cnt):
            nonlocal cursor
            x = cursor
            cursor += catalog.footprint(items[i]["tid"])[0] + GAP
            return x, 0.0
        made[i] = make(i, ground)
        blocks.extend(made[i])
        place_children(i)
        right = max((b["x"] + b["_w"] for b in blocks), default=cursor)
        cursor = max(cursor, right + GAP)
    if blocks:
        dx = 0.5 - min(b["x"] for b in blocks)
        for b in blocks:
            if dx > 0:
                b["x"] = round((b["x"] + dx) * 2) / 2
    if max_width and blocks:       # keep what fits across the strip; say how many were left out
        before = len(blocks)
        while True:
            keep = [b for b in blocks if b["x"] + b["_w"] <= max_width + 1e-6]
            floor = [b for b in keep if b["z_hint"] < 0.01]
            keep = [b for b in keep if b["z_hint"] < 0.01 or any(
                f["x"] - 0.01 <= b["x"] + b["_w"] / 2 <= f["x"] + f["_w"] + 0.01 for f in floor)]
            if len(keep) == len(blocks):
                break
            blocks = keep
        if len(blocks) < before:
            notes.append(f"only {len(blocks)} of {before} blocks fit across the {max_width:g} cm build strip")
    for b in blocks:
        b.pop("_w", None)
    return blocks, notes, _describe(items, sup, made, catalog, order, multi)


def _describe(items, sup, made, catalog, order=None, multi=None):
    multi = multi or [None] * len(items)
    nm = lambda i: _count_name(made[i], items[i]["tid"], catalog) if i in made and made[i] else None

    def line(i):
        base = nm(i)
        if not base:
            return None
        kids = [x for k in range(len(items)) if sup[k] == i and not multi[k] and k in made for x in [line(k)] if x]
        span = [(line(k) or "") + " (across " + str(len(multi[k])) + " stacks)" for k in range(len(items))
                if multi[k] and k in made and made[k] and i == multi[k][-1]]
        kids += span
        return base + (", topped by " + " and ".join(kids) if kids else "")
    parts = [l for i in (order or range(len(items))) if sup[i] is None for l in [line(i)] if l]
    return "Here's " + ", then ".join(parts) + "." if parts else ""


def _norm_color(c):
    """Whatever color word the model returned -> the catalog's name (wood/brown -> natural)."""
    c = str(c or "").strip().lower()
    return COLOR_ALIAS.get(c, c) or None


PROVIDER_NAMES = {"openai": "OpenAI", "nvidia": "NVIDIA"}   # only for the fallback messages


def _chat(url, key, body, drop_json_mode=False):
    """POST an OpenAI-shaped chat completion -> the reply text.
    OpenAI-compatible providers don't all accept response_format, so on a 4xx we retry without it."""
    tries = [body]
    if drop_json_mode and "response_format" in body:
        tries.append({k: v for k, v in body.items() if k != "response_format"})
    for b in tries:
        req = urllib.request.Request(url, json.dumps(b).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if b is tries[-1] or e.code not in (400, 404, 415, 422):
                raise
    return None


def _try_chain(chain, body):
    """Ask each provider in turn until one answers. Nemotron is first; OpenAI is
    only reached if Nemotron has no key or the network ate it. -> reply text.
    Raises the last error if every provider fails, so the caller falls back to
    the rule parser the same way it always did."""
    last = None
    for base, key, model, provider in chain:
        try:
            out = _chat(base + "/chat/completions", key, {**body, "model": model},
                        drop_json_mode=provider != "openai")
            if out:
                if provider != chain[0][3]:
                    print(f"  {PROVIDER_NAMES.get(chain[0][3], chain[0][3])} did not answer; "
                          f"used {PROVIDER_NAMES.get(provider, provider)}")
                return out
        except Exception as e:
            last = e
    if last:
        raise last
    return None


def _json_obj(s):
    """Model text -> dict. Without a JSON mode some models wrap it in ``` fences or add
    chatter, so take the outermost braces; anything else raises and we fall back to the rules."""
    s = str(s or "").strip()
    a, b = s.find("{"), s.rfind("}")
    return json.loads(s[a:b + 1] if 0 <= a < b else s)


def llm_items(text, catalog):
    """Free-form request -> (items, sup) via the configured LLM, or None (no key, offline, or garbage).
    Each block group says which group it sits on (`on`), so there are no connectors to misread.
    layout() and the planner check the result like any other."""
    chain = envfile.llm_chain()
    if not chain:
        return None
    types = {tid: {"name": t.get("name", tid), "size_cm": t["size"], "shape": t["shape"]}
             for tid, t in catalog.types.items()}      # no colors: stock is enforced here, not by the model
    system = (
        "Turn a request for a toy-block build into JSON. Blocks available (id: details): "
        + json.dumps(types) + ". Reply ONLY with JSON: "
        '{"items":[{"id":<int starting at 1>,"type":<block id>,"count":<int>,"color":<color or null>,'
        '"on":<id of the item this one sits on, or a list of ids if it rests across several stacks, '
        'e.g. a roof over two cubes; null if on the table>,'
        '"beside":<null, or {"of":<id>,"side":"left"|"right"} to place this stack left/right of another>}]}. '
        "Each item is a group of identical blocks. Never repeat a block when the text says \"the cube\" "
        "or \"the plank\": point `on` at the existing item instead. List items left to right as built; "
        "items stacked on another come right after it. Several items can sit on the same item (they stack "
        "in the order listed). Nothing can sit on a roof. A \"house\" is two cubes side by side with a roof on top "
        "of both. If the speaker corrects themselves (\"on the right, no, on the left\") use only the final "
        "version. Color words are passed through as spoken, except wood, wooden, natural or plain wood mean "
        "\"natural\". Never swap one block type for another: if the speaker asks for a color a type may not come in "
        "(a blue cube), still output that type and color; the app reports what is missing. Examples: "
        '"planks and a roof on top of the cube" -> cube(id1), plank x2 (id2,on 1), roof (id3,on 1); '
        '"a cylinder with a cube on top, then a plank on top of the cube" -> cylinder(1), cube(2,on 1), '
        "plank(3,on 2); "
        '"two cubes next to a plank" -> cube x2 (1,on null), plank (2,on null); '
        '"a blue cube on the left, a red cube on the right, then a roof over both" -> cube blue (1), '
        'cube red (2, beside 1 right), roof (3, on [1,2]). '
        'Use only the ids above; no explanations. If the request has nothing to do with these blocks, '
        'return {"items":[]}.')
    body = {"model": chain[0][2], "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}
    try:
        data = _json_obj(_try_chain(chain, body))
        raw = data["items"]
        ids = {int(i["id"]): k for k, i in enumerate(raw)}
        items = [{"tid": i["type"], "n": max(1, min(int(i.get("count") or 1), 20)),
                  "color": _norm_color(i.get("color")), "ref": False} for i in raw]
        def ons(i):
            v = i.get("on")
            vs = v if isinstance(v, list) else [v]
            return [ids[int(x)] for x in vs if x is not None and int(x) in ids]
        multi = [ons(i) if len(ons(i)) > 1 else None for i in raw]
        sup = [(ons(i) or [None])[0] for i in raw]
        beside = []
        for i in raw:
            b = i.get("beside")
            ok = isinstance(b, dict) and b.get("side") in ("left", "right") and b.get("of") is not None \
                and int(b["of"]) in ids
            beside.append((ids[int(b["of"])], b["side"]) if ok else None)
    except Exception as e:                       # offline, bad key, bad JSON: fall back to the rules
        print(f"dictation: model fallback failed ({type(e).__name__}); using the rules", flush=True)
        return None
    if not items or any(i["tid"] not in catalog.types for i in items):
        return None
    low = " " + text.lower() + " "
    rx, _ = _noun_re(catalog)
    said = {m.group(1).rstrip("s") for m in rx.finditer(low)}
    allowed = {tid for tid, ws in NOUNS.items() if tid in catalog.types and any(w.rstrip("s") in said for w in ws)}
    for pr in presets.PRESETS:                   # "a house" means its blocks without naming them
        if re.search(r"\b" + re.escape(pr["name"].lower()) + r"s?\b", low):
            allowed |= {b["type"] for b in pr["blocks"]}
    if any(i["tid"] not in allowed for i in items):   # the model swapped in a block nobody asked for
        print("dictation: the model used a block type that wasn't requested; using the rules", flush=True)
        return None
    for k in range(len(items)):                  # roofs hold nothing; a multi-support needs real stacks
        if multi[k]:
            multi[k] = [j for j in multi[k] if j != k and catalog.flat_top(items[j]["tid"])]
            if len(multi[k]) < 2:
                sup[k], multi[k] = (multi[k][0] if multi[k] else None), None
    for k in range(len(items)):                  # no self-support or loops; nothing sits on a roof
        seen, j = {k}, sup[k]
        while j is not None:
            if j in seen or not catalog.flat_top(items[j]["tid"]):
                sup[k] = None
                break
            seen.add(j)
            j = sup[j]
    return items, sup, beside, multi


def _preset(text):
    low = text.lower()
    for p in presets.PRESETS:
        if re.search(r"\b" + re.escape(p["name"].lower()) + r"s?\b", low) or p["id"] in low.split():
            return p
    return None


def _taller(design, catalog, stock, cfg):
    """Add one block on every flat-topped column; roofs move up on top."""
    blocks = [dict(b) for b in design["blocks"]]
    roofs = [b for b in blocks if not catalog.flat_top(b["type"])]
    rest = [b for b in blocks if catalog.flat_top(b["type"])]
    if not rest:
        return None, "There's nothing to stack on."
    st = planner.settle({"blocks": blocks}, cfg, catalog)
    tops = {}
    for i, b in enumerate(blocks):
        if b in rest and i in st:
            tops.setdefault(round(st[i]["rect"][0], 1), (i, b))
    added = []
    for i, b in tops.values():
        tid = b["type"]
        c = stock.take(tid, None)
        if c is None:
            continue
        added.append(_block(catalog, tid, c, b["x"], st[i]["z"] + st[i]["h"], b.get("depth", 0)))
    if not added:
        return None, "I don't have spare blocks to stack higher."
    lift = max(catalog.height(a["type"]) for a in added)
    for r in roofs:
        r["z_hint"] += lift
    return {"blocks": rest + added + roofs}, None


def _swap(design, catalog, stock, old, new):
    out, changed, short = [], 0, 0
    for b in design["blocks"]:
        b = dict(b)
        if b.get("color") == old:
            if stock.take(b["type"], new):
                stock.left[(b["type"], old)] += 1
                b["color"] = new
                changed += 1
            else:
                short += 1
        out.append(b)
    return {"blocks": out}, changed, short


def parse(text, catalog, cfg, current=None, body=None, tile_fn=None):
    """-> {"design", "reply"}; design None when nothing buildable came out.
    current: planner design of the build on screen (for edits); tile_fn: webapi tile helper."""
    strip = planner.grid_info(cfg)["width"]
    low = " " + re.sub(r"[^a-z0-9, ]+", " ", text.lower()).strip() + " "
    items, conns = _entries(low, catalog)
    ents = items
    llm_sup = llm_beside = llm_multi = None
    edit = current and re.search(r"\b(taller|higher|fewer|less|simpl\w+|swap|change|why|explain|add a layer)\b", low)
    if items and not edit:          # a build description: the language model reads it better than the rules
        got = llm_items(text, catalog)
        if got:
            items, conns, llm_sup, llm_beside, llm_multi = got[0], [], got[1], got[2], got[3]

    if not ents:
        p = _preset(low)
        if p:
            return {"design": p, "reply": f"Here's a {p['name'].lower()}. {p['desc']}"}
        m = re.search(r"\b(?:swap|change|turn|make)\b.*?\b(%s)\b.*?\b(?:for|to|into)\b.*?\b(%s)\b" %
                      ("|".join(COLORS), "|".join(COLORS)), low)
        if re.search(r"\bwhy\b|\bexplain\b", low):
            if not current:
                return {"design": None, "reply": "Make or pick a build first, then ask why."}
            kinds = sorted({catalog.types[b["type"]].get("name", b["type"]) for b in current["blocks"]})
            return {"design": None, "reply": f"It uses {len(current['blocks'])} blocks ({', '.join(kinds)}), "
                    "stacked bottom-up so each one rests on a block below."}
        if re.search(r"\b(taller|higher|bigger|more)\b|add a layer", low) or m or \
                re.search(r"\b(fewer|less|simpl\w+|smaller|shorter)\b", low):
            if not current:
                return {"design": None, "reply": "Pick or generate a build first, then I can change it."}
            stock = Stock(catalog, current)
            if m:
                d, n, short = _swap(current, catalog, stock, m.group(1), m.group(2))
                if not n:
                    return {"design": None, "reply": f"I can't swap {m.group(1)} for {m.group(2)}: "
                            "no blocks of that kind or no spare ones in that color."}
                note = f" ({short} stayed {m.group(1)}: none left in {m.group(2)})" if short else ""
                return {"design": d, "reply": f"Swapped {n} block(s) to {m.group(2)}.{note}"}
            if re.search(r"\b(taller|higher|bigger|more)\b|add a layer", low):
                d, why = _taller(current, catalog, stock, cfg)
                if d is None:
                    return {"design": None, "reply": why}
                _, probs = planner.plan(d, cfg, catalog, body)
                errs = [p_ for p_ in probs if p_["level"] == "error"]
                if errs:
                    return {"design": None, "reply": f"Can't go taller: {errs[0]['msg']}"}
                return {"design": d, "reply": "Added a layer on top."}
            # fewer: let the caller's tile helper simplify, else drop the top block
            blocks = list(current["blocks"])
            if len(blocks) <= 1:
                return {"design": None, "reply": "It's already as small as it gets."}
            d = tile_fn(current) if tile_fn else None
            if not d or len(d["blocks"]) >= len(blocks):
                st = planner.settle(current, cfg, catalog)
                top = max(st, key=lambda i: st[i]["z"])
                d = {"blocks": [b for i, b in enumerate(blocks) if i != top]}
            return {"design": d, "reply": f"Trimmed it to {len(d['blocks'])} blocks."}
        got = llm_items(text, catalog)
        if got:
            items, sup, beside, multi = got
            stock = Stock(catalog)
            blocks, notes, summary = layout(items, [], catalog, stock, sup, beside, strip, multi)
            if blocks:
                return {"design": {"blocks": blocks},
                        "reply": summary + (" Note: " + "; ".join(notes) + "." if notes else "")}
        names = ", ".join(sorted(NOUNS_PRETTY(catalog)))
        return {"design": None, "reply": f"I didn't catch a block I know. I have: {names}. "
                "Try \"a plank and a roof on top\" or \"make a house\"."}

    stock = Stock(catalog)
    blocks, notes, summary = layout(items, conns, catalog, stock, llm_sup, llm_beside, strip, llm_multi)
    if not blocks:
        return {"design": None, "reply": "; ".join(notes) + "."}
    reply = summary
    if re.search(r"\b(behind|in front)\b", low):
        notes.append("I can't place blocks behind or in front of each other yet")
    if notes:
        reply += " Note: " + "; ".join(notes) + "."
    return {"design": {"blocks": blocks}, "reply": reply}


def _count_name(blocks, tid, catalog):
    n = sum(1 for b in blocks if b["type"] == tid)
    name = catalog.types[tid].get("name", tid).lower()
    cols = {b.get("color") for b in blocks if b["type"] == tid}
    if len(cols) == 1 and "natural" not in cols:
        name = f"{next(iter(cols))} {name}"
    plural = "es" if name.endswith(("ch", "s", "x")) else "s"
    return f"{n} {name}" + (plural if n > 1 else "")


def NOUNS_PRETTY(catalog):
    return [t.get("name", tid).lower() for tid, t in catalog.types.items()]

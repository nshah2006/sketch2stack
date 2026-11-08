"""Propose-validate-repair: let a model negotiate a buildable design.

The old repair (webapi._trim) drops blocks from the top until the planner stops
complaining. It always works, but it answers every problem the same way: delete.
Most problems have better answers - a colour we actually own, two cubes instead
of one 10 cm bar, a stack one block lower - and picking between them is a
judgement call, which is what a model is for.

So: the model proposes, the planner decides. Nothing the model says is trusted;
every proposal goes back through planner.plan() and is thrown away unless it
comes back clean. If the model is unconfigured, offline, or just wrong three
times running, we trim from the top like before - a live demo has to survive
dead wifi.

  repair(design, cfg, catalog) -> {"design": <always buildable>, "tried": [...],
                                   "used_llm": <did the answer come from the model>}
"""
import json
import urllib.error
import urllib.request

from . import envfile, planner

MAX_BLOCKS = 60          # bigger than any demo build; caps prompt size and junk answers
TIMEOUT = 20             # s; a demo can't wait longer than this for a repair


# ===================================================================== the oracle
def errors(design, cfg, catalog, body=None):
    """The planner's error problems for a design (warns don't block a build).
    Same check webapi._valid makes, so what we return is what the app accepts."""
    _, probs = planner.plan(design, cfg, catalog, body)
    return [p for p in probs if p["level"] == "error"]


def _base(design):
    """Copy a design and fill the optional fields the planner reads. A sparse
    design from the UI (no colour, no pose) would otherwise KeyError in plan()."""
    out = []
    for b in (design or {}).get("blocks") or []:
        b = dict(b)
        for k, v in (("color", None), ("x", 0.0), ("depth", 0), ("rot", 0), ("pose", 0), ("z_hint", 0.0)):
            b.setdefault(k, v)
        out.append(b)
    return {"blocks": out}


# ===================================================================== the loop
def repair(design, cfg, catalog, body=None, rounds=3, llm=None):
    """Make `design` buildable. -> {"design", "tried", "used_llm"}

    Ask the model for a fix, re-validate, repeat at most `rounds` times, then
    fall back to trimming. `llm` is a callable (prompt -> text or None) so this
    can be tested, or replayed, with no network.
    `tried` records every round (what was wrong, what came back, did it pass) so
    the UI can show the negotiation later.
    """
    cur = _base(design)
    errs = errors(cur, cfg, catalog, body)
    tried = []
    if not errs:
        return {"design": cur, "tried": tried, "used_llm": False}

    ask = llm or _ask
    for n in range(max(0, int(rounds or 0))):
        rec = {"round": n + 1, "problems": [p["msg"] for p in errs], "proposed": None,
               "ok": False, "note": ""}
        tried.append(rec)
        text = ask(_prompt(cur, cfg, catalog, errs))
        if not text:
            rec["note"] = "no answer from the model"
            break                              # no key or no network: more rounds won't help
        prop = _clean(_json_obj(text), catalog)
        if prop is None:
            rec["note"] = "answer wasn't a usable design"
            continue                           # garbage this round; the prompt may still land next
        rec["proposed"] = prop
        perrs = errors(prop, cfg, catalog, body)
        if not perrs:
            rec["ok"] = True
            return {"design": prop, "tried": tried, "used_llm": True}
        rec["note"] = "planner still refused: " + "; ".join(p["msg"] for p in perrs[:3])
        if len(perrs) < len(errs):             # it got closer: keep negotiating from here
            cur, errs = prop, perrs           # otherwise re-ask about the design we started with

    out = _trim(_base(design), cfg, catalog, body)   # trim the original, not a proposal that drifted
    tried.append({"round": None, "problems": [p["msg"] for p in errs], "proposed": out,
                  "ok": True, "note": "fell back to dropping blocks from the top"})
    return {"design": out, "tried": tried, "used_llm": False}


def _trim(design, cfg, catalog, body=None):
    """Fallback repair, same as webapi._trim: drop blocks from the top until the
    planner accepts. Dumb, but it needs nothing but the planner - the demo rests on it."""
    # settle() skips types we don't own, so they can never trim away: drop them first.
    d = {"blocks": [b for b in design.get("blocks", []) if b.get("type") in catalog.types]}
    while d["blocks"] and errors(d, cfg, catalog, body):
        st = planner.settle(d, cfg, catalog)
        top = max(st, key=lambda i: st[i]["z"]) if st else len(d["blocks"]) - 1
        d["blocks"].pop(top)
    return d


# ===================================================================== what we tell the model
def _inventory(catalog):
    """type id -> size, poses, and how many of each colour we really own."""
    out = {}
    for tid, t in catalog.types.items():
        w, d, h = catalog.size(tid)
        out[tid] = {"name": t.get("name", tid), "size_cm": [w, d, h],
                    "own": dict(t["colors"]), "total_owned": catalog.count(tid),
                    "poses": [p["name"] for p in catalog.poses(tid)],
                    "holds_blocks": catalog.flat_top(tid)}
    return out


def _compact(design, catalog):
    """The design as short JSON: only the fields the planner reads, rounded."""
    return [{"i": i, "type": b.get("type"), "color": b.get("color"),
             "x": round(_num(b.get("x"), 0.0), 1), "depth": int(_num(b.get("depth"), 0)),
             "rot": int(_num(b.get("rot"), 0)), "pose": int(_num(b.get("pose"), 0)),
             "z_hint": round(_num(b.get("z_hint"), 0.0), 1)}
            for i, b in enumerate(design.get("blocks", [])[:MAX_BLOCKS])]


def _prompt(design, cfg, catalog, errs):
    """One self-contained prompt: the blocks, the planner's exact complaints, and
    the real inventory. Compact on purpose - small models lose the rules in prose."""
    gi = planner.grid_info(cfg)
    return (
        "You repair toy-block builds for a robot arm. A design is JSON:\n"
        '{"blocks":[{"type":<block id>,"color":<colour or null>,"x":<cm>,"depth":<slot int>,'
        '"rot":0|90,"pose":<int>,"z_hint":<cm>}]}\n'
        "x is the block's left edge in cm from the left end of the build strip. depth is the "
        "front-to-back slot (0 = front). rot 90 turns the block a quarter turn about the vertical "
        "axis (its w and d swap). pose indexes that type's poses below. z_hint is roughly how high "
        "off the table it goes: blocks settle by gravity in z_hint order and rest on whatever is "
        "under them, so z_hint only has to put them in the right order, not be exact.\n"
        "Blocks we own (id -> size [w,d,h] cm, count per colour, poses, whether anything can sit on it):\n"
        + json.dumps(_inventory(catalog), separators=(",", ":")) + "\n"
        f"Build strip: {gi['width']:.0f} cm wide, {gi['depth']:.0f} cm deep "
        f"({gi['slots']} slot(s) of {gi['depth_slot']:.0f} cm), nothing above {gi['max_height']:.0f} cm tall.\n"
        "Rules you must respect:\n"
        "- every block must sit inside the strip (0 <= x, x + width <= strip width; depth slot in range)\n"
        "- nothing taller than the strip's max height\n"
        "- a block off the table must rest on blocks below it with its centre over them, and at least "
        "half its footprint supported\n"
        "- nothing can sit on a roof\n"
        "- you may not use more blocks of a type and colour than the counts above\n"
        "Fix the listed problems with the smallest change that keeps the shape recognisable: swap in a "
        "colour we own, split one long block into shorter ones we have, lower or widen a stack, nudge a "
        "block sideways, push one to a back slot. Prefer changing or substituting blocks over deleting "
        "them; delete only as a last resort.\n"
        "Reply ONLY with JSON: {\"blocks\":[...]} - the whole corrected design, no explanation.\n"
        "Current design and the planner's problems (index refers to i above; null means the whole build):\n"
        + json.dumps({"blocks": _compact(design, catalog),
                      "problems": [{"index": p["index"], "msg": p["msg"]} for p in errs[:20]]},
                     separators=(",", ":")))


# ===================================================================== trust nothing
def _num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _json_obj(s):
    """Model text -> dict/list, or None. Without a JSON mode some models add fences
    or chatter, so take the outermost braces; anything unparseable is just a miss."""
    s = str(s or "").strip()
    for a, b in (("{", "}"), ("[", "]")):
        i, j = s.find(a), s.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(s[i:j + 1])
            except ValueError:
                pass
    return None


def _clean(raw, catalog):
    """Model JSON -> a design we dare hand the planner, or None.

    Fields are coerced and unknown keys dropped; a block of a type we don't own
    kills the whole proposal rather than being silently removed, because quietly
    deleting blocks is exactly the dumb repair we're replacing. Colours are left
    as the model wrote them - the planner, not this function, judges stock.
    """
    blocks = raw.get("blocks") if isinstance(raw, dict) else raw
    if not isinstance(blocks, list) or not blocks or len(blocks) > MAX_BLOCKS:
        return None
    out = []
    for b in blocks:
        if not isinstance(b, dict) or b.get("type") not in catalog.types:
            return None
        color = b.get("color")
        color = str(color).strip().lower() or None if color is not None else None
        poses = len(catalog.poses(b["type"]))
        out.append({"type": b["type"], "color": color,
                    "x": round(_num(b.get("x"), 0.0), 2),
                    "depth": max(0, int(_num(b.get("depth"), 0))),
                    "rot": 90 if int(_num(b.get("rot"), 0)) % 180 == 90 else 0,
                    "pose": min(max(0, int(_num(b.get("pose"), 0))), poses - 1),
                    "z_hint": round(_num(b.get("z_hint"), 0.0), 2)})
    return {"blocks": out}


# ===================================================================== the default model call
def _chat(url, key, body, drop_json_mode=False):
    """POST an OpenAI-shaped chat completion -> the reply text. Not every
    OpenAI-compatible provider accepts response_format, so on a 4xx we retry without it."""
    tries = [body]
    if drop_json_mode and "response_format" in body:
        tries.append({k: v for k, v in body.items() if k != "response_format"})
    for b in tries:
        req = urllib.request.Request(url, json.dumps(b).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if b is tries[-1] or e.code not in (400, 404, 415, 422):
                raise
    return None


def _ask(prompt):
    """Default llm: whatever envfile.llm_config() points at. Returns None on any
    failure (no key, offline, bad JSON) so repair() falls back instead of raising."""
    conf = envfile.llm_config()
    if not conf:
        return None
    base, key, model, provider = conf
    body = {"model": model, "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": "Reply with JSON only."},
                         {"role": "user", "content": prompt}]}
    try:
        return _chat(base + "/chat/completions", key, body, drop_json_mode=provider != "openai")
    except Exception as e:
        print(f"repair: {provider} fallback failed ({type(e).__name__})", flush=True)
        return None

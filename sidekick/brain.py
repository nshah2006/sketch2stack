"""The assistant's understanding: what it sees, what it makes of a schematic, and
what to say and do next.

Everything it knows about the bench comes from the one overhead camera (the
builder's block tracker). Nemotron (or OpenAI) decides what to do when a key is
set; without one the rule parser in intents.py answers. The brain never moves
the arm itself: it returns plain commands ("hand me the red cube", "look
happy") that go through the same tested command path as typed or spoken ones,
and an emotion to show.
"""
import collections
import json
import math

from . import envfile, intents, presets

# what the brain may ask the command path to do (each must parse as one of these intents)
ALLOWED = {"stop", "pause", "cancel", "resume", "preset", "build", "hand_me", "put_there", "status",
           "back_off", "move_up", "move_down", "express"}
EMOTIONS = ("yes", "no", "happy", "sad", "confused", "thinking", "greet", "excited", "look_at")


# ===================================================================== seeing
def _name(catalog, tid):
    return catalog.types[tid]["name"].lower() if tid in catalog.types else "block"


def scene(builder, catalog, cfg):
    """A plain summary of what the camera shows right now."""
    snap = builder.snapshot()
    blocks = []
    for b in builder.active_blocks():
        on_build = b.get("zone") == "build" or cfg.in_build(b["x"], b["y"])
        reach = True
        try:
            reach = builder._pick_reachable(b) if (b.get("type") and not on_build) else not on_build
        except Exception:
            pass
        blocks.append({"id": b.get("id"), "type": b.get("type"), "color": b.get("color"),
                       "x": round(b["x"], 1), "y": round(b["y"], 1),
                       "where": "build" if on_build else "loose", "reachable": bool(reach)})
    hands = [{"x": round(h["x"], 1), "y": round(h["y"], 1), "sign": h.get("sign")} for h in (builder.hands or [])]
    steps = snap.get("steps") or []
    return {"blocks": blocks, "hands": hands, "mode": snap.get("mode"), "action": snap.get("action"),
            "step": snap.get("step"), "total": snap.get("total"), "result": snap.get("result"),
            "done_steps": sum(1 for s in steps if s.get("state") == "done"),
            "use_color": bool(cfg["use_color"])}


def _label(b, catalog, use_color):
    kind = _name(catalog, b["type"]) if b.get("type") else "block"
    col = b.get("color") if use_color and b.get("color") not in (None, "any") else None
    return f"{col} {kind}" if col else kind


def describe(sc, catalog):
    """-> one or two short sentences about the bench, in plain words."""
    loose = [b for b in sc["blocks"] if b["where"] == "loose"]
    built = [b for b in sc["blocks"] if b["where"] == "build"]
    if not sc["blocks"]:
        return "The bench is empty: I don't see any blocks."
    c = collections.Counter(_label(b, catalog, sc["use_color"]) for b in loose)
    parts = [f"{n} {k}{'s' if n > 1 else ''}" for k, n in c.most_common()]
    s = f"I see {len(loose)} loose block{'s' if len(loose) != 1 else ''}"
    s += (": " + ", ".join(parts)) if parts else ""
    if built:
        s += f", and {len(built)} on the build strip"
    out_of_reach = [b for b in loose if not b["reachable"]]
    s += "."
    if out_of_reach:
        s += f" {len(out_of_reach)} of them {'is' if len(out_of_reach) == 1 else 'are'} out of my reach."
    if sc["hands"]:
        s += " I can see your hand too."
    return s


# ===================================================================== schematic review
def review(design, sc, catalog):
    """What the build needs versus what is loose on the bench.
    -> {"ok", "missing": [(type, color, n)], "say", "emotion"}"""
    need = collections.Counter(presets.needed(design))
    have = collections.Counter()
    for b in sc["blocks"]:
        if b["where"] == "loose" and b["reachable"]:
            have[(b["type"], b["color"] if sc["use_color"] else None)] += 1
    missing = []
    for (tid, col), n in need.items():
        key = (tid, col if sc["use_color"] else None)
        got = have.get(key, 0)
        if not sc["use_color"]:
            got = 0                  # colorless: blocks are handed over one at a time on the pickup spot
        if got < n:
            missing.append((tid, col, n - got))
            have[key] = 0
        else:
            have[key] = got - n
    total = sum(need.values())
    layers = sorted({round(b.get("z_hint", 0) or 0, 1) for b in design["blocks"]})
    name = design.get("name") or "this"
    if not sc["use_color"]:
        say = (f"{name.capitalize()} takes {total} blocks in {max(1, len(layers))} layer"
               f"{'s' if len(layers) > 1 else ''}. I'll ask you for each one on the pickup spot.")
        return {"ok": True, "missing": missing, "say": say, "emotion": "yes"}
    if not missing:
        return {"ok": True, "missing": [], "emotion": "yes",
                "say": f"I have everything for {name}: {total} blocks. Shall I start?"}
    want = ", ".join(f"{n} {c + ' ' if c else ''}{_name(catalog, t)}{'s' if n > 1 else ''}" for t, c, n in missing)
    return {"ok": False, "missing": missing, "emotion": "confused",
            "say": f"For {name} I'm missing {want}. Put {'them' if len(missing) > 1 else 'it'} where I can reach and I'll start."}


# ===================================================================== thinking
SYSTEM = """You are the mind of Sidekick, a small robot arm on a workbench that builds things from wooden
blocks next to a person. You see the bench only through one overhead camera; the scene below is what you see
right now. Reply as JSON: {"say": "<one or two short spoken sentences>", "emotion": "<one of %s or null>",
"commands": ["<plain command>", ...]}.
Commands are short plain sentences the robot already understands, exactly in these forms:
"build the <house|bridge|gate|tower|skyline>", "build <free description, e.g. two cubes with a roof on top>",
"hand me the <color> <block type>", "put it there", "stop", "wait", "go on", "cancel", "back off",
"move up", "move down", "what are you doing".
How blocks arrive: if the scene says "supply": "hand_over", the person hands you each block on the pickup spot
when you ask for it, so an empty bench is normal and you CAN start any preset build; if it says "bench", you
build only from blocks you can see.
Rules: only use blocks you can see when handing things over; if something is missing or unclear, ask
(say it, emotion "confused", no commands). If the person greets you, greet back (emotion "greet").
When you agree to do something, emotion "yes". When the person seems pleased or a build finished, "happy".
Never invent blocks or positions. Keep "say" under 25 words."""


def _llm(text, sc, catalog, history):
    chain = envfile.llm_chain()
    if not chain:
        return None
    from .dictation import _json_obj, _try_chain
    scene_txt = json.dumps({"supply": "bench" if sc["use_color"] else "hand_over",
                            "bench": describe(sc, catalog), "blocks": sc["blocks"][:30], "hands": sc["hands"],
                            "arm": {"mode": sc["mode"], "doing": sc["action"], "step": sc["step"],
                                    "total": sc["total"], "last_result": sc["result"]}})
    msgs = [{"role": "system", "content": SYSTEM % (", ".join(EMOTIONS)) + "\nScene: " + scene_txt}]
    for h in history[-6:]:
        msgs.append(h)
    msgs.append({"role": "user", "content": text})
    body = {"model": chain[0][2], "temperature": 0.2, "response_format": {"type": "json_object"},
            "messages": msgs}
    try:
        data = _json_obj(_try_chain(chain, body))
    except Exception as e:
        print(f"brain: model unavailable ({type(e).__name__}); using the rules", flush=True)
        return None
    if not isinstance(data, dict):
        return None
    return data


def think(text, builder, catalog, cfg, history=None):
    """-> {"say", "emotion", "commands": [str], "scene": str, "source": "model"|"rules"}.
    Every command is checked against the command parser before it is returned."""
    history = history if history is not None else []
    sc = scene(builder, catalog, cfg)
    low = intents.normalize(text)
    if any(w in low for w in ("what do you see", "what can you see", "what s on the table", "what is on the table",
                              "whats on the table", "look around")):
        return {"say": describe(sc, catalog), "emotion": "thinking", "commands": [],
                "scene": describe(sc, catalog), "source": "rules"}
    data = _llm(text, sc, catalog, history)
    source = "model"
    if data is None:                                         # offline: the rules answer
        source = "rules"
        it = intents.parse(text, catalog)
        if it["intent"] == "unknown":
            data = {"say": "I didn't get that. Try 'build the house' or 'hand me a cube'.",
                    "emotion": "confused", "commands": []}
        else:
            data = {"say": "", "emotion": "yes", "commands": [text]}
    cmds = []
    for c in data.get("commands") or []:
        if not isinstance(c, str):
            continue
        it = intents.parse(c, catalog)
        if it["intent"] in ALLOWED:
            cmds.append(c)
    emo = data.get("emotion") if data.get("emotion") in EMOTIONS else None
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": json.dumps({"say": data.get("say", ""), "commands": cmds})})
    return {"say": str(data.get("say") or "").strip(), "emotion": emo, "commands": cmds,
            "scene": describe(sc, catalog), "source": source}


# ===================================================================== reacting on its own
REACTIONS = [            # builder log text -> emotion the arm shows (between moves, never while carrying)
    ("build started", "greet"),
    ("moved", "confused"),          # "block moved 3 cm ... following it"
    ("lost the block", "confused"),
    ("pick check", "confused"),     # a missed pick
    ("Wrong block", "no"),
    ("build done", "happy"),
    ("build incomplete", "sad"),
    ("build failed", "sad"),
]


def reaction_for(msg):
    for key, emo in REACTIONS:
        if key in msg:
            return emo
    return None


def nearest_hand(hands):
    return min(hands, key=lambda h: math.hypot(h["x"] - 25, h["y"])) if hands else None

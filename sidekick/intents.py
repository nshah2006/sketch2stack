"""Spoken/typed commands -> intent dicts. Rules first, a language model only
for sentences the rules don't understand (and only when a key is set).

    "stop" / "freeze"                 {"intent": "stop"}      halt the arm now (resumable)
    "wait" / "hold on" / "pause"      {"intent": "pause"}
    "cancel" / "stop the build"       {"intent": "cancel"}    end the build
    "go on" / "continue" / "okay go"  {"intent": "resume"}
    "build the bridge"                {"intent": "preset", "preset": "bridge"}
    "two cubes with a roof on top"    {"intent": "build", "text": ...}   (dictation does the rest)
    "hand me the red cube"            {"intent": "hand_me", "type": "cube", "color": "red", "count": 1}
    "put it there"                    {"intent": "put_there", "type": None, "color": None}
    "clean up" / "clear the table"    {"intent": "clear"}
    "what are you doing"              {"intent": "status"}
    "back off" / "get away"           {"intent": "back_off"}  claw up and toward the base, then hold
    "move up" / "higher"              {"intent": "move_up"}   +3 cm, then hold
    "move down" / "lower"             {"intent": "move_down"} -3 cm (never into a block), then hold
    "nod" / "look happy" / "wave"     {"intent": "express", "emotion": "yes"|"happy"|"greet"|...}
    anything else                     {"intent": "unknown"}
"""
import json
import re

from . import presets
from .dictation import COLOR_ALIAS, COLORS, NOUNS, NUMS

STOP = r"\b(stop|freeze|halt|emergency)\b"
CANCEL = r"\b(cancel|abort|stop (the |this )?build(ing)?|forget it|never ?mind|start over)\b"
PAUSE = r"\b(wait|hold on|hold it|hang on|pause|one (sec|second|moment)|just a (sec|second|moment))\b"
RESUME = (r"\b(go on|continue|resume|keep going|carry on|go ahead|okay go|ok go|you can go|"
          r"all clear|unpause)\b|^(go|okay|ok)$")
CLEAR = r"\b(clean up|clean the table|clear (the |off the )?(table|board|strip)|tidy( up)?|put (it all|everything) away)\b"
STATUS = r"\b(what are you doing|status|what'?s (going on|happening)|how far)\b"
HAND = r"\b(hand|give|bring|pass|fetch|get|toss)\b( me| us)?\b|\bcan i (have|get)\b|\bi (need|want) (a|an|the|one|two|that)\b"
THERE = r"\b(put|place|drop|set|move|leave)\b.*\b(there|here|over there|over here)\b"
ARM = r"( it| yourself| the (arm|claw|gripper|hand))?"
BACK_OFF = (r"\b(back (off|away|up|out)|get (away|back|out of (the )?way)|go away|move away|stand back|"
            r"give me (some )?(room|space)|step back|make room)\b")
MOVE_UP = (r"\b(move|go|come|lift|raise|get)" + ARM + r" (up|higher)\b|\braise (the )?(arm|claw|gripper)\b|"
           r"^(a (bit|little) )?(up|higher)( a (bit|little))?$")
MOVE_DOWN = (r"\b(move|go|come|get)" + ARM + r" (down|lower)\b|\blower (the )?(arm|claw|gripper)\b|"
             r"^(a (bit|little) )?(down|lower)( a (bit|little))?$")
# emotion gestures (gestures.EMOTIONS): first match wins
EXPRESS = [
    ("look_at", r"\blook (at me|over here|here|at us)\b"),
    ("yes", r"\b(say yes|nod( your head)?|nodding)\b"),
    ("no", r"\b(say no|shake your head|shaking your head)\b"),
    ("happy", r"\b((look|be|get|are you) happy|dance|dancing|celebrate|show (me )?happy)\b"),
    ("sad", r"\b((look|be|are you|get) sad|cry)\b"),
    ("confused", r"\b((look|be|are you|get) confused)\b"),
    ("excited", r"\b((look|be|get) excited)\b"),
    ("sleepy", r"\b(go to sleep|take a nap|nap( time)?|sleep|sleepy|go to bed)\b"),
    ("thinking", r"\b(think( about it| it over)?|thinking|ponder)\b"),
    ("greet", r"\b(wave( hello| hi)?|say (hi|hello)|greet)\b|^(hi|hello)$"),
]
BUILD = r"\b(build|make|construct|stack|assemble|create|do)\b"
ANY_BLOCK = {"block", "blocks", "one", "piece", "something", "anything", "thing"}


def normalize(text):
    t = text.lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    t = re.sub(r"\b(please|hey|sidekick|robot|could you|can you|would you|will you)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _type_words(catalog):
    """[(phrase, type id)] longest first: dictation's nouns plus the catalog's own names."""
    words = []
    for tid, ws in NOUNS.items():
        if catalog is None or tid in catalog.types:
            words += [(w, tid) for w in ws if not (tid == "cube" and w == "block")]   # "block" = any block
    if catalog is not None:
        for tid, t in catalog.types.items():
            words.append((t.get("name", tid).lower(), tid))
            words.append((tid.replace("_", " "), tid))
    words += [("short cylinder", "cyl_short"), ("long bar", "bar")]
    return sorted(set(words), key=lambda p: -len(p[0]))


def _colors(catalog):
    cs = set(COLORS) | set(COLOR_ALIAS)
    if catalog is not None:
        cs |= {c for t in catalog.types.values() for c in t["colors"]}
    return cs


def block_spec(t, catalog=None):
    """Normalized text -> (type id or None, color or None, count)."""
    tid = None
    for w, k in _type_words(catalog):
        if re.search(r"\b" + re.escape(w) + r"(s|es)?\b", t):
            tid = k
            break
    color = None
    for c in sorted(_colors(catalog), key=len, reverse=True):
        if re.search(r"\b" + re.escape(c) + r"\b", t):
            color = COLOR_ALIAS.get(c, c)
            break
    count = 1
    m = re.search(r"\b(\d+|" + "|".join(k for k in NUMS if k not in ("a", "an")) + r")\b", t)
    if m:
        v = m.group(1)
        count = int(v) if v.isdigit() else NUMS[v]
    return tid, color, max(1, min(count, 10))


def _preset(t, catalog=None):
    """A preset named on its own ("build the bridge"), not as part of a block description."""
    for p in presets.PRESETS:
        name = p["name"].lower()
        if not re.search(r"\b(" + re.escape(name) + "|" + re.escape(p["id"]) + r")s?\b", t):
            continue
        if p["id"] == "stack" and not re.search(r"\b(a|the|my|another) stack\b|^stack$", t):
            continue          # "stack two cubes" is a description, not the Stack preset
        rest = re.sub(r"\b" + re.escape(name) + r"s?\b", " ", t)
        tid, _, _ = block_spec(rest, catalog)
        if tid is None:
            return p["id"]
    return None


def parse(text, catalog=None, use_llm=False):
    """-> {"intent", "text", ...}. Rules only unless use_llm (then the model gets a
    turn at sentences the rules call unknown)."""
    t = normalize(text)
    out = {"text": text.strip()}
    if not t:
        return {**out, "intent": "unknown"}
    if re.search(CANCEL, t):
        return {**out, "intent": "cancel"}
    if re.search(BACK_OFF, t):
        return {**out, "intent": "back_off"}
    if re.search(MOVE_UP, t):
        return {**out, "intent": "move_up"}
    if re.search(MOVE_DOWN, t):
        return {**out, "intent": "move_down"}
    if re.search(STOP, t) and not re.search(r"\b(don'?t|do not|never) stop\b", t):
        return {**out, "intent": "stop"}
    if re.search(PAUSE, t):
        return {**out, "intent": "pause"}
    if re.search(RESUME, t):
        return {**out, "intent": "resume"}
    if re.search(CLEAR, t):
        return {**out, "intent": "clear"}
    if re.search(STATUS, t):
        return {**out, "intent": "status"}
    for name, pat in EXPRESS:
        if re.search(pat, t):
            return {**out, "intent": "express", "emotion": name}
    if re.search(THERE, t):
        tid, color, _ = block_spec(t, catalog)
        return {**out, "intent": "put_there", "type": tid, "color": color}
    if re.search(HAND, t):
        tid, color, count = block_spec(t, catalog)
        return {**out, "intent": "hand_me", "type": tid, "color": color, "count": count}
    pid = _preset(t, catalog)
    if pid and (re.search(BUILD, t) or len(t.split()) <= 3):
        return {**out, "intent": "preset", "preset": pid}
    tid, _, _ = block_spec(t, catalog)
    if re.search(BUILD, t) or tid is not None or pid:
        return {**out, "intent": "build"}
    if use_llm:
        r = llm_parse(text, catalog)
        if r:
            return {**out, **r}
    return {**out, "intent": "unknown"}


INTENTS = ("stop", "pause", "cancel", "resume", "preset", "build", "hand_me", "put_there", "clear", "status",
           "back_off", "move_up", "move_down", "express", "unknown")
EMOTION_NAMES = [n for n, _ in EXPRESS]


def llm_parse(text, catalog=None):
    """Ask the configured model (same providers as dictation) to classify. None if no key/failure."""
    from . import envfile
    from .dictation import _json_obj, _try_chain
    chain = envfile.llm_chain()
    if not chain:
        return None
    types = sorted(catalog.types) if catalog is not None else sorted(NOUNS)
    sys_msg = ("You turn a spoken command to a block-building robot arm into JSON: "
               '{"intent": one of ' + json.dumps(list(INTENTS)) + ', "preset": one of '
               + json.dumps([p["id"] for p in presets.PRESETS]) + ' or null, "emotion": one of ' + json.dumps(EMOTION_NAMES)
               + ' or null, "type": one of '
               + json.dumps(types) + ' or null, "color": a color word or null}. '
               "hand_me = the person wants a block handed to them; build = describe something to build; "
               "put_there = move the held/last block to where they point; back_off/move_up/move_down = "
               "nudge the arm away/up/down; express = show an emotion. Reply with JSON only.")
    body = {"model": chain[0][2], "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": text[:300]}]}
    try:
        r = _json_obj(_try_chain(chain, body) or "")
    except Exception as e:
        print(f"intents: model failed ({type(e).__name__}); rules only", flush=True)
        return None
    if not isinstance(r, dict) or r.get("intent") not in INTENTS:
        return None
    out = {"intent": r["intent"], "llm": True}
    if r["intent"] == "preset":
        if r.get("preset") not in {p["id"] for p in presets.PRESETS}:
            return None
        out["preset"] = r["preset"]
    if r["intent"] == "express":
        if r.get("emotion") not in EMOTION_NAMES:
            return None
        out["emotion"] = r["emotion"]
    if r["intent"] in ("hand_me", "put_there"):
        out["type"] = r.get("type") if r.get("type") in types else None
        c = (r.get("color") or "").lower() or None
        out["color"] = COLOR_ALIAS.get(c, c)
        out["count"] = 1
    return out

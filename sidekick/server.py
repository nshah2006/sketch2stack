"""Web server: the 3D app (frontend/dist), the classic UI (/classic) and the API.

    python -m sidekick ui            # simulator or real arm per config
    then open http://localhost:8000

Standard library only (http.server). Build the 3D app once with
`cd frontend && npm install && npm run build`; without it, / serves the
classic UI.

Stale-state rules the API enforces:
  * every server start has a new server_id; the app drops anything it
    remembers about runs when the id changes
  * every build gets a run_id; status, stop, pause and resume carry it, and a
    command for a run that isn't the current one is refused (409)
  * only one build can start at a time (builder start lock)
  * /api/generate echoes the caller's request_id so late answers are ignored
"""
import json
import math
import mimetypes
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

from . import brain, intents, planner, presets, speech, webapi
from .fetch import Fetcher
from .jog import Jogger
from .overlay import TopDown, render

UI_DIR = Path(__file__).parent / "ui"
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


class App:
    def __init__(self, cfg, catalog, builder, body, world=None):
        self.cfg, self.catalog, self.builder, self.body, self.world = cfg, catalog, builder, body, world
        self.topdown = TopDown(cfg)
        self.server_id = uuid.uuid4().hex[:12]
        self._jpg = None
        self._jpg_t = 0.0
        self._lock = threading.Lock()
        self._gen_lock = threading.Lock()
        self.run_build = None          # the app's build for the current run_id (so any tab can show it)
        self.fetch = Fetcher(cfg, catalog, builder)    # "hand me a cube": one-off moves outside a build
        self.jog = Jogger(cfg, catalog, builder)        # "back off" / "move up" / "move down"
        self._expr = None                               # thread playing an emotion gesture
        self.pick_target = None                         # last "pick" log entry of the build (for the map)
        self._watch_log(builder)

    def _watch_log(self, b):
        """Note the block each pick goes for (Builder._do_step logs "pick" with its id
        and position) without touching builder.py."""
        orig = b.log

        def log(msg, **extra):
            if msg == "pick" and "block" in extra:
                self.pick_target = {"step": extra.get("step"), "id": extra["block"],
                                    "x": extra.get("x"), "y": extra.get("y"), "run_id": b.run_id}
            return orig(msg, **extra)
        b.log = log

    def _expressing(self):
        return self._expr is not None and self._expr.is_alive()

    # ---------------------------------------------------------------- info
    def info(self):
        if getattr(self, "_info", None) is None:      # config and catalog are fixed while the server runs
            self._info = self._make_info()
        return self._info

    def _make_info(self):
        checked = []
        for p in presets.PRESETS:
            _, probs = planner.plan(p, self.cfg, self.catalog, self.body)
            checked.append({**p, "problems": probs, "ok": not any(x["level"] == "error" for x in probs)})
        return {"server_id": self.server_id, "catalog": self.catalog.public(),
                "grid": planner.grid_info(self.cfg), "unit_cm": webapi.UNIT,
                "inventory": {tid: {"name": t.get("name", tid), "count": self.catalog.count(tid),
                                    "colors": t["colors"], "shape": webapi.SHAPE.get(tid, "cube")}
                              for tid, t in self.catalog.types.items()},
                "presets": checked, "sim": self.world is not None, "use_color": self.cfg["use_color"],
                "ambiguous": [list(a[:2]) for a in self.catalog.ambiguities()]}

    def preset_builds(self):
        return webapi.preset_builds(self.cfg, self.catalog, self.body)

    # ---------------------------------------------------------------- planning
    def _design(self, data):
        if "build" in data:
            return webapi.build_to_design(data["build"])
        return data.get("design", {})

    def check(self, data):
        design = self._design(data)
        st, probs = planner.plan(design, self.cfg, self.catalog, self.body)
        settled = planner.settle(design, self.cfg, self.catalog)
        return {"problems": probs, "z": {str(i): s["z"] for i, s in settled.items()},
                "order": [s["index"] for s in st],
                "stability": webapi.stability(settled, probs)}

    def generate(self, data):
        # "fit": true scales the drawing up to fill the strip; the default reads
        # the board at its true size, so the board's ruler means something.
        fit_strip = bool(data.get("fit", False))
        # "color": prefer this colour while stock lasts (the UI's colour picker)
        prefer = data.get("color") or None
        if prefer not in {c for t in self.catalog.types.values() for c in t["colors"]}:
            prefer = None
        with self._gen_lock:          # one generation at a time; it's CPU heavy
            builds = webapi.generate(data.get("strokes", []), data.get("prompt", ""),
                                     self.cfg, self.catalog, self.body,
                                     fit_strip=fit_strip, prefer=prefer)
        return {"request_id": data.get("request_id"), "builds": builds}

    def dictate(self, data):
        with self._gen_lock:          # tile-based edits are CPU heavy; share the generate lock
            out = webapi.dictate(str(data.get("text", ""))[:300], data.get("build"),
                                 self.cfg, self.catalog, self.body)
        return {"request_id": data.get("request_id"), **out}

    def revise(self, data):
        """Change the blocks still to come on a running build, from speech.

        Two steps on purpose: without "apply" this only reports what it would
        do, so a stray sentence picked up by an open mic can never change a
        build that is going up. Nothing here can touch the safety stop.
        """
        text = str(data.get("text", ""))[:300]
        rb = self.run_build or {}
        if not self.builder.busy():
            return {"ok": False, "reply": "The arm isn't building right now.", "applied": False}
        if data.get("run_id") is not None and data["run_id"] != rb.get("run_id"):
            return {"ok": False, "reply": "That build has already finished.", "applied": False}
        old_steps = list(self.builder.plan_steps)
        fixed = self.builder.remaining()[1]
        with self._gen_lock:
            out = webapi.revise_build(text, rb.get("build"), fixed, old_steps,
                                      self.cfg, self.catalog, self.body)
        if not out["ok"] or not data.get("apply"):
            return {**out, "applied": False}
        ok, msg = self.builder.revise(out["steps"])
        return {**out, "applied": bool(ok), "reply": out["reply"] if ok else msg}

    # ---------------------------------------------------------------- running
    def build(self, data):
        design = self._design(data)
        if self.jog.busy() or self._expressing():
            return False, {"ok": False, "problems": [{"level": "error", "msg": "the arm is moving; wait a moment"}],
                           "run_id": None, "server_id": self.server_id}
        if self.fetch.busy():
            return False, {"ok": False, "problems": [{"level": "error", "msg": "the arm is handing over a block; "
                                                      "wait a moment"}], "run_id": None, "server_id": self.server_id}
        ok, probs, run_id = self.builder.start_build(design)
        if ok:
            # owner = who pressed Build (the app's signed-in user), so other people's tabs don't adopt it
            self.run_build = {"run_id": run_id, "build": data.get("build"), "owner": data.get("owner")}
        return ok, {"ok": ok, "problems": probs, "run_id": run_id if ok else None,
                    "server_id": self.server_id}

    def _current(self, data):
        rid = data.get("run_id")
        return rid is None or rid == self.builder.run_id

    def current_run(self):
        rb = self.run_build or {}
        same = rb.get("run_id") == self.builder.run_id
        return {"server_id": self.server_id, "run_id": self.builder.run_id, "busy": self.builder.busy(),
                "build": rb.get("build") if same else None, "owner": rb.get("owner") if same else None}

    def status(self):
        s = self.builder.snapshot()
        s.pop("blocks", None)
        s.pop("plan", None)
        s["server_id"] = self.server_id
        s["busy"] = self.builder.busy()
        s["fetching"] = self.fetch.busy()
        return s

    # ---------------------------------------------------------------- digital map
    def map(self):
        """Top-down picture of what the arm knows, as JSON (twin.html draws it)."""
        cfg, cat, b, f = self.cfg, self.catalog, self.builder, self.fetch
        L = cfg["layout"]
        s = b.snapshot()
        busy, fetching = b.busy(), f.busy()
        marker = s.get("claw")          # the gripper marker; its tip sits marker_to_fingertip below
        claw = None
        if marker:
            tip = self.jog.seen_tip()
            if tip:
                claw = {"x": round(tip[0], 2), "y": round(tip[1], 2), "z": round(tip[2], 2),
                        "marker_z": round(float(marker["z"]), 2)}   # the safety stop compares marker_z
        try:
            cx, cy, cz = self.jog.where()
            cmd = {"x": round(cx, 2), "y": round(cy, 2), "z": round(cz, 2)}
        except Exception:
            cmd = None
        blocks = []
        for blk in s.get("blocks", []):
            tid = blk.get("type")
            blocks.append({"id": blk.get("id"), "x": round(blk["x"], 2), "y": round(blk["y"], 2),
                           "yaw": round(float(blk.get("yaw", blk.get("angle", 0.0)) or 0.0), 1),
                           "angle": round(float(blk.get("angle", 0.0) or 0.0), 1),
                           "size": ([round(float(v), 2) for v in (blk.get("size") or [])][:2]
                                    or (sorted(cat.size(tid, blk.get("pose", 0))[:2], reverse=True)
                                        if tid in cat.types else None)),
                           "type": tid, "name": cat.types[tid].get("name", tid) if tid in cat.types else None,
                           "color": blk.get("color"), "zone": blk.get("zone") or None,
                           "round": blk.get("round"), "z": round(float(blk.get("z") or 0.0), 2)})
        # plan, layer by layer
        plan, states = s.get("plan", []), s.get("steps", [])
        levels = sorted({round(st["z"], 1) for st in plan})
        steps, current = [], None
        for i, st in enumerate(plan):
            state = states[i]["state"] if i < len(states) else "todo"
            if state == "active":
                current = i
            fx, fy = cat.footprint(st["type"], st.get("yaw", 0), st.get("pose", 0))
            steps.append({"i": i, "index": st.get("index"), "type": st["type"], "color": st.get("color"),
                          "x": st["x"], "y": st["y"], "z": st["z"], "h": st["h"], "yaw": st.get("yaw", 0.0),
                          "w": fx, "d": fy, "layer": levels.index(round(st["z"], 1)) + 1, "state": state})
        layer = steps[current]["layer"] if current is not None else None
        # what the arm is going for
        target, action = None, s.get("action") or ""
        placing = "placing" in action or "putting it down" in action
        if busy and self.pick_target and self.pick_target.get("run_id") == b.run_id and current is not None \
                and self.pick_target.get("step") == current:
            pt = self.pick_target
            live = next((x for x in blocks if x["id"] == pt["id"]), None)
            target = {"kind": "place" if placing else "pick", "id": pt["id"],
                      "x": live["x"] if live else pt["x"], "y": live["y"] if live else pt["y"],
                      "block": live, "step": current}
            if placing:
                target.update(x=steps[current]["x"], y=steps[current]["y"], z=steps[current]["z"])
        elif busy and current is not None and not placing:
            target = {"kind": "find", "step": current, "x": steps[current]["x"], "y": steps[current]["y"],
                      "block": None}
        elif fetching and f.target:
            ft = f.target
            blk = ft.get("block") or {}
            live = next((x for x in blocks if x["id"] == blk.get("id")), None)
            if ft.get("stage") == "place":
                target = {"kind": "place", "x": ft["place"][0], "y": ft["place"][1], "block": None}
            else:
                target = {"kind": "pick", "id": blk.get("id"), "x": (live or blk).get("x"),
                          "y": (live or blk).get("y"), "block": live}
        if target is not None and target.get("x") is not None:
            here = claw or cmd
            target["dist"] = round(math.hypot(here["x"] - target["x"], here["y"] - target["y"]), 1) if here else None
        return {"t": round(b.clock.time(), 2), "server_id": self.server_id, "run_id": b.run_id,
                "table": list(L["work_area"]), "build_area": list(L["build_area"]),
                "supply": {k: list(v) for k, v in L["supply"].items()}, "pickup": list(L["pickup"]),
                "base": list(L["base"]), "stop_distance": cfg["stop_distance"],
                "stop_claw_height": cfg["stop_claw_height"],
                "claw": claw, "claw_cmd": cmd, "hands": [{"x": round(h["x"], 1), "y": round(h["y"], 1),
                                                         "open": h.get("open")} for h in s.get("hands", [])],
                "blocks": blocks, "steps": steps, "layers": len(levels), "layer": layer, "current": current,
                "target": target, "phase": self._phase(s, busy, fetching, target, layer, len(levels), claw or cmd),
                "action": action, "mode": s.get("mode"), "paused": bool(s.get("paused")),
                "safety": bool(s.get("safety")), "prompt": s.get("prompt"), "busy": busy, "fetching": fetching,
                "jogging": self.jog.busy(), "expressing": self._expressing()}

    def _phase(self, s, busy, fetching, target, layer, layers, here):
        if s.get("safety"):
            return "paused: hand near the claw"
        if s.get("paused"):
            return "paused (say 'go on')"
        if self.jog.busy():
            return "moving where you asked"
        if self._expressing():
            return "expressing"
        if not (busy or fetching):
            return "idle"
        if s.get("prompt"):
            return "waiting: " + s["prompt"]
        lay = f" layer {layer}/{layers}" if layer and layers else ""
        if target is None:
            return s.get("action") or "working"
        if target["kind"] == "place":
            return "placing" + lay
        if target["kind"] == "find":
            return "looking for a block" + (" for" + lay if lay else "")
        d = target.get("dist")
        if d is None:
            return "picking"
        look = self.cfg.get("pick_look_cm", 10.0)
        if d > look + 3:
            return "moving to target"
        if d > 4:
            return "looking at target"
        if d > 1.5:
            return "aligning"
        return "picking"

    def view(self):
        """The MuJoCo twin's perspective view (JPEG bytes), or None."""
        return getattr(self.world, "view_jpeg", None)

    # ---------------------------------------------------------------- spoken commands
    # ---------------------------------------------------------------- conversation
    FAST = {"stop", "pause", "cancel", "resume", "back_off", "move_up", "move_down", "express",
            "hand_me", "put_there", "status"}

    def chat(self, data):
        """Talk to the assistant. Clear commands run at once (stopping must never wait for
        a model); anything else goes to the brain, which looks at the bench, answers,
        maybe shows a feeling, and issues commands through the same tested path.
        Builds are checked against the blocks on the bench first.
        -> {ok, reply, emotion, commands, results, source}"""
        text = str(data.get("text", ""))[:300]
        hist = self.__dict__.setdefault("_history", [])
        it = intents.parse(text, self.catalog)
        if it["intent"] in self.FAST:
            r = self.command({"text": text})
            return {"ok": r.get("ok", False), "reply": r.get("reply", ""), "emotion": None,
                    "commands": [text], "results": [r], "source": "rules"}
        th = brain.think(text, self.builder, self.catalog, self.cfg, hist)
        replies, results = [th["say"]] if th["say"] else [], []
        for c in th["commands"]:
            ci = intents.parse(c, self.catalog)
            if ci["intent"] == "preset":
                rv = brain.review(presets.get(ci["preset"]), brain.scene(self.builder, self.catalog, self.cfg),
                                  self.catalog)
                if not rv["ok"]:
                    replies.append(rv["say"])
                    results.append({"ok": False, "reply": rv["say"]})
                    th["emotion"] = rv["emotion"]
                    continue
            r = self.command({"text": c})
            results.append(r)
            if r.get("reply") and r["reply"] not in replies:
                replies.append(r["reply"])
        emo = th["emotion"]
        if emo and not th["commands"] and not self.builder.busy() and not self.fetch.busy():
            kw = {}
            if emo == "look_at":
                h = brain.nearest_hand(brain.scene(self.builder, self.catalog, self.cfg)["hands"])
                kw = {"x": h["x"], "y": h["y"]} if h else {"x": 25.0, "y": 5.0}
            threading.Thread(target=self._safe_express, args=(emo, kw), daemon=True).start()
        return {"ok": True, "reply": " ".join(replies).strip() or "Okay.", "emotion": emo,
                "commands": th["commands"], "results": results, "source": th["source"]}

    def _safe_express(self, name, kw):
        try:
            if not (self._expressing() or self.jog.busy()):
                self.builder.motion.express(name, **kw)
        except Exception as e:
            self.builder.log(f"emotion {name} skipped: {e!r}")

    def look(self):
        """What the assistant sees right now, in words and as data."""
        sc = brain.scene(self.builder, self.catalog, self.cfg)
        return {"say": brain.describe(sc, self.catalog), "scene": sc}

    def review(self, data):
        """Check a schematic (preset id or design) against the blocks on the bench."""
        design = presets.get(data["preset"]) if data.get("preset") else self._design(data)
        return brain.review(design, brain.scene(self.builder, self.catalog, self.cfg), self.catalog)

    def command(self, data):
        """Typed/spoken command -> {ok, intent, reply}. See intents.py for the phrases."""
        text = str(data.get("text", ""))[:300]
        it = intents.parse(text, self.catalog, use_llm=True)
        kind = it["intent"]
        out = {"ok": False, "intent": it}
        b, f = self.builder, self.fetch
        if kind in ("stop", "pause"):
            ok = b.pause() if b.busy() else f.pause()
            if not ok:
                b.arm.stop()
            reply = ("Stopped. Say 'go on' to continue or 'cancel' to end it." if ok
                     else "Okay, holding still." if not b.paused else "Already paused. Say 'go on' to continue.")
            return {**out, "ok": True, "reply": reply}
        if kind == "cancel":
            if b.busy():
                b.stop_build()
            elif not f.cancel():
                b.arm.stop()
                return {**out, "ok": True, "reply": "Nothing to cancel."}
            return {**out, "ok": True, "reply": "Okay, stopping."}
        if kind in ("back_off", "move_up", "move_down"):
            return self._jog(out, kind)
        if kind == "express":
            return self._express(out, it.get("emotion"))
        if kind == "resume":
            if b.paused:
                self._wait_jog()
                self.jog.restore()
                self.jog.saved = None
            if b.resume():
                return {**out, "ok": True, "reply": "Going on."}
            if b.safety_stopped:
                return {**out, "reply": "I'll go on once your hand is clear of the arm."}
            return {**out, "reply": "I'm not paused." if (b.busy() or f.busy()) else "Nothing to continue."}
        if kind == "status":
            s = b.snapshot()
            busy = b.busy() or f.busy()
            reply = (f"{s.get('mode', 'idle')}: {s.get('action', '')}" if busy
                     else "Idle. Ask me to build something or hand you a block.")
            if busy and s.get("total"):
                reply += f" (block {s.get('step', 0) + 1} of {s['total']})"
            return {**out, "ok": True, "reply": reply}
        if kind in ("preset", "build", "hand_me", "put_there", "clear") and (b.busy() or f.busy()):
            return {**out, "reply": "I'm busy right now. Say 'cancel' first, or wait until I'm done."}
        if kind == "preset":
            pid = it["preset"]
            build = next((x for x in self.preset_builds() if x.get("id") == f"preset-{pid}"), None)
            if build is None:
                return {**out, "reply": f"I don't know the {pid}."}
            return self._start(out, build, f"Building the {presets.get(pid)['name'].lower()}")
        if kind == "build":
            d = self.dictate({"text": text})
            if not d["builds"]:
                return {**out, "reply": d["reply"] or "I couldn't make a build out of that."}
            return self._start(out, d["builds"][0], d["reply"] or "Building that")
        if kind == "hand_me":
            return self._hand_me(out, it)
        if kind == "put_there":
            return self._put_there(out, it)
        if kind == "clear":
            return {**out, "reply": "I can't clear the table on my own yet. Please move the blocks back by hand."}
        return {**out, "reply": "Sorry, I didn't get that. Try 'build the house', 'hand me a cube', "
                                "'stop' or 'go on'."}

    # ---------------------------------------------------------------- nudges and emotions
    def _wait_jog(self, timeout=8.0):
        end = time.monotonic() + timeout
        while self.jog.busy() and time.monotonic() < end:
            time.sleep(0.05)

    def _jog(self, out, kind):
        """Pause whatever runs, nudge the claw, stay paused until "go on"."""
        b, f = self.builder, self.fetch
        if b.safety_stopped and kind == "move_down":
            return {**out, "reply": "Not moving down while your hand is near the claw."}
        if self._expressing():
            return {**out, "reply": "One moment, I'm in the middle of a gesture."}
        task = b.busy() or f.busy()
        if task and not b.paused:
            b.pause() if b.busy() else f.pause()
            time.sleep(0.15)           # let the interrupted move see the pause
        ok, msg, info = self.jog.run(kind, keep=task)
        words = {"back_off": "Backing off", "move_up": "Moving up", "move_down": "Moving down"}[kind]
        reply = f"{words}: {msg}." if ok else msg
        if task:
            reply += " Holding here; say 'go on' to continue."
        return {**out, "ok": ok, "reply": reply, "jog": info, "paused": bool(task)}

    def _express(self, out, name):
        b, f = self.builder, self.fetch
        if not name:
            return {**out, "reply": "Which feeling? Try 'look happy' or 'nod'."}
        if b.busy() or f.busy():
            return {**out, "reply": "I'm busy with a task right now. Ask me again when I'm done."}
        if self._expressing() or self.jog.busy():
            return {**out, "reply": "One moment, I'm still moving."}
        if b.safety_stopped:
            return {**out, "reply": "Not while your hand is near the claw."}
        kw = {}
        if name == "look_at":
            hands = b.snapshot().get("hands") or []
            kw = {"x": float(hands[0]["x"]), "y": float(hands[0]["y"])} if hands else {"x": 25.0, "y": 5.0}

        def go():
            try:
                r = b.motion.express(name, **kw)
                b.log(f"emotion {name}: {r}")
            except Exception as e:
                b.log(f"emotion {name} failed: {e!r}")
        b.log(f"emotion {name}")
        self._expr = threading.Thread(target=go, daemon=True)
        self._expr.start()
        nice = {"yes": "Nodding yes", "no": "Shaking my head", "happy": "Happy!", "sad": "Sad...",
                "confused": "Hmm, confused", "thinking": "Thinking", "greet": "Hello!", "excited": "Excited!",
                "sleepy": "Getting sleepy", "look_at": "Looking at you"}.get(name, name)
        return {**out, "ok": True, "emotion": name, "reply": nice if nice[-1] in ".!?" else nice + "."}

    def _start(self, out, build, reply):
        ok, body = self.build({"build": build})
        if not ok:
            why = "; ".join(p["msg"] for p in body["problems"] if p["level"] == "error") or "it can't be built"
            return {**out, "reply": f"I can't build that: {why}.", "problems": body["problems"]}
        n = len(build.get("blocks", []))
        return {**out, "ok": True, "run_id": body["run_id"], "build": build,
                "reply": f"{reply.rstrip('.')} ({n} block{'s' if n != 1 else ''})."}

    def _name(self, tid, color=None):
        nm = self.catalog.types[tid].get("name", tid).lower() if tid else "block"
        return f"{color} {nm}" if (color and self.cfg["use_color"]) else nm

    def _hand_me(self, out, it):
        f = self.fetch
        tid, color = it.get("type"), it.get("color")
        spot = tuple(self.cfg["layout"]["pickup"])
        pointed = f.pointed()
        target = pointed or spot
        blk = f.find(tid, color, avoid=[spot, target])
        what = self._name(tid, color)
        if blk is None:
            return {**out, "reply": f"I don't see a loose {what} I can reach outside the build strip. "
                                    "Put one on the table and ask again."}
        free = f.free_spot(*target, blk["type"])
        if free is None:
            return {**out, "reply": ("I can't reach the spot you pointed at." if pointed
                                     else "The hand-over spot is full. Take a block away first.")}
        target = free
        if not f.start(blk, target, f"handing over a {self._name(blk['type'], blk.get('color'))}"):
            return {**out, "reply": "I'm busy right now."}
        where = "where you pointed" if pointed else "on the hand-over spot"
        more = " (one at a time)" if it.get("count", 1) > 1 else ""
        return {**out, "ok": True, "block": {k: blk.get(k) for k in ("x", "y", "type", "color")},
                "target": list(target), "reply": f"Here's a {what}{more}: I'll put it {where}."}

    def _put_there(self, out, it):
        f = self.fetch
        target = f.pointed()
        if target is None:
            return {**out, "reply": "Point at the spot first, then say 'put it there'."}
        blk = None
        if f.last and not it.get("type"):
            blk = f.block_at(f.last["x"], f.last["y"])
            if blk is not None:
                blk = dict(blk, type=f.last["type"], color=f.last.get("color"))
        if blk is None:
            px, py = self.cfg["layout"]["pickup"]
            blk = f.block_at(px, py) if not it.get("type") else None
            if blk is not None:
                blk = dict(blk, type=f.guess_type(blk))
        if blk is None:
            blk = f.find(it.get("type"), it.get("color"), avoid=[target])
        if blk is None:
            return {**out, "reply": "Which block? I don't see one to move."}
        if not f.target_ok(*target, blk["type"]):
            return {**out, "reply": "I can't reach the spot you pointed at."}
        if not f.start(blk, target, f"moving the {self._name(blk['type'], blk.get('color'))}"):
            return {**out, "reply": "I'm busy right now."}
        return {**out, "ok": True, "target": list(target), "reply": "Okay, putting it there."}

    def frame(self):
        with self._lock:
            now = time.monotonic()
            if self._jpg is None or now - self._jpg_t > 0.1:
                img = render(self.builder, self.cfg, self.catalog, self.topdown)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    self._jpg, self._jpg_t = buf.tobytes(), now
            return self._jpg

    # ---------------------------------------------------------------- simulator helpers
    def sim_reset(self, design):
        if self.world is None:
            return {"ok": False, "msg": "not in simulator mode"}
        if self.builder.busy():
            return {"ok": False, "msg": "stop the build first"}
        self.world.clear_blocks()
        if design:
            self.world.fill_supply(presets.needed(design))
        return {"ok": True}

    def sim_add(self, data):
        """Drop a loose block on the simulated table: {type, color?, x, y, yaw?}."""
        if self.world is None:
            return {"ok": False, "msg": "not in simulator mode"}
        tid = data.get("type", "cube")
        if tid not in self.catalog.types:
            return {"ok": False, "msg": f"no block type {tid!r}"}
        color = data.get("color") or next(iter(self.catalog.types[tid]["colors"]), "red")
        self.world.add_block(tid, color, float(data["x"]), float(data["y"]), yaw=float(data.get("yaw", 0.0)))
        return {"ok": True}

    def sim_poke(self):
        if self.world is None:
            return {"ok": False}
        w = self.world
        b = self.cfg["layout"]["build_area"]
        p = w.person
        if p.state == "away":
            import numpy as np
            p.home = np.array([25.0, -5.0])
            p.hand = p.home.copy()
            claw = w.truth()["finger"]
            # stop inside the 10 cm safety radius but well clear of touching the claw
            target = (claw[0], claw[1] - 7) if claw[2] < 25 else ((b[0] + b[1]) / 2, b[2])
            p._start(target, "poke")
        return {"ok": True}


def _static(path):
    """A file from frontend/dist, or None. Never leaves the dist folder."""
    if not DIST.exists():
        return None
    p = (DIST / path.lstrip("/")).resolve()
    if DIST.resolve() not in p.parents and p != DIST.resolve():
        return None
    return p if p.is_file() else None


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json", cache=False):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # hashed build assets can be cached; everything else must never be stale
            self.send_header("Cache-Control", "public, max-age=31536000, immutable" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            try:
                return self._get()
            except Exception as e:          # keep the server up; show the error
                return self._send(500, {"error": repr(e)})

        def do_POST(self):
            try:
                return self._post()
            except ValueError as e:         # bad input (e.g. a build from the old mock generator)
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": repr(e)})

        def _get(self):
            path = self.path.split("?")[0]
            if path == "/api/info":
                return self._send(200, app.info())
            if path == "/api/look":
                return self._send(200, app.look())
            if path == "/api/presets":
                return self._send(200, {"builds": app.preset_builds()})
            if path == "/api/status":
                return self._send(200, app.status())
            if path == "/api/map":
                return self._send(200, app.map())
            if path == "/api/run":
                return self._send(200, app.current_run())
            if path == "/api/frame.jpg":
                return self._send(200, app.frame() or b"", "image/jpeg")
            if path == "/api/view.jpg":
                v = app.view()
                return self._send(200, v, "image/jpeg") if v else self._send(404, {"error": "no 3D view"})
            if path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            if path in ("/twin", "/twin/"):
                return self._send(200, (UI_DIR / "twin.html").read_bytes(), "text/html; charset=utf-8")
            if path in ("/classic", "/classic/"):
                return self._send(200, (UI_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            f = _static(path)
            if f is not None:
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                return self._send(200, f.read_bytes(), ctype, cache="/assets/" in path)
            index = _static("index.html")
            if index is not None:           # single-page app: /app, /login, ... all load index.html
                return self._send(200, index.read_bytes(), "text/html; charset=utf-8")
            return self._send(200, (UI_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")

        def _post(self):
            path = self.path.split("?")[0]
            if path == "/api/transcribe":    # raw audio bytes, not JSON
                n = int(self.headers.get("Content-Length") or 0)
                if n > speech.MAX_BYTES:
                    return self._send(413, {"error": "That recording is too long. Keep it under about a minute."})
                audio = self.rfile.read(n)
                try:
                    return self._send(200, {"text": speech.transcribe(audio, self.headers.get("Content-Type"))})
                except speech.SpeechError as e:
                    return self._send(e.status, {"error": e.msg})
            try:
                data = self._json()
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})
            b = app.builder
            if path == "/api/check":
                return self._send(200, app.check(data))
            if path == "/api/generate":
                return self._send(200, app.generate(data))
            if path == "/api/dictate":
                return self._send(200, app.dictate(data))
            if path == "/api/revise":
                return self._send(200, app.revise(data))
            if path == "/api/command":
                return self._send(200, app.command(data))
            if path == "/api/chat":
                return self._send(200, app.chat(data))
            if path == "/api/review":
                return self._send(200, app.review(data))
            if path == "/api/build":
                ok, body = app.build(data)
                return self._send(200 if ok else 409, body)
            if path in ("/api/stop", "/api/pause", "/api/resume"):
                if not app._current(data):
                    return self._send(409, {"ok": False, "error": "that build is no longer running",
                                            "run_id": b.run_id})
                if path == "/api/stop":
                    b.stop_build()
                    app.fetch.cancel()
                    ok = True
                elif path == "/api/pause":
                    ok = b.pause()
                else:
                    ok = b.resume()
                return self._send(200, {"ok": ok, "run_id": b.run_id})
            if path == "/api/log/clear":
                b.clear_log()
                return self._send(200, {"ok": True})
            if path == "/api/sim/reset":
                return self._send(200, app.sim_reset(data.get("design")))
            if path == "/api/sim/poke":
                return self._send(200, app.sim_poke())
            if path == "/api/sim/add":
                return self._send(200, app.sim_add(data))
            return self._send(404, {"error": "not found"})

    return H


def serve(app, host="127.0.0.1", port=8000):
    app.info()                       # plan the presets once now, so the first page load is instant
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    where = "3D app" if (DIST / "index.html").exists() else "classic UI (build frontend/ for the 3D app)"
    print(f"Sidekick UI: http://localhost:{port}   [{where}; classic UI at /classic]   (Ctrl+C to quit)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()

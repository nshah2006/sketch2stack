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
import mimetypes
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

from . import planner, presets, speech, webapi
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
        with self._gen_lock:          # one generation at a time; it's CPU heavy
            builds = webapi.generate(data.get("strokes", []), data.get("prompt", ""),
                                     self.cfg, self.catalog, self.body, fit_strip=fit_strip)
        return {"request_id": data.get("request_id"), "builds": builds}

    def dictate(self, data):
        with self._gen_lock:          # tile-based edits are CPU heavy; share the generate lock
            out = webapi.dictate(str(data.get("text", ""))[:300], data.get("build"),
                                 self.cfg, self.catalog, self.body)
        return {"request_id": data.get("request_id"), **out}

    # ---------------------------------------------------------------- running
    def build(self, data):
        design = self._design(data)
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
        return s

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
            if path == "/api/presets":
                return self._send(200, {"builds": app.preset_builds()})
            if path == "/api/status":
                return self._send(200, app.status())
            if path == "/api/run":
                return self._send(200, app.current_run())
            if path == "/api/frame.jpg":
                return self._send(200, app.frame() or b"", "image/jpeg")
            if path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
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
            if path == "/api/build":
                ok, body = app.build(data)
                return self._send(200 if ok else 409, body)
            if path in ("/api/stop", "/api/pause", "/api/resume"):
                if not app._current(data):
                    return self._send(409, {"ok": False, "error": "that build is no longer running",
                                            "run_id": b.run_id})
                if path == "/api/stop":
                    b.stop_build()
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

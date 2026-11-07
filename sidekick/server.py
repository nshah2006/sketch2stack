"""Web UI server: presets, front-view designer, live view, build control.

    python -m sidekick.main ui            # simulator or real arm per config
    then open http://localhost:8000

Standard library only (http.server), so there is nothing extra to install.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

from . import planner, presets
from .overlay import TopDown, render

UI_DIR = Path(__file__).parent / "ui"


class App:
    def __init__(self, cfg, catalog, builder, body, world=None):
        self.cfg, self.catalog, self.builder, self.body, self.world = cfg, catalog, builder, body, world
        self.topdown = TopDown(cfg)
        self._jpg = None
        self._jpg_t = 0.0
        self._lock = threading.Lock()

    def info(self):
        checked = []
        for p in presets.PRESETS:
            _, probs = planner.plan(p, self.cfg, self.catalog, self.body)
            checked.append({**p, "problems": probs,
                            "ok": not any(x["level"] == "error" for x in probs)})
        return {"catalog": self.catalog.public(), "grid": planner.grid_info(self.cfg),
                "presets": checked, "sim": self.world is not None,
                "ambiguous": [list(a[:2]) for a in self.catalog.ambiguities()]}

    def check(self, design):
        st, probs = planner.plan(design, self.cfg, self.catalog, self.body)
        settled = planner.settle(design, self.cfg, self.catalog)
        return {"problems": probs, "z": {str(i): s["z"] for i, s in settled.items()},
                "order": [s["index"] for s in st]}

    def frame(self):
        with self._lock:
            now = time.monotonic()
            if self._jpg is None or now - self._jpg_t > 0.1:
                img = render(self.builder, self.cfg, self.catalog, self.topdown)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    self._jpg, self._jpg_t = buf.tobytes(), now
            return self._jpg

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
            target = (claw[0], claw[1] - 4) if claw[2] < 25 else ((b[0] + b[1]) / 2, b[2])
            p._start(target, "poke")
        return {"ok": True}


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
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
            except Exception as e:
                return self._send(500, {"error": repr(e)})

        def _get(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._send(200, (UI_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/info":
                return self._send(200, app.info())
            if path == "/api/status":
                s = app.builder.snapshot()
                s.pop("blocks", None)
                return self._send(200, s)
            if path == "/api/frame.jpg":
                jpg = app.frame()
                return self._send(200, jpg or b"", "image/jpeg")
            return self._send(404, {"error": "not found"})

        def _post(self):
            path = self.path.split("?")[0]
            try:
                data = self._json()
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})
            if path == "/api/check":
                return self._send(200, app.check(data.get("design", {})))
            if path == "/api/build":
                ok, probs = app.builder.start_build(data.get("design", {}))
                return self._send(200 if ok else 409, {"ok": ok, "problems": probs})
            if path == "/api/stop":
                app.builder.stop_build()
                return self._send(200, {"ok": True})
            if path == "/api/sim/reset":
                return self._send(200, app.sim_reset(data.get("design")))
            if path == "/api/sim/poke":
                return self._send(200, app.sim_poke())
            return self._send(404, {"error": "not found"})

    return H


def serve(app, host="127.0.0.1", port=8000):
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"Sidekick UI: http://localhost:{port}   (Ctrl+C to quit)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()

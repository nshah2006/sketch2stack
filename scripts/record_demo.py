"""Record one twin build as a side-by-side video for humans to check what is going on.

Left: the ONE overhead camera (60 cm) exactly as the arm sees it, with what it
detects drawn on top (blocks, claw marker, hand, the planned spots).
Right: an angled observer view - for people only, the arm never uses it.
Bottom: what the arm is doing and its latest log line.

    source /mnt/Data/Tushaar/nvidia_userspace/env.sh
    SIDEKICK_NO_DB=1 venv/bin/python scripts/record_demo.py --preset house --bump 0.5 --out demo
Writes <out>/frames/*.jpg; encode with scripts/encode_demo.py (LeRobot venv has PyAV/H.264).
"""
import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sidekick import body_model as bm  # noqa: E402
from sidekick import config as C  # noqa: E402
from sidekick import presets  # noqa: E402
from sidekick.arm import make_arm  # noqa: E402
from sidekick.builder import Builder  # noqa: E402
from sidekick.catalog import Catalog  # noqa: E402
from sidekick.twin import make_twin  # noqa: E402

W, H = 640, 360            # each panel
CAP = 70                   # caption strip height


def overlay(obs, b, calib, cfg):
    img = cv2.resize(obs.image, (W, H), interpolation=cv2.INTER_AREA)
    s = W / obs.image.shape[1]
    for d in obs.detections:
        if d.get("box_px"):
            pts = (np.array(d["box_px"]) * s).astype(np.int32)
            cv2.polylines(img, [pts], True, (0, 200, 255), 2)
    for st in list(b.plan_steps):
        if calib is not None:
            u, v = calib.table_to_pixel(st["x"], st["y"], st["z"])
            cv2.drawMarker(img, (int(u * s), int(v * s)), (80, 220, 80), cv2.MARKER_CROSS, 14, 2)
    if obs.claw_px is not None:
        u, v = obs.claw_px
        cv2.circle(img, (int(u * s), int(v * s)), int(cfg["claw_blank_px"] * s), (255, 120, 0), 1)
        cv2.circle(img, (int(u * s), int(v * s)), 4, (255, 120, 0), -1)
    for h in obs.hands:
        if h.get("px"):
            hull = cv2.convexHull((np.array(h["px"]) * s).astype(np.int32))
            cv2.polylines(img, [hull], True, (60, 60, 255), 2)
    cv2.rectangle(img, (0, 0), (W, 22), (0, 0, 0), -1)
    cv2.putText(img, "ARM'S CAMERA (overhead, 60 cm) + what it detects", (6, 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="house")
    ap.add_argument("--bump", type=float, default=0.5)
    ap.add_argument("--reach", type=float, default=0.03)
    ap.add_argument("--seed", type=int, default=105)
    ap.add_argument("--babble", default="sidekick_data/fleet/babble_5.jsonl")
    ap.add_argument("--speed", type=float, default=2.0)
    ap.add_argument("--fps", type=float, default=8.0, help="video frames per SIM second")
    ap.add_argument("--out", default="sidekick_data/demo")
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()
    out = Path(a.out)
    shutil.rmtree(out, ignore_errors=True)
    (out / "frames").mkdir(parents=True)
    cfg = C.load(overrides={"use_sim": True})
    cfg["layout"]["pickup"] = [35.0, 30.0]
    cat = Catalog.load()
    w = make_twin(cfg, cat, speed=a.speed, seed=a.seed, view_fps=a.fps)
    P, Y = bm.load_samples(Path(a.babble))
    body, _ = bm.train(P, Y, cfg, log=None)
    arm = make_arm(cfg, world=w).connect()
    arm.start()
    w.bump_rate = a.bump
    w.person.reach_rate = a.reach
    design = presets.get(a.preset)
    b = Builder(cfg, cat, w, arm, body, feeder=w.person, log_dir=tempfile.mkdtemp())
    b.start_build(design)
    n, t_next = 0, w.clock.time()
    t_end = t_next + a.timeout
    events = []
    while b.busy() and w.clock.time() < t_end:
        now = w.clock.time()
        if now < t_next or b.obs is None or w.view_jpeg is None:
            time.sleep(0.01)
            continue
        t_next = now + 1.0 / a.fps
        snap = b.snapshot()
        left = overlay(b.obs, b, w.calib, cfg)
        right = cv2.resize(cv2.imdecode(np.frombuffer(w.view_jpeg, np.uint8), cv2.IMREAD_COLOR), (W, H))
        cv2.rectangle(right, (0, 0), (W, 22), (0, 0, 0), -1)
        cv2.putText(right, "observer view (for people only - the arm never sees this)", (6, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        frame = np.zeros((H + CAP, 2 * W, 3), np.uint8)
        frame[:H, :W], frame[:H, W:] = left, right
        act = snap.get("action") or snap.get("mode") or ""
        last = (snap.get("log") or [""])[-1]
        col = (80, 80, 255) if snap.get("safety") else (255, 255, 255)
        cv2.putText(frame, f"t={now:5.1f}s  step {snap.get('step', 0)}/{snap.get('total', 0)}  {act}"[:110],
                    (8, H + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 1, cv2.LINE_AA)
        cv2.putText(frame, f"log: {last}"[:140], (8, H + 54), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (190, 190, 190), 1,
                    cv2.LINE_AA)
        cv2.imwrite(str(out / "frames" / f"{n:05d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if last and (not events or events[-1]["msg"] != last):
            events.append({"t": round(now, 1), "frame": n, "msg": last})
        n += 1
    snap = b.snapshot()
    steps = list(b.plan_steps)
    b.close()
    time.sleep(0.5)
    blocks = [{"type": q.type, "x": round(q.x, 1), "y": round(q.y, 1), "z": round(q.z, 1)} for q in w.blocks]
    summary = {"preset": a.preset, "result": snap.get("result"), "frames": n, "fps": a.fps, "bumps": w.bumps,
               "plan": [{"type": s["type"], "x": s["x"], "y": s["y"], "z": s["z"]} for s in steps],
               "blocks": blocks, "events": events, "safety_contacts": w.contacts}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in ("preset", "result", "frames", "bumps", "safety_contacts")}))
    arm.close()
    w.stop()


if __name__ == "__main__":
    main()

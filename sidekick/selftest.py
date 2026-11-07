"""Self-test (no hardware) and the simulator test suite.

    python -m sidekick.main selftest [--quick]
    python -m sidekick.main simtest -n 3

selftest checks each part on its own plus one full simulated build.
simtest is the longer run: new random arm errors several times (does the
method adapt?), every preset built repeatedly with a person reaching in.
"""
import math
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

from . import config as C
from .catalog import Catalog

PASS, FAIL = "PASS", "FAIL"


def _report(name, ok, detail=""):
    print(f"[{PASS if ok else FAIL}] {name}{(': ' + detail) if detail else ''}", flush=True)
    return ok


# ===================================================================== 1. calibration math
def test_calibration(cfg):
    from .calibration import Calibration, square_object_points, table_marker_corners
    K = np.array([[1000, 0, 640], [0, 1000, 360], [0, 0, 1]], float)
    cam_pos = np.array([25.0, 17.5, 60.0])
    R = np.diag([1.0, -1.0, -1.0])                    # looking straight down, image top = far side
    rvec = cv2.Rodrigues(R)[0]
    tvec = (-R @ cam_pos).reshape(3, 1)
    proj = lambda pts: cv2.projectPoints(np.asarray(pts, float), rvec, tvec, K, None)[0].reshape(-1, 2)
    markers = {int(k): proj(table_marker_corners(x, y, cfg["table_marker_size"]))
               for k, (x, y) in cfg["layout"]["markers"].items()}
    cal = Calibration(K=K)
    res = cal.calibrate_table(markers, cfg)
    err_pos = 0.0
    for (x, y, z) in ((10, 10, 3.0), (40, 30, 3.0), (25, 20, 0.0), (5, 33, 6.0)):
        u, v = proj([[x, y, z]])[0]
        px, py = cal.pixel_to_table(u, v, z)
        err_pos = max(err_pos, math.hypot(px - x, py - y))
    # a claw marker tilted 10 degrees, 12 cm up
    tilt = np.radians(10)
    Rm = cv2.Rodrigues(np.array([tilt, 0, 0]))[0]
    center = np.array([22.0, 24.0, 12.0])
    pts = (Rm @ square_object_points(cfg["claw_marker_size"]).T).T + center
    claw = cal.claw_pose(proj(pts), cfg["claw_marker_size"])
    claw_err = math.dist([claw["x"], claw["y"], claw["z"]], center)
    down_err = abs(claw["down"] - math.cos(tilt))
    ok = abs(res["height"] - 60) < 0.1 and err_pos < 0.1 and claw_err < 0.1 and down_err < 0.01
    return _report("calibration math", ok,
                   f"camera height {res['height']:.2f} cm, block error {err_pos * 10:.2f} mm, "
                   f"claw error {claw_err * 10:.2f} mm, down-ness error {down_err:.4f}")


# ===================================================================== 2. markers
def test_markers(cfg):
    from .calibration import detect_markers, make_marker_sheets
    with tempfile.TemporaryDirectory() as d:
        make_marker_sheets(cfg, d)
        found = set()
        for name in ("table_markers", "claw_marker"):
            img = cv2.imread(str(Path(d) / f"{name}.png"), cv2.IMREAD_GRAYSCALE)
            found |= set(detect_markers(cv2.resize(img, None, fx=0.5, fy=0.5)))
    want = {0, 1, 2, 3, cfg["layout"]["claw_marker_id"]}
    return _report("marker sheets generated then detected", want <= found, f"found {sorted(found)}")


# ===================================================================== 3. firmware rules
def test_firmware(cfg):
    from .clock import SimClock
    from .sim import FirmwareEmulator
    clk = SimClock(1.0)
    emu = FirmwareEmulator(clk)
    t = [0.0]

    def run(seconds):
        end = t[0] + seconds
        while t[0] < end:
            t[0] += 0.01
            emu.update(t[0])

    def send(line):
        emu.receive(line)
        run(0.03)

    checks = {}
    send("?")
    checks["reply"] = "OK sidekick 1" in list(emu.out.queue)
    send("C 1 1000 2000")
    send("P 1500 3000 1500 1500 1500 1500")
    checks["P clamps"] = emu.cur[1] == 2000
    send("C 1 500 2600")
    checks["limits never wider"] = emu.jmin[1] == 600 and emu.jmax[1] == 2400
    send("A")
    run(1.0)
    checks["attach one at a time"] = sum(emu.attached) in (2, 3) and not all(emu.attached)
    run(2.0)
    checks["all attached"] = all(emu.attached)
    send("J 1500 1500 1500 1500 1500 1500")
    send("J 1500 9999 1500 1500 1500 1500")
    checks["J clamps"] = emu.target[1] == 2400
    send("J 1500 1500 1500 1500 1500 1500")
    for _ in range(10):
        send("H")
    send("J 2000 1500 1500 1500 1500 1500")
    run(0.2)
    send("S")
    checks["stop freezes"] = emu.target == emu.cur and emu.cur[0] < 2000
    send("J 1000 1500 1500 1500 1500 1500")
    run(0.3)
    run(1.2)                                        # silence
    checks["watchdog freezes"] = emu.frozen and emu.target == emu.cur and emu.led == 4
    send("H")
    checks["any line clears frozen"] = not emu.frozen
    send("J 1500 1500 x 1500 1500 1500")
    checks["malformed ignored"] = emu.target[2] == 1500
    send("V 99")
    checks["V range"] = emu.step_us == 8
    ok = all(checks.values())
    bad = [k for k, v in checks.items() if not v]
    return _report("firmware rules on the emulator", ok, "all rules hold" if ok else f"failed: {bad}")


# ===================================================================== 4. planner
def test_planner(cfg):
    from . import presets
    from .planner import plan, validate
    cat = Catalog.load()
    checks = {}
    st, probs = validate({"blocks": [
        {"type": "cube", "color": "red", "x": 2, "z_hint": 0},
        {"type": "cube", "color": "red", "x": 2, "z_hint": 0}]}, cfg, cat)
    checks["gravity stacks"] = abs(st[1]["z"] - 3.0) < 1e-6 and not probs
    _, probs = validate({"blocks": [
        {"type": "roof", "color": "yellow", "x": 2, "z_hint": 0},
        {"type": "cube", "color": "red", "x": 3, "z_hint": 3}]}, cfg, cat)
    checks["nothing on a roof"] = any("can't sit on" in p["msg"] for p in probs)
    _, probs = validate({"blocks": [
        {"type": "cube", "color": "red", "x": 0, "z_hint": 0},
        {"type": "bar", "color": "green", "x": 0, "z_hint": 3}]}, cfg, cat)
    checks["tipping detected"] = any("tip" in p["msg"] for p in probs)
    _, probs = validate({"blocks": [{"type": "bar", "color": "green", "x": 15, "z_hint": 0}]}, cfg, cat)
    checks["out of strip"] = any("sticks out" in p["msg"] for p in probs)
    _, probs = validate({"blocks": [{"type": "cube", "color": "red", "x": 3 * i, "z_hint": 0}
                                    for i in range(3)]}, cfg, cat)
    checks["inventory"] = any("owned" in p["msg"] for p in probs)
    steps, _ = plan(presets.get("gate"), cfg, cat)
    checks["bottom first"] = [s["z"] for s in steps] == sorted(s["z"] for s in steps)
    for p in presets.PRESETS:
        _, probs = plan(p, cfg, cat)
        checks[f"preset {p['id']} valid"] = not any(x["level"] == "error" for x in probs)
    bad = [k for k, v in checks.items() if not v]
    return _report("planner (gravity, support, roof, inventory, order, presets)", not bad,
                   "ok" if not bad else f"failed: {bad}")


# ===================================================================== 5. classification
def test_classify(cfg):
    cat = Catalog.load()
    rng = np.random.default_rng(0)
    total = good = 0
    for tid, t in cat.types.items():
        w, d, _ = cat.size(tid)
        for color in t["colors"]:
            for _ in range(50):
                L = max(w, d) + rng.normal(0, 0.3)
                S = min(w, d) + rng.normal(0, 0.3)
                total += 1
                good += cat.classify(color, L, S, cat.round_(tid)) == tid
    amb = cat.ambiguities()
    note = f", camera-ambiguous pairs: {[(a, b) for a, b, _ in amb]}" if amb else ""
    return _report("block type from color + outline + footprint", good / total > 0.97,
                   f"{good}/{total} correct with 3 mm noise{note}")


# ===================================================================== 6. body model in the sim
def _sim_body(cfg, seed, data_dir, n=800):
    from . import body_model as bm
    from .arm import make_arm
    from .sim import make_world
    cat = Catalog.load()
    w = make_world(cfg, cat, speed=40, seed=seed)
    arm = make_arm(cfg, world=w).connect()
    arm.start()
    out = Path(data_dir) / f"babble_{seed}.jsonl"
    bm.babble(arm, w, cfg, n=n, out_path=out, rng=np.random.default_rng(seed))
    P, Y = bm.load_samples(out)
    body, held = bm.train(P, Y, cfg, log=None)
    return w, arm, body, held


def _grid_error(cfg, w, arm, body):
    x0, x1, y0, y1 = cfg["layout"]["build_area"]
    errs = []
    for x in np.linspace(x0 + 1, x1 - 1, 5):
        for y in np.linspace(y0, y1, 4):
            z = cfg.grasp_z(0, 3.0)
            s = body.solve([x, y, z])
            arm.move(s["pulses"] + [1500, cfg["claw_open"]])
            w.clock.sleep(0.3)
            errs.append(float(np.linalg.norm(w.truth()["finger"] - [x, y, z])))
    return float(np.mean(errs)), float(np.max(errs))


def test_body(cfg, data_dir):
    t0 = time.time()
    w, arm, body, held = _sim_body(cfg, 1, data_dir)
    mean, worst = _grid_error(cfg, w, arm, body)
    arm.close()
    w.stop()
    body.save(Path(data_dir) / "body_sim.pt")
    ok = held < 1.0 and mean < 1.0 and worst < 2.0
    return _report("body model on the simulated arm (800 babbles, 5x4 grid, no correction)", ok,
                   f"held-out {held:.2f} cm, grid mean {mean:.2f} cm, worst {worst:.2f} cm, "
                   f"{time.time() - t0:.0f}s"), body


# ===================================================================== 7. full build
def sim_build(cfg, body, preset_id, seed=2, speed=10, reach_rate=0.0, timeout=900):
    from . import presets
    from .arm import make_arm
    from .builder import Builder
    from .sim import make_world
    cat = Catalog.load()
    w = make_world(cfg, cat, speed=speed, seed=seed, reach_rate=reach_rate)
    arm = make_arm(cfg, world=w).connect()
    arm.start()
    design = presets.get(preset_id)
    w.fill_supply(presets.needed(design)[:2])        # the rest is brought by the simulated person
    with tempfile.TemporaryDirectory() as d:
        b = Builder(cfg, cat, w, arm, body, feeder=w.person, log_dir=d)
        started, probs, _ = b.start_build(design)
        t0 = time.time()
        while started and b.busy() and time.time() - t0 < timeout:
            time.sleep(0.3)
        res = b.snapshot()["result"] if started else "not started: " + "; ".join(p["msg"] for p in probs)
        steps = list(b.plan_steps)
        b.close()
    arm.close()
    w.stop()
    # compare the built blocks against the plan
    worst, used = 0.0, set()
    for s in steps:
        cands = [bl for bl in w.blocks if bl.type == s["type"] and bl.color == s["color"] and bl.id not in used]
        if not cands:
            worst = 99
            continue
        bl = min(cands, key=lambda q: math.hypot(q.x - s["x"], q.y - s["y"]))
        used.add(bl.id)
        e = max(math.hypot(bl.x - s["x"], bl.y - s["y"]), abs(bl.z - s["z"]))
        worst = max(worst, e)
    return {"result": res, "worst_cm": worst, "contacts": w.contacts, "table_hits": w.table_hits,
            "virtual_s": w.clock.time()}


def test_build(cfg, body):
    r = sim_build(cfg, body, "house")
    ok = r["result"] == "done" and r["worst_cm"] < 1.5 and r["contacts"] == 0
    return _report("full simulated build (House preset, person brings missing blocks)", ok,
                   f"{r['result']}, worst placement {r['worst_cm'] * 10:.1f} mm, contacts {r['contacts']}, "
                   f"{r['virtual_s']:.0f} s sim time")


def run(cfg, quick=False):
    cfg = C.load(overrides={"use_sim": True})
    print("Sidekick self-test (no hardware)\n", flush=True)
    results = [test_calibration(cfg), test_markers(cfg), test_firmware(cfg), test_planner(cfg),
               test_classify(cfg)]
    if not quick:
        with tempfile.TemporaryDirectory() as d:
            ok, body = test_body(cfg, d)
            results.append(ok)
            results.append(test_build(cfg, body))
    n = sum(results)
    print(f"\n{n}/{len(results)} passed", flush=True)
    return all(results)


def simtest(cfg, runs=3):
    """Phase 2S: randomization test and repeated preset builds with a person reaching in."""
    from . import presets
    cfg = C.load(overrides={"use_sim": True})
    print("Simulator test suite\n", flush=True)
    ok_all = True
    with tempfile.TemporaryDirectory() as d:
        print("Randomization: new random arm errors, re-babble and retrain each time", flush=True)
        body = None
        for seed in range(10, 10 + max(3, runs)):
            w, arm, body, held = _sim_body(cfg, seed, d)
            mean, worst = _grid_error(cfg, w, arm, body)
            arm.close()
            w.stop()
            ok = held < 1.0 and mean < 1.0 and worst < 2.0
            ok_all &= _report(f"  arm #{seed}", ok, f"held-out {held:.2f}, grid mean {mean:.2f}, worst {worst:.2f} cm")
        print("\nBuilds (person feeds blocks and sometimes reaches into the work area)", flush=True)
        total = done = contacts = 0
        for p in presets.PRESETS:
            for k in range(runs):
                r = sim_build(cfg, body, p["id"], seed=100 + k, speed=10, reach_rate=0.03)
                total += 1
                done += r["result"] == "done"
                contacts += r["contacts"]
                _report(f"  {p['id']} #{k + 1}", r["result"] == "done" and r["contacts"] == 0,
                        f"{r['result']}, worst {r['worst_cm'] * 10:.1f} mm, contacts {r['contacts']}")
        ok_all &= done == total and contacts == 0
        print(f"\nbuilds done {done}/{total}, contacts {contacts}", flush=True)
    return ok_all

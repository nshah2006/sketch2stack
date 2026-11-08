"""Cluttered-table test on the twin: blocks of mixed types and colors lie all over
the table (no supply zones, nobody feeding), and the arm must pick the block each
step needs, in the planner's order, and finish the build.

    source /mnt/Data/Tushaar/nvidia_userspace/env.sh
    SIDEKICK_NO_DB=1 venv/bin/python scripts/clutter_test.py --presets house,bridge,gate,tower,skyline

Per build it prints every pick (what the step needed vs what the claw really
lifted, from the twin's ground truth), placement errors and wrong picks.
The default catalog owns one blue short cylinder; bridge and gate need two, so
counts are raised in memory to what each preset needs.
"""
import argparse
import json
import math
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sidekick import body_model as bm  # noqa: E402
from sidekick import config as C  # noqa: E402
from sidekick import presets  # noqa: E402
from sidekick.arm import make_arm  # noqa: E402
from sidekick.builder import Builder  # noqa: E402
from sidekick.catalog import Catalog  # noqa: E402
from sidekick.twin import make_twin  # noqa: E402


def held(w):
    with w.lock:
        return [b for b in w.blocks if b.held]


def run_one(pid, a, body, log_dir):
    cfg = C.load(overrides={"use_sim": True})
    cfg["use_color"] = True
    cfg["gestures"] = False
    cfg["auto_emotions"] = False
    cat = Catalog.load()
    design = presets.get(pid)
    need = presets.needed(design)
    for tid, color in set(need):
        cols = cat.types[tid]["colors"]
        cols[color] = max(cols.get(color, 0), need.count((tid, color)))
    w = make_twin(cfg, cat, speed=a.speed, seed=a.seed, view_fps=0)
    rng = np.random.default_rng(a.scatter_seed + sum(map(ord, pid)))
    tallest = max(cat.height(t) for t in cat.types)

    def reachable(x, y):
        return all(body.solve([x, y, z])["reachable"] for z in (cfg.grasp_z(0, 1.4), cfg.hover_z(0, tallest)))

    placed = w.scatter(a.n, rng=rng, required=need, colors=a.colors.split(",") if a.colors else None,
                       reachable=reachable)
    arm = make_arm(cfg, world=w).connect()
    arm.start()
    t0 = w.clock.time()
    while w.calib is None and w.clock.time() - t0 < 10:
        time.sleep(0.1)
    b = Builder(cfg, cat, w, arm, body, feeder=None, log_dir=log_dir)
    w.clock.sleep(1.5)                             # a few frames for the tracker
    picks = []
    cur = {"step": None}
    do_step, pick = b._do_step, b.motion.pick

    def wrap_step(i, st):
        cur["step"] = (i, st)
        return do_step(i, st)

    def wrap_pick(blk, g):
        i, st = cur["step"]
        with w.lock:
            near = min(w.blocks, key=lambda q: math.hypot(q.x - blk["x"], q.y - blk["y"]))
        r = pick(blk, g)
        got = held(w)
        rec = {"step": i, "need": f"{st['color']} {st['type']}", "seen": f"{blk['color']} {blk['type']}",
               "at": [round(blk["x"], 1), round(blk["y"], 1)],
               "aimed": f"{near.color} {near.type}", "r": r,
               "got": f"{got[0].color} {got[0].type}" if got else None}
        rec["wrong"] = (rec["got"] or rec["aimed"]) != rec["need"]
        picks.append(rec)
        return r

    b._do_step, b.motion.pick = wrap_step, wrap_pick
    ok, probs, _ = b.start_build(design)
    if not ok:
        print(pid, "plan rejected", probs)
        b.close(); arm.close(); w.stop()
        return {"preset": pid, "result": "rejected"}
    t_end = w.clock.time() + a.timeout
    prompt_since, stuck = None, None
    while b.busy() and w.clock.time() < t_end:
        snap = b.snapshot()
        if snap.get("prompt"):
            prompt_since = prompt_since or w.clock.time()
            if w.clock.time() - prompt_since > a.prompt_wait:
                stuck = snap["prompt"]
                b.stop_build()
        else:
            prompt_since = None
        time.sleep(0.2)
    if b.busy():
        b.stop_build()
    for _ in range(50):
        if not b.busy():
            break
        time.sleep(0.2)
    w.clock.sleep(1.0)
    snap = b.snapshot()
    states = [s["state"] for s in snap["steps"]]
    errs = []
    with w.lock:
        blocks = list(w.blocks)
    for st, state in zip(b.plan_steps, states):
        if state != "done":
            continue
        cands = [q for q in blocks if q.type == st["type"] and q.color == st["color"] and not q.held]
        if cands:
            q = min(cands, key=lambda q: math.hypot(q.x - st["x"], q.y - st["y"]) + abs(q.z - st["z"]))
            errs.append(round(math.hypot(q.x - st["x"], q.y - st["y"]), 2))
    res = {"preset": pid, "result": snap.get("result"), "steps": len(b.plan_steps),
           "done": states.count("done"), "placed": len(placed), "picks": picks,
           "wrong_picks": sum(p["wrong"] for p in picks), "pick_attempts": len(picks),
           "place_err_cm": errs, "toppled": len(w.toppled), "stuck": stuck,
           "sim_s": round(w.clock.time() - t0, 1)}
    b.close()
    arm.close()
    w.stop()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--presets", default="house,bridge,gate,tower,skyline")
    ap.add_argument("--n", type=int, default=15, help="blocks on the table (incl. the ones the build needs)")
    ap.add_argument("--colors", default="", help="limit distractor colors, e.g. red,blue (default: any owned)")
    ap.add_argument("--seed", type=int, default=105, help="twin seed (must match the babble file)")
    ap.add_argument("--scatter-seed", type=int, default=0)
    ap.add_argument("--babble", default="sidekick_data/fleet/babble_5.jsonl")
    ap.add_argument("--speed", type=float, default=2.0)
    ap.add_argument("--timeout", type=float, default=500, help="sim s per build")
    ap.add_argument("--prompt-wait", type=float, default=20, help="sim s a prompt may wait before giving up")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    cfg = C.load(overrides={"use_sim": True})
    P, Y = bm.load_samples(Path(a.babble))
    body, err = bm.train(P, Y, cfg, log=None)
    print(f"body model trained ({len(P)} samples, held-out {err:.2f} cm)")
    log_dir = tempfile.mkdtemp()
    results = []
    for pid in a.presets.split(","):
        r = run_one(pid, a, body, log_dir)
        results.append(r)
        print(f"\n== {pid}: {r['result']}  {r.get('done')}/{r.get('steps')} placed, "
              f"{r.get('wrong_picks')} wrong of {r.get('pick_attempts')} picks, "
              f"place err {r.get('place_err_cm')}, toppled {r.get('toppled')}, "
              f"{r.get('placed')} blocks on the table, {r.get('sim_s')} sim s"
              + (f"\n   stuck: {r['stuck']}" if r.get("stuck") else ""))
        for p in r.get("picks", []):
            print(f"   step {p['step'] + 1}: need {p['need']:16s} seen {p['seen']:16s} at {p['at']}  "
                  f"aimed at {p['aimed']:16s} -> {p['r']:11s} got {p['got']}" + ("  WRONG" if p["wrong"] else ""))
    n_p = sum(r.get("pick_attempts", 0) for r in results)
    n_w = sum(r.get("wrong_picks", 0) for r in results)
    fin = sum(r.get("result") == "done" and r.get("done") == r.get("steps") for r in results)
    print(f"\nSUMMARY: {fin}/{len(results)} builds finished; wrong picks {n_w}/{n_p}"
          f" ({100.0 * n_w / max(1, n_p):.0f}%)")
    print(f"log dir: {log_dir}")
    if a.out:
        Path(a.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()

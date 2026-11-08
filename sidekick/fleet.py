"""Many digital twins at once, each building presets while a simulated person
feeds blocks and reaches in. Watch them all in the browser.

    python -m sidekick.fleet -n 8 --port 8765 [--gl /path/to/nvidia_userspace]

Each worker is its own process with its own MuJoCo world (twin.py), its own
flawed arm (random gains/offsets), its own body model (babbled through the
rendered camera, like the real arm), and its own person (reach rate varies).
It runs the real builder on the real perception code, one preset after
another, and appends one line per build to <out>/results.jsonl.
"""
import argparse
import json
import math
import multiprocessing as mp
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PRESET_IDS = ["house", "bridge", "gate", "tower", "skyline"]
REACH_RATES = [0.0, 0.03, 0.08]          # random reaches into the work area per second


def _gl_env(gl_dir):
    """Env for GPU rendering with user-space NVIDIA libs (no root)."""
    g = Path(gl_dir)
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = f"{g / 'lib'}:{env.get('LD_LIBRARY_PATH', '')}"
    env["__EGL_VENDOR_LIBRARY_FILENAMES"] = str(g / "egl_nvidia.json")
    env["VK_ICD_FILENAMES"] = str(g / "vk_nvidia_icd.json")
    env["MUJOCO_GL"] = "egl"
    return env


def _write(path, data, binary=False):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb" if binary else "w") as f:
        f.write(data)
    os.replace(tmp, path)


def _score(world, steps):
    """Worst placement error (cm) of the built blocks against the plan."""
    worst, used = 0.0, set()
    for s in steps:
        cands = [b for b in world.blocks if b.type == s["type"] and b.color == s["color"] and b.id not in used]
        if not cands:
            return 99.0
        b = min(cands, key=lambda q: math.hypot(q.x - s["x"], q.y - s["y"]))
        used.add(b.id)
        worst = max(worst, math.hypot(b.x - s["x"], b.y - s["y"]), abs(b.z - s["z"]))
    return worst


def worker(k, args, out):
    os.environ["MUJOCO_EGL_DEVICE_ID"] = str(k % max(1, args.gpus))
    os.environ["SIDEKICK_NO_DB"] = "1"
    import numpy as np
    import torch
    torch.set_num_threads(2)
    from . import body_model as bm
    from . import config as C
    from . import presets
    from .arm import make_arm
    from .builder import Builder
    from .catalog import Catalog
    from .twin import make_twin

    out = Path(out)
    seed = args.seed + k
    reach = REACH_RATES[k % len(REACH_RATES)]
    cfg = C.load(overrides={"use_sim": True})
    cat = Catalog.load()
    w = make_twin(cfg, cat, speed=args.babble_speed, seed=seed, reach_rate=0.0)
    arm = make_arm(cfg, world=w).connect()
    arm.start()
    st = {"k": k, "seed": seed, "reach_rate": reach, "phase": "babble", "episode": 0, "preset": None,
          "mode": "", "step": 0, "total": 0, "action": "", "results": [], "safety_stops": 0, "gpu": k % max(1, args.gpus)}
    stop_pub = threading.Event()

    def publish():
        while not stop_pub.is_set():
            st["sim_s"] = round(w.clock.time(), 1)
            st["toppled"] = len(w.toppled)
            st["contacts"] = w.contacts
            _write(out / f"{k}.json", json.dumps(st))
            if w.view_jpeg:
                _write(out / f"{k}.jpg", w.view_jpeg, binary=True)
            time.sleep(0.4)

    threading.Thread(target=publish, daemon=True).start()

    # 1. learn this arm's body through the camera, like the real arm does
    bpath = out / f"babble_{k}.jsonl"
    if args.fresh:
        bpath.unlink(missing_ok=True)         # otherwise resume: same seed, same arm, same samples
    t0 = time.time()
    bm.babble(arm, w, cfg, n=args.babble, out_path=bpath, rng=np.random.default_rng(seed))
    P, Y = bm.load_samples(bpath)
    body, held = bm.train(P, Y, cfg, log=None)
    st["body_cm"] = round(float(held), 2)
    st["babble_s"] = round(time.time() - t0)
    w.clock.set_speed(args.speed)
    w.person.reach_rate = reach

    # 2. build presets forever (or --episodes)
    ep = 0
    while args.episodes <= 0 or ep < args.episodes:
        pid = PRESET_IDS[(k + ep) % len(PRESET_IDS)]
        with w.lock:
            w.clear_blocks()
            w.toppled.clear()
            w.person.requests.clear()
        c0, s_virtual0, t_real0 = w.contacts, w.clock.time(), time.time()
        design = presets.get(pid)
        w.fill_supply(presets.needed(design)[:2])
        st.update(phase="build", episode=ep, preset=pid, safety_stops=0)
        b = Builder(cfg, cat, w, arm, body, feeder=w.person, log_dir=str(out / f"log_{k}"))
        started, probs, _ = b.start_build(design)
        was_safe = False
        while started and b.busy() and w.clock.time() - s_virtual0 < args.timeout:
            s = b.snapshot()
            if s.get("safety") and not was_safe:
                st["safety_stops"] += 1
            was_safe = bool(s.get("safety"))
            st.update(mode=s.get("mode"), step=s.get("step"), total=s.get("total"),
                      action=s.get("action"), safety=s.get("safety", False), prompt=s.get("prompt"))
            time.sleep(0.3)
        s = b.snapshot()
        result = s.get("result") if started else "not started: " + "; ".join(p["msg"] for p in probs)
        if started and b.busy():
            result = "timeout"
            b.stop_build()
        steps = list(b.plan_steps)
        b.close()
        time.sleep(0.5)                      # let the last block settle
        r = {"k": k, "episode": ep, "preset": pid, "result": result, "seed": seed, "reach_rate": reach,
             "worst_cm": round(_score(w, steps), 2) if started else None, "toppled": len(w.toppled),
             "contacts": w.contacts - c0, "safety_stops": st["safety_stops"],
             "virtual_s": round(w.clock.time() - s_virtual0, 1), "real_s": round(time.time() - t_real0, 1),
             "body_cm": st["body_cm"]}
        with open(out / "results.jsonl", "a") as f:
            f.write(json.dumps(r) + "\n")
        st["results"] = (st["results"] + [{"preset": pid, "result": result, "worst_cm": r["worst_cm"],
                                           "toppled": r["toppled"]}])[-6:]
        st["phase"] = "pause"
        time.sleep(1.0)
        ep += 1
    stop_pub.set()
    arm.close()
    w.stop()


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sidekick Fleet</title><style>
:root{--bg:#f4f3ef;--card:#fff;--ink:#1d1d1f;--mute:#6b6b70;--ok:#1f7a3a;--bad:#b3261e;--warn:#9a6700;--line:#e2e0da}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e22;--ink:#eee;--mute:#9a9aa2;--ok:#5cc47a;--bad:#ff6b5e;--warn:#e0b341;--line:#2c2c31}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.4 system-ui,sans-serif}
header{padding:14px 16px;display:flex;gap:18px;align-items:baseline;flex-wrap:wrap;border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0}.sum b{font-variant-numeric:tabular-nums}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;padding:12px 16px}
.c{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.c img{width:100%;aspect-ratio:16/10;display:block;background:#000}
.m{padding:8px 10px}.r1{display:flex;justify-content:space-between;gap:8px}.mute{color:var(--mute)}
.safe{color:var(--bad);font-weight:600}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.res{display:flex;gap:4px;flex-wrap:wrap;margin-top:4px}.res span{font-size:12px;border:1px solid var(--line);border-radius:4px;padding:0 4px}
</style></head><body><header><h1>Sidekick Fleet</h1><div class="sum" id="sum"></div></header><main id="g"></main>
<script>
const N=__N__;const g=document.getElementById('g');
for(let k=0;k<N;k++){g.insertAdjacentHTML('beforeend',`<div class="c"><img id="i${k}" alt="twin ${k}"><div class="m"><div class="r1"><b id="h${k}">Twin ${k}</b><span id="p${k}" class="mute"></span></div><div id="a${k}" class="mute"></div><div class="res" id="r${k}"></div></div></div>`)}
const cls=r=>r==='done'?'ok':(r||'').startsWith('timeout')||(r||'').startsWith('not')?'bad':'warn';
async function tick(){let done=0,total=0,stops=0,top=0;
 for(let k=0;k<N;k++){try{const s=await (await fetch(`${k}.json?`+Date.now())).json();
  document.getElementById('i'+k).src=`${k}.jpg?`+Date.now();
  document.getElementById('h'+k).textContent=`Twin ${k} · ${s.preset||'—'}`;
  document.getElementById('p'+k).innerHTML=`${s.phase} · ep ${s.episode} · reach ${s.reach_rate}/s · gpu ${s.gpu}`;
  document.getElementById('a'+k).innerHTML=(s.safety?'<span class="safe">SAFETY STOP · </span>':'')+(s.phase==='build'?`step ${s.step}/${s.total} · ${s.action||s.mode||''}`:(s.phase==='babble'?'learning its body through the camera…':''))+(s.body_cm!=null?` · body ${s.body_cm} cm`:'');
  document.getElementById('r'+k).innerHTML=(s.results||[]).map(r=>`<span class="${cls(r.result)}">${r.preset}: ${r.result}${r.worst_cm!=null?' '+(r.worst_cm*10).toFixed(0)+'mm':''}${r.toppled?' ⤵'+r.toppled:''}</span>`).join('');
  for(const r of s.results||[]){total++;if(r.result==='done')done++;if(r.toppled)top++}stops+=s.safety_stops||0;
 }catch(e){}}
 document.getElementById('sum').innerHTML=`builds (last 6 each): <b>${done}/${total}</b> done · <b>${top}</b> with toppled blocks · safety stops now: <b>${stops}</b>`;
}
setInterval(tick,700);tick();
</script></body></html>"""


def serve(out, n, port):
    out = Path(out)
    _write(out / "index.html", PAGE.replace("__N__", str(n)))

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(out), **kw)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sidekick.fleet", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", type=int, default=8, help="number of twins")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--out", default="sidekick_data/fleet")
    ap.add_argument("--speed", type=float, default=3.0, help="sim speed while building")
    ap.add_argument("--babble-speed", type=float, default=10.0)
    ap.add_argument("--babble", type=int, default=600, help="babble samples per twin")
    ap.add_argument("--episodes", type=int, default=0, help="builds per twin (0 = forever)")
    ap.add_argument("--timeout", type=float, default=900, help="sim seconds per build")
    ap.add_argument("--gpus", type=int, default=2)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--fresh", action="store_true", help="re-babble even if samples exist")
    ap.add_argument("--gl", default=os.environ.get("SIDEKICK_GL", ""),
                    help="folder with user-space NVIDIA GL libs (GPU rendering)")
    a = ap.parse_args(argv)
    if a.gl and "__EGL_VENDOR_LIBRARY_FILENAMES" not in os.environ:
        os.execve(sys.executable, [sys.executable, "-m", "sidekick.fleet"] + (argv or sys.argv[1:]), _gl_env(a.gl))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").touch()
    serve(out, a.n, a.port)
    print(f"Fleet of {a.n} twins. Watch: http://127.0.0.1:{a.port}/   results: {out / 'results.jsonl'}", flush=True)
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=worker, args=(k, a, str(out)), daemon=True) for k in range(a.n)]
    for p in procs:
        p.start()
    try:
        while any(p.is_alive() for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()

"""Rank the settings tried by a fleet parameter search by mean round loss.
    python scripts/rank_params.py sidekick_data/fleet/results.jsonl [params.json]
"""
import collections
import json
import sys

rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
names = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else None
by = collections.defaultdict(list)
for r in rows:
    if r.get("loss") is not None:
        by[r.get("param_id")].append(r)
print(f"{'set':>3}  {'rounds':>6}  {'loss':>6}  {'done':>5}  {'place':>6}  {'miss':>5}  {'contact':>7}  {'stops':>5}  {'sim s':>6}  settings")
out = []
for pid, rs in by.items():
    n = len(rs)
    mean = lambda k: sum(r["loss_parts"][k] for r in rs) / n
    out.append((sum(r["loss"] for r in rs) / n, pid, n, sum(r["result"] == "done" for r in rs) / n,
                mean("placement"), mean("missing"), sum(r.get("contacts", 0) for r in rs) / n,
                sum(r.get("safety_stops", 0) for r in rs) / n, sum(r.get("virtual_s", 0) for r in rs) / n,
                rs[0].get("params")))
for loss, pid, n, done, pl, mi, co, st, t, p in sorted(out, key=lambda x: x[0]):
    print(f"{str(pid):>3}  {n:>6}  {loss:6.2f}  {done:5.0%}  {pl:6.2f}  {mi:5.2f}  {co:7.2f}  {st:5.1f}  {t:6.0f}  {json.dumps(p)}")

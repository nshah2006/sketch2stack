"""Block counts from the team's Supabase table (public.block_inventory), read-only.

Uses the publishable (anon) key with a select-only policy, so it cannot write. Any problem
(no .env values, offline, paused project, bad rows) returns None and the caller keeps the
counts from sidekick_data/blocks.json or catalog.py. Only counts come from here; sizes stay
in the catalog. SIDEKICK_NO_DB=1 turns it off (selftest).
"""
import json
import os
import urllib.request

from . import envfile

TABLE = "block_inventory"
_cache = {}


def fetch_counts():
    """-> {type_id: {color: quantity>0}} or None. Cached for the life of the process."""
    if "v" in _cache:
        return _cache["v"]
    _cache["v"] = _fetch()
    return _cache["v"]


def _fetch():
    envfile.load_env()
    if os.environ.get("SIDEKICK_NO_DB"):
        return None
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "").strip().strip("<>")
    if not url or not key or "your-" in key:
        return None
    req = urllib.request.Request(f"{url}/rest/v1/{TABLE}?select=type_id,color,quantity",
                                 headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=4) as r:
            rows = json.loads(r.read())
    except Exception as e:                      # offline, paused project, bad key: say so, never crash
        print(f"inventory: database unavailable ({type(e).__name__}); using the local catalog", flush=True)
        return None
    out = {}
    for row in rows:
        tid, color = (row.get("type_id") or "").strip(), (row.get("color") or "").strip().lower()
        try:
            qty = int(row.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        if tid and color and qty > 0:
            out.setdefault(tid, {})[color] = qty
    if not out:
        print("inventory: database returned no usable rows; using the local catalog", flush=True)
        return None
    print(f"inventory: loaded {sum(map(len, out.values()))} color counts from the database", flush=True)
    return out

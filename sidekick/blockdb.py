"""Read the block inventory table from Supabase (see DATABASE.md).

The arm never depends on this: catalog.py / sidekick_data/blocks.json stay the
source of truth for a run. This is for checking access and for comparing what
the team owns against what the catalog claims.

    python -m sidekick db-check
"""
import json
import urllib.error
import urllib.request

from . import envfile

TABLE = "block_inventory"
COLUMNS = "type_id,shape,color,quantity,width_cm,depth_cm,height_cm"
TIMEOUT = 15


class DbError(Exception):
    """Something went wrong talking to Supabase; the message is for the user."""


def fetch_rows(limit=1000):
    """-> list of inventory rows. Raises DbError with a readable reason."""
    conf = envfile.supabase()
    if conf is None:
        raise DbError("SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY are not filled in (.env)")
    url, key = conf
    req = urllib.request.Request(
        f"{url}/rest/v1/{TABLE}?select={COLUMNS}&limit={limit}",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        if e.code in (401, 403):
            raise DbError(f"{e.code}: the key was rejected. Check SUPABASE_PUBLISHABLE_KEY. {body}")
        if e.code == 404:
            raise DbError(f"404: no table {TABLE} at that URL. Check SUPABASE_URL. {body}")
        raise DbError(f"HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise DbError(f"could not reach {url}: {e.reason}")
    except json.JSONDecodeError:
        raise DbError("the response was not JSON; check SUPABASE_URL points at the project root")


def filled(rows):
    """Only the rows someone actually filled in (the table keeps spare blanks)."""
    return [r for r in rows if r.get("type_id")]


def totals(rows):
    """-> {type_id: {color: quantity}} from the database rows."""
    out = {}
    for r in filled(rows):
        q = int(r.get("quantity") or 0)
        if q:
            out.setdefault(r["type_id"], {})[r.get("color") or "?"] = q
    return out


def compare(rows, catalog):
    """Database vs the catalog the arm will actually use.
    -> list of (type_id, db_count, catalog_count, note)."""
    db = totals(rows)
    out = []
    for tid in sorted(set(db) | set(catalog.types)):
        d = sum(db.get(tid, {}).values())
        c = catalog.count(tid) if tid in catalog.types else 0
        if tid not in catalog.types:
            note = "in the database but not in catalog.py"
        elif tid not in db:
            note = "in catalog.py but not in the database"
        else:
            note = "" if d == c else "counts differ"
        out.append((tid, d, c, note))
    return out

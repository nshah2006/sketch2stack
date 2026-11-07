"""Tiny .env loader (no dependency). Real environment variables win over the file."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_done = False


def load_env():
    global _done
    if _done:
        return
    _done = True
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip("'\"")
        if k.strip() and v:
            os.environ.setdefault(k.strip(), v)


def api_key():
    """The OpenAI key, or None if missing or still the placeholder."""
    load_env()
    if os.environ.get("SIDEKICK_NO_LLM"):       # selftest: keep it offline and repeatable
        return None
    k = os.environ.get("OPENAI_API_KEY", "").strip()
    return None if not k or "your-openai" in k else k


def supabase():
    """(url, publishable key) for the block inventory, or None if not filled in.
    The placeholders in .env.example count as missing."""
    load_env()
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not key or "your-project-ref" in url or "your-supabase" in key:
        return None
    return url, key

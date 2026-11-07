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

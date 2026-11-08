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


PROVIDERS = {   # name -> (default base url, key var, model var, default model, placeholder marker)
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "OPENAI_MODEL",
               "gpt-4o-mini", "your-openai"),
    # NVIDIA serves an OpenAI-compatible /chat/completions, so only the url, key and model change.
    # The model id below is a guess: set NVIDIA_MODEL to whatever build.nvidia.com lists for your key.
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", "NVIDIA_MODEL",
               "nvidia/nemotron-3-super-120b-a12b", "your-nvidia"),
}


def llm_config():
    """(base url, key, model, provider name) for the chat LLM, or None if unconfigured.
    LLM_PROVIDER picks the provider; it defaults to openai so an existing .env keeps working.
    None means the caller falls back to the offline rule parser, same as a missing key."""
    load_env()
    if os.environ.get("SIDEKICK_NO_LLM"):       # selftest: keep it offline and repeatable
        return None
    name = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if name not in PROVIDERS:                   # unset or a typo: stay on the provider that worked before
        name = "openai"
    base_default, key_var, model_var, model_default, placeholder = PROVIDERS[name]
    k = os.environ.get(key_var, "").strip()
    if not k or placeholder in k:
        return None
    base = (os.environ.get("LLM_BASE_URL", "").strip() or base_default).rstrip("/")
    model = os.environ.get(model_var, "").strip() or model_default
    return base, k, model, name


def supabase():
    """(url, publishable key) for the block inventory, or None if not filled in.
    The placeholders in .env.example count as missing."""
    load_env()
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url or not key or "your-project-ref" in url or "your-supabase" in key:
        return None
    return url, key

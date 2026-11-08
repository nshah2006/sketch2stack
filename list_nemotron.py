"""List the models your NVIDIA key can reach.  ./venv/bin/python list_nemotron.py"""
import json, urllib.request, urllib.error
from sidekick import envfile

envfile.load_env()
import os
key = os.environ.get("NVIDIA_API_KEY", "").strip()
if not key or key.startswith("paste-"):
    raise SystemExit("Put NVIDIA_API_KEY in .env first (it starts with nvapi-).")

req = urllib.request.Request("https://integrate.api.nvidia.com/v1/models",
                             headers={"Authorization": f"Bearer {key}"})
try:
    data = json.load(urllib.request.urlopen(req, timeout=20))
except urllib.error.HTTPError as e:
    raise SystemExit(f"{e.code}: {e.read().decode('utf-8','replace')[:300]}")

ids = sorted(m.get("id", "") for m in data.get("data", []))
hits = [i for i in ids if "nemotron" in i.lower()]
print(f"{len(ids)} models reachable with this key\n")
print("NEMOTRON MODELS -- copy one into NVIDIA_MODEL in .env:")
for i in hits or ["  (none found - see the full list below)"]:
    print("   ", i)
if not hits:
    print("\nall models:")
    for i in ids:
        print("   ", i)

"""frames/*.jpg -> demo.mp4 (H.264, plays in any browser). Run with the LeRobot venv (has PyAV).
    /mnt/Data/Tushaar/lerobot_venv/bin/python scripts/encode_demo.py sidekick_data/demo [--fps 16]
"""
import argparse
from pathlib import Path

import av
import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("dir")
ap.add_argument("--fps", type=int, default=16, help="playback fps (frames were taken at 8 per sim second)")
ap.add_argument("--crf", default="28")
a = ap.parse_args()
d = Path(a.dir)
frames = sorted((d / "frames").glob("*.jpg"))
first = Image.open(frames[0])
out = av.open(str(d / "demo.mp4"), "w")
s = out.add_stream("libx264", rate=a.fps)
s.width, s.height = first.width - first.width % 2, first.height - first.height % 2
s.pix_fmt = "yuv420p"
s.options = {"crf": a.crf, "preset": "medium", "movflags": "+faststart"}
for f in frames:
    img = np.asarray(Image.open(f).convert("RGB"))[: s.height, : s.width]
    for p in s.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
        out.mux(p)
for p in s.encode():
    out.mux(p)
out.close()
print(d / "demo.mp4", round((d / "demo.mp4").stat().st_size / 1e6, 2), "MB", len(frames), "frames")

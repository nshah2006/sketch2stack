"""Recorded twin builds (sidekick_data/fleet/episodes/*.npz) -> a LeRobot dataset.

Runs in the LeRobot venv, not the sidekick one:
    /mnt/Data/Tushaar/lerobot_venv/bin/python scripts/twin_to_lerobot.py \
        --src sidekick_data/fleet --out sidekick_data/lerobot/sidekick_twin

Keeps finished builds only ("done"), and trims long idle stretches (arm
holding still while it waits for the person or a safety stop): a policy
learns nothing from them except to stand still.
"""
import argparse
import json
import shutil
from pathlib import Path

import cv2
import numpy as np

JOINTS = ["base", "shoulder", "elbow", "wrist_pitch", "wrist_roll", "gripper"]


def keep_mask(state, action, hz, max_idle_s=1.0):
    still = np.all(np.abs(action - state) < 1.0, axis=1) & np.r_[True, np.all(np.abs(np.diff(state, axis=0)) < 1.0, axis=1)]
    keep, run = np.ones(len(state), bool), 0
    for i, s in enumerate(still):
        run = run + 1 if s else 0
        keep[i] = run <= max_idle_s * hz
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="sidekick_data/fleet")
    ap.add_argument("--out", default="sidekick_data/lerobot/sidekick_twin")
    ap.add_argument("--repo-id", default="local/sidekick_twin")
    ap.add_argument("--all", action="store_true", help="include unfinished builds too")
    a = ap.parse_args()
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    files = sorted(Path(a.src, "episodes").glob("*.npz"))
    eps = []
    for f in files:
        z = np.load(f, allow_pickle=True)
        meta = json.loads(str(z["meta"]))
        if a.all or meta.get("result") == "done":
            eps.append((f, z, meta))
    if not eps:
        raise SystemExit(f"no usable episodes in {a.src}/episodes")
    hz = int(round(eps[0][2]["hz"]))
    h, w = cv2.imdecode(np.frombuffer(eps[0][1]["frames"][0], np.uint8), cv2.IMREAD_COLOR).shape[:2]
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    features = {
        "observation.images.top": {"dtype": "video", "shape": (h, w, 3), "names": ["height", "width", "channels"]},
        "observation.state": {"dtype": "float32", "shape": (6,), "names": JOINTS},
        "action": {"dtype": "float32", "shape": (6,), "names": JOINTS},
    }
    ds = LeRobotDataset.create(repo_id=a.repo_id, fps=hz, features=features, root=out,
                               robot_type="sidekick_6dof", use_videos=True)
    total = 0
    for f, z, meta in eps:
        state, action = z["state"], z["action"]
        keep = keep_mask(state, action, hz)
        for i in np.flatnonzero(keep):
            img = cv2.cvtColor(cv2.imdecode(np.frombuffer(z["frames"][i], np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
            ds.add_frame({"observation.images.top": img, "observation.state": state[i],
                          "action": action[i], "task": meta.get("task", "build")})
        ds.save_episode()
        total += int(keep.sum())
        print(f"{f.name}: {keep.sum()}/{len(keep)} frames kept", flush=True)
    ds.finalize()
    print(f"dataset: {out}  episodes {len(eps)}  frames {total}  fps {hz}")


if __name__ == "__main__":
    main()

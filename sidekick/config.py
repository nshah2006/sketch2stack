"""Settings (handbook 2C). load() fills any missing key from DEFAULTS.

All positions are centimeters in the table frame: origin at the front-left
corner of the work area (human side), x right, y away from the human, z up.
All joint values are pulse widths in microseconds.

LAYOUT NOTE: the handbook layout (base at (25, 45), blocks anywhere in
50 x 35, bins at x 0-8 / 42-50, handover at (25, 10) 15 cm up) is out of reach
for 10 cm + 10 cm links with the claw pointing down (reach is about 15 cm from
the base). The defaults below keep the same table frame, markers and
interfaces but move the base and zones so everything is reachable. Change
`layout` after measuring the real arm; `python -m sidekick.main reach` prints
what the body model can actually reach.
"""
import copy
import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("SIDEKICK_DATA", "sidekick_data"))

DEFAULTS = {
    # --- switches ---
    "use_sim": True,               # flip to false at the hackathon
    "sim_speed": 1.0,              # simulator time multiplier (1 = real time)
    "sim_seed": None,              # None = new random arm errors each start

    # --- hardware ---
    "serial_port": "auto",
    "baud": 115200,
    "camera_index": 0,
    "camera_width": 1280,
    "camera_height": 720,
    "camera_fps": 60,

    # --- joints (us) ---
    "hard_min": 600,
    "hard_max": 2400,
    # measure with `jog` before babbling! (Phase 5). The simulator arm was
    # tested with these; the handbook's safer 900/2100 can't reach the table.
    "joint_min": [700, 700, 700, 700, 700, 700],
    "joint_max": [2300, 2300, 2300, 2300, 2300, 2300],
    "home": [1500, 1500, 1500, 1500, 1500, 1500],     # straight up, claw half open
    "park": [1500, 1500, 1500, 1500, 1500, 1300],     # measure: folded, low effort
    # ready: claw pointing down above the middle of the work area, marker visible.
    # Babbling starts here and returns here (home has the marker facing away
    # from the camera, so babbling can't start from home). Measure with jog.
    "ready": [1500, 1685, 2056, 2093, 1500, 1300],
    "claw_open": 1300,                                 # measure
    "claw_closed": 1800,                               # measure
    "step_us": 8,                                      # per 20 ms tick
    "us_per_degree": 7.4,

    # --- sizes (measure the printouts / blocks) ---
    "table_marker_size": 5.0,
    "claw_marker_size": 3.0,
    "marker_to_fingertip": 9.0,
    "hover_extra": 6.0,
    "hand_height": 5.0,
    "chessboard_inner": [9, 6],
    "chessboard_square": 2.5,

    # Short acknowledgements (nod, refuse, look up) at the few moments the arm
    # is dealing with a person. Off makes every build a little quicker.
    "gestures": True,

    # --- safety ---
    "stop_distance": 10.0,
    "stop_claw_height": 25.0,
    "resume_after": 1.0,
    "claw_unseen_stop": 1.0,

    # --- babbling ---
    "babble_samples": 800,
    "babble_step": 120,
    "babble_settle": 0.6,
    "babble_min_height": 1.5,      # fingertip height; below this babbling pulls back

    # --- optional parts ---
    "force_sensors": False,
    "force_grip_threshold": 150,
    "battery_monitor": False,
    "battery_warn": 6.8,
    "battery_stop": 6.4,
    "leds": False,
    "voice": False,
    "roll_alignment": False,
    "roll_direction": 1,

    # --- table layout (see LAYOUT NOTE) ---
    # With the claw pointing down, this arm reaches a ring about 9-17 cm from
    # its base (less when higher up). The build strip and both supply zones sit
    # on that ring. After training the real body model, run
    # `python -m sidekick.main reach` and move these to fit the real arm.
    "layout": {
        "work_area": [50.0, 35.0],
        "markers": {"0": [0, 0], "1": [50, 0], "2": [50, 35], "3": [0, 35]},
        "claw_marker_id": 10,
        "base": [25.0, 36.0],
        # build strip: x0, x1, y_front, y_back (front = human side)
        # 4 cm deep on purpose. A deeper strip would let a plank or arch be turned
        # a quarter (rot 90 needs 6-7 cm), but it can only grow forwards: behind is
        # the supply zone and under the 9 cm inner reach limit. Pushing the front
        # edge to y=19 moved every depth-0 block from 11.5 cm to 15.5 cm from the
        # base, at the ragged outer edge of the arm's ring, and the simulated House
        # build went from 3 mm to 30 mm worst placement. Not worth it.
        "build_area": [15.0, 35.0, 23.0, 27.0],
        # supply zones: x0, x1, y0, y1 (loose blocks are put here)
        "supply": {"left": [7.0, 15.0, 28.0, 34.0], "right": [35.0, 43.0, 28.0, 34.0]},
        # pickup spot (center of a taped square): with use_color off, the arm asks
        # for each block here and trusts that it's the shape it asked for
        "pickup": [11.0, 31.0],
    },
    "max_build_height": 12.0,      # cm; taller stacks are out of reach
    "depth_slot": 3.0,             # cm per front-to-back slot in the build strip
    "place_clearance": 3.0,        # hover this far above a placement / pick

    # --- vision ---
    # use_color false: blocks are found as "anything not white" and the arm asks
    # for each block on the pickup spot. true: blocks are told apart by color +
    # outline anywhere in the supply zones (needs distinct colors per shape).
    "use_color": False,
    "fg_min_saturation": 45,
    "colors": {
        "red": [[[0, 120, 70], [8, 255, 255]], [[170, 120, 70], [179, 255, 255]]],
        "blue": [[[95, 100, 60], [114, 255, 255]]],
        "purple": [[[116, 45, 60], [135, 255, 255]]],
        "green": [[[40, 80, 60], [85, 255, 255]]],
        "yellow": [[[20, 110, 110], [35, 255, 255]]],
        "orange": [[[9, 130, 120], [19, 255, 255]]],
    },
    "block_area_min": 300,
    "block_area_max": 20000,
    "claw_blank_px": 80,

    # --- simulator geometry (replace with the real measurements, Phase 3) ---
    "sim_arm": {
        "shoulder_height": 8.0,
        "upper": 10.0,
        "fore": 10.0,
        "marker_past_wrist": 3.0,
        "finger_past_wrist": 12.0,
    },
}

PATHS = {
    "config": "config.json",
    "calibration": "calibration.json",
    "hand_model": "hand_landmarker.task",
    "babble": "babble/samples.jsonl",
    "babble_sim": "babble/samples_sim.jsonl",
    "body": "models/body.pt",
    "body_sim": "models/body_sim.pt",
    "sessions": "sessions",
    "events": "events.json",
    "task": "models/task.json",
    "intent": "models/intent.pt",
    "logs": "logs",
    "markers": "markers",
    "lens_images": "lens_images",
}


def path(key, data_dir=None):
    p = Path(data_dir or DATA_DIR) / PATHS[key]
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def body_path(cfg, data_dir=None):
    """The simulator and the real arm each get their own body model."""
    return path("body_sim" if cfg["use_sim"] else "body", data_dir)


def babble_path(cfg, data_dir=None):
    return path("babble_sim" if cfg["use_sim"] else "babble", data_dir)


def _merge(defaults, loaded):
    out = copy.deepcopy(defaults)
    for k, v in loaded.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config(dict):
    """A dict with attribute access and a save() method."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def save(self, data_dir=None):
        save(self, data_dir)

    # convenience
    def in_zone(self, x, y, rect, margin=0.0):
        x0, x1, y0, y1 = rect
        return x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin

    def in_supply(self, x, y):
        for name, rect in self["layout"]["supply"].items():
            if self.in_zone(x, y, rect):
                return name
        return None

    def in_build(self, x, y, margin=0.0):
        return self.in_zone(x, y, self["layout"]["build_area"], margin)

    def in_work_area(self, x, y):
        w, h = self["layout"]["work_area"]
        return 0 <= x <= w and 0 <= y <= h

    def grasp_z(self, bottom, height):
        """Fingertip height for gripping a block at its mid-height."""
        return bottom + height / 2

    def hover_z(self, bottom, height):
        return self.grasp_z(bottom, height) + self["place_clearance"]


def load(data_dir=None, overrides=None):
    p = Path(data_dir or DATA_DIR) / PATHS["config"]
    loaded = {}
    if p.exists():
        with open(p) as f:
            loaded = json.load(f)
    cfg = Config(_merge(DEFAULTS, loaded))
    for k, v in (overrides or {}).items():
        cfg[k] = v
    return cfg


def save(cfg, data_dir=None):
    p = path("config", data_dir)
    with open(p, "w") as f:
        json.dump(dict(cfg), f, indent=2)
    return p

"""Preset builds for the demo: 2-4 blocks each, sized for the build strip.

x is the block's left edge in cm from the left end of the build strip;
z_hint only orders the gravity settling (heights are computed).
`python -m sidekick.main presets` checks each one against the current
config, catalog and body model.
"""

PRESETS = [
    {"id": "stack", "name": "Stack", "desc": "One cube on top of another.",
     "blocks": [
         {"type": "cube", "color": "red", "x": 6.5, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "cube", "color": "red", "x": 6.5, "depth": 0, "rot": 0, "z_hint": 3},
     ]},
    {"id": "pyramid", "name": "Pyramid", "desc": "Two cubes with a third across them.",
     "blocks": [
         {"type": "cube", "color": "red", "x": 5.0, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "cube", "color": "red", "x": 8.0, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "cube", "color": "red", "x": 6.5, "depth": 0, "rot": 0, "z_hint": 3},
     ]},
    {"id": "house", "name": "House", "desc": "Two cubes with a roof on top.",
     "blocks": [
         {"type": "cube", "color": "red", "x": 5.0, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "cube", "color": "red", "x": 8.0, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "roof", "color": "yellow", "x": 5.0, "depth": 0, "rot": 0, "z_hint": 3},
     ]},
    {"id": "bridge", "name": "Bridge", "desc": "A long bar across two pillars.",
     "blocks": [
         {"type": "cyl_short", "color": "blue", "x": 3.5, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "cyl_short", "color": "blue", "x": 9.5, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "bar", "color": "green", "x": 3.5, "depth": 0, "rot": 0, "z_hint": 3},
     ]},
    {"id": "gate", "name": "Gate", "desc": "An arch with a roof, between two posts.",
     "blocks": [
         {"type": "cyl_short", "color": "blue", "x": 1.0, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "arch", "color": "green", "x": 5.0, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "cyl_short", "color": "blue", "x": 12.0, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "roof", "color": "yellow", "x": 5.0, "depth": 0, "rot": 0, "z_hint": 3},
     ]},
    {"id": "tower", "name": "Tower", "desc": "A plank, a cube and a cylinder stacked up.",
     "blocks": [
         {"type": "plank", "color": "red", "x": 6.5, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "cube", "color": "red", "x": 8.5, "depth": 0, "rot": 0, "z_hint": 1.4},
         {"type": "cyl_short", "color": "blue", "x": 8.5, "depth": 0, "rot": 0, "z_hint": 4.4},
     ]},
    {"id": "skyline", "name": "Skyline", "desc": "Four shapes side by side, short to tall.",
     "blocks": [
         {"type": "cyl_short", "color": "blue", "x": 1.0, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "cube", "color": "red", "x": 4.5, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "pillar", "color": "orange", "x": 8.0, "depth": 0, "rot": 0, "z_hint": 0},
         {"type": "cyl_tall", "color": "red", "x": 11.5, "depth": 0, "rot": 0, "z_hint": 0},
     ]},
]


def get(pid):
    for p in PRESETS:
        if p["id"] == pid:
            return p
    raise KeyError(f"no preset {pid!r}; choose from {[p['id'] for p in PRESETS]}")


def needed(design):
    """[(type, color)] for every block in a design."""
    return [(b["type"], b["color"]) for b in design["blocks"]]

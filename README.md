# Sidekick Builder (HackUTD)

Pick a preset (or draw a build from the front in the browser) and a 6-joint arm builds it out of real wooden blocks. Blocks drop by gravity in the designer, so the planner works out every block's height, order and grip; the overhead camera finds loose blocks by color and outline, and the arm freezes whenever a hand comes near the claw.

Everything runs in a **simulator first**. At the hackathon the same code switches to the real arm by setting `use_sim` to `false`.

## Quick start (simulator, no hardware)

```bash
brew install python@3.11            # Mac; Windows: python.org 3.11
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m sidekick setup            # data folder, checks, hand model download
python -m sidekick selftest         # 7 checks, about 2 minutes
python -m sidekick ui --sim --speed 3
```
Open http://localhost:8000, pick **House**, click **Put blocks in supply**, then **Build this**. **Sim: reach in** sends a simulated hand in to show the safety freeze.

If `setup` says OpenCV has no ArUco: `pip uninstall -y opencv-python opencv-contrib-python && pip install "opencv-contrib-python<4.11"`.

## Tomorrow: switching to the real arm

Do these in order. Each one writes to `sidekick_data/`, so any step can be redone alone. Add `--real` to every command (or set `"use_sim": false` in `sidekick_data/config.json`).

| # | Step | Command | Done when |
|---|------|---------|-----------|
| 1 | Flash `firmware/sidekick_firmware/sidekick_firmware.ino` (Arduino IDE, board Arduino Uno). Serial Monitor at 115200, send `?` | | Replies `OK sidekick 1`; close the monitor |
| 2 | Wire: battery + to servo bus +, battery − to bus − **and Uno GND**. Signals: base 3, shoulder 5, elbow 6, wrist pitch 9, wrist roll 10, gripper 11. E-stop button pin 12 to GND. Never battery to Uno 5V/VIN | | Multimeter: 7.4–8.4 V on the bus |
| 3 | Center every servo at 1500 µs before fitting horns, build the arm, clamp the base | `python -m sidekick jog --real` | Each joint swings freely |
| 4 | Find limits and poses with one hand on the battery switch: `min <j>` / `max <j>` at each end stop, then `save home`, `save park` (folded, low effort), `save ready` (**claw pointing straight down over the middle of the board, marker visible**), `save open`, `save closed` | `jog --real` | `config.json` has limits and poses |
| 5 | Print markers at 100%, measure them, glue the claw marker on the gripper's back plate | `python -m sidekick markers` | Sizes in config match the ruler |
| 6 | Camera 60 cm up looking straight down. Lens (15+ chessboard views), then table | `calib-lens --real`, `calib-table --real` | Lens error < 0.5 px, table < 1.5 px, height ≈ 60 cm, ruler check within 5 mm |
| 7 | Tune colors under the venue light | `tune-colors --real` | Every block color shows cleanly |
| 8 | Babble (15–20 min, watch it), then train | `babble --real`, `train-body --real` | Held-out error < 1 cm |
| 9 | See what the real arm reaches; move `layout.build_area` / `layout.supply` in `config.json` onto it | `reach --real` | No lowercase `b`/`s` in the map |
| 10 | Accuracy and pick tests | `goto-test --real`, `pick-test --real -n 10` | < 5 mm; 8 of 10 picks |
| 11 | Check the presets against the real arm | `presets --real` | All say `OK` |
| 12 | Demo | `ui --real` | 4 of the last 5 rehearsals succeed |

## The blocks (`sidekick_data/blocks.json`)

Wooden blocks, no studs. Sizes are width × depth × height in cm, as the block stands.

| id | shape | size | can hold blocks on top |
|----|-------|------|-----|
| cube | box | 3 × 3 × 3 | yes |
| pillar | box | 3 × 3 × 6 | yes |
| plank | box | 7 × 3 × 1.4 | yes |
| bar | box | 10 × 3 × 1.4 | yes |
| cyl_short | cylinder | Ø3 × 3 | yes |
| cyl_tall | cylinder | Ø3 × 6 | yes |
| arch | arch | 6 × 3 × 3 | yes |
| roof | roof | 6 × 3 × 3 | no |

**Update the colors and counts** to what you own. The overhead camera sees footprints, not heights: two types with the same footprint, outline and color can't be told apart (`setup` lists any such pairs). Give them different colors. Put colored tape on the natural-wood pillar (beige on white is hard to see).

## How it works

```
designer (front view, gravity)  ->  planner  ->  builder  ->  arm
                                       |            ^
camera -> markers -> claw pose         |            |
       -> blocks (color+outline) -> tracker --------+
       -> hands (MediaPipe) -> safety stop ---------+
```

* **Planner** (`planner.py`): settles blocks by gravity, checks support (nothing on a roof, center over its supports), strip bounds, height, inventory, and reach (through the body model). Orders placements bottom-up, back slot first, left to right, and picks which way the fingers close so they don't hit a neighbour.
* **Depth**: a front view can't show depth, so every block defaults to the front slot (a wall). "Push back" moves a block one slot back; the top view shows it.
* **Body model** (`body_model.py`): babbling + a small neural net (pulses → claw x, y, z, down-ness) + gradient search for any target, with up to 3 camera corrections per move.
* **Builder** (`builder.py`): finds a matching loose block in a supply zone (or asks the user to put one there, with the arm parked), picks it, turns the wrist, places it, checks it with the camera. Safety stop on every frame; the current move resumes 1 s after the area is clear.

## Commands

`python -m sidekick <command> [--sim|--real] [--speed N] [-n N]`

`setup` `markers` `check` `jog` `calib-lens` `calib-table` `tune-colors` `view` `babble` `train-body` `reach` `goto-test` `pick-test` `presets` `build <preset|design.json>` `ui` `selftest [--quick]` `simtest -n 3`

## Serial protocol (laptop ↔ Uno, 115200, one line each)

| Send | Meaning |
|---|---|
| `?` | Uno replies `OK sidekick 1` |
| `P a b c d e f` | Starting pose (µs), only for joints not attached yet |
| `A` | Attach servos one at a time, 400 ms apart |
| `D` | Detach all (arm goes limp) |
| `J a b c d e f` | Targets for all 6 joints, clamped to limits |
| `S` | Freeze |
| `C i min max` | Limits for joint i (never wider than 600–2400) |
| `V n` | Step size 1–30 µs per 20 ms tick |
| `L n` | LEDs 0 off, 1 green, 2 yellow, 3 blue, 4 red |
| `H` | Heartbeat (every 0.3 s) |

The Uno sends `F a0 a1 a2 moving attached` every 40 ms. No line for 1 s freezes the arm.

## Changes from the Sidekick handbook

* **Task**: builds user-designed structures instead of sorting; the intent and task models are dropped. Hand safety stays.
* **Layout**: the handbook layout is out of reach for 10 + 10 cm links with the claw down (reach is about 9–17 cm from the base). The table frame, markers and interfaces are unchanged; the build strip and supply zones sit where the arm reaches (`reach` prints the real map).
* **`ready` pose**: babbling starts from a claw-down pose, because at `home` the marker faces away from the camera.
* **Joint limits default to 700–2300 µs** (the handbook's 900–2100 can't reach the table). Measure the real ones with `jog` before babbling.
* **Separate body models** for the simulator (`body_sim.pt`) and the real arm (`body.pt`).

## Layout

```
firmware/sidekick_firmware/   Uno sketch
sidekick/                     Python package (config, arm, sim, camera, calibration, perception,
                              body_model, motion, planner, catalog, presets, builder, overlay,
                              server + ui/index.html, selftest, main)
legacy/                       first teach-by-showing prototype
```

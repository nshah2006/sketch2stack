# CLAUDE.md

Sidekick Builder (HackUTD). The user picks a preset or draws a build from the front in the browser; a 6-joint arm builds it from real wooden blocks. Hackathon deadline: ~3-4 days from 2026-11-06. Favor working over elegant.

The first prototype (teach-by-showing: hand demo -> replay) lives in `legacy/` and is no longer the plan.

## Pipeline
0. Main UI: `frontend/` (React + three.js): sketch -> `POST /api/generate` (`sidekick/webapi.py`) -> choose -> `POST /api/build` -> live status by `run_id`. Classic UI stays at `/classic`.
   The sketch board has two modes (`BoardModeToggle`): **Draw** (freehand, the tiler guesses the blocks) and **Blocks** (`components/blocks/BlockEditor.tsx`, drag real catalog blocks onto the strip). Blocks mode skips the tiler entirely, so the layout is exact; it posts to `/api/check` on every edit for gravity heights, stability and problems, then hands the build straight to the Choose screen.
1. Design: `sidekick/ui/index.html` front-view editor. Blocks drop by gravity; "push back" sets the depth slot. Or one of the presets in `sidekick/presets.py`. The 3D app's sketch board is the build strip 1:1 (true size), so the size drawn is the size built; `"fit": true` on `/api/generate` scales the drawing up to fill the strip instead.
2. Plan: `planner.py` settles heights, checks support/roof/bounds/inventory/reach, orders bottom-up, back first, left to right, and picks the finger direction.
3. Build: `builder.py` finds a matching loose block in a supply zone (or asks the user for one), `motion.py` picks it, turns the wrist, places it; the camera checks it.
4. Safety: every camera frame, a hand within 10 cm of the low claw stops the arm; it resumes 1 s after the area is clear.

## Digital twin, fleet, training (GPU server)
- `sidekick/twin.py`: MuJoCo twin. Same wiring as `sim.py`, but blocks are rigid bodies and the camera is a rendered overhead image run through the real `perception.py` (ArUco calibration, claw marker, outlines). Hand position still comes from the person model.
- `python -m sidekick.fleet -n 12 --record --gl /mnt/Data/Tushaar/nvidia_userspace`: N twins (own flawed arm, own person, own babbled body), building presets in a loop. Live grid at http://127.0.0.1:8765, results in `sidekick_data/fleet/results.jsonl`, demos in `sidekick_data/fleet/episodes/`.
- GPU server has a compute-only NVIDIA driver: GL/Vulkan libs live in `/mnt/Data/Tushaar/nvidia_userspace` (`source env.sh`). Isaac Lab 3.0 container: `/mnt/Data/Tushaar/containers/isaac-lab_3.0.0.sif`.
- Training (LeRobot venv `/mnt/Data/Tushaar/lerobot_venv`): `scripts/twin_to_lerobot.py` (episodes -> LeRobot dataset), then `scripts/train_policy.sh act|smolvla|groot`.

## Layout
- `firmware/sidekick_firmware/sidekick_firmware.ino`: Uno servo driver. Microseconds only; limits, smoothing, watchdog, E-stop. No calibration or kinematics here.
- `sidekick/`: Python package, run as `python -m sidekick <command>` from the repo root.
  - `config.py` all settings (defaults + `sidekick_data/config.json`); `catalog.py` block types (`sidekick_data/blocks.json`).
  - `arm.py` serial driver; `sim.py` simulator (firmware emulator, flawed arm model, blocks, person, state camera).
  - `camera.py`, `calibration.py` (ArUco, lens, table pose, pixel <-> table, claw pose), `perception.py` (blocks, tracker, MediaPipe hands).
  - `body_model.py` babbling + neural net + solver; `motion.py`; `planner.py`; `builder.py`; `overlay.py`; `server.py`; `selftest.py`; `main.py`.

## Hardware
- Arduino Uno R3, 6DOF aluminum arm kit, Inland iC840 webcam 60 cm overhead, white poster board with ArUco markers 0-3 at the corners, marker 10 on the gripper's back plate.
- Joints 0-5: base, shoulder, elbow, wrist pitch, wrist roll, gripper. Pins 3, 5, 6, 9, 10, 11.
- Shoulder/elbow: Hiwonder HPS-2527 (25kg, 270 deg). Others: HPS-2027 (20kg).
- Servo power: 2x 18650 in series (7.4V). Battery negative MUST share GND with the Uno. Never battery to Uno 5V/VIN.
- E-stop button: pin 12 to GND. LEDs (optional): pins 2, 4, 7, 8 (green, yellow, blue, red).
- Base clamped so it can't twist; a shift breaks the camera calibration.

## Serial protocol (115200, newline-terminated, space-separated) - protocol of record
`?` -> `OK sidekick 1` | `P a b c d e f` start pose (before attach) | `A` attach one at a time | `D` detach | `J a b c d e f` targets | `S` freeze | `C i min max` limits (600-2400 max) | `V n` step 1-30 us per 20 ms | `L n` LED | `H` heartbeat every 0.3 s.
Uno sends `F a0 a1 a2 moving attached` every 40 ms. No line for 1 s freezes the arm.
This supersedes the comma protocol of the legacy firmware v2.

## Conventions
- Table frame in cm: origin front-left of the work area (human side), x right, y away from the human, z up. Joint values are microseconds everywhere.
- Python 3.11 venv; `pip install -r requirements.txt` (numpy<2, opencv-contrib<4.11, mediapipe 0.10.14, torch, pyserial).
- `use_sim` in config (or `--sim` / `--real`) switches the whole stack; the sim and real arms keep separate body models.
- Data lives in `sidekick_data/` (gitignored, per machine).
- `python -m sidekick selftest` must pass before pushing.

## Status
Done: firmware, simulator, calibration, perception, body model, motion, planner, builder, web UI, presets, self-test (7/7).
To do on the real arm: jog limits + poses (incl. `ready`), calibration, color tuning, babble + train, `reach` -> move build/supply zones, goto/pick tests.
Open inputs: block colors and counts in `blocks.json`; claw opening (`max_grip`); real link lengths for the sim (`sim_arm`).

## Working rules
- Match existing style: small modules, short comments, no frameworks.
- Never command moves without the E-stop or battery switch within reach. Low speed first.
- Branch per person: `git checkout -b feature/<name>`; PR into `main`.

# CLAUDE.md

Teach-by-Showing Arm (HackUTD). Show the arm a pick-and-place task once with your hand; it repeats it even if the blocks move. Hackathon deadline: ~3-4 days from 2026-11-06. Favor working over elegant.

## Pipeline
1. Watch: overhead webcam + MediaPipe hand tracking. Pinch closed = grab, open = release.
2. Understand: HSV color detection finds the block grabbed and where it was placed. Saved as steps in `demo.json` (`pick`, `place_on`, `place_at`).
3. Repeat: re-detect blocks, pixel -> table coordinates, inverse kinematics -> joint angles, send over serial.

## Layout
- `firmware/arm_firmware/arm_firmware.ino`: Uno servo driver. Knows only microseconds. No calibration lives here.
- `python/arm_serial.py`: `Arm` class; degrees -> microseconds via `JOINTS` (range, offset, direction). All calibration lives here.
- `python/servo_test.py`: keyboard jog tool.
- `python/color_detect.py`: `detect_blocks`, `nearest_block`, `draw_blocks`, HSV tuner.
- `python/record_demo.py`: hand demo -> `demo.json`.

## Hardware
- Arduino Uno R3, 6DOF aluminum arm kit, overhead USB webcam, white poster board.
- Joints 0-5: base, shoulder, elbow, wrist_p, wrist_r, gripper. Pins 3, 5, 6, 9, 10, 11.
- Shoulder/elbow: Hiwonder HPS-2527 (25kg, 270 deg). Others: HPS-2027 (20kg, 180 deg range as configured).
- Servo power: 2x 18650 in series (7.4V). Battery negative MUST share GND with the Uno.
- E-stop button: pin 2 to GND. Buzzer: pin 4.
- Base is clamped to the table. One clamp can twist at J1 and shifts break camera calibration, so add Velcro/board/weight or a second clamp. Test: push and twist the arm at home; base must not move.

## Serial protocol (115200, newline-terminated, comma-separated)
`P,u0..u5` all targets (us) | `J,i,u` one joint | `C` center (1500) | `V,n` max speed, us per 10 ms tick | `X` soft stop | `R` resume | `?` print pulses.
Replies: `READY OK DONE ESTOP STOPPED ERR`. This is the protocol of record; the original build manual (space-separated, `H`) is superseded.
Pulse range 500-2500 us. Keep speed low (`V,6` or lower) so the arm does not jolt the base.

## Conventions
- Angles are physical degrees from servo center (0 = center). Convert only in `arm_serial.py`.
- Do not add calibration or kinematics to the firmware.
- Python 3.11 venv; deps in `python/requirements.txt` (numpy<2, opencv<4.11, mediapipe 0.10.14).
- Scripts run from `python/` (they import each other by bare name). `demo.json` is gitignored.
- Run without hardware using `Arm(port, dry_run=True)`.

## Status
Done: firmware v2, serial link, jog tool, color detection, demo recorder.
Needs real-world tuning: HSV ranges, `PINCH_CLOSE/OPEN`, `GRAB_RADIUS`, per-joint offset/direction in `JOINTS`.
To build: pixel -> table calibration (homography from 4 marks), inverse kinematics, replay loop.
Known gap: `record_demo.py` can lose the block when the hand occludes it.

## Open inputs (TODO: fill in, IK depends on these)
- Link lengths in mm: shoulder->elbow ___, elbow->wrist ___, wrist->gripper tip ___.
- Shoulder height above table ___ mm; camera height ___ mm.
- Positive-direction convention per joint and safe angle limits per joint.
- Gripper open/closed values; block size and stack height.

## Working rules
- Match existing style: small modules, short comments, no frameworks.
- Never command moves without the E-stop reachable. Dry-run first, then low speed.
- Branch per person: `git checkout -b feature/<name>`; PR into `main`.

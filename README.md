# Teach by Showing Arm (HackUTD)

Show a robot arm a task once with your hand. It learns which object went where and repeats it, even if the objects move.

## How it works
1. **Watch:** an overhead camera tracks your hand with MediaPipe. Pinch closing = grab, pinch opening = release.
2. **Understand:** color detection finds which block you grabbed and where you placed it. The demo is saved as steps like `pick red -> place on blue`.
3. **Repeat:** on replay the camera re-finds each block, converts pixels to table coordinates, and inverse kinematics turns that into servo angles.
4. **Adapt:** move the blocks and the arm still finds them.

## Hardware
- Arduino Uno R3, 6DOF aluminum arm kit
- 2x Hiwonder HPS-2527 (25kg, 270 deg) for shoulder and elbow
- 4x Hiwonder HPS-2027 (20kg) for base, wrist pitch, wrist roll, gripper
- 2x 18650 cells in series (7.4V) for servo power, battery negative tied to Uno GND
- Overhead USB webcam, white poster board work surface

## Layout
```
firmware/arm_firmware/arm_firmware.ino   Uno servo driver (microsecond protocol, streaming, E-stop)
python/arm_serial.py                     Serial link + per-joint degree -> microsecond calibration
python/servo_test.py                     Keyboard jog tool
python/color_detect.py                   Block detection + HSV tuner
python/record_demo.py                    Hand demo -> demo.json step list
```

## Setup (Mac)
```
brew install python@3.11
python3.11 -m venv venv
source venv/bin/activate
pip install -r python/requirements.txt
```
Flash `firmware/arm_firmware/arm_firmware.ino` with Arduino IDE (board: Arduino Uno, 115200 baud).

## Serial protocol (115200, newline-terminated)
| Command | Meaning |
|---|---|
| `P,u0,u1,u2,u3,u4,u5` | Target pulse (us) for all 6 joints |
| `J,i,u` | Target pulse for joint i |
| `C` | Center all (1500 us) |
| `V,n` | Max speed, us per 10 ms tick |
| `X` | Soft stop |
| `R` | Resume after E-stop |
| `?` | Print current pulses |

Replies: `READY`, `OK`, `DONE`, `ESTOP`, `STOPPED`, `ERR`.

Pins: servos on 3, 5, 6, 9, 10, 11 (base to gripper). E-stop button pin 2 to GND. Buzzer pin 4.

## Status
- [x] Firmware v2
- [x] Serial link, jog tool
- [x] Color detection, demo recorder (needs tuning on the real camera)
- [ ] Pixel -> table calibration
- [ ] Inverse kinematics
- [ ] Replay loop

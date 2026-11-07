"""Jog servos from the keyboard.

Usage: python servo_test.py /dev/cu.usbmodem1101
       python servo_test.py            (no port = dry run, prints commands)
Commands:
  <joint> <deg>     physical degrees from center, e.g. "0 30" or "1 -45"
  u <joint> <us>    raw pulse, e.g. "u 0 1700"   (use this for the SG90 test)
  c                 center all
  v <n>             speed, us per tick (default 10, lower = slower)
  x                 stop      r   resume after E-stop
  q                 quit
"""
import sys
from arm_serial import Arm, JOINTS

port = sys.argv[1] if len(sys.argv) > 1 else None
arm = Arm(port, dry_run=(port is None))
print("Joints:", ", ".join(f"{i}={j['name']}({j['range_deg']})" for i, j in enumerate(JOINTS)))
print("Type '<joint> <deg>', 'u <joint> <us>', 'c', 'v <n>', 'x', 'r', or 'q'.")

while True:
    parts = input("> ").strip().lower().split()
    if not parts:
        continue
    try:
        if parts[0] == "q":
            break
        elif parts[0] == "c":
            arm.center()
        elif parts[0] == "x":
            arm.stop()
        elif parts[0] == "r":
            arm.resume()
        elif parts[0] == "v":
            arm.set_speed(int(parts[1]))
        elif parts[0] == "u":
            arm.move_joint_us(int(parts[1]), int(parts[2]))
        else:
            arm.move_joint(int(parts[0]), float(parts[1]))
    except (ValueError, IndexError):
        print("Bad command. Examples: '0 30', 'u 0 1700', 'c'")

arm.close()

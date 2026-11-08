import sys, time, xarm

sid = int(sys.argv[1])
arm = xarm.Controller('USB')
p = max(0, min(1000, arm.getPosition(sid)))   # keep inside 0-1000
d = -40 if p > 900 else 40
print(f"servo {sid}: {p} -> {p + d} and back")
arm.setPosition(sid, p + d, duration=1500, wait=True)
time.sleep(0.5)
arm.setPosition(sid, p, duration=1500, wait=True)

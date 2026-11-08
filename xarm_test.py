import xarm

arm = xarm.Controller('USB', debug=True)   # finds the arm over USB
print("Battery:", arm.getBatteryVoltage(), "V")
for sid in range(1, 7):
    print("servo", sid, "position:", arm.getPosition(sid))

#!/usr/bin/env python3
import sys, time
from robot_api import robot

side = sys.argv[1] if len(sys.argv) > 1 else "both"
power = float(sys.argv[2]) if len(sys.argv) > 2 else 40
seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 3

left = power if side in ("left", "both") else 0
right = power if side in ("right", "both") else 0

end = time.time() + seconds

try:
    robot.start()
    while time.time() < end:
        robot.drive_tank(left, right)
        time.sleep(0.1)
finally:
    robot.stop()
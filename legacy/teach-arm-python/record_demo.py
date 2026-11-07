"""Watch a hand demo and turn it into steps like pick red -> place on blue.

Run: python record_demo.py
  - Pinch thumb + index near a block = GRAB
  - Open the pinch = RELEASE
  - Press r to start/stop recording, q to quit. Steps save to demo.json.
"""
import json
import time
import cv2
import mediapipe as mp
from color_detect import detect_blocks, nearest_block, draw_blocks

PINCH_CLOSE = 0.05   # normalized distance; tune with the printed value
PINCH_OPEN = 0.08    # hysteresis so it doesn't flicker
GRAB_RADIUS = 80     # pixels: pinch must be this close to a block to count

hands = mp.solutions.hands.Hands(max_num_hands=1, min_detection_confidence=0.6)
cap = cv2.VideoCapture(0)

recording = False
pinched = False
held = None          # color currently held
steps = []

while True:
    ok, frame = cap.read()
    if not ok:
        break
    h, w = frame.shape[:2]
    found = detect_blocks(frame)
    draw_blocks(frame, found)

    res = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    if res.multi_hand_landmarks:
        lm = res.multi_hand_landmarks[0].landmark
        thumb, index = lm[4], lm[8]
        dist = ((thumb.x - index.x) ** 2 + (thumb.y - index.y) ** 2) ** 0.5
        px, py = int((thumb.x + index.x) / 2 * w), int((thumb.y + index.y) / 2 * h)
        cv2.circle(frame, (px, py), 6, (0, 255, 0) if pinched else (0, 0, 255), -1)
        cv2.putText(frame, f"pinch {dist:.3f}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        if not pinched and dist < PINCH_CLOSE:
            pinched = True
            # Ignore the block under the hand being occluded: use last-known blocks too
            block, d = nearest_block(found, px, py)
            if recording and block and d < GRAB_RADIUS:
                held = block[0]
                steps.append({"action": "pick", "color": held})
                print("GRAB", held)
        elif pinched and dist > PINCH_OPEN:
            pinched = False
            if recording and held:
                # Target = nearest OTHER block, else a table spot
                others = {k: v for k, v in found.items() if k != held}
                block, d = nearest_block(others, px, py)
                if block and d < GRAB_RADIUS * 1.5:
                    steps.append({"action": "place_on", "color": block[0]})
                    print("RELEASE on", block[0])
                else:
                    steps.append({"action": "place_at", "pixel": [px, py]})
                    print("RELEASE at", px, py)
                held = None

    status = "REC" if recording else "idle"
    cv2.putText(frame, f"{status} | steps: {len(steps)}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255) if recording else (255, 255, 255), 2)
    cv2.imshow("record demo (r = rec, q = quit)", frame)
    k = cv2.waitKey(1) & 0xFF
    if k == ord("r"):
        recording = not recording
        if recording:
            steps, held = [], None
        else:
            json.dump(steps, open("demo.json", "w"), indent=2)
            print("Saved demo.json:", steps)
    elif k == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()

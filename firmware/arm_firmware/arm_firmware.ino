// Teach-by-Showing Arm: Uno firmware v2
//
// The Uno is a "dumb" servo driver. All calibration, IK, and the
// degrees -> microseconds conversion live in Python (arm_serial.py).
// Everything is in microseconds (us) so 180 and 270 degree servos work
// the same way: 1500 = center, ~500 and ~2500 = the two ends.
//
// Protocol (115200 baud, one command per line, ends in \n):
//   P,u0,u1,u2,u3,u4,u5   set target pulse for all 6 joints (us)
//   J,i,u                  set target for one joint i (0-5)
//   C                      all joints to center (1500)
//   V,n                    max speed: n us per 10 ms tick (1-100, default 10)
//   X                      soft stop: freeze where they are now
//   R                      resume after an E-stop
//   ?                      print current pulses
// Replies: READY, OK, DONE (target reached), ESTOP, STOPPED, ERR
//
// Streaming: Python may send P lines at 20-50 Hz without waiting for
// DONE. Each new P replaces the target; the speed limit keeps motion smooth.
//
// Wiring: servo signals on 3,5,6,9,10,11. E-stop button: pin 2 to GND.
// Active buzzer: pin 4 (+) to GND (-). Servo power from the battery,
// with battery negative tied to Uno GND.

#include <Servo.h>

const int NUM = 6;
// 0 base, 1 shoulder, 2 elbow, 3 wrist pitch, 4 wrist roll, 5 gripper
const int PINS[NUM]   = {3, 5, 6, 9, 10, 11};
// Hard safety limits per joint. Tighten after assembly.
const int MIN_US[NUM] = {500, 500, 500, 500, 500, 500};
const int MAX_US[NUM] = {2500, 2500, 2500, 2500, 2500, 2500};
const int CENTER_US = 1500;

const int ESTOP_PIN = 2;
const int BUZZER_PIN = 4;
const unsigned long TICK_MS = 10;   // 100 Hz update

Servo servos[NUM];
int cur[NUM];
int target[NUM];
int maxStep = 10;                   // us per tick (~90 deg/s on a 180 servo)
bool moving = false;
bool estopped = false;
unsigned long lastTick = 0;

char buf[64];
int len = 0;

int clampUs(int i, int u) {
  if (u < MIN_US[i]) return MIN_US[i];
  if (u > MAX_US[i]) return MAX_US[i];
  return u;
}

void beep(int ms) {
  digitalWrite(BUZZER_PIN, HIGH);
  delay(ms);
  digitalWrite(BUZZER_PIN, LOW);
}

// Parse comma-separated ints after the command letter. Returns count.
int parseInts(char *s, int *out, int maxCount) {
  int n = 0;
  char *tok = strtok(s, ",");
  while (tok != NULL && n < maxCount) {
    out[n++] = atoi(tok);
    tok = strtok(NULL, ",");
  }
  return n;
}

void freeze() {
  for (int i = 0; i < NUM; i++) target[i] = cur[i];
  moving = false;
}

void handleLine(char *line) {
  char cmd = line[0];
  int vals[NUM];

  // Motion commands are blocked during an E-stop
  if (estopped && (cmd == 'P' || cmd == 'J' || cmd == 'C')) {
    Serial.println("STOPPED");
    return;
  }

  if (cmd == 'P') {
    if (parseInts(line + 2, vals, NUM) != NUM) { Serial.println("ERR"); return; }
    for (int i = 0; i < NUM; i++) target[i] = clampUs(i, vals[i]);
    moving = true;
    Serial.println("OK");
  } else if (cmd == 'J') {
    if (parseInts(line + 2, vals, 2) != 2 || vals[0] < 0 || vals[0] >= NUM) {
      Serial.println("ERR"); return;
    }
    target[vals[0]] = clampUs(vals[0], vals[1]);
    moving = true;
    Serial.println("OK");
  } else if (cmd == 'C') {
    for (int i = 0; i < NUM; i++) target[i] = clampUs(i, CENTER_US);
    moving = true;
    Serial.println("OK");
  } else if (cmd == 'V') {
    if (parseInts(line + 2, vals, 1) != 1 || vals[0] < 1 || vals[0] > 100) {
      Serial.println("ERR"); return;
    }
    maxStep = vals[0];
    Serial.println("OK");
  } else if (cmd == 'X') {
    freeze();
    Serial.println("OK");
  } else if (cmd == 'R') {
    if (digitalRead(ESTOP_PIN) == LOW) { Serial.println("STOPPED"); return; }
    estopped = false;
    Serial.println("OK");
  } else if (cmd == '?') {
    for (int i = 0; i < NUM; i++) {
      Serial.print(cur[i]);
      Serial.print(i < NUM - 1 ? "," : "\n");
    }
  } else {
    Serial.println("ERR");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(ESTOP_PIN, INPUT_PULLUP);
  pinMode(BUZZER_PIN, OUTPUT);

  // Attach one servo at a time. All 6 jumping at once can brown out the Uno.
  for (int i = 0; i < NUM; i++) {
    cur[i] = CENTER_US;
    target[i] = CENTER_US;
    servos[i].attach(PINS[i], MIN_US[i], MAX_US[i]);
    servos[i].writeMicroseconds(CENTER_US);
    delay(300);
  }
  beep(80);
  Serial.println("READY");
}

void loop() {
  // 1. Hardware E-stop: press = freeze immediately
  if (!estopped && digitalRead(ESTOP_PIN) == LOW) {
    estopped = true;
    freeze();
    Serial.println("ESTOP");
    beep(300);
  }

  // 2. Read serial into a line buffer
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (len > 0) {
        buf[len] = '\0';
        handleLine(buf);
        len = 0;
      }
    } else if (len < (int)sizeof(buf) - 1) {
      buf[len++] = c;
    }
  }

  // 3. Move every joint toward its target at the speed limit
  unsigned long now = millis();
  if (moving && now - lastTick >= TICK_MS) {
    lastTick = now;
    bool allThere = true;
    for (int i = 0; i < NUM; i++) {
      int diff = target[i] - cur[i];
      if (diff > maxStep)       { cur[i] += maxStep; allThere = false; }
      else if (diff < -maxStep) { cur[i] -= maxStep; allThere = false; }
      else                      { cur[i] = target[i]; }
      servos[i].writeMicroseconds(cur[i]);
    }
    if (allThere) {
      moving = false;
      Serial.println("DONE");
    }
  }
}

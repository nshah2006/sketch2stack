// Sidekick firmware (handbook Phase 2B)
//
// The Uno never decides where to go. It moves where told, smoothly and
// within limits, and reports sensors. Joint values are pulse widths in
// microseconds only (never degrees: the Servo library's degree function
// assumes 180 degree servos, ours are 270).
//
// Serial protocol, 115200 baud, one line per command, ends with newline:
//   ?                 -> replies "OK sidekick 1"
//   P a b c d e f     set starting pose (6 pulses); only for joints not attached yet
//   A                 attach servos one at a time, 400 ms apart
//   D                 detach all servos (arm goes limp)
//   J a b c d e f     new targets for all 6 joints, clamped to limits
//   S                 freeze where you are
//   C i min max       set limits for joint i (never wider than 600..2400)
//   V n               step size, 1..30 us per 20 ms tick
//   L n               LEDs: 0 off, 1 green, 2 yellow, 3 blue, 4 red
//   H                 heartbeat (laptop sends every 0.3 s)
// Malformed lines are ignored, but any complete line counts as "alive".
//
// Uno -> laptop every 40 ms:  F a0 a1 a2 moving attached
// Watchdog: no line for 1 s -> every target = current, LED red, frozen.

#include <Servo.h>

const int NUM = 6;
// J0 base, J1 shoulder, J2 elbow, J3 wrist pitch, J4 wrist roll, J5 gripper
const int PINS[NUM] = {3, 5, 6, 9, 10, 11};
const int HARD_MIN = 600;
const int HARD_MAX = 2400;
const int LED_PINS[4] = {2, 4, 7, 8};   // green, yellow, blue, red

const unsigned long TICK_MS = 20;
const unsigned long REPORT_MS = 40;
const unsigned long WATCHDOG_MS = 1000;

Servo servos[NUM];
int cur[NUM];
int target[NUM];
int jmin[NUM];
int jmax[NUM];
bool attached[NUM];
int stepUs = 8;
bool frozen = false;

unsigned long lastTick = 0;
unsigned long lastReport = 0;
unsigned long lastMsg = 0;

char buf[80];
int len = 0;

int clampJ(int i, long v) {
  if (v < jmin[i]) return jmin[i];
  if (v > jmax[i]) return jmax[i];
  return (int)v;
}

void setLed(int n) {
  for (int k = 0; k < 4; k++) digitalWrite(LED_PINS[k], LOW);
  if (n >= 1 && n <= 4) digitalWrite(LED_PINS[n - 1], HIGH);
}

// Split "rest" into exactly `want` integers. Returns false if malformed.
bool parseInts(char *rest, long *out, int want) {
  int n = 0;
  char *tok = strtok(rest, " ");
  while (tok != NULL) {
    if (n >= want) return false;
    char *end;
    long v = strtol(tok, &end, 10);
    if (end == tok || *end != '\0') return false;
    out[n++] = v;
    tok = strtok(NULL, " ");
  }
  return n == want;
}

bool anyAttached() {
  for (int i = 0; i < NUM; i++) if (attached[i]) return true;
  return false;
}

bool allAttached() {
  for (int i = 0; i < NUM; i++) if (!attached[i]) return false;
  return true;
}

bool isMoving() {
  for (int i = 0; i < NUM; i++) if (cur[i] != target[i]) return true;
  return false;
}

void handleLine(char *line) {
  char cmd = line[0];
  char *rest = line + 1;
  long v[6];

  if (cmd == '?' && line[1] == '\0') {
    Serial.println("OK sidekick 1");
  } else if (cmd == 'P') {
    if (!parseInts(rest, v, 6)) return;
    for (int i = 0; i < NUM; i++) {
      if (!attached[i]) {
        cur[i] = clampJ(i, v[i]);
        target[i] = cur[i];
      }
    }
  } else if (cmd == 'A' && line[1] == '\0') {
    for (int i = 0; i < NUM; i++) {
      if (attached[i]) continue;
      servos[i].writeMicroseconds(cur[i]);   // current pulse first...
      servos[i].attach(PINS[i], 500, 2500);  // ...then attach with the true range
      servos[i].writeMicroseconds(cur[i]);
      attached[i] = true;
      delay(400);
    }
    lastMsg = millis();                      // the attach delay is not silence
  } else if (cmd == 'D' && line[1] == '\0') {
    for (int i = 0; i < NUM; i++) {
      if (attached[i]) servos[i].detach();
      attached[i] = false;
    }
  } else if (cmd == 'J') {
    if (!parseInts(rest, v, 6)) return;
    for (int i = 0; i < NUM; i++) target[i] = clampJ(i, v[i]);
  } else if (cmd == 'S' && line[1] == '\0') {
    for (int i = 0; i < NUM; i++) target[i] = cur[i];
  } else if (cmd == 'C') {
    if (!parseInts(rest, v, 3)) return;
    int i = (int)v[0];
    if (i < 0 || i >= NUM) return;
    long lo = v[1] < HARD_MIN ? HARD_MIN : v[1];
    long hi = v[2] > HARD_MAX ? HARD_MAX : v[2];
    if (lo >= hi) return;
    jmin[i] = (int)lo;
    jmax[i] = (int)hi;
    target[i] = clampJ(i, target[i]);
    if (!attached[i]) cur[i] = clampJ(i, cur[i]);
  } else if (cmd == 'V') {
    if (!parseInts(rest, v, 1)) return;
    if (v[0] >= 1 && v[0] <= 30) stepUs = (int)v[0];
  } else if (cmd == 'L') {
    if (!parseInts(rest, v, 1)) return;
    if (v[0] >= 0 && v[0] <= 4) setLed((int)v[0]);
  } else if (cmd == 'H' && line[1] == '\0') {
    // heartbeat: nothing to do, the line itself counts as alive
  }
}

void setup() {
  Serial.begin(115200);
  for (int k = 0; k < 4; k++) pinMode(LED_PINS[k], OUTPUT);
  setLed(0);
  for (int i = 0; i < NUM; i++) {
    cur[i] = 1500;
    target[i] = 1500;
    jmin[i] = HARD_MIN;
    jmax[i] = HARD_MAX;
    attached[i] = false;
  }
  lastMsg = millis();
}

void loop() {
  unsigned long now = millis();

  // 1. Read characters without blocking; act on complete lines.
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (len > 0) {
        buf[len] = '\0';
        frozen = false;          // any line clears frozen and counts as alive
        lastMsg = millis();
        handleLine(buf);
        len = 0;
      }
    } else if (len < (int)sizeof(buf) - 1) {
      buf[len++] = c;
    } else {
      len = 0;                   // overlong line: drop it
    }
  }
  now = millis();

  // 2. Watchdog: silence for 1 s freezes the arm.
  if (!frozen && now - lastMsg > WATCHDOG_MS) {
    for (int i = 0; i < NUM; i++) target[i] = cur[i];
    setLed(4);
    frozen = true;
  }

  // 3. Every 20 ms, step each joint toward its target.
  if (now - lastTick >= TICK_MS) {
    lastTick = now;
    for (int i = 0; i < NUM; i++) {
      int d = target[i] - cur[i];
      if (d > stepUs) d = stepUs;
      if (d < -stepUs) d = -stepUs;
      cur[i] += d;
      if (attached[i]) servos[i].writeMicroseconds(cur[i]);
    }
  }

  // 4. Every 40 ms, report sensors and state.
  if (now - lastReport >= REPORT_MS) {
    lastReport = now;
    Serial.print("F ");
    Serial.print(analogRead(A0));
    Serial.print(' ');
    Serial.print(analogRead(A1));
    Serial.print(' ');
    Serial.print(analogRead(A2));
    Serial.print(' ');
    Serial.print(isMoving() ? 1 : 0);
    Serial.print(' ');
    Serial.println(allAttached() ? 1 : 0);
  }
}

"""Short acknowledgement gestures (handbook 2I, expressive extra).

Scripted joint nudges only: no perception, no planning. A gesture is a few
tens of microseconds of travel away from the pose the arm is already in and
always finishes back on that exact pose, so it can be dropped between build
steps without moving the arm's working position.

Everything goes through Motion._move, so the safety stop interrupts a gesture
the same way it interrupts a pick: the arm waits where it is and the gesture
finishes by returning to its starting pose once the area is clear again.
"""

BASE, SHOULDER, ELBOW, PITCH, ROLL, CLAW = range(6)
CENTRE = 1500                 # pulse that faces the base straight at the human (front of the table)

# Travel per phase, in microseconds. Deliberately small: an acknowledgement,
# not a move. At the default 8 us per 20 ms tick these take ~0.2 s a phase.
NOD_US = 60                   # wrist-pitch dip, twice
TILT_US = 70                  # wrist roll, side to side
TURN_US = 80                  # base turn toward the human
LIFT_US = 40                  # small wrist-pitch lift that goes with the turn
SLOW_US = 3                   # us per tick while refusing, so the "no" reads as reluctant


def _dir(cfg, pose, i, delta):
    """`delta` if the joint has room for it, otherwise the other way.
    Keeps a gesture visible when the joint already sits near a limit instead of
    clamping it down to nothing."""
    lo, hi = cfg["joint_min"][i], cfg["joint_max"][i]
    if lo <= pose[i] + delta <= hi:
        return delta
    return -delta if lo <= pose[i] - delta <= hi else 0


def _toward_front(pose):
    """Base nudge toward the person: joint 0 at 1500 faces the front of the table."""
    gap = CENTRE - pose[BASE]
    return int(max(-TURN_US, min(TURN_US, gap)))


def _pose(cfg, start, offsets):
    """start + offsets, clamped to the configured limits (a gesture never widens them)."""
    lo, hi = cfg["joint_min"], cfg["joint_max"]
    pose = list(start)
    for i, d in offsets.items():
        pose[i] = int(min(max(start[i] + d, lo[i]), hi[i]))
    return pose


def run(m, script, speed_us=None):
    """Play `script` ([({joint: offset_us}, dwell_s), ...]) and come back to the start pose.

    -> "ok" | "busy" (carrying a block, nothing moved) | "abort" (safety stop)
    """
    if m.carrying():
        m.log("not gesturing: the claw is holding a block")
        return "busy"
    if m.abort.is_set():
        return "abort"                               # never queue a gesture behind a safety stop
    start = list(m.arm.targets)                      # the pose we must end on
    if speed_us:
        m.arm.speed(speed_us)
    try:
        for offsets, dwell in script:
            if m.abort.is_set():
                break                                # safety stop wins; skip to the restore
            if not m._move(_pose(m.cfg, start, offsets)):
                return "abort"
            m.clock.sleep(dwell)
        ok = m._move(start)                          # _move waits out a stop, so this still lands
    finally:
        if speed_us:
            m.arm.speed(int(m.cfg["step_us"]))       # never leave the arm slowed down
    return "ok" if ok else "abort"


def nod(m):
    """"Got it": two small wrist-pitch dips."""
    d = _dir(m.cfg, m.arm.targets, PITCH, NOD_US)
    return run(m, [({PITCH: d}, 0.08), ({}, 0.08), ({PITCH: d}, 0.08), ({}, 0.0)])


def refuse(m):
    """"I can't do that": a slow side-to-side wrist tilt."""
    d = _dir(m.cfg, m.arm.targets, ROLL, TILT_US)
    return run(m, [({ROLL: d}, 0.15), ({ROLL: -d}, 0.15), ({ROLL: d}, 0.15), ({}, 0.0)],
               speed_us=max(1, min(SLOW_US, int(m.cfg["step_us"]))))


def listen(m):
    """"Listening": a brief turn of the base toward the person, held for a moment.
    The wrist lifts a little too, so the gesture still reads when the base is
    already pointing at the front."""
    turn = _toward_front(m.arm.targets)
    lift = _dir(m.cfg, m.arm.targets, PITCH, -LIFT_US)
    return run(m, [({BASE: turn, PITCH: lift}, 0.6), ({}, 0.0)])


# ===================================================================== emotions
# Expressive moves in the spirit of ELEGNT (arXiv 2501.12493): the wrist is the
# arm's "head", and the feeling comes from timing, amplitude and where the head
# points rather than from big travel. Same rules as the gestures above: small
# offsets from the current pose, clamped to the limits, always back on the start
# pose, refused while carrying, and the safety stop still wins.
#
# Joint directions (sim, ready pose): wrist pitch - looks up / out at the person,
# + droops the head down and in; shoulder - leans back and lifts, + leans forward
# and down (kept small: the claw hangs only a few cm above the table at ready).
#
# Call any of them through one entry point:   gestures.express(motion, "happy")
#                                             gestures.express(motion, "look_at", x=10, y=5)
# EMOTIONS maps name -> function(m, **kw); each returns "ok" | "busy" | "abort".

EMO_MAX_US = 150              # per-joint travel cap for every emotion except the base in look_at
LOOK_TURN_MAX = 450           # base travel cap for look_at (about 60 deg)
FAST, QUICK, SLOW, CRAWL = 20, 14, 4, 2   # us per 20 ms tick


def _cap(d, cap=EMO_MAX_US):
    return int(max(-cap, min(cap, d)))


def _claw_close(cfg, us):
    """Offset that closes the claw by `us` (claw_closed may sit above or below claw_open)."""
    return us if cfg["claw_closed"] >= cfg["claw_open"] else -us


def _flow(m, pose, sp):
    """Send `pose` and sleep the firmware's travel time instead of waiting for the
    "stopped" report, so keyframes without a dwell blend into one fluid motion.
    The firmware moves every joint at most `sp` us per 20 ms tick, so the time is
    exact for the commanded pose. A safety stop falls back to Motion._move."""
    prev = m.arm.targets
    m.arm.send_targets(pose)
    left = max(abs(a - b) for a, b in zip(prev, pose)) / sp * 0.02
    while left > 0:
        if m.abort.is_set():
            return m._move(pose)                     # waits out the stop, then lands the pose
        m.clock.sleep(min(0.02, left))
        left -= 0.02
    return True


def play(m, frames):
    """Like run(), but every keyframe can carry its own speed:
    frames = [({joint: offset_us}, dwell_s, speed_us or None), ...]; the final
    return to the start pose uses the last keyframe's speed."""
    if m.carrying():
        m.log("not emoting: the claw is holding a block")
        return "busy"
    if m.abort.is_set():
        return "abort"
    cfg = m.cfg
    start = list(m.arm.targets)
    default = int(cfg["step_us"])
    cur = None
    try:
        for offsets, dwell, sp in frames:
            if m.abort.is_set():
                break
            sp = int(sp or default)
            if sp != cur:
                m.arm.speed(sp)
                cur = sp
            pose = _pose(cfg, start, {i: _cap(d, LOOK_TURN_MAX if i == BASE else EMO_MAX_US)
                                      for i, d in offsets.items()})
            if not (_flow(m, pose, sp) if dwell <= 0 else m._move(pose)):
                return "abort"
            m.clock.sleep(dwell)
        ok = m._move(start)
    finally:
        if cur is not None and cur != default:
            m.arm.speed(default)
    return "ok" if ok else "abort"


def yes(m):
    """Clear "yes": two quick, deeper wrist-pitch nods, the second a little smaller."""
    d = _dir(m.cfg, m.arm.targets, PITCH, 120)
    return play(m, [({PITCH: d}, 0.05, QUICK), ({PITCH: -d // 3}, 0.05, QUICK),
                    ({PITCH: d * 3 // 4}, 0.05, QUICK), ({}, 0.0, QUICK)])


def no(m):
    """Head shake: the base swings side to side twice with the head slightly lowered."""
    d = _dir(m.cfg, m.arm.targets, BASE, 100)
    p = _dir(m.cfg, m.arm.targets, PITCH, 50)
    return play(m, [({BASE: d, PITCH: p}, 0.05, QUICK), ({BASE: -d, PITCH: p}, 0.05, QUICK),
                    ({BASE: d * 2 // 3, PITCH: p}, 0.05, QUICK), ({BASE: -d // 2, PITCH: p}, 0.0, QUICK),
                    ({}, 0.0, QUICK)])


def happy(m):
    """Quick bouncy lifts of the head (shoulder back + pitch up) with a claw clap on each bounce."""
    c = _claw_close(m.cfg, 150)
    up = {SHOULDER: _dir(m.cfg, m.arm.targets, SHOULDER, -70), PITCH: _dir(m.cfg, m.arm.targets, PITCH, -140)}
    half = {k: v // 3 for k, v in up.items()}
    seq = []
    for k in range(3):
        seq += [({**up, ROLL: 50 if k % 2 else -50}, 0.0, FAST), ({**half, CLAW: c}, 0.0, FAST)]
    return play(m, seq + [(up, 0.1, FAST), ({}, 0.0, QUICK)])


def sad(m):
    """Slow sag: the head droops down and tilts a little, hangs there, then slowly recovers."""
    p = _dir(m.cfg, m.arm.targets, PITCH, 150)
    r = _dir(m.cfg, m.arm.targets, ROLL, 60)
    s = _dir(m.cfg, m.arm.targets, SHOULDER, -40)            # shoulders drop back, not down onto the table
    return play(m, [({PITCH: p, ROLL: r, SHOULDER: s}, 0.45, SLOW),
                    ({PITCH: p * 4 // 5, ROLL: r, SHOULDER: s}, 0.0, CRAWL), ({}, 0.0, SLOW)])


def confused(m):
    """Head tilt one way, pause, the other way, with a small base turn - "huh?"."""
    r = _dir(m.cfg, m.arm.targets, ROLL, 140)
    b = _dir(m.cfg, m.arm.targets, BASE, 60)
    p = _dir(m.cfg, m.arm.targets, PITCH, -60)
    return play(m, [({ROLL: r, BASE: b, PITCH: p}, 0.45, QUICK),
                    ({ROLL: -r, BASE: -b // 2, PITCH: p}, 0.45, 10), ({}, 0.0, QUICK)])


def thinking(m, loops=1):
    """Small slow circles traced by the head (pitch + roll), looking slightly up."""
    import math
    lift = _dir(m.cfg, m.arm.targets, PITCH, -60)
    pts = []
    for _ in range(max(1, int(loops))):
        for k in range(8):
            a = 2 * math.pi * k / 8
            pts.append(({PITCH: lift + int(round(60 * math.sin(a))), ROLL: int(round(100 * math.cos(a)))}, 0.0, 8))
    return play(m, pts + [({PITCH: lift, ROLL: 100}, 0.05, 8), ({}, 0.0, 10)])


def greet(m):
    """Wave hello: turn toward the person, lift the head up and wiggle the wrist roll."""
    t = _toward_front(m.arm.targets)
    up = {BASE: t, SHOULDER: _dir(m.cfg, m.arm.targets, SHOULDER, -110),
          PITCH: _dir(m.cfg, m.arm.targets, PITCH, -150)}
    seq = [(up, 0.05, QUICK)]
    for k in range(4):
        seq.append(({**up, ROLL: 130 if k % 2 == 0 else -130}, 0.0, FAST))
    return play(m, seq + [(up, 0.1, FAST), ({}, 0.0, QUICK)])


def excited(m):
    """Fast small bounces with the claw fluttering open and shut."""
    c = _claw_close(m.cfg, 150)
    s = _dir(m.cfg, m.arm.targets, SHOULDER, -60)
    p = _dir(m.cfg, m.arm.targets, PITCH, -80)
    seq = []
    for k in range(5):
        seq += [({SHOULDER: s, PITCH: p, CLAW: c}, 0.0, 25), ({SHOULDER: s // 4, PITCH: p // 4}, 0.0, 25)]
    return play(m, seq + [({}, 0.0, FAST)])


def sleepy(m, breaths=2):
    """Idle breathing: a slow shoulder rise and fall, the head nodding off a little on each out-breath."""
    s = _dir(m.cfg, m.arm.targets, SHOULDER, -50)
    p = _dir(m.cfg, m.arm.targets, PITCH, 90)
    seq = []
    for _ in range(max(1, int(breaths))):
        seq += [({SHOULDER: s, PITCH: p // 4}, 0.3, 2), ({PITCH: p}, 0.6, 2)]
    return play(m, seq + [({}, 0.0, SLOW)])


def look_at(m, x, y, hold_s=0.8):
    """Turn the base toward table point (x, y) cm and raise the head toward it
    (more when it is far from the base), hold, and come back. Uses the same
    yaw convention as Motion.base_yaw: base 1500 faces the front of the table."""
    import math
    cfg = m.cfg
    bx, by = cfg["layout"]["base"]
    yaw = math.degrees(math.atan2(x - bx, -(y - by)))
    start = m.arm.targets
    want = 1500 + yaw * cfg["us_per_degree"]
    turn = int(max(-LOOK_TURN_MAX, min(LOOK_TURN_MAX, want - start[BASE])))
    far = math.hypot(x - bx, y - by)
    lift = _dir(cfg, start, PITCH, -int(max(40, min(EMO_MAX_US, (far - 12.0) * 6))))
    return play(m, [({BASE: turn, PITCH: lift}, hold_s, QUICK), ({}, 0.0, QUICK)])


EMOTIONS = {
    "yes": yes, "no": no, "happy": happy, "sad": sad, "confused": confused,
    "thinking": thinking, "greet": greet, "excited": excited, "sleepy": sleepy,
    "look_at": look_at,
    "nod": nod, "refuse": refuse, "listen": listen,      # the original acknowledgements
}


def express(m, name, **kw):
    """Play emotion `name` on Motion `m` -> "ok" | "busy" | "abort" | "unknown".
    Off when cfg["gestures"] is false (returns "ok" without moving)."""
    fn = EMOTIONS.get(name)
    if fn is None:
        m.log(f"unknown emotion {name!r}")
        return "unknown"
    if not m.cfg.get("gestures", True):
        return "ok"
    return fn(m, **kw)

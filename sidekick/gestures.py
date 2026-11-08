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

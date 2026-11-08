# Handover: getting the real arm picking accurately

For whoever is calibrating the arm on the bench machine. `README.md` has the full
step-by-step checklist and the target numbers; this covers the part that is not
obvious from it — what to do when the claw does not line up with where the camera
says the block is, and how the feature work on the `rishi` branch gets wired in
afterwards.

Short version: **there is nothing to wire in.** Every feature sits above the
hardware seam. You drop the trained and measured files into `sidekick_data/` and run
with `--real`.

---

## Part 1 — the claw not lining up

### The code already corrects itself. Check it is getting the chance to.

`motion.go_to()` does not trust the learned model blindly. It moves, looks at where
the claw actually ended up, and aims past the error — up to three times:

```
move -> read the claw marker with the camera -> error = target - actual
within 6 mm horizontally and 10 mm vertically?  done
otherwise: aim += error, re-solve, move again
```

A systematic offset should wash out on its own. If it is not washing out, one of
these is true, in rough order of likelihood.

### 1. `marker_to_fingertip` has never been measured

```
sidekick_data/config.json  ->  "marker_to_fingertip": 9.0
```

**This is a default nobody measured** — it is listed as an open input in `CLAUDE.md`.
The code works out where the fingertips are by projecting this distance backwards
along the claw marker's face normal (`perception.claw_tip`).

If the real distance is not 9.0 cm, **every pick is off by a constant, in the
direction the claw is pointing.** That is exactly what "the claw does not line up"
looks like.

Measure from the face of the marker to the fingertips with a ruler and put the real
number in `sidekick_data/config.json`. Two minutes, and it is the first thing to
rule out.

### 2. The claw marker is not visible in the pose being corrected

Look for this in the log:

```
claw marker not visible; accepting the move
```

If that appears, the correction loop is being skipped and you are flying on the body
model alone. Causes: the arm occludes the marker at that pose, glare, or the marker
is too small to detect at 60 cm. `claw_marker_size` must match the printed marker —
measure the printout rather than assuming it printed at 100%.

### 3. Table calibration is off

`calib-table --real` should report under 1.5 px, a camera height near 60 cm, and the
ruler check should agree within 5 mm. If the table solve is off, block positions and
claw readings are wrong in the same direction, and the correction loop will happily
converge on the wrong place.

### 4. Babble did not cover where you are building

The body model is only accurate where it has seen itself move. If you babbled in one
region and are building in another, predictions degrade at the edges. `reach --real`
prints what the arm can actually touch — if the build strip sits near the boundary of
that map, move it inwards.

### Measure, do not guess

```bash
python -m sidekick goto-test --real          # mean and worst error, in mm
python -m sidekick pick-test --real -n 10
```

Targets: goto under 5 mm, 8 of 10 picks.

How to read a bad result:

| What you see | Likely cause |
|---|---|
| Large error, **always the same direction** | `marker_to_fingertip`, or table calibration |
| Large error, **scattered** | body model needs more or better-spread babble |
| Fine near the base, bad further out | building near the edge of reach; move the zones in |
| `unreachable` before it even moves | target outside what babble covered |

A constant direction is good news — it is one number, not a training problem.

### Easy things to get wrong

- **`claw_open` / `claw_closed`** are marked "measure" in config and still hold
  defaults. If `claw_closed` does not actually close on a block, picks fail in a way
  that looks like aiming.
- **`max_grip`** (in `blocks.json`, currently 5.0 cm) is the widest side the claw can
  close across. Wrong value and the planner will plan picks the gripper physically
  cannot make.
- **The base must not shift.** Moving it invalidates the table calibration and the
  body model at the same time, and the symptom looks like drift rather than a reset.

---

## Part 2 — wiring in the features afterwards

### There is nothing to wire

The simulator fakes the *hardware*, not the application. A fake serial port speaks the
exact firmware protocol, and the simulated camera emits the same observation objects
the real one does. The arm driver and everything above perception are the same code in
both.

The only thing that changes is which file gets loaded:

```python
def body_path(cfg, data_dir=None):
    """The simulator and the real arm each get their own body model."""
    return path("body_sim" if cfg["use_sim"] else "body", data_dir)
```

Every feature calls `body.solve([x, y, z])` — "put the claw here" — and never knows
which model answered.

### What to drop in

```
sidekick_data/models/body.pt          trained body model
sidekick_data/babble/samples.jsonl    the babble samples it came from
sidekick_data/calibration.json        lens + table calibration
sidekick_data/config.json             measured limits, poses, marker_to_fingertip
```

Then add `--real` to any command, or set `"use_sim": false` in `config.json`.

### Expect the first real run to surface something

Camera index, a joint limit, a frame mismatch. Budget an hour. It is debugging, not
integration — no feature code should need changing, and if it does, that is a bug
worth reporting rather than patching locally.

Worth running before the demo:

```bash
python -m sidekick selftest          # 9/10 is the current expected result
python -m sidekick presets --real    # every preset should say OK
```

### What you get once it runs

Three ways to describe a build (sketch, hand-placed blocks, speech), mid-build voice
changes, acknowledgement gestures, and a repair loop that negotiates when something
will not stand. All of it already works against the simulated arm.

---

## Known failures, so you do not chase them

- **One selftest fails on purpose**: `block type from color + outline + footprint`,
  1079/1500. Cube and pillar are both 3 x 3 cm seen from overhead and 60% of our
  blocks are unpainted, so colour cannot separate them. It is a physics limit, and it
  does **not** affect the pickup-spot flow where a person hands the arm each block —
  that check is gated behind `use_color`, which is off.
- **Mid-build voice changes only affect blocks not yet placed.** The arm can pick from
  a supply zone and place, but cannot take a block back off a finished stack. It says
  so rather than pretending.
- **The build strip is 4 cm deep on purpose.** Deepening it so long blocks could be
  turned a quarter pushed every placement to the edge of reach and made placement ten
  times worse (3 mm to 30 mm on the simulated House build). The reasoning is recorded
  in `config.py` so it does not get retried blind.

---

## Branch

Pull **`rishi`** from `github.com/nshah2006/sketch2stack`. If you are working from a
copy taken before the repository migration, take the branch rather than the files —
several fixes exist only in the history.

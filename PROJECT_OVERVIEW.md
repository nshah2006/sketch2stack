# Sketch2Stack — project overview

Context for writing a pitch deck. Figures here are measured, not estimated. Where
something is unproven it says so, because a judge who finds one overclaim stops
believing the rest.

---

## One line

Draw a shape, place blocks by hand, or just say what you want — a 6-joint robot
arm builds it out of real wooden blocks, and you can change your mind out loud
while it is building.

## The problem

Telling a robot arm what to build normally means CAD, a teach pendant, or
hand-written coordinates. That rules out anyone who is not already a robotics
person. We wanted the instruction to be a drawing or a sentence, and the arm to
work out the rest — including noticing when what you asked for will not stand up,
and saying so.

---

## How it works

**Four stages, each independently inspectable.**

1. **Describe** — three ways in, all producing the same design JSON:
   - *Draw*: sketch a front view. The board is the build area at 1:1, with a
     centimetre ruler, so the size you draw is the size that gets built.
   - *Blocks*: drag real catalogue pieces onto the strip. Sizes, colours and stock
     come from the live inventory, so the layout is exactly buildable.
   - *Speak*: say what you want; a language model turns it into blocks.
2. **Plan** — a deterministic planner settles every block by gravity and checks
   support, overhang, roof rules, strip bounds, stock, and whether the arm can
   physically reach each placement. It orders the build bottom-up, back-first,
   left-to-right, and picks which axis the gripper closes along so a finger never
   hits a neighbouring block.
3. **Build** — two threads. A vision thread runs perception and safety every frame;
   a worker thread is the only thing allowed to move the arm. It finds a matching
   block, picks it, rotates the wrist, places it, and verifies with the camera.
4. **Verify and adapt** — placement is checked against the plan, and you can talk to
   the build while it runs to change what has not been placed yet.

---

## What is genuinely hard here, and what we did about it

**No hand-written inverse kinematics. The arm learns its own body.** It babbles —
800 semi-random poses while an overhead camera tracks a marker on the gripper —
then trains a small neural network mapping servo pulses to fingertip position and
orientation. To reach a point, we gradient-search that network. Held-out error
**0.24 cm**. This matters because these are hobby servos with no encoders and no
force feedback: a closed-form model of an *ideal* arm would not describe *this*
arm, with its particular slop and droop.

**The microcontroller is deliberately stupid.** The Arduino only speaks pulse
widths, enforces joint limits, smooths motion, and runs a watchdog that freezes
everything if the host goes quiet for one second. Every decision lives in Python,
which makes the whole system testable without hardware.

**The simulator is a first-class seam, not a toy.** A fake serial port speaks the
exact firmware protocol, and a simulated camera emits the same observation objects
the real one does. The arm driver and everything above perception are identical in
simulation and reality. The simulated arm is *deliberately flawed* — gain and offset
errors, backlash, droop — so the learning code is tested against an imperfect
machine rather than a perfect one.

**The planner is the oracle; the language model only proposes.** When a request does
not fit, the model is handed the planner's exact complaints plus real stock and asked
to repair it — swap a colour we own, split one long block into shorter ones, lower a
stack. Every proposal is re-validated. A model that returns prose, broken JSON, an
invented block type, or nothing at all falls back to a deterministic trim. The model
can only ever improve on the fallback, never break it.

**Safety is deterministic and the AI cannot override it.** Every camera frame, a hand
within 10 cm of a lowered claw stops the arm; it resumes one second after the area is
clear. There is a hardware E-stop. Nothing with a network round-trip sits anywhere
near that path.

---

## The numbers

| | |
|---|---|
| Real wooden blocks | **75**, across 8 types and 7 colours |
| Build area | 20 cm wide × 12 cm tall × 4 cm deep |
| Learned kinematics, held-out error | **0.24 cm** |
| Placement accuracy (simulated arm) | **2–3 mm** |
| Sketch → block-shape fidelity | **0.83–0.93 IoU** |
| Automated test suite | **9 of 10 passing** |
| Code | ~6,400 lines Python · ~6,200 TypeScript · 231 lines firmware |

---

## Features built

- **Three input modes** — freehand sketch, hand-placed blocks, speech.
- **True-size drawing board** with a centimetre ruler: what you draw at 6 cm is built
  at 6 cm. Previously only a drawing's aspect ratio survived.
- **Block editor** — drag real catalogue pieces, snap to the edges and centre of
  whatever is underneath, slide a block in between two already stacked, rotate
  through the poses the arm can actually achieve.
- **Inventory-aware throughout** — a build never asks for more of a colour than
  exists. Stock is a live database of the physical blocks on the bench.
- **Talk to a running build** — change the blocks still to come by speaking. It
  previews the change and waits for confirmation; an open microphone can never alter
  a build on its own.
- **The arm answers you** — nods when it takes a change, shakes its head at the wrong
  block, looks up when it needs one from you.
- **Negotiated repair** — when something will not stand, the model proposes fixes and
  the planner judges them.
- **Three-layer resilience** — Nemotron first, OpenAI if it cannot be reached, and a
  hand-written rule parser that needs no network at all.

---

## Honest status

**Working and verified**
- The whole pipeline end to end in simulation, repeatedly.
- The real arm is wired, moving, and opening and closing its gripper.
- Inventory database connected; the catalogue matches the physical blocks exactly.
- 9 of 10 automated checks passing.

**In progress**
- Calibration and body-model training on the real arm. The code path is identical to
  simulation — a trained file is dropped in, not a rewrite.
- Nemotron is wired as the primary model and routes correctly, but the NVIDIA account
  is not yet entitled to run inference, so OpenAI is answering today. Switching is a
  key, not a code change.
- Neither speech path has been tested with a real microphone yet.

**Known limits we chose, and why**
- *Mid-build changes affect only blocks not yet placed.* The arm can pick from a
  supply zone and place, but cannot take a block back off a finished stack. Rather
  than fake it, the arm says so: "the base is already down, but I can change the roof."
- *The camera cannot tell a cube from a pillar in bare wood.* Both are 3 × 3 cm seen
  from overhead and 60% of our blocks are unpainted. That is a physics limit, not a
  software one — the fix is paint or separate pickup spots, and it does not affect the
  flow we use, where a person hands the arm each block.
- *The build strip is 4 cm deep.* We tried deepening it so long blocks could be turned
  a quarter; it pushed every placement to the ragged edge of the arm's reach and made
  placement ten times worse. Measured, reverted, documented.

---

## What we would build next

1. **A side camera** to catch a collapsed or leaning stack. The overhead view verifies
   position but not height, so "did the tower survive" is currently invisible.
2. **A trained block classifier** on photographs of our actual blocks, replacing the
   hand-written colour-and-outline rules.
3. **Showing the negotiation on screen** — the repair loop already records each round;
   surfacing it lets you watch the system reason about why something will not stand.

---

## Why it matters beyond the demo

The same loop — *say what you want, have a machine check it against physical reality,
and correct it together* — is what assembly assistance looks like for anyone who cannot
easily handle small parts themselves. The blocks are a toy. The structure is not: a
learned body model, a deterministic safety layer the AI cannot override, live inventory,
and a language model that negotiates rather than dictates.

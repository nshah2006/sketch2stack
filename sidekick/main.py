"""Sidekick command-line tool: one command per build step.

    python -m sidekick.main <command> [--sim | --real] [--speed N]

Setup and checks   setup, markers, check, selftest, simtest
Arm                jog, babble, train-body, reach, goto-test, pick-test
Camera             calib-lens, calib-table, tune-colors, view
Building           presets, build <preset>, ui

Every command reads and writes only the data folder (sidekick_data/, or
$SIDEKICK_DATA), so any step can be redone on its own.
"""
import argparse
import json
import math
import sys
import time

import numpy as np

from . import config as C
from .catalog import Catalog

HAND_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
                  "hand_landmarker/float16/latest/hand_landmarker.task")


# ===================================================================== shared setup
class Stack:
    """Everything a command needs, built the same way for sim and real."""

    def __init__(self, cfg, need_arm=True, need_body=False, need_vision=True, hands=True, speed=None):
        self.cfg, self.catalog = cfg, Catalog.load()
        self.world = self.arm = self.source = self.body = None
        if cfg["use_sim"]:
            from .sim import make_world
            self.world = make_world(cfg, self.catalog, speed=speed)
            self.source = self.world
            self.clock = self.world.clock
        else:
            from .clock import RealClock
            self.clock = RealClock()
            if need_vision:
                from .calibration import Calibration
                from .camera import Camera
                from .perception import HandTracker, RealVision
                calib = Calibration.load()
                cam = Camera.from_config(cfg)
                if not calib.has_lens:
                    calib.default_lens(*cam.size())
                tracker = None
                if hands and C.path("hand_model").exists():
                    tracker = HandTracker(C.path("hand_model"), cfg)
                elif hands:
                    print("WARNING: no hand model; run `setup`. Hand safety stop is OFF.")
                self.source = RealVision(cfg, cam, calib, tracker)
                self.source.calib = calib
                if calib.has_table and calib.marker_px:
                    obs = self.source.read(2.0)
                    if obs is not None and obs.markers and calib.camera_moved(obs.markers):
                        print("WARNING: the camera or board moved since calibration. Redo calib-table.")
        if need_arm:
            from .arm import make_arm
            self.arm = make_arm(cfg, world=self.world, clock=self.clock).connect()
            self.arm.start()
        if need_body:
            self.body = load_body(cfg, self)

    def close(self):
        if self.arm:
            try:
                if not self.cfg["use_sim"]:
                    self.arm.park_and_detach()
            except Exception:
                pass
            self.arm.close()
        if self.world:
            self.world.stop()
        elif self.source is not None:
            self.source.close()


def load_body(cfg, stack=None):
    from .body_model import BodyModel
    if not cfg["use_sim"] and C.path("kinematic").exists():
        from .kinematics import KinematicBody
        return KinematicBody.load(cfg)
    p = C.body_path(cfg)
    if p.exists():
        return BodyModel.load(p)
    if cfg["use_sim"] and stack is not None and stack.arm is not None:
        print("No simulator body model yet: babbling and training one now (about a minute).")
        speed = stack.clock.speed
        stack.clock.set_speed(40)              # babble the simulated arm fast...
        try:
            return babble_and_train(cfg, stack, n=cfg["babble_samples"])
        finally:
            stack.clock.set_speed(speed)       # ...then run the UI at the speed asked for
    sys.exit(f"No body model at {p}. Run `babble` then `train-body` first.")


def babble_and_train(cfg, st, n):
    from . import body_model as bm
    out = C.babble_path(cfg)
    t0 = time.time()

    def prog(have, total, in_area, z=None):
        if have % 50 == 0 or have == total:
            print(f"  babble {have}/{total}  (claw pointing down in the work area: {in_area})"
                  f"  {time.time() - t0:.0f}s", flush=True)

    bm.babble(st.arm, st.source, cfg, n=n, out_path=out, progress=prog)
    P, Y = bm.load_samples(out)
    body, err = bm.train(P, Y, cfg)
    body.save(C.body_path(cfg))
    print(f"Body model: {len(P)} samples, held-out error {err:.2f} cm (target under 1 cm)")
    return body


# ===================================================================== commands
def cmd_setup(cfg, a):
    d = C.DATA_DIR
    d.mkdir(exist_ok=True)
    if not C.path("config").exists():
        C.save(cfg)
        print(f"wrote {C.path('config')}")
    cat_path = C.path("config").parent / "blocks.json"
    if not cat_path.exists():
        Catalog.load().save()
        print(f"wrote {cat_path} (edit it with your measured blocks)")
    ok = True
    for mod in ("numpy", "cv2", "serial", "torch", "mediapipe"):
        try:
            m = __import__(mod)
            print(f"  ok   {mod} {getattr(m, '__version__', '')}")
        except Exception as e:
            ok = False
            print(f"  FAIL {mod}: {e}")
    try:
        import cv2
        cv2.aruco.getPredefinedDictionary
        print("  ok   OpenCV ArUco (contrib build)")
    except AttributeError:
        ok = False
        print("  FAIL OpenCV has no ArUco: `pip uninstall -y opencv-python` then reinstall opencv-contrib-python")
    hm = C.path("hand_model")
    if not hm.exists():
        try:
            import urllib.request
            print("  downloading MediaPipe hand model...")
            urllib.request.urlretrieve(HAND_MODEL_URL, hm)
        except Exception as e:
            ok = False
            print(f"  FAIL hand model download: {e}\n       Download it from {HAND_MODEL_URL} into {hm}")
    print(f"  {'ok' if hm.exists() else 'MISSING'}   hand model {hm}")
    amb = Catalog.load().ambiguities()
    for x, y, cols in amb:
        print(f"  NOTE the camera can't tell {x} from {y} in {', '.join(cols)}: give them different colors "
              "or separate supply spots")
    print("setup OK" if ok else "setup has problems (see above)")


def cmd_markers(cfg, a):
    from .calibration import make_marker_sheets
    out = C.path("markers")
    files = make_marker_sheets(cfg, out)
    print("Print at 100% scale (no 'fit to page'), then measure each marker with a ruler:")
    for f in files:
        print("  ", f)


def cmd_check(cfg, a):
    from .arm import find_port
    if not cfg["use_sim"]:
        print("Uno port:", find_port() or "not found")
    st = Stack(cfg, need_arm=True, need_vision=True, hands=False)
    try:
        print("Uno replied OK sidekick 1. Reports for 5 s:")
        t_end = st.clock.time() + 5
        while st.clock.time() < t_end:
            print(f"  force {st.arm.force}  battery {st.arm.battery_v and round(st.arm.battery_v, 2)} V  "
                  f"moving {st.arm.moving}  attached {st.arm.attached}")
            st.clock.sleep(1.0)
        if st.source is not None:
            n, t0 = 0, time.monotonic()
            while time.monotonic() - t0 < 3:
                if st.source.read(1.0) is not None:
                    n += 1
            print(f"camera: {n / 3:.1f} frames/s")
    finally:
        st.close()


def cmd_jog(cfg, a):
    st = Stack(cfg, need_arm=True, need_vision=False)
    arm = st.arm
    names = ["base", "shoulder", "elbow", "wrist pitch", "wrist roll", "gripper"]
    print(__doc_jog__)
    try:
        while True:
            print("now:", " ".join(f"J{i}={p}" for i, p in enumerate(arm.targets)))
            parts = input("> ").strip().split()
            if not parts:
                continue
            c = parts[0].lower()
            try:
                if c in ("q", "quit"):
                    break
                elif c.isdigit() and len(parts) == 2:
                    j, v = int(c), parts[1]
                    val = arm.targets[j] + int(v) if v[0] in "+-" else int(v)
                    lo, hi = cfg["hard_min"], cfg["hard_max"]
                    t = list(arm.targets)
                    t[j] = max(lo, min(hi, val))
                    arm._send("C %d %d %d" % (j, lo, hi))   # jog may explore past the saved limits
                    arm._send("J " + " ".join(str(x) for x in t))
                    arm.targets = t
                elif c in ("min", "max") and len(parts) == 2:
                    j = int(parts[1])
                    margin = 40 if c == "min" else -40
                    cfg["joint_" + c][j] = int(arm.targets[j] + margin)
                    print(f"  {names[j]} {c} = {cfg['joint_' + c][j]} (40 us inside where it is now)")
                elif c == "save" and len(parts) == 2:
                    what = parts[1].lower()
                    if what in ("home", "park", "ready"):
                        cfg[what] = list(arm.targets)
                    elif what == "open":
                        cfg["claw_open"] = arm.targets[5]
                    elif what == "closed":
                        cfg["claw_closed"] = arm.targets[5]
                    else:
                        print("  save home | park | ready | open | closed")
                        continue
                    print(f"  saved {what}")
                elif c == "speed" and len(parts) == 2:
                    arm.speed(int(parts[1]))
                elif c == "attach":
                    arm._send("A")
                elif c == "detach":
                    arm.detach()
                elif c == "write":
                    C.save(cfg)
                    print(f"  wrote {C.path('config')}")
                else:
                    print("  ?  type 'help' for commands" if c != "help" else __doc_jog__)
            except (ValueError, IndexError):
                print("  bad command")
    finally:
        C.save(cfg)
        print(f"config saved to {C.path('config')}")
        st.close()


__doc_jog__ = """Jog: move one joint at a time and save limits and poses.
  <joint> <us>      absolute pulse, e.g. `1 1600`      joints: 0 base 1 shoulder 2 elbow
  <joint> +<us>     relative, e.g. `2 +50` or `2 -50`           3 wrist pitch 4 wrist roll 5 gripper
  min <joint>       save the current pulse as that joint's min (40 us inside)
  max <joint>       save as max
  save home|park|ready|open|closed     save named poses (ready = claw pointing down
                                       above the middle of the board, marker visible)
  speed <n>         step size 1-30 us per tick      attach / detach      write      q
Keep one hand on the battery switch. Move slowly near the table and end stops."""


def cmd_calib_lens(cfg, a):
    import cv2
    from .calibration import Calibration
    from .camera import Camera
    cam = Camera.from_config(cfg)
    calib = Calibration.load()
    nx, ny = cfg["chessboard_inner"]
    shots = []
    print("Hold the chessboard in view at different angles and distances.\n"
          "SPACE = capture (when corners show), C = calibrate (15+ captures), Q = quit")
    try:
        while True:
            frame, _ = cam.read()
            if frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ok, corners = cv2.findChessboardCorners(gray, (nx, ny), cv2.CALIB_CB_FAST_CHECK)
            show = frame.copy()
            if ok:
                cv2.drawChessboardCorners(show, (nx, ny), corners, ok)
            cv2.putText(show, f"captures: {len(shots)}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 200, 0), 2)
            cv2.imshow("calib-lens", show)
            k = cv2.waitKey(1) & 0xFF
            if k == ord(" ") and ok:
                shots.append(frame)
            elif k == ord("c"):
                err, n = calib.calibrate_lens(shots, (nx, ny), cfg["chessboard_square"])
                calib.save()
                print(f"lens calibrated from {n} views, reprojection error {err:.3f} px (good: under 0.5)")
                break
            elif k == ord("q"):
                break
    finally:
        cam.close()
        cv2.destroyAllWindows()


def cmd_calib_table(cfg, a):
    import cv2
    from .calibration import Calibration, detect_markers
    from .camera import Camera
    cam = Camera.from_config(cfg)
    calib = Calibration.load()
    if not calib.has_lens:
        print("No lens calibration; using a rough default (run calib-lens for better accuracy).")
        calib.default_lens(*cam.size())
    try:
        # many frames, median corners per marker: one blurry frame can't drop or skew a marker
        seen = {}
        for _ in range(30):
            frame = cam.read()[0]
            if frame is not None:
                for mid, c in detect_markers(frame).items():
                    seen.setdefault(mid, []).append(np.asarray(c, np.float64))
        markers = {mid: np.median(cs, axis=0) for mid, cs in seen.items() if len(cs) >= 5}
        want = sorted(int(k) for k in cfg["layout"]["markers"])
        missing = [m for m in want if m not in markers]
        if missing:
            print(f"WARNING: marker(s) {missing} not seen well. Check they're uncovered, flat and not in glare.")
        if a.height:
            f = calib.lens_from_height(markers, cfg, cam.size(), a.height)
            print(f"lens set from your measured height {a.height} cm (focal length {f:.0f} px)")
        res = calib.calibrate_table(markers, cfg)
        calib.save()
        print(f"table pose from markers {res['used']}: error {res['error_px']:.2f} px (good: under 1.5), "
              f"camera {res['height']:.1f} cm above the board (expect about 60)")
        print("Ruler check: move the mouse over the image; the window title shows table x, y (cm). Q to quit.")
        pos = {"p": None}
        cv2.namedWindow("calib-table")
        cv2.setMouseCallback("calib-table", lambda e, x, y, f, p: pos.update(p=(x, y)))
        while True:
            frame, _ = cam.read()
            if frame is None:
                continue
            for x, y in cfg["layout"]["markers"].values():
                cv2.circle(frame, tuple(int(v) for v in calib.table_to_pixel(x, y)), 6, (0, 200, 0), 2)
            if pos["p"]:
                tx, ty = calib.pixel_to_table(*pos["p"], 0.0)
                cv2.putText(frame, f"x {tx:.1f}  y {ty:.1f} cm", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1,
                            (0, 0, 255), 2)
            cv2.imshow("calib-table", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cam.close()
        cv2.destroyAllWindows()


def cmd_tune_colors(cfg, a):
    import cv2
    from .camera import Camera
    from .perception import color_mask
    cam = Camera.from_config(cfg)
    colors = list(cfg["colors"])
    idx = 0
    win = "tune-colors"
    cv2.namedWindow(win)

    def load_bars():
        lo, hi = cfg["colors"][colors[idx]][-1]
        for n, v, mx in (("H lo", lo[0], 179), ("H hi", hi[0], 179), ("S lo", lo[1], 255), ("S hi", hi[1], 255),
                         ("V lo", lo[2], 255), ("V hi", hi[2], 255)):
            cv2.createTrackbar(n, win, int(v), mx, lambda _: None)
            cv2.setTrackbarPos(n, win, int(v))
    load_bars()
    print("N = next color, S = save, Q = quit. Red has two ranges; the sliders edit the last one.")
    try:
        while True:
            frame, _ = cam.read()
            if frame is None:
                continue
            g = lambda n: cv2.getTrackbarPos(n, win)
            rng = [[g("H lo"), g("S lo"), g("V lo")], [g("H hi"), g("S hi"), g("V hi")]]
            cfg["colors"][colors[idx]][-1] = rng
            hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)
            mask = color_mask(hsv, cfg["colors"][colors[idx]])
            show = cv2.bitwise_and(frame, frame, mask=mask)
            cv2.putText(show, colors[idx], (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            cv2.imshow(win, cv2.resize(show, (960, 540)))
            k = cv2.waitKey(1) & 0xFF
            if k == ord("n"):
                idx = (idx + 1) % len(colors)
                load_bars()
            elif k == ord("s"):
                C.save(cfg)
                print("saved colors to config")
            elif k == ord("q"):
                break
    finally:
        cam.close()
        cv2.destroyAllWindows()


def cmd_view(cfg, a):
    import cv2
    from .builder import Builder
    from .overlay import render
    st = Stack(cfg, need_arm=cfg["use_sim"], need_body=False, hands=True, speed=a.speed)
    dummy_body = _NullBody()
    b = Builder(cfg, st.catalog, st.source, st.arm or _NullArm(st.clock), dummy_body)
    pos = {"p": None}
    cv2.namedWindow("view")
    cv2.setMouseCallback("view", lambda e, x, y, f, p: pos.update(p=(x, y)))
    try:
        while True:
            img = render(b, cfg, st.catalog)
            calib = getattr(st.source, "calib", None)
            if pos["p"] and calib is not None and calib.has_table:
                tx, ty = calib.pixel_to_table(*pos["p"], 0.0)
                cv2.putText(img, f"x {tx:.1f} y {ty:.1f}", (10, img.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (0, 0, 255), 2)
            cv2.imshow("view", img)
            if cv2.waitKey(30) & 0xFF == ord("q"):
                break
    finally:
        b.close()
        st.close()
        cv2.destroyAllWindows()


class _NullBody:
    def solve(self, t, **k):
        return {"reachable": False, "error": 99, "pulses": [1500] * 4, "down": 0, "pred": [0, 0, 0, 0]}

    def reachable(self, x, y):
        return False


class _NullArm:
    moving = False

    def __init__(self, clock):
        self.clock = clock

    def stop(self):
        pass

    def led(self, n):
        pass


def cmd_babble(cfg, a):
    from . import body_model as bm
    st = Stack(cfg, need_arm=True, hands=False, speed=a.speed or (40 if cfg["use_sim"] else None))
    try:
        if not cfg["use_sim"]:
            print("Babbling moves the arm randomly for 15-20 min. Keep a hand on the battery switch.\n"
                  "Ctrl+C stops; running it again resumes.")
        out = C.babble_path(cfg)
        t0 = time.time()
        bm.babble(st.arm, st.source, cfg, n=a.n or cfg["babble_samples"], out_path=out,
                  progress=lambda h, n, ia, z: print(f"  {h}/{n}  usable (claw down, in area): {ia}  "
                                                     f"fingertip z {z:.1f} cm  {time.time() - t0:.0f}s",
                                                     flush=True))
    except KeyboardInterrupt:
        print("stopped; run babble again to continue")
    finally:
        st.close()


def cmd_train_body(cfg, a):
    from . import body_model as bm
    P, Y = bm.load_samples(C.babble_path(cfg))
    print(f"training on {len(P)} samples...")
    body, err = bm.train(P, Y, cfg)
    p = body.save(C.body_path(cfg))
    print(f"held-out position error {err:.2f} cm (target under 1 cm). Saved {p}")


def cmd_reach(cfg, a):
    from .body_model import BodyModel
    body = BodyModel.load(C.body_path(cfg))
    lay = cfg["layout"]
    print("Reachable fingertip positions (# = yes) at the grasp height of a 3 cm block on the table,\n"
          "and 4 cm higher. Columns x = 0..50, rows y from back (top) to front. B = build strip, S = supply.")
    for z in (cfg.grasp_z(0, 3.0), cfg.grasp_z(0, 3.0) + 4):
        print(f"\nfingertip z = {z:.1f} cm")
        for y in range(int(lay["work_area"][1]), -1, -2):
            row = ""
            for x in range(0, int(lay["work_area"][0]) + 1, 2):
                ok = body.solve([x, y, z], steps=80)["reachable"]
                ch = "#" if ok else "."
                if cfg.in_build(x, y):
                    ch = "B" if ok else "b"
                elif cfg.in_supply(x, y):
                    ch = "S" if ok else "s"
                row += ch
            print(f"{y:3d} {row}", flush=True)
    print("\nLowercase b/s = a build or supply spot the arm can't reach. Move layout.build_area / "
          "layout.supply in config.json onto the # area.")


def cmd_goto_test(cfg, a):
    from .builder import Builder
    st = Stack(cfg, need_arm=True, need_body=True, speed=a.speed)
    b = Builder(cfg, st.catalog, st.source, st.arm, st.body)
    try:
        x0, x1, y0, y1 = cfg["layout"]["build_area"]
        z = cfg.grasp_z(0, 3.0) + 2
        errs = []
        for x in np.linspace(x0 + 1, x1 - 1, 3):
            for y in np.linspace(y0, y1, 3):
                r = b.motion.go_to(x, y, z, correct=True)
                m = b.read_claw()
                e = None if m is None else float(np.linalg.norm([m["x"] - x, m["y"] - y, m["z"] - z]))
                errs.append(e)
                print(f"  ({x:.1f}, {y:.1f}, {z:.1f}) {r}  error {'unseen' if e is None else f'{e * 10:.1f} mm'}")
        good = [e for e in errs if e is not None]
        if good:
            print(f"mean {np.mean(good) * 10:.1f} mm, worst {np.max(good) * 10:.1f} mm (target under 5 mm)")
        b.motion.home()
    finally:
        b.close()
        st.close()


def cmd_pick_test(cfg, a):
    """Pick a block from the supply and put it back down in the build strip, 10 times."""
    from .builder import Builder
    st = Stack(cfg, need_arm=True, need_body=True, speed=a.speed)
    feeder = st.world.person if st.world else None
    b = Builder(cfg, st.catalog, st.source, st.arm, st.body, feeder=feeder)
    ok = 0
    try:
        for k in range(a.n or 10):
            design = {"blocks": [{"type": "cube", "color": "red", "x": 8.5, "depth": 0, "rot": 0, "z_hint": 0}]}
            if st.world:
                st.world.clear_blocks()
            started, probs, _ = b.start_build(design)
            if not started:
                print(probs)
                break
            while b.busy():
                time.sleep(0.2)
            res = b.snapshot()["result"]
            ok += res == "done"
            print(f"  pick {k + 1}: {res}")
            if not st.world:
                input("  move the cube back to a supply zone, then press Enter")
        print(f"{ok}/{a.n or 10} picks succeeded")
    finally:
        b.close()
        st.close()


def cmd_presets(cfg, a):
    from . import presets
    from .body_model import BodyModel
    from .planner import plan
    cat = Catalog.load()
    p = C.body_path(cfg)
    body = BodyModel.load(p) if p.exists() else None
    if body is None:
        print("(no body model yet: checking shape and stability only, not reach)")
    for pr in presets.PRESETS:
        steps, probs = plan(pr, cfg, cat, body)
        errs = [x for x in probs if x["level"] == "error"]
        print(f"{'OK ' if not errs else 'NO '} {pr['id']:8s} {len(steps)} blocks  " +
              "; ".join(x["msg"] for x in probs))


def cmd_build(cfg, a):
    from . import presets
    from .builder import Builder
    design = json.load(open(a.target)) if a.target.endswith(".json") else presets.get(a.target)
    st = Stack(cfg, need_arm=True, need_body=True, speed=a.speed)
    if st.world:
        st.world.fill_supply(presets.needed(design))
    b = Builder(cfg, st.catalog, st.source, st.arm, st.body, feeder=st.world.person if st.world else None)
    try:
        ok, probs, _ = b.start_build(design)
        for p in probs:
            print(f"  {p['level']}: {p['msg']}")
        if not ok:
            return
        last = None
        while b.busy():
            s = b.snapshot()
            if s["action"] != last:
                print(" ", s["action"], flush=True)
                last = s["action"]
            time.sleep(0.2)
        print("result:", b.snapshot()["result"])
    except KeyboardInterrupt:
        b.stop_build()
    finally:
        b.close()
        st.close()


def cmd_ui(cfg, a):
    from .builder import Builder
    from .server import App, serve
    st = Stack(cfg, need_arm=True, need_body=True, speed=a.speed)
    feeder = st.world.person if (st.world and a.autofeed) else None
    b = Builder(cfg, st.catalog, st.source, st.arm, st.body, feeder=feeder)
    app = App(cfg, st.catalog, b, st.body, world=st.world)
    try:
        serve(app, port=a.port)
    finally:
        b.close()
        st.close()


def cmd_selftest(cfg, a):
    from .selftest import run
    sys.exit(0 if run(cfg, quick=a.quick) else 1)


def cmd_simtest(cfg, a):
    from .selftest import simtest
    sys.exit(0 if simtest(cfg, runs=a.n or 3) else 1)


from .perception import arm_heading   # noqa: E402


def cmd_claw(cfg, a):
    """Print where the camera thinks the fingertips are, twice a second (no arm moves).
    `claw --zero`: with the claw pointing straight down and its tips touching the
    paper, learn the marker's tilt bias and the marker-to-tip distance."""
    import numpy as np
    from .body_model import read_claw
    st = Stack(cfg, need_arm=False, hands=False)
    try:
        if a.zero:
            m = read_claw(st.source, 30, timeout=6.0, raw=True)
            if m is None:
                print("claw marker not seen; nothing saved")
                return
            n = np.array([m["nx"], m["ny"], m["down"]])
            n = n / np.linalg.norm(n)
            cfg["claw_normal_bias"] = [round(float(v), 4) for v in n]
            cfg["claw_normal_bias"].append(round(arm_heading(m["x"], m["y"], cfg["layout"]["base"]), 2))
            cfg["marker_to_fingertip"] = round(float(m["z"]), 2)     # tips on the paper: z = 0
            C.save(cfg)
            print(f"saved: claw_normal_bias {cfg['claw_normal_bias']} (tilt it measured: "
                  f"{np.degrees(np.arccos(min(1.0, n[2]))):.0f} deg), marker_to_fingertip {cfg['marker_to_fingertip']} cm")
            return
        print("Fingertip from the claw marker (cm). Touch the tips to the paper: z should read about 0. Ctrl+C quits.")
        while True:
            m = read_claw(st.source, 5, marker_to_fingertip=cfg["marker_to_fingertip"],
                          forward=cfg.get("marker_forward", 0.0), base=cfg["layout"]["base"],
                          bias=cfg.get("claw_normal_bias"))
            if m is None:
                print("  claw marker not seen", flush=True)
            else:
                print(f"  x {m['x']:6.1f}  y {m['y']:6.1f}  z {m['z']:5.1f}   down {m['down']:.2f}", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        st.close()


def _lengths(cfg):
    L = cfg.get("arm_lengths")
    if not L or len(L) != 4:
        sys.exit("Set arm_lengths [A, B, C, D] (cm) in sidekick_data/config.json first: table to shoulder "
                 "pivot, shoulder to elbow, elbow to wrist, wrist to the closed claw tips.")
    return [float(v) for v in L]


def cmd_touch(cfg, a):
    """Collect touch points for the kinematic model: jog the claw straight down until
    the tips touch the paper, then `save`. Spread 6-10 points over the area."""
    import json as _json
    from .body_model import read_claw
    _lengths(cfg)
    st = Stack(cfg, need_arm=True, hands=False)
    arm = st.arm
    out = C.path("touch")
    print(__doc_touch__)
    try:
        while True:
            n = len(open(out).readlines()) if out.exists() else 0
            print(f"[{n} points]  now:", " ".join(f"J{i}={p}" for i, p in enumerate(arm.targets)))
            parts = input("> ").strip().split()
            if not parts:
                continue
            c = parts[0].lower()
            try:
                if c in ("q", "quit"):
                    break
                elif c.isdigit() and len(parts) == 2:
                    j, v = int(c), parts[1]
                    val = arm.targets[j] + int(v) if v[0] in "+-" else int(v)
                    t = list(arm.targets)
                    t[j] = max(cfg["hard_min"], min(cfg["hard_max"], val))
                    arm._send("J " + " ".join(str(x) for x in t))
                    arm.targets = t
                elif c == "save":
                    h = float(parts[1]) if len(parts) > 1 else 0.0     # `save 2.5` = tips on a 2.5 cm block
                    m = _touch_tip(st.source, cfg, h)
                    if m is None:
                        print("  claw marker not seen; not saved (keep hands out of view)")
                        continue
                    pulses = arm.read_stable() if hasattr(arm, "read_stable") else None
                    pulses = pulses[:4] if pulses else None
                    if pulses is None:
                        pulses = list(arm.targets[:4])
                    with open(out, "a") as f:
                        f.write(_json.dumps(dict(m, p=pulses, h=h)) + "\n")
                    print(f"  saved point at x {m['x']:.1f}  y {m['y']:.1f}  (tips at height {h:g} cm)")
                elif c == "zero":
                    raw = read_claw(st.source, 30, timeout=6.0, raw=True)
                    if raw is None:
                        print("  claw marker not seen; nothing changed")
                        continue
                    nv = np.array([raw["nx"], raw["ny"], raw["down"]])
                    nv = nv / np.linalg.norm(nv)
                    cfg["claw_normal_bias"] = [round(float(v), 4) for v in nv]
                    cfg["claw_normal_bias"].append(round(arm_heading(raw["x"], raw["y"], cfg["layout"]["base"]), 2))
                    cfg["marker_to_fingertip"] = round(float(raw["z"]), 2)
                    C.save(cfg)
                    print(f"  zeroed: marker tilt bias {np.degrees(np.arccos(min(1.0, nv[2]))):.0f} deg, "
                          f"marker_to_fingertip {cfg['marker_to_fingertip']} cm. Now `save` this point.")
                elif c == "undo":
                    if out.exists():
                        lines = open(out).readlines()[:-1]
                        open(out, "w").writelines(lines)
                        print("  removed the last point")
                elif c == "clear":
                    out.unlink(missing_ok=True)
                    print("  all points removed")
                elif c == "fit":
                    _fit_arm(cfg)
                else:
                    print(__doc_touch__)
            except (ValueError, IndexError):
                print("  bad command")
    finally:
        st.close()


def _tip_from_px(calib, cfg, u, v, h, base):
    hit = calib.pixel_to_table(u, v, z=h + cfg["marker_to_fingertip"])
    if hit is None:
        return None
    x, y = hit
    fwd = cfg.get("marker_forward", 0.0)
    r = math.hypot(x - base[0], y - base[1])
    if fwd and r > 3.0:
        x, y = x - fwd * (x - base[0]) / r, y - fwd * (y - base[1]) / r
    return float(x), float(y)


def _touch_tip(source, cfg, h=0.0, n=15, timeout=4.0):
    """Fingertip x, y for a touch point. With the claw pointing straight down the
    marker centre sits marker_to_fingertip above the tips, so its pixel ray is cut
    at that height (no marker-tilt estimate involved, which is good to ~1 cm only),
    then marker_forward is taken off toward the base."""
    px, t_end = [], time.monotonic() + timeout
    while len(px) < n and time.monotonic() < t_end:
        obs = source.read(timeout=0.5)
        if obs is not None and obs.claw_px is not None:
            px.append(obs.claw_px)
    calib = getattr(source, "calib", None)
    if len(px) < max(2, n // 2) or calib is None:
        return None
    u, v = np.median(np.array(px, float), axis=0)
    hit = _tip_from_px(calib, cfg, u, v, h, cfg["layout"]["base"])
    if hit is None:
        return None
    return {"x": hit[0], "y": hit[1], "px": [float(u), float(v)]}


def _fit_arm(cfg):
    from .kinematics import default_params, fit, load_points
    pts = load_points()
    if len(pts) < 4:
        print(f"  need at least 4 touch points (have {len(pts)})")
        return None
    params = default_params(cfg, _lengths(cfg))
    calib = None
    if any("px" in q for q in pts):
        from .calibration import Calibration
        calib = Calibration.load()
    for _ in range(3 if calib else 1):
        if calib:      # the marker offset points away from the base: redo the tips with the fitted base
            for q in pts:
                if "px" in q:
                    hit = _tip_from_px(calib, cfg, q["px"][0], q["px"][1], q.get("h", 0.0),
                                       (params["bx"], params["by"]))
                    if hit:
                        q["x"], q["y"] = hit
        body, rms, worst, each = fit(params, pts, cfg["joint_min"], cfg["joint_max"])
        params = dict(params, bx=body.p["bx"], by=body.p["by"])
    body.save()
    p = body.p
    for i, (q, d) in enumerate(zip(pts, each)):
        flag = "   <-- off, check this one" if d > max(0.8, 2.5 * rms) else ""
        print(f"    point {i + 1}: J {' '.join(str(v) for v in q['p'])}  error {d * 10:.0f} mm{flag}")
    print(f"  fitted {len(pts)} points: average error {rms * 10:.1f} mm, worst {worst * 10:.1f} mm "
          f"(good: under 5 mm). Saved {C.path('kinematic')}")
    print(f"  offsets J0..J3 = {p['o0']:.0f} {p['o1']:.0f} {p['o2']:.0f} {p['o3']:.0f}, shoulder height "
          f"{p['A']:.1f} cm, base at ({p['bx']:.1f}, {p['by']:.1f}), turntable direction {p['s0']:+.0f}, "
          f"{p['k']:.2f} us/deg")
    return body


def cmd_fit_arm(cfg, a):
    _fit_arm(cfg)


__doc_touch__ = """Touch points: jog the claw STRAIGHT DOWN until the tips just touch the paper, then type save.
  <joint> <us> / <joint> +<us>   move (same as jog)      save    store this point
  save 2.5   store a point with the tips resting on top of something 2.5 cm tall
  zero   (first point only) claw straight down, tips touching: re-zero the camera's claw reading
  undo   remove the last point     clear   remove all     fit   fit the arm model     q   quit
Do 6-10 points spread over where the arm will build: left, right, near, far."""


COMMANDS = {
    "setup": cmd_setup, "markers": cmd_markers, "check": cmd_check, "jog": cmd_jog,
    "calib-lens": cmd_calib_lens, "calib-table": cmd_calib_table, "tune-colors": cmd_tune_colors,
    "view": cmd_view, "claw": cmd_claw, "touch": cmd_touch, "fit-arm": cmd_fit_arm, "babble": cmd_babble, "train-body": cmd_train_body, "reach": cmd_reach,
    "goto-test": cmd_goto_test, "pick-test": cmd_pick_test, "presets": cmd_presets, "build": cmd_build,
    "ui": cmd_ui, "selftest": cmd_selftest, "simtest": cmd_simtest,
}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sidekick", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("target", nargs="?", default="", help="preset id or design .json (build)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sim", action="store_true", help="use the simulator")
    g.add_argument("--real", action="store_true", help="use the real arm and camera")
    ap.add_argument("--speed", type=float, default=None, help="simulator speed multiplier")
    ap.add_argument("-n", type=int, default=None, help="count (samples, picks, runs)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-autofeed", dest="autofeed", action="store_false",
                    help="sim: don't have the simulated person bring blocks")
    ap.add_argument("--height", type=float, default=None,
                    help="calib-table: measured camera height in cm; sets the lens from it")
    ap.add_argument("--zero", action="store_true", help="claw: learn the claw marker's tilt bias (tips on the paper)")
    ap.add_argument("--quick", action="store_true", help="selftest: skip the slow simulator build")
    a = ap.parse_args(argv)
    over = {}
    if a.sim:
        over["use_sim"] = True
    if a.real:
        over["use_sim"] = False
    cfg = C.load(overrides=over)
    COMMANDS[a.command](cfg, a)


if __name__ == "__main__":
    main()

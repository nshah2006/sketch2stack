"""Level 2 simulator: a MuJoCo digital twin of the table.

Same wiring as sim.World (firmware emulator, flawed arm model, simulated
person), with two things made real:
  * blocks are rigid bodies (gravity, friction, stacking, toppling), so an
    unstable build actually falls over;
  * the camera is a rendered overhead image at the real camera's height and
    lens, and it goes through the real perception code: ArUco table
    calibration, claw marker pose, block outlines. Only the hand comes from
    the person model (MediaPipe needs a real-looking hand).

Rendering uses EGL. With the NVIDIA user-space libs on the path (see
`gl_libs` in config) it runs on the GPU, otherwise on the CPU (Mesa).
"""
import math
import os
import queue
import tempfile
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")

import cv2
import mujoco
import numpy as np

from .calibration import Calibration, detect_markers, marker_image
from .perception import Observation, detect_blocks
from .clock import SimClock
from .sim import FirmwareEmulator, World

# blue and purple sit mid-band in cfg["colors"] (hue 109 / 127; they were at 113 / 138,
# on or past the edge of the real-camera ranges, so purple blocks went undetected)
RGBA = {"red": (0.80, 0.10, 0.10), "blue": (0.10, 0.35, 0.80), "green": (0.10, 0.60, 0.20),
        "yellow": (0.95, 0.80, 0.10), "orange": (0.95, 0.45, 0.05), "purple": (0.28, 0.15, 0.70),
        "natural": (0.82, 0.64, 0.42)}
CAM_W, CAM_H, CAM_HFOV = 1280, 720, 70.0      # matches default_lens on the real webcam
VIEW_W, VIEW_H = 640, 400
SUB = 8                                       # physics substeps per 60 Hz world step
PARK = (5.0, 5.0)                             # m; unused block slots wait out here


def _quat_z_to(v):
    """Quaternion turning +z onto v."""
    v = np.asarray(v, float)
    v = v / (np.linalg.norm(v) + 1e-12)
    z = np.array([0.0, 0.0, 1.0])
    c = float(np.dot(z, v))
    if c < -0.999999:
        return np.array([0.0, 1.0, 0.0, 0.0])
    ax = np.cross(z, v)
    q = np.array([1.0 + c, *ax])
    return q / np.linalg.norm(q)


def _quat_frame(x_axis, z_axis):
    z = np.asarray(z_axis, float)
    z = z / np.linalg.norm(z)
    x = np.asarray(x_axis, float) - np.dot(x_axis, z) * z
    if np.linalg.norm(x) < 1e-6:
        x = np.cross([0, 1, 0], z)
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.column_stack([x, y, z]).ravel())
    return q


def _yaw_quat(deg):
    a = math.radians(deg) / 2
    return np.array([math.cos(a), 0.0, 0.0, math.sin(a)])


class TwinWorld(World):
    def __init__(self, cfg, catalog=None, speed=None, seed=None, camera_fps=20, reach_rate=0.0,
                 view_fps=5):
        super().__init__(cfg, catalog=catalog, speed=speed, seed=seed, camera_fps=camera_fps,
                         reach_rate=reach_rate)
        self.view_fps = view_fps
        self._next_view = 0.0
        self.view_jpeg = None                 # latest perspective frame (for the fleet viewer)
        self._tex_dir = Path(tempfile.mkdtemp(prefix="twin_tex_"))
        self._build_model()
        self._renderer = self._view_renderer = None
        self.calib = None
        self.toppled = set()                  # ids of blocks that are no longer upright
        self.frames_rendered = 0
        self._rec = None                      # demo recording (fleet.py -> LeRobot dataset)
        self.bump_rate = 0.0                  # chance the person bumps a block the claw is coming for
        self.bumps = 0
        self._bump_checked = {}               # block id -> trigger distance (cm), or None once decided
        # building the scene takes a moment: restart time so the world doesn't
        # start out seconds behind its clock (the arm would miss its handshake)
        self.clock = SimClock(self.clock.speed)
        self.emu = FirmwareEmulator(self.clock)
        self._t = self._next_frame = self.clock.time()

    # ================================================================= scene
    def _marker_png(self, mid, border):
        side = 600
        img = marker_image(mid, side)
        pad = int(side * border)
        img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
        p = self._tex_dir / f"m{mid}.png"
        cv2.imwrite(str(p), cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
        return p

    def _block_geoms(self, tid, w, d, h, name):
        """MJCF geoms (cm -> m) for one block, centered on its bounding box."""
        shape = self.catalog.types[tid]["shape"]
        W, D, H = w / 100, d / 100, h / 100
        g = f'class="blk" material="{name}"'
        if shape == "cylinder":
            return f'<geom type="cylinder" size="{D / 2} {H / 2}" {g}/>'
        if shape == "arch":
            leg, top = W * 0.25, H * 0.35
            return (f'<geom type="box" size="{leg / 2} {D / 2} {H / 2}" pos="{-(W - leg) / 2} 0 0" {g}/>'
                    f'<geom type="box" size="{leg / 2} {D / 2} {H / 2}" pos="{(W - leg) / 2} 0 0" {g}/>'
                    f'<geom type="box" size="{W / 2} {D / 2} {top / 2}" pos="0 0 {(H - top) / 2}" {g}/>')
        if shape == "roof":
            return f'<geom type="mesh" mesh="roof_{tid}" {g}/>'
        return f'<geom type="box" size="{W / 2} {D / 2} {H / 2}" {g}/>'

    def _build_model(self):
        cfg, cat = self.cfg, self.catalog
        lay = cfg["layout"]
        aw, ad = lay["work_area"]
        border = 0.15
        assets, bodies = [], []
        # table markers (printed top edge away from the human)
        s = cfg["table_marker_size"]
        for mid_s, (cx, cy) in lay["markers"].items():
            mid = int(mid_s)
            assets.append(f'<texture name="t{mid}" type="2d" file="{self._marker_png(mid, border)}"/>'
                          f'<material name="t{mid}" texture="t{mid}"/>')
            half = s * (1 + 2 * border) / 200
            bodies.append(f'<geom type="box" size="{half} {half} 0.0002" pos="{cx / 100} {cy / 100} 0.0002" '
                          f'material="t{mid}" contype="0" conaffinity="0"/>')
        cid = lay["claw_marker_id"]
        assets.append(f'<texture name="claw" type="2d" file="{self._marker_png(cid, border)}"/>'
                      f'<material name="claw" texture="claw"/>')
        # one material per color, roof meshes, then a pool of block slots per (type, pose)
        for c, (r, g, b) in RGBA.items():
            assets.append(f'<material name="c_{c}" rgba="{r} {g} {b} 1" specular="0.1"/>')
        self._slots = {}                      # (tid, pose) -> [slot index]
        self._slot_info = []                  # slot -> (tid, pose, body name)
        for tid, t in cat.types.items():
            if t["shape"] == "roof":
                W, D, H = (v / 100 for v in t["size"])
                v = [(-W / 2, -D / 2, -H / 2), (W / 2, -D / 2, -H / 2), (0, -D / 2, H / 2),
                     (-W / 2, D / 2, -H / 2), (W / 2, D / 2, -H / 2), (0, D / 2, H / 2)]
                assets.append(f'<mesh name="roof_{tid}" vertex="{" ".join(f"{a} {b} {c}" for a, b, c in v)}"/>')
            n_owned = max(1, cat.count(tid))
            for pose in range(len(cat.poses(tid))):
                w, d, h = cat.size(tid, pose)
                for _ in range(min(n_owned, 30) if pose == 0 else min(n_owned, 6)):
                    k = len(self._slot_info)
                    name = f"b{k}"
                    assets.append(f'<material name="{name}" rgba="1 1 1 1" specular="0.1"/>')
                    bodies.append(f'<body name="{name}" pos="{PARK[0] + 0.1 * k} {PARK[1]} 0.1">'
                                  f'<freejoint/>{self._block_geoms(tid, w, d, h, name)}</body>')
                    self._slots.setdefault((tid, pose), []).append(k)
                    self._slot_info.append((tid, pose, name))
        g = cfg["sim_arm"]
        L = {"upper": g["upper"], "fore": g["fore"] * 0.6}     # forearm drawn short of the wrist: keeps the claw marker in view
        arm = [f'<body name="base_col" mocap="true"><geom type="cylinder" size="0.035 {g["shoulder_height"] / 200}" '
               f'material="arm_dark" class="vis"/></body>']
        bulk = float(cfg.get("twin_arm_bulk", 1.0))    # 0 = thin rods, 1 = like the real kit (servos + brackets)
        if bulk > 0:                                    # servo bodies at shoulder and elbow block the camera too
            for nm in ("servo_sh", "servo_el"):
                arm.append(f'<body name="{nm}" mocap="true"><geom type="box" size="{0.02 * bulk} {0.012 * bulk} {0.022 * bulk}" '
                           f'material="arm_dark" class="vis"/></body>')
        for link, length in L.items():
            if bulk > 0:                                # flat U-brackets, ~3 cm wide on the upper arm
                w = (0.015 if link == "upper" else 0.012) * bulk
                arm.append(f'<body name="{link}" mocap="true"><geom type="box" size="{w} 0.004 {length / 200}" '
                           f'material="arm" class="vis"/></body>')
                continue
            rad = 0.009 if link == "upper" else 0.006     # thin like the real brackets
            arm.append(f'<body name="{link}" mocap="true"><geom type="capsule" size="{rad} {length / 200}" '
                       f'material="arm" class="vis"/></body>')
        arm.append('<body name="finger_a" mocap="true"><geom type="box" size="0.004 0.006 0.012" material="arm_dark" class="vis"/></body>'
                   '<body name="finger_b" mocap="true"><geom type="box" size="0.004 0.006 0.012" material="arm_dark" class="vis"/></body>')
        half = cfg["claw_marker_size"] * (1 + 2 * border) / 200
        arm.append(f'<body name="claw_plate" mocap="true"><geom type="box" size="{half} {half} 0.001" '
                   f'material="claw" class="vis"/></body>')
        person = ('<body name="hand" mocap="true"><geom type="ellipsoid" size="0.045 0.035 0.015" material="skin" class="vis"/></body>'
                  '<body name="forearm" mocap="true"><geom type="capsule" size="0.03 0.12" material="skin" class="vis"/></body>'
                  '<body name="torso" mocap="true" pos="0.25 -0.45 0.2"><geom type="box" size="0.18 0.1 0.3" material="shirt" class="vis"/>'
                  '<geom type="sphere" size="0.1" pos="0 0 0.42" material="skin" class="vis"/></body>')
        H = cfg.get("twin_camera_height", 60.0) / 100
        eye, look = np.array([aw / 100 + 0.12, -0.22, 0.38]), np.array([aw / 200, ad / 200 + 0.06, 0.03])
        fwd = (look - eye) / np.linalg.norm(look - eye)
        right = np.cross(fwd, [0, 0, 1])
        right /= np.linalg.norm(right)
        xyax = np.round(np.concatenate([right, np.cross(right, fwd)]), 4)
        eye = np.round(eye, 4)
        fovy = 2 * math.degrees(math.atan(math.tan(math.radians(CAM_HFOV / 2)) * CAM_H / CAM_W))
        xml = f"""<mujoco model="sidekick_twin">
  <option timestep="{self.DT / SUB}" gravity="0 0 -9.81" cone="elliptic" impratio="10"/>
  <visual><global offwidth="{CAM_W}" offheight="{CAM_W}"/><quality shadowsize="2048"/>
    <headlight ambient="0.45 0.45 0.45" diffuse="0.35 0.35 0.35" specular="0 0 0"/></visual>
  <default>
    <default class="blk"><geom friction="0.6 0.005 0.0001" density="600" solref="0.004 1" condim="4"/></default>
    <default class="vis"><geom contype="0" conaffinity="0"/></default>
  </default>
  <asset>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.32 0.35 0.40" rgb2="0.08 0.09 0.11" width="256" height="256"/>
    <material name="board" rgba="0.96 0.96 0.95 1" specular="0"/>
    <material name="tabletop" rgba="0.55 0.45 0.35 1"/>
    <material name="arm" rgba="0.72 0.73 0.75 1" specular="0.5"/>
    <material name="arm_dark" rgba="0.12 0.12 0.13 1"/>
    <material name="skin" rgba="0.87 0.66 0.53 1"/>
    <material name="shirt" rgba="0.2 0.3 0.45 1"/>
    {"".join(assets)}
  </asset>
  <worldbody>
    <light pos="{aw / 200} {ad / 200} 1.2" dir="0 0 -1" diffuse="0.5 0.5 0.5" castshadow="true"/>
    <geom name="table" type="box" size="0.6 0.45 0.01" pos="{aw / 200} {ad / 200} -0.0105" material="tabletop"/>
    <geom name="board" type="box" size="{aw / 200 + 0.04} {ad / 200 + 0.04} 0.0005" pos="{aw / 200} {ad / 200} -0.0005"
          material="board" friction="0.5 0.005 0.0001"/>
    <camera name="top" pos="{aw / 200} {ad / 200} {H}" fovy="{fovy}"/>
    <camera name="view" pos="{' '.join(map(str, eye))}" xyaxes="{' '.join(map(str, xyax))}" fovy="45"/>
    {"".join(arm)}{person}{"".join(bodies)}
  </worldbody>
</mujoco>"""
        self.m = mujoco.MjModel.from_xml_string(xml)
        self.d = mujoco.MjData(self.m)
        self._fovy = fovy
        mid = lambda n: self.m.body(n).mocapid[0]
        self._servos = ["servo_sh", "servo_el"] if float(self.cfg.get("twin_arm_bulk", 1.0)) > 0 else []
        self._mocap = {n: mid(n) for n in ("base_col", "upper", "fore", "finger_a", "finger_b", *self._servos,
                                           "claw_plate", "hand", "forearm", "torso")}
        self._slot_body = [self.m.body(n).id for _, _, n in self._slot_info]
        self._slot_qadr = [self.m.jnt_qposadr[self.m.body_jntadr[b]] for b in self._slot_body]
        self._slot_vadr = [self.m.jnt_dofadr[self.m.body_jntadr[b]] for b in self._slot_body]
        self._slot_geoms = [[gi for gi in range(self.m.ngeom) if self.m.geom_bodyid[gi] == b]
                            for b in self._slot_body]
        self._slot_mat = [self.m.material(n).id for _, _, n in self._slot_info]
        self._slot_of = {}                    # block id -> slot
        self._free = {k: list(v) for k, v in self._slots.items()}
        for k in range(len(self._slot_info)):
            self._park(k)
        mujoco.mj_forward(self.m, self.d)

    # ================================================================= blocks <-> bodies
    def _set_collide(self, k, on):
        for gi in self._slot_geoms[k]:
            self.m.geom_contype[gi] = self.m.geom_conaffinity[gi] = 1 if on else 0

    def _park(self, k):
        a, v = self._slot_qadr[k], self._slot_vadr[k]
        self.d.qpos[a:a + 7] = [PARK[0] + 0.1 * k, PARK[1], 0.1, 1, 0, 0, 0]
        self.d.qvel[v:v + 6] = 0
        self._set_collide(k, False)

    def _place(self, k, b, z_center_cm):
        a, v = self._slot_qadr[k], self._slot_vadr[k]
        self.d.qpos[a:a + 3] = [b.x / 100, b.y / 100, z_center_cm / 100]
        self.d.qpos[a + 3:a + 7] = _yaw_quat(b.yaw)
        self.d.qvel[v:v + 6] = 0

    def add_block(self, tid, color, x, y, yaw=0.0, z=0.0, pose=0):
        with self.lock:
            b = super().add_block(tid, color, x, y, yaw=yaw, z=z, pose=pose)
            free = self._free.get((tid, int(pose))) or self._free.get((tid, 0))
            if not free:
                raise RuntimeError(f"twin: no free body slot for {tid} pose {pose}")
            k = free.pop()
            self._slot_of[b.id] = k
            self.m.mat_rgba[self._slot_mat[k]][:3] = RGBA.get(color, RGBA["natural"])
            self._set_collide(k, True)
            self._place(k, b, b.z + b.h / 2)
        return b

    def _release(self, b, finger_z):
        k = self._slot_of.get(b.id)
        if k is None:
            return super()._release(b, finger_z)
        b.z = finger_z - b.h / 2              # let go where it is; physics does the rest
        self._place(k, b, finger_z)
        self._set_collide(k, True)

    # ================================================================= stepping
    def _physics(self, pose):
        m, d = self.m, self.d
        live = {b.id for b in self.blocks}
        for bid in [i for i in self._slot_of if i not in live]:     # removed by the person / clear
            k = self._slot_of.pop(bid)
            self._park(k)
            tid, p, _ = self._slot_info[k]
            self._free.setdefault((tid, p), []).append(k)
        fx, fy, fz = pose["finger"]
        for b in self.blocks:
            if b.held:
                k = self._slot_of.get(b.id)
                if k is not None:
                    self._set_collide(k, False)
                    self._place(k, b, fz)
        self._pose_arm(pose)
        if self.bump_rate:
            self._maybe_bump(fx, fy, fz)
        for _ in range(SUB):
            mujoco.mj_step(m, d)
            for b in self.blocks:              # held blocks ride with the claw, unparked slots stay put
                if b.held and b.id in self._slot_of:
                    v = self._slot_vadr[self._slot_of[b.id]]
                    d.qvel[v:v + 6] = 0
        for b in self.blocks:
            k = self._slot_of.get(b.id)
            if k is None or b.held:
                continue
            a = self._slot_qadr[k]
            x, y, zc = d.qpos[a:a + 3] * 100
            w, qx, qy, qz = d.qpos[a + 3:a + 7]
            up = 1 - 2 * (qx * qx + qy * qy)               # z of the block's up axis
            b.x, b.y = float(x), float(y)
            b.z = float(zc - b.h / 2)
            b.yaw = float((math.degrees(math.atan2(2 * (w * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))) + 90) % 180 - 90)
            if up < 0.9:
                self.toppled.add(b.id)
            else:
                self.toppled.discard(b.id)

    def _maybe_bump(self, fx, fy, fz):
        """Once per loose block, when the claw first comes within a random 5-12 cm of
        it from above, the person may bump it 2.5-4 cm and twist it a little."""
        for b in self.blocks:
            if b.held or self.cfg.in_build(b.x, b.y) or b.id in self.toppled:
                continue
            trig = self._bump_checked.setdefault(b.id, float(self.rng.uniform(5, 12)))
            if trig is None or math.hypot(b.x - fx, b.y - fy) > trig or fz < b.z + b.h + 1.5:
                continue
            self._bump_checked[b.id] = None
            if self.rng.random() >= self.bump_rate:
                continue
            for _ in range(10):
                a = self.rng.uniform(0, 2 * math.pi)
                r = self.rng.uniform(2.5, 4.0)
                nx, ny = b.x + r * math.cos(a), b.y + r * math.sin(a)
                if self.cfg.in_build(nx, ny, 2.0) or not self.cfg.in_work_area(nx, ny):
                    continue
                if any(o is not b and math.hypot(o.x - nx, o.y - ny) < 4.5 for o in self.blocks):
                    continue
                if math.hypot(nx - fx, ny - fy) < 3.0:
                    continue                   # not into the claw
                b.x, b.y = float(nx), float(ny)
                b.yaw = float(((b.yaw + self.rng.uniform(-25, 25)) + 90) % 180 - 90)
                k = self._slot_of.get(b.id)
                if k is not None:
                    self._place(k, b, b.z + b.h / 2)
                self.bumps += 1
                break

    def _pose_arm(self, pose):
        m, d, mc = self.m, self.d, self._mocap
        base = np.array([*self.cfg["layout"]["base"], 0.0])
        h0 = self.cfg["sim_arm"]["shoulder_height"]
        sh = base + [0, 0, h0]
        cm = lambda p: np.asarray(p, float) / 100

        heading = np.array([*(np.asarray(pose["wrist"][:2]) - base[:2]), 0.0])
        side = np.cross(heading, [0, 0, 1]) if np.linalg.norm(heading[:2]) > 1e-6 else np.array([1.0, 0, 0])

        def seg(name, a, b):
            d.mocap_pos[mc[name]] = cm((np.asarray(a) + np.asarray(b)) / 2)
            d.mocap_quat[mc[name]] = _quat_frame(side, np.asarray(b) - np.asarray(a))   # flat side stays horizontal-ish

        for nm, at in (("servo_sh", sh), ("servo_el", pose["elbow"])):
            if nm in mc:
                d.mocap_pos[mc[nm]] = cm(at)
                d.mocap_quat[mc[nm]] = _quat_frame(side, [0, 0, 1])

        d.mocap_pos[mc["base_col"]] = cm(base + [0, 0, h0 / 2])
        seg("upper", sh, pose["elbow"])
        el, wr = np.asarray(pose["elbow"], float), np.asarray(pose["wrist"], float)
        seg("fore", el, el + (wr - el) * 0.6)
        g = math.radians(self.grip_axis())
        axis = np.array([math.cos(g), math.sin(g), 0.0])
        frac = min(1.0, max(0.0, self._claw_fraction()))
        gap = (5.0 - 2.4 * frac) / 2                          # cm from center to each finger
        tip = np.asarray(pose["finger"], float)
        reach = tip - np.asarray(pose["wrist"], float)
        for name, sgn in (("finger_a", 1), ("finger_b", -1)):
            d.mocap_pos[mc[name]] = cm(tip - reach / np.linalg.norm(reach) * 1.2 + sgn * gap * axis)
            d.mocap_quat[mc[name]] = _quat_frame(axis, reach * -1)
        heading = np.array([*(np.asarray(pose["wrist"][:2]) - base[:2]), 0.0])
        d.mocap_pos[mc["claw_plate"]] = cm(pose["marker"])
        d.mocap_quat[mc["claw_plate"]] = _quat_frame(np.cross(heading, [0, 0, 1]) * -1, pose["normal"])
        hand = self.person.hand
        if hand is None:
            for n in ("hand", "forearm"):
                d.mocap_pos[mc[n]] = [0.25, -0.6, -1.0]
            d.mocap_pos[mc["torso"]] = [0.25, -0.75, 0.15]
        else:
            hp = np.array([hand[0], hand[1], self.cfg["hand_height"]])
            elbow = np.array([hand[0] * 0.7 + 7.5, -25.0, 12.0])
            d.mocap_pos[mc["hand"]] = cm(hp)
            d.mocap_quat[mc["hand"]] = _yaw_quat(math.degrees(math.atan2(*(hp - elbow)[:2][::-1])))
            seg("forearm", hp + (elbow - hp) * 0.25, elbow)
            d.mocap_pos[mc["torso"]] = cm([hand[0] * 0.5 + 12.5, -45.0, 20.0])
        mujoco.mj_forward(m, d)

    # ================================================================= camera
    def _observe(self, t, pose):
        """Runs on the world thread: render only. Perception runs in read()."""
        if self.clock.time() - t > 2.0 / self.camera_fps:
            return None                       # behind the clock: drop this frame, catch up first
        if self._renderer is None:
            self._renderer = mujoco.Renderer(self.m, CAM_H, CAM_W)
            self._view_renderer = mujoco.Renderer(self.m, VIEW_H, VIEW_W)
        self._renderer.update_scene(self.d, camera="top")
        rgb = self._renderer.render()
        self.frames_rendered += 1
        if self.view_fps and t >= self._next_view:
            self._next_view = t + 1.0 / self.view_fps
            self._view_renderer.update_scene(self.d, camera="view")
            ok, buf = cv2.imencode(".jpg", cv2.cvtColor(self._view_renderer.render(), cv2.COLOR_RGB2BGR),
                                   [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                self.view_jpeg = buf.tobytes()
        rec = self._rec
        if rec is not None and t >= rec["next"]:
            rec["next"] = t + 1.0 / rec["hz"]
            small = cv2.resize(rgb, rec["size"], interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", cv2.cvtColor(small, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
            if ok:
                rec["frames"].append(buf.tobytes())
                rec["state"].append(list(self.emu.cur))       # where the servos are (us)
                rec["action"].append(list(self.emu.target))   # what was commanded (us)
                rec["t"].append(t)
        p = self.person
        signing = p.state == "signing"
        hand = None if p.hand is None else (np.array(p.hand, float), bool(p.open),
                                            p.sign if signing else None, p.point_at if signing else None)
        return (t, rgb, hand)

    # ================================================================= demo recording
    def start_recording(self, hz=10, size=(320, 180)):
        with self.lock:
            self._rec = {"hz": hz, "size": size, "next": 0.0, "frames": [], "state": [], "action": [], "t": []}

    def stop_recording(self):
        with self.lock:
            rec, self._rec = self._rec, None
        return rec

    def top_lens(self):
        f = (CAM_H / 2) / math.tan(math.radians(self._fovy / 2))
        return np.array([[f, 0, CAM_W / 2], [0, f, CAM_H / 2], [0, 0, 1]], np.float64)

    def read(self, timeout=1.0):
        try:
            t, rgb, hand = self._frames.get(timeout=self.clock.real(timeout))
        except queue.Empty:
            return None
        frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        markers = detect_markers(frame)
        if self.calib is None:
            c = Calibration(K=self.top_lens(), image_size=[CAM_W, CAM_H])
            try:
                c.calibrate_table(markers, self.cfg)
                self.calib = c
            except ValueError:
                return Observation(t=t, claw=None, detections=[], hands=[], image=frame, markers=markers)
        calib = self.calib
        claw, claw_px = None, None
        cid = self.cfg["layout"]["claw_marker_id"]
        if cid in markers:
            claw = calib.claw_pose(markers[cid], self.cfg["claw_marker_size"])
            claw_px = tuple(markers[cid].mean(axis=0))
        hands = []
        if hand is not None:
            (hx, hy), opened, sign, point_at = hand
            hx, hy = hx + self.rng.normal(0, 0.3), hy + self.rng.normal(0, 0.3)
            ring = [(hx + 6 * math.cos(a), hy + 6 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
            ring += [(hx - 4, -10.0), (hx + 4, -10.0)]          # the forearm, back to the human
            px = [calib.table_to_pixel(x, y, self.cfg["hand_height"]) for x, y in ring]
            hands.append(self._sign_fields({"x": float(hx), "y": float(hy), "open": opened, "px": px},
                                           sign or "", point_at))
        dets = detect_blocks(frame, self.cfg, calib, markers, claw_px, [h["px"] for h in hands])
        return Observation(t=t, claw=claw, detections=dets, hands=hands, image=frame,
                           markers=markers, claw_px=claw_px)

    # ================================================================= clutter
    def scatter(self, n, rng=None, types=None, colors=None, required=(), keep_out=None, margin=2.0,
                min_gap=4.0, near=(3.2, 4.0), near_frac=0.3, reachable=None, tries=600):
        """A cluttered table: drop n loose blocks at random reachable spots.

        required: [(type, color)] placed first (what the build needs); the rest
        are distractors drawn from what the catalog owns (counts respected,
        minus blocks already out), optionally limited to `types` / `colors`.
        Spots: outside keep_out (default the build strip) grown by `margin`,
        footprints never overlap, centres >= min_gap apart, except that about
        near_frac of the blocks go 3.2-4 cm from another one (near-touching).
        reachable(x, y) -> bool (e.g. from the body model); default: 9-17 cm
        from the arm's base. Returns the blocks placed (may be fewer than n)."""
        rng = rng if rng is not None else self.rng
        cat = self.catalog
        bx, by = self.cfg["layout"]["base"]
        aw, ad = self.cfg["layout"]["work_area"]
        keep = keep_out or self.cfg["layout"]["build_area"]
        reachable = reachable or (lambda x, y: 9.0 <= math.hypot(x - bx, y - by) <= 17.0)
        from collections import Counter
        with self.lock:
            out_now = Counter((b.type, b.color) for b in self.blocks)
        pool = []
        for tid, t in cat.types.items():
            if types and tid not in types:
                continue
            for c, k in t["colors"].items():
                if colors and c not in colors:
                    continue
                pool += [(tid, c)] * max(0, int(k) - out_now[(tid, c)])
        items = list(required)
        for it in items:
            if it in pool:
                pool.remove(it)
        rng.shuffle(pool)
        items += pool[:max(0, n - len(items))]

        def rect(x, y, yaw, w, d, grow=0.0):
            return ((float(x), float(y)), (w + 2 * grow, d + 2 * grow), float(yaw))

        def overlaps(r1, r2):
            return cv2.rotatedRectangleIntersection(r1, r2)[0] != cv2.INTERSECT_NONE

        placed = []
        for tid, color in items:
            w, d, _ = cat.size(tid)
            for _ in range(tries):
                yaw = float(rng.uniform(-90, 90))
                loose = [b for b in self.blocks if not b.held and not self.cfg.in_build(b.x, b.y)]
                if loose and rng.random() < near_frac:
                    o = loose[rng.integers(len(loose))]
                    a, r = rng.uniform(0, 2 * math.pi), rng.uniform(*near)
                    x, y = o.x + r * math.cos(a), o.y + r * math.sin(a)
                    gap = near[0]
                else:
                    x, y = rng.uniform(0, aw), rng.uniform(0, ad)
                    gap = min_gap
                me = rect(x, y, yaw, w, d)
                pts = cv2.boxPoints(me)
                if not all(1.0 <= px <= aw - 1.0 and 1.0 <= py <= ad - 1.0 for px, py in pts):
                    continue
                kx0, kx1, ky0, ky1 = keep
                kr = (((kx0 + kx1) / 2, (ky0 + ky1) / 2), (kx1 - kx0 + 2 * margin, ky1 - ky0 + 2 * margin), 0.0)
                if overlaps(me, kr) or not reachable(x, y):
                    continue
                with self.lock:
                    others = list(self.blocks)
                if any(math.hypot(o.x - x, o.y - y) < gap - 1e-6 or
                       overlaps(rect(x, y, yaw, w, d, 0.1), rect(o.x, o.y, o.yaw, o.w, o.d, 0.1))
                       for o in others):
                    continue
                placed.append(self.add_block(tid, color, x, y, yaw=yaw))
                break
        return placed


def make_twin(cfg, catalog=None, speed=None, seed=None, camera_fps=20, reach_rate=0.0, view_fps=5):
    return TwinWorld(cfg, catalog=catalog, speed=speed, seed=seed, camera_fps=camera_fps,
                     reach_rate=reach_rate, view_fps=view_fps).start()

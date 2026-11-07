"""Lens and table calibration, pixel <-> table, claw pose (handbook 2F)."""
import json

import cv2
import numpy as np

from . import config as C

DICT = cv2.aruco.DICT_4X4_50


# ===================================================================== markers
def _dictionary():
    try:
        return cv2.aruco.getPredefinedDictionary(DICT)
    except AttributeError:
        return cv2.aruco.Dictionary_get(DICT)


def detect_markers(image):
    """Return {id: 4x2 corner pixels in ArUco order (TL, TR, BR, BL)}.
    Supports the newer detector object and the older function."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    d = _dictionary()
    if hasattr(cv2.aruco, "ArucoDetector"):
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        corners, ids, _ = cv2.aruco.ArucoDetector(d, params).detectMarkers(gray)
    else:
        params = cv2.aruco.DetectorParameters_create()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        corners, ids, _ = cv2.aruco.detectMarkers(gray, d, parameters=params)
    out = {}
    if ids is not None:
        for c, i in zip(corners, ids.flatten()):
            out[int(i)] = c.reshape(4, 2).astype(np.float64)
    return out


def marker_image(marker_id, pixels):
    d = _dictionary()
    if hasattr(cv2.aruco, "generateImageMarker"):
        return cv2.aruco.generateImageMarker(d, marker_id, pixels)
    return cv2.aruco.drawMarker(d, marker_id, pixels)


def make_marker_sheets(cfg, out_dir, dpi=300):
    """Write printable sheets at 100% scale: table markers 0-3, claw marker,
    and the chessboard. PDF when Pillow is available (keeps the true size)."""
    from pathlib import Path
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    px_per_cm = dpi / 2.54
    page_w, page_h = int(8.5 * dpi), int(11 * dpi)

    def sheet(items):
        page = np.full((page_h, page_w), 255, np.uint8)
        y = int(1.5 * px_per_cm)
        x = int(1.5 * px_per_cm)
        for mid, size_cm in items:
            s = int(round(size_cm * px_per_cm))
            border = int(round(0.6 * px_per_cm))
            if x + s + 2 * border > page_w:
                x = int(1.5 * px_per_cm)
                y += s + 2 * border + int(1.5 * px_per_cm)
            page[y + border:y + border + s, x + border:x + border + s] = marker_image(mid, s)
            cv2.rectangle(page, (x, y), (x + s + 2 * border, y + s + 2 * border), 180, 2)
            cv2.putText(page, f"ID {mid}  {size_cm} cm", (x, y + s + 2 * border + int(0.6 * px_per_cm)),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3)
            x += s + 2 * border + int(1.5 * px_per_cm)
        return page

    pages = {
        "table_markers": sheet([(i, cfg["table_marker_size"]) for i in range(4)]),
        "claw_marker": sheet([(cfg["layout"]["claw_marker_id"], cfg["claw_marker_size"])]),
    }
    # chessboard: (inner+1) x (inner+1) squares
    nx, ny = cfg["chessboard_inner"]
    sq = int(round(cfg["chessboard_square"] * px_per_cm))
    board = np.full((page_w, page_h), 255, np.uint8)   # landscape
    ox, oy = int(1.2 * px_per_cm), int(1.2 * px_per_cm)
    for r in range(ny + 1):
        for c in range(nx + 1):
            if (r + c) % 2 == 0:
                board[oy + r * sq:oy + (r + 1) * sq, ox + c * sq:ox + (c + 1) * sq] = 0
    cv2.putText(board, f"{nx}x{ny} inner corners, {cfg['chessboard_square']} cm squares",
                (ox, oy + (ny + 1) * sq + int(0.8 * px_per_cm)), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 3)
    pages["chessboard"] = board

    written = []
    for name, img in pages.items():
        try:
            from PIL import Image
            p = out_dir / f"{name}.pdf"
            Image.fromarray(img).save(p, resolution=dpi)
        except ImportError:
            p = out_dir / f"{name}.png"
            cv2.imwrite(str(p), img)
        written.append(p)
        cv2.imwrite(str(out_dir / f"{name}.png"), img)
    return written


# ===================================================================== geometry helpers
def table_marker_corners(cx, cy, s):
    """Table positions of a marker's corners in ArUco order (TL, TR, BR, BL),
    with its printed top edge facing away from the human (+y)."""
    h = s / 2
    return np.array([[cx - h, cy + h, 0], [cx + h, cy + h, 0],
                     [cx + h, cy - h, 0], [cx - h, cy - h, 0]], dtype=np.float64)


def square_object_points(s):
    h = s / 2
    return np.array([[-h, h, 0], [h, h, 0], [h, -h, 0], [-h, -h, 0]], dtype=np.float64)


# ===================================================================== calibration object
class Calibration:
    def __init__(self, K=None, dist=None, rvec=None, tvec=None, marker_px=None, image_size=None,
                 lens_error=None, table_error=None):
        self.K = None if K is None else np.asarray(K, np.float64)
        self.dist = np.zeros(5) if dist is None else np.asarray(dist, np.float64).reshape(-1)
        self.rvec = None if rvec is None else np.asarray(rvec, np.float64).reshape(3, 1)
        self.tvec = None if tvec is None else np.asarray(tvec, np.float64).reshape(3, 1)
        self.marker_px = marker_px or {}
        self.image_size = image_size
        self.lens_error = lens_error
        self.table_error = table_error

    # ---- persistence
    def to_dict(self):
        f = lambda a: None if a is None else np.asarray(a).tolist()
        return {"K": f(self.K), "dist": f(self.dist), "rvec": f(self.rvec), "tvec": f(self.tvec),
                "marker_px": {str(k): f(v) for k, v in self.marker_px.items()},
                "image_size": self.image_size, "lens_error": self.lens_error,
                "table_error": self.table_error}

    def save(self, data_dir=None):
        p = C.path("calibration", data_dir)
        with open(p, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        return p

    @classmethod
    def load(cls, data_dir=None):
        p = C.path("calibration", data_dir)
        if not p.exists():
            return cls()
        with open(p) as fh:
            d = json.load(fh)
        mp = {int(k): np.asarray(v) for k, v in (d.get("marker_px") or {}).items()}
        return cls(d.get("K"), d.get("dist"), d.get("rvec"), d.get("tvec"), mp,
                   d.get("image_size"), d.get("lens_error"), d.get("table_error"))

    @property
    def has_lens(self):
        return self.K is not None

    @property
    def has_table(self):
        return self.rvec is not None

    def R(self):
        return cv2.Rodrigues(self.rvec)[0]

    def camera_position(self):
        R = self.R()
        return (-R.T @ self.tvec).ravel()

    # ---- lens
    def calibrate_lens(self, images, inner=(9, 6), square=2.5):
        """Chessboard views -> camera matrix and distortion. Returns (error_px, used)."""
        nx, ny = inner
        objp = np.zeros((nx * ny, 3), np.float32)
        objp[:, :2] = np.mgrid[0:nx, 0:ny].T.reshape(-1, 2) * square
        obj_pts, img_pts, size = [], [], None
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        for img in images:
            gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            size = gray.shape[::-1]
            ok, corners = cv2.findChessboardCorners(gray, (nx, ny), None)
            if not ok:
                continue
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), crit)
            obj_pts.append(objp)
            img_pts.append(corners)
        if len(obj_pts) < 3:
            raise ValueError(f"Only {len(obj_pts)} views with the chessboard found; need 15+.")
        err, K, dist, _, _ = cv2.calibrateCamera(obj_pts, img_pts, size, None, None)
        self.K, self.dist, self.image_size, self.lens_error = K, dist.reshape(-1), list(size), float(err)
        return float(err), len(obj_pts)

    def default_lens(self, width, height, hfov_deg=70.0):
        """Rough camera matrix for when no lens calibration exists yet."""
        f = (width / 2) / np.tan(np.radians(hfov_deg / 2))
        self.K = np.array([[f, 0, width / 2], [0, f, height / 2], [0, 0, 1]], np.float64)
        self.dist = np.zeros(5)
        self.image_size = [width, height]

    # ---- table pose
    def calibrate_table(self, markers, cfg):
        """markers: {id: corners px}. Solves the camera pose from the table markers."""
        size = cfg["table_marker_size"]
        obj, img, used = [], [], {}
        for mid_s, (cx, cy) in cfg["layout"]["markers"].items():
            mid = int(mid_s)
            if mid in markers:
                obj.append(table_marker_corners(cx, cy, size))
                img.append(markers[mid])
                used[mid] = markers[mid]
        if len(used) < 3:
            raise ValueError(f"Only {len(used)} table markers visible ({sorted(used)}); need at least 3.")
        obj, img = np.vstack(obj), np.vstack(img)
        ok, rvec, tvec = cv2.solvePnP(obj, img, self.K, self.dist, flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            raise ValueError("solvePnP failed")
        proj, _ = cv2.projectPoints(obj, rvec, tvec, self.K, self.dist)
        err = float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - img) ** 2, axis=1))))
        self.rvec, self.tvec = rvec, tvec
        cam = self.camera_position()
        if cam[2] <= 0:
            self.rvec = self.tvec = None
            raise ValueError("Camera came out below the table: markers are rotated or swapped. "
                             "Check each marker's ID and that its top edge faces away from the human.")
        self.marker_px = {k: v for k, v in used.items()}
        self.table_error = err
        return {"error_px": err, "camera": cam.tolist(), "height": float(cam[2]), "used": sorted(used)}

    def camera_moved(self, markers, tol_px=3.0):
        """True if any saved table-marker corner moved more than tol_px."""
        for mid, saved in self.marker_px.items():
            if mid in markers and np.max(np.linalg.norm(markers[mid] - saved, axis=1)) > tol_px:
                return True
        return False

    # ---- pixel <-> table
    def pixel_to_table(self, u, v, z=0.0):
        pts = np.array([[[u, v]]], np.float64)
        n = cv2.undistortPoints(pts, self.K, self.dist).reshape(2)
        ray_c = np.array([n[0], n[1], 1.0])
        R = self.R()
        cam = self.camera_position()
        d = R.T @ ray_c
        if abs(d[2]) < 1e-9:
            return None
        s = (z - cam[2]) / d[2]
        p = cam + s * d
        return float(p[0]), float(p[1])

    def table_to_pixel(self, x, y, z=0.0):
        pts = np.array([[x, y, z]], np.float64)
        px, _ = cv2.projectPoints(pts, self.rvec, self.tvec, self.K, self.dist)
        return tuple(float(a) for a in px.reshape(2))

    # ---- claw pose
    def claw_pose(self, corners, size):
        """Square-marker pose -> table x, y, z (cm) and down-ness (1.0 = claw points straight down)."""
        obj = square_object_points(size)
        img = np.asarray(corners, np.float64).reshape(4, 1, 2)
        try:
            n, rvecs, tvecs, errs = cv2.solvePnPGeneric(obj, img, self.K, self.dist,
                                                         flags=cv2.SOLVEPNP_IPPE_SQUARE)
        except cv2.error:
            return None
        best = None
        for i in range(n):
            Rm = cv2.Rodrigues(rvecs[i])[0]
            normal_cam = Rm[:, 2]
            to_cam = -tvecs[i].ravel()
            facing = float(np.dot(normal_cam, to_cam)) > 0      # marker faces the camera
            e = float(np.ravel(errs)[i]) if errs is not None else 0.0
            score = (0 if facing else 1, e)
            if best is None or score < best[0]:
                best = (score, rvecs[i], tvecs[i])
        if best is None:
            return None
        _, rv, tv = best
        R = self.R()
        pos = (R.T @ (tv.reshape(3, 1) - self.tvec)).ravel()
        normal = R.T @ cv2.Rodrigues(rv)[0][:, 2]
        return {"x": float(pos[0]), "y": float(pos[1]), "z": float(pos[2]), "down": float(normal[2])}

"""Headless orthographic renders. No interactive GUI and no pixel oracle."""

from __future__ import annotations

import base64
import struct
import zlib

import numpy as np

# Camera forward is the direction from the eye toward the target.
# Front looks along +Y, so +X is image-right and +Z is image-up.
VIEWS = {
    "front": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "rear": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "left": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "bottom": ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
    "isometric": ((1.0, 1.0, -1.0), (0.0, 0.0, 1.0)),
}
BACKGROUND = np.array([32, 40, 48], dtype=np.float64)
BODY_COLOR = np.array([186, 196, 208], dtype=np.float64)
HIGHLIGHT = np.array([255, 196, 77], dtype=np.float64)


def render_meshes(meshes: list[dict], views: list[str], width: int, height: int, *, highlight=None) -> list[dict]:
    images = []
    for name in views:
        if name not in VIEWS:
            raise ValueError(f"unknown view {name}")
        forward, up = VIEWS[name]
        rgb = _rasterize(meshes, forward, up, width, height, highlight=highlight if name == views[0] else None)
        encoded = _png(rgb)
        images.append({
            "name": name,
            "width": width,
            "height": height,
            "media_type": "image/png",
            "png_base64": base64.b64encode(encoded).decode("ascii"),
            "metrics": _metrics(rgb),
            "camera": {
                "forward": list(_normalize(forward)),
                "up": list(_normalize(up)),
                "projection": "orthographic",
            },
        })
    return images


def _rasterize(meshes, forward, up, width, height, highlight=None) -> np.ndarray:
    forward = _normalize(forward)
    up = _normalize(up)
    z_axis = -forward
    x_axis = _normalize(np.cross(up, z_axis))
    y_axis = np.cross(z_axis, x_axis)
    triangles = []
    for mesh in meshes:
        vertices = np.asarray(mesh["vertices"], dtype=np.float64)
        if len(vertices) == 0:
            continue
        color = HIGHLIGHT if mesh.get("highlight") else BODY_COLOR
        for tri in mesh["triangles"]:
            pts = vertices[list(tri)]
            if pts.shape != (3, 3):
                continue
            triangles.append((pts, color))
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[:] = BACKGROUND.astype(np.uint8)
    if not triangles:
        return image
    projected = []
    for pts, color in triangles:
        cam = np.column_stack((pts @ x_axis, pts @ y_axis, pts @ z_axis))
        projected.append((cam, color, pts))
    xs = np.concatenate([item[0][:, 0] for item in projected])
    ys = np.concatenate([item[0][:, 1] for item in projected])
    span = max(float(xs.max() - xs.min()), float(ys.max() - ys.min()), 1e-9)
    pad = 0.08 * span
    min_x, max_x = float(xs.min()) - pad, float(xs.max()) + pad
    min_y, max_y = float(ys.min()) - pad, float(ys.max()) + pad
    scale = min((width - 1) / (max_x - min_x), (height - 1) / (max_y - min_y))
    zbuf = np.full((height, width), np.inf)
    light = _normalize(forward * 0.6 + up * 0.8 + x_axis * 0.2)
    for cam, color, world in projected:
        screen = np.column_stack((
            (cam[:, 0] - min_x) * scale,
            (max_y - cam[:, 1]) * scale,
        ))
        normal = np.cross(world[1] - world[0], world[2] - world[0])
        length = np.linalg.norm(normal)
        if length <= 1e-12:
            continue
        normal = normal / length
        if float(np.dot(normal, forward)) > 0:
            normal = -normal
        shade = max(0.22, float(np.dot(normal, light)))
        shaded = np.clip(color * shade, 0, 255)
        _fill(image, zbuf, screen, cam[:, 2], shaded)
    return image


def _fill(image, zbuf, screen, depth, color) -> None:
    height, width = zbuf.shape
    min_x = max(int(np.floor(screen[:, 0].min())), 0)
    max_x = min(int(np.ceil(screen[:, 0].max())), width - 1)
    min_y = max(int(np.floor(screen[:, 1].min())), 0)
    max_y = min(int(np.ceil(screen[:, 1].max())), height - 1)
    if min_x > max_x or min_y > max_y:
        return
    v0, v1, v2 = screen
    area = (v1[0] - v0[0]) * (v2[1] - v0[1]) - (v2[0] - v0[0]) * (v1[1] - v0[1])
    if abs(area) <= 1e-8:
        return
    ys, xs = np.mgrid[min_y:max_y + 1, min_x:max_x + 1]
    w0 = (v1[0] - xs) * (v2[1] - ys) - (v2[0] - xs) * (v1[1] - ys)
    w1 = (v2[0] - xs) * (v0[1] - ys) - (v0[0] - xs) * (v2[1] - ys)
    w2 = area - w0 - w1
    if area < 0:
        mask = (w0 <= 0) & (w1 <= 0) & (w2 <= 0)
    else:
        mask = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    if not np.any(mask):
        return
    w0 = w0 / area
    w1 = w1 / area
    w2 = w2 / area
    zval = w0 * depth[0] + w1 * depth[1] + w2 * depth[2]
    closer = mask & (zval < zbuf[min_y:max_y + 1, min_x:max_x + 1])
    tile = zbuf[min_y:max_y + 1, min_x:max_x + 1]
    tile[closer] = zval[closer]
    zbuf[min_y:max_y + 1, min_x:max_x + 1] = tile
    pixel = image[min_y:max_y + 1, min_x:max_x + 1]
    pixel[closer] = color.astype(np.uint8)
    image[min_y:max_y + 1, min_x:max_x + 1] = pixel


def _metrics(rgb: np.ndarray) -> dict:
    background = np.array(BACKGROUND, dtype=np.uint8)
    mask = np.any(rgb != background, axis=2)
    filled = float(mask.mean())
    mirror = np.abs(mask.astype(np.int8) - mask[:, ::-1].astype(np.int8)).mean()
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any():
        aspect = 0.0
    else:
        y0, y1 = np.flatnonzero(rows)[[0, -1]]
        x0, x1 = np.flatnonzero(cols)[[0, -1]]
        aspect = float(x1 - x0 + 1) / float(y1 - y0 + 1)
    return {
        "silhouette_fraction": filled,
        "horizontal_asymmetry": float(mirror),
        "silhouette_aspect": aspect,
    }


def _png(rgb: np.ndarray) -> bytes:
    height, width, _channels = rgb.shape

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + rgb[row].tobytes() for row in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def _normalize(vector) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float64)
    return array / np.linalg.norm(array)

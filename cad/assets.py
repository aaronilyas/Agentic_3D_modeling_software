"""Reference-image assets. Bytes live in the document, not in a chat transcript."""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from pathlib import Path

from cad.errors import InvalidArgument

ROLES = {"front", "side", "top", "perspective", "detail", "inspiration", "other"}


@dataclass
class ReferenceImage:
    id: str
    label: str
    role: str
    filename: str
    media_type: str
    width: int
    height: int
    checksum: str
    notes: str = ""
    camera_hint: dict | None = None
    calibration: dict | None = None
    data: bytes = b""

    def public(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "role": self.role,
            "filename": self.filename,
            "media_type": self.media_type,
            "width": self.width,
            "height": self.height,
            "checksum": self.checksum,
            "image_uri": f"cad://references/{self.id}/{self.checksum}",
            "notes": self.notes,
            "camera_hint": self.camera_hint,
            "calibration": self.calibration,
            "bytes": len(self.data),
            "units": "mm",
        }


def load_image(path: str, *, role: str, label: str | None, notes: str, camera_hint) -> tuple[str, str, int, int, bytes]:
    if role not in ROLES:
        raise InvalidArgument(f"role must be one of {sorted(ROLES)}")
    if not isinstance(path, str) or not path:
        raise InvalidArgument("reference image path must be a nonempty string")
    source = Path(path)
    if not source.is_file():
        raise InvalidArgument("reference image file does not exist")
    data = source.read_bytes()
    if len(data) > 30 * 1024 * 1024:
        raise InvalidArgument("reference image is larger than 30 MB")
    media_type, width, height = image_size(data)
    if camera_hint is not None and not isinstance(camera_hint, dict):
        raise InvalidArgument("camera_hint must be an object")
    if notes and not isinstance(notes, str):
        raise InvalidArgument("notes must be a string")
    return media_type, source.name, width, height, data


def image_size(data: bytes) -> tuple[str, int, int]:
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        if width <= 0 or height <= 0:
            raise InvalidArgument("image dimensions must be positive")
        return "image/png", int(width), int(height)
    if data.startswith(b"\xff\xd8"):
        size = _jpeg_size(data)
        if size is not None:
            return "image/jpeg", size[0], size[1]
    raise InvalidArgument("reference image must be a PNG or JPEG")


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def calibrate(p1, p2, distance_mm: float) -> dict:
    pixel_distance = math.dist(p1, p2)
    if pixel_distance <= 1e-6:
        raise InvalidArgument("calibration points must be distinct")
    if distance_mm <= 0:
        raise InvalidArgument("calibration distance must be greater than zero")
    return {
        "p1": [float(p1[0]), float(p1[1])],
        "p2": [float(p2[0]), float(p2[1])],
        "distance_mm": float(distance_mm),
        "pixel_distance": float(pixel_distance),
        "mm_per_pixel": float(distance_mm) / float(pixel_distance),
        "kind": "two_point",
    }


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    offset = 2
    while offset + 8 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            return None
        length = struct.unpack(">H", data[offset:offset + 2])[0]
        if length < 2 or offset + length > len(data):
            return None
        if marker in {0xC0, 0xC1, 0xC2} and offset + 7 <= len(data):
            height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            return int(width), int(height)
        offset += length
    return None

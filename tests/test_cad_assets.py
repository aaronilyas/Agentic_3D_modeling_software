"""Reference images, calibration, headless renders, and project round-trip."""

import base64
import struct
import tempfile
import zlib
from pathlib import Path

from tests.cad_support import CadTestCase


def write_png(path: Path, width: int, height: int) -> None:
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes([40, 90, 140]) * width for _ in range(height))
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


class AssetTests(CadTestCase):
    def test_reference_calibration_and_uncalibrated_estimate(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        image = Path(directory.name) / "front.png"
        write_png(image, 80, 40)
        added = self.ok(
            "add_reference", path=str(image), role="front", label="front view",
            notes="shop photo", camera_hint={"view": "front"},
        )
        self.assertEqual(added["width"], 80)
        self.assertEqual(added["height"], 40)
        self.assertEqual(len(added["checksum"]), 64)
        listed = self.ok("list_references")["references"]
        self.assertEqual(listed[0]["role"], "front")
        self.assertIsNone(listed[0]["calibration"])
        uncalibrated = self.ok("estimate_length", id=added["id"], pixel_length=40)
        self.assertEqual(uncalibrated["kind"], "uncalibrated")
        self.assertIsNone(uncalibrated["millimeters"])
        calibrated = self.ok(
            "set_calibration", id=added["id"], p1=[0, 0], p2=[80, 0], distance_mm=100,
        )
        self.assertAlmostEqual(calibrated["calibration"]["mm_per_pixel"], 1.25, delta=1e-9)
        estimate = self.ok("estimate_length", id=added["id"], pixel_length=40)
        self.assertEqual(estimate["kind"], "calibrated_estimate")
        self.assertAlmostEqual(estimate["millimeters"], 50, delta=1e-9)
        self.assertFalse(estimate["geometric"])
        self.assertEqual(self.err("add_reference", path=str(image), role="gem-top")["code"], "INVALID_ARGUMENT")
        self.ok("undo")
        self.assertIsNone(self.ok("inspect_reference", id=added["id"])["calibration"])
        self.ok("redo")
        self.assertEqual(self.ok("inspect_reference", id=added["id"])["scale"], "calibrated")

    def test_headless_render_has_a_silhouette_without_a_pixel_oracle(self):
        box = self.ok("create_primitive", kind="box", size=[30, 10, 20], origin=[0, 0, 0])["ref"]
        rendered = self.ok(
            "render_views", ref=box, views=["isometric", "front", "top"], width=96, height=72,
        )
        self.assertEqual(rendered["units"], "mm")
        names = []
        for view in rendered["views"]:
            names.append(view["name"])
            png = base64.b64decode(view["png_base64"])
            self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertGreater(view["metrics"]["silhouette_fraction"], 0.02)
            self.assertEqual(view["camera"]["projection"], "orthographic")
        self.assertEqual(names, ["isometric", "front", "top"])
        self.assertEqual(self.revision(), rendered["revision"])

    def test_project_round_trip_replays_features_and_assets(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        image = Path(directory.name) / "side.png"
        write_png(image, 20, 10)
        created = self.ok("create_primitive", kind="box", size=[8, 4, 2], origin=[1, 0, 0], name="cover")
        self.ok("edit_feature", feature_id=created["feature_id"], parameters={"size": [8, 4, 3]})
        asset = self.ok("add_reference", path=str(image), role="side", label="side")
        self.ok("set_calibration", id=asset["id"], p1=[0, 0], p2=[20, 0], distance_mm=50)
        destination = str(Path(directory.name) / "cover.cadproj")
        revision = self.revision()
        saved = self.ok("save_project", path=destination)
        self.assertEqual(saved["format_version"], 1)
        self.assertEqual(self.revision(), revision)
        extra = self.ok("create_primitive", kind="sphere", radius=1, center=[40, 0, 0])
        fresh = self.ok("open_project", path=destination)
        info = self.ok("inspect", ref=created["ref"])
        self.assertAlmostEqual(info["volume"], 96, delta=1e-6)
        self.assertEqual(info["name"], "cover")
        self.assertEqual(info["bounds"][0][0], 1)
        self.assertNotIn(extra["ref"], self.ok("snapshot")["references"])
        opened = self.ok("inspect_reference", id=asset["id"])
        self.assertAlmostEqual(opened["calibration"]["mm_per_pixel"], 2.5, delta=1e-9)
        self.assertEqual(fresh["format_version"], 1)
        self.ok("undo")
        self.assertIn(extra["ref"], self.ok("snapshot")["references"])
        broken = Path(directory.name) / "bad.cadproj"
        broken.write_text("not a project", encoding="utf-8")
        self.assertEqual(self.err("open_project", path=str(broken))["code"], "INVALID_ARGUMENT")
        self.assertIn(extra["ref"], self.ok("snapshot")["references"])

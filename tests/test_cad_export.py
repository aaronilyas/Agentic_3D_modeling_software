"""STEP, glTF, STL, and OBJ exports stay atomic and do not mutate the document."""

import json
import struct
import tempfile
from pathlib import Path

from build123d import import_step

from tests.cad_support import CadTestCase


class ExportTests(CadTestCase):
    def setUp(self):
        super().setUp()
        self.box = self.ok("create_primitive", kind="box", size=[10, 20, 30], origin=[0, 0, 0])["ref"]
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def path(self, name):
        return str(Path(self.directory.name) / name)

    def test_formats_and_exact_step(self):
        formats = {item["format"]: item for item in self.ok("list_export_formats")["formats"]}
        self.assertEqual(formats["step"]["geometry"], "brep")
        self.assertEqual(formats["glb"]["geometry"], "mesh")
        self.assertTrue(formats["stl"]["manufacturing_default"])
        destination = self.path("part.step")
        before = self.ok("snapshot")
        exported = self.ok("export", ref=self.box, path=destination, format="step", mode="preview")
        self.assertEqual(exported["units"], "mm")
        self.assertEqual(exported["geometry"], "brep")
        self.assertEqual(self.ok("snapshot"), before)
        text = Path(destination).read_text(encoding="utf-8", errors="replace")
        self.assertIn("ISO-10303-21", text)
        self.assertNotIn("facet normal", text.lower())
        reloaded = import_step(destination)
        self.assertAlmostEqual(float(reloaded.volume), 6000, delta=1e-4)

    def test_glb_is_metres_and_stl_obj_are_millimetre_meshes(self):
        glb = self.path("part.glb")
        exported = self.ok("export", ref=self.box, path=glb, format="glb", mode="preview")
        self.assertEqual(exported["units"], "m")
        data = Path(glb).read_bytes()
        self.assertTrue(data.startswith(b"glTF"))
        chunk_length = struct.unpack_from("<I", data, 12)[0]
        document = json.loads(data[20:20 + chunk_length])
        positions = [
            accessor["max"] for accessor in document["accessors"]
            if accessor.get("max") and max(abs(value) for value in accessor["max"]) < 0.2
        ]
        self.assertTrue(positions)
        self.assertTrue(any(max(point) > 0.02 for point in positions))
        self.assertTrue(all(max(point) < 0.05 for point in positions))
        stl = self.path("part.stl")
        stl_export = self.ok("export", ref=self.box, path=stl, format="stl", mode="preview")
        self.assertEqual(stl_export["units"], "mm")
        blob = Path(stl).read_bytes()
        self.assertTrue(blob.startswith(b"agentic-cad mm"))
        count = struct.unpack_from("<I", blob, 80)[0]
        self.assertGreater(count, 10)
        self.assertEqual(len(blob), 84 + count * 50)
        obj_path = self.path("part.obj")
        obj_export = self.ok("export", ref=self.box, path=obj_path, format="obj", mode="preview")
        self.assertEqual(obj_export["units"], "mm")
        obj = Path(obj_path).read_text(encoding="ascii")
        self.assertIn("units mm", obj)
        self.assertIn("v 10.000000", obj)

    def test_manufacturing_stl_is_atomic(self):
        destination = Path(self.path("keep.stl"))
        destination.write_bytes(b"SENTINEL")
        before = self.ok("snapshot")
        blocked = self.err("export", ref=self.box, path=str(destination), format="stl", mode="manufacturing")
        self.assertEqual(blocked["code"], "INVALID_ARGUMENT")
        self.assertEqual(destination.read_bytes(), b"SENTINEL")
        self.assertEqual(self.ok("snapshot"), before)
        report = self.ok("validate", scope="manufacturing", profile="fdm", ref=self.box)
        self.assertTrue(report["ready"])
        self.ok("edit_feature", feature_id=self.ok("snapshot")["features"][0]["id"], parameters={"size": [10, 20, 10]})
        stale = self.err(
            "export", ref=self.box, path=str(destination), format="stl",
            mode="manufacturing", validation=report,
        )
        self.assertEqual(stale["code"], "STALE_VALIDATION")
        self.assertEqual(destination.read_bytes(), b"SENTINEL")
        current = self.ok("validate", scope="manufacturing", profile="fdm", ref=self.box)
        self.ok(
            "export", ref=self.box, path=str(destination), format="stl",
            mode="manufacturing", validation=current,
        )
        self.assertTrue(destination.read_bytes().startswith(b"agentic-cad mm"))
        missing = self.path("missing-dir/part.step")
        failed = self.err("export", ref=self.box, path=missing, format="step")
        self.assertEqual(failed["code"], "EXPORT_IO_ERROR")
        self.assertFalse(Path(missing).exists())

    def test_blend_uses_an_injected_blender_and_does_not_invent_bytes(self):
        calls = {}

        def runner(glb_path, blend_path):
            calls["glb"] = Path(glb_path).read_bytes()[:4]
            Path(blend_path).write_bytes(b"BLENDER-FAKE")

        self.app._blender_runner = runner
        destination = self.path("part.blend")
        exported = self.ok("export", ref=self.box, path=destination, format="blend", mode="preview")
        self.assertEqual(exported["units"], "m")
        self.assertEqual(calls["glb"], b"glTF")
        self.assertEqual(Path(destination).read_bytes(), b"BLENDER-FAKE")
        self.app._blender_runner = lambda *_args: (_ for _ in ()).throw(RuntimeError("blender failed"))
        sentinel = Path(self.path("keep.blend"))
        sentinel.write_bytes(b"KEEP")
        failed = self.err("export", ref=self.box, path=str(sentinel), format="blend", mode="preview")
        self.assertEqual(failed["code"], "EXPORT_IO_ERROR")
        self.assertEqual(sentinel.read_bytes(), b"KEEP")

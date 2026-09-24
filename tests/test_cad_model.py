"""Generic solids, feature edits, topology, and history."""

import math
from pathlib import Path

from tests.cad_support import CadTestCase

ROOT = Path(__file__).resolve().parents[1]


class GenericModelTests(CadTestCase):
    def test_core_sources_do_not_depend_on_jewelry(self):
        banned = ("jewelry", "prong", "gemstone", "create_ring")
        for path in (ROOT / "cad").rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for word in banned:
                self.assertNotIn(word, text, f"{path} contains {word}")

    def test_primitives_extrude_revolve_and_booleans(self):
        box = self.ok("create_primitive", kind="box", size=[10, 20, 30], origin=[1, 2, 3], name="block")
        info = self.ok("inspect", ref=box["ref"])
        self.assertAlmostEqual(info["volume"], 6000, delta=1e-6)
        self.assertEqual(info["bounds"], [[1, 2, 3], [11, 22, 33]])
        self.assertEqual(info["topology"]["components"], 1)
        self.assertEqual(info["name"], "block")
        self.assertEqual(info["units"], "mm")
        cylinder = self.ok("create_primitive", kind="cylinder", radius=2, height=10, origin=[0, 0, 0])
        self.assertAlmostEqual(self.ok("inspect", ref=cylinder["ref"])["volume"], math.pi * 4 * 10, delta=1e-6)
        sphere = self.ok("create_primitive", kind="sphere", radius=2, center=[0, 0, 0])
        self.assertAlmostEqual(self.ok("inspect", ref=sphere["ref"])["volume"], 4 / 3 * math.pi * 8, delta=1e-4)
        extruded = self.ok("extrude", profile=[[0, 0], [8, 0], [8, 5], [0, 5]], height=4)
        self.assertAlmostEqual(self.ok("inspect", ref=extruded["ref"])["volume"], 160, delta=1e-6)
        sketch = self.ok("create_sketch", profile=[[0, 0], [4, 0], [4, 4], [0, 4]], name="square")
        from_sketch = self.ok("extrude", sketch_id=sketch["feature_id"], height=2)
        self.assertAlmostEqual(self.ok("inspect", ref=from_sketch["ref"])["volume"], 32, delta=1e-6)
        revolved = self.ok("revolve", profile=[[2, 0], [4, 0], [4, 3], [2, 3]], angle_degrees=360)
        self.assertAlmostEqual(self.ok("inspect", ref=revolved["ref"])["volume"], math.pi * 12 * 3, delta=1e-4)
        swept = self.ok(
            "sweep",
            profile=[[-1, -1], [1, -1], [1, 1], [-1, 1]],
            path=[[0, 0, 0], [15, 0, 0], [15, 8, 4]],
        )
        self.assertGreater(self.ok("inspect", ref=swept["ref"])["volume"], 50)
        lofted = self.ok(
            "loft",
            profiles=[[[-4, -4], [4, -4], [4, 4], [-4, 4]], [[-1, -1], [1, -1], [1, 1], [-1, 1]]],
            stations=[0, 12],
        )
        self.assertAlmostEqual(self.ok("inspect", ref=lofted["ref"])["volume"], 336, delta=0.1)
        plate = self.ok("create_primitive", kind="box", size=[20, 20, 10], origin=[0, 0, 0])
        cutter = self.ok("create_primitive", kind="cylinder", radius=2, height=30, origin=[10, 10, -10])
        cut = self.ok("boolean", kind="subtract", left=plate["ref"], right=cutter["ref"], name="plate")
        self.assertAlmostEqual(
            self.ok("inspect", ref=cut["ref"])["volume"], 4000 - math.pi * 4 * 10, delta=1e-3,
        )
        before = self.revision()
        empty = self.err("boolean", kind="subtract", left=plate["ref"], right=plate["ref"])
        self.assertEqual(empty["code"], "EMPTY_RESULT")
        self.assertEqual(self.revision(), before)
        self.err("create_primitive", kind="box", size=[0, 1, 1], origin=[0, 0, 0])
        self.assertEqual(self.revision(), before)

    def test_fillet_chamfer_shell_hole_patterns_and_transforms(self):
        box = self.ok("create_primitive", kind="box", size=[20, 20, 10], origin=[0, 0, 0])
        filleted = self.ok("fillet", ref=box["ref"], radius=1, selector={"kind": "longest_vertical", "count": 4})
        self.assertAlmostEqual(self.ok("inspect", ref=filleted["ref"])["volume"], 3991.4159265358976, delta=1e-3)
        bar = self.ok("extrude", profile=[[0, 0], [8, 0], [8, 5], [0, 5]], height=4)
        chamfered = self.ok("chamfer", ref=bar["ref"], distance=0.4, selector="vertical")
        self.assertLess(self.ok("inspect", ref=chamfered["ref"])["volume"], 160)
        shelled = self.ok("shell", ref=bar["ref"], thickness=0.4)
        shell_info = self.ok("inspect", ref=shelled["ref"])
        self.assertLess(shell_info["volume"], 160)
        self.assertTrue(shell_info["topology"]["closed"])
        block = self.ok("create_primitive", kind="box", size=[20, 20, 10], origin=[0, 0, 0], name="drilled")
        drilled = self.ok("hole", ref=block["ref"], position=[10, 10, 10], diameter=3, through=True)
        self.assertAlmostEqual(
            self.ok("inspect", ref=drilled["ref"])["volume"], 4000 - math.pi * 2.25 * 10, delta=1e-2,
        )
        edited = self.ok("edit_feature", feature_id=drilled["feature_id"], parameters={"diameter": 4})
        self.assertAlmostEqual(
            self.ok("inspect", ref=edited["ref"])["volume"], 4000 - math.pi * 4 * 10, delta=1e-2,
        )
        peg = self.ok("create_primitive", kind="cylinder", radius=1, height=4, origin=[12, 0, 0])
        pattern = self.ok("linear_pattern", ref=peg["ref"], direction=[0, 1, 0], spacing=6, count=3)
        pattern_info = self.ok("inspect", ref=pattern["ref"])
        self.assertEqual(pattern_info["topology"]["components"], 3)
        self.assertAlmostEqual(pattern_info["volume"], 3 * math.pi * 4, delta=1e-3)
        spun = self.ok("circular_pattern", ref=peg["ref"], origin=[0, 0, 0], direction=[0, 0, 1], count=4)
        self.assertEqual(self.ok("inspect", ref=spun["ref"])["topology"]["components"], 4)
        mirrored = self.ok("mirror", ref=block["ref"], plane="yz")
        self.assertAlmostEqual(self.ok("inspect", ref=mirrored["ref"])["bounds"][1][0], 0, delta=1e-4)
        slider = self.ok("create_primitive", kind="box", size=[4, 4, 4], origin=[0, 0, 0])
        moved = self.ok(
            "transform", ref=slider["ref"],
            matrix=[1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        )
        bounds = self.ok("inspect", ref=moved["ref"])["bounds"]
        self.assertAlmostEqual(bounds[0][0], 5, delta=1e-4)
        singular = self.revision()
        self.assertEqual(self.err("transform", ref=block["ref"], matrix=[0] * 16)["code"], "INVALID_ARGUMENT")
        self.assertEqual(self.revision(), singular)

    def test_feature_edit_failure_undo_and_dependency_delete(self):
        created = self.ok("create_primitive", kind="box", size=[10, 20, 30], origin=[0, 0, 0])
        edited = self.ok("edit_feature", feature_id=created["feature_id"], parameters={"size": [10, 20, 40]})
        self.assertAlmostEqual(self.ok("inspect", ref=edited["ref"])["volume"], 8000, delta=1e-6)
        before = self.ok("snapshot")
        bad = self.err("edit_feature", feature_id=created["feature_id"], parameters={"size": [-1, 20, 40]})
        self.assertEqual(bad["code"], "INVALID_GEOMETRY")
        self.assertEqual(self.ok("snapshot")["revision"], before["revision"])
        self.assertAlmostEqual(self.ok("inspect", ref=created["ref"])["volume"], 8000, delta=1e-6)
        with self.app.fail_at("edit_feature", "after_geometry") as fault:
            injected = self.err("edit_feature", feature_id=created["feature_id"], parameters={"size": [10, 10, 10]})
        self.assertTrue(fault.triggered)
        self.assertEqual(injected["code"], "INJECTED_FAILURE")
        self.assertEqual(self.ok("snapshot")["revision"], before["revision"])
        self.ok("undo")
        self.assertAlmostEqual(self.ok("inspect", ref=created["ref"])["volume"], 6000, delta=1e-6)
        self.ok("redo")
        self.assertAlmostEqual(self.ok("inspect", ref=created["ref"])["volume"], 8000, delta=1e-6)
        other = self.ok("create_primitive", kind="box", size=[2, 2, 2], origin=[30, 0, 0])
        union = self.ok("boolean", kind="union", left=created["ref"], right=other["ref"])
        blocked = self.revision()
        self.assertEqual(self.err("delete", ref=created["ref"])["code"], "DEPENDENCY")
        self.assertEqual(self.revision(), blocked)
        self.ok("delete", ref=union["ref"])
        self.ok("delete", ref=created["ref"])
        self.assertNotIn(created["ref"], self.ok("snapshot")["references"])
        self.ok("undo")
        self.assertAlmostEqual(self.ok("inspect", ref=created["ref"])["volume"], 8000, delta=1e-6)
        fresh = self.ok("create_primitive", kind="sphere", radius=1, center=[0, 0, 0])
        self.assertNotEqual(fresh["ref"], created["ref"])

    def test_semantic_topology_and_stale_selection(self):
        box = self.ok("create_primitive", kind="box", size=[10, 20, 30], origin=[0, 0, 0])
        faces = self.ok("query_faces", ref=box["ref"], geom="plane", order="largest", limit=1)
        self.assertEqual(len(faces["faces"]), 1)
        self.assertAlmostEqual(faces["faces"][0]["area"], 600, delta=1e-6)
        self.assertEqual(faces["revision"], self.revision())
        edges = self.ok("query_edges", ref=box["ref"], geom="line", order="largest", limit=1)
        edge_id = edges["edges"][0]["id"]
        self.assertAlmostEqual(edges["edges"][0]["length"], 30, delta=1e-6)
        self.assertTrue(edges["edges"][0]["face_ids"])
        nearest = self.ok("query_faces", ref=box["ref"], nearest=[100, 10, 15], limit=1)
        self.assertEqual(nearest["faces"][0]["normal"][0], 1)
        section = self.ok("section", ref=box["ref"], origin=[0, 0, 15], normal=[0, 0, 1])
        self.assertAlmostEqual(section["area"], 200, delta=1e-4)
        self.assertTrue(section["loops"])
        other = self.ok("create_primitive", kind="box", size=[1, 1, 1], origin=[50, 0, 0])
        stale = self.err(
            "fillet", ref=box["ref"], radius=0.5, edge_ids=[edge_id], selection_revision=edges["revision"],
        )
        self.assertEqual(stale["code"], "STALE_SELECTION")
        self.assertIn(other["ref"], self.ok("snapshot")["references"])
        current = self.ok("query_edges", ref=box["ref"], geom="line", order="largest", limit=1)
        self.ok(
            "fillet", ref=box["ref"], radius=0.5,
            edge_ids=[current["edges"][0]["id"]], selection_revision=current["revision"],
        )
        missing = self.err(
            "fillet", ref=box["ref"], radius=0.2, edge_ids=["edge-missing"],
            selection_revision=self.revision(),
        )
        self.assertEqual(missing["code"], "TOPOLOGY_NOT_FOUND")
        self.ok("query_faces", ref=box["ref"])
        self.ok("rename", ref=box["ref"], name="renamed")
        report = self.ok("validate", scope="geometry", ref=box["ref"])
        self.assertNotIn("STALE_SELECTION", [item["code"] for item in report["findings"]])
        self.assertTrue(report["geometry_ready"])

    def test_validation_is_non_mutating_and_splits_manufacturing(self):
        solid = self.ok("create_primitive", kind="box", size=[10, 10, 10], origin=[0, 0, 0])
        before = self.ok("snapshot")
        ready = self.ok("validate", scope="manufacturing", profile="fdm", ref=solid["ref"])
        self.assertTrue(ready["ready"])
        self.assertEqual(self.ok("snapshot"), before)
        thin = self.ok("create_primitive", kind="box", size=[10, 10, 0.2], origin=[0, 0, 0])
        thin_report = self.ok("validate", scope="manufacturing", profile="fdm", ref=thin["ref"])
        self.assertFalse(thin_report["ready"])
        self.assertIn("THIN_WALL", [item["code"] for item in thin_report["findings"]])
        small = self.ok("create_primitive", kind="cylinder", radius=0.1, height=5, origin=[0, 0, 0])
        small_report = self.ok("validate", scope="manufacturing", profile="fdm", ref=small["ref"])
        self.assertIn("SMALL_FEATURE", [item["code"] for item in small_report["findings"]])
        left = self.ok("create_primitive", kind="box", size=[4, 4, 4], origin=[0, 0, 0])
        right = self.ok("create_primitive", kind="box", size=[4, 4, 4], origin=[20, 0, 0])
        disjoint = self.ok("boolean", kind="union", left=left["ref"], right=right["ref"])
        split = self.ok("validate", profile="fdm", ref=disjoint["ref"])
        self.assertIn("COMPONENT_COUNT", [item["code"] for item in split["findings"]])
        self.assertEqual(self.err("validate", profile="unknown-process")["code"], "INVALID_PROFILE")

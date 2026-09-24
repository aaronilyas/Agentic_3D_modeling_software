"""Regression coverage for document boundaries and untrusted project inputs."""
import base64
import copy
import json
import tempfile
import threading
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from cad.agent import Decision, RefinementLoop
from cad.content import ImageResource
from cad.features import dependency_graph
from cad.geometry.protocol import GeometryBackend
from cad.mcp_server import McpSession
from cad.project import FORMAT, VERSION, load_project
from cad.replay import replay
from cad.tools import TOOLS
from cad.topology import assign_ids
from tests.cad_support import CadTestCase
from tests.test_cad_assets import write_png


class HardeningTests(CadTestCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def path(self, name):
        return str(Path(self.directory.name) / name)

    def box(self, **kwargs):
        return self.ok("create_primitive", kind="box", size=[10, 20, 30], **kwargs)

    def test_inspection_does_not_change_persistent_state_or_history(self):
        body = self.box()
        before = self.ok("snapshot")
        faces = self.ok("query_faces", ref=body["ref"])
        edges = self.ok("query_edges", ref=body["ref"])
        self.err("query_faces", ref=body["ref"], geom="unsupported")
        self.assertEqual(self.ok("snapshot"), before)
        self.assertNotIn("pinned_selection", vars(self.app.document))
        self.ok("rename", ref=body["ref"], name="renamed")
        self.assertFalse(self.ok("validate", scope="geometry")["findings"])
        self.assertEqual(self.err("fillet", ref=body["ref"], radius=1,
                                  edge_ids=[edges["edges"][0]["id"]],
                                  selection_revision=edges["revision"])["code"], "STALE_SELECTION")
        self.assertEqual(self.err("render_selection", ref=body["ref"],
                                  face_ids=[faces["faces"][0]["id"]],
                                  selection_revision=faces["revision"])["code"], "STALE_SELECTION")

    def test_inputs_outputs_and_snapshots_do_not_alias_document_metadata(self):
        sketch = self.ok("create_sketch", profile=[[0, 0], [2, 0], [2, 2], [0, 2]])
        self.ok("extrude", sketch_id=sketch["feature_id"], height=3)
        snapshot = self.ok("snapshot")
        snapshot["sketches"][0]["profile"][0][0] = 999
        self.assertEqual(self.ok("snapshot")["sketches"][0]["profile"][0][0], 0)
        image = self.path("ref.png")
        write_png(Path(image), 4, 4)
        hint = {"view": "front"}
        added = self.ok("add_reference", path=image, camera_hint=hint)
        hint["view"] = "changed"
        added["camera_hint"]["view"] = "changed again"
        self.assertEqual(self.ok("inspect_reference", id=added["id"])["camera_hint"], {"view": "front"})

    def test_dependencies_bind_to_preceding_body_producer_and_sketch(self):
        sketch = self.ok("create_sketch", profile=[[0, 0], [2, 0], [2, 2], [0, 2]])
        extruded = self.ok("extrude", sketch_id=sketch["feature_id"], height=3)
        moved = self.ok("transform", ref=extruded["ref"],
                        matrix=[1, 0, 0, 4, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
        patterned = self.ok("linear_pattern", ref=extruded["ref"], direction=[1, 0, 0], spacing=5, count=2)
        graph = dependency_graph(self.app.document.features)
        self.assertEqual(graph[extruded["feature_id"]], (sketch["feature_id"],))
        self.assertEqual(graph[moved["feature_id"]], (extruded["feature_id"],))
        self.assertEqual(graph[patterned["feature_id"]], (moved["feature_id"],))
        self.assertEqual(self.err("delete", ref=extruded["ref"])["code"], "DEPENDENCY")
        self.ok("delete", ref=patterned["ref"])
        self.ok("rename", ref=extruded["ref"], name="renamed")
        self.ok("delete", ref=extruded["ref"])
        self.assertFalse(self.ok("snapshot")["references"])

    def test_replay_is_deterministic_and_failed_downstream_edit_is_atomic(self):
        body = self.box()
        self.ok("fillet", ref=body["ref"], radius=2, selector="vertical")
        before = self.ok("snapshot")
        for _ in range(2):
            solids, _ = replay(self.app.document.features, self.app.backend)
            self.assertEqual(self.app.backend.measure(solids[body["ref"]]),
                             self.app.backend.measure(self.app.document.resolve(body["ref"])))
        self.err("edit_feature", feature_id=body["feature_id"], parameters={"size": [1, 1, 1]})
        self.assertEqual(self.ok("snapshot"), before)
        self.ok("undo")
        self.assertAlmostEqual(self.ok("inspect", ref=body["ref"])["volume"], 6000)
        self.ok("redo")
        self.assertAlmostEqual(self.ok("inspect", ref=body["ref"])["volume"], before["bodies"][0]["volume"])

    def test_baked_duplicate_survives_source_deletion_and_project_replay(self):
        source = self.box()
        duplicated = self.ok("duplicate", ref=source["ref"], translation=[50, 0, 0])
        self.assertFalse(self.app.document.feature(duplicated["feature_id"]).input_refs)
        self.ok("delete", ref=source["ref"])
        self.ok("save_project", path=self.path("copy.cadproj"))
        self.ok("open_project", path=self.path("copy.cadproj"))
        self.assertEqual(self.ok("snapshot")["references"], [duplicated["ref"]])
        self.assertEqual(self.ok("inspect", ref=duplicated["ref"])["bounds"][0][0], 50)

    def test_open_undo_and_save_preserve_identifier_high_water_marks(self):
        self.box()
        self.ok("save_project", path=self.path("old.cadproj"))
        later = self.box()
        self.ok("open_project", path=self.path("old.cadproj"))
        self.ok("undo")
        fresh = self.box()
        self.assertNotEqual(fresh["ref"], later["ref"])
        self.assertEqual(len(self.ok("snapshot")["references"]), 3)
        self.ok("delete", ref=fresh["ref"])
        self.ok("save_project", path=self.path("current.cadproj"))
        loaded = load_project(self.path("current.cadproj"), self.app.backend)
        self.assertGreater(loaded["serials"]["body"], int(fresh["ref"].split("-")[1]))

    def test_nonfinite_feature_edits_never_reach_geometry_or_commit(self):
        body = self.box()
        before = self.ok("snapshot")
        for value in (float("nan"), float("inf"), -float("inf")):
            self.assertEqual(self.err("edit_feature", feature_id=body["feature_id"],
                                      parameters={"size": [value, 2, 3]})["code"], "INVALID_ARGUMENT")
            self.assertEqual(self.ok("snapshot"), before)

    def test_geometry_report_cannot_authorize_manufacturing_export(self):
        body = self.box()
        report = self.ok("validate", scope="geometry")
        destination = self.path("part.stl")
        Path(destination).write_bytes(b"KEEP")
        self.assertEqual(self.err("export", ref=body["ref"], path=destination, format="stl",
                                  validation=report)["code"], "INVALID_ARGUMENT")
        self.assertEqual(Path(destination).read_bytes(), b"KEEP")

    def test_legacy_v1_project_uses_features_even_with_unrelated_shape_cache(self):
        body = self.box()
        raw = self.app.document.feature(body["feature_id"]).to_public()
        for key in ("input_refs", "input_features", "editable_parameters", "replayable"):
            raw.pop(key)
        payload = {"format": FORMAT, "format_version": 1, "units": "mm", "features": [raw],
                   "sketches": {"feature-999": [[0, 0], [1, 0], [0, 1]]},
                   "shape_cache": ["shapes/ignored.brep"]}
        self.ok("open_project", path=self._archive(payload, {"shapes/ignored.brep": b"not geometry"}))
        self.assertAlmostEqual(self.ok("inspect", ref=body["ref"])["volume"], 6000)
        self.assertFalse(self.ok("snapshot")["sketches"])

    def test_backend_copy_and_mutation_ownership(self):
        self.assertIsInstance(self.app.backend, GeometryBackend)
        body = self.box()
        original = self.app.document.resolve(body["ref"])
        copied = self.app.backend.copy(original)
        self.assertFalse(original.wrapped.IsSame(copied.wrapped))
        self.app.backend.translate(copied, [100, 0, 0])
        self.app.backend.fillet(copied, 1, selector="vertical")
        self.assertEqual(self.app.backend.bounds(original), [[0, 0, 0], [10, 20, 30]])
        self.assertAlmostEqual(original.volume, 6000)

    def test_topology_ids_unique_deterministic_and_independent_of_query_sort(self):
        body = self.box()
        raw = self.ok("query_edges", ref=body["ref"])["edges"]
        self.assertTrue(all("index" not in r and "face_indices" not in r for r in raw))
        nearest = self.ok("query_edges", ref=body["ref"], nearest=[100, 0, 0])["edges"]
        self.assertEqual({r["id"] for r in raw}, {r["id"] for r in nearest})
        records = [{"geom": "plane", "area": 1, "center": [0, 0, 0], "index": i} for i in range(20)]
        first = assign_ids("face", records)
        self.assertEqual(first, assign_ids("face", list(reversed(records))))
        self.assertEqual(len({r["id"] for r in first}), len(records))
        with patch("cad.topology.hashlib.sha1") as digest:
            digest.return_value.hexdigest.return_value = "0" * 40
            collided = assign_ids("face", records)
        self.assertEqual(len({r["id"] for r in collided}), len(records))

    def test_render_faces_highlight_and_edges_fail_explicitly(self):
        body = self.box()
        faces = self.ok("query_faces", ref=body["ref"])
        args = {"ref": body["ref"], "views": ["front", "top"], "width": 80, "height": 64}
        before = self.ok("snapshot")
        plain = self.ok("render_views", **args)
        selected = self.ok("render_selection", **args, face_ids=[f["id"] for f in faces["faces"]],
                           selection_revision=faces["revision"])
        for a, b in zip(plain["views"], selected["views"]):
            self.assertNotEqual(a["png_base64"], b["png_base64"])
            self.assertEqual(a["metrics"]["silhouette_fraction"], b["metrics"]["silhouette_fraction"])
        # The rear face must be occluded when looking along +Y from the front.
        rear = next(f for f in faces["faces"] if f["normal"] == [0.0, 1.0, 0.0])
        hidden = self.ok("render_selection", **args, face_ids=[rear["id"]],
                         selection_revision=faces["revision"])
        self.assertEqual(plain["views"][0]["png_base64"], hidden["views"][0]["png_base64"])
        self.assertNotIn("edge_ids", TOOLS["render_selection"]["schema"]["properties"])
        self.assertEqual(self.err("render_selection", **args, edge_ids=["edge-id"],
                                  selection_revision=faces["revision"])["code"], "INVALID_ARGUMENT")
        self.assertEqual(self.ok("snapshot"), before)

    def _archive(self, payload, members=None):
        path = self.path("malformed.cadproj")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("project.json", json.dumps(payload))
            for name, data in (members or {}).items():
                archive.writestr(name, data)
        return path

    def test_malformed_projects_fail_without_partial_commit(self):
        body = self.box()
        before = self.ok("snapshot")
        valid = {"format": FORMAT, "format_version": VERSION, "units": "mm", "features": [], "assets": []}
        cases = [[], {**valid, "format_version": 999}, {**valid, "format_version": True},
                 {**valid, "features": {}}, {**valid, "names": []},
                 {**valid, "settings": {"units": "m"}}, {**valid, "serials": {"body": -1}},
                 {**valid, "revision": float("nan")}, {**valid, "assets": [{"id": "asset-1", "file": "../secret"}]}]
        feature = self.app.document.feature(body["feature_id"]).to_public()
        cases += [{**valid, "features": [feature, feature]},
                  {**valid, "features": [{**feature, "params": {**feature["params"], "brep_file": "shapes/cache"}}]},
                  {**valid, "features": [{**feature, "op": "unknown"}]},
                  {**valid, "features": [{**feature, "op": "duplicate", "params": {"brep_file": "shapes/missing"}}]},
                  {**valid, "features": [{**feature, "op": "transform", "params": {"target": "body-999"}}]}]
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.err("open_project", path=self._archive(payload))["code"], "INVALID_ARGUMENT")
                self.assertEqual(self.ok("snapshot"), before)
        for name in ("../outside", "/absolute", "assets/../../outside", "assets\\outside"):
            with self.subTest(member=name):
                self.assertEqual(self.err("open_project", path=self._archive(valid, {name: b"bad"}))["code"], "INVALID_ARGUMENT")
        with patch("cad.project.MAX_ARCHIVE_BYTES", 1):
            self.assertEqual(self.err("open_project", path=self._archive(valid))["code"], "INVALID_ARGUMENT")
        self.assertEqual(self.ok("snapshot"), before)

    def test_project_asset_content_and_metadata_are_verified(self):
        image = self.path("image.png")
        write_png(Path(image), 8, 4)
        self.ok("add_reference", path=image)
        self.ok("save_project", path=self.path("image.cadproj"))
        with zipfile.ZipFile(self.path("image.cadproj")) as archive:
            payload = json.loads(archive.read("project.json"))
            member = payload["assets"][0]["file"]
            data = archive.read(member)
        before = self.ok("snapshot")
        for update in ({"width": 9}, {"checksum": "incorrect"}, {"role": "invalid"},
                       {"calibration": {"p1": [0, 0], "p2": [0, 0], "distance_mm": 10}}):
            broken = copy.deepcopy(payload)
            broken["assets"][0].update(update)
            self.assertEqual(self.err("open_project", path=self._archive(broken, {member: data}))["code"], "INVALID_ARGUMENT")
        self.assertEqual(self.ok("snapshot"), before)

    def test_planner_receives_reference_render_and_previous_results_without_demo_assumptions(self):
        image = self.path("image.png")
        write_png(Path(image), 8, 4)
        self.ok("add_reference", path=image)
        contexts = []

        class Planner:
            def decide(_, context):
                contexts.append(context)
                if context["iteration"] == 0:
                    return Decision("execute", [("create_primitive", {"kind": "box", "size": [2, 2, 0.1], "name": "foil"})],
                                    goals=[{"metric": "volume_sum", "equals": 0.4, "tolerance": 1e-6}])
                if context["iteration"] == 1:
                    ref = context["snapshot"]["references"][0]
                    return Decision("execute", [("query_edges", {"ref": ref}),
                                                ("render_views", {"ref": ref, "views": ["top"]})])
                return Decision("stop")

        self.app.planner = Planner()
        result = self.ok("refine", request="inspect foil", max_iterations=4)
        self.assertEqual(result["status"], "satisfied")
        self.assertEqual(result["validation"]["scope"], "geometry")
        context = contexts[-1]
        self.assertEqual([r["op"] for r in context["previous_results"]], ["create_primitive", "query_edges", "render_views"])
        self.assertTrue(all(isinstance(item, ImageResource) for item in context["images"]))
        self.assertEqual(len(context["images"]), 2)
        self.assertEqual(context["images"][0].data, Path(image).read_bytes())
        self.assertTrue(context["images"][1].data.startswith(b"\x89PNG"))
        self.assertNotIn("png_base64", json.dumps(context["previous_results"]))

    def test_failed_planner_action_is_returned_to_planner_and_validation_failure_is_terminal(self):
        contexts = []

        class Planner:
            def decide(_, context):
                contexts.append(context)
                if len(contexts) == 1:
                    return Decision("execute", [("create_primitive", {"kind": "box", "size": [-1, 2, 3]})])
                return Decision("stop", goals=[{"metric": "volume_sum", "equals": 0, "tolerance": 0}],
                                validation={"scope": "manufacturing", "profile": "unknown"})

        result = RefinementLoop(self.app, Planner()).run("try", max_iterations=3)
        self.assertFalse(contexts[-1]["previous_results"][0]["result"]["ok"])
        self.assertEqual(result["status"], "validation_failed")
        self.assertFalse(self.ok("snapshot")["references"])

    def test_cancel_command_is_available_while_refinement_holds_document_lock(self):
        entered, release = threading.Event(), threading.Event()

        class Planner:
            def decide(_, context):
                entered.set()
                release.wait(3)
                return Decision("execute", [("create_primitive", {"kind": "box", "size": [1, 1, 1]})])

        self.app.planner = Planner()
        results = []
        worker = threading.Thread(target=lambda: results.append(self.app.execute("refine", {"request": "wait"})))
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            cancelled = threading.Event()
            canceller = threading.Thread(target=lambda: (self.app.execute("cancel_refine"), cancelled.set()))
            canceller.start()
            try:
                self.assertTrue(cancelled.wait(1), "cancel was blocked by the document lock")
            finally:
                release.set()
                canceller.join(5)
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]["value"]["status"], "cancelled")
        self.assertFalse(self.ok("snapshot")["references"])

    def test_missing_metadata_duplicate_members_and_failed_save_are_atomic(self):
        self.box()
        before = self.ok("snapshot")
        destination = self.path("bad.cadproj")
        for members in ([('unrelated', b'anything')], [('project.json', b'{')],
                        [('project.json', b'{}'), ('project.json', b'{}')]):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(destination, "w") as archive:
                    for name, data in members:
                        archive.writestr(name, data)
            self.assertEqual(self.err("open_project", path=destination)["code"], "INVALID_ARGUMENT")
            self.assertEqual(self.ok("snapshot"), before)
        Path(destination).write_bytes(b"KEEP")
        with patch("cad.project.MAX_ARCHIVE_BYTES", 1):
            self.assertEqual(self.err("save_project", path=destination)["code"], "INVALID_ARGUMENT")
        self.assertEqual(Path(destination).read_bytes(), b"KEEP")
        self.assertEqual(self.ok("snapshot"), before)

    def test_mcp_image_wire_output_and_oversized_response_recovery(self):
        body = self.box()
        transport = self.app.open_mcp()
        self.addCleanup(transport.close)

        def request(method, params):
            transport.send_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}))
            return json.loads(transport.recv_line(timeout=10))

        request("initialize", {})
        rendered = request("tools/call", {"name": "render_views", "arguments": {"ref": body["ref"], "views": ["front"]}})
        self.assertEqual(rendered["result"]["content"][1]["type"], "image")
        self.assertTrue(base64.b64decode(rendered["result"]["content"][1]["data"]).startswith(b"\x89PNG"))
        with patch("cad.mcp_server.MAX_LINE", 512):
            oversized = request("tools/call", {"name": "snapshot"})
            self.assertIn("transport limit", oversized["error"]["message"])
            self.assertEqual(request("ping", {})["result"], {})

    def test_mcp_images_resources_and_tool_schemas(self):
        session = McpSession(self.app.endpoint())
        image = self.path("image.png")
        write_png(Path(image), 8, 4)
        asset = self.ok("add_reference", path=image)
        before = self.ok("snapshot")
        reply = session._handle("tools/call", {"name": "inspect_reference", "arguments": {"id": asset["id"]}})
        images = [block for block in reply["content"] if block["type"] == "image"]
        self.assertEqual(base64.b64decode(images[0]["data"]), Path(image).read_bytes())
        listed = session._handle("resources/list", {})["resources"]
        read = session._handle("resources/read", {"uri": listed[0]["uri"]})
        self.assertEqual(base64.b64decode(read["contents"][0]["blob"]), Path(image).read_bytes())
        self.assertEqual(self.ok("snapshot"), before)
        body = self.box()
        reply = session._handle("tools/call", {"name": "render_views", "arguments": {"ref": body["ref"], "views": ["front"]}})
        self.assertEqual(reply["content"][1]["type"], "image")
        self.assertNotIn("png_base64", reply["content"][0]["text"])
        self.assertIn("image_uri", reply["structuredContent"]["value"]["views"][0])
        self.assertEqual(set(TOOLS), set(self.app.operation_names()))
        for tool in TOOLS.values():
            schema = tool["schema"]
            self.assertEqual(schema["type"], "object")
            self.assertTrue(set(schema["required"]) <= set(schema["properties"]))
            json.dumps(schema, allow_nan=False)

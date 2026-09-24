"""Bounded refinement and real MCP calls. Tool success is not request completion."""

import json
import threading

from cad.agent import Decision, RefinementLoop

from tests.cad_support import CadTestCase


class _OneThenCancel:
    def __init__(self, cancel):
        self.cancel = cancel
        self.calls = 0

    def decide(self, _context):
        self.calls += 1
        if self.calls == 1:
            return Decision("execute", [(
                "create_primitive",
                {"kind": "box", "size": [2, 2, 2], "origin": [0, 0, 0], "name": "first"},
            )], "create the first solid")
        self.cancel.set()
        return Decision("execute", [(
            "create_primitive",
            {"kind": "box", "size": [3, 3, 3], "origin": [10, 0, 0]},
        )], "this operation must not run")


class AgentTests(CadTestCase):
    def test_bracket_refinement_uses_measurement_not_the_first_success(self):
        result = self.ok("refine", request="Make a mounting bracket", max_iterations=12)
        self.assertEqual(result["status"], "satisfied")
        self.assertGreaterEqual(result["iterations"], 8)
        self.assertFalse(result["mismatches"])
        self.assertTrue(result["validation"]["ready"])
        self.assertGreater(result["visual"]["views"][0]["metrics"]["silhouette_fraction"], 0.02)
        operations = [item.get("op") for item in result["evidence"] if item.get("phase") == "execute"]
        self.assertIn("edit_feature", operations)
        self.assertIn("linear_pattern", operations)
        self.assertIn("fillet", operations)
        self.assertLess(operations.index("create_primitive"), operations.index("edit_feature"))
        bracket = next(body for body in self.ok("snapshot")["bodies"] if body["name"] == "bracket")
        faces = self.ok("query_faces", ref=bracket["ref"], geom="cylinder")
        holes = [face for face in faces["faces"] if face["radius"] >= 1.5]
        self.assertEqual(len(holes), 2)
        for face in holes:
            self.assertAlmostEqual(face["radius"], 2, delta=0.02)
        self.assertIn("linear_pattern", [feature["op"] for feature in self.ok("snapshot")["features"]])

    def test_box_request_corrects_its_own_first_solid(self):
        result = self.ok("refine", request="box 10 20 30", max_iterations=6)
        self.assertEqual(result["status"], "satisfied")
        self.assertGreaterEqual(result["iterations"], 2)
        body = self.ok("snapshot")["bodies"][0]
        self.assertAlmostEqual(body["volume"], 6000, delta=1e-6)
        edits = [item for item in result["evidence"] if item.get("op") == "edit_feature"]
        self.assertTrue(edits)
        self.assertTrue(edits[0]["result"]["ok"])

    def test_cancel_stops_before_later_operations(self):
        cancel = threading.Event()
        report = RefinementLoop(self.app, _OneThenCancel(cancel), cancel_event=cancel).run("anything", max_iterations=4)
        self.assertEqual(report["status"], "cancelled")
        bodies = self.ok("snapshot")["bodies"]
        self.assertEqual(len(bodies), 1)
        self.assertAlmostEqual(bodies[0]["volume"], 8, delta=1e-6)

    def test_impossible_request_does_not_invent_geometry(self):
        before = self.ok("snapshot")
        result = self.ok("refine", request="design a cathedral", max_iterations=3)
        self.assertEqual(result["status"], "impossible")
        self.assertEqual(self.ok("snapshot")["references"], before["references"])
        self.assertEqual(self.ok("snapshot")["revision"], before["revision"])

    def test_mcp_create_and_inspect_use_the_live_document(self):
        transport = self.app.open_mcp()
        self.addCleanup(transport.close)
        self._request(transport, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "cad-tests", "version": "1"},
        })
        transport.send_line(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        listed = self._request(transport, "tools/list", {})
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertIn("create_primitive", names)
        self.assertIn("refine", names)
        self.assertNotIn("create_ring", names)
        schema = next(tool for tool in listed["result"]["tools"] if tool["name"] == "create_primitive")
        self.assertEqual(schema["inputSchema"]["properties"]["kind"]["enum"], ["box", "cylinder", "sphere"])
        self.assertFalse(schema["inputSchema"]["additionalProperties"])
        created = self._request(transport, "tools/call", {
            "name": "create_primitive",
            "arguments": {"kind": "box", "size": [2, 3, 4], "origin": [0, 0, 0], "name": "mcp-box"},
        })
        envelope = created["result"]["structuredContent"]
        self.assertTrue(envelope["ok"])
        self.assertFalse(created["result"]["isError"])
        ref = envelope["value"]["ref"]
        inspected = self._request(transport, "tools/call", {
            "name": "inspect", "arguments": {"ref": ref},
        })
        info = inspected["result"]["structuredContent"]["value"]
        self.assertAlmostEqual(info["volume"], 24, delta=1e-6)
        self.assertEqual(self.ok("inspect", ref=ref)["volume"], info["volume"])
        self.assertTrue(self.app.endpoint().observed_calls)
        failed = self._request(transport, "tools/call", {
            "name": "create_primitive", "arguments": {"kind": "box", "size": [0, 1, 1]},
        })
        self.assertTrue(failed["result"]["isError"])
        self.assertFalse(failed["result"]["structuredContent"]["ok"])
        self.assertEqual(len(self.ok("snapshot")["references"]), 1)

    def _request(self, transport, method, params):
        self._request_id = getattr(self, "_request_id", 0) + 1
        transport.send_line(json.dumps({
            "jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params,
        }))
        while True:
            message = json.loads(transport.recv_line(timeout=10))
            if message.get("id") == self._request_id:
                self.assertIn("result", message, message)
                return message

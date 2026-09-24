"""Bounded inspect / model / measure / render / refine loop.

A successful CAD call is evidence, not completion. The document and structured
tool results decide whether measurable goals are satisfied. Visual metrics are
recorded separately from exact geometry.
"""

from __future__ import annotations

import copy
import math

from cad.errors import InvalidArgument


class Decision:
    def __init__(self, kind: str, operations=None, reason: str = "", goals=None):
        self.kind = kind
        self.operations = list(operations or [])
        self.reason = reason
        self.goals = goals

    def public(self) -> dict:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "operations": [{"op": name, "arguments": args} for name, args in self.operations],
            "goals": self.goals,
        }


class GoalPlanner:
    """Deterministic planner. It reads the document; it does not store geometry."""

    def decide(self, context: dict) -> Decision:
        request = str(context.get("request") or "")
        lowered = request.lower()
        if "bracket" in lowered or "mounting" in lowered:
            return self._bracket(context)
        if lowered.startswith("box "):
            return self._box(context, lowered)
        return Decision(
            "impossible",
            reason="the built-in planner does not have a modeling sequence for this request",
        )

    def _box(self, context: dict, request: str) -> Decision:
        parts = request.split()
        if len(parts) != 4:
            return Decision("impossible", reason="box requests use: box sx sy sz")
        try:
            size = [float(parts[1]), float(parts[2]), float(parts[3])]
        except ValueError:
            return Decision("impossible", reason="box dimensions must be numbers")
        if any(value <= 0 or not math.isfinite(value) for value in size):
            return Decision("impossible", reason="box dimensions must be positive")
        goals = [{"metric": "volume_sum", "equals": size[0] * size[1] * size[2], "tolerance": 0.01}]
        features = _features(context)
        boxes = [feature for feature in features if feature["op"] == "box"]
        if not boxes:
            wrong = [size[0], size[1], size[2] * 0.5]
            return Decision(
                "execute",
                [("create_primitive", {"kind": "box", "size": wrong, "origin": [0, 0, 0], "name": "block"})],
                reason="create an initial block, then correct it from measurement",
                goals=goals,
            )
        if context.get("mismatches"):
            return Decision(
                "execute",
                [("edit_feature", {"feature_id": boxes[0]["id"], "parameters": {"size": size}})],
                reason="measured volume does not match the requested box",
                goals=goals,
            )
        return Decision("stop", reason="measured box volume matches the request", goals=goals)

    def _bracket(self, context: dict) -> Decision:
        goals = [
            {"metric": "named_volume", "name": "bracket", "min": 14000, "max": 14450},
            {"metric": "hole_count", "name": "bracket", "equals": 2},
            {"metric": "hole_diameter", "name": "bracket", "equals": 4.0, "tolerance": 0.05},
            {"metric": "bounds_size", "name": "bracket", "min": [59.5, 39.5, 23.5], "max": [60.5, 40.5, 24.5]},
            {"metric": "feature", "op": "linear_pattern", "min_count": 1},
            {"metric": "feature", "op": "fillet", "min_count": 1},
        ]
        features = _features(context)
        boxes = [feature for feature in features if feature["op"] == "box"]
        if not boxes:
            return Decision(
                "execute",
                [("create_primitive", {
                    "kind": "box", "size": [60, 40, 4], "origin": [0, 0, 0], "name": "plate",
                })],
                reason="start the mounting bracket with a plate",
                goals=goals,
            )
        if len(boxes) == 1:
            return Decision(
                "execute",
                [("create_primitive", {
                    "kind": "box", "size": [60, 4, 20], "origin": [0, 36, 4], "name": "rib",
                })],
                reason="add the vertical rib",
                goals=goals,
            )
        booleans = [feature for feature in features if feature["op"] == "boolean"]
        unions = [feature for feature in booleans if feature["params"].get("kind") == "union"]
        if not unions:
            return Decision(
                "execute",
                [("boolean", {
                    "kind": "union", "left": boxes[0]["output_ref"], "right": boxes[1]["output_ref"],
                    "name": "joined",
                })],
                reason="join the plate and rib",
                goals=goals,
            )
        cylinders = [feature for feature in features if feature["op"] == "cylinder"]
        if not cylinders:
            return Decision(
                "execute",
                [("create_primitive", {
                    "kind": "cylinder", "radius": 1.5, "height": 10, "origin": [10, 20, -3],
                    "name": "cutter",
                })],
                reason="place a cutter; its diameter is checked before the bracket is accepted",
                goals=goals,
            )
        patterns = [feature for feature in features if feature["op"] == "linear_pattern"]
        if not patterns:
            return Decision(
                "execute",
                [("linear_pattern", {
                    "ref": cylinders[0]["output_ref"], "direction": [1, 0, 0], "spacing": 40, "count": 2,
                })],
                reason="pattern the cutter across the plate",
                goals=goals,
            )
        subtracts = [feature for feature in booleans if feature["params"].get("kind") == "subtract"]
        if not subtracts:
            return Decision(
                "execute",
                [("boolean", {
                    "kind": "subtract", "left": unions[0]["output_ref"],
                    "right": patterns[0]["output_ref"], "name": "bracket",
                })],
                reason="cut the patterned holes through the bracket",
                goals=goals,
            )
        diameters = context.get("hole_diameters") or []
        if not diameters or any(abs(diameter - 4.0) > 0.05 for diameter in diameters):
            return Decision(
                "execute",
                [("edit_feature", {"feature_id": cylinders[0]["id"], "parameters": {"radius": 2.0}})],
                reason="measured hole diameter does not match 4 mm",
                goals=goals,
            )
        fillets = [feature for feature in features if feature["op"] == "fillet"]
        if not fillets:
            return Decision(
                "execute",
                [("fillet", {
                    "ref": subtracts[0]["output_ref"], "radius": 1.0,
                    "selector": {"kind": "longest_vertical", "count": 4},
                })],
                reason="round the four longest vertical edges",
                goals=goals,
            )
        return Decision("stop", reason="geometry matches the bracket goals", goals=goals)


class RefinementLoop:
    def __init__(self, application, planner, *, cancel_event=None):
        self.application = application
        self.planner = planner
        self.cancel_event = cancel_event

    def run(self, request: str, goals=None, max_iterations: int = 8) -> dict:
        if not isinstance(request, str) or not request.strip():
            raise InvalidArgument("request must be a nonempty string")
        if isinstance(max_iterations, bool) or not isinstance(max_iterations, int):
            raise InvalidArgument("max_iterations must be an integer")
        max_iterations = max(1, min(max_iterations, 20))
        active_goals = list(goals or [])
        evidence = []
        renders = []
        status = "limit"
        reason = "iteration limit reached"
        iterations = 0
        for iteration in range(max_iterations):
            iterations = iteration + 1
            if self._cancelled():
                status, reason = "cancelled", "refinement was cancelled"
                break
            context = self._context(request, active_goals)
            context["iteration"] = iteration
            decision = self.planner.decide(context)
            if decision.goals and not active_goals:
                active_goals = list(decision.goals)
                context = self._context(request, active_goals)
                if decision.kind == "stop" and context["mismatches"]:
                    decision = self.planner.decide(context)
            mismatches = context["mismatches"]
            evidence.append({
                "iteration": iteration,
                "phase": "plan",
                "decision": decision.public(),
                "mismatches": mismatches,
                "revision": context["snapshot"].get("revision"),
            })
            if decision.kind == "impossible":
                status, reason = "impossible", decision.reason
                break
            if decision.kind == "stop" or (active_goals and not mismatches and not decision.operations):
                status, reason = "review", decision.reason or "planner stopped"
                break
            if not decision.operations:
                status, reason = "incomplete", "planner produced no operation while goals remain open"
                break
            failed = False
            for name, arguments in decision.operations:
                if self._cancelled():
                    status, reason = "cancelled", "refinement was cancelled"
                    failed = True
                    break
                result = self.application.execute(name, arguments)
                evidence.append({
                    "iteration": iteration,
                    "phase": "execute",
                    "op": name,
                    "result": _without_images(result),
                })
                if not result.get("ok"):
                    failed = True
                    break
            if status == "cancelled":
                break
            if failed:
                continue
        else:
            status, reason = "limit", "iteration limit reached before the goals were satisfied"
        final = self._context(request, active_goals)
        if status in {"limit", "review"} and active_goals and not final["mismatches"]:
            status, reason = "review", "measurable goals match the latest document"
        validation = self.application.execute("validate", {
            "scope": "manufacturing",
            "profile": "fdm",
            "ref": _named_ref(final["snapshot"], "bracket"),
        })
        evidence.append({"phase": "validate", "result": _without_images(validation)})
        if final["snapshot"].get("references"):
            rendered = self.application.execute("render_views", {"views": ["isometric", "front", "top"]})
            renders = (rendered.get("value") or {}).get("views", []) if rendered.get("ok") else []
            evidence.append({"phase": "render", "result": _without_images(rendered)})
        mismatches = final["mismatches"]
        if status == "review":
            if active_goals and not mismatches and (validation.get("value") or {}).get("geometry_ready", False):
                ready = (validation.get("value") or {}).get("ready")
                status = "satisfied" if ready else "validation_failed"
                reason = "measurable goals match the document" if ready else "goals match but manufacturing validation reported errors"
            elif active_goals and mismatches:
                status = "incomplete"
                reason = "planner stopped before measurable goals were satisfied"
            elif not active_goals:
                status = "stopped"
        report = {
            "status": status,
            "reason": reason,
            "iterations": iterations,
            "revision": final["snapshot"].get("revision"),
            "goals": active_goals,
            "mismatches": mismatches,
            "evidence": evidence,
            "validation": (validation.get("value") if validation.get("ok") else validation.get("error")),
            "visual": {
                "views": [_view_public(view) for view in renders],
                "references": final["references"],
                "note": (
                    "Rendered views supplement exact CAD inspection. "
                    "An uncalibrated image does not establish absolute scale or depth."
                ),
            },
            "units": "mm",
        }
        return report

    def _context(self, request: str, goals: list) -> dict:
        snapshot = self._value("snapshot")
        references = self._value("list_references").get("references", [])
        inspection = {}
        diameters = []
        for body in snapshot.get("bodies", []):
            faces = self._value("query_faces", {"ref": body["ref"]})
            inspection[body["ref"]] = faces
            if body.get("name") == "bracket":
                diameters = _hole_diameters(faces.get("faces", []), min_diameter=3.0)
        mismatches = evaluate_goals(snapshot, inspection, goals)
        return {
            "request": request,
            "snapshot": snapshot,
            "references": references,
            "inspection": inspection,
            "hole_diameters": diameters,
            "mismatches": mismatches,
        }

    def _value(self, operation: str, arguments: dict | None = None) -> dict:
        result = self.application.execute(operation, arguments or {})
        if not result.get("ok"):
            return {}
        return result["value"]

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()


def evaluate_goals(snapshot: dict, inspection: dict, goals: list) -> list[dict]:
    mismatches = []
    for goal in goals:
        metric = goal.get("metric")
        if metric == "volume_sum":
            total = sum(body["volume"] for body in snapshot.get("bodies", []))
            if abs(total - float(goal["equals"])) > float(goal.get("tolerance", 0)):
                mismatches.append({"metric": metric, "measured": total, "expected": goal["equals"]})
        elif metric == "named_volume":
            body = _named(snapshot, goal["name"])
            if body is None:
                mismatches.append({"metric": metric, "measured": None, "expected": goal["name"]})
            elif not (float(goal["min"]) <= body["volume"] <= float(goal["max"])):
                mismatches.append({"metric": metric, "measured": body["volume"], "expected": [goal["min"], goal["max"]]})
        elif metric == "bounds_size":
            body = _named(snapshot, goal["name"])
            if body is None:
                mismatches.append({"metric": metric, "measured": None, "expected": goal["name"]})
            else:
                size = [body["bounds"][1][axis] - body["bounds"][0][axis] for axis in range(3)]
                if any(size[axis] < goal["min"][axis] or size[axis] > goal["max"][axis] for axis in range(3)):
                    mismatches.append({"metric": metric, "measured": size, "expected": [goal["min"], goal["max"]]})
        elif metric in {"hole_count", "hole_diameter"}:
            body = _named(snapshot, goal["name"])
            faces = [] if body is None else inspection.get(body["ref"], {}).get("faces", [])
            diameters = _hole_diameters(faces, goal.get("min_diameter", 3.0))
            if metric == "hole_count" and len(diameters) != int(goal["equals"]):
                mismatches.append({"metric": metric, "measured": len(diameters), "expected": goal["equals"]})
            if metric == "hole_diameter":
                tolerance = float(goal.get("tolerance", 0))
                if not diameters or any(abs(diameter - float(goal["equals"])) > tolerance for diameter in diameters):
                    mismatches.append({"metric": metric, "measured": diameters, "expected": goal["equals"]})
        elif metric == "feature":
            count = sum(1 for feature in snapshot.get("features", []) if feature.get("op") == goal["op"])
            if count < int(goal.get("min_count", 1)):
                mismatches.append({"metric": metric, "measured": count, "expected": goal["op"]})
        else:
            mismatches.append({"metric": metric, "measured": None, "expected": "supported metric"})
    return mismatches


def _hole_diameters(faces: list, min_diameter: float) -> list[float]:
    """Cylindrical faces at or above min_diameter. Straight fillets are smaller cylinders."""
    diameters = []
    for face in faces:
        radius = face.get("radius")
        if face.get("geom") == "cylinder" and radius:
            diameter = 2.0 * float(radius)
            if diameter + 1e-9 >= float(min_diameter):
                diameters.append(diameter)
    return diameters


def _features(context: dict) -> list[dict]:
    return list(context.get("snapshot", {}).get("features", []))


def _named(snapshot: dict, name: str) -> dict | None:
    for body in snapshot.get("bodies", []):
        if body.get("name") == name:
            return body
    return None


def _named_ref(snapshot: dict, name: str):
    body = _named(snapshot, name)
    return None if body is None else body["ref"]


def _without_images(result: dict) -> dict:
    copied = copy.deepcopy(result)
    value = copied.get("value")
    if isinstance(value, dict) and isinstance(value.get("views"), list):
        for view in value["views"]:
            if "png_base64" in view:
                view["png_base64"] = f"<{len(view['png_base64'])} chars>"
    return copied


def _view_public(view: dict) -> dict:
    return {
        "name": view.get("name"),
        "width": view.get("width"),
        "height": view.get("height"),
        "metrics": view.get("metrics"),
        "png_base64": view.get("png_base64"),
        "camera": view.get("camera"),
    }

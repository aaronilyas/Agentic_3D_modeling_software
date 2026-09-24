"""Deterministic demo sequences, not a general-purpose CAD intelligence layer."""

import math
from cad.planning import Decision
from cad.goals import _features, _named_ref, _hole_diameters


class DeterministicPlanner:
    """Deterministic planner. It reads the document; it does not store geometry."""

    def decide(self, context: dict) -> Decision:
        decision = self._decide(context)
        ref = _named_ref(context["snapshot"], "bracket")
        decision.validation = {"scope": "manufacturing", "profile": "fdm"}
        if ref:
            decision.validation["ref"] = ref
        return decision

    def _decide(self, context: dict) -> Decision:
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
            {"metric": "hole_count", "min_diameter": 3.0, "name": "bracket", "equals": 2},
            {"metric": "hole_diameter", "min_diameter": 3.0, "name": "bracket", "equals": 4.0, "tolerance": 0.05},
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
        ref = _named_ref(context["snapshot"], "bracket")
        faces = context["inspection"].get(ref, {}).get("faces", [])
        diameters = _hole_diameters(faces, min_diameter=3.0)
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



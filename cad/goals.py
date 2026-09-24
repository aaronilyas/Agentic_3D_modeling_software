"""Measurable goal evaluation, independent of planning or execution."""

from cad.numbers import finite_tree
from cad.errors import InvalidArgument

def evaluate_goals(snapshot: dict, inspection: dict, goals: list) -> list[dict]:
    if not isinstance(goals, list) or any(not isinstance(goal, dict) for goal in goals):
        raise InvalidArgument("goals must be a list of objects")
    finite_tree(goals)
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
            diameters = _hole_diameters(faces, goal.get("min_diameter", 0.0))
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



"""Non-mutating geometry and manufacturing checks.

Manufacturing profiles are generic process presets. Findings never change the document.
"""

from __future__ import annotations

import math

from cad.errors import InvalidArgument, InvalidProfile

PROFILES = {
    "geometry": {"id": "geometry", "process": "geometry", "max_components": 1000},
    "fdm": {"id": "fdm", "process": "fdm", "min_wall": 0.8, "min_feature": 0.4, "max_components": 1},
    "sla": {"id": "sla", "process": "sla", "min_wall": 0.4, "min_feature": 0.3, "max_components": 1},
    "cnc": {"id": "cnc", "process": "cnc", "min_wall": 1.0, "min_feature": 1.0, "max_components": 8},
    "casting": {"id": "casting", "process": "casting", "min_wall": 1.5, "min_feature": 1.0, "max_components": 1},
}


def resolve_profile(profile: object) -> dict:
    if profile is None or profile == "geometry":
        return dict(PROFILES["geometry"])
    if isinstance(profile, str):
        if profile not in PROFILES:
            raise InvalidProfile(f"unknown profile {profile}")
        return dict(PROFILES[profile])
    if not isinstance(profile, dict):
        raise InvalidProfile("profile must be a name or an object")
    rules = {"id": str(profile.get("id") or "custom"), "process": str(profile.get("process") or "custom")}
    if "max_components" in profile:
        value = profile["max_components"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise InvalidProfile("max_components must be a positive integer")
        rules["max_components"] = value
    else:
        rules["max_components"] = 1000
    for key in ("min_wall", "min_feature"):
        if key in profile:
            value = profile[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
                raise InvalidProfile(f"{key} must be a positive finite number")
            rules[key] = float(value)
    rules["units"] = "mm"
    return rules


def validate_shape(shape, backend, rules: dict, *, label: str) -> list[dict]:
    findings = []
    topology = backend.topology(shape)
    volume = float(shape.volume or 0.0)
    if not topology["valid"]:
        findings.append(_finding("INVALID_SHAPE", f"{label} is not a valid B-rep", "error"))
    if volume <= 1e-9:
        findings.append(_finding("ZERO_VOLUME", f"{label} has no volume", "error"))
    if not topology["closed"]:
        findings.append(_finding("OPEN_SHELL", f"{label} is not a closed solid", "error"))
    if not topology["manifold"]:
        findings.append(_finding("NON_MANIFOLD", f"{label} is not manifold", "error"))
    if topology["components"] > rules["max_components"]:
        findings.append(_finding(
            "COMPONENT_COUNT",
            f"{label} has {topology['components']} components; limit is {rules['max_components']}",
            "error",
        ))
    if "min_wall" in rules or "min_feature" in rules:
        query = backend.query(shape)
        if "min_wall" in rules:
            wall = _min_wall(shape, backend, query["faces"])
            if wall is not None and wall + 1e-9 < rules["min_wall"]:
                findings.append({
                    "code": "THIN_WALL",
                    "message": f"{label} wall {wall:.4f} mm is below {rules['min_wall']} mm",
                    "severity": "error",
                    "measured": wall,
                    "required": rules["min_wall"],
                    "units": "mm",
                })
        if "min_feature" in rules:
            feature = _min_feature(query["faces"])
            if feature is not None and feature + 1e-9 < rules["min_feature"]:
                findings.append({
                    "code": "SMALL_FEATURE",
                    "message": f"{label} feature {feature:.4f} mm is below {rules['min_feature']} mm",
                    "severity": "error",
                    "measured": feature,
                    "required": rules["min_feature"],
                    "units": "mm",
                })
    return findings


def stale_selection_finding(selection: dict | None, revision: int) -> dict | None:
    if not selection:
        return None
    if selection.get("revision") == revision:
        return None
    return _finding(
        "STALE_SELECTION",
        "a pinned topology selection is from revision "
        f"{selection.get('revision')} and the document is at revision {revision}",
        "warning",
    )


def report(revision: int, rules: dict, findings: list[dict], scope: str) -> dict:
    errors = [item for item in findings if item.get("severity") == "error"]
    return {
        "revision": int(revision),
        "scope": scope,
        "rules": rules,
        "ready": not errors,
        "geometry_ready": not any(item["code"] in {
            "INVALID_SHAPE", "ZERO_VOLUME", "OPEN_SHELL", "NON_MANIFOLD", "COMPONENT_COUNT",
        } for item in errors),
        "findings": findings,
        "units": "mm",
    }


def _min_wall(shape, backend, faces: list[dict]) -> float | None:
    planes = [face for face in faces if face.get("geom") == "plane" and face.get("normal")]
    measured = None
    for index, left in enumerate(planes):
        normal = left["normal"]
        for right in planes[index + 1:]:
            other = right["normal"]
            dot = sum(normal[axis] * other[axis] for axis in range(3))
            if dot > -0.95:
                continue
            delta = [right["center"][axis] - left["center"][axis] for axis in range(3)]
            distance = abs(sum(delta[axis] * normal[axis] for axis in range(3)))
            if distance <= 1e-6:
                continue
            midpoint = [(left["center"][axis] + right["center"][axis]) / 2 for axis in range(3)]
            if not backend.contains(shape, midpoint):
                continue
            measured = distance if measured is None else min(measured, distance)
    return measured


def _min_feature(faces: list[dict]) -> float | None:
    sizes = []
    for face in faces:
        radius = face.get("radius")
        if not radius:
            continue
        if face.get("geom") == "cylinder":
            sizes.append(2.0 * float(radius))
        elif face.get("geom") == "torus":
            sizes.append(float(radius))
    if not sizes:
        return None
    return min(sizes)


def _finding(code: str, message: str, severity: str) -> dict:
    if severity not in {"error", "warning"}:
        raise InvalidArgument("finding severity must be error or warning")
    return {"code": code, "message": message, "severity": severity}

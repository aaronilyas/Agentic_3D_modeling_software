"""Manufacturing profile checks, analytic thin features, and mesh diagnostics."""

from __future__ import annotations

import copy
import math

from jewelry.document import Document
from jewelry.errors import InvalidProfile
from jewelry.kernel.evaluate import bake_transform
from jewelry.kernel.solids import Annulus, Body, CsgBody, Cylinder, TransformedBody
from jewelry.mesh import mesh_findings


def parse_profile(profile: object) -> dict:
    if not isinstance(profile, dict) or not profile:
        raise InvalidProfile()
    for key in ("id", "version", "units", "min_wall", "min_prong", "max_components"):
        if key not in profile:
            raise InvalidProfile(f"profile missing {key}")
    if profile["units"] != "mm":
        raise InvalidProfile("profile units must be 'mm'")
    min_wall = _positive_finite(profile["min_wall"], "min_wall")
    min_prong = _positive_finite(profile["min_prong"], "min_prong")
    max_components = profile["max_components"]
    if isinstance(max_components, bool) or not isinstance(max_components, int) or max_components < 1:
        raise InvalidProfile("max_components must be a positive integer")
    rules = {
        "id": profile["id"],
        "version": profile["version"],
        "units": "mm",
        "min_wall": min_wall,
        "min_prong": min_prong,
        "max_components": max_components,
    }
    if "max_wall" in profile:
        max_wall = _finite_number(profile["max_wall"], "max_wall")
        if max_wall < min_wall:
            raise InvalidProfile("max_wall must not be below min_wall")
        rules["max_wall"] = max_wall
    return rules


def validate_document(document: Document, profile: object) -> dict:
    rules = parse_profile(profile)
    findings: list[dict] = []
    bodies = list(document.bodies.values())
    components = sum(max(1, int(body.topology().get("components", 1))) for body in bodies)
    if len(bodies) > rules["max_components"] or components > rules["max_components"]:
        findings.append({
            "code": "UNINTENDED_BODY",
            "message": "live solid count exceeds max_components",
            "severity": "error",
        })
    walls = [thickness for body in bodies for thickness in _annulus_walls(body)]
    prongs = [diameter for body in bodies for diameter in _additive_cylinder_diameters(body)]
    if walls:
        measured = min(walls)
        required = rules["min_wall"]
        if measured < required:
            findings.append(_thin_feature("wall", measured, required))
    if prongs:
        measured = min(prongs)
        required = rules["min_prong"]
        if measured < required:
            findings.append(_thin_feature("prong", measured, required))
    return _report(document.revision, rules, findings)


def validate_mesh(vertices: object, triangles: object, profile: object, *, revision: int) -> dict:
    rules = parse_profile(profile)
    findings, metrics = mesh_findings(vertices, triangles)
    if metrics["components"] > rules["max_components"]:
        findings.append({
            "code": "UNINTENDED_BODY",
            "message": "mesh component count exceeds max_components",
            "severity": "error",
        })
    return _report(revision, rules, findings)


def _report(revision: int, rules: dict, findings: list[dict]) -> dict:
    ready = not any(item.get("severity") == "error" for item in findings)
    copied = copy.deepcopy(rules)
    return {
        "revision": int(revision),
        "rules": copied,
        "profile": copy.deepcopy(copied),
        "ready": ready,
        "findings": findings,
    }


def _thin_feature(feature_type: str, measured: float, required: float) -> dict:
    return {
        "code": "THIN_FEATURE",
        "message": f"{feature_type} {measured} mm is below {required} mm",
        "severity": "error",
        "feature_type": feature_type,
        "measured": float(measured),
        "required": required,
    }


def _positive_finite(value: object, name: str) -> float:
    number = _finite_number(value, name)
    if number <= 0.0:
        raise InvalidProfile(f"{name} must be greater than zero")
    return number


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidProfile(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise InvalidProfile(f"{name} must be a finite number")
    return number


def _annulus_walls(body: Body) -> list[float]:
    body = bake_transform(body)
    if isinstance(body, Annulus):
        return [body.outer_radius - body.inner_radius]
    if isinstance(body, CsgBody):
        return _annulus_walls(body.left) + _annulus_walls(body.right)
    if isinstance(body, TransformedBody):
        return _annulus_walls(body.base)
    return []


def _additive_cylinder_diameters(body: Body, additive: bool = True) -> list[float]:
    body = bake_transform(body)
    if isinstance(body, Cylinder):
        return [2.0 * body.radius] if additive else []
    if isinstance(body, CsgBody):
        if body.op == "union":
            return (
                _additive_cylinder_diameters(body.left, additive)
                + _additive_cylinder_diameters(body.right, additive)
            )
        return (
            _additive_cylinder_diameters(body.left, additive)
            + _additive_cylinder_diameters(body.right, False)
        )
    if isinstance(body, TransformedBody):
        return _additive_cylinder_diameters(body.base, additive)
    return []

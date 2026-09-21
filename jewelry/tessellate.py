"""Tessellate analytic CSG at export time. Document bodies remain analytic."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from jewelry.errors import ContractError
from jewelry.kernel.evaluate import bake_transform
from jewelry.kernel.numeric import KERNEL_NUMERIC_TOL, as_finite_number
from jewelry.kernel.solids import (
    Annulus,
    Body,
    Box,
    CsgBody,
    Cylinder,
    ExtrudedPolygon,
    RevolvedSolid,
    Sphere,
    TransformedBody,
)

_MAX_SEGMENTS = 4096
_MIN_SEGMENTS = 8


def circular_segments(radius: float, chord_tolerance: float) -> int:
    """n such that sagitta r*(1-cos(pi/n)) stays under chord_tolerance."""
    radius = abs(float(radius))
    if radius <= 0.0:
        return _MIN_SEGMENTS
    allowed = chord_tolerance * 0.5
    if allowed <= 0.0:
        return _MAX_SEGMENTS
    limit = 1.0 - allowed / radius
    if limit <= -1.0:
        n = _MIN_SEGMENTS
    elif limit >= 1.0:
        n = _MAX_SEGMENTS
    else:
        n = int(math.ceil(math.pi / math.acos(limit)))
    n = max(_MIN_SEGMENTS, n)
    n = (n + 3) // 4 * 4
    return min(n, _MAX_SEGMENTS)


def tessellate_body(body: Body, chord_tolerance: object, max_triangles: object = None) -> dict:
    chord = as_finite_number(chord_tolerance, "chord_tolerance")
    if chord < KERNEL_NUMERIC_TOL:
        raise ContractError(
            "INVALID_ARGUMENT",
            "chord_tolerance is below kernel numeric accuracy",
        )
    budget = _optional_triangle_budget(max_triangles)
    try:
        solid = _to_manifold(bake_transform(body), chord)
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError(
            "TESSELLATION_FAILED",
            str(exc) or "tessellation failed",
        ) from exc
    if solid.is_empty() or solid.status() != mf.Error.NoError:
        raise ContractError("TESSELLATION_FAILED", f"tessellation failed: {solid.status()}")
    mesh = solid.to_mesh()
    vertices = [
        [float(point[0]), float(point[1]), float(point[2])]
        for point in np.asarray(mesh.vert_properties)[:, :3]
    ]
    triangles = [
        [int(corner[0]), int(corner[1]), int(corner[2])]
        for corner in np.asarray(mesh.tri_verts)
    ]
    if budget is not None and len(triangles) > budget:
        raise ContractError(
            "TRIANGLE_BUDGET",
            "mesh meeting the chord bound exceeds max_triangles",
        )
    return {"vertices": vertices, "triangles": triangles}


def _optional_triangle_budget(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError("INVALID_ARGUMENT", "max_triangles must be a positive integer")
    return value


def _to_manifold(body: Body, chord: float) -> mf.Manifold:
    if isinstance(body, CsgBody):
        left = _to_manifold(body.left, chord)
        right = _to_manifold(body.right, chord)
        if body.op == "union":
            return left + right
        return left - right
    if isinstance(body, TransformedBody):
        return _transform(_to_manifold(body.base, chord), body.transform.matrix)
    if isinstance(body, Box):
        return mf.Manifold.cube(list(body.size)).translate(list(body.origin))
    if isinstance(body, Cylinder):
        n = circular_segments(body.radius, chord)
        return mf.Manifold.cylinder(
            body.height,
            body.radius,
            circular_segments=n,
        ).translate(list(body.origin))
    if isinstance(body, Sphere):
        n = circular_segments(body.radius, chord)
        return mf.Manifold.sphere(body.radius, circular_segments=n).translate(list(body.center))
    if isinstance(body, Annulus):
        return _annulus(body, chord)
    if isinstance(body, ExtrudedPolygon):
        return _extruded(body)
    if isinstance(body, RevolvedSolid):
        return _revolved(body, chord)
    raise ContractError("INVALID_ARGUMENT", f"cannot tessellate {type(body).__name__}")


def _annulus(body: Annulus, chord: float) -> mf.Manifold:
    n_outer = circular_segments(body.outer_radius, chord)
    n_inner = circular_segments(body.inner_radius, chord)
    outer = mf.CrossSection.circle(body.outer_radius, n_outer)
    inner = mf.CrossSection.circle(body.inner_radius, n_inner)
    section = outer - inner
    cx, cy = body.center_xy
    if cx or cy:
        section = section.translate([cx, cy])
    height = body.zmax - body.zmin
    return mf.Manifold.extrude(section, height).translate([0.0, 0.0, body.zmin])


def _extruded(body: ExtrudedPolygon) -> mf.Manifold:
    points = np.asarray(body.vertices, dtype=np.float64)
    section = mf.CrossSection([points])
    height = body.zmax - body.zmin
    solid = mf.Manifold.extrude(section, height)
    if body.zmin:
        solid = solid.translate([0.0, 0.0, body.zmin])
    return solid


def _revolved(body: RevolvedSolid, chord: float) -> mf.Manifold:
    points = np.asarray(body.vertices, dtype=np.float64)
    radius = max(abs(float(vertex[0])) for vertex in body.vertices)
    n = circular_segments(radius, chord)
    return mf.Manifold.revolve(mf.CrossSection([points]), circular_segments=n)


def _transform(solid: mf.Manifold, matrix: tuple[float, ...]) -> mf.Manifold:
    affine = np.array(
        [
            [matrix[0], matrix[1], matrix[2], matrix[3]],
            [matrix[4], matrix[5], matrix[6], matrix[7]],
            [matrix[8], matrix[9], matrix[10], matrix[11]],
        ],
        dtype=np.float64,
    )
    return solid.transform(affine)

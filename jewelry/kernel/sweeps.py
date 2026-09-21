"""Extrude and revolve of simple polygonal profiles."""

from __future__ import annotations

from jewelry.errors import InvalidGeometry
from jewelry.kernel.numeric import KERNEL_NUMERIC_TOL, as_finite_number, as_positive_dimension
from jewelry.kernel.profiles import as_profile, axis_aligned_rect
from jewelry.kernel.solids import Annulus, Body, Box, Cylinder, ExtrudedPolygon, RevolvedSolid


def extrude(profile: object, height: object) -> Body:
    vertices = as_profile(profile)
    extrusion = as_positive_dimension(height, "height")
    rect = axis_aligned_rect(vertices)
    if rect is not None:
        min_x, min_y, max_x, max_y = rect
        return Box(
            origin=(min_x, min_y, 0.0),
            size=(max_x - min_x, max_y - min_y, extrusion),
        )
    return ExtrudedPolygon(vertices=vertices, zmin=0.0, zmax=extrusion)


def revolve(profile: object, angle_degrees: object) -> Body:
    vertices = as_profile(profile)
    angle = as_finite_number(angle_degrees, "angle_degrees")
    if abs(angle - 360.0) > KERNEL_NUMERIC_TOL:
        raise InvalidGeometry(
            "INVALID_ARGUMENT",
            "only a 360 degree revolution is supported",
        )
    if any(radius < 0.0 for radius, _z in vertices):
        raise InvalidGeometry(
            "INVALID_ARGUMENT",
            "revolve profile radius must be nonnegative",
        )
    rect = axis_aligned_rect(vertices)
    if rect is not None:
        min_r, min_z, max_r, max_z = rect
        if min_r == 0.0:
            return Cylinder(
                origin=(0.0, 0.0, min_z),
                radius=max_r,
                height=max_z - min_z,
            )
        return Annulus(
            center_xy=(0.0, 0.0),
            inner_radius=min_r,
            outer_radius=max_r,
            zmin=min_z,
            zmax=max_z,
        )
    return RevolvedSolid(vertices=vertices)

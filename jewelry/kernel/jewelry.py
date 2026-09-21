"""Jewelry construction helpers built from analytic CSG."""

from __future__ import annotations

import math

from jewelry.errors import InvalidGeometry
from jewelry.kernel.boolean import boolean
from jewelry.kernel.numeric import (
    as_finite_number,
    as_positive_dimension,
    as_positive_int,
    as_vec2,
)
from jewelry.kernel.solids import Annulus, Body, Cylinder


def modify_ring(body: Body, arguments: dict) -> Annulus:
    if not isinstance(body, Annulus):
        raise InvalidGeometry("INVALID_ARGUMENT", "modify_ring requires a ring solid")
    inner = arguments["inner_radius"] if "inner_radius" in arguments else body.inner_radius
    outer = arguments["outer_radius"] if "outer_radius" in arguments else body.outer_radius
    if "width" in arguments:
        width = arguments["width"]
    else:
        width = body.zmax - body.zmin
    return create_ring(inner, outer, width)


def create_ring(inner_radius: object, outer_radius: object, width: object) -> Annulus:
    inner = as_positive_dimension(inner_radius, "inner_radius")
    outer = as_positive_dimension(outer_radius, "outer_radius")
    band = as_positive_dimension(width, "width")
    if outer <= inner:
        raise InvalidGeometry(
            "INVALID_DIMENSION",
            "outer_radius must be greater than inner_radius",
        )
    half = band / 2.0
    return Annulus(
        center_xy=(0.0, 0.0),
        inner_radius=inner,
        outer_radius=outer,
        zmin=-half,
        zmax=half,
    )


def cut_through_hole(body: Body, center: object, radius: object) -> Body:
    cx, cy = as_vec2(center, "center")
    hole_radius = as_positive_dimension(radius, "radius")
    bounds = body.bounds()
    zmin, zmax = bounds[0][2], bounds[1][2]
    height = zmax - zmin
    if height <= 0.0:
        raise InvalidGeometry("INVALID_DIMENSION", "body has no Z extent")
    cutter = Cylinder(origin=(cx, cy, zmin), radius=hole_radius, height=height)
    return boolean("subtract", body, cutter)


def cut_recess(
    body: Body,
    center: object,
    radius: object,
    top_z: object,
    depth: object,
) -> Body:
    cx, cy = as_vec2(center, "center")
    hole_radius = as_positive_dimension(radius, "radius")
    top = as_finite_number(top_z, "top_z")
    recess_depth = as_positive_dimension(depth, "depth")
    cutter = Cylinder(
        origin=(cx, cy, top - recess_depth),
        radius=hole_radius,
        height=recess_depth,
    )
    return boolean("subtract", body, cutter)


def add_setting(
    body: Body,
    center: object,
    radius: object,
    base_z: object,
    height: object,
) -> Body:
    cx, cy = as_vec2(center, "center")
    setting_radius = as_positive_dimension(radius, "radius")
    base = as_finite_number(base_z, "base_z")
    setting_height = as_positive_dimension(height, "height")
    setting = Cylinder(
        origin=(cx, cy, base),
        radius=setting_radius,
        height=setting_height,
    )
    return boolean("union", body, setting)


def repeat_prongs(
    body: Body,
    center: object,
    orbit_radius: object,
    diameter: object,
    base_z: object,
    height: object,
    count: object,
    start_angle_degrees: object,
) -> Body:
    cx, cy = as_vec2(center, "center")
    orbit = as_finite_number(orbit_radius, "orbit_radius")
    prong_diameter = as_positive_dimension(diameter, "diameter")
    base = as_finite_number(base_z, "base_z")
    prong_height = as_positive_dimension(height, "height")
    n = as_positive_int(count, "count")
    start = as_finite_number(start_angle_degrees, "start_angle_degrees")
    radius = prong_diameter / 2.0
    start_rad = math.radians(start)
    result = body
    for index in range(n):
        angle = start_rad + 2.0 * math.pi * index / n
        px = cx + orbit * math.cos(angle)
        py = cy + orbit * math.sin(angle)
        prong = Cylinder(origin=(px, py, base), radius=radius, height=prong_height)
        result = boolean("union", result, prong)
    return result

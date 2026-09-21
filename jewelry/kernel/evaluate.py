"""CSG volume, intersection, and connected-component evaluation."""

from __future__ import annotations

import math

from jewelry.errors import InvalidGeometry
from jewelry.kernel.geometry2d import Disk, Polygon2D, Rect2D, Ring2D, intersection_area
from jewelry.kernel.numeric import KERNEL_NUMERIC_TOL
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
from jewelry.kernel.transform import AffineTransform


# K05: 0 < abs(gap) <= 2 * KERNEL_NUMERIC_TOL is TOLERANCE_AMBIGUITY; exact 0 merges.
_AMBIGUITY_WINDOW = 2.0 * KERNEL_NUMERIC_TOL


def csg_volume(body: CsgBody) -> float:
    left = body.left.volume()
    right = body.right.volume()
    shared = intersection_volume((body.left, body.right))
    if body.op == "union":
        return left + right - shared
    return left - shared


def intersection_volume(bodies: tuple[Body, ...]) -> float:
    if not bodies:
        return 0.0
    world = tuple(bake_transform(body) for body in bodies)
    for index, body in enumerate(world):
        if isinstance(body, CsgBody):
            others = world[:index] + world[index + 1 :]
            if body.op == "union":
                return (
                    intersection_volume((body.left, *others))
                    + intersection_volume((body.right, *others))
                    - intersection_volume((body.left, body.right, *others))
                )
            return intersection_volume((body.left, *others)) - intersection_volume(
                (body.left, body.right, *others)
            )
        if isinstance(body, TransformedBody):
            raise InvalidGeometry(
                "INVALID_ARGUMENT",
                "boolean of a general affine image is not supported",
            )
    return _primitive_intersection_volume(world)


def component_count(body: Body) -> int:
    parts = union_leaves(body)
    parent = list(range(len(parts)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def merge(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for i, left in enumerate(parts):
        for j, right in enumerate(parts):
            if j <= i:
                continue
            relation = classify_contact(left, right)
            if relation in {"overlap", "face", "contained"}:
                merge(i, j)
    return len({find(index) for index in range(len(parts))})


def union_leaves(body: Body) -> list[Body]:
    body = bake_transform(body)
    if isinstance(body, CsgBody) and body.op == "union":
        return union_leaves(body.left) + union_leaves(body.right)
    return [body]


def classify_contact(left: Body, right: Body) -> str:
    left = bake_transform(left)
    right = bake_transform(right)
    if isinstance(left, CsgBody) and left.op == "union":
        return _combine_part_relations(
            [classify_contact(part, right) for part in union_leaves(left)]
        )
    if isinstance(right, CsgBody) and right.op == "union":
        return _combine_part_relations(
            [classify_contact(left, part) for part in union_leaves(right)]
        )
    if isinstance(left, Box) and isinstance(right, Box):
        return classify_aabb(
            left.origin,
            _box_max(left),
            right.origin,
            _box_max(right),
        )
    if isinstance(left, Sphere) and isinstance(right, Sphere):
        return classify_spheres(left, right)
    if _aabb_relation(left, right) == "disjoint":
        return "disjoint"
    if _is_z_extruded(left) and _is_z_extruded(right):
        return _combine_xy_z(
            _classify_xy(_xy_shape(left), _xy_shape(right)),
            classify_interval(_z_interval(left), _z_interval(right)),
        )
    shared = intersection_volume((left, right))
    if shared > 0.0:
        return "overlap"
    return "disjoint"


def classify_aabb(
    a_min: tuple[float, float, float] | tuple[float, float],
    a_max: tuple[float, float, float] | tuple[float, float],
    b_min: tuple[float, float, float] | tuple[float, float],
    b_max: tuple[float, float, float] | tuple[float, float],
) -> str:
    signed = [
        max(a_min[i], b_min[i]) - min(a_max[i], b_max[i])
        for i in range(len(a_min))
    ]
    if any(0.0 < abs(value) <= _AMBIGUITY_WINDOW for value in signed):
        if any(value > _AMBIGUITY_WINDOW for value in signed):
            return "disjoint"
        return "ambiguous"
    if any(value > _AMBIGUITY_WINDOW for value in signed):
        return "disjoint"
    if all(value < -_AMBIGUITY_WINDOW for value in signed):
        return "overlap"
    zeros = sum(1 for value in signed if value == 0.0)
    if zeros == 1 and all(value <= 0.0 for value in signed):
        return "face"
    if zeros >= 2:
        return "point"
    if all(value <= 0.0 for value in signed):
        return "overlap"
    return "disjoint"


def classify_interval(left: tuple[float, float], right: tuple[float, float]) -> str:
    signed = max(left[0], right[0]) - min(left[1], right[1])
    if signed == 0.0:
        return "face"
    if 0.0 < abs(signed) <= _AMBIGUITY_WINDOW:
        return "ambiguous"
    if signed > 0.0:
        return "disjoint"
    return "overlap"


def classify_spheres(left: Sphere, right: Sphere) -> str:
    distance = math.hypot(
        left.center[0] - right.center[0],
        left.center[1] - right.center[1],
        left.center[2] - right.center[2],
    )
    outer = distance - (left.radius + right.radius)
    inner = abs(left.radius - right.radius) - distance
    if outer == 0.0 or (inner == 0.0 and distance > 0.0):
        return "point"
    if 0.0 < abs(outer) <= _AMBIGUITY_WINDOW or 0.0 < abs(inner) <= _AMBIGUITY_WINDOW:
        return "ambiguous"
    if outer > 0.0:
        return "disjoint"
    return "overlap"


def bake_transform(body: Body) -> Body:
    if isinstance(body, CsgBody):
        return CsgBody(body.op, bake_transform(body.left), bake_transform(body.right))
    if not isinstance(body, TransformedBody):
        return body
    base = bake_transform(body.base)
    baked = _apply_translation(base, body.transform)
    if baked is not None:
        return baked
    if isinstance(base, CsgBody):
        return CsgBody(
            base.op,
            bake_transform(TransformedBody.apply(base.left, body.transform)),
            bake_transform(TransformedBody.apply(base.right, body.transform)),
        )
    return TransformedBody.apply(base, body.transform)


def _apply_translation(body: Body, transform: AffineTransform) -> Body | None:
    offset = _translation_only(transform)
    if offset is None:
        return None
    tx, ty, tz = offset
    if isinstance(body, Box):
        origin = (body.origin[0] + tx, body.origin[1] + ty, body.origin[2] + tz)
        return Box(origin=origin, size=body.size)
    if isinstance(body, Cylinder):
        origin = (body.origin[0] + tx, body.origin[1] + ty, body.origin[2] + tz)
        return Cylinder(origin=origin, radius=body.radius, height=body.height)
    if isinstance(body, Sphere):
        center = (body.center[0] + tx, body.center[1] + ty, body.center[2] + tz)
        return Sphere(center=center, radius=body.radius)
    if isinstance(body, Annulus):
        return Annulus(
            center_xy=(body.center_xy[0] + tx, body.center_xy[1] + ty),
            inner_radius=body.inner_radius,
            outer_radius=body.outer_radius,
            zmin=body.zmin + tz,
            zmax=body.zmax + tz,
        )
    if isinstance(body, ExtrudedPolygon):
        vertices = tuple((x + tx, y + ty) for x, y in body.vertices)
        return ExtrudedPolygon(vertices=vertices, zmin=body.zmin + tz, zmax=body.zmax + tz)
    if isinstance(body, RevolvedSolid) and abs(tx) <= KERNEL_NUMERIC_TOL and abs(ty) <= KERNEL_NUMERIC_TOL:
        vertices = tuple((radius, z + tz) for radius, z in body.vertices)
        return RevolvedSolid(vertices=vertices)
    return None


def _translation_only(transform: AffineTransform) -> tuple[float, float, float] | None:
    matrix = transform.matrix
    linear = (
        matrix[0], matrix[1], matrix[2],
        matrix[4], matrix[5], matrix[6],
        matrix[8], matrix[9], matrix[10],
    )
    identity = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    if any(abs(linear[i] - identity[i]) > KERNEL_NUMERIC_TOL for i in range(9)):
        return None
    return (matrix[3], matrix[7], matrix[11])


def _primitive_intersection_volume(bodies: tuple[Body, ...]) -> float:
    if not bodies:
        return 0.0
    lo, hi = [float(v) for v in bodies[0].bounds()[0]], [float(v) for v in bodies[0].bounds()[1]]
    for body in bodies[1:]:
        other_lo, other_hi = body.bounds()
        lo = [max(lo[i], other_lo[i]) for i in range(3)]
        hi = [min(hi[i], other_hi[i]) for i in range(3)]
        if any(hi[i] <= lo[i] for i in range(3)):
            return 0.0
    if any(isinstance(body, Sphere) for body in bodies):
        spheres = [body for body in bodies if isinstance(body, Sphere)]
        others = [body for body in bodies if not isinstance(body, Sphere)]
        if others:
            raise InvalidGeometry(
                "INVALID_ARGUMENT",
                "sphere boolean with non-sphere solids is not supported",
            )
        return _sphere_intersection_volume(tuple(spheres))
    if not all(_is_z_extruded(body) for body in bodies):
        raise InvalidGeometry(
            "INVALID_ARGUMENT",
            "boolean operands must be Z-extruded analytic solids",
        )
    zmin = max(_z_interval(body)[0] for body in bodies)
    zmax = min(_z_interval(body)[1] for body in bodies)
    if zmax <= zmin:
        return 0.0
    area = intersection_area(tuple(_xy_shape(body) for body in bodies))
    return area * (zmax - zmin)


def _sphere_intersection_volume(spheres: tuple[Sphere, ...]) -> float:
    if not spheres:
        return 0.0
    if len(spheres) == 1:
        return spheres[0].volume()
    if len(spheres) != 2:
        raise InvalidGeometry(
            "INVALID_ARGUMENT",
            "intersection of more than two spheres is not supported",
        )
    left, right = spheres
    distance = math.hypot(
        left.center[0] - right.center[0],
        left.center[1] - right.center[1],
        left.center[2] - right.center[2],
    )
    ra, rb = left.radius, right.radius
    if distance >= ra + rb:
        return 0.0
    if distance <= abs(ra - rb):
        smaller = min(ra, rb)
        return (4.0 / 3.0) * math.pi * smaller ** 3
    ra2, rb2 = ra * ra, rb * rb
    dist2 = distance * distance
    x_a = (dist2 + ra2 - rb2) / (2.0 * distance)
    x_b = (dist2 + rb2 - ra2) / (2.0 * distance)
    return math.pi * (
        (ra - x_a) ** 2 * (2.0 * ra + x_a) + (rb - x_b) ** 2 * (2.0 * rb + x_b)
    ) / 3.0


def _is_z_extruded(body: Body) -> bool:
    return isinstance(body, (Box, Cylinder, Annulus, ExtrudedPolygon))


def _z_interval(body: Body) -> tuple[float, float]:
    if isinstance(body, Box):
        return (body.origin[2], body.origin[2] + body.size[2])
    if isinstance(body, Cylinder):
        return (body.origin[2], body.origin[2] + body.height)
    if isinstance(body, Annulus):
        return (body.zmin, body.zmax)
    if isinstance(body, ExtrudedPolygon):
        return (body.zmin, body.zmax)
    if isinstance(body, Sphere):
        return (body.center[2] - body.radius, body.center[2] + body.radius)
    raise InvalidGeometry("INVALID_ARGUMENT", "body has no Z interval")


def _xy_shape(body: Body):
    if isinstance(body, Box):
        return Rect2D((body.origin[0], body.origin[1]), (body.size[0], body.size[1]))
    if isinstance(body, Cylinder):
        return Disk((body.origin[0], body.origin[1]), body.radius)
    if isinstance(body, Annulus):
        return Ring2D(body.center_xy, body.inner_radius, body.outer_radius)
    if isinstance(body, ExtrudedPolygon):
        return Polygon2D(body.vertices)
    raise InvalidGeometry("INVALID_ARGUMENT", "body has no XY section")


def _box_max(box: Box) -> tuple[float, float, float]:
    return (
        box.origin[0] + box.size[0],
        box.origin[1] + box.size[1],
        box.origin[2] + box.size[2],
    )


def _aabb_relation(left: Body, right: Body) -> str:
    a = left.bounds()
    b = right.bounds()
    return classify_aabb(tuple(a[0]), tuple(a[1]), tuple(b[0]), tuple(b[1]))


def _classify_xy(left, right) -> str:
    if isinstance(left, Rect2D) and isinstance(right, Rect2D):
        a_max = (left.origin[0] + left.size[0], left.origin[1] + left.size[1])
        b_max = (right.origin[0] + right.size[0], right.origin[1] + right.size[1])
        return classify_aabb(left.origin, a_max, right.origin, b_max)
    if isinstance(left, Disk) and isinstance(right, Disk):
        return _classify_disks(left, right)
    if isinstance(left, Ring2D) and isinstance(right, Disk):
        return _classify_disk_ring(right, left)
    if isinstance(left, Disk) and isinstance(right, Ring2D):
        return _classify_disk_ring(left, right)
    if isinstance(left, Ring2D) and isinstance(right, Ring2D):
        return _classify_rings(left, right)
    shared = intersection_area((left, right))
    if shared > 0.0:
        return "overlap"
    return "disjoint"


def _classify_disks(left: Disk, right: Disk) -> str:
    distance = math.hypot(
        left.center[0] - right.center[0],
        left.center[1] - right.center[1],
    )
    outer = distance - (left.radius + right.radius)
    inner = abs(left.radius - right.radius) - distance
    # External tangency is a point. Internal tangency of filled disks still has
    # positive area (the smaller disk), so it is overlap, not a point contact.
    if outer == 0.0:
        return "point"
    if 0.0 < abs(outer) <= _AMBIGUITY_WINDOW or 0.0 < abs(inner) <= _AMBIGUITY_WINDOW:
        return "ambiguous"
    if outer > 0.0:
        return "disjoint"
    return "overlap"


def _classify_disk_ring(disk: Disk, ring: Ring2D) -> str:
    outer = _classify_disks(disk, Disk(ring.center, ring.outer))
    if outer == "disjoint":
        return "disjoint"
    distance = math.hypot(
        disk.center[0] - ring.center[0],
        disk.center[1] - ring.center[1],
    )
    hole_clearance = ring.inner - (distance + disk.radius)
    if hole_clearance > _AMBIGUITY_WINDOW:
        return "disjoint"
    if 0.0 < abs(hole_clearance) <= _AMBIGUITY_WINDOW:
        return "ambiguous"
    if hole_clearance == 0.0:
        return "point"
    if outer in {"point", "ambiguous"}:
        return outer
    return "overlap"


def _classify_rings(left: Ring2D, right: Ring2D) -> str:
    return _classify_disk_ring(Disk(right.center, right.outer), left)


def _combine_xy_z(xy: str, z: str) -> str:
    if xy == "disjoint" or z == "disjoint":
        return "disjoint"
    if xy == "ambiguous" or z == "ambiguous":
        return "ambiguous"
    if xy == "overlap" and z == "overlap":
        return "overlap"
    if xy == "overlap" and z == "face":
        return "face"
    if xy == "face" and z == "overlap":
        return "face"
    if xy == "point" or z == "point":
        return "point"
    if xy == "face" and z == "face":
        return "point"
    return "overlap"


def _combine_part_relations(relations: list[str]) -> str:
    if any(relation in {"overlap", "face", "contained"} for relation in relations):
        return "overlap"
    if any(relation == "point" for relation in relations):
        return "point"
    if any(relation == "ambiguous" for relation in relations):
        return "ambiguous"
    return "disjoint"

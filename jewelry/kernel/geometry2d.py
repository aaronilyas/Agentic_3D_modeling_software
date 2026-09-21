"""Closed-form 2D areas for Z-extruded CSG (disks, rings, axis-aligned rects)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from jewelry.errors import InvalidGeometry
from jewelry.kernel.numeric import KERNEL_NUMERIC_TOL
from jewelry.kernel.profiles import polygon_area


@dataclass(frozen=True)
class Disk:
    center: tuple[float, float]
    radius: float


@dataclass(frozen=True)
class Ring2D:
    center: tuple[float, float]
    inner: float
    outer: float


@dataclass(frozen=True)
class Rect2D:
    origin: tuple[float, float]
    size: tuple[float, float]


@dataclass(frozen=True)
class Polygon2D:
    vertices: tuple[tuple[float, float], ...]


Shape2D = Disk | Ring2D | Rect2D | Polygon2D


def shape_area(shape: Shape2D) -> float:
    if isinstance(shape, Disk):
        return math.pi * shape.radius * shape.radius
    if isinstance(shape, Ring2D):
        return math.pi * (shape.outer * shape.outer - shape.inner * shape.inner)
    if isinstance(shape, Rect2D):
        return shape.size[0] * shape.size[1]
    return abs(polygon_area(shape.vertices))


def intersection_area(shapes: tuple[Shape2D, ...]) -> float:
    if not shapes:
        return 0.0
    return _intersection_area(list(shapes))


def disk_intersection_area(left: Disk, right: Disk) -> float:
    radius_a = left.radius
    radius_b = right.radius
    if radius_a <= 0.0 or radius_b <= 0.0:
        return 0.0
    dx = right.center[0] - left.center[0]
    dy = right.center[1] - left.center[1]
    distance = math.hypot(dx, dy)
    if distance >= radius_a + radius_b:
        return 0.0
    if distance <= abs(radius_a - radius_b):
        smaller = min(radius_a, radius_b)
        return math.pi * smaller * smaller
    ra2 = radius_a * radius_a
    rb2 = radius_b * radius_b
    dist2 = distance * distance
    alpha = math.acos(
        max(-1.0, min(1.0, (dist2 + ra2 - rb2) / (2.0 * distance * radius_a)))
    )
    beta = math.acos(
        max(-1.0, min(1.0, (dist2 + rb2 - ra2) / (2.0 * distance * radius_b)))
    )
    under = (
        (-distance + radius_a + radius_b)
        * (distance + radius_a - radius_b)
        * (distance - radius_a + radius_b)
        * (distance + radius_a + radius_b)
    )
    return ra2 * alpha + rb2 * beta - 0.5 * math.sqrt(max(0.0, under))


def _intersection_area(shapes: list[Shape2D]) -> float:
    if not shapes:
        return 0.0
    for index, shape in enumerate(shapes):
        if isinstance(shape, Ring2D):
            others = shapes[:index] + shapes[index + 1 :]
            outer = Disk(shape.center, shape.outer)
            inner = Disk(shape.center, shape.inner)
            return _intersection_area([outer, *others]) - _intersection_area(
                [inner, *others]
            )
    if all(isinstance(shape, Disk) for shape in shapes):
        return _disks_intersection_area([shape for shape in shapes if isinstance(shape, Disk)])
    if all(isinstance(shape, Rect2D) for shape in shapes):
        return _rects_intersection_area(
            [shape for shape in shapes if isinstance(shape, Rect2D)]
        )
    if len(shapes) == 1:
        return shape_area(shapes[0])
    raise InvalidGeometry(
        "INVALID_ARGUMENT",
        "boolean operands have an unsupported cross-section intersection",
    )


def _rects_intersection_area(rects: list[Rect2D]) -> float:
    x0 = max(rect.origin[0] for rect in rects)
    y0 = max(rect.origin[1] for rect in rects)
    x1 = min(rect.origin[0] + rect.size[0] for rect in rects)
    y1 = min(rect.origin[1] + rect.size[1] for rect in rects)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def _disks_intersection_area(disks: list[Disk]) -> float:
    reduced = _reduce_disks(disks)
    if reduced is None:
        return 0.0
    if len(reduced) == 1:
        disk = reduced[0]
        return math.pi * disk.radius * disk.radius
    if len(reduced) == 2:
        return disk_intersection_area(reduced[0], reduced[1])
    if len(reduced) >= 3:
        for i in range(len(reduced)):
            for j in range(i + 1, len(reduced)):
                if disk_intersection_area(reduced[i], reduced[j]) <= 0.0:
                    return 0.0
        if len(reduced) == 3:
            return _three_disk_intersection_area(reduced[0], reduced[1], reduced[2])
        first = _three_disk_intersection_area(reduced[0], reduced[1], reduced[2])
        if first <= 0.0:
            return 0.0
        vertices = _triple_vertices(reduced[0], reduced[1], reduced[2])
        for disk in reduced[3:]:
            if vertices and all(_point_in_disk(disk, point) for point in vertices):
                continue
            return 0.0
        return first
    return 0.0


def _reduce_disks(disks: list[Disk]) -> list[Disk] | None:
    remaining = list(disks)
    changed = True
    while changed:
        changed = False
        drop: int | None = None
        for i, left in enumerate(remaining):
            for j, right in enumerate(remaining):
                if i == j:
                    continue
                if _disk_contains_disk(left, right) and not _disk_contains_disk(right, left):
                    drop = i
                    break
                if disk_intersection_area(left, right) <= 0.0:
                    return None
            if drop is not None:
                break
        if drop is not None:
            remaining.pop(drop)
            changed = True
    return remaining


def _disk_contains_disk(outer: Disk, inner: Disk) -> bool:
    distance = math.hypot(
        inner.center[0] - outer.center[0],
        inner.center[1] - outer.center[1],
    )
    return distance + inner.radius <= outer.radius + KERNEL_NUMERIC_TOL


def _point_in_disk(disk: Disk, point: tuple[float, float]) -> bool:
    return math.hypot(
        point[0] - disk.center[0],
        point[1] - disk.center[1],
    ) <= disk.radius + KERNEL_NUMERIC_TOL


def _circle_intersections(left: Disk, right: Disk) -> list[tuple[float, float]]:
    dx = right.center[0] - left.center[0]
    dy = right.center[1] - left.center[1]
    distance = math.hypot(dx, dy)
    if distance == 0.0:
        return []
    if distance > left.radius + right.radius or distance < abs(left.radius - right.radius):
        return []
    along = (left.radius ** 2 - right.radius ** 2 + distance ** 2) / (2.0 * distance)
    height_sq = left.radius ** 2 - along ** 2
    if height_sq < 0.0:
        height_sq = 0.0
    height = math.sqrt(height_sq)
    px = left.center[0] + along * dx / distance
    py = left.center[1] + along * dy / distance
    if height == 0.0:
        return [(px, py)]
    mx = height * dy / distance
    my = -height * dx / distance
    return [(px + mx, py + my), (px - mx, py - my)]


def _triple_vertices(a: Disk, b: Disk, c: Disk) -> list[tuple[float, float]]:
    vertices: list[tuple[float, float]] = []
    for first, second, third in ((a, b, c), (b, c, a), (c, a, b)):
        for point in _circle_intersections(first, second):
            if _point_in_disk(third, point):
                vertices.append(point)
    return vertices


def _three_disk_intersection_area(a: Disk, b: Disk, c: Disk) -> float:
    pair_ab = disk_intersection_area(a, b)
    pair_bc = disk_intersection_area(b, c)
    pair_ca = disk_intersection_area(c, a)
    if pair_ab <= 0.0 or pair_bc <= 0.0 or pair_ca <= 0.0:
        return 0.0
    for first, second, third, pair in (
        (a, b, c, pair_ab),
        (b, c, a, pair_bc),
        (c, a, b, pair_ca),
    ):
        points = _circle_intersections(first, second)
        if points and all(_point_in_disk(third, point) for point in points):
            return pair
        if not points:
            inner = first if first.radius <= second.radius else second
            if _disk_contains_disk(third, inner):
                return math.pi * inner.radius * inner.radius
            return 0.0
    p_ab = _one_inside(_circle_intersections(a, b), c)
    p_bc = _one_inside(_circle_intersections(b, c), a)
    p_ca = _one_inside(_circle_intersections(c, a), b)
    if p_ab is None or p_bc is None or p_ca is None:
        return 0.0
    triangle = _triangle_area(p_ab, p_bc, p_ca)
    return (
        triangle
        + _segment_area(a, p_ca, p_ab)
        + _segment_area(b, p_ab, p_bc)
        + _segment_area(c, p_bc, p_ca)
    )


def _one_inside(
    points: list[tuple[float, float]], disk: Disk
) -> tuple[float, float] | None:
    inside = [point for point in points if _point_in_disk(disk, point)]
    if not inside:
        return None
    return inside[0]


def _triangle_area(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    return abs((a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1])) / 2.0)


def _segment_area(
    disk: Disk,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    ux = start[0] - disk.center[0]
    uy = start[1] - disk.center[1]
    vx = end[0] - disk.center[0]
    vy = end[1] - disk.center[1]
    angle = abs(math.atan2(ux * vy - uy * vx, ux * vx + uy * vy))
    return 0.5 * disk.radius * disk.radius * (angle - math.sin(angle))

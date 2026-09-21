"""Planar profile validation for extrude (xy) and revolve (rz)."""

from __future__ import annotations

import math
from collections.abc import Sequence

from jewelry.errors import InvalidGeometry
from jewelry.kernel.numeric import KERNEL_NUMERIC_TOL, as_finite_number


def as_profile(value: object, name: str = "profile") -> tuple[tuple[float, float], ...]:
    if isinstance(value, dict):
        raise InvalidGeometry("INVALID_ARGUMENT", f"{name} type is not supported")
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InvalidGeometry("INVALID_ARGUMENT", f"{name} must be a list of points")
    if len(value) < 3:
        raise InvalidGeometry(
            "INVALID_ARGUMENT",
            f"{name} must have at least 3 vertices",
        )
    points: list[tuple[float, float]] = []
    for index, item in enumerate(value):
        points.append(_as_point(item, f"{name}[{index}]"))
    if len(points) >= 4 and points[0] == points[-1]:
        points = points[:-1]
    if len(points) < 3:
        raise InvalidGeometry(
            "INVALID_ARGUMENT",
            f"{name} must have at least 3 vertices",
        )
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        if point == nxt:
            raise InvalidGeometry(
                "INVALID_ARGUMENT",
                f"{name} has a zero-length edge",
            )
    if not is_simple_polygon(points):
        raise InvalidGeometry("INVALID_ARGUMENT", f"{name} is self-intersecting")
    area = polygon_area(points)
    if abs(area) <= KERNEL_NUMERIC_TOL:
        raise InvalidGeometry("INVALID_ARGUMENT", f"{name} has zero area")
    if area < 0.0:
        points = list(reversed(points))
    return tuple(points)


def polygon_area(vertices: Sequence[tuple[float, float]]) -> float:
    return 0.5 * _shoelace_twice(vertices)


def polygon_centroid(vertices: Sequence[tuple[float, float]]) -> tuple[float, float]:
    twice = _shoelace_twice(vertices)
    if abs(twice) <= KERNEL_NUMERIC_TOL:
        raise InvalidGeometry("INVALID_ARGUMENT", "profile has zero area")
    cx = 0.0
    cy = 0.0
    count = len(vertices)
    for index, (x0, y0) in enumerate(vertices):
        x1, y1 = vertices[(index + 1) % count]
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    factor = 1.0 / (3.0 * twice)
    return (cx * factor, cy * factor)


def point_in_polygon(point: tuple[float, float], vertices: Sequence[tuple[float, float]]) -> bool:
    """Winding-number interior test. Boundary classification is not contract-critical."""
    x, y = point
    winding = 0
    count = len(vertices)
    for index in range(count):
        x0, y0 = vertices[index]
        x1, y1 = vertices[(index + 1) % count]
        if y0 <= y:
            if y1 > y and _cross(x0, y0, x1, y1, x, y) > 0.0:
                winding += 1
        elif y1 <= y and _cross(x0, y0, x1, y1, x, y) < 0.0:
            winding -= 1
    return winding != 0


def is_simple_polygon(vertices: Sequence[tuple[float, float]]) -> bool:
    count = len(vertices)
    for i in range(count):
        a = vertices[i]
        b = vertices[(i + 1) % count]
        for j in range(i + 1, count):
            if _edges_adjacent(i, j, count):
                continue
            c = vertices[j]
            d = vertices[(j + 1) % count]
            if _segments_intersect(a, b, c, d):
                return False
    return True


def axis_aligned_rect(
    vertices: Sequence[tuple[float, float]],
) -> tuple[float, float, float, float] | None:
    if len(vertices) != 4:
        return None
    xs = {point[0] for point in vertices}
    ys = {point[1] for point in vertices}
    if len(xs) != 2 or len(ys) != 2:
        return None
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    corners = {
        (min_x, min_y),
        (min_x, max_y),
        (max_x, min_y),
        (max_x, max_y),
    }
    if set(vertices) != corners:
        return None
    return (min_x, min_y, max_x, max_y)


def _as_point(value: object, name: str) -> tuple[float, float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 2:
        raise InvalidGeometry("INVALID_ARGUMENT", f"{name} must be a 2-vector")
    return (
        as_finite_number(value[0], f"{name}[0]"),
        as_finite_number(value[1], f"{name}[1]"),
    )


def _shoelace_twice(vertices: Sequence[tuple[float, float]]) -> float:
    total = 0.0
    count = len(vertices)
    for index, (x0, y0) in enumerate(vertices):
        x1, y1 = vertices[(index + 1) % count]
        total += x0 * y1 - x1 * y0
    return total


def _cross(x0: float, y0: float, x1: float, y1: float, x: float, y: float) -> float:
    return (x1 - x0) * (y - y0) - (x - x0) * (y1 - y0)


def _edges_adjacent(i: int, j: int, count: int) -> bool:
    if i == j:
        return True
    return (i + 1) % count == j or (j + 1) % count == i


def _orientation(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> bool:
    return (
        min(a[0], b[0]) - KERNEL_NUMERIC_TOL <= c[0] <= max(a[0], b[0]) + KERNEL_NUMERIC_TOL
        and min(a[1], b[1]) - KERNEL_NUMERIC_TOL <= c[1] <= max(a[1], b[1]) + KERNEL_NUMERIC_TOL
    )


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if (o1 > 0.0 and o2 < 0.0 or o1 < 0.0 and o2 > 0.0) and (
        o3 > 0.0 and o4 < 0.0 or o3 < 0.0 and o4 > 0.0
    ):
        return True
    if abs(o1) <= KERNEL_NUMERIC_TOL and _on_segment(a, b, c) and c not in (a, b):
        return True
    if abs(o2) <= KERNEL_NUMERIC_TOL and _on_segment(a, b, d) and d not in (a, b):
        return True
    if abs(o3) <= KERNEL_NUMERIC_TOL and _on_segment(c, d, a) and a not in (c, d):
        return True
    if abs(o4) <= KERNEL_NUMERIC_TOL and _on_segment(c, d, b) and b not in (c, d):
        return True
    return False

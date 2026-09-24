"""Finite-number parsing. Internal coordinates are millimetres."""

from __future__ import annotations

import math

from cad.errors import InvalidArgument, InvalidGeometry


def finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidArgument(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise InvalidArgument(f"{name} must be a finite number")
    return number


def positive_number(value: object, name: str) -> float:
    number = finite_number(value, name)
    if number <= 0.0:
        raise InvalidGeometry(f"{name} must be greater than zero")
    return number


def positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidArgument(f"{name} must be a positive integer")
    if value < 1:
        raise InvalidGeometry(f"{name} must be a positive integer")
    return value


def vec3(value: object, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise InvalidArgument(f"{name} must be a 3-number vector")
    return (
        finite_number(value[0], name),
        finite_number(value[1], name),
        finite_number(value[2], name),
    )


def vec2(value: object, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise InvalidArgument(f"{name} must be a 2-number vector")
    return finite_number(value[0], name), finite_number(value[1], name)


def polygon(value: object, name: str, minimum: int = 3) -> list[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) < minimum:
        raise InvalidArgument(f"{name} needs at least {minimum} points")
    points = [list(vec2(point, name)) for point in value]
    area = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        area += point[0] * nxt[1] - nxt[0] * point[1]
    if abs(area) <= 1e-12:
        raise InvalidGeometry(f"{name} has zero area")
    return points


def polyline3(value: object, name: str, minimum: int = 2) -> list[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) < minimum:
        raise InvalidArgument(f"{name} needs at least {minimum} points")
    points = [list(vec3(point, name)) for point in value]
    span = 0.0
    for left, right in zip(points, points[1:]):
        span += math.dist(left, right)
    if span <= 1e-12:
        raise InvalidGeometry(f"{name} has zero length")
    return points


def optional_name(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise InvalidArgument("name must be a nonempty string")
    if len(value) > 120:
        raise InvalidArgument("name is too long")
    return value.strip()


def finite_tree(value) -> None:
    """Reject non-finite values before replay or kernel execution."""
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidArgument("numbers must be finite")
    if isinstance(value, dict):
        for child in value.values():
            finite_tree(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            finite_tree(child)

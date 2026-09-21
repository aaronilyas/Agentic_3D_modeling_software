"""Kernel numeric policy and input validation (millimetres)."""

from __future__ import annotations

import math
from collections.abc import Sequence

from jewelry.errors import InvalidGeometry

# Matches tests/fixtures.py:KERNEL_NUMERIC_TOL. Boundary classification is
# deferred; primitives still use this as the kernel's numeric epsilon.
KERNEL_NUMERIC_TOL = 1e-7


def as_finite_number(value: object, name: str, *, code: str = "INVALID_ARGUMENT") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidGeometry(code, f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise InvalidGeometry(code, f"{name} must be finite")
    return number


def as_positive_dimension(value: object, name: str) -> float:
    number = as_finite_number(value, name, code="INVALID_DIMENSION")
    if number <= 0.0:
        raise InvalidGeometry("INVALID_DIMENSION", f"{name} must be greater than zero")
    return number


def as_vec3(value: object, name: str) -> tuple[float, float, float]:
    components = _three_components(value, name)
    return (
        as_finite_number(components[0], f"{name}[0]"),
        as_finite_number(components[1], f"{name}[1]"),
        as_finite_number(components[2], f"{name}[2]"),
    )


def as_size(value: object, name: str = "size") -> tuple[float, float, float]:
    components = _three_components(value, name)
    return (
        as_positive_dimension(components[0], f"{name}[0]"),
        as_positive_dimension(components[1], f"{name}[1]"),
        as_positive_dimension(components[2], f"{name}[2]"),
    )


def _three_components(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InvalidGeometry("INVALID_ARGUMENT", f"{name} must be a 3-vector")
    if len(value) != 3:
        raise InvalidGeometry("INVALID_ARGUMENT", f"{name} must have 3 components")
    return value

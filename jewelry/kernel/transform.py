"""Orientation-preserving affine transforms. Independent of document/application."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from jewelry.errors import InvalidTransform
from jewelry.kernel.numeric import KERNEL_NUMERIC_TOL


def _as_matrix16(value: object) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InvalidTransform("matrix must be a flat sequence of 16 numbers")
    if len(value) != 16:
        raise InvalidTransform("matrix must have 16 elements")
    elements = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise InvalidTransform(f"matrix[{index}] must be a number")
        number = float(item)
        if not math.isfinite(number):
            raise InvalidTransform(f"matrix[{index}] must be finite")
        elements.append(number)
    return tuple(elements)


def _linear_determinant(matrix: tuple[float, ...]) -> float:
    a00, a01, a02 = matrix[0], matrix[1], matrix[2]
    a10, a11, a12 = matrix[4], matrix[5], matrix[6]
    a20, a21, a22 = matrix[8], matrix[9], matrix[10]
    return (
        a00 * (a11 * a22 - a12 * a21)
        - a01 * (a10 * a22 - a12 * a20)
        + a02 * (a10 * a21 - a11 * a20)
    )


def _invert_affine(matrix: tuple[float, ...], determinant: float) -> tuple[float, ...]:
    a00, a01, a02, tx = matrix[0], matrix[1], matrix[2], matrix[3]
    a10, a11, a12, ty = matrix[4], matrix[5], matrix[6], matrix[7]
    a20, a21, a22, tz = matrix[8], matrix[9], matrix[10], matrix[11]
    inv_det = 1.0 / determinant
    b00 = (a11 * a22 - a12 * a21) * inv_det
    b01 = (a02 * a21 - a01 * a22) * inv_det
    b02 = (a01 * a12 - a02 * a11) * inv_det
    b10 = (a12 * a20 - a10 * a22) * inv_det
    b11 = (a00 * a22 - a02 * a20) * inv_det
    b12 = (a02 * a10 - a00 * a12) * inv_det
    b20 = (a10 * a21 - a11 * a20) * inv_det
    b21 = (a01 * a20 - a00 * a21) * inv_det
    b22 = (a00 * a11 - a01 * a10) * inv_det
    return (
        b00, b01, b02, -(b00 * tx + b01 * ty + b02 * tz),
        b10, b11, b12, -(b10 * tx + b11 * ty + b12 * tz),
        b20, b21, b22, -(b20 * tx + b21 * ty + b22 * tz),
        0.0, 0.0, 0.0, 1.0,
    )


def _mul4(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    result = []
    for row in range(4):
        for column in range(4):
            result.append(sum(
                left[row * 4 + k] * right[k * 4 + column]
                for k in range(4)
            ))
    return tuple(result)


def _apply(matrix: tuple[float, ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    )


@dataclass(frozen=True)
class AffineTransform:
    """Invertible 4x4 affine map; translation is the last column of a row-major matrix."""

    matrix: tuple[float, ...]
    _inverse: tuple[float, ...]
    _linear_det: float

    @classmethod
    def from_matrix(cls, value: object) -> AffineTransform:
        elements = _as_matrix16(value)
        if (
            abs(elements[12]) > KERNEL_NUMERIC_TOL
            or abs(elements[13]) > KERNEL_NUMERIC_TOL
            or abs(elements[14]) > KERNEL_NUMERIC_TOL
            or abs(elements[15] - 1.0) > KERNEL_NUMERIC_TOL
        ):
            raise InvalidTransform("matrix must be affine (last row [0, 0, 0, 1])")
        canonical = elements[:12] + (0.0, 0.0, 0.0, 1.0)
        determinant = _linear_determinant(canonical)
        if not math.isfinite(determinant):
            raise InvalidTransform("transform determinant must be finite")
        if abs(determinant) <= KERNEL_NUMERIC_TOL:
            raise InvalidTransform("transform is singular or has zero scale")
        if determinant < 0.0:
            raise InvalidTransform(
                "transform must preserve orientation; negative scale is invalid"
            )
        return cls(
            matrix=canonical,
            _inverse=_invert_affine(canonical, determinant),
            _linear_det=determinant,
        )

    def transform_point(self, point: tuple[float, float, float]) -> tuple[float, float, float]:
        return _apply(self.matrix, point)

    def inverse_transform_point(
        self, point: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        return _apply(self._inverse, point)

    def linear_map(self, vector: tuple[float, float, float]) -> tuple[float, float, float]:
        x, y, z = vector
        m = self.matrix
        return (
            m[0] * x + m[1] * y + m[2] * z,
            m[4] * x + m[5] * y + m[6] * z,
            m[8] * x + m[9] * y + m[10] * z,
        )

    def linear_row_norm(self, row: int) -> float:
        index = row * 4
        m = self.matrix
        return math.sqrt(m[index] ** 2 + m[index + 1] ** 2 + m[index + 2] ** 2)

    def volume_scale(self) -> float:
        return self._linear_det

    def compose(self, other: AffineTransform) -> AffineTransform:
        """Return a transform that applies `other` first, then this transform."""
        return AffineTransform.from_matrix(_mul4(self.matrix, other.matrix))

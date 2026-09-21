"""Geometry kernel: construct analytic solids without a B-Rep implementation."""

from jewelry.errors import ContractError, InvalidTransform
from jewelry.kernel.numeric import KERNEL_NUMERIC_TOL
from jewelry.kernel.solids import Body, Box, Cylinder, Primitive, Sphere, TransformedBody
from jewelry.kernel.transform import AffineTransform


class GeometryKernel:
    """Factory for analytic primitives and affine images of those solids."""

    def create_box(self, size: object, origin: object) -> Box:
        return Box.from_arguments(size, origin)

    def create_cylinder(self, radius: object, height: object, origin: object) -> Cylinder:
        return Cylinder.from_arguments(radius, height, origin)

    def create_sphere(self, radius: object, center: object) -> Sphere:
        return Sphere.from_arguments(radius, center)

    def transform(self, body: Body, matrix: object) -> Body:
        try:
            return TransformedBody.apply(body, AffineTransform.from_matrix(matrix))
        except ContractError:
            raise
        except (ArithmeticError, ValueError, OverflowError) as exc:
            raise InvalidTransform(str(exc) or "transform could not be applied") from exc


__all__ = [
    "KERNEL_NUMERIC_TOL",
    "AffineTransform",
    "Body",
    "Box",
    "Cylinder",
    "GeometryKernel",
    "Primitive",
    "Sphere",
    "TransformedBody",
]

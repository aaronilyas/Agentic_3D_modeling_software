"""Geometry kernel: construct analytic solids without a B-Rep implementation."""

from jewelry.kernel.numeric import KERNEL_NUMERIC_TOL
from jewelry.kernel.solids import Body, Box, Cylinder, Primitive, Sphere


class GeometryKernel:
    """Factory for analytic primitives. Transforms and Booleans belong here later."""

    def create_box(self, size: object, origin: object) -> Box:
        return Box.from_arguments(size, origin)

    def create_cylinder(self, radius: object, height: object, origin: object) -> Cylinder:
        return Cylinder.from_arguments(radius, height, origin)

    def create_sphere(self, radius: object, center: object) -> Sphere:
        return Sphere.from_arguments(radius, center)


__all__ = [
    "KERNEL_NUMERIC_TOL",
    "Body",
    "Box",
    "Cylinder",
    "GeometryKernel",
    "Primitive",
    "Sphere",
]

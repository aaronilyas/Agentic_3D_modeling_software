"""Geometry kernel: construct analytic solids without a B-Rep implementation."""

from jewelry.errors import ContractError, InvalidTransform
from jewelry.kernel.boolean import boolean as boolean_bodies
from jewelry.kernel.jewelry import (
    add_setting as add_setting_body,
    create_ring as create_ring_body,
    cut_recess as cut_recess_body,
    cut_through_hole as cut_through_hole_body,
    modify_ring as modify_ring_body,
    repeat_prongs as repeat_prongs_body,
)
from jewelry.kernel.numeric import KERNEL_NUMERIC_TOL
from jewelry.kernel.solids import (
    Annulus,
    Body,
    Box,
    CsgBody,
    Cylinder,
    ExtrudedPolygon,
    Primitive,
    RevolvedSolid,
    Sphere,
    TransformedBody,
)
from jewelry.kernel.sweeps import extrude as extrude_profile
from jewelry.kernel.sweeps import revolve as revolve_profile
from jewelry.kernel.transform import AffineTransform


class GeometryKernel:
    """Factory for analytic primitives, sweeps, and CSG of those solids."""

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

    def extrude(self, profile: object, height: object) -> Body:
        return extrude_profile(profile, height)

    def revolve(self, profile: object, angle_degrees: object) -> Body:
        return revolve_profile(profile, angle_degrees)

    def boolean(self, kind: object, left: Body, right: Body) -> Body:
        return boolean_bodies(kind, left, right)

    def create_ring(self, inner_radius: object, outer_radius: object, width: object) -> Body:
        return create_ring_body(inner_radius, outer_radius, width)

    def modify_ring(self, body: Body, arguments: dict) -> Body:
        return modify_ring_body(body, arguments)

    def cut_through_hole(self, body: Body, center: object, radius: object) -> Body:
        return cut_through_hole_body(body, center, radius)

    def cut_recess(
        self,
        body: Body,
        center: object,
        radius: object,
        top_z: object,
        depth: object,
    ) -> Body:
        return cut_recess_body(body, center, radius, top_z, depth)

    def add_setting(
        self,
        body: Body,
        center: object,
        radius: object,
        base_z: object,
        height: object,
    ) -> Body:
        return add_setting_body(body, center, radius, base_z, height)

    def repeat_prongs(
        self,
        body: Body,
        center: object,
        orbit_radius: object,
        diameter: object,
        base_z: object,
        height: object,
        count: object,
        start_angle_degrees: object,
    ) -> Body:
        return repeat_prongs_body(
            body,
            center,
            orbit_radius,
            diameter,
            base_z,
            height,
            count,
            start_angle_degrees,
        )


__all__ = [
    "KERNEL_NUMERIC_TOL",
    "AffineTransform",
    "Annulus",
    "Body",
    "Box",
    "CsgBody",
    "Cylinder",
    "ExtrudedPolygon",
    "GeometryKernel",
    "Primitive",
    "RevolvedSolid",
    "Sphere",
    "TransformedBody",
]

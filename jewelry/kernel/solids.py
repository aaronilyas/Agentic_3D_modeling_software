"""Analytic solid bodies. Topology is closed-manifold by construction."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from jewelry.kernel.numeric import as_positive_dimension, as_size, as_vec3
from jewelry.kernel.profiles import point_in_polygon, polygon_area, polygon_centroid
from jewelry.kernel.transform import AffineTransform


def closed_solid_topology(components: int = 1) -> dict:
    return {"closed": True, "manifold": True, "components": int(components)}


class Body(ABC):
    """Geometry stored in a document. Later kernels may wrap B-Rep solids."""

    @abstractmethod
    def volume(self) -> float:
        raise NotImplementedError

    @abstractmethod
    def bounds(self) -> list[list[float]]:
        raise NotImplementedError

    @abstractmethod
    def contains(self, point: tuple[float, float, float]) -> bool:
        raise NotImplementedError

    @abstractmethod
    def describe(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def transformed_bounds(self, transform: AffineTransform) -> list[list[float]]:
        raise NotImplementedError

    def topology(self) -> dict:
        return closed_solid_topology()


def _aabb_from_points(points: list[tuple[float, float, float]]) -> list[list[float]]:
    return [
        [min(point[i] for point in points) for i in range(3)],
        [max(point[i] for point in points) for i in range(3)],
    ]


def _union_aabb(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [
        [min(left[0][i], right[0][i]) for i in range(3)],
        [max(left[1][i], right[1][i]) for i in range(3)],
    ]


def _disk_aabb(
    transform: AffineTransform,
    center: tuple[float, float, float],
    radius: float,
) -> list[list[float]]:
    mapped = transform.transform_point(center)
    u = transform.linear_map((radius, 0.0, 0.0))
    v = transform.linear_map((0.0, radius, 0.0))
    extents = (math.hypot(u[0], v[0]), math.hypot(u[1], v[1]), math.hypot(u[2], v[2]))
    return [
        [mapped[i] - extents[i] for i in range(3)],
        [mapped[i] + extents[i] for i in range(3)],
    ]


class Primitive(Body):
    """Single-component analytic solid; a B-Rep kernel can replace these later."""


@dataclass(frozen=True)
class Box(Primitive):
    """Axis-aligned box. `origin` is the minimum corner; `size` is (x, y, z)."""

    origin: tuple[float, float, float]
    size: tuple[float, float, float]

    @classmethod
    def from_arguments(cls, size: object, origin: object) -> Box:
        return cls(origin=as_vec3(origin, "origin"), size=as_size(size, "size"))

    def volume(self) -> float:
        return self.size[0] * self.size[1] * self.size[2]

    def bounds(self) -> list[list[float]]:
        return [
            [self.origin[0], self.origin[1], self.origin[2]],
            [
                self.origin[0] + self.size[0],
                self.origin[1] + self.size[1],
                self.origin[2] + self.size[2],
            ],
        ]

    def contains(self, point: tuple[float, float, float]) -> bool:
        return all(
            self.origin[i] <= point[i] <= self.origin[i] + self.size[i]
            for i in range(3)
        )

    def describe(self) -> dict:
        return {
            "kind": "box",
            "origin": [self.origin[0], self.origin[1], self.origin[2]],
            "size": [self.size[0], self.size[1], self.size[2]],
        }

    def transformed_bounds(self, transform: AffineTransform) -> list[list[float]]:
        ox, oy, oz = self.origin
        sx, sy, sz = self.size
        return _aabb_from_points([
            transform.transform_point((ox + dx, oy + dy, oz + dz))
            for dx in (0.0, sx)
            for dy in (0.0, sy)
            for dz in (0.0, sz)
        ])


@dataclass(frozen=True)
class Cylinder(Primitive):
    """Right circular cylinder. `origin` is the base-disk center; axis is +Z."""

    origin: tuple[float, float, float]
    radius: float
    height: float

    @classmethod
    def from_arguments(cls, radius: object, height: object, origin: object) -> Cylinder:
        return cls(
            origin=as_vec3(origin, "origin"),
            radius=as_positive_dimension(radius, "radius"),
            height=as_positive_dimension(height, "height"),
        )

    def volume(self) -> float:
        return math.pi * self.radius * self.radius * self.height

    def bounds(self) -> list[list[float]]:
        ox, oy, oz = self.origin
        radius = self.radius
        return [
            [ox - radius, oy - radius, oz],
            [ox + radius, oy + radius, oz + self.height],
        ]

    def contains(self, point: tuple[float, float, float]) -> bool:
        dx = point[0] - self.origin[0]
        dy = point[1] - self.origin[1]
        z = point[2]
        in_radius = dx * dx + dy * dy <= self.radius * self.radius
        in_height = self.origin[2] <= z <= self.origin[2] + self.height
        return in_radius and in_height

    def describe(self) -> dict:
        return {
            "kind": "cylinder",
            "origin": [self.origin[0], self.origin[1], self.origin[2]],
            "radius": self.radius,
            "height": self.height,
        }

    def transformed_bounds(self, transform: AffineTransform) -> list[list[float]]:
        ox, oy, oz = self.origin
        return _union_aabb(
            _disk_aabb(transform, (ox, oy, oz), self.radius),
            _disk_aabb(transform, (ox, oy, oz + self.height), self.radius),
        )


@dataclass(frozen=True)
class Sphere(Primitive):
    """Solid ball with the given center and radius."""

    center: tuple[float, float, float]
    radius: float

    @classmethod
    def from_arguments(cls, radius: object, center: object) -> Sphere:
        return cls(
            center=as_vec3(center, "center"),
            radius=as_positive_dimension(radius, "radius"),
        )

    def volume(self) -> float:
        return (4.0 / 3.0) * math.pi * self.radius ** 3

    def bounds(self) -> list[list[float]]:
        cx, cy, cz = self.center
        radius = self.radius
        return [
            [cx - radius, cy - radius, cz - radius],
            [cx + radius, cy + radius, cz + radius],
        ]

    def contains(self, point: tuple[float, float, float]) -> bool:
        dx = point[0] - self.center[0]
        dy = point[1] - self.center[1]
        dz = point[2] - self.center[2]
        return dx * dx + dy * dy + dz * dz <= self.radius * self.radius

    def describe(self) -> dict:
        return {
            "kind": "sphere",
            "center": [self.center[0], self.center[1], self.center[2]],
            "radius": self.radius,
        }

    def transformed_bounds(self, transform: AffineTransform) -> list[list[float]]:
        center = transform.transform_point(self.center)
        extents = tuple(self.radius * transform.linear_row_norm(axis) for axis in range(3))
        return [
            [center[i] - extents[i] for i in range(3)],
            [center[i] + extents[i] for i in range(3)],
        ]


@dataclass(frozen=True)
class TransformedBody(Body):
    """Solid image of `base` under an orientation-preserving affine transform."""

    base: Body
    transform: AffineTransform

    @classmethod
    def apply(cls, body: Body, transform: AffineTransform) -> TransformedBody:
        if isinstance(body, TransformedBody):
            return cls(body.base, transform.compose(body.transform))
        return cls(body, transform)

    def volume(self) -> float:
        return self.base.volume() * self.transform.volume_scale()

    def bounds(self) -> list[list[float]]:
        return self.base.transformed_bounds(self.transform)

    def contains(self, point: tuple[float, float, float]) -> bool:
        return self.base.contains(self.transform.inverse_transform_point(point))

    def describe(self) -> dict:
        return {
            "kind": "transformed",
            "base": self.base.describe(),
            "matrix": list(self.transform.matrix),
        }

    def transformed_bounds(self, transform: AffineTransform) -> list[list[float]]:
        return self.base.transformed_bounds(transform.compose(self.transform))

    def topology(self) -> dict:
        return self.base.topology()


@dataclass(frozen=True)
class ExtrudedPolygon(Body):
    """Right prism of a simple xy polygon, extruded along +Z."""

    vertices: tuple[tuple[float, float], ...]
    zmin: float
    zmax: float

    def volume(self) -> float:
        return abs(polygon_area(self.vertices)) * (self.zmax - self.zmin)

    def bounds(self) -> list[list[float]]:
        xs = [point[0] for point in self.vertices]
        ys = [point[1] for point in self.vertices]
        return [
            [min(xs), min(ys), self.zmin],
            [max(xs), max(ys), self.zmax],
        ]

    def contains(self, point: tuple[float, float, float]) -> bool:
        if not (self.zmin <= point[2] <= self.zmax):
            return False
        return point_in_polygon((point[0], point[1]), self.vertices)

    def describe(self) -> dict:
        return {
            "kind": "extruded",
            "vertices": [list(vertex) for vertex in self.vertices],
            "zmin": self.zmin,
            "zmax": self.zmax,
        }

    def transformed_bounds(self, transform: AffineTransform) -> list[list[float]]:
        return _aabb_from_points([
            transform.transform_point((x, y, z))
            for x, y in self.vertices
            for z in (self.zmin, self.zmax)
        ])


@dataclass(frozen=True)
class RevolvedSolid(Body):
    """360° solid of revolution of an rz polygon about +Z (Pappus)."""

    vertices: tuple[tuple[float, float], ...]

    def volume(self) -> float:
        area = abs(polygon_area(self.vertices))
        centroid_r, _ = polygon_centroid(self.vertices)
        return 2.0 * math.pi * abs(centroid_r) * area

    def bounds(self) -> list[list[float]]:
        radii = [vertex[0] for vertex in self.vertices]
        zs = [vertex[1] for vertex in self.vertices]
        outer = max(radii)
        return [
            [-outer, -outer, min(zs)],
            [outer, outer, max(zs)],
        ]

    def contains(self, point: tuple[float, float, float]) -> bool:
        radius = math.hypot(point[0], point[1])
        return point_in_polygon((radius, point[2]), self.vertices)

    def describe(self) -> dict:
        return {
            "kind": "revolved",
            "vertices": [list(vertex) for vertex in self.vertices],
            "angle_degrees": 360.0,
        }

    def transformed_bounds(self, transform: AffineTransform) -> list[list[float]]:
        lo, hi = self.bounds()
        return _aabb_from_points([
            transform.transform_point((x, y, z))
            for x in (lo[0], hi[0])
            for y in (lo[1], hi[1])
            for z in (lo[2], hi[2])
        ])


@dataclass(frozen=True)
class Annulus(Primitive):
    """Coaxial Z ring: material between inner and outer radius over a Z interval."""

    center_xy: tuple[float, float]
    inner_radius: float
    outer_radius: float
    zmin: float
    zmax: float

    def volume(self) -> float:
        return (
            math.pi
            * (self.outer_radius * self.outer_radius - self.inner_radius * self.inner_radius)
            * (self.zmax - self.zmin)
        )

    def bounds(self) -> list[list[float]]:
        cx, cy = self.center_xy
        radius = self.outer_radius
        return [
            [cx - radius, cy - radius, self.zmin],
            [cx + radius, cy + radius, self.zmax],
        ]

    def contains(self, point: tuple[float, float, float]) -> bool:
        if not (self.zmin <= point[2] <= self.zmax):
            return False
        dx = point[0] - self.center_xy[0]
        dy = point[1] - self.center_xy[1]
        radial = dx * dx + dy * dy
        return self.inner_radius * self.inner_radius <= radial <= self.outer_radius * self.outer_radius

    def describe(self) -> dict:
        return {
            "kind": "annulus",
            "center_xy": [self.center_xy[0], self.center_xy[1]],
            "inner_radius": self.inner_radius,
            "outer_radius": self.outer_radius,
            "zmin": self.zmin,
            "zmax": self.zmax,
        }

    def transformed_bounds(self, transform: AffineTransform) -> list[list[float]]:
        cx, cy = self.center_xy
        return _union_aabb(
            _disk_aabb(transform, (cx, cy, self.zmin), self.outer_radius),
            _disk_aabb(transform, (cx, cy, self.zmax), self.outer_radius),
        )


@dataclass(frozen=True)
class CsgBody(Body):
    """Binary CSG node. Operands are retained; the node is a new solid."""

    op: str
    left: Body
    right: Body

    def volume(self) -> float:
        from jewelry.kernel.evaluate import csg_volume

        return csg_volume(self)

    def bounds(self) -> list[list[float]]:
        if self.op == "subtract":
            return self.left.bounds()
        return _union_aabb(self.left.bounds(), self.right.bounds())

    def contains(self, point: tuple[float, float, float]) -> bool:
        if self.op == "union":
            return self.left.contains(point) or self.right.contains(point)
        return self.left.contains(point) and not self.right.contains(point)

    def describe(self) -> dict:
        return {
            "kind": "csg",
            "op": self.op,
            "left": self.left.describe(),
            "right": self.right.describe(),
        }

    def transformed_bounds(self, transform: AffineTransform) -> list[list[float]]:
        if self.op == "subtract":
            return self.left.transformed_bounds(transform)
        return _union_aabb(
            self.left.transformed_bounds(transform),
            self.right.transformed_bounds(transform),
        )

    def topology(self) -> dict:
        from jewelry.kernel.evaluate import component_count

        return closed_solid_topology(component_count(self))


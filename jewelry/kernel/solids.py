"""Analytic solid bodies. Topology is closed-manifold by construction."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from jewelry.kernel.numeric import as_positive_dimension, as_size, as_vec3


def closed_solid_topology() -> dict:
    return {"closed": True, "manifold": True, "components": 1}


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

    def topology(self) -> dict:
        return closed_solid_topology()


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

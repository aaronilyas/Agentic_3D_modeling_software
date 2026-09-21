"""Boolean construction: classify contact, canonicalize, then commit a CSG node."""

from __future__ import annotations

from jewelry.errors import EmptyResult, InvalidGeometry, ToleranceAmbiguity
from jewelry.kernel.evaluate import bake_transform, classify_contact, intersection_volume
from jewelry.kernel.numeric import KERNEL_NUMERIC_TOL
from jewelry.kernel.solids import Annulus, Body, CsgBody, Cylinder


def boolean(kind: object, left: Body, right: Body) -> Body:
    if kind not in ("union", "subtract"):
        raise InvalidGeometry(
            "INVALID_ARGUMENT",
            "kind must be 'union' or 'subtract'",
        )
    left = bake_transform(left)
    right = bake_transform(right)
    if kind == "union":
        return _union(left, right)
    return _subtract(left, right)


def _union(left: Body, right: Body) -> Body:
    relation = classify_contact(left, right)
    if relation == "ambiguous":
        raise ToleranceAmbiguity()
    if relation in {"point"}:
        raise InvalidGeometry(
            "NON_MANIFOLD",
            "union meets at a non-manifold point or edge",
        )
    return _commit(CsgBody("union", left, right))


def _subtract(left: Body, right: Body) -> Body:
    # Self-subtract is empty; EMPTY_RESULT rather than a solid with volume 0.
    if left is right:
        raise EmptyResult()
    canonical = _canonicalize_through_bore(left, right)
    if canonical is not None:
        return canonical
    shared = intersection_volume((left, right))
    remaining = left.volume() - shared
    volume_floor = KERNEL_NUMERIC_TOL * max(abs(left.volume()), KERNEL_NUMERIC_TOL)
    if remaining <= volume_floor:
        raise EmptyResult()
    return _commit(CsgBody("subtract", left, right))


def _commit(body: CsgBody) -> CsgBody:
    """A successful boolean must be inspectable: volume and topology evaluate now."""
    body.volume()
    body.topology()
    return body


def _canonicalize_through_bore(left: Body, right: Body) -> Annulus | None:
    if not isinstance(left, Cylinder) or not isinstance(right, Cylinder):
        return None
    if not _coaxial(left, right):
        return None
    if right.radius >= left.radius:
        return None
    if not _z_covers(right, left):
        return None
    return Annulus(
        center_xy=(left.origin[0], left.origin[1]),
        inner_radius=right.radius,
        outer_radius=left.radius,
        zmin=left.origin[2],
        zmax=left.origin[2] + left.height,
    )


def _coaxial(left: Cylinder, right: Cylinder) -> bool:
    return (
        abs(left.origin[0] - right.origin[0]) <= KERNEL_NUMERIC_TOL
        and abs(left.origin[1] - right.origin[1]) <= KERNEL_NUMERIC_TOL
    )


def _z_covers(inner: Cylinder, outer: Cylinder) -> bool:
    inner_min, inner_max = inner.origin[2], inner.origin[2] + inner.height
    outer_min, outer_max = outer.origin[2], outer.origin[2] + outer.height
    return inner_min <= outer_min + KERNEL_NUMERIC_TOL and inner_max >= outer_max - KERNEL_NUMERIC_TOL

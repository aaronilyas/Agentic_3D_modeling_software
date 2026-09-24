"""Rebuild solids from the feature list. Features are the semantic source of truth."""

from __future__ import annotations

from cad.errors import InvalidGeometry, UnknownReference
from cad.features import Feature


def evaluate(feature: Feature, solids: dict, sketches: dict, backend):
    params = feature.params
    op = feature.op
    if op == "box":
        return backend.box(params["size"], params["origin"])
    if op == "cylinder":
        return backend.cylinder(params["radius"], params["height"], params["origin"])
    if op == "sphere":
        return backend.sphere(params["radius"], params["center"])
    if op == "extrude":
        profile = sketches[params["sketch_id"]] if params.get("sketch_id") else params["profile"]
        return backend.extrude(profile, params["height"])
    if op == "revolve":
        profile = sketches[params["sketch_id"]] if params.get("sketch_id") else params["profile"]
        return backend.revolve(profile, params["angle_degrees"])
    if op == "sweep":
        return backend.sweep(params["profile"], params["path"])
    if op == "loft":
        return backend.loft(params["profiles"], params["stations"])
    if op == "boolean":
        return backend.boolean(params["kind"], _solid(solids, params["left"]), _solid(solids, params["right"]))
    if op == "transform":
        return backend.transform(_solid(solids, params["target"]), params["matrix"])
    if op == "fillet":
        return backend.fillet(
            _solid(solids, params["target"]), params["radius"],
            params.get("edge_ids"), params.get("selector"),
        )
    if op == "chamfer":
        return backend.chamfer(
            _solid(solids, params["target"]), params["distance"],
            params.get("edge_ids"), params.get("selector"),
        )
    if op == "shell":
        return backend.shell(
            _solid(solids, params["target"]), params["thickness"], params.get("face_ids"),
        )
    if op == "hole":
        return backend.hole(
            _solid(solids, params["target"]), params["position"], params["direction"],
            params["diameter"], params.get("depth"), bool(params.get("through")),
        )
    if op == "mirror":
        return backend.mirror(
            _solid(solids, params["target"]), params["plane"],
            params.get("origin"), params.get("normal"), bool(params.get("keep_original")),
        )
    if op == "linear_pattern":
        return backend.linear_pattern(
            _solid(solids, params["target"]), params["direction"], params["spacing"], params["count"],
        )
    if op == "circular_pattern":
        return backend.circular_pattern(
            _solid(solids, params["target"]), params["origin"], params["direction"], params["count"],
        )
    if op == "duplicate":
        return backend.import_brep_bytes(params["brep"])
    raise InvalidGeometry(f"cannot replay feature operation {op}")


def replay(features: list[Feature], backend) -> tuple[dict, dict]:
    solids: dict = {}
    sketches: dict = {}
    for feature in features:
        if feature.op == "sketch":
            sketches[feature.id] = feature.params["profile"]
            continue
        if feature.op in {"rename", "delete"}:
            if feature.op == "delete":
                solids.pop(feature.params["ref"], None)
            continue
        try:
            shape = evaluate(feature, solids, sketches, backend)
        except KeyError as exc:
            raise UnknownReference(f"replay is missing {exc}") from exc
        if feature.output_ref:
            solids[feature.output_ref] = shape
    return solids, sketches


def _solid(solids: dict, ref: str):
    try:
        return solids[ref]
    except KeyError as exc:
        raise UnknownReference(f"feature dependency {ref} is not a live solid") from exc

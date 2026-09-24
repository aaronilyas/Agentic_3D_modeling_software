"""Rebuild solids from the feature list. Features are the semantic source of truth."""

from __future__ import annotations

from cad.errors import InvalidGeometry, UnknownReference
from cad.features import Feature
from cad.operations import REPLAY


def evaluate(feature: Feature, solids: dict, sketches: dict, backend):
    evaluator = REPLAY.get(feature.op)
    if evaluator is None:
        raise InvalidGeometry(f"cannot replay feature operation {feature.op}")
    return evaluator(feature.params, solids, sketches, backend)


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

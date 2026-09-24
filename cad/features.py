"""Semantic feature records. Parameters are the editable source of truth."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from cad.operations import BODY_INPUTS, FEATURE_INPUTS, EDITABLE, REPLAY


@dataclass
class Feature:
    id: str
    op: str
    params: dict
    output_ref: str | None = None
    name: str = ""

    @property
    def input_refs(self) -> tuple[str, ...]:
        return tuple(self.params[key] for key in BODY_INPUTS.get(self.op, ()) if self.params.get(key))

    @property
    def input_features(self) -> tuple[str, ...]:
        return tuple(self.params[key] for key in FEATURE_INPUTS.get(self.op, ()) if self.params.get(key))

    @property
    def editable_parameters(self) -> tuple[str, ...]:
        return tuple(sorted(EDITABLE.get(self.op, ())))

    @property
    def replayable(self) -> bool:
        return self.op in REPLAY or self.op in {"sketch", "rename", "delete"}

    def clone(self, **updates) -> Feature:
        params = copy.deepcopy(self.params)
        if "params" in updates:
            params.update(copy.deepcopy(updates.pop("params")))
        payload = {
            "id": self.id,
            "op": self.op,
            "params": params,
            "output_ref": self.output_ref,
            "name": self.name,
        }
        payload.update(updates)
        return Feature(**payload)

    def to_public(self) -> dict:
        params = {}
        for key, value in self.params.items():
            if key == "brep":
                params[key] = {"omitted_bytes": len(value)}
            else:
                params[key] = copy.deepcopy(value)
        return {
            "id": self.id,
            "op": self.op,
            "params": params,
            "output_ref": self.output_ref,
            "name": self.name,
            "input_refs": list(self.input_refs),
            "input_features": list(self.input_features),
            "editable_parameters": list(self.editable_parameters),
            "replayable": self.replayable,
        }


def dependency_graph(features: list[Feature]) -> dict[str, tuple[str, ...]]:
    """Bind body inputs to the producer preceding each feature in history."""
    producers = {}
    graph = {}
    for feature in features:
        graph[feature.id] = tuple(dict.fromkeys([
            *feature.input_features,
            *(producers[ref] for ref in feature.input_refs if ref in producers),
        ]))
        if feature.output_ref:
            producers[feature.output_ref] = feature.id
        if feature.op == "delete":
            producers.pop(feature.params["ref"], None)
    return graph

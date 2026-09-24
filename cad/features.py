"""Semantic feature records. Parameters are the editable source of truth."""

from __future__ import annotations

import copy
from dataclasses import dataclass


@dataclass
class Feature:
    id: str
    op: str
    params: dict
    output_ref: str | None = None
    name: str = ""

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
        }

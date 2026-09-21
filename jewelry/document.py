"""Committed document state: bodies, opaque references, revision."""

from __future__ import annotations

import copy

from jewelry.errors import UnknownReference
from jewelry.kernel.solids import Body


class Document:
    def __init__(self) -> None:
        self._bodies: dict[str, Body] = {}
        self._next_serial = 1
        self._revision = 0

    def insert(self, body: Body) -> str:
        ref = f"body-{self._next_serial}"
        self._next_serial += 1
        self._bodies[ref] = body
        self._revision += 1
        return ref

    def resolve(self, ref: object) -> Body:
        if not isinstance(ref, str):
            raise UnknownReference()
        body = self._bodies.get(ref)
        if body is None:
            raise UnknownReference()
        return body

    def snapshot(self) -> dict:
        return copy.deepcopy({
            "references": list(self._bodies),
            "revision": self._revision,
            "undo": [],
            "redo": [],
            "bodies": [
                {"ref": ref, **body.describe()}
                for ref, body in self._bodies.items()
            ],
        })

    def clear(self) -> None:
        self._bodies.clear()

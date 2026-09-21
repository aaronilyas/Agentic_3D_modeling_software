"""Committed document state: bodies, opaque references, revision, undo/redo."""

from __future__ import annotations

import copy

from jewelry.errors import EmptyHistory, UnknownReference
from jewelry.kernel.solids import Body


def _history_entry(bodies: dict[str, Body], revision: int) -> dict:
    return {
        "revision": revision,
        "references": list(bodies),
        "bodies": [{"ref": ref, **body.describe()} for ref, body in bodies.items()],
    }


class Document:
    def __init__(self) -> None:
        self._bodies: dict[str, Body] = {}
        self._next_serial = 1
        self._revision = 0
        self._undo: list[tuple[dict[str, Body], int]] = []
        self._redo: list[tuple[dict[str, Body], int]] = []

    @property
    def bodies(self) -> dict[str, Body]:
        return self._bodies

    @property
    def revision(self) -> int:
        return self._revision

    def peek_ref(self) -> str:
        return f"body-{self._next_serial}"

    def commit(self, bodies: dict[str, Body], *, consume_serial: bool = False) -> None:
        self._undo.append((dict(self._bodies), self._revision))
        self._redo.clear()
        self._bodies = dict(bodies)
        self._revision += 1
        # A04: serial never rewinds on undo; new bodies never reuse old refs.
        if consume_serial:
            self._next_serial += 1

    def undo(self) -> None:
        if not self._undo:
            raise EmptyHistory()
        self._redo.append((dict(self._bodies), self._revision))
        bodies, _revision = self._undo.pop()
        self._bodies = dict(bodies)
        self._revision += 1

    def redo(self) -> None:
        if not self._redo:
            raise EmptyHistory()
        self._undo.append((dict(self._bodies), self._revision))
        bodies, _revision = self._redo.pop()
        self._bodies = dict(bodies)
        self._revision += 1

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
            "undo": [_history_entry(bodies, revision) for bodies, revision in self._undo],
            "redo": [_history_entry(bodies, revision) for bodies, revision in self._redo],
            "bodies": [
                {"ref": ref, **body.describe()}
                for ref, body in self._bodies.items()
            ],
        })

    def clear(self) -> None:
        self._bodies.clear()
        self._undo.clear()
        self._redo.clear()
        self._revision = 0
        self._next_serial = 1

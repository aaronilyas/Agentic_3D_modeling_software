"""Authoritative document: feature graph, shape cache, assets, revision, undo."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

from cad.errors import EmptyHistory, UnknownFeature, UnknownReference
from cad.features import Feature


@dataclass
class DocumentState:
    features: list[Feature]
    solids: dict
    sketches: dict
    names: dict
    assets: list
    settings: dict
    revision: int


@dataclass
class Document:
    copy_shape: Callable[[object], object] = field(default=copy.deepcopy, repr=False, kw_only=True)
    features: list[Feature] = field(default_factory=list)
    solids: dict = field(default_factory=dict)
    sketches: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)
    assets: list = field(default_factory=list)
    settings: dict = field(default_factory=lambda: {"units": "mm", "axes": "right-handed-z-up"})
    revision: int = 0
    _serials: dict = field(default_factory=lambda: {"feature": 1, "body": 1, "asset": 1})
    _undo: list = field(default_factory=list)
    _redo: list = field(default_factory=list)

    def peek(self, kind: str) -> str:
        return f"{kind}-{self._serials[kind]}"

    def references(self) -> tuple[str, ...]:
        return tuple(self.solids)

    def has_ref(self, ref: object) -> bool:
        return isinstance(ref, str) and ref in self.solids

    def resolve(self, ref: object):
        if not isinstance(ref, str) or ref not in self.solids:
            raise UnknownReference()
        return self.solids[ref]

    def feature(self, feature_id: object) -> Feature:
        if not isinstance(feature_id, str):
            raise UnknownFeature()
        for item in self.features:
            if item.id == feature_id:
                return item
        raise UnknownFeature()

    def capture(self) -> DocumentState:
        return DocumentState(
            features=copy.deepcopy(self.features),
            solids={key: self.copy_shape(value) for key, value in self.solids.items()},
            sketches=copy.deepcopy(self.sketches),
            names=copy.deepcopy(self.names),
            assets=copy.deepcopy(self.assets),
            settings=copy.deepcopy(self.settings),
            revision=self.revision,
        )

    def _install(self, state: DocumentState) -> None:
        self.features = state.features
        self.solids = state.solids
        self.sketches = state.sketches
        self.names = state.names
        self.assets = state.assets
        self.settings = state.settings

    def commit(
        self,
        *,
        features: list[Feature],
        solids: dict,
        sketches: dict | None = None,
        names: dict | None = None,
        assets: list | None = None,
        settings: dict | None = None,
        consume: dict | None = None,
    ) -> None:
        self._undo.append(self.capture())
        self._redo.clear()
        self.features = features
        self.solids = solids
        if sketches is not None:
            self.sketches = sketches
        if names is not None:
            self.names = names
        if assets is not None:
            self.assets = assets
        if settings is not None:
            self.settings = settings
        for kind, count in (consume or {}).items():
            self._serials[kind] += int(count)
        self.revision += 1

    def undo(self) -> None:
        if not self._undo:
            raise EmptyHistory()
        self._redo.append(self.capture())
        self._install(self._undo.pop())
        self.revision += 1

    def redo(self) -> None:
        if not self._redo:
            raise EmptyHistory()
        self._undo.append(self.capture())
        self._install(self._redo.pop())
        self.revision += 1

    def history_public(self, entries: list[DocumentState]) -> list[dict]:
        public = []
        for state in entries:
            public.append({
                "revision": state.revision,
                "references": list(state.solids),
                "feature_ids": [feature.id for feature in state.features],
            })
        return public

    def replace(self, *, features, solids, sketches, names, assets, settings, serials) -> None:
        self._undo.append(self.capture())
        self._redo.clear()
        self.features = features
        self.solids = solids
        self.sketches = sketches
        self.names = names
        self.assets = assets
        self.settings = settings
        self._serials = {kind: max(self._serials[kind], serials[kind]) for kind in self._serials}
        self.revision += 1

    def clear(self) -> None:
        self.features.clear()
        self.solids.clear()
        self.sketches.clear()
        self.names.clear()
        self.assets.clear()
        self._undo.clear()
        self._redo.clear()
        self.revision = 0
        self._serials = {"feature": 1, "body": 1, "asset": 1}

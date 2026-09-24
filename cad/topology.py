"""Semantic topology ids. Raw kernel indices are not part of the public contract."""

from __future__ import annotations

import hashlib
import math


def _round(value: float, digits: int = 4) -> float:
    if value is None:
        return 0.0
    number = float(value)
    if not math.isfinite(number):
        return 0.0
    return round(number, digits)


def _vec(values) -> tuple:
    if not values:
        return ()
    return tuple(_round(item) for item in values)


def assign_ids(kind: str, records: list[dict]) -> list[dict]:
    """Geometry fingerprints plus an ordinal, scoped to a queried revision.

    Equal geometric keys use kernel index as a tie-breaker. This is stable for
    repeated inspection of one shape, not persistent naming after recomputation.
    Preserve version-1 fingerprints for stored feature selections.
    """
    decorated = []
    for record in records:
        key = (
            record.get("geom") or "",
            _round(record.get("area", record.get("length", 0.0)), 4),
            _vec(record.get("center")),
            _vec(record.get("normal") or record.get("direction")),
            _round(record.get("radius") or 0.0, 4),
        )
        decorated.append((key, record))
    decorated.sort(key=lambda item: (item[0], item[1].get("index", 0)))
    assigned = []
    used = set()
    for ordinal, (key, record) in enumerate(decorated):
        payload = f"{kind}|{ordinal}|{key}".encode("utf-8")
        digest = hashlib.sha1(payload).hexdigest()[:12]
        public = dict(record)
        public["ordinal"] = ordinal
        identifier = f"{kind}-{digest}"
        if identifier in used:
            identifier += f"-{ordinal}"
        used.add(identifier)
        public["id"] = identifier
        assigned.append(public)
    return assigned


def index_by_id(records: list[dict]) -> dict[str, dict]:
    return {record["id"]: record for record in records}


def adjacent_ids(faces: list[dict], edges: list[dict]) -> None:
    by_index = {face.get("index"): face["id"] for face in faces}
    for face in faces:
        face["adjacent"] = []
    incoming = {face["id"]: [] for face in faces}
    for edge in edges:
        ids = [by_index[index] for index in edge.get("face_indices", []) if index in by_index]
        edge["face_ids"] = ids
        for face_id in ids:
            incoming[face_id].extend(other for other in ids if other != face_id)
    for face in faces:
        seen = []
        for item in incoming.get(face["id"], []):
            if item not in seen:
                seen.append(item)
        face["adjacent"] = seen

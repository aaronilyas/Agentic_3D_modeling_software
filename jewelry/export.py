"""Atomic STL publish. Validation reports authorize current geometry only."""

from __future__ import annotations

import os
import struct
import tempfile

from jewelry.document import Document
from jewelry.errors import ContractError
from jewelry.kernel.solids import Body
from jewelry.mesh import mesh_findings, parse_mesh
from jewelry.tessellate import tessellate_body
from jewelry.validator import validate_document


def export_body(
    body: Body,
    *,
    path: object,
    format: object,
    validation: object,
    chord_tolerance: object,
    document: Document,
) -> dict:
    _require_stl(format)
    destination = _require_path(path)
    _authorize(validation, document)
    mesh = tessellate_body(body, chord_tolerance)
    payload = stl_bytes(mesh["vertices"], mesh["triangles"])
    publish_bytes(destination, payload)
    return {"revision": document.revision}


def export_mesh(
    vertices: object,
    triangles: object,
    *,
    path: object,
    format: object,
) -> dict:
    _require_stl(format)
    destination = _require_path(path)
    parsed_vertices, parsed_triangles = parse_mesh(vertices, triangles)
    findings, metrics = mesh_findings(parsed_vertices, parsed_triangles)
    if findings:
        raise ContractError("INVALID_MESH", findings[0]["message"])
    payload = stl_bytes(
        [list(vertex) for vertex in metrics["vertices"]],
        metrics["triangles"],
    )
    publish_bytes(destination, payload)
    return {"revision": None}


def stl_bytes(vertices: list[list[float]], triangles: list[list[int]]) -> bytes:
    header = b"jewelry mm" + b"\0" * (80 - 10)
    records = [header, struct.pack("<I", len(triangles))]
    for face in triangles:
        a, b, c = (vertices[i] for i in face)
        nx, ny, nz = _facet_normal(a, b, c)
        records.append(struct.pack(
            "<12fH",
            nx, ny, nz,
            float(a[0]), float(a[1]), float(a[2]),
            float(b[0]), float(b[1]), float(b[2]),
            float(c[0]), float(c[1]), float(c[2]),
            0,
        ))
    return b"".join(records)


def publish_bytes(path: str, data: bytes) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise ContractError("INVALID_ARGUMENT", "export parent is not a directory")
    fd, tmp = tempfile.mkstemp(prefix=".jewelry-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)  # atomic publish on the same filesystem
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _authorize(validation: object, document: Document) -> None:
    if not isinstance(validation, dict):
        raise ContractError("INVALID_ARGUMENT", "validation must be a report object")
    rules = validation.get("rules")
    if rules is None:
        rules = validation.get("profile")
    if not isinstance(rules, dict):
        raise ContractError("INVALID_ARGUMENT", "validation report has no rules")
    # Always revalidate live document geometry. A ready flag on a mesh-only
    # report (or any client-supplied dict) must not authorize export.
    report = validate_document(document, rules)
    if not report["ready"]:
        raise ContractError(
            "NOT_MANUFACTURING_READY",
            "current geometry is not manufacturing-ready under the report rules",
        )


def _require_stl(format: object) -> None:
    if not isinstance(format, str) or format.strip().lower() != "stl":
        raise ContractError("INVALID_ARGUMENT", "only stl export is supported")


def _require_path(path: object) -> str:
    if not isinstance(path, (str, os.PathLike)) or not str(path):
        raise ContractError("INVALID_ARGUMENT", "export path must be a nonempty string")
    return os.fspath(path)


def _facet_normal(a, b, c) -> tuple[float, float, float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = (nx * nx + ny * ny + nz * nz) ** 0.5
    if length == 0.0:
        return (0.0, 0.0, 0.0)
    return (nx / length, ny / length, nz / length)

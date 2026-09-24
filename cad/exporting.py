"""Format registry. Exact CAD and mesh exports stay on separate paths."""

from __future__ import annotations

import os
import shutil
import struct
import tempfile
from collections import Counter
from pathlib import Path

from cad.errors import ExportError, InvalidArgument, InvalidMesh, MissingCapability

FORMATS = {
    "step": {
        "extensions": [".step", ".stp"],
        "geometry": "brep",
        "manufacturing_default": False,
        "description": "Precise STEP AP214 B-rep. Coordinates are millimetres.",
    },
    "glb": {
        "extensions": [".glb"],
        "geometry": "mesh",
        "manufacturing_default": False,
        "description": "glTF binary mesh. Coordinates are metres converted from millimetres.",
    },
    "stl": {
        "extensions": [".stl"],
        "geometry": "mesh",
        "manufacturing_default": True,
        "description": "Binary STL triangle mesh. STL has no unit metadata; coordinates are millimetres.",
    },
    "obj": {
        "extensions": [".obj"],
        "geometry": "mesh",
        "manufacturing_default": False,
        "description": "Wavefront OBJ triangle mesh. Coordinates are millimetres.",
    },
    "blend": {
        "extensions": [".blend"],
        "geometry": "mesh",
        "manufacturing_default": False,
        "description": "Blender file written by headless Blender from a generated glTF mesh.",
    },
}


def list_formats(blender_available: bool) -> list[dict]:
    listed = []
    for name, spec in FORMATS.items():
        available = blender_available if name == "blend" else True
        listed.append({
            "format": name,
            "extensions": list(spec["extensions"]),
            "geometry": spec["geometry"],
            "manufacturing_default": spec["manufacturing_default"],
            "available": available,
            "description": spec["description"],
        })
    return listed


def normalize_format(name: object) -> str:
    if not isinstance(name, str) or name.strip().lower() not in FORMATS:
        raise InvalidArgument(
            "format must be one of " + ", ".join(FORMATS)
        )
    return name.strip().lower()


def publish_bytes(path: str, data: bytes) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise ExportError("export parent is not a directory")
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".cad-", suffix=".tmp", dir=parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        tmp = None
    except OSError as exc:
        raise ExportError(str(exc)) from exc
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def step_bytes(backend, shape) -> bytes:
    fd, path = tempfile.mkstemp(prefix=".cad-", suffix=".step")
    os.close(fd)
    try:
        backend.export_step(shape, path)
        data = Path(path).read_bytes()
    finally:
        _unlink(path)
    if b"ISO-10303-21" not in data[:400]:
        raise InvalidMesh("STEP writer did not produce a STEP header")
    return data


def glb_bytes(backend, shape, chord: float) -> bytes:
    fd, path = tempfile.mkstemp(prefix=".cad-", suffix=".glb")
    os.close(fd)
    try:
        backend.export_gltf(shape, path, chord)
        data = Path(path).read_bytes()
    finally:
        _unlink(path)
    if not data.startswith(b"glTF"):
        raise InvalidMesh("glTF writer did not produce a GLB file")
    return data


def stl_bytes(vertices, triangles) -> bytes:
    welded_vertices, welded = weld(vertices, triangles)
    _require_closed_mesh(welded_vertices, welded)
    header = b"agentic-cad mm" + b"\0" * (80 - len(b"agentic-cad mm"))
    records = [header, struct.pack("<I", len(welded))]
    for tri in welded:
        a, b, c = (welded_vertices[index] for index in tri)
        normal = _normal(a, b, c)
        records.append(struct.pack(
            "<12fH",
            normal[0], normal[1], normal[2],
            a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2], 0,
        ))
    return b"".join(records)


def obj_bytes(vertices, triangles) -> bytes:
    welded_vertices, welded = weld(vertices, triangles)
    _require_closed_mesh(welded_vertices, welded)
    lines = ["# units mm", "o solid"]
    for vertex in welded_vertices:
        lines.append(f"v {vertex[0]:.6f} {vertex[1]:.6f} {vertex[2]:.6f}")
    for tri in welded:
        lines.append(f"f {tri[0] + 1} {tri[1] + 1} {tri[2] + 1}")
    return ("\n".join(lines) + "\n").encode("ascii")


def blend_bytes(backend, shape, chord: float, runner) -> bytes:
    if runner is None:
        blender = shutil.which("blender")
        if not blender:
            raise MissingCapability("Blender is not on PATH; .blend export needs headless Blender")
        runner = _blender_runner(blender)
    fd, glb_path = tempfile.mkstemp(prefix=".cad-", suffix=".glb")
    os.close(fd)
    fd, blend_path = tempfile.mkstemp(prefix=".cad-", suffix=".blend")
    os.close(fd)
    try:
        backend.export_gltf(shape, glb_path, chord)
        try:
            runner(glb_path, blend_path)
        except ExportError:
            raise
        except Exception as exc:
            raise ExportError(str(exc) or "Blender export failed") from exc
        data = Path(blend_path).read_bytes()
    finally:
        _unlink(glb_path)
        _unlink(blend_path)
    if not data:
        raise ExportError("Blender did not write a blend file")
    return data


def weld(vertices, triangles, digits: int = 6):
    index = {}
    welded = []
    remap = []
    for vertex in vertices:
        key = tuple(round(float(component), digits) for component in vertex)
        if key not in index:
            index[key] = len(welded)
            welded.append([float(component) for component in key])
        remap.append(index[key])
    mapped = []
    for tri in triangles:
        if len(tri) != 3:
            raise InvalidMesh("triangle must have 3 indices")
        mapped.append([remap[int(item)] for item in tri])
    return welded, mapped


def _require_closed_mesh(vertices, triangles) -> None:
    if not triangles:
        raise InvalidMesh("mesh has no triangles")
    edges: Counter = Counter()
    for tri in triangles:
        if len(set(tri)) < 3:
            raise InvalidMesh("mesh has a degenerate triangle")
        for index in tri:
            if index < 0 or index >= len(vertices):
                raise InvalidMesh("mesh index is out of range")
            if not all(map(_finite, vertices[index])):
                raise InvalidMesh("mesh coordinate is not finite")
        edges[tuple(sorted((tri[0], tri[1])))] += 1
        edges[tuple(sorted((tri[1], tri[2])))] += 1
        edges[tuple(sorted((tri[2], tri[0])))] += 1
    bad = [edge for edge, count in edges.items() if count != 2]
    if bad:
        raise InvalidMesh(f"mesh has {len(bad)} edges that are not shared by two triangles")


def _normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = (nx * nx + ny * ny + nz * nz) ** 0.5
    if length == 0:
        return (0.0, 0.0, 0.0)
    return (nx / length, ny / length, nz / length)


def _finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _blender_runner(blender: str):
    def run(glb_path: str, blend_path: str) -> None:
        script = (
            "import bpy, sys\n"
            "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "bpy.ops.import_scene.gltf(filepath=sys.argv[-2])\n"
            "bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])\n"
        )
        fd, script_path = tempfile.mkstemp(prefix=".cad-", suffix=".py")
        os.close(fd)
        Path(script_path).write_text(script, encoding="utf-8")
        try:
            import subprocess
            completed = subprocess.run(
                [blender, "--background", "--python", script_path, "--", glb_path, blend_path],
                check=False, capture_output=True, text=True,
            )
            if completed.returncode != 0 or not os.path.isfile(blend_path):
                message = (completed.stderr or completed.stdout or "Blender export failed").strip()
                raise ExportError(message[-500:])
        finally:
            _unlink(script_path)
    return run

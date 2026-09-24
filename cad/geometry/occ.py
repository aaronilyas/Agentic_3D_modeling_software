"""OpenCascade geometry via build123d.

Shapes stored in the document are B-rep solids. Meshes are produced only by
tessellation for display and mesh exports. STEP is written from the B-rep.
"""

from __future__ import annotations

import copy
import math
import os
import tempfile
from pathlib import Path

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform, BRepBuilderAPI_Transform
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.collections import (
    IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher,
)
from OCP.gp import gp_Ax1, gp_Dir, gp_GTrsf, gp_Mat, gp_Pnt, gp_Trsf, gp_XYZ

from cad.errors import EmptyResult, InvalidArgument, InvalidGeometry, TopologyNotFound
from cad.topology import assign_ids

try:
    import build123d as bd
except ImportError as exc:  # pragma: no cover - exercised when the extra is absent
    bd = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _require_build123d() -> None:
    if bd is None:
        raise InvalidGeometry(
            "build123d is not installed; the OpenCascade backend cannot run"
        ) from _IMPORT_ERROR


def _xyz(vector) -> list[float]:
    return [float(vector.X), float(vector.Y), float(vector.Z)]


def _unit(vector: tuple[float, float, float], name: str) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 1e-12:
        raise InvalidGeometry(f"{name} must be a nonzero vector")
    return tuple(component / length for component in vector)


def _canonical(direction: list[float]) -> list[float]:
    for component in direction:
        if abs(component) > 1e-9:
            if component < 0:
                return [-item for item in direction]
            break
    return direction


class OccBackend:
    """Exact B-rep operations. The backend never turns a mesh back into a solid."""

    name = "build123d"

    def __init__(self) -> None:
        _require_build123d()

    def box(self, size, origin) -> object:
        shape = bd.Pos(*origin) * bd.Box(
            size[0], size[1], size[2],
            align=(bd.Align.MIN, bd.Align.MIN, bd.Align.MIN),
        )
        return self._require_solid(shape)

    def cylinder(self, radius, height, origin) -> object:
        shape = bd.Pos(*origin) * bd.Cylinder(
            radius, height,
            align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
        )
        return self._require_solid(shape)

    def sphere(self, radius, center) -> object:
        return self._require_solid(bd.Pos(*center) * bd.Sphere(radius))

    def extrude(self, profile, height) -> object:
        if height <= 0:
            raise InvalidGeometry("extrude height must be greater than zero")
        face = bd.make_face(bd.Polyline(*[(point[0], point[1]) for point in profile], close=True))
        return self._require_solid(bd.extrude(face, amount=height))

    def revolve(self, profile, angle_degrees) -> object:
        if angle_degrees <= 0 or angle_degrees > 360:
            raise InvalidGeometry("revolve angle must be within (0, 360] degrees")
        for radius, _z in profile:
            if radius < -1e-9:
                raise InvalidGeometry("revolve radius must not be negative")
        face = bd.Plane.XZ * bd.make_face(
            bd.Polyline(*[(point[0], point[1]) for point in profile], close=True)
        )
        return self._require_solid(bd.revolve(face, axis=bd.Axis.Z, revolution_arc=angle_degrees))

    def sweep(self, profile, path) -> object:
        points = [tuple(point) for point in path]
        tangent = _unit(
            (points[1][0] - points[0][0], points[1][1] - points[0][1], points[1][2] - points[0][2]),
            "sweep path",
        )
        section = bd.Plane(origin=points[0], z_dir=tangent) * bd.make_face(
            bd.Polyline(*[(point[0], point[1]) for point in profile], close=True)
        )
        wire = bd.Polyline(*points)
        try:
            solid = bd.sweep(section, wire, transition=bd.Transition.RIGHT, clean=True)
        except Exception as exc:
            raise InvalidGeometry(str(exc) or "sweep failed") from exc
        return self._require_solid(solid)

    def loft(self, profiles, stations) -> object:
        if len(profiles) < 2 or len(profiles) != len(stations):
            raise InvalidArgument("loft needs one station height per profile")
        faces = []
        for profile, height in zip(profiles, stations):
            face = bd.Pos(0, 0, height) * bd.make_face(
                bd.Polyline(*[(point[0], point[1]) for point in profile], close=True)
            )
            faces.append(face)
        try:
            solid = bd.loft(faces)
        except Exception as exc:
            raise InvalidGeometry(str(exc) or "loft failed") from exc
        return self._require_solid(solid)

    def boolean(self, kind, left, right) -> object:
        left = self.copy(left)
        right = self.copy(right)
        try:
            if kind == "union":
                result = left + right
            elif kind == "subtract":
                result = left - right
            elif kind == "intersection":
                result = left & right
            else:
                raise InvalidArgument("boolean kind must be union, subtract, or intersection")
        except InvalidArgument:
            raise
        except Exception as exc:
            raise InvalidGeometry(str(exc) or "boolean failed") from exc
        return self._require_solid(result)

    def transform(self, shape, matrix) -> object:
        mat = gp_Mat(
            matrix[0], matrix[1], matrix[2],
            matrix[4], matrix[5], matrix[6],
            matrix[8], matrix[9], matrix[10],
        )
        gtrsf = gp_GTrsf(mat, gp_XYZ(matrix[3], matrix[7], matrix[11]))
        builder = BRepBuilderAPI_GTransform(self.copy(shape).wrapped, gtrsf, True)
        if not builder.IsDone():
            raise InvalidGeometry("transform could not be applied")
        return self._require_solid(bd.Shape.cast(builder.Shape()))

    def translate(self, shape, vector) -> object:
        return self._require_solid(bd.Pos(*vector) * self.copy(shape))

    def fillet(self, shape, radius, edge_ids=None, selector=None) -> object:
        if radius <= 0:
            raise InvalidGeometry("fillet radius must be greater than zero")
        shape = self.copy(shape)
        edges = self._select_edges(shape, edge_ids, selector, min_length=radius * 2)
        try:
            result = bd.fillet(edges, radius)
        except Exception as exc:
            raise InvalidGeometry(str(exc) or "fillet failed") from exc
        return self._require_solid(result)

    def chamfer(self, shape, distance, edge_ids=None, selector=None) -> object:
        if distance <= 0:
            raise InvalidGeometry("chamfer distance must be greater than zero")
        shape = self.copy(shape)
        edges = self._select_edges(shape, edge_ids, selector, min_length=distance * 2)
        try:
            result = bd.chamfer(edges, distance)
        except Exception as exc:
            raise InvalidGeometry(str(exc) or "chamfer failed") from exc
        return self._require_solid(result)

    def shell(self, shape, thickness, face_ids=None) -> object:
        if thickness <= 0:
            raise InvalidGeometry("shell thickness must be greater than zero")
        shape = self.copy(shape)
        try:
            if face_ids:
                faces = self._select_faces(shape, face_ids)
                result = bd.offset(shape, amount=-thickness, openings=faces)
            else:
                inner = bd.offset(shape, amount=-thickness)
                result = shape - inner
        except Exception as exc:
            raise InvalidGeometry(str(exc) or "shell failed") from exc
        return self._require_solid(result)

    def hole(self, shape, position, direction, diameter, depth, through) -> object:
        if diameter <= 0:
            raise InvalidGeometry("hole diameter must be greater than zero")
        direction = _unit(tuple(direction), "hole direction")
        if through:
            bounds = self.bounds(shape)
            span = math.dist(bounds[0], bounds[1]) + diameter
            start = [position[index] - direction[index] * span for index in range(3)]
            height = span * 2
        else:
            if depth <= 0:
                raise InvalidGeometry("hole depth must be greater than zero")
            start = list(position)
            height = depth
        cutter = bd.Plane(origin=tuple(start), z_dir=direction) * bd.Cylinder(
            diameter / 2.0, height,
            align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
        )
        return self.boolean("subtract", shape, cutter)

    def mirror(self, shape, plane, origin=None, normal=None, keep_original=False) -> object:
        about = self._plane(plane, origin, normal)
        try:
            mirrored = bd.mirror(self.copy(shape), about=about)
        except Exception as exc:
            raise InvalidGeometry(str(exc) or "mirror failed") from exc
        if keep_original:
            mirrored = self.boolean("union", shape, mirrored)
        return self._require_solid(mirrored)

    def linear_pattern(self, shape, direction, spacing, count) -> object:
        if count < 2:
            raise InvalidGeometry("linear pattern count must be at least 2")
        if spacing <= 0:
            raise InvalidGeometry("linear pattern spacing must be greater than zero")
        direction = _unit(tuple(direction), "pattern direction")
        pieces = []
        for index in range(count):
            offset = tuple(direction[axis] * spacing * index for axis in range(3))
            pieces.append(self.translate(shape, offset))
        return self._fuse(pieces)

    def circular_pattern(self, shape, origin, direction, count) -> object:
        if count < 2:
            raise InvalidGeometry("circular pattern count must be at least 2")
        direction = _unit(tuple(direction), "pattern axis")
        pieces = []
        axis = gp_Ax1(gp_Pnt(*origin), gp_Dir(*direction))
        source = self.copy(shape)
        for index in range(count):
            trsf = gp_Trsf()
            trsf.SetRotation(axis, index * 2.0 * math.pi / count)
            moved = BRepBuilderAPI_Transform(source.wrapped, trsf, True).Shape()
            pieces.append(self._require_solid(bd.Shape.cast(moved)))
        return self._fuse(pieces)

    def query(self, shape, point=None) -> dict:
        face_list = list(shape.faces())
        edge_list = list(shape.edges())
        adjacency = self._edge_face_indices(shape, face_list, edge_list)
        faces = [self._face_record(face, index, point) for index, face in enumerate(face_list)]
        edges = []
        for index, edge in enumerate(edge_list):
            record = self._edge_record(edge, index, point)
            record["face_indices"] = adjacency.get(index, [])
            edges.append(record)
        return {"faces": faces, "edges": edges}

    def section(self, shape, origin, normal) -> dict:
        plane = bd.Plane(origin=tuple(origin), z_dir=_unit(tuple(normal), "section normal"))
        try:
            sketch = bd.section(shape, plane)
        except Exception as exc:
            raise InvalidGeometry(str(exc) or "section failed") from exc
        loops = []
        wires = list(sketch.wires()) if hasattr(sketch, "wires") else []
        for wire in wires:
            loop = []
            for edge in wire.edges():
                for parameter in (0.0, 0.25, 0.5, 0.75):
                    point = edge @ parameter
                    loop.append(_xyz(point))
            if loop:
                loops.append(loop)
        return {"area": float(sketch.area), "loops": loops, "units": "mm"}

    def measure(self, shape) -> dict:
        center = shape.center()
        return {
            "volume": float(shape.volume),
            "area": float(shape.area),
            "bounds": self.bounds(shape),
            "center": _xyz(center),
            "topology": self.topology(shape),
            "units": "mm",
        }

    def contains(self, shape, point) -> bool:
        classifier = BRepClass3d_SolidClassifier(
            shape.wrapped, gp_Pnt(point[0], point[1], point[2]), 1e-7
        )
        return classifier.State() == TopAbs_IN

    def bounds(self, shape) -> list[list[float]]:
        box = shape.bounding_box()
        return [_xyz(box.min), _xyz(box.max)]

    def topology(self, shape) -> dict:
        solids = list(shape.solids()) if hasattr(shape, "solids") else []
        volume = float(shape.volume or 0.0)
        components = len(solids)
        valid = bool(shape.is_valid)
        return {
            "closed": bool(valid and volume > 1e-9 and components >= 1),
            "manifold": bool(shape.is_manifold),
            "components": components,
            "valid": valid,
        }

    def tessellate(self, shape, chord) -> dict:
        if chord <= 0:
            raise InvalidArgument("chord tolerance must be greater than zero")
        vertices, triangles = shape.tessellate(float(chord))
        return {
            "vertices": [_xyz(vertex) for vertex in vertices],
            "triangles": [list(triangle) for triangle in triangles],
            "units": "mm",
        }

    def tessellate_faces(self, shape, face_ids, chord) -> dict:
        if chord <= 0:
            raise InvalidArgument("chord tolerance must be greater than zero")
        selected = self._select_faces(shape, face_ids)
        vertices = []
        triangles = []
        for face in selected:
            face_vertices, face_triangles = face.tessellate(float(chord))
            base = len(vertices)
            vertices.extend(_xyz(vertex) for vertex in face_vertices)
            triangles.extend([index + base for index in triangle] for triangle in face_triangles)
        if not triangles:
            raise TopologyNotFound("selected faces produced no triangles")
        return {"vertices": vertices, "triangles": triangles, "units": "mm"}

    def copy(self, shape):
        # build123d implements __deepcopy__ with BRepBuilderAPI_Copy. Retain an
        # independent kernel shape for history and operations that may mutate
        # their inputs. Sharing immutable shapes would require a stronger contract.
        return copy.deepcopy(shape)

    def export_step(self, shape, path: str) -> None:
        ok = bd.export_step(shape, path, unit=bd.Unit.MM)
        if ok is False:
            raise InvalidGeometry("STEP export was rejected by the kernel")

    def export_gltf(self, shape, path: str, chord: float) -> None:
        # build123d converts the declared millimetre model into glTF metres.
        ok = bd.export_gltf(
            shape, path, unit=bd.Unit.MM, binary=str(path).lower().endswith(".glb"),
            linear_deflection=float(chord),
        )
        if ok is False:
            raise InvalidGeometry("glTF export was rejected by the kernel")

    def export_brep_bytes(self, shape) -> bytes:
        fd, path = tempfile.mkstemp(prefix=".cad-", suffix=".brep")
        os.close(fd)
        try:
            bd.export_brep(shape, path)
            return Path(path).read_bytes()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def import_brep_bytes(self, payload: bytes):
        fd, path = tempfile.mkstemp(prefix=".cad-", suffix=".brep")
        os.close(fd)
        try:
            Path(path).write_bytes(payload)
            shape = bd.import_brep(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        return self._require_solid(shape)

    def import_step(self, path: str):
        return bd.import_step(path)

    def _fuse(self, pieces: list) -> object:
        fused = pieces[0]
        for piece in pieces[1:]:
            fused = self.boolean("union", fused, piece)
        return fused

    def _require_solid(self, shape):
        solids = list(shape.solids()) if hasattr(shape, "solids") else []
        volume = float(getattr(shape, "volume", 0.0) or 0.0)
        if volume <= 1e-9 or not solids:
            raise EmptyResult()
        if not shape.is_valid:
            raise InvalidGeometry("kernel returned an invalid shape")
        return shape

    def _plane(self, plane, origin, normal):
        if plane == "xy":
            return bd.Plane.XY
        if plane == "yz":
            return bd.Plane.YZ
        if plane == "xz":
            return bd.Plane.XZ
        if plane == "custom":
            return bd.Plane(origin=tuple(origin), z_dir=_unit(tuple(normal), "mirror normal"))
        raise InvalidArgument("mirror plane must be xy, yz, xz, or custom")

    def _face_record(self, face, index: int, point) -> dict:
        geom = face.geom_type.name.lower()
        center = _xyz(face.center())
        normal = None
        radius = None
        axis = None
        try:
            normal = _xyz(face.normal_at())
        except Exception:
            normal = None
        if geom in {"cylinder", "sphere", "torus", "cone"}:
            adaptor = BRepAdaptor_Surface(face.wrapped)
            surface = adaptor.Cylinder() if geom == "cylinder" else None
            if geom == "cylinder":
                radius = float(surface.Radius())
                direction = surface.Axis().Direction()
                location = surface.Axis().Location()
                axis = {
                    "origin": [location.X(), location.Y(), location.Z()],
                    "direction": _canonical([direction.X(), direction.Y(), direction.Z()]),
                }
            elif geom == "sphere":
                radius = float(adaptor.Sphere().Radius())
            elif geom == "torus":
                radius = float(adaptor.Torus().MinorRadius())
        record = {
            "index": index,
            "geom": geom,
            "area": float(face.area),
            "center": center,
            "normal": normal,
            "radius": radius,
            "axis": axis,
        }
        if point is not None:
            record["distance"] = float(face.distance_to(tuple(point)))
        return record

    def _edge_record(self, edge, index: int, point) -> dict:
        geom = edge.geom_type.name.lower()
        tangent = _xyz(edge.tangent_at(0.5))
        radius = None
        if geom == "circle":
            try:
                radius = float(edge.radius)
            except Exception:
                radius = None
        record = {
            "index": index,
            "geom": geom,
            "length": float(edge.length),
            "center": _xyz(edge.center()),
            "direction": _canonical(tangent) if geom == "line" else tangent,
            "radius": radius,
        }
        if point is not None:
            record["distance"] = float(edge.distance_to(tuple(point)))
        return record

    def _edge_face_indices(self, shape, face_list, edge_list) -> dict[int, list[int]]:
        shape_map = IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher()
        TopExp.MapShapesAndAncestors_s(shape.wrapped, TopAbs_EDGE, TopAbs_FACE, shape_map)
        mapping = {}
        for edge_index in range(1, shape_map.Extent() + 1):
            topo_edge = TopoDS.Edge(shape_map.FindKey(edge_index))
            matched = None
            for index, edge in enumerate(edge_list):
                if edge.wrapped.IsSame(topo_edge):
                    matched = index
                    break
            if matched is None:
                continue
            faces = []
            for topo_face in shape_map.FindFromIndex(edge_index):
                topo_face = TopoDS.Face(topo_face)
                for index, face in enumerate(face_list):
                    if face.wrapped.IsSame(topo_face):
                        faces.append(index)
                        break
            mapping[matched] = faces
        return mapping

    def _annotated_edges(self, shape) -> list[dict]:
        raw = self.query(shape)["edges"]
        return assign_ids("edge", raw)

    def _annotated_faces(self, shape) -> list[dict]:
        raw = self.query(shape)["faces"]
        return assign_ids("face", raw)

    def _select_edges(self, shape, edge_ids, selector, min_length: float) -> list:
        records = self._annotated_edges(shape)
        by_index = {record["index"]: record for record in records}
        chosen = []
        if selector:
            kind = selector if isinstance(selector, str) else selector.get("kind")
            count = None if isinstance(selector, str) else selector.get("count")
            pool = []
            for record in records:
                vertical = (
                    record["geom"] == "line"
                    and abs(abs(record["direction"][2]) - 1.0) < 1e-3
                    and record["length"] + 1e-9 >= min_length
                )
                if kind == "vertical" and vertical:
                    pool.append(record)
                elif kind == "longest_vertical" and vertical:
                    pool.append(record)
                elif kind == "longest":
                    pool.append(record)
            if kind in {"longest_vertical", "longest"}:
                pool.sort(key=lambda record: record["length"], reverse=True)
                if count:
                    pool = pool[: int(count)]
            chosen = pool
        if edge_ids:
            wanted = set(edge_ids)
            matched = [record for record in records if record["id"] in wanted]
            missing = wanted.difference(record["id"] for record in matched)
            if missing:
                raise TopologyNotFound("edge selection does not match the current solid")
            chosen = matched if not chosen else [record for record in matched if record in chosen]
        if not chosen:
            raise TopologyNotFound("no edges matched the selection")
        edge_list = list(shape.edges())
        return [edge_list[record["index"]] for record in chosen]

    def _select_faces(self, shape, face_ids) -> list:
        records = self._annotated_faces(shape)
        wanted = set(face_ids)
        matched = [record for record in records if record["id"] in wanted]
        if len(matched) != len(wanted):
            raise TopologyNotFound("face selection does not match the current solid")
        face_list = list(shape.faces())
        return [face_list[record["index"]] for record in matched]

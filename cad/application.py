"""Authoritative CAD application. Agents call this; they do not own the model."""

from __future__ import annotations

import copy
import shutil
import threading
from contextlib import contextmanager

from cad import exporting, project, validation
from cad.agent import RefinementLoop
from cad.planners import DeterministicPlanner
from cad.planning import Planner
from cad.assets import ReferenceImage, calibrate, checksum, load_image
from cad.document import Document
from cad.content import reference_resource
from cad.errors import (
    ContractError,
    DependencyError,
    ExportError,
    GeometryInvalid,
    InvalidArgument,
    InvalidGeometry,
    InvalidMesh,
    MissingCapability,
    NotManufacturingReady,
    StaleValidation,
    UnknownReference,
)
from cad.features import Feature, dependency_graph
from cad.operations import EDITABLE
from cad.geometry.protocol import GeometryBackend
from cad.inspection import InspectionService, require_current_selection
from cad.geometry.occ import OccBackend
from cad.numbers import (
    finite_number,
    finite_tree,
    optional_name,
    polygon,
    polyline3,
    positive_int,
    positive_number,
    vec2,
    vec3,
)
from cad.replay import replay


def _success(value: object) -> dict:
    return {"ok": True, "value": value}


def _failure(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


class _Fault:
    def __init__(self) -> None:
        self.triggered = False


class Application:
    def __init__(self, backend: GeometryBackend | None = None, *, blender_runner=None, planner: Planner | None = None) -> None:
        self.backend = backend if backend is not None else OccBackend()
        self.document = Document(copy_shape=self.backend.copy)
        self.inspection = InspectionService(self.document, self.backend)
        self.planner = planner if planner is not None else DeterministicPlanner()
        self._blender_runner = blender_runner
        self._closed = False
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._armed: tuple[str, str, _Fault] | None = None
        self._endpoint = None
        self._operations = {name: getattr(self, f"_op_{name}") for name in (
            "snapshot", "inspect", "rename", "duplicate", "delete", "undo", "redo",
            "edit_feature", "create_primitive", "create_sketch", "extrude", "revolve",
            "sweep", "loft", "boolean", "transform", "fillet", "chamfer", "shell",
            "hole", "mirror", "linear_pattern", "circular_pattern", "measure",
            "query_faces", "query_edges", "section", "render_views", "render_selection",
            "add_reference", "list_references", "inspect_reference", "set_calibration",
            "estimate_length", "validate", "list_export_formats", "export", "tessellate",
            "save_project", "open_project", "refine", "cancel_refine",
        )}

    def reference_resources(self) -> tuple:
        """Read immutable image bytes with detached metadata under the command lock."""
        with self._lock:
            return tuple(reference_resource(asset) for asset in self.document.assets)

    def operation_names(self) -> tuple[str, ...]:
        return tuple(self._operations)

    def has_operation(self, name: object) -> bool:
        return isinstance(name, str) and name in self._operations

    def execute(self, operation: str, arguments: dict | None = None) -> dict:
        # Refinement holds the document lock. Cancellation only sets a thread-safe
        # event, so another MCP session must be able to request it during the run.
        if operation == "cancel_refine":
            return self._execute(operation, arguments)
        with self._lock:
            return self._execute(operation, arguments)

    def cancel(self) -> None:
        self._cancel.set()

    def _execute(self, operation: str, arguments: dict | None) -> dict:
        if self._closed:
            return _failure("APPLICATION_CLOSED", "application is closed")
        if not isinstance(operation, str) or not operation.strip():
            return _failure("INVALID_ARGUMENT", "operation must be a nonempty string")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _failure("INVALID_ARGUMENT", "arguments must be an object")
        handler = self._operations.get(operation)
        if handler is None:
            return _failure("MISSING_CAPABILITY", f"operation {operation!r} is not implemented")
        try:
            finite_tree(arguments)
            # Callers cannot retain aliases into committed metadata or parameters.
            return _success(copy.deepcopy(handler(copy.deepcopy(arguments))))
        except ContractError as exc:
            return _failure(exc.code, exc.message)
        except (ArithmeticError, OverflowError) as exc:
            return _failure("INVALID_ARGUMENT", str(exc) or "numeric error during operation")
        except Exception as exc:
            # Kernel failures must stay inside the transaction: handlers commit
            # only after geometry succeeds, so this does not leave a partial edit.
            return _failure("INVALID_GEOMETRY", f"{type(exc).__name__}: {exc}".strip(": "))

    def endpoint(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("application is closed")
            if self._endpoint is None:
                from cad.mcp_server import McpEndpoint
                self._endpoint = McpEndpoint(self)
                self._endpoint.start()
            return self._endpoint

    def open_mcp(self):
        return self.endpoint().open_client()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            endpoint = self._endpoint
            self._endpoint = None
            self.document.clear()
        if endpoint is not None:
            endpoint.close()

    @contextmanager
    def fail_at(self, operation: str, stage: str):
        fault = _Fault()
        previous = self._armed
        self._armed = (operation, stage, fault)
        try:
            yield fault
        finally:
            self._armed = previous

    def _fail_if_armed(self, operation: str, stage: str) -> None:
        armed = self._armed
        if armed is None:
            return
        name, expected, fault = armed
        if name == operation and expected == stage:
            fault.triggered = True
            raise ContractError("INJECTED_FAILURE", f"failure injected at {operation}/{stage}")

    def _op_snapshot(self, _arguments: dict) -> dict:
        bodies = []
        for ref in self.document.references():
            bodies.append(self._describe(ref))
        return {
            "units": "mm",
            "axes": "right-handed-z-up",
            "revision": self.document.revision,
            "references": list(self.document.references()),
            "names": dict(self.document.names),
            "features": [feature.to_public() for feature in self.document.features],
            "dependencies": {key: list(value) for key, value in dependency_graph(self.document.features).items()},
            "sketches": [
                {"id": feature_id, "profile": profile}
                for feature_id, profile in self.document.sketches.items()
            ],
            "bodies": bodies,
            "assets": [asset.public() for asset in self.document.assets],
            "settings": dict(self.document.settings),
            "undo": self.document.history_public(self.document._undo),
            "redo": self.document.history_public(self.document._redo),
            "backend": self.backend.name,
        }

    def _op_inspect(self, arguments: dict) -> dict:
        return self._describe(self._ref(arguments))

    def _op_measure(self, arguments: dict) -> dict:
        if arguments.get("a") is not None or arguments.get("b") is not None:
            start = vec3(arguments.get("a"), "a")
            end = vec3(arguments.get("b"), "b")
            distance = float(sum((start[i] - end[i]) ** 2 for i in range(3)) ** 0.5)
            return {"kind": "geometric", "distance": distance, "units": "mm"}
        ref = self._ref(arguments)
        shape = self.document.resolve(ref)
        measured = self.backend.measure(shape)
        measured["ref"] = ref
        measured["revision"] = self.document.revision
        if "point" in arguments and arguments["point"] is not None:
            measured["contains"] = bool(self.backend.contains(shape, vec3(arguments["point"], "point")))
        return measured

    def _op_rename(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        name = optional_name(arguments.get("name"))
        if not name:
            raise InvalidArgument("rename requires a name")
        feature_id = self.document.peek("feature")
        features = [*self.document.features, Feature(feature_id, "rename", {"ref": ref, "name": name}, None, name)]
        names = dict(self.document.names)
        names[ref] = name
        self._fail_if_armed("rename", "after_geometry")
        self.document.commit(features=features, solids=dict(self.document.solids), names=names, consume={"feature": 1})
        return {"ref": ref, "name": name, "revision": self.document.revision}

    def _op_duplicate(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        translation = list(vec3(arguments.get("translation", [0, 0, 0]), "translation"))
        shape = self.backend.copy(self.document.resolve(ref))
        if any(translation):
            shape = self.backend.translate(shape, translation)
        payload = self.backend.export_brep_bytes(shape)
        return self._insert("duplicate", {"brep": payload, "source": ref, "translation": translation}, shape, optional_name(arguments.get("name")))

    def _op_delete(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        for feature in self.document.features:
            if feature.output_ref == ref:
                continue
            if ref in feature.input_refs:
                raise DependencyError(f"{feature.id} still depends on {ref}")
        feature_id = self.document.peek("feature")
        removed_ids = {feature.id for feature in self.document.features if feature.output_ref == ref}
        features = [feature for feature in self.document.features if feature.output_ref != ref
                    and not (feature.op == "rename" and feature.params.get("ref") == ref)]
        names = {key: value for key, value in self.document.names.items() if key not in removed_ids | {ref}}
        features.append(Feature(feature_id, "delete", {"ref": ref}))
        solids = {key: value for key, value in self.document.solids.items() if key != ref}
        self._fail_if_armed("delete", "after_geometry")
        self.document.commit(features=features, solids=solids, names=names, consume={"feature": 1})
        return {"ref": ref, "revision": self.document.revision}

    def _op_undo(self, _arguments: dict) -> dict:
        self._fail_if_armed("undo", "after_geometry")
        self.document.undo()
        return {"revision": self.document.revision}

    def _op_redo(self, _arguments: dict) -> dict:
        self._fail_if_armed("redo", "after_geometry")
        self.document.redo()
        return {"revision": self.document.revision}

    def _op_edit_feature(self, arguments: dict) -> dict:
        feature_id = arguments.get("feature_id")
        if not isinstance(feature_id, str):
            raise InvalidArgument("feature_id must be a string")
        feature = self.document.feature(feature_id)
        updates = arguments.get("parameters")
        if not isinstance(updates, dict) or not updates:
            raise InvalidArgument("parameters must be a nonempty object")
        allowed = EDITABLE.get(feature.op)
        if not allowed:
            raise InvalidArgument(f"{feature.op} features cannot be edited parametrically")
        unknown = set(updates).difference(allowed)
        if unknown:
            raise InvalidArgument(f"unknown parameters for {feature.op}: {sorted(unknown)}")
        features = [
            item.clone(params=updates) if item.id == feature_id else item.clone()
            for item in self.document.features
        ]
        solids, sketches = replay(features, self.backend)
        self._fail_if_armed("edit_feature", "after_geometry")
        self.document.commit(features=features, solids=solids, sketches=sketches)
        return {
            "feature_id": feature_id,
            "ref": feature.output_ref,
            "revision": self.document.revision,
        }

    def _op_create_primitive(self, arguments: dict) -> dict:
        kind = arguments.get("kind")
        name = optional_name(arguments.get("name"))
        if kind == "box":
            size = [positive_number(value, "size") for value in vec3(arguments.get("size"), "size")]
            origin = list(vec3(arguments.get("origin", [0, 0, 0]), "origin"))
            shape = self.backend.box(size, origin)
            return self._insert("box", {"size": size, "origin": origin}, shape, name, "create_primitive")
        if kind == "cylinder":
            radius = positive_number(arguments.get("radius"), "radius")
            height = positive_number(arguments.get("height"), "height")
            origin = list(vec3(arguments.get("origin", [0, 0, 0]), "origin"))
            shape = self.backend.cylinder(radius, height, origin)
            return self._insert("cylinder", {"radius": radius, "height": height, "origin": origin}, shape, name, "create_primitive")
        if kind == "sphere":
            radius = positive_number(arguments.get("radius"), "radius")
            center = list(vec3(arguments.get("center", [0, 0, 0]), "center"))
            shape = self.backend.sphere(radius, center)
            return self._insert("sphere", {"radius": radius, "center": center}, shape, name, "create_primitive")
        raise InvalidArgument("kind must be box, cylinder, or sphere")

    def _op_create_sketch(self, arguments: dict) -> dict:
        profile = polygon(arguments.get("profile"), "profile")
        name = optional_name(arguments.get("name"))
        feature_id = self.document.peek("feature")
        feature = Feature(feature_id, "sketch", {"profile": profile}, None, name)
        features = [*self.document.features, feature]
        sketches = dict(self.document.sketches)
        sketches[feature_id] = profile
        names = dict(self.document.names)
        if name:
            names[feature_id] = name
        self._fail_if_armed("create_sketch", "after_geometry")
        self.document.commit(
            features=features, solids=dict(self.document.solids), sketches=sketches,
            names=names, consume={"feature": 1},
        )
        return {"feature_id": feature_id, "revision": self.document.revision}

    def _op_extrude(self, arguments: dict) -> dict:
        height = positive_number(arguments.get("height"), "height")
        profile, sketch_id = self._profile(arguments)
        shape = self.backend.extrude(profile, height)
        params = {"height": height, "profile": profile}
        if sketch_id:
            params["sketch_id"] = sketch_id
        return self._insert("extrude", params, shape, optional_name(arguments.get("name")), "extrude")

    def _op_revolve(self, arguments: dict) -> dict:
        angle = positive_number(arguments.get("angle_degrees", 360), "angle_degrees")
        profile, sketch_id = self._profile(arguments)
        shape = self.backend.revolve(profile, angle)
        params = {"angle_degrees": angle, "profile": profile}
        if sketch_id:
            params["sketch_id"] = sketch_id
        return self._insert("revolve", params, shape, optional_name(arguments.get("name")), "revolve")

    def _op_sweep(self, arguments: dict) -> dict:
        profile = polygon(arguments.get("profile"), "profile")
        path = polyline3(arguments.get("path"), "path")
        shape = self.backend.sweep(profile, path)
        return self._insert("sweep", {"profile": profile, "path": path}, shape, optional_name(arguments.get("name")), "sweep")

    def _op_loft(self, arguments: dict) -> dict:
        profiles = arguments.get("profiles")
        stations = arguments.get("stations")
        if not isinstance(profiles, list) or not isinstance(stations, list):
            raise InvalidArgument("loft requires profiles and stations")
        parsed = [polygon(profile, "profile") for profile in profiles]
        heights = [finite_number(value, "stations") for value in stations]
        shape = self.backend.loft(parsed, heights)
        return self._insert("loft", {"profiles": parsed, "stations": heights}, shape, optional_name(arguments.get("name")), "loft")

    def _op_boolean(self, arguments: dict) -> dict:
        kind = arguments.get("kind")
        if kind not in {"union", "subtract", "intersection"}:
            raise InvalidArgument("kind must be union, subtract, or intersection")
        left = self._ref(arguments, "left")
        right = self._ref(arguments, "right")
        shape = self.backend.boolean(kind, self.document.resolve(left), self.document.resolve(right))
        return self._insert("boolean", {"kind": kind, "left": left, "right": right}, shape, optional_name(arguments.get("name")), "boolean")

    def _op_transform(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        matrix = _matrix(arguments.get("matrix"))
        shape = self.backend.transform(self.document.resolve(ref), matrix)
        return self._replace("transform", {"target": ref, "matrix": matrix}, shape, ref, "transform")

    def _op_fillet(self, arguments: dict) -> dict:
        return self._edge_modifier("fillet", arguments, "radius")

    def _op_chamfer(self, arguments: dict) -> dict:
        return self._edge_modifier("chamfer", arguments, "distance")

    def _op_shell(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        thickness = positive_number(arguments.get("thickness"), "thickness")
        face_ids = arguments.get("face_ids")
        self._require_current_selection(arguments, face_ids)
        shape = self.backend.shell(self.document.resolve(ref), thickness, face_ids)
        return self._replace("shell", {"target": ref, "thickness": thickness, "face_ids": face_ids}, shape, ref, "shell")

    def _op_hole(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        position = list(vec3(arguments.get("position"), "position"))
        direction = list(vec3(arguments.get("direction", [0, 0, -1]), "direction"))
        diameter = positive_number(arguments.get("diameter"), "diameter")
        through = bool(arguments.get("through", True))
        depth = None if through else positive_number(arguments.get("depth"), "depth")
        shape = self.backend.hole(self.document.resolve(ref), position, direction, diameter, depth, through)
        params = {
            "target": ref, "position": position, "direction": direction,
            "diameter": diameter, "depth": depth, "through": through,
        }
        return self._replace("hole", params, shape, ref, "hole")

    def _op_mirror(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        plane = arguments.get("plane", "yz")
        origin = list(vec3(arguments.get("origin", [0, 0, 0]), "origin")) if plane == "custom" or "origin" in arguments else None
        normal = list(vec3(arguments["normal"], "normal")) if "normal" in arguments else None
        keep = bool(arguments.get("keep_original", False))
        shape = self.backend.mirror(self.document.resolve(ref), plane, origin, normal, keep)
        params = {"target": ref, "plane": plane, "origin": origin, "normal": normal, "keep_original": keep}
        return self._replace("mirror", params, shape, ref, "mirror")

    def _op_linear_pattern(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        direction = list(vec3(arguments.get("direction"), "direction"))
        spacing = positive_number(arguments.get("spacing"), "spacing")
        count = positive_int(arguments.get("count"), "count")
        shape = self.backend.linear_pattern(self.document.resolve(ref), direction, spacing, count)
        params = {"target": ref, "direction": direction, "spacing": spacing, "count": count}
        return self._insert("linear_pattern", params, shape, optional_name(arguments.get("name")), "linear_pattern")

    def _op_circular_pattern(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        origin = list(vec3(arguments.get("origin", [0, 0, 0]), "origin"))
        direction = list(vec3(arguments.get("direction", [0, 0, 1]), "direction"))
        count = positive_int(arguments.get("count"), "count")
        shape = self.backend.circular_pattern(self.document.resolve(ref), origin, direction, count)
        params = {"target": ref, "origin": origin, "direction": direction, "count": count}
        return self._insert("circular_pattern", params, shape, optional_name(arguments.get("name")), "circular_pattern")

    def _op_query_faces(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        return self._query(ref, "faces", arguments)

    def _op_query_edges(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        return self._query(ref, "edges", arguments)

    def _op_section(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        origin = vec3(arguments.get("origin"), "origin")
        normal = vec3(arguments.get("normal"), "normal")
        section = self.backend.section(self.document.resolve(ref), origin, normal)
        section["ref"] = ref
        section["revision"] = self.document.revision
        return section

    def _op_render_views(self, arguments: dict) -> dict:
        return self._render(arguments, highlight=False)

    def _op_render_selection(self, arguments: dict) -> dict:
        return self._render(arguments, highlight=True)

    def _op_add_reference(self, arguments: dict) -> dict:
        role = arguments.get("role") or "other"
        loaded = load_image(
            arguments.get("path"), role=role, label=arguments.get("label"),
            notes=arguments.get("notes") or "", camera_hint=arguments.get("camera_hint"),
        )
        media_type, filename, width, height, data = loaded
        asset_id = self.document.peek("asset")
        label = optional_name(arguments.get("label")) or filename
        asset = ReferenceImage(
            id=asset_id, label=label, role=role, filename=filename, media_type=media_type,
            width=width, height=height, checksum=checksum(data), notes=arguments.get("notes") or "",
            camera_hint=arguments.get("camera_hint"), data=data,
        )
        assets = [*self.document.assets, asset]
        self._fail_if_armed("add_reference", "after_geometry")
        self.document.commit(
            features=list(self.document.features), solids=dict(self.document.solids),
            assets=assets, consume={"asset": 1},
        )
        return {"id": asset_id, "revision": self.document.revision, **asset.public()}

    def _op_list_references(self, _arguments: dict) -> dict:
        return {
            "revision": self.document.revision,
            "references": [asset.public() for asset in self.document.assets],
            "units": "mm",
        }

    def _op_inspect_reference(self, arguments: dict) -> dict:
        asset = self._asset(arguments.get("id"))
        public = asset.public()
        public["scale"] = "calibrated" if asset.calibration else "unknown"
        public["note"] = (
            "A calibrated image relates pixel distance to millimetres in the image plane. "
            "It does not determine depth or a unique absolute scale of the solid."
        )
        return public

    def _op_set_calibration(self, arguments: dict) -> dict:
        asset = self._asset(arguments.get("id"))
        calibration = calibrate(
            vec2(arguments.get("p1"), "p1"),
            vec2(arguments.get("p2"), "p2"),
            positive_number(arguments.get("distance_mm"), "distance_mm"),
        )
        updated = ReferenceImage(**{**asset.__dict__, "calibration": calibration})
        assets = [updated if item.id == asset.id else item for item in self.document.assets]
        self._fail_if_armed("set_calibration", "after_geometry")
        self.document.commit(
            features=list(self.document.features), solids=dict(self.document.solids), assets=assets,
        )
        return {"id": asset.id, "calibration": calibration, "revision": self.document.revision}

    def _op_estimate_length(self, arguments: dict) -> dict:
        asset = self._asset(arguments.get("id"))
        pixels = positive_number(arguments.get("pixel_length"), "pixel_length")
        if not asset.calibration:
            return {
                "kind": "uncalibrated",
                "millimeters": None,
                "geometric": False,
                "reason": "the image has no two-point calibration, so pixel length is not a millimetre length",
            }
        return {
            "kind": "calibrated_estimate",
            "millimeters": pixels * asset.calibration["mm_per_pixel"],
            "geometric": False,
            "mm_per_pixel": asset.calibration["mm_per_pixel"],
            "units": "mm",
        }

    def _op_validate(self, arguments: dict) -> dict:
        scope = arguments.get("scope", "all")
        if scope not in {"geometry", "manufacturing", "all"}:
            raise InvalidArgument("scope must be geometry, manufacturing, or all")
        profile_name = "geometry" if scope == "geometry" else arguments.get("profile", "fdm")
        rules = validation.resolve_profile(profile_name)
        if scope == "geometry":
            rules = validation.resolve_profile("geometry")
        findings = []
        refs = [arguments["ref"]] if arguments.get("ref") else list(self.document.references())
        if arguments.get("ref"):
            self.document.resolve(arguments["ref"])
        for ref in refs:
            label = self.document.names.get(ref) or ref
            use_rules = rules if scope != "geometry" else validation.resolve_profile("geometry")
            if scope == "geometry":
                use_rules = {key: value for key, value in use_rules.items() if key not in {"min_wall", "min_feature"}}
            findings.extend(validation.validate_shape(
                self.document.resolve(ref), self.backend, use_rules, label=label,
            ))
        return validation.report(self.document.revision, rules, findings, scope)

    def _op_list_export_formats(self, _arguments: dict) -> dict:
        return {"formats": exporting.list_formats(self._blender_available())}

    def _op_export(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        fmt = exporting.normalize_format(arguments.get("format"))
        path = arguments.get("path")
        if not isinstance(path, str) or not path:
            raise InvalidArgument("export path must be a nonempty string")
        mode = arguments.get("mode")
        if mode is None:
            mode = "manufacturing" if exporting.FORMATS[fmt]["manufacturing_default"] else "preview"
        if mode not in {"preview", "manufacturing"}:
            raise InvalidArgument("mode must be preview or manufacturing")
        before = self._op_snapshot({})
        shape = self.document.resolve(ref)
        self._authorize_export(ref, arguments.get("validation"), mode)
        chord = positive_number(arguments.get("chord_tolerance", 0.2), "chord_tolerance")
        try:
            payload, units = self._export_bytes(fmt, shape, chord)
            exporting.publish_bytes(path, payload)
        except (InvalidMesh, ExportError, MissingCapability, GeometryInvalid):
            if self._op_snapshot({}) != before:
                raise GeometryInvalid("export mutated the document")
            raise
        if self._op_snapshot({}) != before:
            raise GeometryInvalid("export mutated the document")
        return {
            "path": path,
            "format": fmt,
            "revision": self.document.revision,
            "mode": mode,
            "units": units,
            "source_units": "mm",
            "geometry": exporting.FORMATS[fmt]["geometry"],
        }

    def _op_tessellate(self, arguments: dict) -> dict:
        ref = self._ref(arguments)
        chord = positive_number(arguments.get("chord_tolerance", 0.2), "chord_tolerance")
        mesh = self.backend.tessellate(self.document.resolve(ref), chord)
        mesh["ref"] = ref
        mesh["revision"] = self.document.revision
        return mesh

    def _op_save_project(self, arguments: dict) -> dict:
        path = arguments.get("path")
        if not isinstance(path, str) or not path:
            raise InvalidArgument("path must be a nonempty string")
        before = self.document.revision
        saved = project.save_project(self.document, path)
        if self.document.revision != before:
            raise GeometryInvalid("save mutated the document")
        return saved

    def _op_open_project(self, arguments: dict) -> dict:
        path = arguments.get("path")
        if not isinstance(path, str) or not path:
            raise InvalidArgument("path must be a nonempty string")
        loaded = project.load_project(path, self.backend)
        self._fail_if_armed("open_project", "after_geometry")
        self.document.replace(
            features=loaded["features"], solids=loaded["solids"], sketches=loaded["sketches"],
            names=loaded["names"], assets=loaded["assets"], settings=loaded["settings"],
            serials=loaded["serials"],
        )
        return {
            "path": path,
            "format_version": loaded["format_version"],
            "revision": self.document.revision,
            "references": list(self.document.references()),
        }

    def _op_refine(self, arguments: dict) -> dict:
        request = arguments.get("request")
        if not isinstance(request, str):
            raise InvalidArgument("request must be a string")
        iterations = arguments.get("max_iterations", 12)
        self._cancel.clear()
        loop = RefinementLoop(self, self.planner, cancel_event=self._cancel)
        return loop.run(request, goals=arguments.get("goals"), max_iterations=iterations)

    def _op_cancel_refine(self, _arguments: dict) -> dict:
        self._cancel.set()
        return {"cancel_requested": True}

    def _insert(self, op: str, params: dict, shape, name: str, operation: str | None = None) -> dict:
        ref = self.document.peek("body")
        feature_id = self.document.peek("feature")
        feature = Feature(feature_id, op, params, ref, name)
        features = [*self.document.features, feature]
        solids = dict(self.document.solids)
        solids[ref] = shape
        names = dict(self.document.names)
        if name:
            names[ref] = name
            names[feature_id] = name
        self._fail_if_armed(operation or op, "after_geometry")
        self.document.commit(features=features, solids=solids, names=names, consume={"body": 1, "feature": 1})
        return {"ref": ref, "feature_id": feature_id, "revision": self.document.revision}

    def _replace(self, op: str, params: dict, shape, ref: str, operation: str) -> dict:
        feature_id = self.document.peek("feature")
        feature = Feature(feature_id, op, params, ref, self.document.names.get(ref, ""))
        features = [*self.document.features, feature]
        solids = dict(self.document.solids)
        solids[ref] = shape
        self._fail_if_armed(operation, "after_geometry")
        self.document.commit(features=features, solids=solids, consume={"feature": 1})
        return {"ref": ref, "feature_id": feature_id, "revision": self.document.revision}

    def _edge_modifier(self, op: str, arguments: dict, field: str) -> dict:
        ref = self._ref(arguments)
        amount = positive_number(arguments.get(field), field)
        edge_ids = arguments.get("edge_ids")
        selector = arguments.get("selector")
        if edge_ids is not None and not isinstance(edge_ids, list):
            raise InvalidArgument("edge_ids must be a list")
        if selector is not None and not isinstance(selector, (str, dict)):
            raise InvalidArgument("selector must be a string or object")
        if not edge_ids and not selector:
            raise InvalidArgument(f"{op} requires edge_ids or a selector")
        self._require_current_selection(arguments, edge_ids)
        method = getattr(self.backend, op)
        shape = method(self.document.resolve(ref), amount, edge_ids, selector)
        params = {"target": ref, field: amount, "edge_ids": edge_ids, "selector": selector}
        return self._replace(op, params, shape, ref, op)

    def _require_current_selection(self, arguments: dict, ids) -> None:
        require_current_selection(self.document.revision, arguments, ids)

    def _query(self, ref: str, kind: str, arguments: dict) -> dict:
        return self.inspection.query(ref, kind, arguments)

    def _render(self, arguments: dict, *, highlight: bool) -> dict:
        return self.inspection.render(arguments, highlight=highlight)

    def _authorize_export(self, ref: str, report: object, mode: str) -> None:
        rules = validation.resolve_profile("geometry")
        findings = validation.validate_shape(self.document.resolve(ref), self.backend, rules, label=ref)
        if any(item["severity"] == "error" for item in findings):
            raise GeometryInvalid(findings[0]["message"])
        if mode != "manufacturing":
            return
        if not isinstance(report, dict):
            raise InvalidArgument("manufacturing export requires the current validation report")
        if report.get("revision") != self.document.revision:
            raise StaleValidation()
        if not report.get("ready"):
            raise NotManufacturingReady()
        if report.get("scope") not in {"manufacturing", "all"}:
            raise InvalidArgument("manufacturing export requires manufacturing validation")
        rules = report.get("rules")
        if not isinstance(rules, dict):
            raise InvalidArgument("validation report has no rules")
        rules = validation.resolve_profile(rules)
        live = validation.validate_shape(self.document.resolve(ref), self.backend, rules, label=ref)
        if any(item["severity"] == "error" for item in live):
            raise NotManufacturingReady(live[0]["message"])

    def _export_bytes(self, fmt: str, shape, chord: float) -> tuple[bytes, str]:
        if fmt == "step":
            return exporting.step_bytes(self.backend, shape), "mm"
        if fmt == "glb":
            return exporting.glb_bytes(self.backend, shape, chord), "m"
        mesh = self.backend.tessellate(shape, chord)
        if fmt == "stl":
            return exporting.stl_bytes(mesh["vertices"], mesh["triangles"]), "mm"
        if fmt == "obj":
            return exporting.obj_bytes(mesh["vertices"], mesh["triangles"]), "mm"
        if fmt == "blend":
            return exporting.blend_bytes(self.backend, shape, chord, self._blender_runner), "m"
        raise InvalidArgument(f"unsupported format {fmt}")

    def _describe(self, ref: str) -> dict:
        shape = self.document.resolve(ref)
        feature_id = None
        for feature in self.document.features:
            if feature.output_ref == ref:
                feature_id = feature.id
        measured = self.backend.measure(shape)
        return {
            "ref": ref,
            "name": self.document.names.get(ref, ""),
            "feature_id": feature_id,
            "bounds": measured["bounds"],
            "volume": measured["volume"],
            "area": measured["area"],
            "center": measured["center"],
            "topology": measured["topology"],
            "backend": self.backend.name,
            "units": "mm",
        }

    def _profile(self, arguments: dict) -> tuple[list, str | None]:
        sketch_id = arguments.get("sketch_id")
        if sketch_id is not None:
            if not isinstance(sketch_id, str) or sketch_id not in self.document.sketches:
                raise UnknownReference("sketch does not exist")
            return self.document.sketches[sketch_id], sketch_id
        return polygon(arguments.get("profile"), "profile"), None

    def _ref(self, arguments: dict, key: str = "ref") -> str:
        ref = arguments.get(key)
        if not self.document.has_ref(ref):
            raise UnknownReference()
        return ref

    def _asset(self, asset_id: object) -> ReferenceImage:
        if not isinstance(asset_id, str):
            raise UnknownReference("reference image does not exist")
        for asset in self.document.assets:
            if asset.id == asset_id:
                return asset
        raise UnknownReference("reference image does not exist")

    def _blender_available(self) -> bool:
        return self._blender_runner is not None or shutil.which("blender") is not None


def _matrix(value: object) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 16:
        raise InvalidArgument("matrix must be 16 row-major numbers")
    numbers = [finite_number(item, "matrix") for item in value]
    expected = (0.0, 0.0, 0.0, 1.0)
    if any(abs(numbers[12 + index] - expected[index]) > 1e-9 for index in range(4)):
        raise InvalidArgument("matrix last row must be [0, 0, 0, 1]")
    det = (
        numbers[0] * (numbers[5] * numbers[10] - numbers[6] * numbers[9])
        - numbers[1] * (numbers[4] * numbers[10] - numbers[6] * numbers[8])
        + numbers[2] * (numbers[4] * numbers[9] - numbers[5] * numbers[8])
    )
    if abs(det) <= 1e-12:
        raise InvalidArgument("matrix is singular")
    return numbers

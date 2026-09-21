"""Document application exposing the execute/close adapter contract."""

from __future__ import annotations

import threading
from contextlib import contextmanager

from jewelry.document import Document
from jewelry.errors import ContractError, UnknownReference
from jewelry.export import export_body, export_mesh
from jewelry.kernel import GeometryKernel
from jewelry.kernel.numeric import as_vec3
from jewelry.mcp_server import McpEndpoint
from jewelry.tessellate import tessellate_body
from jewelry.validator import validate_document, validate_mesh


def _success(value: object) -> dict:
    return {"ok": True, "value": value}


def _failure(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


class _Fault:
    def __init__(self) -> None:
        self.triggered = False


class Application:
    def __init__(self, kernel: GeometryKernel | None = None) -> None:
        self._kernel = kernel if kernel is not None else GeometryKernel()
        self._document = Document()
        self._closed = False
        self._lock = threading.RLock()
        self._endpoint: McpEndpoint | None = None
        self._armed: tuple[str, str, _Fault] | None = None
        self._operations = {
            "create_box": self._create_box,
            "create_cylinder": self._create_cylinder,
            "create_sphere": self._create_sphere,
            "transform": self._transform,
            "extrude": self._extrude,
            "revolve": self._revolve,
            "boolean": self._boolean,
            "create_ring": self._create_ring,
            "modify_ring": self._modify_ring,
            "cut_through_hole": self._cut_through_hole,
            "cut_recess": self._cut_recess,
            "add_setting": self._add_setting,
            "repeat_prongs": self._repeat_prongs,
            "delete": self._delete,
            "undo": self._undo,
            "redo": self._redo,
            "inspect": self._inspect,
            "contains": self._contains,
            "snapshot": self._snapshot,
            "validate": self._validate,
            "validate_mesh": self._validate_mesh,
            "tessellate": self._tessellate,
            "export": self._export,
            "export_mesh": self._export_mesh,
        }

    def operation_names(self) -> tuple[str, ...]:
        return tuple(self._operations)

    def has_operation(self, name: object) -> bool:
        return isinstance(name, str) and name in self._operations

    def execute(self, operation: str, arguments: dict | None = None) -> dict:
        with self._lock:
            return self._execute(operation, arguments)

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
            return _failure(
                "MISSING_CAPABILITY",
                f"operation {operation!r} is not implemented",
            )
        try:
            return _success(handler(arguments))
        except ContractError as exc:
            return _failure(exc.code, exc.message)
        except (ArithmeticError, OverflowError) as exc:
            return _failure(
                "INVALID_ARGUMENT",
                str(exc) or "numeric error during operation",
            )

    def endpoint(self) -> McpEndpoint:
        with self._lock:
            if self._closed:
                raise RuntimeError("application is closed")
            if self._endpoint is None:
                self._endpoint = McpEndpoint(self)
                self._endpoint.start()
            return self._endpoint

    def open_mcp(self):
        return self.endpoint().open_client()

    def open_acp(self, agent: str, cwd: str, deterministic: bool = True):
        from jewelry.acp import open_acp

        return open_acp(self, agent, cwd=cwd, deterministic=deterministic)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            endpoint = self._endpoint
            self._endpoint = None
            self._document.clear()
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
        # A02: inject after the candidate exists and before commit.
        armed = self._armed
        if armed is None:
            return
        name, expected_stage, fault = armed
        if name == operation and expected_stage == stage:
            fault.triggered = True
            raise ContractError(
                "INJECTED_FAILURE",
                f"failure injected at {operation}/{stage}",
            )

    def _insert(self, operation: str, body) -> dict:
        ref = self._document.peek_ref()
        candidate = self._document.copy_state()
        candidate[ref] = body
        self._fail_if_armed(operation, "after_geometry")
        self._document.commit(candidate, consume_serial=True)
        return {"ref": ref}

    def _replace(self, operation: str, ref: object, body) -> dict:
        if not self._document.has_ref(ref):
            raise UnknownReference()
        candidate = self._document.copy_state()
        candidate[ref] = body
        self._fail_if_armed(operation, "after_geometry")
        self._document.commit(candidate, consume_serial=False)
        return {"ref": ref}

    def _create_box(self, arguments: dict) -> dict:
        body = self._kernel.create_box(arguments.get("size"), arguments.get("origin"))
        return self._insert("create_box", body)

    def _create_cylinder(self, arguments: dict) -> dict:
        body = self._kernel.create_cylinder(
            arguments.get("radius"),
            arguments.get("height"),
            arguments.get("origin"),
        )
        return self._insert("create_cylinder", body)

    def _create_sphere(self, arguments: dict) -> dict:
        body = self._kernel.create_sphere(
            arguments.get("radius"),
            arguments.get("center"),
        )
        return self._insert("create_sphere", body)

    def _transform(self, arguments: dict) -> dict:
        ref = arguments.get("ref")
        body = self._document.resolve(ref)
        candidate = self._kernel.transform(body, arguments.get("matrix"))
        return self._replace("transform", ref, candidate)

    def _extrude(self, arguments: dict) -> dict:
        body = self._kernel.extrude(arguments.get("profile"), arguments.get("height"))
        return self._insert("extrude", body)

    def _revolve(self, arguments: dict) -> dict:
        body = self._kernel.revolve(
            arguments.get("profile"),
            arguments.get("angle_degrees"),
        )
        return self._insert("revolve", body)

    def _boolean(self, arguments: dict) -> dict:
        left = self._document.resolve(arguments.get("left"))
        right = self._document.resolve(arguments.get("right"))
        body = self._kernel.boolean(arguments.get("kind"), left, right)
        return self._insert("boolean", body)

    def _create_ring(self, arguments: dict) -> dict:
        body = self._kernel.create_ring(
            arguments.get("inner_radius"),
            arguments.get("outer_radius"),
            arguments.get("width"),
        )
        return self._insert("create_ring", body)

    def _modify_ring(self, arguments: dict) -> dict:
        if "ref" not in arguments:
            raise UnknownReference("modify_ring requires a target reference")
        ref = arguments.get("ref")
        body = self._document.resolve(ref)
        candidate = self._kernel.modify_ring(body, arguments)
        return self._replace("modify_ring", ref, candidate)

    def _cut_through_hole(self, arguments: dict) -> dict:
        ref = arguments.get("ref")
        body = self._document.resolve(ref)
        candidate = self._kernel.cut_through_hole(
            body,
            arguments.get("center"),
            arguments.get("radius"),
        )
        return self._replace("cut_through_hole", ref, candidate)

    def _cut_recess(self, arguments: dict) -> dict:
        ref = arguments.get("ref")
        body = self._document.resolve(ref)
        candidate = self._kernel.cut_recess(
            body,
            arguments.get("center"),
            arguments.get("radius"),
            arguments.get("top_z"),
            arguments.get("depth"),
        )
        return self._replace("cut_recess", ref, candidate)

    def _add_setting(self, arguments: dict) -> dict:
        ref = arguments.get("ref")
        body = self._document.resolve(ref)
        candidate = self._kernel.add_setting(
            body,
            arguments.get("center"),
            arguments.get("radius"),
            arguments.get("base_z"),
            arguments.get("height"),
        )
        return self._replace("add_setting", ref, candidate)

    def _repeat_prongs(self, arguments: dict) -> dict:
        ref = arguments.get("ref")
        body = self._document.resolve(ref)
        candidate = self._kernel.repeat_prongs(
            body,
            arguments.get("center"),
            arguments.get("orbit_radius"),
            arguments.get("diameter"),
            arguments.get("base_z"),
            arguments.get("height"),
            arguments.get("count"),
            arguments.get("start_angle_degrees"),
        )
        return self._replace("repeat_prongs", ref, candidate)

    def _delete(self, arguments: dict) -> dict:
        ref = arguments.get("ref")
        self._document.resolve(ref)
        candidate = {
            key: body for key, body in self._document.body_items() if key != ref
        }
        self._fail_if_armed("delete", "after_geometry")
        self._document.commit(candidate, consume_serial=False)
        return {"ref": ref}

    def _undo(self, _arguments: dict) -> dict:
        self._document.undo()
        return {}

    def _redo(self, _arguments: dict) -> dict:
        self._document.redo()
        return {}

    def _inspect(self, arguments: dict) -> dict:
        body = self._document.resolve(arguments.get("ref"))
        return {
            "bounds": body.bounds(),
            "volume": float(body.volume()),
            "topology": body.topology(),
        }

    def _contains(self, arguments: dict) -> bool:
        point = as_vec3(arguments.get("point"), "point")
        body = self._document.resolve(arguments.get("ref"))
        return bool(body.contains(point))

    def _snapshot(self, _arguments: dict) -> dict:
        return self._document.snapshot()

    def _validate(self, arguments: dict) -> dict:
        return validate_document(self._document, arguments.get("profile"))

    def _validate_mesh(self, arguments: dict) -> dict:
        return validate_mesh(
            arguments.get("vertices"),
            arguments.get("triangles"),
            arguments.get("profile"),
            revision=self._document.revision,
        )

    def _tessellate(self, arguments: dict) -> dict:
        body = self._document.resolve(arguments.get("ref"))
        return tessellate_body(
            body,
            arguments.get("chord_tolerance"),
            arguments.get("max_triangles"),
        )

    def _export(self, arguments: dict) -> dict:
        body = self._document.resolve(arguments.get("ref"))
        return export_body(
            body,
            path=arguments.get("path"),
            format=arguments.get("format", "stl"),
            validation=arguments.get("validation"),
            chord_tolerance=arguments.get("chord_tolerance"),
            document=self._document,
        )

    def _export_mesh(self, arguments: dict) -> dict:
        return export_mesh(
            arguments.get("vertices"),
            arguments.get("triangles"),
            path=arguments.get("path"),
            format=arguments.get("format", "stl"),
        )

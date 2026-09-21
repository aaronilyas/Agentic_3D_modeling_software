"""Document application exposing the execute/close adapter contract."""

from __future__ import annotations

from jewelry.document import Document
from jewelry.errors import ContractError
from jewelry.kernel import GeometryKernel
from jewelry.kernel.numeric import as_vec3


def _success(value: object) -> dict:
    return {"ok": True, "value": value}


def _failure(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


class Application:
    def __init__(self, kernel: GeometryKernel | None = None) -> None:
        self._kernel = kernel if kernel is not None else GeometryKernel()
        self._document = Document()
        self._closed = False
        self._operations = {
            "create_box": self._create_box,
            "create_cylinder": self._create_cylinder,
            "create_sphere": self._create_sphere,
            "inspect": self._inspect,
            "contains": self._contains,
            "snapshot": self._snapshot,
        }

    def execute(self, operation: str, arguments: dict | None = None) -> dict:
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

    def close(self) -> None:
        self._closed = True
        self._document.clear()

    def _create_box(self, arguments: dict) -> dict:
        body = self._kernel.create_box(arguments.get("size"), arguments.get("origin"))
        return {"ref": self._document.insert(body)}

    def _create_cylinder(self, arguments: dict) -> dict:
        body = self._kernel.create_cylinder(
            arguments.get("radius"),
            arguments.get("height"),
            arguments.get("origin"),
        )
        return {"ref": self._document.insert(body)}

    def _create_sphere(self, arguments: dict) -> dict:
        body = self._kernel.create_sphere(
            arguments.get("radius"),
            arguments.get("center"),
        )
        return {"ref": self._document.insert(body)}

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

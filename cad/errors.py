"""Structured failures for the generic CAD application."""

from __future__ import annotations


class ContractError(Exception):
    """Domain failure with a stable code and a nonempty message."""

    def __init__(self, code: str, message: str):
        code = str(code).strip()
        message = str(message).strip()
        if not code:
            raise ValueError("error code must be nonempty")
        if not message:
            raise ValueError("error message must be nonempty")
        super().__init__(message)
        self.code = code
        self.message = message


class InvalidArgument(ContractError):
    def __init__(self, message: str = "invalid argument"):
        super().__init__("INVALID_ARGUMENT", message)


class InvalidGeometry(ContractError):
    def __init__(self, message: str = "geometry is invalid"):
        super().__init__("INVALID_GEOMETRY", message)


class UnknownReference(ContractError):
    def __init__(self, message: str = "reference does not exist"):
        super().__init__("UNKNOWN_REFERENCE", message)


class UnknownFeature(ContractError):
    def __init__(self, message: str = "feature does not exist"):
        super().__init__("UNKNOWN_FEATURE", message)


class EmptyResult(ContractError):
    def __init__(self, message: str = "operation produced empty geometry"):
        super().__init__("EMPTY_RESULT", message)


class EmptyHistory(ContractError):
    def __init__(self, message: str = "undo/redo history is empty"):
        super().__init__("EMPTY_HISTORY", message)


class StaleSelection(ContractError):
    def __init__(self, message: str = "topology selection is from another revision"):
        super().__init__("STALE_SELECTION", message)


class TopologyNotFound(ContractError):
    def __init__(self, message: str = "topology selection does not match current geometry"):
        super().__init__("TOPOLOGY_NOT_FOUND", message)


class GeometryInvalid(ContractError):
    def __init__(self, message: str = "geometry validation failed"):
        super().__init__("GEOMETRY_INVALID", message)


class StaleValidation(ContractError):
    def __init__(self, message: str = "validation report is not for the current revision"):
        super().__init__("STALE_VALIDATION", message)


class NotManufacturingReady(ContractError):
    def __init__(self, message: str = "current geometry is not manufacturing-ready"):
        super().__init__("NOT_MANUFACTURING_READY", message)


class InvalidProfile(ContractError):
    def __init__(self, message: str = "validation profile is invalid"):
        super().__init__("INVALID_PROFILE", message)


class DependencyError(ContractError):
    def __init__(self, message: str = "other features still depend on this object"):
        super().__init__("DEPENDENCY", message)


class ExportError(ContractError):
    def __init__(self, message: str = "export failed"):
        super().__init__("EXPORT_IO_ERROR", message)


class InvalidMesh(ContractError):
    def __init__(self, message: str = "mesh is not valid for export"):
        super().__init__("INVALID_MESH", message)


class MissingCapability(ContractError):
    def __init__(self, message: str = "capability is not available"):
        super().__init__("MISSING_CAPABILITY", message)


class Cancelled(ContractError):
    def __init__(self, message: str = "operation was cancelled"):
        super().__init__("CANCELLED", message)

"""Structured failures mapped to the execute() envelope."""


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


class InvalidGeometry(ContractError):
    """Primitive dimensions or coordinates that cannot form a solid."""


class InvalidTransform(ContractError):
    """Affine matrix that this kernel cannot apply to a solid."""

    def __init__(self, message: str = "transform is not a valid affine mapping"):
        super().__init__("INVALID_TRANSFORM", message)


class UnknownReference(ContractError):
    def __init__(self, message: str = "reference does not exist"):
        super().__init__("UNKNOWN_REFERENCE", message)

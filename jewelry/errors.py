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


class EmptyResult(ContractError):
    """Boolean subtract with no remaining solid; empty geometry is not a solid."""

    def __init__(self, message: str = "boolean operation produced empty geometry"):
        super().__init__("EMPTY_RESULT", message)


class ToleranceAmbiguity(ContractError):
    """Operands sit inside the kernel gap/overlap band of 2 * KERNEL_NUMERIC_TOL."""

    def __init__(
        self,
        message: str = "boolean operands are within the kernel numeric tolerance band",
    ):
        super().__init__("TOLERANCE_AMBIGUITY", message)


class EmptyHistory(ContractError):
    def __init__(self, message: str = "undo/redo history is empty"):
        super().__init__("EMPTY_HISTORY", message)


class InvalidProfile(ContractError):
    def __init__(self, message: str = "manufacturing profile is invalid"):
        super().__init__("INVALID_PROFILE", message)

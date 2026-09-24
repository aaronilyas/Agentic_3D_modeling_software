"""Provider-neutral planner contract. Context contains semantic state, evidence,
image resources (bytes separate from metadata), and previous execution results.
Decisions may request existing inspection/render tools alongside CAD operations.
"""
from typing import Protocol


class Decision:
    def __init__(self, kind: str, operations=None, reason: str = "", goals=None, validation=None):
        self.kind = kind
        self.operations = list(operations or [])
        self.reason = reason
        self.goals = goals
        self.validation = validation

    def public(self) -> dict:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "operations": [{"op": name, "arguments": args} for name, args in self.operations],
            "goals": self.goals,
            "validation": self.validation,
        }


class Planner(Protocol):
    def decide(self, context: dict) -> Decision: ...

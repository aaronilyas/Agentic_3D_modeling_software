"""Bounded inspect / model / measure / render / refine loop.

A successful CAD call is evidence, not completion. The document and structured
tool results decide whether measurable goals are satisfied. Visual metrics are
recorded separately from exact geometry.
"""

from __future__ import annotations

import copy
from cad.planning import Decision, Planner
from cad.planners import DeterministicPlanner
from cad.goals import evaluate_goals
from cad.content import split_images
from cad.errors import InvalidArgument

# Compatibility for existing callers.
GoalPlanner = DeterministicPlanner


class RefinementLoop:
    def __init__(self, application, planner: Planner, *, cancel_event=None):
        self.application = application
        self.planner = planner
        self.cancel_event = cancel_event

    def run(self, request: str, goals=None, max_iterations: int = 8) -> dict:
        if not isinstance(request, str) or not request.strip():
            raise InvalidArgument("request must be a nonempty string")
        if isinstance(max_iterations, bool) or not isinstance(max_iterations, int):
            raise InvalidArgument("max_iterations must be an integer")
        max_iterations = max(1, min(max_iterations, 20))
        active_goals = list(goals or [])
        evidence = []
        previous_results = []
        images = []
        validation_arguments = {"scope": "geometry"}
        renders = []
        status = "limit"
        reason = "iteration limit reached"
        iterations = 0
        for iteration in range(max_iterations):
            iterations = iteration + 1
            if self._cancelled():
                status, reason = "cancelled", "refinement was cancelled"
                break
            context = self._context(request, active_goals, previous_results, images)
            context["iteration"] = iteration
            decision = self.planner.decide(context)
            if decision.goals and not active_goals:
                active_goals = list(decision.goals)
                context = self._context(request, active_goals, previous_results, images)
                context["iteration"] = iteration
                if decision.kind == "stop" and context["mismatches"]:
                    decision = self.planner.decide(context)
            if decision.kind not in {"execute", "stop", "impossible"}:
                raise InvalidArgument("planner decision kind must be execute, stop, or impossible")
            if decision.validation is not None:
                validation_arguments = dict(decision.validation)
            mismatches = context["mismatches"]
            evidence.append({
                "iteration": iteration,
                "phase": "plan",
                "decision": decision.public(),
                "mismatches": mismatches,
                "revision": context["snapshot"].get("revision"),
            })
            if decision.kind == "impossible":
                status, reason = "impossible", decision.reason
                break
            if decision.kind == "stop" or (active_goals and not mismatches and not decision.operations):
                status, reason = "review", decision.reason or "planner stopped"
                break
            if not decision.operations:
                status, reason = "incomplete", "planner produced no operation while goals remain open"
                break
            failed = False
            for name, arguments in decision.operations:
                if self._cancelled():
                    status, reason = "cancelled", "refinement was cancelled"
                    failed = True
                    break
                if name in {"refine", "cancel_refine"}:
                    raise InvalidArgument("a planner cannot recursively invoke refinement")
                result = self.application.execute(name, arguments)
                normalized, produced_images = split_images(result)
                previous_results.append({"op": name, "arguments": copy.deepcopy(arguments), "result": normalized})
                images.extend(produced_images)
                evidence.append({
                    "iteration": iteration,
                    "phase": "execute",
                    "op": name,
                    "result": _without_images(result),
                })
                if not result.get("ok"):
                    failed = True
                    break
            if status == "cancelled":
                break
            if failed:
                continue
        else:
            status, reason = "limit", "iteration limit reached before the goals were satisfied"
        final = self._context(request, active_goals, previous_results, images)
        if status in {"limit", "review"} and active_goals and not final["mismatches"]:
            status, reason = "review", "measurable goals match the latest document"
        validation = self.application.execute("validate", validation_arguments)
        evidence.append({"phase": "validate", "result": _without_images(validation)})
        if final["snapshot"].get("references"):
            rendered = self.application.execute("render_views", {"views": ["isometric", "front", "top"]})
            renders = (rendered.get("value") or {}).get("views", []) if rendered.get("ok") else []
            evidence.append({"phase": "render", "result": _without_images(rendered)})
        mismatches = final["mismatches"]
        if status == "review":
            if active_goals and not mismatches:
                ready = (validation.get("value") or {}).get("ready")
                status = "satisfied" if ready else "validation_failed"
                reason = "measurable goals match the document" if ready else "goals match but validation failed"
            elif active_goals and mismatches:
                status = "incomplete"
                reason = "planner stopped before measurable goals were satisfied"
            elif not active_goals:
                status = "stopped"
        report = {
            "status": status,
            "reason": reason,
            "iterations": iterations,
            "revision": final["snapshot"].get("revision"),
            "goals": active_goals,
            "mismatches": mismatches,
            "evidence": evidence,
            "validation": (validation.get("value") if validation.get("ok") else validation.get("error")),
            "visual": {
                "views": [_view_public(view) for view in renders],
                "references": final["references"],
                "note": (
                    "Rendered views supplement exact CAD inspection. "
                    "An uncalibrated image does not establish absolute scale or depth."
                ),
            },
            "units": "mm",
        }
        return report

    def _context(self, request: str, goals: list, previous_results=None, images=None) -> dict:
        snapshot = self._value("snapshot")
        references = self._value("list_references").get("references", [])
        inspection = {}
        for body in snapshot.get("bodies", []):
            faces = self._value("query_faces", {"ref": body["ref"]})
            inspection[body["ref"]] = faces
        mismatches = evaluate_goals(snapshot, inspection, goals)
        return {
            "request": request,
            "snapshot": snapshot,
            "references": references,
            "inspection": inspection,
            "images": [*self.application.reference_resources(), *(images or [])],
            "previous_results": copy.deepcopy(previous_results or []),
            "goals": copy.deepcopy(goals),
            "mismatches": mismatches,
        }

    def _value(self, operation: str, arguments: dict | None = None) -> dict:
        result = self.application.execute(operation, arguments or {})
        if not result.get("ok"):
            return {}
        return result["value"]

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()


def _without_images(result: dict) -> dict:
    return split_images(result)[0]


def _view_public(view: dict) -> dict:
    return {
        "name": view.get("name"),
        "width": view.get("width"),
        "height": view.get("height"),
        "metrics": view.get("metrics"),
        "png_base64": view.get("png_base64"),
        "camera": view.get("camera"),
    }

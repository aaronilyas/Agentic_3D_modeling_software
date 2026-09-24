"""One application, serialized. Presentation caches are not the model."""

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from cad.adapter import create_application


class _Signals(QObject):
    finished = Signal(object)


class _Job(QRunnable):
    def __init__(self, work):
        super().__init__()
        self.work = work
        self.signals = _Signals()

    def run(self):
        self.signals.finished.emit(self.work())


class Controller(QObject):
    refreshed = Signal(object)
    failed = Signal(str, str)
    busy_changed = Signal(bool)
    activity = Signal(str)
    refined = Signal(object)

    def __init__(self, parent=None, application=None, *, background=True):
        super().__init__(parent)
        self.application = application if application is not None else create_application()
        self.background = background
        self.snapshot = None
        self.validation = None
        self.selected_ref = None
        self.busy = False
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    def close(self):
        if self.application is not None:
            self.application.close()
            self.application = None

    def new_document(self):
        self.close()
        self.application = create_application()
        self.validation = None
        self.selected_ref = None
        self.refresh()
        self.activity.emit("New document")

    def refresh(self):
        return self.call("snapshot", {}, refresh=False, on_value=self._store_snapshot)

    def call(self, operation, arguments=None, *, refresh=True, on_value=None):
        if self.application is None or self.busy:
            return False

        def work():
            return self.application.execute(operation, arguments or {})

        def finish(result):
            self.busy = False
            self.busy_changed.emit(False)
            if not result.get("ok"):
                error = result.get("error") or {}
                self.failed.emit(error.get("code", "ERROR"), error.get("message", ""))
                self.activity.emit(error.get("code", "Error"))
                return
            if on_value is not None:
                on_value(result["value"])
            if refresh and operation != "snapshot":
                self.refresh()
            elif operation == "snapshot":
                self.refreshed.emit(self.snapshot)

        self.busy = True
        self.busy_changed.emit(True)
        if not self.background:
            finish(work())
            return True
        job = _Job(work)
        job.signals.finished.connect(finish)
        self._pool.start(job)
        return True

    def _store_snapshot(self, value):
        self.snapshot = value
        if self.selected_ref not in (value.get("references") or []):
            self.selected_ref = None

    def select(self, ref):
        self.selected_ref = ref or None
        self.refreshed.emit(self.snapshot)

    def mutate(self, operation, arguments=None):
        return self.call(operation, arguments or {})

    def delete_selected(self):
        if self.selected_ref:
            self.mutate("delete", {"ref": self.selected_ref})

    def validate(self):
        arguments = {"scope": "manufacturing", "profile": "fdm"}
        if self.selected_ref:
            arguments["ref"] = self.selected_ref

        def store(value):
            self.validation = value
            self.activity.emit("Ready" if value.get("ready") else "Validation findings")

        return self.call("validate", arguments, on_value=store)

    def export(self, fmt, path):
        if not self.selected_ref:
            self.failed.emit("INVALID_ARGUMENT", "select a body before export")
            return False
        arguments = {"ref": self.selected_ref, "path": path, "format": fmt, "mode": "preview"}
        if fmt == "stl":
            if not self.validation or not self.validation.get("ready"):
                self.failed.emit("INVALID_ARGUMENT", "validate the current revision before STL export")
                return False
            if self.snapshot and self.validation.get("revision") != self.snapshot.get("revision"):
                self.failed.emit("STALE_VALIDATION", "validate the current revision before STL export")
                return False
            arguments["mode"] = "manufacturing"
            arguments["validation"] = self.validation
        return self.call("export", arguments, on_value=lambda value: self.activity.emit(value.get("path", "Exported")))

    def save(self, path):
        return self.call("save_project", {"path": path}, refresh=False,
                         on_value=lambda value: self.activity.emit(value.get("path", "Saved")))

    def open(self, path):
        self.validation = None
        return self.call("open_project", {"path": path},
                         on_value=lambda _value: self.activity.emit("Opened"))

    def add_reference(self, path, role="front"):
        return self.call("add_reference", {"path": path, "role": role, "label": role})

    def refine(self, request):
        def show(value):
            self.last_refine = value
            self.refined.emit(value)
            self.activity.emit(value.get("status", "refine"))

        self.last_refine = None
        return self.call("refine", {"request": request, "max_iterations": 12}, on_value=show)

    def cancel(self):
        if self.application is not None:
            self.application.cancel()
            self.activity.emit("Cancel requested")

"""Serialized GUI access to one Application; all cached data is presentation only."""
from PySide6.QtCore import QObject, Signal

from jewelry.application import Application


class Controller(QObject):
    refreshed = Signal(object, object)  # backend snapshot, tessellated meshes by ref
    selection_changed = Signal(object, object)  # ref, backend inspection
    failed = Signal(str, str)

    def __init__(self, parent=None, application_factory=Application):
        super().__init__(parent)
        self._factory = application_factory
        self.application = self._factory()
        self.snapshot = None
        self.selected_ref = None
        self.closed = False

    def request(self, operation, **arguments):
        """The single envelope boundary, also used for read operations."""
        try:
            result = self.application.execute(operation, arguments)
            if result['ok'] is True:
                return True, result['value']
            error = result['error']
            self.failed.emit(error['code'], error['message'])
        except Exception as exc:
            self.failed.emit('GUI_REQUEST_FAILED', str(exc) or type(exc).__name__)
        return False, None

    def mutate(self, operation, **arguments):
        ok, value = self.request(operation, **arguments)
        if ok:
            self.refresh()
            if isinstance(value, dict) and value.get('ref') in self.references:
                self.select(value['ref'])
        return ok

    @property
    def references(self):
        return self.snapshot['references'] if self.snapshot else []

    def refresh(self):
        ok, snapshot = self.request('snapshot')
        if not ok:
            # Never leave stale geometry presented as the current document.
            self.snapshot = None
            self.refreshed.emit(None, {})
            self.select(None)
            return False
        meshes = {}
        for ref in snapshot['references']:
            ok, mesh = self.request('tessellate', ref=ref, chord_tolerance=0.02)
            if ok:
                meshes[ref] = mesh
        self.snapshot = snapshot
        self.refreshed.emit(snapshot, meshes)
        self.select(self.selected_ref)
        return True

    def select(self, ref):
        ref = ref if ref in self.references else None
        info = None
        if ref is not None:
            ok, info = self.request('inspect', ref=ref)
            if not ok:
                ref = None
        self.selected_ref = ref
        self.selection_changed.emit(ref, info)

    def create_ring(self):
        return self.mutate('create_ring', inner_radius=8, outer_radius=9.5, width=4)

    def delete_selected(self):
        if self.selected_ref is not None:
            self.mutate('delete', ref=self.selected_ref)

    def new_document(self):
        if self.closed:
            return
        self.application.close()
        self.application = self._factory()
        self.selected_ref = None
        self.refresh()

    def close(self):
        if not self.closed:
            self.closed = True
            self.application.close()

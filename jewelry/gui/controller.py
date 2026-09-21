"""Serialized access to one Application; all cached data is presentation only."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from jewelry.application import Application


# The repository's mvp-single-piece profile (also used by the contract fixtures).
DEFAULT_PROFILE = {
    'id': 'mvp-single-piece', 'version': 1, 'units': 'mm',
    'min_wall': 1.0, 'min_prong': 0.8, 'max_components': 1,
}
EVENTS = {
    'create_ring': 'Ring created', 'modify_ring': 'Ring modified',
    'cut_through_hole': 'Through-hole cut', 'cut_recess': 'Stone seat / recess cut',
    'add_setting': 'Setting added', 'repeat_prongs': 'Prongs added',
    'delete': 'Object deleted', 'undo': 'Undo', 'redo': 'Redo',
    'validate': 'Validation completed',
}


class _JobSignals(QObject):
    finished = Signal(object)


class _Job(QRunnable):
    def __init__(self, work):
        super().__init__()
        self.work = work
        self.signals = _JobSignals()

    def run(self):
        self.signals.finished.emit(self.work())


class Controller(QObject):
    refreshed = Signal(object, object)
    selection_changed = Signal(object, object)
    validation_changed = Signal(object, bool)  # report, stale
    busy_changed = Signal(bool)
    activity = Signal(str)
    failed = Signal(str, str)
    completed = Signal(str, bool)

    def __init__(self, parent=None, application_factory=Application, *, background=True):
        super().__init__(parent)
        self._factory = application_factory
        self.application = self._factory()
        self.snapshot = None
        self.selected_ref = None
        self.inspection = None
        self.validation = None
        self.profile = deepcopy(DEFAULT_PROFILE)
        self.closed = False
        self.busy = False
        self.background = background
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._job = None

    @staticmethod
    def _execute(application, operation, arguments):
        try:
            return application.execute(operation, arguments)
        except Exception as exc:
            return {'ok': False, 'error': {'code': 'GUI_REQUEST_FAILED',
                                          'message': str(exc) or type(exc).__name__}}

    def request(self, operation, **arguments):
        """Synchronous adapter access for diagnostics/tests; never overlaps a job."""
        if self.closed or self.busy:
            return False, None
        result = self._execute(self.application, operation, arguments)
        if result['ok']:
            return True, result['value']
        self.failed.emit(result['error']['code'], result['error']['message'])
        return False, None

    @property
    def references(self):
        return self.snapshot['references'] if self.snapshot else []

    @property
    def ring_dimensions(self):
        body = next((b for b in (self.snapshot or {}).get('bodies', [])
                     if b['ref'] == self.selected_ref), {})
        if body.get('kind') != 'annulus':
            return None
        return {key: body[key] for key in ('inner_radius', 'outer_radius')} | {
            'width': body['zmax'] - body['zmin']}

    def _start(self, operation, arguments, *, synchronize=False, target=None):
        if self.closed or self.busy:
            return False
        self.busy = True
        self.busy_changed.emit(True)
        application = self.application
        arguments = deepcopy(arguments)

        def work():
            result = {'operation': operation, 'errors': [], 'ok': True}

            def call(name, args):
                envelope = self._execute(application, name, args)
                if not envelope['ok']:
                    result['errors'].append(envelope['error'])
                    return False, None
                return True, envelope['value']

            ok, value = call(operation, arguments)
            result.update(ok=ok, value=value)
            if synchronize and (ok or operation == 'snapshot'):
                ok, snapshot = (ok, value) if operation == 'snapshot' else call('snapshot', {})
                result['snapshot'] = snapshot
                meshes = {}
                if ok:
                    for ref in snapshot['references']:
                        mesh_ok, mesh = call('tessellate', {'ref': ref, 'chord_tolerance': .02})
                        if mesh_ok:
                            meshes[ref] = mesh
                    selected = value.get('ref', target)
                    refs = snapshot['references']
                    selected = selected if selected in refs else (refs[0] if refs else None)
                else:
                    selected = None
                result['meshes'] = meshes
                info = None
                if selected:
                    inspected, info = call('inspect', {'ref': selected})
                    if not inspected:
                        selected = None
                result.update(selected=selected, inspection=info)
            return result

        if self.background:
            self._job = _Job(work)
            self._job.signals.finished.connect(self._finish)
            self._pool.start(self._job)
            return True  # accepted; completion is reported by completed
        result = work()
        self._finish(result)
        return result['ok']

    @Slot(object)
    def _finish(self, result):
        if self.closed:
            return
        operation = result['operation']
        if operation == 'inspect' and not result['ok']:
            self.selected_ref = None
            self.inspection = None
            self.selection_changed.emit(None, None)
        if 'snapshot' in result:
            self.snapshot = result['snapshot']
            self.selected_ref = result['selected']
            self.inspection = result['inspection']
            self.refreshed.emit(self.snapshot, result['meshes'])
            self.selection_changed.emit(self.selected_ref, self.inspection)
            self._validation_state()
        if result['ok']:
            if operation == 'inspect':
                self.inspection = result['value']
                self.selection_changed.emit(self.selected_ref, self.inspection)
            elif operation == 'validate':
                self.validation = result['value']
                self._validation_state()
            if operation in EVENTS:
                self.activity.emit(EVENTS[operation])
            elif operation == 'export':
                self.activity.emit(f'Exported STL: {self._export_path}')
        self.busy = False
        self._job = None
        self.busy_changed.emit(False)
        self.completed.emit(operation, result['ok'])
        # A committed edit can still have refresh errors. Close its form first
        # so those errors remain visible in the window instead of disappearing.
        for error in result['errors']:
            self.failed.emit(error['code'], error['message'])

    def _validation_state(self):
        stale = bool(self.validation and (not self.snapshot or
                     self.validation['revision'] != self.snapshot['revision']))
        self.validation_changed.emit(self.validation, stale)

    def set_profile(self, profile):
        if self.busy or self.closed:
            return
        if profile != self.profile:
            self.profile = deepcopy(profile)
            self.validation = None
            self._validation_state()

    def mutate(self, operation, **arguments):
        return self._start(operation, arguments, synchronize=True, target=self.selected_ref)

    def refresh(self):
        return self._start('snapshot', {}, synchronize=True, target=self.selected_ref)

    def select(self, ref):
        if self.busy or self.closed:
            return
        self.selected_ref = ref if ref in self.references else None
        if self.selected_ref is None:
            self.inspection = None
            self.selection_changed.emit(None, None)
        else:
            self._start('inspect', {'ref': self.selected_ref})

    def create_ring(self, inner_radius=8, outer_radius=9.5, width=4):
        return self.mutate('create_ring', inner_radius=inner_radius, outer_radius=outer_radius, width=width)

    def modify_ring(self, **dimensions):
        return self.feature('modify_ring', **dimensions)

    def feature(self, operation, **parameters):
        if self.selected_ref is None:
            return False
        return self.mutate(operation, ref=self.selected_ref, **parameters)

    def delete_selected(self):
        return self.feature('delete')

    def validate(self):
        return self._start('validate', {'profile': self.profile})

    def export_stl(self, path):
        if self.busy or self.closed or self.selected_ref is None:
            return False
        self._export_path = str(Path(path).absolute()) if path else path
        return self._start('export', {'ref': self.selected_ref, 'path': self._export_path,
                                     'format': 'stl', 'validation': self.validation,
                                     'chord_tolerance': .02})

    def new_document(self):
        if self.closed or self.busy:
            return False
        self.application.close()
        self.application = self._factory()
        self.selected_ref = None
        self.validation = None
        self.activity.emit('New document')
        return self.refresh()

    def close(self):
        if not self.closed:
            self.closed = True
            self._pool.waitForDone()
            self.application.close()

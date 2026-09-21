"""Owns ACP lifecycle and shares the direct controller's document/work queue."""
import json
import threading
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
from jewelry.acp import MissingCapability
from jewelry.agent_session import AgentError, AgentSession
from jewelry.gui.controller import _Job, EVENTS


class AgentController(QObject):
    status = Signal(str)
    message = Signal(str, str)
    finished = Signal(bool)

    def __init__(self, controller, parent=None, *, deterministic=False, cwd=None):
        super().__init__(parent)
        self.controller = controller
        self.deterministic = deterministic
        self.cwd = str(Path(cwd or Path.cwd()).absolute())
        self.session = None
        self.active = False
        self.closed = False
        self._job = None
        self._ok = True
        self._cancelled = threading.Event()
        controller.completed.connect(self._refreshed)
        controller.agent_controller = self

    def send(self, prompt, agent='grok', *, calls=None):
        c = self.controller
        if self.closed or c.closed or c.busy or not prompt.strip():
            return False
        self._cancelled.clear()
        self.active = True
        c.busy = True
        c.busy_changed.emit(True)
        self.message.emit('You', prompt)
        application = c.application
        context = f'Selected reference: {c.selected_ref}. Manufacturing profile: {json.dumps(c.profile)}.'

        def work():
            result = {'text': '', 'calls': [], 'error': None, 'tool_failures': []}
            baseline = len(application.endpoint().observed_calls)
            try:
                if self.session and (self.session.agent != agent or self.session.application is not application):
                    self.session.close()
                    self.session = None
                if self.session is None:
                    self.session = AgentSession(application, agent, self.cwd, deterministic=self.deterministic)
                self.session.cancelled = self._cancelled
                result['text'], result['calls'] = self.session.turn(prompt, self.status.emit, context=context, calls=calls)
            except Exception as exc:
                code = ('MISSING_CAPABILITY' if isinstance(exc, MissingCapability) else
                        exc.code if isinstance(exc, AgentError) else
                        'ACP_CONNECTION' if isinstance(exc, (ConnectionError, BrokenPipeError)) else 'ACP_STARTUP')
                if self._cancelled.is_set():
                    code = 'CANCELLED'
                result['error'] = (code, str(exc)[:2000])
                if self.session:
                    self.session.close()
                    self.session = None
                result['calls'] = list(application.endpoint().observed_calls[baseline:])
            if self.session:
                result['tool_failures'] = list(self.session.tool_failures)
            return result

        self._job = _Job(work)
        self._job.signals.finished.connect(self._finish)
        c._pool.start(self._job)
        return True

    @Slot(object)
    def _finish(self, result):
        self._job = None
        if self.closed or self.controller.closed:
            return
        self._ok = result['error'] is None and not result['tool_failures']
        for title in result['tool_failures']:
            self.message.emit('Agent tool error', f'{title} failed; agent prose does not confirm success.')
        for call in result['calls']:
            envelope = call['result']
            name = call['name']
            if not envelope['ok']:
                self._ok = False
                error = envelope['error']
                self.message.emit('CAD error', f"{name}: {error['code']} — {error['message']}")
            elif name == 'validate':
                report = envelope['value']
                self.controller.validation = report
                self.message.emit('CAD result', 'Validated model: ' + ('ready' if report['ready'] else
                                  f"not ready — {len(report['findings'])} manufacturing findings"))
            elif name in EVENTS or name.startswith('export'):
                label = EVENTS.get(name, 'Export completed')
                self.message.emit('CAD result', label)
        if result['text']:
            self.message.emit('Assistant (agent text)', result['text'])
        if result['error']:
            self.message.emit('Connection / protocol error', ': '.join(result['error']))
        elif not result['calls']:
            self.message.emit('Status', 'No CAD tool operation was verified for this turn.')
        self.status.emit('Refreshing model')
        # Keep the shared busy lease through refresh; no event-loop yield occurs
        # between releasing it here and acquiring it in refresh().
        self.controller.busy = False
        self.controller.refresh()

    @Slot(str, bool)
    def _refreshed(self, operation, ok):
        if self.active and operation == 'snapshot':
            self.active = False
            self.status.emit('Ready' if self._ok and ok else 'Error')
            self.finished.emit(self._ok and ok)

    def cancel(self):
        self._cancelled.set()
        if self.session:
            self.session.cancelled.set()

    def close(self):
        self.closed = True
        self.cancel()
        self.controller._pool.waitForDone()
        if self.session:
            self.session.close()
            self.session = None

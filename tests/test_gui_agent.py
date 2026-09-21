"""GUI agent tests. Integration cases launch real CLIs with the local model."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from jewelry.application import Application
from jewelry.agent_session import AgentSession, AgentError
from jewelry.gui.controller import Controller
from jewelry.gui.main_window import MainWindow


class AgentGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = Controller(background=False)
        self.window = MainWindow(self.controller)
        self.agent = self.window.agent_controller
        self.agent.deterministic = True
        self.messages = []
        self.agent.message.connect(lambda *args: self.messages.append(args))
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.controller.close()
        self.window.close()
        self.qt.processEvents()

    def wait_for(self, predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.qt.processEvents()
            time.sleep(.01)
        self.assertTrue(predicate(), (self.messages, self.window.agent_panel.status.text(),
                                     self.agent.session.transport._stderr_lines[-5:]
                                     if self.agent.session and self.agent.session.transport else []))

    def turn(self, agent, operation, **arguments):
        self.assertTrue(self.agent.send('Please update the design', agent,
                                       calls=[{'name': operation, 'arguments': arguments}]))
        self.wait_for(lambda: not self.agent.active)

    def test_panel_missing_capability_and_concurrent_send(self):
        panel = self.window.agent_panel
        self.assertEqual(self.window.agent_dock.windowTitle(), 'Design Assistant')
        self.assertFalse(panel.send_button.isEnabled())
        panel.prompt.setText('Create a ring')
        self.assertTrue(panel.send_button.isEnabled())
        for name in ('grok', 'codex'):
            panel.agent.setCurrentIndex(panel.agent.findData(name))
            panel.prompt.setText('Create a ring')
            with patch.dict(os.environ, {f'JEWELRY_{name.upper()}': f'/missing/jewelry-{name}'}):
                panel.send()
                self.assertFalse(panel.send_button.isEnabled())
                self.assertFalse(self.agent.send('Another edit'))
                self.assertFalse(self.controller.create_ring())
                self.wait_for(lambda: not self.agent.active)
            self.assertIn('MISSING_CAPABILITY', panel.transcript.toPlainText())
            self.assertEqual(panel.status.text(), 'Error')
            self.assertEqual(self.controller.references, [])

    def test_real_acp_both_agents_shared_document_lifecycle_and_errors(self):
        for name in ('grok', 'codex'):
            with self.subTest(agent=name):
                self.controller.new_document()
                app = self.controller.application
                self.controller.create_ring()
                ref = self.controller.selected_ref
                self.controller.validate()
                report = self.controller.validation
                heartbeats = []
                timer = QTimer()
                timer.setInterval(10)
                timer.timeout.connect(lambda: heartbeats.append(1))
                timer.start()
                self.turn(name, 'modify_ring', ref=ref, outer_radius=10.)
                timer.stop()
                self.assertTrue(heartbeats)
                self.assertIs(self.agent.session.application, app)
                self.assertIs(self.agent.session.application.endpoint().application, app)
                self.assertEqual(self.controller.references, [ref])
                self.assertEqual(self.controller.ring_dimensions['outer_radius'], 10.)
                self.assertAlmostEqual(self.window.viewport.actors_by_ref[ref].bounds.x_max, 10.)
                self.assertEqual(self.window.inspector.fields['Reference'].text(), ref)
                self.assertEqual(list(self.window.tree.items_by_ref), [ref])
                self.assertNotEqual(report['revision'], self.controller.snapshot['revision'])
                self.assertIn('stale', self.window.validation_panel.status.text().lower())
                self.turn(name, 'validate', profile=self.controller.profile)
                self.assertEqual(self.controller.validation['revision'], self.controller.snapshot['revision'])
                self.assertIn('Ready', self.window.validation_panel.status.text())
                transport = self.agent.session.transport
                proc, home = transport._proc, transport._home
                self.turn(name, 'modify_ring', ref=ref, outer_radius=7.)
                self.assertIs(self.agent.session.transport, transport)
                self.assertEqual(self.controller.ring_dimensions['outer_radius'], 10.)
                self.assertTrue(any(role == 'CAD error' for role, _ in self.messages))
                self.assertEqual(self.window.agent_panel.status.text(), 'Error')
                self.controller.mutate('undo')
                self.assertEqual(self.controller.ring_dimensions['outer_radius'], 9.5)
                self.controller.mutate('redo')
                self.controller.validate()
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'ring.stl'
                    self.assertTrue(self.controller.export_stl(str(path)))
                    self.assertTrue(path.exists())
                endpoint = app.endpoint()
                self.controller.new_document()
                self.assertIsNone(self.agent.session)
                self.assertIsNotNone(proc.poll())
                self.assertFalse(home.exists())
                self.assertTrue(endpoint._closed)
                self.assertIsNone(endpoint._sock)
                self.assertEqual(endpoint._sessions, set())

    def test_configured_cli_path_with_real_agents_and_local_inference(self):
        # Exercise deterministic=False without paying for inference or replacing
        # ACP: install a local provider into each real CLI's temporary config.
        from jewelry.acp import _isolated_env, _grok_config, _codex_config
        from jewelry.mock_model import MockModel
        for name in ('grok', 'codex'):
            with self.subTest(agent=name), tempfile.TemporaryDirectory() as directory:
                self.controller.new_document()
                app = self.controller.application
                endpoint = app.endpoint()
                model = MockModel()
                model.observed_len = lambda: len(endpoint.observed_calls)
                model.mcp_ready = endpoint.tools_ready
                model.start()
                try:
                    root = Path(directory)
                    config = root / name
                    config.mkdir()
                    env = _isolated_env(root)
                    if name == 'grok':
                        (config / 'config.toml').write_text(_grok_config(model.base_url))
                        env.update(GROK_HOME=str(config), XAI_API_KEY='test',
                                   GROK_CLI_CHAT_PROXY_BASE_URL=model.base_url,
                                   GROK_MODELS_BASE_URL=model.base_url, GROK_AGENT_DASHBOARD='0')
                    else:
                        (config / 'config.toml').write_text(_codex_config(model.base_url, Path.cwd()))
                        (config / 'auth.json').write_text('{"auth_mode":"apikey","OPENAI_API_KEY":"test"}')
                        env.update(CODEX_HOME=str(config), OPENAI_API_KEY='test', CODEX_API_KEY='test',
                                   APP_SERVER_LOGS=str(root / 'logs'))
                    model.queue_tool_calls([{'name': 'create_ring', 'arguments':
                                            {'inner_radius': 8., 'outer_radius': 9.5, 'width': 4.}}])
                    self.agent.deterministic = False
                    with patch.dict(os.environ, env, clear=True):
                        self.assertTrue(self.agent.send('Create a ring with inner radius 8 mm, outer radius 9.5 mm, width 4 mm', name))
                        self.wait_for(lambda: not self.agent.active)
                        self.assertEqual(len(self.controller.references), 1, self.messages)
                        self.assertIsNone(self.agent.session.transport._mock)
                        self.controller.new_document()
                finally:
                    if self.agent.active:
                        self.agent.cancel()
                        self.wait_for(lambda: not self.agent.active, timeout=15)
                    if self.agent.session:
                        self.agent.session.close()
                        self.agent.session = None
                    model.close()

    def test_switch_agent_startup_failure_does_not_replay_previous_results(self):
        self.turn('grok', 'create_ring', inner_radius=8., outer_radius=9.5, width=4.)
        app = self.controller.application
        proc = self.agent.session.transport._proc
        successes = [message for message in self.messages if message[0] == 'CAD result']
        with patch.dict(os.environ, {'JEWELRY_CODEX': '/missing/codex'}):
            self.assertTrue(self.agent.send('Modify the ring', 'codex'))
            self.wait_for(lambda: not self.agent.active)
        self.assertEqual(successes, [message for message in self.messages if message[0] == 'CAD result'])
        self.assertIs(self.controller.application, app)
        self.assertEqual(len(self.controller.references), 1)
        self.assertIsNotNone(proc.poll())
        self.assertEqual(self.window.agent_panel.status.text(), 'Error')

    def test_real_acp_close_during_turn(self):
        self.agent.send('Create a ring', 'grok', calls=[{'name': 'create_ring', 'arguments':
                        {'inner_radius': 8., 'outer_radius': 9.5, 'width': 4.}}])
        self.window.close()
        self.wait_for(lambda: self.window._shutdown_done)
        self.assertTrue(self.controller.closed)
        self.assertIsNone(self.agent.session)
        self.assertEqual(self.controller._pool.activeThreadCount(), 0)

    def test_protocol_error_is_distinct_and_session_closes(self):
        # Client unit test only; real ACP integration is exercised above.
        class InvalidTransport:
            def send_line(self, line):
                pass
            def recv_line(self, timeout):
                return 'not json'
            def close(self):
                self.closed = True
        session = AgentSession(self.controller.application, 'grok', Path.cwd())
        transport = session.transport = InvalidTransport()
        with self.assertRaises(AgentError) as caught:
            session.request('initialize', {}, lambda _: None)
        self.assertEqual(caught.exception.code, 'ACP_PROTOCOL')
        session.close()
        self.assertTrue(transport.closed)

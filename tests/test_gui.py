"""Real Qt/VTK integration tests; run explicitly with GUI extras installed."""
import unittest
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from PySide6.QtCore import Qt, QTimer
from jewelry.application import Application
from jewelry.gui.controller import Controller
from jewelry.gui.main_window import MainWindow


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.factory = Mock(side_effect=Application)
        self.controller = Controller(application_factory=self.factory, background=False)
        self.window = MainWindow(self.controller)
        self.window.show()
        self.qt.processEvents()
        self.addCleanup(self.window.close)

    def ring(self):
        self.window.actions['ring'].trigger()
        self.submit_dialog()
        return self.controller.selected_ref

    def submit_dialog(self, **values):
        dialog = self.window.operation_dialog
        self.assertIsNotNone(dialog)
        for key, value in values.items():
            dialog.fields[key].setValue(value)
        dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).click()

    def test_window_one_application_and_shutdown(self):
        self.assertEqual(self.factory.call_count, 1)
        self.assertIs(self.window.centralWidget(), self.window.viewport)
        self.assertTrue(self.window.isVisible())
        app = self.controller.application
        self.window.close()
        self.controller.close()
        self.assertEqual(app.execute('snapshot')['error']['code'], 'APPLICATION_CLOSED')

    def test_success_failure_envelopes_preserve_document(self):
        failures = []
        self.controller.failed.connect(lambda *args: failures.append(args))
        ok, snapshot = self.controller.request('snapshot')
        self.assertTrue(ok)
        self.assertEqual(snapshot['references'], [])
        self.assertFalse(self.controller.mutate('create_ring', inner_radius=9, outer_radius=8, width=4))
        self.assertTrue(failures[-1][0])
        self.assertTrue(failures[-1][1])
        self.assertEqual(self.controller.request('snapshot')[1], snapshot)
        self.assertTrue(self.controller.create_ring())

    def test_backend_mesh_tree_inspection_and_selection(self):
        ref = self.ring()
        self.assertEqual(self.factory.call_count, 1)
        item = self.window.tree.items_by_ref[ref]
        self.assertEqual(item.data(0, Qt.ItemDataRole.UserRole), ref)
        self.assertEqual(item.text(0), 'Ring 1')
        actor = self.window.viewport.actors_by_ref[ref]
        mesh = self.controller.request('tessellate', ref=ref, chord_tolerance=.02)[1]
        np.testing.assert_allclose(actor.mapper.dataset.points, mesh['vertices'])
        np.testing.assert_array_equal(actor.mapper.dataset.faces.reshape(-1, 4)[:, 1:], mesh['triangles'])
        self.assertEqual(self.window.inspector.fields['Reference'].text(), ref)
        self.assertEqual(self.window.inspector.fields['Closed'].text(), 'Yes')
        self.controller.select(None)
        self.window.tree.setCurrentItem(item)
        self.assertEqual(self.controller.selected_ref, ref)
        self.controller.select(None)
        self.window.viewport._picked(actor)
        self.assertEqual(self.controller.selected_ref, ref)
        self.assertTrue(item.isSelected())
        self.assertEqual(actor.prop.color.hex_rgb, '#ffcb4d')

    def test_refresh_external_change_delete_undo_redo_new(self):
        ref = self.ring()
        app = self.controller.application
        app.execute('modify_ring', {'ref': ref, 'outer_radius': 11})
        self.controller.refresh()
        self.assertAlmostEqual(self.window.viewport.actors_by_ref[ref].bounds.x_max, 11)
        self.window.actions['delete'].trigger()
        self.assertEqual(self.window.viewport.actors_by_ref, {})
        self.assertEqual(self.window.tree.items_by_ref, {})
        self.assertEqual(self.window.inspector.fields['Reference'].text(), '—')
        self.window.actions['undo'].trigger()
        self.assertIn(ref, self.window.viewport.actors_by_ref)
        self.assertEqual(self.controller.selected_ref, ref)
        self.assertEqual(self.window.inspector.fields['Reference'].text(), ref)
        self.assertAlmostEqual(self.window.viewport.actors_by_ref[ref].bounds.x_max, 11)
        self.window.actions['redo'].trigger()
        self.assertEqual(self.window.viewport.actors_by_ref, {})
        self.window.actions['undo'].trigger()
        self.window.actions['new'].trigger()
        self.assertEqual(self.factory.call_count, 2)
        self.assertEqual(app.execute('snapshot')['error']['code'], 'APPLICATION_CLOSED')
        self.assertEqual(self.controller.references, [])
        self.assertEqual(self.window.viewport.actors_by_ref, {})
        self.assertFalse(self.window.actions['undo'].isEnabled())

    def test_failed_tessellation_drops_stale_actor(self):
        ref = self.ring()
        execute = self.controller.application.execute
        def fail_mesh(operation, arguments):
            if operation == 'tessellate':
                return {'ok': False, 'error': {'code': 'TESSELLATION_FAILED', 'message': 'test failure'}}
            return execute(operation, arguments)
        self.controller.application.execute = fail_mesh
        self.controller.refresh()
        self.assertIn(ref, self.window.tree.items_by_ref)
        self.assertNotIn(ref, self.window.viewport.actors_by_ref)

    def test_failed_snapshot_clears_stale_presentation(self):
        self.ring()
        self.window.actions['validate'].trigger()
        execute = self.controller.application.execute
        def fail_snapshot(operation, arguments):
            if operation == 'snapshot':
                return {'ok': False, 'error': {'code': 'SNAPSHOT_FAILED', 'message': 'test failure'}}
            return execute(operation, arguments)
        self.controller.application.execute = fail_snapshot
        self.assertFalse(self.controller.refresh())
        self.assertIsNone(self.controller.snapshot)
        self.assertIsNone(self.controller.selected_ref)
        self.assertEqual(self.window.tree.items_by_ref, {})
        self.assertEqual(self.window.viewport.actors_by_ref, {})
        self.assertEqual(self.window.inspector.fields['Reference'].text(), '—')
        self.assertIn('stale', self.window.validation_panel.status.text())

    def test_camera_fit_edges_and_real_picker(self):
        ref = self.ring()
        snapshot = self.controller.request('snapshot')[1]
        viewport = self.window.viewport
        plotter = viewport.plotter
        self.window.actions['edges'].trigger()
        self.assertTrue(viewport.actors_by_ref[ref].prop.show_edges)
        plotter.camera.position = (1000, 1000, 1000)
        distant = plotter.camera.distance
        viewport.fit_model()
        self.assertLess(plotter.camera.distance, distant / 5)
        viewport.reset_camera()
        self.assertEqual(tuple(plotter.camera.up), (0, 0, 1))
        # Pick a projected point on the actual ring with VTK, not a fake mesh.
        renderer = plotter.renderer
        renderer.SetWorldPoint(8.75, 0, 2, 1)
        renderer.WorldToDisplay()
        x, y, _ = renderer.GetDisplayPoint()
        self.controller.select(None)
        plotter.iren.picker.Pick(x, y, 0, renderer)
        self.assertEqual(self.controller.selected_ref, ref)
        # Exercise VTK's interaction style through mouse events.
        iren = plotter.iren.interactor
        before = tuple(plotter.camera.position)
        iren.SetEventInformation(200, 200)
        iren.InvokeEvent('LeftButtonPressEvent')
        iren.SetEventInformation(240, 230)
        iren.InvokeEvent('MouseMoveEvent')
        iren.InvokeEvent('LeftButtonReleaseEvent')
        self.assertNotEqual(tuple(plotter.camera.position), before)
        before = tuple(plotter.camera.focal_point)
        iren.SetEventInformation(200, 200)
        iren.InvokeEvent('MiddleButtonPressEvent')
        iren.SetEventInformation(220, 220)
        iren.InvokeEvent('MouseMoveEvent')
        iren.InvokeEvent('MiddleButtonReleaseEvent')
        self.assertNotEqual(tuple(plotter.camera.focal_point), before)
        before = plotter.camera.distance
        iren.InvokeEvent('MouseWheelForwardEvent')
        self.assertNotEqual(plotter.camera.distance, before)
        self.assertEqual(self.controller.request('snapshot')[1], snapshot)

    def test_create_form_validation_cancel_and_structured_backend_failure(self):
        self.window.actions['ring'].trigger()
        dialog = self.window.operation_dialog
        dialog.fields['outer_radius'].setValue(7)
        self.assertFalse(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
        self.assertEqual(dialog.fields['width'].suffix(), ' mm')
        dialog.reject()
        self.assertEqual(self.controller.references, [])
        self.window.actions['ring'].trigger()
        with self.controller.application.fail_at('create_ring', 'after_geometry'):
            self.submit_dialog()
        self.assertIn('INJECTED_FAILURE', self.window.operation_dialog.error.text())
        self.assertEqual(self.controller.references, [])
        self.submit_dialog(inner_radius=7, outer_radius=9, width=5)
        self.assertIsNone(self.window.operation_dialog)
        self.assertEqual(self.controller.ring_dimensions, {'inner_radius': 7, 'outer_radius': 9, 'width': 5})
        self.assertEqual(self.window.statusBar().currentMessage(), 'Ring created')

    def test_create_modify_validate_export_workflow(self):
        from tests.export_assertions import assert_stl
        ref = self.ring()
        self.window.inspector.modify_button.click()
        self.assertEqual(self.window.operation_dialog.fields['outer_radius'].value(), 9.5)
        self.submit_dialog(outer_radius=10, width=5)
        self.assertEqual(self.controller.selected_ref, ref)
        self.assertEqual(self.window.tree.currentItem().data(0, Qt.ItemDataRole.UserRole), ref)
        self.assertAlmostEqual(self.window.viewport.actors_by_ref[ref].bounds.x_max, 10)
        self.assertIn('Width: 5', self.window.inspector.fields['Ring dimensions (mm)'].text())
        self.window.actions['undo'].trigger()
        self.assertEqual(self.controller.ring_dimensions['width'], 4)
        self.assertAlmostEqual(self.window.viewport.actors_by_ref[ref].bounds.x_max, 9.5)
        self.window.actions['redo'].trigger()
        self.assertEqual(self.controller.ring_dimensions['width'], 5)
        self.assertAlmostEqual(self.window.viewport.actors_by_ref[ref].bounds.x_max, 10)
        self.window.actions['validate'].trigger()
        self.assertEqual(self.window.validation_panel.status.text(), 'Ready for export')
        before = self.controller.request('snapshot')[1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ring.stl'
            with patch('jewelry.gui.main_window.QFileDialog.getSaveFileName', return_value=(str(path), 'STL files (*.stl)')) as chooser:
                self.window.actions['export'].trigger()
                chooser.assert_called_once()
            assert_stl(self, path, self.controller.inspection)
            self.assertIn(str(path), self.window.statusBar().currentMessage())
            with patch('jewelry.gui.main_window.QFileDialog.getSaveFileName', return_value=('', '')):
                self.window.actions['export'].trigger()
            self.assertEqual(list(Path(directory).iterdir()), [path])
        self.assertEqual(before, self.controller.request('snapshot')[1])

    def test_feature_dialogs_dispatch_and_refresh_decorated_workflow(self):
        ref = self.ring()
        execute = self.controller.application.execute
        with patch.object(self.controller.application, 'execute', wraps=execute) as calls:
            for operation in ('add_setting', 'cut_recess', 'repeat_prongs', 'cut_through_hole'):
                with self.subTest(operation=operation):
                    previous_volume = self.controller.inspection['volume']
                    self.window.actions[operation].trigger()
                    expected = self.window.operation_dialog.parameters()
                    self.submit_dialog()
                    calls.assert_any_call(operation, {'ref': ref, **expected})
                    self.assertEqual(self.controller.selected_ref, ref)
                    self.assertNotEqual(self.controller.inspection['volume'], previous_volume)
                    self.assertIn(ref, self.window.viewport.actors_by_ref)
                    mesh = self.controller.request('tessellate', ref=ref, chord_tolerance=.02)[1]
                    np.testing.assert_allclose(self.window.viewport.actors_by_ref[ref].mapper.dataset.points, mesh['vertices'])
                    self.assertEqual(self.window.inspector.fields['Reference'].text(), ref)
                    self.assertTrue(self.window.tree.items_by_ref[ref].isSelected())
            self.assertFalse(self.window.actions['modify_ring'].isEnabled())
            self.assertFalse(self.window.inspector.modify_button.isEnabled())
            self.window.actions['validate'].trigger()
            self.assertTrue(self.controller.validation['ready'])
        # Undoing every feature restores the backend's editable ring type.
        for _ in range(4):
            self.window.actions['undo'].trigger()
        self.assertTrue(self.window.actions['modify_ring'].isEnabled())
        self.assertIn('stale', self.window.validation_panel.status.text())

    def test_validation_findings_profile_and_export_rejections(self):
        ref = self.ring()
        self.window.actions['validate'].trigger()
        self.controller.modify_ring(outer_radius=10)  # valid but stale
        failures = []
        self.controller.failed.connect(lambda code, message: failures.append(code))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ring.stl'
            self.assertFalse(self.controller.export_stl(str(path)))
            self.assertEqual(failures[-1], 'STALE_VALIDATION')
            self.assertFalse(path.exists())
            self.controller.modify_ring(outer_radius=8.5)
            previous_failures = len(failures)
            self.window.validation_panel.validate_button.click()
            self.assertEqual(len(failures), previous_failures)
            self.assertEqual(self.window.validation_panel.status.text(), 'Manufacturing issues found')
            table = self.window.validation_panel.findings
            self.assertEqual([table.item(0, col).text() for col in (0, 1, 3, 4)],
                             ['error', 'THIN_FEATURE', '0.5', '1.0'])
            self.assertFalse(self.controller.export_stl(str(path)))
            self.assertEqual(failures[-1], 'NOT_MANUFACTURING_READY')
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.window.validation_panel.fields['min_wall'].setValue(.4)
            self.assertIsNone(self.controller.validation)
            self.window.actions['validate'].trigger()
            self.assertTrue(self.controller.validation['ready'])
            self.assertTrue(self.controller.export_stl(str(path)))
            original = path.read_bytes()
            self.assertFalse(self.controller.export_stl(str(path / 'invalid.stl')))
            self.assertEqual(failures[-1], 'INVALID_ARGUMENT')
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.controller.selected_ref, ref)

    def test_all_finding_codes_render_without_transport_error(self):
        codes = ['OPEN_SHELL', 'NON_MANIFOLD', 'SELF_INTERSECTION', 'ZERO_THICKNESS', 'THIN_FEATURE', 'UNINTENDED_BODY']
        panel = self.window.validation_panel
        panel.display({'ready': False, 'findings': [
            {'severity': 'error', 'code': code, 'message': f'Description for {code}'} for code in codes]})
        self.assertEqual(panel.status.text(), 'Manufacturing issues found')
        self.assertEqual(panel.findings.rowCount(), 6)
        for row, code in enumerate(codes):
            self.assertEqual(panel.findings.item(row, 1).text(), code)
            self.assertEqual(panel.findings.item(row, 2).text(), f'Description for {code}')
            self.assertEqual(panel.findings.item(row, 3).text(), '—')

    def test_shortcuts_and_missing_validation(self):
        self.ring()
        self.assertEqual(self.window.actions['delete'].shortcut().toString(), 'Del')
        self.assertEqual(self.window.actions['redo'].shortcut().toString(), 'Ctrl+Shift+Z')
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(self.controller.export_stl(str(Path(directory) / 'unvalidated.stl')))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_background_access_is_serial_and_event_loop_stays_responsive(self):
        self.controller.background = True
        entered, release = threading.Event(), threading.Event()
        execute = self.controller.application.execute
        threads = []
        def slow(operation, arguments):
            threads.append(threading.get_ident())
            if operation == 'create_ring':
                entered.set()
                release.wait(5)
            return execute(operation, arguments)
        self.controller.application.execute = slow
        self.addCleanup(release.set)
        self.window.actions['ring'].trigger()
        self.submit_dialog()
        self.assertTrue(entered.wait(2))
        self.assertTrue(self.controller.busy)
        self.assertFalse(self.window.actions['ring'].isEnabled())
        self.assertFalse(self.controller.create_ring())
        self.assertFalse(self.controller.new_document())
        self.assertEqual(self.controller.request('snapshot'), (False, None))
        self.assertFalse(self.window.close())
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        self.qt.processEvents()
        self.assertTrue(ticks)
        release.set()
        self.wait_idle()
        self.assertEqual(len(self.controller.references), 1)
        self.assertTrue(self.window.actions['modify_ring'].isEnabled())
        self.assertIsNone(self.window.operation_dialog)
        self.assertTrue(all(thread != threading.get_ident() for thread in threads))
        self.controller.validate()
        self.wait_idle()
        self.assertEqual(self.window.validation_panel.status.text(), 'Ready for export')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'async.stl'
            self.controller.export_stl(str(path))
            self.wait_idle()
            self.assertTrue(path.is_file())

    def wait_idle(self):
        deadline = time.monotonic() + 10
        while self.controller.busy and time.monotonic() < deadline:
            self.qt.processEvents()
            time.sleep(.005)
        self.assertFalse(self.controller.busy, 'controller worker did not finish')

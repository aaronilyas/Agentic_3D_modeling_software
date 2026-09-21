"""Real Qt/VTK integration tests; run explicitly with GUI extras installed."""
import unittest
from unittest.mock import Mock

import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from jewelry.application import Application
from jewelry.gui.controller import Controller
from jewelry.gui.main_window import MainWindow


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.factory = Mock(side_effect=Application)
        self.controller = Controller(application_factory=self.factory)
        self.window = MainWindow(self.controller)
        self.window.show()
        self.qt.processEvents()
        self.addCleanup(self.window.close)

    def ring(self):
        self.window.actions['ring'].trigger()
        return self.controller.selected_ref

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

    def test_camera_fit_edges_and_real_picker(self):
        ref = self.ring()
        viewport = self.window.viewport
        plotter = viewport.plotter
        self.window.actions['edges'].trigger()
        self.assertTrue(viewport.actors_by_ref[ref].prop.show_edges)
        plotter.camera.position = (1000, 1000, 1000)
        viewport.fit_model()
        self.assertLess(plotter.camera.distance, 100)
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

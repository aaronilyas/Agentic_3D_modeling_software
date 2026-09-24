"""Offscreen construction of the agent-first window."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolBar

from cad.gui.controller import Controller
from cad.gui.main_window import MainWindow
from tests.test_cad_assets import write_png


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_window_creates_a_body_reference_and_project(self):
        controller = Controller(background=False)
        window = MainWindow(controller)
        self.addCleanup(window.close)
        self.assertEqual(window.windowTitle(), "Agentic CAD")
        self.assertTrue(any(bar.objectName() == "Tools" for bar in window.findChildren(QToolBar)))
        controller.mutate("create_primitive", {
            "kind": "box", "size": [2, 3, 4], "origin": [0, 0, 0], "name": "gui-box",
        })
        root = window.tree.topLevelItem(0)
        self.assertEqual(root.text(0), "Document")
        self.assertEqual(root.childCount(), 1)
        self.assertEqual(root.child(0).text(0), "gui-box")
        root.child(0).setSelected(True)
        self.assertIn("24.000", window.inspector.toPlainText())
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        image = Path(directory.name) / "front.png"
        write_png(image, 8, 4)
        window.references.files_dropped.emit(str(image))
        self.assertIn("front", window.references.list.item(0).text())
        destination = str(Path(directory.name) / "model.cadproj")
        controller.save(destination)
        self.assertTrue(Path(destination).is_file())
        controller.mutate("create_primitive", {
            "kind": "sphere", "radius": 1, "center": [20, 0, 0], "name": "extra",
        })
        self.assertEqual(window.tree.topLevelItem(0).childCount(), 2)
        controller.open(destination)
        self.assertEqual(window.tree.topLevelItem(0).childCount(), 1)
        self.assertEqual(
            controller.application.execute("snapshot")["value"]["bodies"][0]["name"],
            "gui-box",
        )

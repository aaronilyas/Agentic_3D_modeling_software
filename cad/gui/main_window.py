"""Agent-first window. Modeling dialogs are not the architecture."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QLabel, QMainWindow,
    QTreeWidget, QTreeWidgetItem, QPlainTextEdit,
)

from cad.gui.agent_panel import AgentPanel
from cad.gui.controller import Controller
from cad.gui.references import ReferencePanel
from cad.gui.viewport import Viewport


class MainWindow(QMainWindow):
    def __init__(self, controller=None):
        super().__init__()
        app = QApplication.instance()
        if app is not None:
            from cad.gui.main import apply_palette
            apply_palette(app)
        self.setWindowTitle("Agentic CAD")
        self.resize(1280, 860)
        self.controller = controller if controller is not None else Controller(self)
        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.inspector = QPlainTextEdit(self)
        self.inspector.setReadOnly(True)
        self.validation = QPlainTextEdit(self)
        self.validation.setReadOnly(True)
        self.references = ReferencePanel(self)
        self.agent = AgentPanel(self)
        self._dock("Model Tree", self.tree, Qt.DockWidgetArea.LeftDockWidgetArea)
        self._dock("Inspector", self.inspector, Qt.DockWidgetArea.RightDockWidgetArea)
        self._dock("References", self.references, Qt.DockWidgetArea.RightDockWidgetArea)
        self._dock("Validation", self.validation, Qt.DockWidgetArea.BottomDockWidgetArea)
        self._dock("Design Assistant", self.agent, Qt.DockWidgetArea.BottomDockWidgetArea)
        self._menus()
        self.statusBar().addPermanentWidget(QLabel("mm"))
        self.statusBar().showMessage("Ready")
        self.controller.refreshed.connect(self._refresh)
        self.controller.failed.connect(self._error)
        self.controller.activity.connect(self.statusBar().showMessage)
        self.controller.busy_changed.connect(self.agent.set_busy)
        self.controller.refined.connect(self.agent.show_result)
        self.tree.itemSelectionChanged.connect(self._tree_selected)
        self.references.files_dropped.connect(self.controller.add_reference)
        self.agent.send_requested.connect(self.controller.refine)
        self.agent.cancel_requested.connect(self.controller.cancel)
        self.controller.refresh()

    def _dock(self, title, widget, area):
        dock = QDockWidget(title, self)
        dock.setObjectName(title)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _action(self, menu, label, callback, shortcut=None):
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def _menus(self):
        file_menu = self.menuBar().addMenu("&File")
        self._action(file_menu, "&New", self.controller.new_document, QKeySequence.StandardKey.New)
        self._action(file_menu, "&Open…", self._open, QKeySequence.StandardKey.Open)
        self._action(file_menu, "&Save…", self._save, QKeySequence.StandardKey.Save)
        self._action(file_menu, "Add reference image…", self._add_reference)
        file_menu.addSeparator()
        self._action(file_menu, "Export STEP…", lambda: self._export("step"))
        self._action(file_menu, "Export GLB…", lambda: self._export("glb"))
        self._action(file_menu, "Export STL…", lambda: self._export("stl"))
        file_menu.addSeparator()
        self._action(file_menu, "E&xit", self.close, QKeySequence.StandardKey.Quit)
        edit = self.menuBar().addMenu("&Edit")
        self._action(edit, "&Undo", lambda: self.controller.mutate("undo"), QKeySequence.StandardKey.Undo)
        self._action(edit, "&Redo", lambda: self.controller.mutate("redo"), "Ctrl+Shift+Z")
        self._action(edit, "&Delete selected", self.controller.delete_selected, "Delete")
        validate = self.menuBar().addMenu("&Validate")
        self._action(validate, "Validate model", self.controller.validate)
        toolbar = self.addToolBar("Tools")
        toolbar.setObjectName("Tools")
        self._action(toolbar, "Validate", self.controller.validate)

    def _refresh(self, snapshot):
        snapshot = snapshot or {}
        self.tree.blockSignals(True)
        self.tree.clear()
        root = QTreeWidgetItem(["Document"])
        self.tree.addTopLevelItem(root)
        meshes = []
        for number, body in enumerate(snapshot.get("bodies", []), 1):
            label = body.get("name") or f"Body {number}"
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.ItemDataRole.UserRole, body["ref"])
            root.addChild(item)
            if body["ref"] == self.controller.selected_ref:
                item.setSelected(True)
            result = self.controller.application.execute(
                "tessellate", {"ref": body["ref"], "chord_tolerance": 0.2},
            )
            if result.get("ok"):
                meshes.append(result["value"])
        root.setExpanded(True)
        self.tree.blockSignals(False)
        self.viewport.show_meshes(meshes, self.controller.selected_ref)
        self.references.synchronize(snapshot)
        self._show_inspector(snapshot)
        report = self.controller.validation
        if report is None:
            self.validation.setPlainText("Not validated")
        else:
            lines = [f"ready={report.get('ready')} revision={report.get('revision')}"]
            for finding in report.get("findings", []):
                lines.append(f"{finding.get('severity')}: {finding.get('code')} {finding.get('message')}")
            self.validation.setPlainText("\n".join(lines))

    def _show_inspector(self, snapshot):
        selected = next(
            (body for body in snapshot.get("bodies", []) if body["ref"] == self.controller.selected_ref),
            None,
        )
        if selected is None:
            self.inspector.setPlainText("No selection")
            return
        bounds = selected["bounds"]
        topology = selected["topology"]
        self.inspector.setPlainText(
            f"Reference: {selected['ref']}\n"
            f"Name: {selected.get('name') or '—'}\n"
            f"Feature: {selected.get('feature_id')}\n"
            f"Volume: {selected['volume']:.3f} mm³\n"
            f"Bounds: {bounds[0]} → {bounds[1]} mm\n"
            f"Closed: {topology['closed']}\n"
            f"Manifold: {topology['manifold']}\n"
            f"Components: {topology['components']}"
        )

    def _tree_selected(self):
        items = self.tree.selectedItems()
        ref = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        if ref == self.controller.selected_ref:
            return
        self.controller.selected_ref = ref or None
        self._show_inspector(self.controller.snapshot or {})

    def _error(self, code, message):
        self.agent.show_error(code, message)
        self.statusBar().showMessage(f"{code}: {message}")

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "CAD project (*.cadproj)")
        if path:
            self.controller.open(path)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save project", "model.cadproj", "CAD project (*.cadproj)")
        if path:
            self.controller.save(path)

    def _add_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, "Add reference image", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            self.controller.add_reference(path, "front")

    def _export(self, fmt):
        path, _ = QFileDialog.getSaveFileName(self, f"Export {fmt.upper()}", f"model.{fmt}", f"*.{fmt}")
        if path:
            self.controller.export(fmt, path)

    def closeEvent(self, event):
        self.viewport.close()
        self.controller.close()
        super().closeEvent(event)

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QDockWidget, QMessageBox, QFileDialog

from jewelry.gui.controller import Controller, _Job
from jewelry.gui.agent_controller import AgentController
from jewelry.gui.agent_panel import AgentPanel
from jewelry.gui.dialogs import OperationDialog, TITLES
from jewelry.gui.model_tree import ModelTree
from jewelry.gui.inspector import Inspector
from jewelry.gui.validation_panel import ValidationPanel
from jewelry.gui.viewport import Viewport


class MainWindow(QMainWindow):
    def __init__(self, controller=None):
        super().__init__()
        self.setWindowTitle('Jewelry CAD')
        self.resize(1280, 900)
        self.setMinimumSize(960, 680)
        self.setDockNestingEnabled(True)
        self._closing = False
        self._shutdown_done = False
        self._shutdown_job = None
        self.controller = controller if controller is not None else Controller(self)
        self.operation_dialog = None
        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)
        self.tree = ModelTree(self)
        self.inspector = Inspector(self)
        self.validation_panel = ValidationPanel(self)
        self.tree_dock = self._dock('Model Tree', self.tree, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.inspector_dock = self._dock('Inspector', self.inspector, Qt.DockWidgetArea.RightDockWidgetArea)
        self.validation_dock = self._dock('Manufacturing Validation', self.validation_panel, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.agent_controller = AgentController(self.controller, self)
        self.agent_panel = AgentPanel(self.agent_controller, self)
        self.agent_dock = self._dock('Design Assistant', self.agent_panel, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.tabifyDockWidget(self.validation_dock, self.agent_dock)
        self.agent_dock.raise_()
        self.actions = {}
        self._menus()
        self.resizeDocks([self.tree_dock, self.inspector_dock], [180, 280], Qt.Orientation.Horizontal)
        self.resizeDocks([self.validation_dock], [220], Qt.Orientation.Vertical)
        self.controller.refreshed.connect(self._refresh)
        self.controller.selection_changed.connect(self._selection)
        self.controller.failed.connect(self._error)
        self.controller.busy_changed.connect(self._busy)
        self.controller.activity.connect(self.statusBar().showMessage)
        self.controller.validation_changed.connect(self.validation_panel.display)
        self.validation_panel.validate_requested.connect(self.validate_model)
        self.validation_panel.profile_changed.connect(self.controller.set_profile)
        self.inspector.modify_requested.connect(lambda: self.open_operation('modify_ring'))
        self.tree.ref_selected.connect(self.controller.select)
        self.viewport.ref_selected.connect(self.controller.select)
        self.statusBar().showMessage('mm • Drag: orbit • Middle / Shift+drag: pan • Wheel: zoom • Right-click: select')
        self.controller.refresh()

    def _dock(self, title, widget, area):
        dock = QDockWidget(title, self)
        dock.setObjectName(title)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _action(self, menu, key, label, callback, shortcut=None, checkable=False):
        action = QAction(label, self)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        menu.addAction(action)
        self.actions[key] = action
        return action

    def _menus(self):
        file_menu = self.menuBar().addMenu('&File')
        self._action(file_menu, 'new', '&New', self.controller.new_document, QKeySequence.StandardKey.New)
        self._action(file_menu, 'exit', 'E&xit', self.close, QKeySequence.StandardKey.Quit)
        edit = self.menuBar().addMenu('&Edit')
        self._action(edit, 'undo', '&Undo', lambda: self.controller.mutate('undo'), QKeySequence.StandardKey.Undo)
        self._action(edit, 'redo', '&Redo', lambda: self.controller.mutate('redo'), 'Ctrl+Shift+Z')
        self._action(edit, 'delete', '&Delete selected', self.controller.delete_selected, 'Delete')
        modeling = self.menuBar().addMenu('&Modeling')
        for operation, title in TITLES.items():
            key = 'ring' if operation == 'create_ring' else operation
            self._action(modeling, key, title + '…', lambda checked=False, op=operation: self.open_operation(op))
        manufacturing = self.menuBar().addMenu('&Manufacturing')
        self._action(manufacturing, 'validate', 'Validate Model', self.validate_model)
        self._action(manufacturing, 'export', 'Export STL…', self.export_stl)
        view = self.menuBar().addMenu('&View')
        self._action(view, 'fit', '&Fit model', self.viewport.fit_model, 'F')
        self._action(view, 'reset', '&Reset camera', self.viewport.reset_camera)
        self._action(view, 'edges', 'Show mesh &edges', self.viewport.set_edges, checkable=True)
        view.addSeparator()
        for dock in (self.tree_dock, self.inspector_dock, self.validation_dock, self.agent_dock):
            view.addAction(dock.toggleViewAction())
        toolbar = self.addToolBar('Tools')
        toolbar.setObjectName('Tools')
        for key in ('ring', 'modify_ring', 'fit', 'undo', 'redo', 'validate', 'export'):
            toolbar.addAction(self.actions[key])

    def open_operation(self, operation):
        if self.controller.busy:
            return
        if self.operation_dialog is not None:
            self.operation_dialog.raise_()
            return
        dimensions = self.controller.ring_dimensions if operation == 'modify_ring' else None
        if operation != 'create_ring' and self.controller.selected_ref is None:
            return
        if operation == 'modify_ring' and dimensions is None:
            return
        dialog = OperationDialog(operation, dimensions, self)
        self.operation_dialog = dialog
        dialog.submitted.connect(lambda values: self.controller.create_ring(**values)
                                 if operation == 'create_ring' else self.controller.feature(operation, **values))
        self.controller.busy_changed.connect(dialog.set_busy)
        self.controller.completed.connect(dialog.completed)
        dialog.finished.connect(self._dialog_closed)
        dialog.open()

    def _dialog_closed(self, _result):
        self.operation_dialog = None

    def validate_model(self):
        self.validation_dock.show()
        self.validation_dock.raise_()
        self.controller.validate()

    def export_stl(self):
        if self.controller.busy or self.controller.selected_ref is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export selected object as STL (mm)', 'jewelry.stl', 'STL files (*.stl)')
        if path:
            self.controller.export_stl(path)

    def _refresh(self, snapshot, meshes):
        self.tree.synchronize(snapshot)
        self.viewport.synchronize(meshes)
        self._update_actions()

    def _selection(self, ref, info):
        self.tree.select_ref(ref)
        self.viewport.select_ref(ref)
        self.inspector.inspect(ref, info, self.controller.ring_dimensions)
        self._update_actions()

    def _update_actions(self):
        controller = self.controller
        idle = not controller.busy
        selected = controller.selected_ref is not None
        for key in ('new', 'ring'):
            self.actions[key].setEnabled(idle)
        for key in ('cut_through_hole', 'cut_recess', 'add_setting', 'repeat_prongs', 'delete', 'export'):
            self.actions[key].setEnabled(idle and selected)
        self.actions['modify_ring'].setEnabled(idle and controller.ring_dimensions is not None)
        for key in ('undo', 'redo'):
            self.actions[key].setEnabled(idle and bool((controller.snapshot or {}).get(key)))
        self.actions['validate'].setEnabled(idle and bool(controller.references))
        self.validation_panel.validate_button.setEnabled(idle and bool(controller.references))
        self.inspector.modify_button.setEnabled(idle and controller.ring_dimensions is not None)

    def _busy(self, busy):
        self.tree.setEnabled(not busy)
        self.validation_panel.set_busy(busy)
        self._update_actions()
        if busy:
            self.statusBar().showMessage('Working…')
        elif self.statusBar().currentMessage() == 'Working…':
            self.statusBar().showMessage('Ready')

    def _error(self, code, message):
        self.statusBar().showMessage(f'{code}: {message}')
        if self.operation_dialog is not None:
            self.operation_dialog.show_error(code, message)
            return
        box = QMessageBox(QMessageBox.Icon.Warning, 'Jewelry CAD', f'{code}\n{message}', parent=self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.open()

    def closeEvent(self, event):
        if self._shutdown_done:
            super().closeEvent(event)
            return
        if self.controller.busy and not self.agent_controller.active:
            self.statusBar().showMessage('Please wait for the current operation to finish before closing.')
            event.ignore()
            return
        # Resource teardown can wait for process exit; keep that off the Qt thread.
        if self.agent_controller.session is not None or self.agent_controller.active:
            event.ignore()
            if not self._closing:
                self._closing = True
                self.setEnabled(False)
                self.statusBar().showMessage('Closing agent and CAD resources…')
                self._shutdown_job = _Job(self.controller.close)
                self._shutdown_job.signals.finished.connect(self._closed)
                QThreadPool.globalInstance().start(self._shutdown_job)
            return
        self.controller.close()
        self.viewport.shutdown()
        self._shutdown_done = True
        super().closeEvent(event)

    def _closed(self, _result):
        self.viewport.shutdown()
        self._shutdown_done = True
        self._shutdown_job = None
        self.close()

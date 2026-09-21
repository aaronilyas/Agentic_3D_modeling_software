from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QDockWidget, QMessageBox

from jewelry.gui.controller import Controller
from jewelry.gui.model_tree import ModelTree
from jewelry.gui.inspector import Inspector
from jewelry.gui.viewport import Viewport


class MainWindow(QMainWindow):
    def __init__(self, controller=None):
        super().__init__()
        self.setWindowTitle('Jewelry CAD')
        self.resize(1200, 800)
        self.controller = controller if controller is not None else Controller(self)
        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)
        self.tree = ModelTree(self)
        self.inspector = Inspector(self)
        self.tree_dock = self._dock('Model Tree', self.tree, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.inspector_dock = self._dock('Inspector', self.inspector, Qt.DockWidgetArea.RightDockWidgetArea)
        self.actions = {}
        self._menus()
        self.controller.refreshed.connect(self._refresh)
        self.controller.selection_changed.connect(self._selection)
        self.controller.failed.connect(self._error)
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
        self._action(edit, 'redo', '&Redo', lambda: self.controller.mutate('redo'), QKeySequence.StandardKey.Redo)
        self._action(edit, 'delete', '&Delete selected', self.controller.delete_selected, QKeySequence.StandardKey.Delete)
        view = self.menuBar().addMenu('&View')
        self._action(view, 'fit', '&Fit model', self.viewport.fit_model, 'F')
        self._action(view, 'reset', '&Reset camera', self.viewport.reset_camera)
        self._action(view, 'edges', 'Show mesh &edges', self.viewport.set_edges, checkable=True)
        view.addSeparator()
        view.addAction(self.tree_dock.toggleViewAction())
        view.addAction(self.inspector_dock.toggleViewAction())
        toolbar = self.addToolBar('Tools')
        toolbar.setObjectName('Tools')
        self._action(toolbar, 'ring', 'Create Canonical Ring', self.controller.create_ring)
        toolbar.addAction(self.actions['fit'])
        toolbar.addAction(self.actions['undo'])
        toolbar.addAction(self.actions['redo'])

    def _refresh(self, snapshot, meshes):
        self.tree.synchronize(snapshot)
        self.viewport.synchronize(meshes)
        self.actions['undo'].setEnabled(bool(snapshot and snapshot['undo']))
        self.actions['redo'].setEnabled(bool(snapshot and snapshot['redo']))

    def _selection(self, ref, info):
        self.tree.select_ref(ref)
        self.viewport.select_ref(ref)
        self.inspector.inspect(ref, info)
        self.actions['delete'].setEnabled(ref is not None)

    def _error(self, code, message):
        self.statusBar().showMessage(f'{code}: {message}')
        box = QMessageBox(QMessageBox.Icon.Warning, 'Jewelry CAD', f'{code}\n{message}', parent=self)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.open()

    def closeEvent(self, event):
        self.controller.close()
        self.viewport.shutdown()
        super().closeEvent(event)

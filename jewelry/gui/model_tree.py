from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem


class ModelTree(QTreeWidget):
    ref_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setIndentation(16)
        self.setUniformRowHeights(True)
        self.setAnimated(False)
        self.items_by_ref = {}
        self.document_item = None
        self.itemSelectionChanged.connect(self._selection)

    def synchronize(self, snapshot):
        with QSignalBlocker(self):
            self.clear()
            self.items_by_ref.clear()
            root = QTreeWidgetItem(['Document'])
            root.setData(0, Qt.ItemDataRole.UserRole, None)
            self.addTopLevelItem(root)
            self.document_item = root
            for number, body in enumerate((snapshot or {}).get('bodies', []), 1):
                label = 'Ring' if body.get('kind') == 'annulus' else 'Body'
                item = QTreeWidgetItem([f'{label} {number}'])
                item.setData(0, Qt.ItemDataRole.UserRole, body['ref'])
                root.addChild(item)
                self.items_by_ref[body['ref']] = item
            root.setExpanded(True)

    def select_ref(self, ref):
        with QSignalBlocker(self):
            self.clearSelection()
            item = self.items_by_ref.get(ref)
            self.setCurrentItem(item)

    def _selection(self):
        items = self.selectedItems()
        ref = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        self.ref_selected.emit(ref or None)

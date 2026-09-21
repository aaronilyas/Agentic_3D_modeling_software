from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class ModelTree(QTreeWidget):
    ref_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabel('Document objects')
        self.items_by_ref = {}
        self.itemSelectionChanged.connect(self._selection)

    def synchronize(self, snapshot):
        with QSignalBlocker(self):
            self.clear()
            self.items_by_ref.clear()
            for number, body in enumerate((snapshot or {}).get('bodies', []), 1):
                label = 'Ring' if body.get('kind') == 'annulus' else 'Body'
                item = QTreeWidgetItem([f'{label} {number}'])
                item.setData(0, Qt.ItemDataRole.UserRole, body['ref'])
                item.setToolTip(0, body['ref'])
                self.addTopLevelItem(item)
                self.items_by_ref[body['ref']] = item

    def select_ref(self, ref):
        with QSignalBlocker(self):
            self.clearSelection()
            self.setCurrentItem(self.items_by_ref.get(ref))

    def _selection(self):
        items = self.selectedItems()
        self.ref_selected.emit(items[0].data(0, Qt.ItemDataRole.UserRole) if items else None)

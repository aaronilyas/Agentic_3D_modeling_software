"""Project reference images. Dropped files are copied into the document."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget, QVBoxLayout, QWidget


class ReferencePanel(QWidget):
    files_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.list = QListWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)

    def synchronize(self, snapshot):
        self.list.clear()
        for asset in (snapshot or {}).get("assets", []):
            scale = "calibrated" if asset.get("calibration") else "unknown"
            self.list.addItem(
                f"{asset.get('role', 'other')}: {asset.get('label') or asset.get('filename')} "
                f"{asset.get('width')}×{asset.get('height')} {scale}"
            )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.files_dropped.emit(path)
        event.acceptProposedAction()

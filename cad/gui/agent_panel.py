"""Refinement controls. The transcript shows structured loop results."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class AgentPanel(QWidget):
    send_requested = Signal(str)
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.prompt = QPlainTextEdit(self)
        self.prompt.setPlaceholderText("Describe the part. The loop inspects, models, measures, and renders.")
        self.prompt.setFixedHeight(72)
        self.transcript = QPlainTextEdit(self)
        self.transcript.setReadOnly(True)
        self.send_button = QPushButton("Send", self)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setEnabled(False)
        row = QHBoxLayout()
        row.addWidget(self.send_button)
        row.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.prompt)
        layout.addLayout(row)
        layout.addWidget(self.transcript)
        self.send_button.clicked.connect(self._send)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)

    def _send(self):
        text = self.prompt.toPlainText().strip()
        if text:
            self.send_requested.emit(text)

    def show_result(self, value):
        mismatches = value.get("mismatches") or []
        self.transcript.appendPlainText(
            f"{value.get('status')}: {value.get('reason')} "
            f"({value.get('iterations')} iterations, revision {value.get('revision')})"
        )
        if mismatches:
            self.transcript.appendPlainText(f"mismatches: {mismatches}")

    def show_error(self, code, message):
        self.transcript.appendPlainText(f"{code}: {message}")

    def set_busy(self, busy):
        self.send_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.prompt.setEnabled(not busy)

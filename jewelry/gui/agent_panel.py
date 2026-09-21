"""Compact CAD transcript. This widget never executes backend commands."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
                               QLineEdit, QPushButton, QLabel, QComboBox)


class AgentPanel(QWidget):
    def __init__(self, agent_controller, parent=None):
        super().__init__(parent)
        self.agent_controller = agent_controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.agent = QComboBox()
        self.agent.addItem('Grok', 'grok')
        self.agent.addItem('Codex', 'codex')
        self.agent.setToolTip('Uses the selected CLI’s configured model and credentials')
        self.status = QLabel('Ready • configured CLI required')
        self.status.setAccessibleName('Agent connection and activity status')
        header.addWidget(self.agent)
        header.addWidget(self.status, 1)
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(agent_controller.cancel)
        header.addWidget(self.cancel_button)
        layout.addLayout(header)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setMaximumBlockCount(2000)
        self.transcript.setAccessibleName('Design Assistant conversation')
        layout.addWidget(self.transcript, 1)
        entry = QHBoxLayout()
        self.prompt = QLineEdit()
        self.prompt.setPlaceholderText('Describe a change to the current design…')
        self.prompt.setAccessibleName('Design prompt')
        self.send_button = QPushButton('Send')
        entry.addWidget(self.prompt, 1)
        entry.addWidget(self.send_button)
        layout.addLayout(entry)
        self.prompt.returnPressed.connect(self.send)
        self.send_button.clicked.connect(self.send)
        self.prompt.textChanged.connect(self._update_send)
        agent_controller.status.connect(self.status.setText)
        agent_controller.message.connect(self.append_message)
        agent_controller.controller.busy_changed.connect(self.set_busy)
        self._update_send()

    def append_message(self, role, text):
        self.transcript.appendPlainText(f'{role}\n{text}\n')
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())

    def _update_send(self):
        self.send_button.setEnabled(not self.agent_controller.controller.busy and bool(self.prompt.text().strip()))

    def set_busy(self, busy):
        self.agent.setEnabled(not busy)
        self.prompt.setEnabled(not busy)
        self.cancel_button.setEnabled(busy and self.agent_controller.active)
        self._update_send()

    def send(self):
        if self.agent_controller.send(self.prompt.text(), self.agent.currentData()):
            self.prompt.clear()

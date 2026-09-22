"""Presentation of backend manufacturing reports and supported profile settings."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from jewelry.gui.controller import DEFAULT_PROFILE
from jewelry.gui.dialogs import number_control


class ValidationPanel(QWidget):
    validate_requested = Signal()
    profile_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.status = QLabel('Not validated — run Validate Model before export.')
        self.status.setWordWrap(True)
        header.addWidget(self.status, 1)
        self.validate_button = QPushButton('Validate Model')
        self.validate_button.clicked.connect(self.validate_requested)
        header.addWidget(self.validate_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        self.settings = QGroupBox('Advanced manufacturing profile')
        self.settings.setCheckable(True)
        self.settings.setChecked(False)
        settings_layout = QVBoxLayout(self.settings)
        self.settings_content = QWidget()
        form = QFormLayout(self.settings_content)
        form.addRow(QLabel('MVP single piece • mm'))
        self.fields = {}
        for key, title, suffix in [('min_wall', 'Minimum wall', ' mm'),
                                   ('min_prong', 'Minimum prong', ' mm'),
                                   ('max_components', 'Maximum components', '')]:
            field = number_control(key, DEFAULT_PROFILE[key], 1 if key == 'max_components' else .001, 1000, suffix)
            field.valueChanged.connect(lambda: self.profile_changed.emit(self.profile()))
            self.fields[key] = field
            form.addRow(title, field)
        settings_layout.addWidget(self.settings_content)
        self.settings_content.hide()
        self.settings.toggled.connect(self.settings_content.setVisible)
        layout.addWidget(self.settings)
        self.findings = QTableWidget(0, 5)
        self.findings.setHorizontalHeaderLabels(['Severity', 'Code', 'Description', 'Measured', 'Required'])
        self.findings.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.findings.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.findings.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.findings.setMinimumHeight(72)
        layout.addWidget(self.findings, 1)
        note = QLabel('Validation covers the whole document. Export STL saves the selected object. Measurements use the profile’s mm units unless the finding describes a count.')
        note.setWordWrap(True)
        layout.addWidget(note)

    def profile(self):
        return DEFAULT_PROFILE | {key: field.value() for key, field in self.fields.items()}

    def display(self, report, stale=False):
        if report is None:
            self.status.setText('Not validated — run Validate Model before export.')
        elif stale:
            self.status.setText('Validation is stale — run Validate Model again. Previous findings below.')
        else:
            self.status.setText('Ready for export' if report['ready'] else 'Manufacturing issues found')
        findings = (report or {}).get('findings', [])
        self.findings.setRowCount(len(findings))
        for row, finding in enumerate(findings):
            for col, key in enumerate(('severity', 'code', 'message', 'measured', 'required')):
                value = finding.get(key, '—')
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.findings.setItem(row, col, item)
        self.findings.resizeRowsToContents()

    def set_busy(self, busy):
        self.validate_button.setEnabled(not busy)
        self.settings.setEnabled(not busy)

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QFormLayout, QLabel, QPushButton, QGroupBox, QVBoxLayout


class Inspector(QWidget):
    modify_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.addLayout(form)
        self.fields = {}
        for name in ('Bounds (mm)', 'Volume (mm³)', 'Closed', 'Manifold', 'Components', 'Ring dimensions (mm)'):
            label = QLabel('—')
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(name, label)
            self.fields[name] = label
        self.modify_button = QPushButton('Modify Ring…')
        self.modify_button.clicked.connect(self.modify_requested)
        layout.addWidget(self.modify_button)
        self.edit_note = QLabel('Select a plain ring to edit its dimensions. Feature solids support further jewelry operations.')
        self.edit_note.setWordWrap(True)
        layout.addWidget(self.edit_note)
        details = QGroupBox('Developer details')
        details.setCheckable(True)
        details.setChecked(False)
        reference = QLabel('—')
        reference.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.fields['Reference'] = reference
        detail_layout = QVBoxLayout(details)
        detail_layout.addWidget(reference)
        reference.hide()
        details.toggled.connect(reference.setVisible)
        layout.addWidget(details)
        layout.addStretch()

    def inspect(self, ref, info, dimensions=None):
        for field in self.fields.values():
            field.setText('—')
        self.modify_button.setEnabled(dimensions is not None)
        if ref is None or info is None:
            return
        self.fields['Reference'].setText(ref)
        bounds = ['(' + ', '.join(f'{n:.4g}' for n in point) + ')' for point in info['bounds']]
        self.fields['Bounds (mm)'].setText(' to\n'.join(bounds))
        self.fields['Volume (mm³)'].setText(f"{info['volume']:.6g}")
        topology = info['topology']
        for name in ('Closed', 'Manifold'):
            self.fields[name].setText('Yes' if topology[name.lower()] else 'No')
        self.fields['Components'].setText(str(topology['components']))
        if dimensions:
            self.fields['Ring dimensions (mm)'].setText(
                f"Inner radius: {dimensions['inner_radius']:g}\n"
                f"Outer radius: {dimensions['outer_radius']:g}\nWidth: {dimensions['width']:g}")

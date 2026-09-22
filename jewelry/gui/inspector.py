from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QFormLayout, QGroupBox, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)


class Inspector(QWidget):
    modify_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        self.fields = {}
        self._group('Geometry', ('Bounds (mm)', 'Volume (mm³)'), layout)
        self._group('Topology', ('Closed', 'Manifold', 'Components'), layout)
        self._ring_group(layout)
        details = QGroupBox('Developer details')
        details.setFlat(True)
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
        scroll.setWidget(host)
        outer.addWidget(scroll)

    def _value_label(self):
        label = QLabel('—')
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _group(self, title, names, layout):
        box = QGroupBox(title)
        box.setFlat(True)
        box.setCheckable(True)
        box.setChecked(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(8, 2, 4, 4)
        form.setSpacing(2)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for name in names:
            label = self._value_label()
            form.addRow(name, label)
            self.fields[name] = label
        inner = QVBoxLayout(box)
        inner.setContentsMargins(6, 2, 6, 4)
        inner.addWidget(content)
        box.toggled.connect(content.setVisible)
        layout.addWidget(box)

    def _ring_group(self, layout):
        box = QGroupBox('Ring')
        box.setFlat(True)
        box.setCheckable(True)
        box.setChecked(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 2, 4, 4)
        content_layout.setSpacing(4)
        form = QFormLayout()
        form.setSpacing(2)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        dimensions = self._value_label()
        form.addRow('Ring dimensions (mm)', dimensions)
        self.fields['Ring dimensions (mm)'] = dimensions
        content_layout.addLayout(form)
        self.modify_button = QPushButton('Modify Ring…')
        self.modify_button.clicked.connect(self.modify_requested)
        content_layout.addWidget(self.modify_button)
        self.edit_note = QLabel('Select a plain ring to edit its dimensions. Feature solids support further jewelry operations.')
        self.edit_note.setWordWrap(True)
        content_layout.addWidget(self.edit_note)
        inner = QVBoxLayout(box)
        inner.setContentsMargins(6, 2, 6, 4)
        inner.addWidget(content)
        box.toggled.connect(content.setVisible)
        layout.addWidget(box)

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

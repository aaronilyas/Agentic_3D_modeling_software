from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QFormLayout, QLabel


class Inspector(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)
        self.fields = {}
        for name in ('Reference', 'Bounds (mm)', 'Volume (mm³)', 'Closed', 'Manifold', 'Components'):
            label = QLabel('—')
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addRow(name, label)
            self.fields[name] = label

    def inspect(self, ref, info):
        for field in self.fields.values():
            field.setText('—')
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

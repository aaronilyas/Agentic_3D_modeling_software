"""Numeric operation forms. Geometry and manufacturing decisions stay in Application."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
    QSpinBox, QVBoxLayout,
)


TITLES = {
    'create_ring': 'Create Ring', 'modify_ring': 'Modify Ring',
    'cut_through_hole': 'Cut Through-Hole', 'cut_recess': 'Cut Stone Seat / Recess',
    'add_setting': 'Add Setting', 'repeat_prongs': 'Repeat Prongs',
}
# key, label, initial value, minimum, maximum, suffix
CENTER = [('center_x', 'Center X', 10, -10000, 10000, ' mm'),
          ('center_y', 'Center Y', 0, -10000, 10000, ' mm')]
RING = [('inner_radius', 'Inner radius', 8, .001, 10000, ' mm'),
        ('outer_radius', 'Outer radius', 9.5, .001, 10000, ' mm'),
        ('width', 'Width', 4, .001, 10000, ' mm')]
FIELDS = {
    'create_ring': RING, 'modify_ring': RING,
    'cut_through_hole': [*CENTER, ('radius', 'Hole radius', .2, .001, 10000, ' mm')],
    'cut_recess': [*CENTER, ('radius', 'Seat radius', .65, .001, 10000, ' mm'),
                  ('top_z', 'Top Z', 3, -10000, 10000, ' mm'),
                  ('depth', 'Depth (down from top)', .5, .001, 10000, ' mm')],
    'add_setting': [*CENTER, ('radius', 'Setting radius', 1.5, .001, 10000, ' mm'),
                    ('base_z', 'Base Z', 1.8, -10000, 10000, ' mm'),
                    ('height', 'Height', 1.2, .001, 10000, ' mm')],
    'repeat_prongs': [*CENTER, ('orbit_radius', 'Distance from center', 1, 0, 10000, ' mm'),
                      ('diameter', 'Prong diameter', .8, .001, 10000, ' mm'),
                      ('base_z', 'Base Z', 2.8, -10000, 10000, ' mm'),
                      ('height', 'Height', 2, .001, 10000, ' mm'),
                      ('count', 'Number of prongs', 4, 1, 64, ''),
                      ('start_angle_degrees', 'Start angle', 0, -360, 360, '°')],
}


def number_control(key, value, minimum, maximum, suffix, parent=None):
    control = QSpinBox(parent) if key in ('count', 'max_components') else QDoubleSpinBox(parent)
    if isinstance(control, QDoubleSpinBox):
        control.setDecimals(3)
        control.setSingleStep(.1)
    control.setRange(minimum, maximum)
    control.setSuffix(suffix)
    control.setValue(value)
    control.setObjectName(key)
    return control


class OperationDialog(QDialog):
    submitted = Signal(object)

    def __init__(self, operation, dimensions=None, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.setWindowTitle(TITLES[operation])
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        hints = {
            'create_ring': 'The ring is centered at the origin. All dimensions are in millimetres.',
            'modify_ring': 'Edit this plain ring. Dimension editing is unavailable after adding or cutting features.',
            'cut_through_hole': 'Cuts along Z through the full height of the selected object.',
            'cut_recess': 'Cuts a cylindrical stone seat downward from Top Z.',
            'add_setting': 'Adds a cylindrical setting along +Z. Overlap the band to make a connected piece.',
            'repeat_prongs': 'Adds vertical prongs evenly around the center. Overlap their bases with the setting.',
        }
        hint = QLabel(hints[operation] + (' X and Y use document coordinates.' if operation not in ('create_ring', 'modify_ring') else ''))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.form = QFormLayout()
        layout.addLayout(self.form)
        self.fields = {}
        for key, label, value, minimum, maximum, suffix in FIELDS[operation]:
            value = (dimensions or {}).get(key, value)
            if operation == 'cut_through_hole' and key == 'center_x':
                value = -8.75
            control = number_control(key, value, minimum, maximum, suffix, self)
            self.fields[key] = control
            self.form.addRow(label, control)
            control.valueChanged.connect(self._check)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(TITLES[operation])
        self.buttons.accepted.connect(lambda: self.submitted.emit(self.parameters()))
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._busy = False
        self._check()

    def parameters(self):
        values = {key: field.value() for key, field in self.fields.items()}
        if 'center_x' in values:
            values['center'] = [values.pop('center_x'), values.pop('center_y')]
        return values

    def _check(self):
        if not hasattr(self, 'buttons'):
            return
        values = self.parameters()
        valid = 'inner_radius' not in values or values['outer_radius'] > values['inner_radius']
        self.error.setText('Outer radius must be greater than inner radius.' if not valid else '')
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid and not self._busy)

    def set_busy(self, busy):
        self._busy = busy
        for field in self.fields.values():
            field.setEnabled(not busy)
        self._check()

    def show_error(self, code, message):
        self.error.setText(f'{code}: {message}')

    def completed(self, operation, success):
        if operation == self.operation and success:
            self.accept()

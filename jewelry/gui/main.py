"""Desktop entry point. Backend imports do not require GUI dependencies."""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from jewelry.gui.main_window import MainWindow


def apply_palette(app):
    """Dark neutral palette. The viewport stays darker than these panels."""
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: '#2e343c', QPalette.ColorRole.WindowText: '#e8eaed',
        QPalette.ColorRole.Base: '#252b33', QPalette.ColorRole.AlternateBase: '#343c46',
        QPalette.ColorRole.Text: '#e8eaed', QPalette.ColorRole.Button: '#3a424c',
        QPalette.ColorRole.ButtonText: '#e8eaed', QPalette.ColorRole.Highlight: '#9a5824',
        QPalette.ColorRole.HighlightedText: '#fff8f0', QPalette.ColorRole.PlaceholderText: '#9aa3ad',
        QPalette.ColorRole.Light: '#4a545f', QPalette.ColorRole.Midlight: '#3e4752',
        QPalette.ColorRole.Mid: '#323a44', QPalette.ColorRole.Dark: '#1c222a',
        QPalette.ColorRole.Shadow: '#12161b', QPalette.ColorRole.ToolTipBase: '#2a3038',
        QPalette.ColorRole.ToolTipText: '#e8eaed', QPalette.ColorRole.Link: '#d3924a',
    }.items():
        palette.setColor(role, QColor(color))
    disabled_text = QColor('#c5ced6')
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText, QPalette.ColorRole.PlaceholderText,
                 QPalette.ColorRole.HighlightedText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor('#2a3038'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Window, QColor('#2a3038'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor('#222830'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor('#6a4a30'))
    app.setPalette(palette)


def main():
    qt = QApplication(sys.argv)
    qt.setApplicationName('Jewelry CAD')
    qt.setStyle('Fusion')
    apply_palette(qt)
    window = MainWindow()
    qt.aboutToQuit.connect(window.controller.close)
    window.show()
    try:
        return qt.exec()
    finally:
        window.controller.close()

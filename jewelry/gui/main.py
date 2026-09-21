"""Desktop entry point. Backend imports do not require GUI dependencies."""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from jewelry.gui.main_window import MainWindow


def main():
    qt = QApplication(sys.argv)
    qt.setApplicationName('Jewelry CAD')
    qt.setStyle('Fusion')
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: '#30363e', QPalette.ColorRole.WindowText: '#e6e9ed',
        QPalette.ColorRole.Base: '#222830', QPalette.ColorRole.AlternateBase: '#343c46',
        QPalette.ColorRole.Text: '#e6e9ed', QPalette.ColorRole.Button: '#3b444f',
        QPalette.ColorRole.ButtonText: '#e6e9ed', QPalette.ColorRole.Highlight: '#456b90',
        QPalette.ColorRole.HighlightedText: '#ffffff', QPalette.ColorRole.PlaceholderText: '#a2acb8',
    }.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor('#87919e'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor('#87919e'))
    qt.setPalette(palette)
    window = MainWindow()
    qt.aboutToQuit.connect(window.controller.close)
    window.show()
    try:
        return qt.exec()
    finally:
        window.controller.close()

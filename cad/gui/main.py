"""Launch the generic CAD desktop."""

import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from cad.gui.main_window import MainWindow


def apply_palette(app: QApplication) -> None:
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1c222a"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e8eaed"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#252b33"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e8eaed"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2a3038"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e8eaed"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#9a5824"))
    app.setPalette(palette)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    apply_palette(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

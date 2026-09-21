"""Desktop entry point. Backend imports do not require GUI dependencies."""
import sys
from PySide6.QtWidgets import QApplication
from jewelry.gui.main_window import MainWindow


def main():
    qt = QApplication(sys.argv)
    qt.setApplicationName('Jewelry CAD')
    window = MainWindow()
    qt.aboutToQuit.connect(window.controller.close)
    window.show()
    try:
        return qt.exec()
    finally:
        window.controller.close()

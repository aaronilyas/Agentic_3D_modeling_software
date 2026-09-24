"""Viewport meshes are disposable. The document remains the geometry authority."""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class Viewport(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.plotter = None
        self._actors = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QLabel("3D viewport unavailable", self)
        self.placeholder.setStyleSheet("color: #9aa3ad; background: #202832;")
        layout.addWidget(self.placeholder)
        try:
            from PySide6.QtGui import QGuiApplication
            if QGuiApplication.platformName() == "offscreen":
                raise RuntimeError("offscreen Qt has no OpenGL viewport")
            import pyvista as pv
            from pyvistaqt import QtInteractor
            self._pv = pv
            self.plotter = QtInteractor(self, auto_update=False)
            self.plotter.set_background("#202832")
            self.plotter.enable_trackball_style()
            layout.addWidget(self.plotter)
            self.placeholder.hide()
        except Exception as exc:
            self.plotter = None
            self.placeholder.setText(f"3D viewport unavailable: {exc}")

    def show_meshes(self, meshes, selected):
        if self.plotter is None:
            return
        try:
            self._draw(meshes, selected)
        except Exception as exc:
            self.placeholder.setText(f"3D viewport unavailable: {exc}")
            self.placeholder.show()

    def _draw(self, meshes, selected):
        self.plotter.clear()
        self._actors = {}
        for mesh in meshes:
            if not mesh["triangles"]:
                continue
            faces = []
            for triangle in mesh["triangles"]:
                faces.extend((3, *triangle))
            poly = self._pv.PolyData(mesh["vertices"], faces)
            color = "#ffcb4d" if mesh["ref"] == selected else "#c8b078"
            self._actors[mesh["ref"]] = self.plotter.add_mesh(poly, color=color, smooth_shading=True)
        self.plotter.reset_camera()
        self.plotter.render()

    def close(self):
        if self.plotter is not None:
            self.plotter.close()
        super().close()

"""VTK actors are disposable render state, never CAD geometry."""
import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout
import pyvista as pv
from pyvistaqt import QtInteractor


class Viewport(QWidget):
    ref_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plotter = QtInteractor(self, auto_update=False)
        layout.addWidget(self.plotter)
        self.actors_by_ref = {}
        self.edges = False
        self.plotter.set_background('#202832')
        self.plotter.enable_trackball_style()
        self.plotter.add_axes()
        self.plotter.enable_mesh_picking(
            callback=self._picked, use_actor=True, show=False,
            show_message=False, left_clicking=False,
        )
        self.reset_camera()

    def synchronize(self, meshes):
        was_empty = not self.actors_by_ref
        for actor in self.actors_by_ref.values():
            self.plotter.remove_actor(actor, reset_camera=False, render=False)
        self.actors_by_ref.clear()
        for ref, mesh in meshes.items():
            triangles = np.asarray(mesh['triangles'], dtype=np.int64)
            faces = np.column_stack((np.full(len(triangles), 3), triangles))
            data = pv.PolyData(np.asarray(mesh['vertices'], dtype=float), faces)
            self.actors_by_ref[ref] = self.plotter.add_mesh(
                data, name=ref, color='#c8b078', show_edges=self.edges,
                edge_color='#343b45', reset_camera=False, render=False,
            )
        if was_empty and meshes:
            self.fit_model()
        self.plotter.render()

    def _picked(self, actor):
        ref = next((ref for ref, candidate in self.actors_by_ref.items() if candidate is actor), None)
        self.ref_selected.emit(ref)

    def select_ref(self, ref):
        for key, actor in self.actors_by_ref.items():
            actor.prop.color = '#ffcb4d' if key == ref else '#c8b078'
        self.plotter.render()

    def set_edges(self, enabled):
        self.edges = enabled
        for actor in self.actors_by_ref.values():
            actor.prop.show_edges = enabled
        self.plotter.render()

    def fit_model(self):
        if self.actors_by_ref:
            self.plotter.reset_camera()

    def reset_camera(self):
        self.plotter.view_isometric()
        self.plotter.camera.up = (0, 0, 1)
        self.fit_model()

    def shutdown(self):
        self.plotter.close()

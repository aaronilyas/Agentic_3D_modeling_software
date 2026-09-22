"""VTK actors are disposable render state, never CAD geometry."""
import numpy as np
from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout
import pyvista as pv
from pyvistaqt import QtInteractor
from vtkmodules.vtkInteractionWidgets import (
    vtkCameraOrientationRepresentation,
    vtkCameraOrientationWidget,
)
from vtkmodules.vtkRenderingCore import vtkActor, vtkPropCollection

# Logical pixels. SquareResize divides by the render window's device-pixel size.
_LOGICAL_SIZE_PX = 96
_LOGICAL_PAD_PX = 16


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
        self.orientation_widget = None
        self.plotter.set_background('#202832')
        self.plotter.enable_trackball_style()
        self.plotter.enable_mesh_picking(
            callback=self._picked, use_actor=True, show=False,
            show_message=False, left_clicking=False,
        )
        self.orientation_widget = self._create_orientation_widget()
        self.reset_camera()

    def _create_orientation_widget(self):
        widget = vtkCameraOrientationWidget()
        widget.SetParentRenderer(self.plotter.renderer)
        widget.SetInteractor(self.plotter.iren.interactor)
        representation = vtkCameraOrientationRepresentation()
        widget.SetRepresentation(representation)
        representation.SetShaftResolution(16)
        representation.SetNormalizedHandleDia(0.46)
        # Constructor bakes shaft radius 0.02 and never copies ShaftResolution
        # onto the tube, which is about one pixel inside a 96px gizmo.
        self._set_shaft_radius(representation, 0.09)
        container = representation.GetContainerProperty()
        container.SetColor(0.10, 0.11, 0.13)
        container.SetOpacity(0.32)
        overlay = widget.GetDefaultRenderer()
        overlay.SetPreserveColorBuffer(True)
        overlay.SetBackgroundAlpha(0.0)
        self._apply_orientation_metrics(widget)
        widget.On()
        return widget

    def _set_shaft_radius(self, representation, radius):
        props = vtkPropCollection()
        representation.GetActors(props)
        props.InitTraversal()
        sides = max(int(representation.GetShaftResolution()), 3)
        prop = props.GetNextProp()
        while prop is not None:
            actor = vtkActor.SafeDownCast(prop)
            mapper = actor.GetMapper() if actor is not None else None
            algorithm = mapper.GetInputAlgorithm() if mapper is not None else None
            if algorithm is not None and algorithm.IsA('vtkTubeFilter'):
                algorithm.SetRadius(radius)
                algorithm.SetNumberOfSides(sides)
            prop = props.GetNextProp()

    def _apply_orientation_metrics(self, widget=None):
        widget = self.orientation_widget if widget is None else widget
        plotter = getattr(self, 'plotter', None)
        if widget is None or plotter is None or getattr(plotter, '_closed', False):
            return
        representation = widget.GetRepresentation()
        if representation is None:
            return
        dpr = float(plotter.devicePixelRatioF())
        size = round(_LOGICAL_SIZE_PX * dpr)
        pad = round(_LOGICAL_PAD_PX * dpr)
        representation.SetSize(int(size), int(size))
        representation.SetPadding(int(pad), int(pad))
        representation.AnchorToLowerLeft()
        representation.SetXAxisColor(1.0, 0.0, 0.0)
        representation.SetYAxisColor(0.0, 1.0, 0.0)
        representation.SetZAxisColor(0.0, 0.0, 1.0)
        widget.SetAnimate(False)
        widget.SetShouldResetCamera(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_orientation_metrics()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self._apply_orientation_metrics()

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
        self._release_orientation_widget()
        plotter = getattr(self, 'plotter', None)
        if plotter is not None and not getattr(plotter, '_closed', False):
            plotter.close()

    def _release_orientation_widget(self):
        widget = getattr(self, 'orientation_widget', None)
        if widget is None:
            return
        if widget.GetEnabled():
            widget.Off()
        if widget.GetParentRenderer() is not None:
            widget.SetParentRenderer(None)
        if widget.GetInteractor() is not None:
            widget.SetInteractor(None)

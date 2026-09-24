"""Factory for an isolated generic CAD application."""

from cad.application import Application
from cad.geometry.occ import OccBackend


def create_application() -> Application:
    return Application(OccBackend())

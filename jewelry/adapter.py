"""Test-adapter factory. Returns an isolated application per call."""

from jewelry.application import Application


def create_application() -> Application:
    return Application()

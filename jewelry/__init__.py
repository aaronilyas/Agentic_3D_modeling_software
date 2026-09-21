"""Analytic jewelry CAD kernel and document application."""

from jewelry.deps import ensure_venv_site_packages

ensure_venv_site_packages()

from jewelry.adapter import create_application

__all__ = ["create_application"]

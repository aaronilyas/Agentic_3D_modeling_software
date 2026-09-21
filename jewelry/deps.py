"""Locate the project virtualenv so system python3 can import numpy/manifold3d."""

from __future__ import annotations

import sys
from pathlib import Path

_INSERTED = False


def ensure_venv_site_packages() -> None:
    global _INSERTED
    if _INSERTED:
        return
    root = Path(__file__).resolve().parent.parent
    lib = root / ".venv" / "lib"
    if not lib.is_dir():
        return
    for site in sorted(lib.glob("python3.*/site-packages"), reverse=True):
        path = str(site)
        if path not in sys.path:
            sys.path.insert(0, path)
        _INSERTED = True
        return

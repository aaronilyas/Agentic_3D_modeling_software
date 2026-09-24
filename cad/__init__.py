"""Generic parametric CAD core.

Units are millimetres. The coordinate system is right-handed with Z up.
The application document is the only geometry authority. Domain-specific parts
and manufacturing rules live outside this package.
"""

from cad.adapter import create_application

__all__ = ["create_application"]

"""Shared analytic inputs; no synthetic successful product results."""
import math

KERNEL_NUMERIC_TOL = 1e-7
GEOMETRY_ABS_TOL = 1e-6
VOLUME_REL_TOL = 1e-6
TESSELLATION_ERROR = 0.02
EXPORT_VOLUME_REL_TOL = 0.01
CANONICAL_RING = {'inner_radius': 8.0, 'outer_radius': 9.5, 'width': 4.0}
CANONICAL_VOLUME = 105 * math.pi
CANONICAL_BOUNDS = [[-9.5, -9.5, -2.0], [9.5, 9.5, 2.0]]
MANUFACTURING_PROFILE = {
    'id': 'mvp-single-piece', 'version': 1, 'units': 'mm',
    'min_wall': 1.0, 'min_prong': 0.8, 'max_components': 1,
}


def translation(tx, ty, tz):
    """Row-major 4x4 affine matrix; translation is the last column."""
    return [
        1.0, 0.0, 0.0, tx,
        0.0, 1.0, 0.0, ty,
        0.0, 0.0, 1.0, tz,
        0.0, 0.0, 0.0, 1.0,
    ]


def rotation_z(degrees):
    angle = math.radians(degrees)
    cosine, sine = math.cos(angle), math.sin(angle)
    return [
        cosine, -sine, 0.0, 0.0,
        sine, cosine, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def uniform_scale(factor):
    scale = float(factor)
    return [
        scale, 0.0, 0.0, 0.0,
        0.0, scale, 0.0, 0.0,
        0.0, 0.0, scale, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]



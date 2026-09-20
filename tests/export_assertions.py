"""Independent artifact assertions shared by export, ACP and end-to-end tests."""
from tests.fixtures import EXPORT_VOLUME_REL_TOL, GEOMETRY_ABS_TOL, TESSELLATION_ERROR
from tests.mesh_oracle import assert_printable_mesh, read_stl


def assert_stl(case, path, expected, tolerance=TESSELLATION_ERROR):
    mesh = read_stl(path)
    metrics = assert_printable_mesh(case, mesh)
    case.assertAlmostEqual(metrics['signed_volume'], expected['volume'],
                           delta=expected['volume']*EXPORT_VOLUME_REL_TOL)
    for actual, wanted in zip(metrics['bounds'], expected['bounds']):
        for value, target in zip(actual, wanted):
            case.assertAlmostEqual(value, target, delta=tolerance+GEOMETRY_ABS_TOL)
    return mesh

"""Direct adversarial meshes: fixtures only, never production results."""
import copy

TETRAHEDRON = {
    'vertices': [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    'triangles': [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
}


def _shifted_mesh(mesh, offset, reverse=False):
    dx, dy, dz = offset
    return {
        'vertices': [[x + dx, y + dy, z + dz] for x, y, z in mesh['vertices']],
        'triangles': [list(reversed(face)) if reverse else list(face)
                      for face in mesh['triangles']],
    }


def _join_meshes(*meshes):
    vertices, triangles, start = [], [], 0
    for mesh in meshes:
        vertices.extend([list(v) for v in mesh['vertices']])
        triangles.extend([[start + i for i in face] for face in mesh['triangles']])
        start = len(vertices)
    return {'vertices': vertices, 'triangles': triangles}


def _open_tetrahedron():
    mesh = copy.deepcopy(TETRAHEDRON)
    mesh['triangles'] = mesh['triangles'][:-1]
    return mesh


def _nonmanifold_edge_mesh():
    mesh = copy.deepcopy(TETRAHEDRON)
    mesh['vertices'].append([2.0, 0.5, 0.0])
    mesh['triangles'].append([0, 1, 4])
    return mesh


def _vertex_kiss_mesh():
    mesh = copy.deepcopy(TETRAHEDRON)
    mesh['vertices'].extend([[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]])
    mapping = [0, 4, 5, 6]
    mesh['triangles'].extend(
        [[mapping[i] for i in reversed(face)] for face in TETRAHEDRON['triangles']]
    )
    return mesh


def _self_intersecting_mesh():
    return _join_meshes(TETRAHEDRON, _shifted_mesh(TETRAHEDRON, (0.2, 0.2, 0.2)))


def _zero_thickness_sandwich():
    return {
        'vertices': [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0]],
        'triangles': [[0, 1, 2], [0, 2, 1]],
    }


def _coplanar_tetrahedron():
    return {
        'vertices': [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.4, 0.4, 0.0]],
        'triangles': [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
    }


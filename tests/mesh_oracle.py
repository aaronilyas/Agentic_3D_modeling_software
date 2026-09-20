"""Independent mesh measurements and STL reader used to check exported artifacts.

Exact welding is appropriate for serialized STL: adjacent triangles must emit
the same coordinates. No manufacturing or kernel tolerance repairs bad meshes.
"""
from collections import Counter, defaultdict
import math
from pathlib import Path
import struct


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def read_stl(path):
    """Read binary or ASCII STL without using the application's exporter."""
    data = Path(path).read_bytes()
    points = []
    if len(data) >= 84 and len(data) == 84 + 50*struct.unpack_from('<I', data, 80)[0]:
        for offset in range(84, len(data), 50):
            record = struct.unpack_from('<12fH', data, offset)
            points.extend(tuple(record[i:i+3]) for i in (3, 6, 9))
    else:
        source = data.decode('ascii')
        lines = [line.strip().split() for line in source.splitlines() if line.strip()]
        if not lines or lines[0][0] != 'solid' or lines[-1][0] != 'endsolid':
            raise ValueError('Not a complete ASCII or binary STL')
        cursor = 1
        while cursor < len(lines)-1:
            if cursor + 6 >= len(lines)-1:
                raise ValueError('Truncated STL facet')
            if lines[cursor][:2] != ['facet', 'normal'] or len(lines[cursor]) != 5:
                raise ValueError('Expected facet normal')
            if lines[cursor+1] != ['outer', 'loop']:
                raise ValueError('Expected outer loop')
            for row in lines[cursor+2:cursor+5]:
                if len(row) != 4 or row[0] != 'vertex':
                    raise ValueError('Expected three vertices')
                points.append(tuple(float(n) for n in row[1:]))
            if lines[cursor+5:cursor+7] != [['endloop'], ['endfacet']]:
                raise ValueError('Incomplete facet')
            cursor += 7
        if cursor != len(lines)-1:
            raise ValueError('Truncated STL')
    if not points or len(points) % 3:
        raise ValueError('STL has no complete triangles')
    vertices, triangles, indices = [], [], {}
    for i in range(0, len(points), 3):
        triangle = []
        for p in points[i:i+3]:
            if not all(math.isfinite(x) for x in p):
                raise ValueError('Non-finite STL coordinate')
            if p not in indices:
                indices[p] = len(vertices)
                vertices.append(p)
            triangle.append(indices[p])
        triangles.append(triangle)
    return {'vertices': vertices, 'triangles': triangles}


def measure_mesh(mesh):
    vertices, triangles = mesh['vertices'], mesh['triangles']
    if not vertices or not triangles:
        raise ValueError('Empty mesh')
    if any(len(v) != 3 or not all(math.isfinite(x) for x in v) for v in vertices):
        raise ValueError('Invalid vertices')
    # Tessellators may split indices at normals/UV seams. Weld identical
    # coordinates just as an STL reader does; never close a numeric gap.
    unique, mapping, remap = [], {}, []
    for vertex in vertices:
        key = tuple(vertex)
        if key not in mapping:
            mapping[key] = len(unique)
            unique.append(vertex)
        remap.append(mapping[key])
    welded = []
    for face in triangles:
        if len(face) != 3 or any(type(i) is not int or i < 0 or i >= len(vertices) for i in face):
            raise ValueError('Invalid triangle indices')
        welded.append([remap[i] for i in face])
    vertices, triangles = unique, welded
    edges, directed, adjacency = Counter(), Counter(), defaultdict(set)
    volume, degenerate = 0.0, 0
    used = set()
    for face in triangles:
        if len(face) != 3 or any(type(i) is not int or i < 0 or i >= len(vertices) for i in face):
            raise ValueError('Invalid triangle indices')
        a, b, c = (vertices[i] for i in face)
        area_vector = cross(sub(b, a), sub(c, a))
        degenerate += int(len(set(face)) != 3 or dot(area_vector, area_vector) == 0)
        volume += dot(a, cross(b, c))/6
        used.update(face)
        for u, v in zip(face, (*face[1:], face[0])):
            edges[tuple(sorted((u, v)))] += 1
            directed[(u, v)] += 1
            adjacency[u].add(v)
            adjacency[v].add(u)
    remaining, components = set(used), 0
    while remaining:
        components += 1
        stack = [remaining.pop()]
        while stack:
            for v in adjacency[stack.pop()]:
                if v in remaining:
                    remaining.remove(v)
                    stack.append(v)
    # Each vertex link must be one cycle (reject shells touching at a point).
    manifold_vertices = True
    for vertex in used:
        link = defaultdict(list)
        for face in triangles:
            if vertex in face:
                other = [i for i in face if i != vertex]
                if len(other) != 2:
                    manifold_vertices = False
                    continue
                u, v = other
                link[u].append(v)
                link[v].append(u)
        if not link or any(len(neighbors) != 2 for neighbors in link.values()):
            manifold_vertices = False
            continue
        seen, stack = set(), [next(iter(link))]
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                stack.extend(link[current])
        manifold_vertices &= len(seen) == len(link)
    return {
        'bounds': [[min(v[k] for v in vertices) for k in range(3)],
                   [max(v[k] for v in vertices) for k in range(3)]],
        'signed_volume': volume, 'components': components,
        'boundary_edges': sum(count == 1 for count in edges.values()),
        'nonmanifold_edges': sum(count > 2 for count in edges.values()),
        'consistent_orientation': all(directed[(u,v)] == directed[(v,u)] == 1 for u,v in edges),
        'manifold_vertices': manifold_vertices, 'degenerate_triangles': degenerate,
        'unused_vertices': len(vertices)-len(used),
    }


def assert_printable_mesh(case, mesh, components=1):
    metrics = measure_mesh(mesh)
    case.assertEqual(metrics['boundary_edges'], 0, metrics)
    case.assertEqual(metrics['nonmanifold_edges'], 0, metrics)
    case.assertTrue(metrics['manifold_vertices'], metrics)
    case.assertTrue(metrics['consistent_orientation'], metrics)
    case.assertEqual(metrics['degenerate_triangles'], 0, metrics)
    case.assertEqual(metrics['unused_vertices'], 0, metrics)
    case.assertEqual(metrics['components'], components, metrics)
    case.assertGreater(metrics['signed_volume'], 0, metrics)
    return metrics


def contains_point(mesh, point):
    """Generalized winding number; test probes must avoid the surface."""
    angle = 0.0
    for face in mesh['triangles']:
        a,b,c = [sub(mesh['vertices'][i], point) for i in face]
        la,lb,lc = [math.sqrt(dot(v,v)) for v in (a,b,c)]
        numerator = dot(a, cross(b,c))
        denominator = la*lb*lc + dot(a,b)*lc + dot(b,c)*la + dot(c,a)*lb
        angle += 2*math.atan2(numerator, denominator)
    return abs(angle) > 2*math.pi


def point_triangle_distance(point, a, b, c):
    """Closest distance to a triangle, including its edge and vertex regions."""
    ab,ac,ap = sub(b,a),sub(c,a),sub(point,a)
    d1,d2 = dot(ab,ap),dot(ac,ap)
    if d1 <= 0 and d2 <= 0:
        return math.sqrt(dot(ap,ap))
    bp = sub(point,b)
    d3,d4 = dot(ab,bp),dot(ac,bp)
    if d3 >= 0 and d4 <= d3:
        return math.sqrt(dot(bp,bp))
    vc = d1*d4-d3*d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1/(d1-d3)
        nearest = tuple(a[i]+v*ab[i] for i in range(3))
    else:
        cp = sub(point,c)
        d5,d6 = dot(ab,cp),dot(ac,cp)
        if d6 >= 0 and d5 <= d6:
            return math.sqrt(dot(cp,cp))
        vb = d5*d2-d1*d6
        if vb <= 0 and d2 >= 0 and d6 <= 0:
            w = d2/(d2-d6)
            nearest = tuple(a[i]+w*ac[i] for i in range(3))
        else:
            va = d3*d6-d5*d4
            if va <= 0 and d4-d3 >= 0 and d5-d6 >= 0:
                w = (d4-d3)/((d4-d3)+(d5-d6))
                nearest = tuple(b[i]+w*(c[i]-b[i]) for i in range(3))
            else:
                denominator = va+vb+vc
                if denominator == 0:
                    raise ValueError('Degenerate triangle')
                v,w = vb/denominator,vc/denominator
                nearest = tuple(a[i]+v*ab[i]+w*ac[i] for i in range(3))
    delta = sub(point,nearest)
    return math.sqrt(dot(delta,delta))


def point_mesh_distance(mesh, point):
    return min(point_triangle_distance(point, *(mesh['vertices'][i] for i in face))
               for face in mesh['triangles'])

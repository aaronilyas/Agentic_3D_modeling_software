"""Mesh topology diagnostics. Exact-coordinate welding only; no gap repair."""

from __future__ import annotations

from collections import Counter, defaultdict

from jewelry.errors import ContractError


def _as_point(value: object, name: str) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ContractError("INVALID_ARGUMENT", f"{name} must be a 3-vector")
    if len(value) != 3:
        raise ContractError("INVALID_ARGUMENT", f"{name} must have 3 components")
    try:
        point = (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError) as exc:
        raise ContractError("INVALID_ARGUMENT", f"{name} must be numeric") from exc
    return point


def _sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _orient(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
    d: tuple[float, float, float],
) -> float:
    return _dot(_sub(b, a), _cross(_sub(c, a), _sub(d, a)))


def parse_mesh(vertices: object, triangles: object) -> tuple[list[tuple[float, float, float]], list[list[int]]]:
    if not isinstance(vertices, (list, tuple)) or not isinstance(triangles, (list, tuple)):
        raise ContractError("INVALID_ARGUMENT", "vertices and triangles must be lists")
    parsed_vertices = [_as_point(vertex, f"vertices[{index}]") for index, vertex in enumerate(vertices)]
    parsed_triangles: list[list[int]] = []
    count = len(parsed_vertices)
    for index, face in enumerate(triangles):
        if not isinstance(face, (list, tuple)) or len(face) != 3:
            raise ContractError("INVALID_ARGUMENT", f"triangles[{index}] must have 3 indices")
        indices = []
        for item in face:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ContractError("INVALID_ARGUMENT", f"triangles[{index}] indices must be integers")
            if item < 0 or item >= count:
                raise ContractError("INVALID_ARGUMENT", f"triangles[{index}] index {item} is out of range")
            indices.append(item)
        parsed_triangles.append(indices)
    return parsed_vertices, parsed_triangles


def weld_exact(
    vertices: list[tuple[float, float, float]],
    triangles: list[list[int]],
) -> tuple[list[tuple[float, float, float]], list[list[int]]]:
    unique: list[tuple[float, float, float]] = []
    mapping: dict[tuple[float, float, float], int] = {}
    remap: list[int] = []
    for vertex in vertices:
        key = tuple(vertex)
        found = mapping.get(key)
        if found is None:
            found = len(unique)
            mapping[key] = found
            unique.append(vertex)
        remap.append(found)
    welded = [[remap[i] for i in face] for face in triangles]
    return unique, welded


def analyze_mesh(vertices: object, triangles: object) -> dict:
    parsed_vertices, parsed_triangles = parse_mesh(vertices, triangles)
    vertices, triangles = weld_exact(parsed_vertices, parsed_triangles)
    if not triangles:
        raise ContractError("INVALID_ARGUMENT", "mesh has no triangles")

    edges: Counter[tuple[int, int]] = Counter()
    directed: Counter[tuple[int, int]] = Counter()
    adjacency: dict[int, set[int]] = defaultdict(set)
    used: set[int] = set()
    volume = 0.0
    degenerate = 0
    coincident: dict[frozenset[int], int] = Counter()

    for face in triangles:
        coincident[frozenset(face)] += 1
        a, b, c = (vertices[i] for i in face)
        area = _cross(_sub(b, a), _sub(c, a))
        if len(set(face)) != 3 or _dot(area, area) == 0.0:
            degenerate += 1
        volume += _dot(a, _cross(b, c)) / 6.0
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
            for vertex in adjacency[stack.pop()]:
                if vertex in remaining:
                    remaining.remove(vertex)
                    stack.append(vertex)

    manifold_vertices = True
    for vertex in used:
        link: dict[int, list[int]] = defaultdict(list)
        for face in triangles:
            if vertex in face:
                other = [index for index in face if index != vertex]
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
        manifold_vertices = manifold_vertices and len(seen) == len(link)

    boundary_edges = sum(count == 1 for count in edges.values())
    nonmanifold_edges = sum(count > 2 for count in edges.values())
    closed = boundary_edges == 0 and nonmanifold_edges == 0
    return {
        "vertices": vertices,
        "triangles": triangles,
        "signed_volume": volume,
        "components": components,
        "boundary_edges": boundary_edges,
        "nonmanifold_edges": nonmanifold_edges,
        "manifold_vertices": manifold_vertices,
        "degenerate_triangles": degenerate,
        "coincident_faces": any(count > 1 for count in coincident.values()),
        "closed": closed,
        "self_intersecting": _self_intersecting(vertices, triangles),
    }


def mesh_findings(vertices: object, triangles: object) -> tuple[list[dict], dict]:
    metrics = analyze_mesh(vertices, triangles)
    findings: list[dict] = []
    if metrics["boundary_edges"]:
        findings.append(_finding("OPEN_SHELL", "mesh has boundary edges"))
    if metrics["nonmanifold_edges"] or not metrics["manifold_vertices"]:
        findings.append(_finding("NON_MANIFOLD", "mesh is not a 2-manifold"))
    if metrics["self_intersecting"]:
        findings.append(_finding("SELF_INTERSECTION", "triangles intersect away from shared edges"))
    zero_volume = metrics["closed"] and metrics["signed_volume"] == 0.0
    if metrics["degenerate_triangles"] or metrics["coincident_faces"] or zero_volume:
        findings.append(_finding("ZERO_THICKNESS", "mesh has collapsed or coincident faces"))
    return findings, metrics


def _finding(code: str, message: str) -> dict:
    return {"code": code, "message": message, "severity": "error"}


def _self_intersecting(
    vertices: list[tuple[float, float, float]],
    triangles: list[list[int]],
) -> bool:
    faces = [tuple(face) for face in triangles]
    count = len(faces)
    for i in range(count):
        a, b, c = (vertices[index] for index in faces[i])
        ia = set(faces[i])
        for j in range(i + 1, count):
            shared = ia.intersection(faces[j])
            if shared:
                continue
            d, e, f = (vertices[index] for index in faces[j])
            if _triangles_intersect((a, b, c), (d, e, f), 0):
                return True
    return False


def _triangles_intersect(
    tri_a: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
    tri_b: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
    shared_vertices: int,
) -> bool:
    a, b, c = tri_a
    d, e, f = tri_b
    da, db, dc = _orient(d, e, f, a), _orient(d, e, f, b), _orient(d, e, f, c)
    if _same_side(da, db, dc):
        return False
    dd, de, df_ = _orient(a, b, c, d), _orient(a, b, c, e), _orient(a, b, c, f)
    if _same_side(dd, de, df_):
        return False
    if da == db == dc == 0.0 or dd == de == df_ == 0.0:
        return _coplanar_overlap(tri_a, tri_b) and shared_vertices < 2
    edges_a = ((a, b), (b, c), (c, a))
    edges_b = ((d, e), (e, f), (f, d))
    for p, q in edges_a:
        if _segment_hits_triangle(p, q, d, e, f, shared_vertices):
            return True
    for p, q in edges_b:
        if _segment_hits_triangle(p, q, a, b, c, shared_vertices):
            return True
    return False


def _same_side(x: float, y: float, z: float) -> bool:
    return (x > 0.0 and y > 0.0 and z > 0.0) or (x < 0.0 and y < 0.0 and z < 0.0)


def _segment_hits_triangle(
    p: tuple[float, float, float],
    q: tuple[float, float, float],
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
    shared_vertices: int,
) -> bool:
    op, oq = _orient(a, b, c, p), _orient(a, b, c, q)
    if op == 0.0 and oq == 0.0:
        return False
    if op * oq > 0.0:
        return False
    o1, o2, o3 = _orient(p, q, a, b), _orient(p, q, b, c), _orient(p, q, c, a)
    if not ((o1 >= 0.0 and o2 >= 0.0 and o3 >= 0.0) or (o1 <= 0.0 and o2 <= 0.0 and o3 <= 0.0)):
        return False
    zeros = (o1 == 0.0) + (o2 == 0.0) + (o3 == 0.0) + (op == 0.0) + (oq == 0.0)
    if shared_vertices and zeros:
        return False
    return not (op == 0.0 and oq == 0.0)


def _coplanar_overlap(
    tri_a: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
    tri_b: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
) -> bool:
    normal = _cross(_sub(tri_a[1], tri_a[0]), _sub(tri_a[2], tri_a[0]))
    axis = max(range(3), key=lambda index: abs(normal[index]))
    keep = [index for index in range(3) if index != axis]
    a2 = tuple((p[keep[0]], p[keep[1]]) for p in tri_a)
    b2 = tuple((p[keep[0]], p[keep[1]]) for p in tri_b)
    return _triangles_overlap_2d(a2, b2)


def _triangles_overlap_2d(
    a: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    b: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> bool:
    for triangle in (a, b):
        other = b if triangle is a else a
        for i in range(3):
            p, q = triangle[i], triangle[(i + 1) % 3]
            edge = (q[0] - p[0], q[1] - p[1])
            axis = (-edge[1], edge[0])
            if _separated_2d(triangle, other, axis):
                return False
    return True


def _separated_2d(
    a: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    b: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    axis: tuple[float, float],
) -> bool:
    if axis[0] == 0.0 and axis[1] == 0.0:
        return False
    pa = [p[0] * axis[0] + p[1] * axis[1] for p in a]
    pb = [p[0] * axis[0] + p[1] * axis[1] for p in b]
    return max(pa) <= min(pb) or max(pb) <= min(pa)

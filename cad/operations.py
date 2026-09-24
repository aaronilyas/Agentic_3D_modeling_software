"""Small explicit registry of replay operations and their semantic inputs."""

from cad.errors import UnknownReference


def _profile(params, sketches):
    return sketches[params["sketch_id"]] if params.get("sketch_id") else params["profile"]

EDITABLE = {
    "box": {"size", "origin"},
    "cylinder": {"radius", "height", "origin"},
    "sphere": {"radius", "center"},
    "extrude": {"height"},
    "revolve": {"angle_degrees"},
    "fillet": {"radius"},
    "chamfer": {"distance"},
    "shell": {"thickness"},
    "hole": {"diameter", "depth", "position", "direction", "through"},
    "linear_pattern": {"spacing", "count", "direction"},
    "circular_pattern": {"count"},
}

BODY_INPUTS = {
    "boolean": ("left", "right"),
    "transform": ("target",),
    "fillet": ("target",),
    "chamfer": ("target",),
    "shell": ("target",),
    "hole": ("target",),
    "mirror": ("target",),
    "linear_pattern": ("target",),
    "circular_pattern": ("target",),
}
FEATURE_INPUTS = {"extrude": ("sketch_id",), "revolve": ("sketch_id",)}

REPLAY = {
    'box': lambda params, solids, sketches, backend: (
        backend.box(params['size'], params['origin'])
    ),
    'cylinder': lambda params, solids, sketches, backend: (
        backend.cylinder(params['radius'], params['height'], params['origin'])
    ),
    'sphere': lambda params, solids, sketches, backend: (
        backend.sphere(params['radius'], params['center'])
    ),
    'extrude': lambda params, solids, sketches, backend: (
        backend.extrude(_profile(params, sketches), params['height'])
    ),
    'revolve': lambda params, solids, sketches, backend: (
        backend.revolve(_profile(params, sketches), params['angle_degrees'])
    ),
    'sweep': lambda params, solids, sketches, backend: (
        backend.sweep(params['profile'], params['path'])
    ),
    'loft': lambda params, solids, sketches, backend: (
        backend.loft(params['profiles'], params['stations'])
    ),
    'boolean': lambda params, solids, sketches, backend: (
        backend.boolean(params['kind'], _solid(solids, params['left']), _solid(solids, params['right']))
    ),
    'transform': lambda params, solids, sketches, backend: (
        backend.transform(_solid(solids, params['target']), params['matrix'])
    ),
    'fillet': lambda params, solids, sketches, backend: (
        backend.fillet(_solid(solids, params['target']), params['radius'], params.get('edge_ids'), params.get('selector'))
    ),
    'chamfer': lambda params, solids, sketches, backend: (
        backend.chamfer(_solid(solids, params['target']), params['distance'], params.get('edge_ids'), params.get('selector'))
    ),
    'shell': lambda params, solids, sketches, backend: (
        backend.shell(_solid(solids, params['target']), params['thickness'], params.get('face_ids'))
    ),
    'hole': lambda params, solids, sketches, backend: (
        backend.hole(_solid(solids, params['target']), params['position'], params['direction'], params['diameter'], params.get('depth'), bool(params.get('through')))
    ),
    'mirror': lambda params, solids, sketches, backend: (
        backend.mirror(_solid(solids, params['target']), params['plane'], params.get('origin'), params.get('normal'), bool(params.get('keep_original')))
    ),
    'linear_pattern': lambda params, solids, sketches, backend: (
        backend.linear_pattern(_solid(solids, params['target']), params['direction'], params['spacing'], params['count'])
    ),
    'circular_pattern': lambda params, solids, sketches, backend: (
        backend.circular_pattern(_solid(solids, params['target']), params['origin'], params['direction'], params['count'])
    ),
    'duplicate': lambda params, solids, sketches, backend: (
        backend.import_brep_bytes(params['brep'])
    ),
}


def _solid(solids: dict, ref: str):
    try:
        return solids[ref]
    except KeyError as exc:
        raise UnknownReference(f"feature dependency {ref} is not a live solid") from exc

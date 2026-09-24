"""Typed MCP tool schemas. Lengths are millimetres unless a format says otherwise."""

from __future__ import annotations

_NUMBER = {"type": "number"}
_INT = {"type": "integer"}
_STRING = {"type": "string"}
_VEC2 = {"type": "array", "items": _NUMBER, "minItems": 2, "maxItems": 2}
_VEC3 = {
    "type": "array", "items": _NUMBER, "minItems": 3, "maxItems": 3,
    "description": "Millimetre vector. Axes are right-handed and Z is up.",
}
_REF = {"type": "string", "description": "Opaque body reference from snapshot.references"}
_PROFILE = {
    "type": "array",
    "items": _VEC2,
    "description": "Closed 2D profile in millimetres. Extrude profiles are XY; revolve profiles are (radius, z).",
}
_OBJECT = {"type": "object"}

def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOLS = {
    "snapshot": {
        "description": "Read the live document: references, feature graph, revision, and undo/redo. Lengths are mm.",
        "schema": _schema({}),
    },
    "inspect": {
        "description": "Exact volume, area, bounds, center, and topology for one body at the current revision.",
        "schema": _schema({"ref": _REF}, ["ref"]),
    },
    "rename": {
        "description": "Rename a body. This commits a revision and can be undone.",
        "schema": _schema({"ref": _REF, "name": _STRING}, ["ref", "name"]),
    },
    "duplicate": {
        "description": "Copy a body. The copy is a baked B-rep, not a live parametric link. Translation is millimetres.",
        "schema": _schema({"ref": _REF, "translation": _VEC3, "name": _STRING}, ["ref"]),
    },
    "delete": {
        "description": "Delete a body and the features that output it. Fails if another live body depends on it.",
        "schema": _schema({"ref": _REF}, ["ref"]),
    },
    "undo": {"description": "Undo the last committed document change.", "schema": _schema({})},
    "redo": {"description": "Redo the last undone document change.", "schema": _schema({})},
    "edit_feature": {
        "description": "Change parameters of one feature and rebuild its dependents. A failed rebuild leaves the document unchanged.",
        "schema": _schema({
            "feature_id": {"type": "string", "description": "Stable feature id from snapshot.features"},
            "parameters": {"type": "object", "description": "Partial parameter update. Lengths are millimetres."},
        }, ["feature_id", "parameters"]),
    },
    "create_primitive": {
        "description": "Create a box, cylinder, or sphere. Box origin is the minimum corner. Cylinder origin is the base center and extends +Z. Sphere uses center.",
        "schema": _schema({
            "kind": {"type": "string", "enum": ["box", "cylinder", "sphere"]},
            "size": _VEC3, "origin": _VEC3, "radius": _NUMBER, "height": _NUMBER, "center": _VEC3, "name": _STRING,
        }, ["kind"]),
    },
    "create_sketch": {
        "description": "Store a closed XY profile. A sketch is not a solid until extrude or revolve.",
        "schema": _schema({"profile": _PROFILE, "name": _STRING}, ["profile"]),
    },
    "extrude": {
        "description": "Extrude a sketch or an inline XY profile along +Z by height millimetres.",
        "schema": _schema({"sketch_id": _STRING, "profile": _PROFILE, "height": _NUMBER, "name": _STRING}, ["height"]),
    },
    "revolve": {
        "description": "Revolve a profile of [radius, z] points around Z. angle_degrees is in (0, 360].",
        "schema": _schema({
            "sketch_id": _STRING, "profile": _PROFILE, "angle_degrees": _NUMBER, "name": _STRING,
        }),
    },
    "sweep": {
        "description": "Sweep a 2D profile along a 3D polyline. The profile is in the plane normal to the first segment.",
        "schema": _schema({"profile": _PROFILE, "path": {"type": "array", "items": _VEC3}, "name": _STRING}, ["profile", "path"]),
    },
    "loft": {
        "description": "Loft XY profiles placed at station Z heights, in millimetres.",
        "schema": _schema({
            "profiles": {"type": "array", "items": _PROFILE},
            "stations": {"type": "array", "items": _NUMBER},
            "name": _STRING,
        }, ["profiles", "stations"]),
    },
    "boolean": {
        "description": "Union, subtract, or intersect two bodies. Returns a new body and keeps the operands.",
        "schema": _schema({
            "kind": {"type": "string", "enum": ["union", "subtract", "intersection"]},
            "left": _REF, "right": _REF, "name": _STRING,
        }, ["kind", "left", "right"]),
    },
    "transform": {
        "description": "Replace a body with its image under a row-major 4x4 affine matrix. Translation is the last column, in millimetres.",
        "schema": _schema({
            "ref": _REF,
            "matrix": {"type": "array", "items": _NUMBER, "minItems": 16, "maxItems": 16},
        }, ["ref", "matrix"]),
    },
    "fillet": {
        "description": "Fillet edges of a body. edge_ids require selection_revision equal to the current document revision. selector may be vertical or {kind: longest_vertical, count}.",
        "schema": _schema({
            "ref": _REF, "radius": _NUMBER, "edge_ids": {"type": "array", "items": _STRING},
            "selector": {}, "selection_revision": _INT,
        }, ["ref", "radius"]),
    },
    "chamfer": {
        "description": "Chamfer edges. Selection rules match fillet. distance is millimetres.",
        "schema": _schema({
            "ref": _REF, "distance": _NUMBER, "edge_ids": {"type": "array", "items": _STRING},
            "selector": {}, "selection_revision": _INT,
        }, ["ref", "distance"]),
    },
    "shell": {
        "description": "Hollow a solid by thickness millimetres. face_ids open those faces and require selection_revision.",
        "schema": _schema({
            "ref": _REF, "thickness": _NUMBER, "face_ids": {"type": "array", "items": _STRING},
            "selection_revision": _INT,
        }, ["ref", "thickness"]),
    },
    "hole": {
        "description": "Cut a cylindrical hole. position and direction are millimetres. through=true ignores depth and spans the body.",
        "schema": _schema({
            "ref": _REF, "position": _VEC3, "direction": _VEC3, "diameter": _NUMBER,
            "depth": _NUMBER, "through": {"type": "boolean"},
        }, ["ref", "position", "diameter"]),
    },
    "mirror": {
        "description": "Mirror a body through xy, yz, xz, or a custom plane. keep_original unions the mirror with the source.",
        "schema": _schema({
            "ref": _REF, "plane": {"type": "string", "enum": ["xy", "yz", "xz", "custom"]},
            "origin": _VEC3, "normal": _VEC3, "keep_original": {"type": "boolean"},
        }, ["ref"]),
    },
    "linear_pattern": {
        "description": "Fuse count copies of a body spaced along direction. count includes the original. spacing is millimetres.",
        "schema": _schema({
            "ref": _REF, "direction": _VEC3, "spacing": _NUMBER, "count": _INT, "name": _STRING,
        }, ["ref", "direction", "spacing", "count"]),
    },
    "circular_pattern": {
        "description": "Fuse count copies rotated about an axis. count includes the original.",
        "schema": _schema({
            "ref": _REF, "origin": _VEC3, "direction": _VEC3, "count": _INT, "name": _STRING,
        }, ["ref", "count"]),
    },
    "measure": {
        "description": "Exact measurement. With ref, returns volume, area, bounds, and center. With a and b, returns point distance. With point, also returns containment.",
        "schema": _schema({"ref": _REF, "point": _VEC3, "a": _VEC3, "b": _VEC3}),
    },
    "query_faces": {
        "description": "Semantic faces for this revision. Ids are not kernel indices. geom can be plane, cylinder, sphere, torus, or cone. order is largest or smallest.",
        "schema": _schema({
            "ref": _REF, "geom": _STRING, "order": {"type": "string", "enum": ["largest", "smallest"]},
            "nearest": _VEC3, "limit": _INT,
        }, ["ref"]),
    },
    "query_edges": {
        "description": "Semantic edges for this revision, including line and circle geometry, length, and adjacent face ids.",
        "schema": _schema({
            "ref": _REF, "geom": _STRING, "order": {"type": "string", "enum": ["largest", "smallest"]},
            "nearest": _VEC3, "limit": _INT,
        }, ["ref"]),
    },
    "section": {
        "description": "Intersect a body with a plane given by origin and normal. Returns section area and sampled loops in millimetres.",
        "schema": _schema({"ref": _REF, "origin": _VEC3, "normal": _VEC3}, ["ref", "origin", "normal"]),
    },
    "render_views": {
        "description": "Headless orthographic PNG renders. Views: isometric, front, rear, left, right, top, bottom. Images are evidence, not geometry.",
        "schema": _schema({
            "ref": _REF, "views": {"type": "array", "items": _STRING},
            "width": _INT, "height": _INT, "chord_tolerance": _NUMBER,
        }),
    },
    "render_selection": {
        "description": "Render a body and highlight face_ids from the same revision.",
        "schema": _schema({
            "ref": _REF, "face_ids": {"type": "array", "items": _STRING},
            "edge_ids": {"type": "array", "items": _STRING}, "selection_revision": _INT,
            "views": {"type": "array", "items": _STRING}, "width": _INT, "height": _INT,
        }, ["ref", "selection_revision"]),
    },
    "add_reference": {
        "description": "Copy a PNG or JPEG into the project as a reference image. role is front, side, top, perspective, detail, inspiration, or other.",
        "schema": _schema({
            "path": _STRING, "role": _STRING, "label": _STRING, "notes": _STRING, "camera_hint": _OBJECT,
        }, ["path"]),
    },
    "list_references": {
        "description": "List reference images stored in the document. These are project assets, not chat attachments.",
        "schema": _schema({}),
    },
    "inspect_reference": {
        "description": "Reference metadata, checksum, pixel size, and calibration. scale is calibrated or unknown.",
        "schema": _schema({"id": _STRING}, ["id"]),
    },
    "set_calibration": {
        "description": "Set a two-point scale: p1 and p2 are pixels and distance_mm is the real distance between them.",
        "schema": _schema({"id": _STRING, "p1": _VEC2, "p2": _VEC2, "distance_mm": _NUMBER}, ["id", "p1", "p2", "distance_mm"]),
    },
    "estimate_length": {
        "description": "Convert a pixel length using calibration. Uncalibrated images return millimeters null and kind uncalibrated.",
        "schema": _schema({"id": _STRING, "pixel_length": _NUMBER}, ["id", "pixel_length"]),
    },
    "validate": {
        "description": "Non-mutating geometry and manufacturing checks. ready=false is a finding, not a failed tool call. Profile names: geometry, fdm, sla, cnc, casting.",
        "schema": _schema({
            "scope": {"type": "string", "enum": ["geometry", "manufacturing", "all"]},
            "profile": {}, "ref": _REF,
        }),
    },
    "tessellate": {
        "description": "Derived triangle mesh for display. chord_tolerance is millimetres. This does not modify the B-rep.",
        "schema": _schema({"ref": _REF, "chord_tolerance": _NUMBER}, ["ref"]),
    },
    "list_export_formats": {
        "description": "Export formats. step is exact B-rep in mm. glb is a mesh in metres. stl and obj are meshes in mm with no assumption that STL stores units.",
        "schema": _schema({}),
    },
    "export": {
        "description": "Export one body. Manufacturing mode requires a current ready validation report. Preview mode requires valid geometry only. The document is not modified.",
        "schema": _schema({
            "ref": _REF, "path": _STRING,
            "format": {"type": "string", "enum": ["step", "glb", "stl", "obj", "blend"]},
            "mode": {"type": "string", "enum": ["preview", "manufacturing"]},
            "validation": _OBJECT, "chord_tolerance": _NUMBER,
        }, ["ref", "path", "format"]),
    },
    "save_project": {
        "description": "Write a versioned project archive. Features are the source of truth; B-rep bytes are a cache. Does not modify the document.",
        "schema": _schema({"path": _STRING}, ["path"]),
    },
    "open_project": {
        "description": "Replace the live document by replaying a project archive. The previous document remains available through undo.",
        "schema": _schema({"path": _STRING}, ["path"]),
    },
    "refine": {
        "description": "Run the bounded inspect, model, measure, render, and refine loop. A successful CAD operation does not by itself complete the request.",
        "schema": _schema({
            "request": _STRING, "goals": {"type": "array"}, "max_iterations": _INT,
        }, ["request"]),
    },
    "cancel_refine": {
        "description": "Request cancellation of the refinement loop. Committed operations remain undoable.",
        "schema": _schema({}),
    },
}

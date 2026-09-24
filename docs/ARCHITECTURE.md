# Architecture

The editable model is an ordered feature graph plus exact boundary representation.
Triangle meshes are derived for the viewport, headless renders, STL, OBJ, and glTF.
STEP is written from the B-Rep. A mesh is never converted back into a solid.
Internal units are millimetres; axes are right-handed with Z up.

## Authority and ownership

`cad.application.Application.execute(operation, arguments)` remains the public
command and transaction boundary. The GUI, MCP tools, and refinement loop use the
same application and document. Results are `{ok: true, value}` or
`{ok: false, error: {code, message}}`. Inputs and returned metadata are detached
copies, so callers cannot change committed parameters through Python aliases.
Non-finite numeric arguments are rejected before kernel execution.

`Document` stores persistent features, B-Rep shapes, sketches, names, image assets,
and settings. Revisions and undo/redo track commits. Failed geometry evaluation
and project loading finish before commit and leave the live document unchanged.
ID counters never rewind during undo, redo, or opening an older project; loading
a file preserves its stored IDs, while subsequent allocations use the application's
high-water marks. Opening a project is undoable.

History takes independent shape copies through `GeometryBackend.copy`. The OCC
implementation retains build123d's `deepcopy`, whose implementation uses
`BRepBuilderAPI_Copy`. Backend modeling operations copy inputs where necessary;
callers must treat document shapes as read-only. Tessellation may populate kernel
mesh caches, but those are disposable derived data, not edits to B-Rep geometry.
This favors transaction isolation over reducing history memory usage.

`InspectionService` owns read-only topology queries and render preparation.
Persistence, exporting, validation, assets, and rasterization remain focused
modules. Application keeps modeling command validation and commit orchestration;
there is no second model in these services.

## Geometry seam

`cad.geometry.protocol.GeometryBackend` describes the capabilities used by the
application, replay, inspection, validation, and export. Shape handles are opaque
outside the backend. It is a dependency seam, not a plugin framework.
`cad.geometry.occ.OccBackend` is the production build123d/OpenCascade backend.

Supported operations remain primitives, sketches, extrude, revolve, sweep, loft,
booleans, transform, fillet, chamfer, shell, hole, mirror, and linear/circular
patterns. This cleanup adds no modeling operations.

The jewelry package retains its analytic kernel, original numeric policy,
manufacturing rules, tools, CLI, and GUI. `jewelry.domain` is its application-facing
domain layer. The generic `cad` package does not import jewelry.

## Feature graph and replay

Each `Feature` has its existing stable ID, operation, parameters, output reference,
and name. It exposes `input_refs`, `input_features`, `editable_parameters`, and
`replayable`. `cad.operations` explicitly declares body inputs, sketch inputs,
editable fields, and replay functions; application code no longer scans arbitrary
parameter dictionaries for reference-like keys.

The snapshot's `dependencies` maps feature IDs to the producers they consume.
Body inputs bind to the latest preceding producer in history, which makes
in-place operations such as fillet depend on the preceding state of that body.
Sketch inputs bind directly to sketch feature IDs. Evaluation still follows the
ordered history and rebuilds the full list on an edit. There is no dependency
solver or incremental rebuild engine.

Deletion checks semantic body inputs. Rename records do not create geometric
dependencies. A duplicate is intentionally a baked independent B-Rep: its source
is provenance, not a live dependency, and deleting the source does not break it.
Normally replayable features always rebuild from parameters and dependencies.

## Topology selections

`query_faces` and `query_edges` do not change the document, its history, or
validation results. Selections are caller/session state. An edit consuming IDs
must provide the current integer `selection_revision`; stale use fails with
`STALE_SELECTION`. IDs are interpreted against the supplied body reference.

IDs retain version-1 geometry fingerprints and ordinal disambiguation. Repeated
queries of one shape, including filters and nearest-point sorting, produce the
same IDs. Identical geometric keys use kernel index as a tie-breaker; an explicit
collision fallback keeps IDs unique within the query. They are **revision-scoped**,
not persistent topological names across arbitrary recomputation or kernel versions.
Recorded feature selections replay against their input shape. A changed upstream
shape can invalidate them and cause a rebuild to fail without committing.

`render_selection` supports face IDs. It highlights visible selected faces using
the same camera and depth buffer as the body. Edge highlighting is explicitly
unsupported: `edge_ids` is absent from its MCP schema, and nonempty edge selections
fail rather than silently rendering an unhighlighted image. Modeling tools still
support edge selections.

## Projects

Projects remain ZIP archives with `format: agentic-cad-project` and
`format_version: 1`, containing `project.json`, reference assets, and baked
B-Rep data for duplicates. Optional serial counters and derived feature metadata
are additive version-1 fields. Older files without them still load; unknown
versions are rejected. Persisted `sketches` are a legacy cache and are not a
fallback for missing sketch features.

Loading validates metadata types, finite numbers, identifiers, duplicate IDs,
feature ordering/dependencies, output ownership, assets, checksums, dimensions,
and calibration before installing the reconstructed document. Calibration scale
is recomputed from its points and real distance. Only duplicate features may
consume B-Rep bytes; normal features cannot replace semantics with a shape cache.

Archive members are read without extraction. Absolute paths, traversal paths,
backslashes, duplicate members, symlinks, and encrypted members are rejected.
Limits are 4,096 entries, 64 MiB per member, 256 MiB total uncompressed content,
and 30 MiB per reference image. These limits bound archive reads; they do not
provide a time budget or sandbox for the geometry kernel. Corrupt or missing
members fail without partially replacing the current project. Save publishes
atomically and does not change document state.

## Validation and export

Validation is read-only. Geometry checks cover valid B-Rep, nonzero volume,
closed solids, manifold edges, and component count. It does not warn about a
previous read-only query becoming old.

Manufacturing presets `fdm`, `sla`, `cnc`, and `casting` are **lightweight
heuristics**, not manufacturing simulation or complete machinability analysis.
They add minimum wall and feature-size checks. Wall estimates use opposed planar
faces whose midpoint lies in material; feature estimates use cylindrical
diameters and toroidal minor radii. These checks do not evaluate tool access,
fixtures, supports, material behavior, or all local wall thicknesses. Reports
include this limitation. Jewelry-specific checks stay in the jewelry validator.

| Format | Geometry | Units | Default gate |
| --- | --- | --- | --- |
| STEP | exact B-Rep | mm | valid solid |
| GLB | derived mesh | metres converted from mm | valid solid |
| STL | derived mesh | mm; STL has no unit field | manufacturing report |
| OBJ | derived mesh | mm | valid solid |
| BLEND | derived glTF imported by headless Blender | metres | valid solid, Blender available |

Publication writes a temporary file and uses `os.replace`. A failed export leaves
an existing destination intact and does not change history. Manufacturing export
requires a current, ready report with manufacturing/all scope and rechecks the
body against validated profile rules. A geometry-only report cannot authorize it.

## Images and MCP

Reference images are persistent project assets: PNG/JPEG bytes, role, label,
notes, camera hint, dimensions, checksum, and optional two-point calibration.
Calibration relates pixel distance to millimetres in the image plane. One image
does not establish depth or a unique solid. `estimate_length` returns
`uncalibrated` without that relationship.

Headless orthographic PNG renders support isometric, front, rear, left, right,
top, and bottom. Front looks along +Y, with +X right and +Z up. Silhouette fraction,
aspect, and asymmetry supplement exact measurements; they are not a pixel oracle.

`ImageResource` separates immutable image bytes, media type, URI, and detached
metadata. `Application.reference_resources()` is a locked read accessor for
in-process consumers. `split_images` normalizes render results into metadata and
image resources, retaining the source revision. It does not modify tool results.

MCP remains JSON-RPC 2025-06-18 with typed tool schemas. Render tool results carry
first-class `image` blocks alongside structured metadata containing `image_uri`.
`add_reference` and `inspect_reference` also return image blocks. References can
be listed/read using MCP resources at checksum-qualified `cad://references/`
URIs. Render URIs identify the attached image content; they are not persistent
`resources/read` entries. The NDJSON limit is 64 MiB, enough for one maximum-size
reference encoded as base64. Oversized responses fail explicitly without closing
the session. Reference resources disappear when their asset is no
longer in the current document.

For compatibility, direct Python `execute` render results still contain
`png_base64`. MCP render metadata intentionally replaces that field with
`image_uri`; image data is in image content blocks rather than duplicated prose.
The structured success/error envelope and existing tool names are preserved.

## Planning and refinement

`Planner.decide(context) -> Decision` is provider-neutral. Inject a planner with
`Application(planner=...)` or `RefinementLoop(application, planner)`. No provider
client or model name is required by the generic architecture.

The context contains the task (`request`), semantic snapshot including exact body
measurements, topology inspection, reference metadata, actual reference and
requested render `ImageResource` objects, goals/mismatches, and previous tool
results including failures. Render bytes are separate from those JSON results.

Decisions contain a kind (`execute`, `stop`, `impossible`), structured existing
CAD/inspection/render operations, optional goals, reason, and optional validation
arguments. Requested evidence is executed through Application and passed back on
the next iteration. The loop observes, plans, executes, and repeats for at most
20 iterations. It checks goals and validates before reporting satisfaction.
Default final validation checks geometry; process-specific rules and target refs
come from the planner. Final overview renders remain in the report. Cancellation
sets a thread-safe event without waiting for the document lock, including through
MCP. It stops further operations; already committed work remains undoable.

`cad.planners.DeterministicPlanner` contains the box-correction and mounting-bracket
demos, including their body names, diameter thresholds, and FDM choice.
`GoalPlanner` remains a compatibility alias. These sequences test orchestration;
they are not general-purpose intelligence. The loop itself has no bracket name,
hole-diameter threshold, or fixed manufacturing profile. Goal evaluation lives in
`cad.goals`; cylindrical-face counts are geometric heuristics, not full hole
recognition.

A future multimodal adapter can implement Planner and consume these normalized
resources. Provider adapters, semantic visual criticism, robust persistent
naming, incremental rebuilds, and history memory optimization remain future work.

## Desktop and packaging

`agentic-cad` opens the generic viewport, model tree, inspector, reference panel,
validation, and refinement panel. `jewelry-cad` remains the compatibility desktop.
Neither GUI owns a second editable model.

The distribution name `agentic-jewelry-cad` is retained for installation/upgrade
compatibility: renaming without a transitional package could leave two installed
distributions owning the same modules and entry points. README, description,
keywords, and the primary CLI identify the generic direction. `manifold3d` remains
mandatory so existing base installations keep working for the jewelry CLI and
contract; splitting it into an extra is deferred to a coordinated packaging
transition. GUI dependencies remain in the `gui` extra.

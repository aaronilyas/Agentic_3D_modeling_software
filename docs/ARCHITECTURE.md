# Architecture

The editable model is a parametric feature graph plus exact boundary representation.
Triangle meshes are derived for the viewport, headless renders, STL, OBJ, and glTF.
STEP is written from the B-rep. A mesh is never converted back into a solid.

## Authority

`cad.application.Application` owns one document. The GUI, MCP server, and refinement
loop call `execute`. They do not keep a second geometric model. A tool result is
`{ok: true, value}` or `{ok: false, error: {code, message}}`. Assistant text is not
evidence that geometry changed.

Internal units are millimetres. The axes are right-handed and Z is up. A box origin
is its minimum corner. A cylinder origin is the center of its base and the cylinder
extends along +Z. Topology ids come from face and edge geometry at a document
revision. A selection whose `selection_revision` is not the current revision fails
with `STALE_SELECTION` and does not edit the solid.

Failed edits raise before `Document.commit`. Undo and redo restore an earlier
feature list and shape cache. Reference ids are not reused.

## Geometry

`cad.geometry.occ.OccBackend` implements production solids with build123d and
OpenCascade. Supported operations include box, cylinder, sphere, sketch, extrude,
revolve, sweep, loft, boolean union/subtract/intersection, affine transform,
fillet, chamfer, shell, hole, mirror, and linear and circular patterns.

The jewelry package keeps its analytic kernel. That kernel still answers the
original jewelry contract, including its numeric tolerance policy. `jewelry.domain`
is the only application-facing jewelry API. The `cad` package does not import it.

## Features

Each committed operation appends a `Feature` with a stable id, operation name,
parameters, and output reference. `edit_feature` changes parameters and replays
the whole list. Replay is deterministic for the same parameters. A duplicate is a
baked B-rep copy, not a live link, because a copy should survive deletion of its
source. Opening a project replays features; saved B-rep bytes are a cache for
duplicates and are not a substitute for the feature list.

Project files are zip archives with `format_version: 1`, `project.json`,
`assets/`, and optional `shapes/`. The format name is `agentic-cad-project`.
Units in the file are millimetres. An unknown format version is rejected.

## Validation and export

Validation does not modify the document.

- Geometry checks valid B-rep, nonzero volume, a closed solid, manifold edges,
  component count, and a stale pinned selection.
- Manufacturing profiles `fdm`, `sla`, `cnc`, and `casting` add minimum wall and
  minimum feature checks. Wall thickness is the distance between opposed planar
  faces whose midpoint lies in material. Feature size uses cylindrical diameters
  and toroidal minor radii.
- Jewelry wall and prong checks remain on the jewelry validator and its
  `mvp-single-piece` profile.

| Format | Geometry | Units at the boundary | Default gate |
| --- | --- | --- | --- |
| STEP | exact B-rep | millimetres | valid solid |
| GLB | mesh | metres, converted from millimetres | valid solid |
| STL | mesh | millimetres; STL stores no unit | manufacturing report |
| OBJ | mesh | millimetres | valid solid |
| BLEND | mesh via headless Blender | metres inside the imported glTF | valid solid, Blender required |

Export writes a temporary file, checks it, and replaces the destination with
`os.replace`. A failure leaves an existing destination in place and does not
change the document or its history. STL manufacturing mode requires a ready
validation report for the current revision and revalidates before writing.
Preview mode only requires a valid solid. `.blend` is produced by importing a
generated glTF in headless Blender. This repository does not write Blender's
native structure itself.

## References and renders

Reference images are document assets. PNG and JPEG files can be added with a
role (`front`, `side`, `top`, `perspective`, `detail`, `inspiration`, or
`other`), a label, notes, and an optional camera hint. The asset stores pixel
size and a SHA-256 checksum. A calibration stores two pixel points and a
millimetre distance, which gives millimetres per pixel in the image plane.
`estimate_length` returns `uncalibrated` when that relationship is absent.
One image does not determine depth or a unique scale.

Headless renders are orthographic PNG images for isometric, front, rear, left,
right, top, and bottom. Front looks along +Y, with +X to the right and +Z up.
The refinement report records silhouette fraction, aspect, and left-right
asymmetry. Those metrics supplement exact inspection. They are not a pixel oracle
and they do not replace volume, topology, or hole diameter.

## Agent loop

`refine` runs a bounded loop:

1. Read the snapshot and reference assets.
2. Measure bodies and query faces.
3. Compare measurable goals with the document.
4. Ask the planner for the next operations.
5. Execute those operations.
6. Repeat until the goals match, the planner stops, the request is impossible,
   the loop is cancelled, or the iteration limit is reached (at most 20).
7. Validate and render.

The built-in planner can correct a box whose first solid is intentionally short,
and it can build a mounting bracket from plates, a union, a cutter, a linear
pattern, a subtraction, a diameter edit, and a fillet. A successful create is
not completion. Cancellation stops further iterations. Operations that already
committed stay in the undo stack.

MCP is JSON-RPC 2025-06-18 on the same application. Tool schemas are typed.
`ok: false` is a failed tool call. A manufacturing finding inside a successful
`validate` call is not a tool failure.

## Desktop

`agentic-cad` opens the generic window: viewport, model tree, inspector,
reference images, validation, and the refinement panel. `jewelry-cad` remains
the jewelry window on the analytic document, including its existing assistant.
Direct jewelry dialogs are compatibility and debugging controls for that window.
The generic modeling path is the feature graph and the refinement loop.

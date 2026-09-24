# Agentic CAD

Agent-first parametric CAD. The editable model is a feature graph plus exact
B-rep. Meshes are derived for display, renders, and mesh export. STEP comes
from the B-rep.

Millimetres are the internal unit. Axes are right-handed and Z is up. The
application document is the only geometry authority: the desktop, MCP server,
and refinement loop all call that document. A successful tool call is not, by
itself, completion of a request.

The jewelry package remains as a domain and compatibility layer. Its analytic
kernel, manufacturing checks, MCP contract, and desktop are unchanged. The
generic `cad` package does not import it.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the feature graph, export
gates, reference images, and the refinement loop.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[gui]'
```

Runtime dependencies are `numpy`, `manifold3d` (jewelry tessellation), and
`build123d` (OpenCascade). The `gui` extra adds PySide6 and PyVista. Python
3.10 or newer is required; the OpenCascade wheels used here were exercised on
3.14.

## Generic model

```python
from cad.adapter import create_application

app = create_application()
box = app.execute("create_primitive", {
    "kind": "box", "size": [60, 40, 4], "origin": [0, 0, 0], "name": "plate",
})
```

`execute` returns `{ok: true, value}` or `{ok: false, error: {code, message}}`.
Create operations return a stable `ref` and `feature_id`. `edit_feature` changes
parameters and rebuilds dependents. A failed edit leaves the revision unchanged.
`undo` and `redo` restore earlier commits. References are not reused.

Modeling operations include primitives, sketches, extrude, revolve, sweep, loft,
boolean, transform, fillet, chamfer, shell, hole, mirror, and linear and
circular patterns. `query_faces` and `query_edges` return semantic ids for the
current revision. Passing those ids with an older `selection_revision` fails
with `STALE_SELECTION`.

`refine` runs a bounded loop: inspect the document and reference images, plan,
execute, measure, render, and repeat until measurable goals match, the planner
stops, the request is impossible, the loop is cancelled, or the iteration cap
is hit. The built-in planner can correct `box sx sy sz` and build a mounting
bracket (plates, union, patterned holes, a diameter edit, and a fillet).
Cancellation leaves already committed operations undoable.

## Reference images

`add_reference` copies a PNG or JPEG into the document with a role (`front`,
`side`, `top`, `perspective`, `detail`, `inspiration`, or `other`), label,
notes, pixel size, and SHA-256 checksum. `set_calibration` stores two pixel
points and their real millimetre distance. `estimate_length` uses that scale.
Without calibration the estimate is `uncalibrated`: one photograph does not
establish depth or absolute scale. Images are saved in the project file, not
only as chat attachments.

Headless `render_views` returns PNG orthographic views (`isometric`, `front`,
`rear`, `left`, `right`, `top`, `bottom`) and silhouette metrics. Front looks
along +Y, with +X to the right and +Z up. Those images supplement exact
volume and topology checks.

## Projects and export

`save_project` writes a versioned `.cadproj` zip (`format_version` 1) containing
the feature graph, names, settings, reference files, and B-rep cache bytes.
`open_project` replays the features. An unknown format version is rejected.
Save does not modify the document. Open can be undone.

| Format | Source | Units | Default gate |
| --- | --- | --- | --- |
| STEP | exact B-rep | millimetres | valid solid |
| GLB | mesh | metres, converted from millimetres | valid solid |
| STL | mesh | millimetres; STL has no unit field | current manufacturing report |
| OBJ | mesh | millimetres | valid solid |
| BLEND | headless Blender imports a generated glTF | metres in that glTF | valid solid, Blender on `PATH` |

Publication writes a temporary file and replaces the destination atomically.
A failed export keeps the previous file and does not change the model.
`validate` is read-only. Profiles are `geometry`, `fdm`, `sla`, `cnc`, and
`casting`. Jewelry wall and prong rules stay on the jewelry validator.

## Desktop

```bash
.venv/bin/agentic-cad
# or: .venv/bin/python -m cad.gui
```

The window is agent-first: viewport, model tree, inspector, reference images
(including drag and drop), validation, and a refinement panel. File commands
cover new, open, save, and STEP, GLB, and STL export. STL export uses
manufacturing mode and requires a ready validation report for the current
revision. Cancel asks the refinement loop to stop between iterations.

The jewelry desktop is still available:

```bash
.venv/bin/jewelry-cad
# or: .venv/bin/python -m jewelry.gui
```

That window keeps direct ring, setting, recess, and prong controls for the
analytic document, plus its existing Design Assistant. Those dialogs are the
jewelry compatibility surface.

## Tests

Generic CAD:

```bash
.venv/bin/python -m tests.run generic
```

Jewelry contract, with the analytic adapter:

```bash
export JEWELRY_TEST_ADAPTER=jewelry.adapter:create_application
.venv/bin/python -m tests.run local
```

`local` is harness, fast, and integration. It does not start Grok or Codex.
ACP and end-to-end jewelry tests stay opt-in (`tests.run acp`, `tests.run e2e`).
GitHub Actions runs the jewelry harness, fast, and integration layers, then
`tests.run generic`.

Offscreen widget coverage, without an OpenGL viewport:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_cad_gui -v
```

Jewelry GUI tests need a display or Xvfb:

```bash
xvfb-run -a .venv/bin/python -m unittest tests.test_gui tests.test_gui_agent -v
```

[tests/CONTRACT.md](tests/CONTRACT.md) remains the jewelry adapter contract.
Importing the jewelry test modules does not launch a CLI.

## MCP

Generic tools are served from the live application over MCP `2025-06-18`.
`app.open_mcp()` returns the NDJSON transport. Tool schemas are typed.
Lengths in arguments are millimetres except where an export format states
otherwise. `instructions` on initialize restates units, axes, revision-bound
selections, and that prose is not geometry.

The jewelry MCP server is separate and still exposes the jewelry contract,
including `create_ring`.

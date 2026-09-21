# GUI modeling and manufacturing validation

Baseline before edits: harness 15, fast 19, integration 8, e2e 3, GUI 6 passed.

The desktop now supports numeric ring creation/modification, cylindrical settings,
through-holes, blind stone seats, circular prong repetition, deletion, backend
undo/redo, profile configuration, manufacturing reports, and selected-object STL
export through the native Qt save chooser. All modeling remains behind
`Application.execute`. Snapshot, tessellation, and inspection refresh after each
mutation; no widget implements geometry or manufacturing checks.

The controller runs one worker job at a time. Each mutation and its full refresh
are one GUI job. Document actions and profile inputs are disabled while busy;
camera interaction remains available. VTK and widget updates run on the GUI
thread. Close is deferred by asking the user to wait while a job is active, and
controller shutdown waits for worker completion before closing the Application.

The default profile matches the repository fixture: `mvp-single-piece`, version
1, mm, min_wall 1, min_prong 0.8, max_components 1. Profile changes clear validation;
CAD changes retain the old report visibly marked stale. Findings remain domain
results and are displayed without transport-error dialogs.

Two narrow export protection gaps were addressed in the backend: a stale report
is now rejected even if the new geometry is still valid, and the existing mesh
diagnostics check the tessellated export before publication. Filesystem publication
errors now return `EXPORT_IO_ERROR` through the structured contract. Live geometry
is still revalidated under the report rules. Failed exports preserve existing
files and remove temporary output.

Verification commands:

```bash
export JEWELRY_TEST_ADAPTER=jewelry.adapter:create_application
.venv/bin/python -m tests.run harness
.venv/bin/python -m tests.run fast
.venv/bin/python -m tests.run integration
.venv/bin/python -m tests.run e2e
.venv/bin/python -m unittest tests.test_gui -v
```

Final results: harness 15 passed, fast 19 passed, integration 9 passed, e2e 3
passed, and GUI 14 passed. No failures or skips. `git diff --check` also passed.

GUI coverage includes real dialog input, cancellation, structured failure/retry,
create → modify → undo/redo → validate → export, all four feature forms, complete
mesh/tree/inspector synchronization, finding rendering, profile changes, stale and
invalid export rejection, save cancellation, backend history, camera independence,
and a deliberately blocked worker proving event-loop responsiveness and rejection
of concurrent requests. Export tests include stale-but-valid geometry, structural
mesh rejection, and publication failure without damage to existing artifacts.

The real desktop workflow was also rendered and visually inspected. The GUI suite
uses a real Qt/VTK display, without pixel-perfect assertions. Native chooser
invocation is mocked in the automated export test so it can supply a temporary
path deterministically. Existing VTK OpenGL color-buffer query warnings (1282)
persist on this machine; rendering, picking, and interaction tests pass.

Remaining scope: ring dimensions are editable only for backend annulus solids;
features use explicit document coordinates and Z-aligned cylinders. The document
validator retains its existing analytic wall/prong/component checks; it does not
become a general minimum-thickness solver. STL exports one selected object and has
no unit metadata. Large jobs have no cancellation/progress percentage yet, and VTK
actor rebuilding still occurs on the GUI thread. Persistence, assistant chat, and
ACP session integration are not part of this implementation.

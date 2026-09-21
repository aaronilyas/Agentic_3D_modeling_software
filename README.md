# Agentic jewelry CAD

Python jewelry CAD application and the MVP contract suite. Kernel groups
K01–K08, document transactions A01–A04, manufacturing validation V01–V07,
tessellation/export X01–X04, MCP M01–M04, ACP C01–C04, and E2E E01–E03 are
implemented. Requires Python 3.10 or newer.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
export JEWELRY_TEST_ADAPTER=jewelry.adapter:create_application
```

Install the project into the virtualenv you use to run it. `import jewelry`
does not search for a `.venv` or modify `sys.path`. Runtime dependencies are
`numpy>=1.26,<3` and `manifold3d>=3.0,<4`.

`JEWELRY_TEST_ADAPTER=jewelry.adapter:create_application` selects the in-repo
factory. The factory returns an object with `execute(operation, arguments)`
and `close()`.

## Deterministic tests

From the repository root, with the virtualenv's interpreter:

```bash
.venv/bin/python -m tests.run harness      # test infrastructure
.venv/bin/python -m tests.run fast         # K01–K08, V01–V07, A01–A04
.venv/bin/python -m tests.run integration  # X01–X04, M01–M04
.venv/bin/python -m tests.run local        # harness + fast + integration
```

The default `python -m tests.run` runs only fast tests. These layers do not
start Grok or Codex. GitHub Actions runs harness, fast, and integration.

## ACP and end-to-end tests

ACP and E2E are explicit opt-in. They are not part of baseline CI.

```bash
.venv/bin/python -m tests.run acp   # C01–C04, both CLI adapters
.venv/bin/python -m tests.run e2e   # E01–E03
.venv/bin/python -m tests.run all   # every layer, including ACP and E2E
```

E2E uses MCP on the live application and does not need a model CLI. ACP spawns
real `grok` and `codex` processes against a local HTTP model. It does not call
paid inference.

Executable lookup uses `PATH`, unless an override is set:

```text
JEWELRY_GROK        grok executable
JEWELRY_CODEX       codex executable
JEWELRY_NPX         npx executable
JEWELRY_CODEX_ACP   npm package spec (default @agentclientprotocol/codex-acp@1.12.0)
```

The Codex adapter runs `npx -y` with that package spec. This tree was exercised
with grok 1.0.40 and codex-cli 0.154.0. Those CLI versions are not pinned;
override the executables when you need a specific build. A missing or
non-executable override raises `MISSING_CAPABILITY` and does not fall back to
`PATH`.

## Contract

[tests/CONTRACT.md](tests/CONTRACT.md) is the adapter boundary. References are
opaque. Assertions concern observable behavior. The adapter must not calculate
fixture answers, fabricate validation, or mock successful geometry.

MCP is stdlib NDJSON JSON-RPC (2025-06-18) on the same `Application` as
`execute()`. ACP launches `grok agent stdio` and the pinned Codex ACP package
with an isolated HOME and a local HTTP model at `127.0.0.1`.

All geometry uses millimetres and mm³. Kernel numeric tolerance, geometry
comparison tolerances, configured manufacturing limits, tessellation chord
error, and export measurement tolerances stay separate. STL is unitless; its
coordinates are millimetres.

| Layer | Specification groups |
| --- | --- |
| Kernel | K01–K08 |
| Manufacturing validator | V01–V07 |
| Tessellation / export | X01–X04 |
| Application | A01–A04 |
| MCP | M01–M04 |
| ACP (one contract, Codex and Grok) | C01–C04 |
| End to end | E01–E03 |

## Desktop GUI foundation

Install the optional desktop dependencies and launch on a graphical desktop:

```bash
.venv/bin/pip install -e '.[gui]'
.venv/bin/python -m jewelry.gui
# Alternatively: .venv/bin/jewelry-cad
```

The PySide6 window embeds PyVistaQt/VTK, with model-tree, inspector, and
manufacturing-validation docks. **Modeling → Create Ring** opens numeric controls
for inner radius, outer radius, and width, in mm. Select a plain ring and use
**Modify Ring** in the toolbar or inspector to edit those dimensions. Drag to orbit, middle-drag
(or Shift+left-drag) to pan, and scroll to zoom. Right-click a body to select it,
or select it in the tree. View → Fit model (`F`) frames all bodies; Reset camera
restores the isometric orientation. Show mesh edges overlays triangle edges.

File → New discards the current in-memory document and history, closes its
Application, and creates one empty replacement. There is no persistence yet.
Undo, Redo, and Delete selected operate on backend history. The controller calls
only `Application.execute` for geometry and diagnostic operations; snapshots,
tree items, selection, and VTK meshes are disposable presentation state.
CAD work, inspection, tessellation, validation, and export run in a serialized
worker; Qt/VTK rendering stays on the main thread. Document actions are disabled
while work is running. Preview/export chord tolerance is 0.02 mm; dimensions and
inspection volumes are shown in mm and mm³. Camera movement never enters history.

The Modeling menu also provides **Cut Through-Hole**, **Cut Stone Seat / Recess**,
**Add Setting**, and **Repeat Prongs**. Forms use document X/Y coordinates and Z
heights; cutters and additions are cylindrical and aligned with Z. Defaults work
with the initial ring: add setting → cut recess → repeat prongs. Adjust placement
for other dimensions. After adding/cutting features, the combined solid no longer
supports ring dimension editing; undo those features to edit the plain ring.
Use Delete to remove a selection, Ctrl/Cmd+Z to undo, and Ctrl/Cmd+Shift+Z to redo.

**Manufacturing → Validate Model** shows the real backend's readiness and findings,
including severity, code, description, and any measured/required values. The
advanced profile starts with `mvp-single-piece`: minimum wall 1 mm, minimum prong
0.8 mm, maximum components 1. Validation applies to the whole document. Editing,
undo, or redo makes the report stale; changing the profile requires new validation.

**Manufacturing → Export STL** opens a native save chooser and exports the selected
object in mm. Validate first. The backend rejects stale reports, rechecks current
geometry under the report rules, and checks the export mesh using its existing
structural diagnostics. Publication is atomic: failures preserve an existing file
and clean up temporary output. Errors show the backend code and reason; success
shows the final path in the status bar. STL itself has no unit metadata.

Run desktop integration tests separately (requires the GUI extra and a working
Qt/OpenGL display; a configured Xvfb display can also be used):

```bash
.venv/bin/python -m unittest tests.test_gui -v
```

The tests use real Qt widgets, backend geometry, and VTK actors/picking;
they check camera interaction without pixel comparisons. Backend-only installs
and the existing contract test layers do not import the GUI.

The GUI uses the existing validator's semantics: analytic document validation
checks supported wall/prong dimensions and components; export additionally checks
mesh structure. It does not infer printability from the preview. There is no
generic feature-parameter editor, persistence, or assistant/ACP integration yet.

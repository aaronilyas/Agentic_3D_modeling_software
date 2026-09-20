# MVP test adapter contract

Repository inspection found only LICENSE. These tests specify a **proposed test
boundary**, not an existing product API. Do not implement a fake CAD application
to satisfy them. An adapter may translate real production APIs to this boundary.

Set `JEWELRY_TEST_ADAPTER=package.module:create_application`. The zero-argument
factory must return an isolated empty application. Close it after each test.
Missing adapters fail with `MISSING_CAPABILITY`, never skip. Other import/runtime
errors remain errors and must not be classified as expected missing behavior.

`ContractTestCase` provides
`self.app`, `ok(operation, **arguments)`, `error(operation, **arguments)`,
`ring(**overrides)`, `snapshot()`, `assert_solid(ref, volume=None, components=1)`,
`assert_bounds(ref, expected)`, `contains(ref, point)`. `ok` returns `value` from
`app.execute(operation, arguments)`; `error` returns its structured error.
Every successful create/edit returns a dict including `ref`. Refs are opaque.

Envelope: `{'ok': True, 'value': ...}` or
`{'ok': False, 'error': {'code': nonempty_string, 'message': nonempty_string, ...}}`.
The failure envelope must not contain `value` or a live result reference.

Operations (snake_case):

- `create_ring(inner_radius, outer_radius, width)` centered on Z, spanning
  `[-width/2, width/2]`; `create_box(size=[x,y,z], origin=[x,y,z])` uses minimum
  corner origin; `create_cylinder(radius, height, origin)` uses the base-disk
  center as origin and extends along +Z;
  `create_sphere(radius, center)`.
- `inspect(ref)` -> `bounds: [[xmin,ymin,zmin],[xmax,ymax,zmax]], volume,
  topology: {closed, manifold, components}, ...`;
  `contains(ref, point)` -> bool, material interior (avoid boundary probes).
- `transform(ref, matrix)` uses a flat 16-number row-major 4x4 affine matrix, translation last
  column; `boolean(kind='union'|'subtract', left, right)` returns a new ref.
  `extrude(profile=[[x,y],...], height)` extends +Z;
  `revolve(profile=[[radius,z],...], angle_degrees=360)` around Z.
- `modify_ring(ref, **dimensions)`, `delete(ref)`, `undo()`, `redo()`;
  `snapshot()` -> serializable committed geometry plus `references` (live opaque
  reference list), `revision` (integer), `undo` and `redo` (history lists).
  No volatile timestamps in this diagnostic representation. Ring modifications
  preserve the body's reference. Undo may use monotonic or restored revision
  numbering; failed operations must not change revision. Restoring an object
  through undo restores its reference, but a new object must not reuse an old one.
- `validate(profile)` -> revision, rules metadata, ready, findings;
  `tessellate(ref, chord_tolerance)` -> vertices and triangles;
  `export(ref, path, format, validation, chord_tolerance)` atomically publishes.
- Specialized operations may be declared alongside their tests until production
  APIs exist. Keep their meaning explicit and share fixtures where possible.

Jewelry additions use the +Z axis and edit their target body, returning its live
reference. These are adapter operations; a real implementation may use ordinary
kernel primitives rather than introducing identically named product APIs:

- `add_setting(ref, center=[x,y], radius, base_z, height)` unions a solid cylinder
  with the band. The fixture overlaps the band, so it must be connected.
- `cut_recess(ref, center=[x,y], radius, top_z, depth)` removes the cylinder from
  `top_z-depth` to `top_z`, leaving the specified floor.
- `cut_through_hole(ref, center=[x,y], radius)` cuts through the complete body's
  Z extent. The shared fixture places this small hole opposite the setting.
- `repeat_prongs(ref, center=[x,y], orbit_radius, diameter, base_z, height,
  count, start_angle_degrees)` unions equally spaced upright cylinders with the
  setting. Counts must be positive integers. Zero/negative diameters and
  non-finite pattern arguments are invalid. See `jewelry_fixtures.py` for values.

Boolean construction operands may be retained or consumed. Tests do not depend
on that choice. The V03 control removes retained operands before validating the
resolved solid. Point-only sphere contact must fail with a structured geometry
error; a compound with a non-manifold point may not claim printable topology.

Tolerance policy: kernel numeric tolerance 1e-7 mm; geometry comparisons 1e-6 mm
and 1e-6 relative volume; manufacturing dimensions are configured rules, not
numeric epsilon; default mesh chord error 0.02 mm; independent mesh volume
comparison 1%. Manufacturing minimums are inclusive. Tolerance-edge Boolean
inputs within twice the numeric tolerance may return `TOLERANCE_AMBIGUITY` or
valid geometry; a successful
union must preserve the interiors of both operands. Exact face contact merges;
clear disjoint union returns a valid multi-component solid, not a fabricated
connection. Self subtraction returns an explicit empty result or structured
EMPTY_RESULT error (empty geometry must not claim to be a solid).
Successful self-subtraction returns `{'empty': True}` without a ref.

## Manufacturing and artifact contract

`validate(profile)` validates every live document body, including detached
fragments. It returns `{revision, rules, ready, findings}`; `profile` is also
accepted as the metadata key for `rules`. Findings carry nonempty `code`,
`message` and `severity` (`error` or `warning`). `ready` is true exactly when no
blocking findings exist. Findings and metadata must be repeatable; validation
does not mutate document geometry, references, revision or edit history.

The profile contains `id`, `version`, `units='mm'`, positive finite `min_wall`
and `min_prong`, and positive integer `max_components`. Minimums are inclusive;
wall and prong criteria are separate feature classes. If `max_wall` is supplied,
it must not be below `min_wall`. Bad/missing profiles return `INVALID_PROFILE`
before claiming readiness. The default is a single-piece profile. If a
two-component profile is supported, the disconnected-body control must pass;
otherwise that optional policy must return `UNSUPPORTED_PROFILE` explicitly.

`validate_mesh(vertices, triangles, profile)` is a direct diagnostic entry for
adversarial geometry. It must use the production validator, leave the document
unchanged, and report `OPEN_SHELL`, `NON_MANIFOLD`, `SELF_INTERSECTION`,
`ZERO_THICKNESS`, `THIN_FEATURE`, or `UNINTENDED_BODY` as appropriate. Thin-feature
findings expose `feature_type` (`wall`/`prong`), `measured`, and `required` in mm.
An adapter may normalize equivalent production finding codes to these names.

`tessellate(ref, chord_tolerance, max_triangles=optional)` returns numeric
`vertices` and integer indexed `triangles`. Identical coordinate seams may use
separate indices; the oracle welds these exactly, without repairing geometric
gaps. Invalid or below-kernel accuracy requests must fail. An impossible explicit
triangle budget must fail rather than erase features or violate the error bound.
Preview tessellation is independent of manufacturing readiness. Accuracy checks
sample analytic surfaces, triangle vertices, edge midpoints and centroids; they
are deterministic regression checks, not a formal Hausdorff-distance proof.

`export(ref, path, format='stl', validation=report, chord_tolerance)` exports the
current geometry and returns `{revision, ...}` for the exported revision. The
validation argument is the actual report, not a Boolean or a profile. It must be
current and ready, or export must revalidate under its rules before authorizing
the current geometry. X04 uses a stale ready report after a thin-wall edit to
ensure the old report cannot authorize the invalid revision. Every failure
preserves document state and any previous artifact, and leaves no partial file.

STL is the chosen minimal export format for this empty repository. Coordinates
are mm; STL itself has no unit metadata. Independent parsing checks dimensions,
orientation, manifold connectivity and volume. 3MF is not made mandatory.
`export_mesh(vertices, triangles, path, format)` tests the production exporter's
direct mesh boundary: open geometry and structurally invalid mesh data must be
rejected before publishing bytes. It is not a bypass for topology validation.

The application adapter provides the test-only context manager
`app.fail_at(operation, stage)` for A02. `fail_at('modify_ring', 'after_geometry')`
injects a failure **after candidate geometry is built and before commit**. The
yielded object exposes `triggered: bool`. A preflight rejection does not satisfy
the test. An adapter can map this to the real transaction's dependency injection
or fault hook; no full transaction engine is supplied by the test harness.

## MCP and ACP transport contract

MCP adapters must cross a real MCP transport and expose the application's shared
document, not dispatch directly from a mock client. `app.open_mcp()` returns a
transport with `send_line(str)`, `recv_line(timeout=seconds)` and `close()`.
Lines are serialized JSON-RPC bodies; the transport supplies NDJSON delimiters
and bounded reads. Tests pin MCP 2025-06-18 and perform the initialize/initialized
handshake. Tools use the operation names above. Their result contains the domain
envelope in `structuredContent` or JSON text content; `isError` agrees with domain
failure. Successful validation with violations is a successful tool call.

`app.open_acp(agent, cwd=absolute_path, deterministic=True)` accepts `codex` or
`grok` and returns a real CLI ACP NDJSON transport with the same line/close
methods. Both run the same C01–C04 contract. In addition it provides:

- `mcp_servers`: valid ACP `session/new.mcpServers` configurations pointing to
  this application's real local MCP endpoint.
- `queue_tool_calls([{name, arguments}, ...])`: configure deterministic **model
  backend responses** for the next ACP prompt. This must not directly execute
  the calls. The real CLI must receive and execute them through ACP/MCP, then
  finish the turn. An isolated test provider or recorded backend replay is
  appropriate. Merely asking a live model to obey a transcript is insufficient.
- `observed_calls`: append-only `{name, arguments, result}` records captured
  at the actual modeling/MCP boundary. This is observation, never dispatch.

ACP tests pin protocol version 1, use normal `session/prompt` text, require
structured `rawOutput` in tool updates and compare it to the observed domain
result. No fallback queries synthesize missing ACP results. The adapter must
preauthorize only the isolated CAD tools and must not use paid model inference
for deterministic contract runs. A missing controllable backend fails explicitly.

C tests opt into real external CLIs. E tests use a single real MCP session per
workflow, checking local state and independent artifacts; they do not duplicate
the CLI matrix. Importing any test module never starts a CLI.

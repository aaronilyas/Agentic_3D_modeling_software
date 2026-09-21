# Agentic jewelry CAD — MVP executable specification

This repository contains a Python standard-library contract suite for the MVP
and a production `jewelry` application. Primitive solids (K01) and affine
transforms (K02) are implemented. Later kernel, manufacturing, export, MCP, and
ACP groups remain TDD targets until real production behavior is connected.

Requires Python 3.10 or newer; no third-party test dependencies.

## Run

Run from the repository root:

```bash
python3 -m tests.run harness      # independent test-infrastructure checks
python3 -m tests.run fast         # K01–K08, V01–V07, A01–A04
python3 -m tests.run integration  # X01–X04, M01–M04
python3 -m tests.run mcp          # M01–M04 only
python3 -m tests.run acp          # C01–C04, both CLI adapters; explicit opt-in
python3 -m tests.run e2e          # E01–E03; explicit opt-in
python3 -m tests.run local        # harness + fast + integration
python3 -m tests.run all          # full available suite, including ACP/E2E
```

The default `python3 -m tests.run` runs only fast tests. Use these layer commands
instead of unrestricted unittest discovery when external adapters are configured.
The suite must never invoke a paid model during routine local runs.

With the in-repo adapter, **harness checks pass and K01–K02 are green**. Later
fast groups (K03–K08, V01–V07, A01–A04) and the integration/ACP/E2E layers
remain red until those capabilities exist. The 34 specification groups expand to
38 cases because the four ACP groups run against both CLI adapters.

| Layer | Passing | Remaining TDD |
| --- | ---: | ---: |
| Harness | 11 | 0 |
| Fast | 2 | 17 |
| Integration | 0 | 8 |
| ACP | 0 | 8 |
| E2E | 0 | 3 |

## Connect production

[tests/CONTRACT.md](tests/CONTRACT.md) documents the adapter boundary. The
in-repo production factory is:

```bash
JEWELRY_TEST_ADAPTER=jewelry.adapter:create_application
```

The factory returns an object with `execute(operation, arguments)` and `close()`.
The adapter translates real APIs; it must not calculate fixture answers,
fabricate validation, or mock successful geometry. References are opaque and
assertions concern observable behavior.

MCP needs a real transport connected to that same application. ACP additionally
needs real Codex/Grok CLI transports with deterministic model-backend replay;
the harness intentionally supplies no fake CLI or CAD implementation. E2E
workflows use real MCP and independent STL parsing, without duplicating the
external CLI matrix. See the transport section in the contract for exact hooks.

Missing production is an explicit `MISSING_CAPABILITY` assertion failure.
Invalid adapter configuration, import errors, missing methods, or malformed
results are harness/integration errors to fix, not evidence of a valid red test.
No group is permanently skipped or marked as an expected failure.

All geometry uses millimetres and mm³. Kernel numeric tolerance, geometry
comparison tolerances, configured manufacturing limits, tessellation chord error,
and export measurement tolerances are separate. STL is unitless; its contract
uses coordinates in millimetres. Independent artifact parsing checks that scale.

## Coverage

| Layer | Specification groups |
| --- | --- |
| Kernel | K01–K08 |
| Manufacturing validator | V01–V07 |
| Tessellation / export | X01–X04 |
| Application | A01–A04 |
| MCP | M01–M04 |
| ACP (one contract, Codex and Grok) | C01–C04 |
| End to end | E01–E03 |

These are 34 groups, with boundary cases parameterized inside each group.
Harness checks are separate from product coverage. K01 primitive geometry and
K02 transforms are implemented; later groups still fail until their production
slices land.

The next small production slice is extrusion and revolution (K03). Run the
current kernel slices with:

```bash
python3 -m unittest \
  tests.test_kernel.KernelTests.test_K01_primitives_and_invalid_dimensions \
  tests.test_kernel.KernelTests.test_K02_rigid_inverse_scale_and_invalid_transforms \
  -v
```

# Agentic jewelry CAD — MVP executable specification

This repository contains a Python standard-library contract suite for the MVP
and a production `jewelry` application. Kernel groups K01–K08, document
transactions A01–A04, manufacturing validation V01–V07, tessellation/export
X01–X04, MCP M01–M04, ACP C01–C04, and E2E E01–E03 are implemented.

Requires Python 3.10 or newer. The kernel and validator are standard-library
only. Tessellation uses `numpy` and `manifold3d` from a project virtualenv:

```bash
python3 -m venv .venv
.venv/bin/pip install numpy manifold3d
```

The application inserts `<repo>/.venv/lib/python3.*/site-packages` onto
`sys.path` when that directory exists, so tests can run with system `python3`.

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

With the in-repo adapter, **harness, K01–K08, A01–A04, V01–V07, X01–X04,
M01–M04, C01–C04, and E01–E03 are green**. The 34 specification groups expand
to 38 cases because the four ACP groups run against both CLI adapters.

MCP is stdlib NDJSON JSON-RPC (2025-06-18) on the live `Application` document.
ACP spawns real `grok` / `codex` CLIs against a local mock model; it never
calls paid inference.

| Layer | Passing | Remaining TDD |
| --- | ---: | ---: |
| Harness | 11 | 0 |
| Fast | 19 | 0 |
| Integration | 8 | 0 |
| ACP | 8 | 0 |
| E2E | 3 | 0 |

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

MCP is a real NDJSON transport on the same `Application` instance as
`execute()`. ACP launches real `grok agent stdio` and
`npx @agentclientprotocol/codex-acp` with an isolated HOME and a local HTTP
mock at `127.0.0.1`. E2E uses one MCP session per workflow plus independent
STL parsing, without duplicating the CLI matrix.

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
Harness checks are separate from product coverage. K/A/V/X/M/C/E are
implemented.

```bash
export JEWELRY_TEST_ADAPTER=jewelry.adapter:create_application
python3 -m tests.run harness
python3 -m unittest tests.test_kernel -v
python3 -m unittest tests.test_application -v
python3 -m unittest tests.test_validator -v
python3 -m unittest tests.test_export -v
python3 -m tests.run fast
```

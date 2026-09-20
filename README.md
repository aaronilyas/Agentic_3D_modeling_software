# Agentic jewelry CAD — MVP executable specification

This repository initially contained only a license. It now contains a Python
standard-library contract suite for the MVP. There is no CAD kernel, application,
MCP server, or ACP implementation yet. The tests deliberately fail until real
production behavior is connected; they do not contain a substitute CAD product.

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

Current result: **49 tests collected: 11 harness checks pass, 38 product cases
fail with `MISSING_CAPABILITY`, zero errors and zero skips.** The 34 specification
groups expand to 38 cases because the four ACP groups run against both CLI
adapters. Parameterized boundary cases execute once production is connected.

| Layer | Passing | Missing production |
| --- | ---: | ---: |
| Harness | 11 | 0 |
| Fast | 0 | 19 |
| Integration | 0 | 8 |
| ACP | 0 | 8 |
| E2E | 0 | 3 |

## Connect production

[tests/CONTRACT.md](tests/CONTRACT.md) documents the proposed adapter boundary.
Set `JEWELRY_TEST_ADAPTER=your_package.adapter:create_application` to provide a
fresh isolated application for each test. The factory returns an object with
`execute(operation, arguments)` and `close()`. The adapter translates real APIs;
it must not calculate fixture answers, fabricate validation, or mock successful
geometry. References are opaque and assertions concern observable behavior.

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
Harness checks are separate from product coverage. Since no production code
exists, green harness tests do not establish that any MVP capability works.

The next small production slice is primitive construction (box, cylinder,
sphere), geometry inspection/containment and the thin document adapter needed by
K01. Run that slice with:

```bash
python3 -m unittest tests.test_kernel.KernelTests.test_K01_primitives_and_invalid_dimensions -v
```

Production test bodies cannot yet be exercised past adapter setup. Their red
results establish that the missing boundary is diagnosed correctly; correctness
against a functioning CAD implementation remains to be verified as it is built.

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

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**mrrc-testbed** is a monorepo for testing the [mrrc library](https://github.com/dchud/mrrc) (a MARC record processor) against real-world data at scale. It is separate from mrrc itself — the testbed discovers bugs that curated unit test fixtures miss.

The design document is `testbed-proposal.md`. Consult it for detailed specs on data formats, discovery workflows, state management, and repository structure.

## Current Status

This project is in **early planning/setup**. The testbed-proposal.md contains the full architectural design; implementation has not yet started. Check `br ready` for current work items.

## Architecture

**Two test modes:**
- **CI mode** (`MRRC_TEST_MODE` unset or `ci`): Runs against committed fixtures only (~10MB in `data/fixtures/`). Fast, no downloads.
- **Local mode** (`MRRC_TEST_MODE=local`): Runs against large downloaded datasets + optional BYOD data. Thorough, may take hours.

**Two testing layers:**
- **Rust core** (primary): `crates/mrrc_testbed/tests/` — stress, malformed record discovery, encoding, concurrency
- **Python bindings** (compatibility): `suites/` — pymarc API compat, encoding through bindings

**Dataset priority cascade in local mode:** custom paths (`.env`) → downloaded (`data/downloads/`) → fixtures (`data/fixtures/`)

**Two-stage discovery pipeline:** Tests output JSON to `results/discoveries/` (gitignored, ephemeral) → `import_run.py` converts to YAML in `state/discoveries/` (committed, source of truth)

**State management:** YAML files in `state/` are the source of truth. No database — just YAML files and `grep`.

## Technology Stack

- Python 3.13+, current Rust edition
- **uv** for Python environment, **cargo** for Rust
- **justfile** for task execution
- **ruff** and **rustfmt** for formatting/linting
- **pytest** for Python tests, **cargo test** for Rust tests
- **dotenv** for configuration (`.env` file, never committed)
- **beads** (`br` only, not `bd`) for issue tracking — see AGENTS.md

## Commands

The justfile is the primary interface. Raw commands shown for reference.

```bash
# Common workflows (via justfile)
just setup              # cargo build, uv sync, copy .env.example
just test               # CI mode — both Rust and Python
just test-local         # local mode — full datasets + BYOD
just test-stress        # stress tests only (local mode)
just lint               # cargo fmt/clippy + ruff
just download watson    # download a specific dataset
just import             # import test results to persistent state
just discoveries        # list new discoveries
just validate           # validate fixtures + manifests

# Raw commands (when you need more control)
cargo test                              # Rust CI mode
MRRC_TEST_MODE=local cargo test stress  # Rust specific module, local mode
cargo test -- --nocapture               # verbose Rust output
uv run pytest suites/ -v                # verbose Python output
```

## Key Directories

- `crates/mrrc_testbed/` — Rust test harness crate (lib + integration tests)
- `src/mrrc_testbed/` — Python package (config, datasets, state, discovery)
- `suites/` — Python test suites (pymarc compat, encoding, discovery)
- `scripts/` — CLI tools (fixture curation, dataset download, state import)
- `data/fixtures/` — Committed test records with `manifest.json` provenance
- `data/downloads/` — Gitignored large public datasets
- `data/custom/` — Gitignored BYOD data
- `state/` — Discovery and run YAML files (committed)
- `results/` — Gitignored per-run output

## Conventions

- Tests requiring local mode: mark with `#[ignore]` (Rust) or `@pytest.mark.local` (Python)
- Every committed fixture record must have provenance in its `manifest.json`
- Discovery YAML in `state/discoveries/` is the canonical record; JSON in `results/` is ephemeral
- Never commit downloaded public data, `.env` files, or `data/custom/` content
- mrrc is a **git dependency** in Cargo.toml (pinned to commit/tag) and a **pyproject.toml dependency** for Python

# mrrc-testbed

A test harness for the [mrrc](https://github.com/dchud/mrrc) MARC record processor. Discovers bugs that curated unit test fixtures miss by running mrrc against real-world MARC data at scale.

## What this tests

The testbed exercises mrrc across two dimensions:

- **Rust core tests**: stress testing, malformed record handling, encoding roundtrips, concurrency, and edge case discovery against large datasets
- **Python binding tests**: pymarc API compatibility, encoding through bindings, iteration at scale

Two test modes control which data is used:

- **CI mode** (default): Runs against committed fixture records only (~680 KB in `data/fixtures/`). Fast, deterministic, no downloads required.
- **Local mode** (`MRRC_TEST_MODE=local`): Runs against downloaded public datasets and optional bring-your-own data. Thorough, may take minutes.

## Setup

```bash
git clone https://github.com/dchud/mrrc-testbed.git
cd mrrc-testbed
just setup    # cargo build, uv sync, copy .env.example -> .env
```

Prerequisites: Rust (current edition), Python 3.13+, [uv](https://docs.astral.sh/uv/), [just](https://github.com/casey/just). Optional: [gh](https://cli.github.com/) (for `just report`).

## Running tests

### CI mode (fixtures only)

```bash
just test          # run all Rust + Python tests
just test-rust     # Rust only
just test-python   # Python only
```

### Local mode (full datasets)

```bash
just test-local    # all suites against downloaded data
just test-stress   # stress tests only (with verbose output)
just bench         # same as test-stress (alias)
```

Local-mode tests are marked `#[ignore]` in Rust and `@pytest.mark.local` in Python. They are automatically included when running `just test-local`.

## Downloading datasets

```bash
just download watson        # ~20 MB, 11 files, good starting point
just download ia_lendable   # ~129 MB, Internet Archive lendable books
just download-verify        # check integrity of all downloaded datasets
```

Available datasets:

| Name | Size | Description |
|------|------|-------------|
| `watson` | ~20 MB | Watson MARC test collection (11 .mrc files) |
| `ia_lendable` | ~129 MB | Internet Archive lendable books metadata |
| `loc_books` | ~15 GB | Library of Congress Books All (deferred) |
| `loc_names` | ~1.5 GB | Library of Congress Name Authority File |
| `loc_subjects` | ~1 GB | Library of Congress Subject Authority File |

Downloads go to `data/downloads/` (gitignored).

## Bring your own data (BYOD)

Set environment variables in `.env` to point at your own MARC files:

```bash
# Override a specific dataset name
MRRC_WATSON=/path/to/my/watson.mrc

# Or set a local directory (subdirectories should match dataset names)
MRRC_LOCAL_DIR=/path/to/my/marc/data

# Or point to a single local file
MRRC_LOCAL_DATASET=/path/to/any/file.mrc
```

The dataset priority cascade in local mode is: env override -> local path -> downloads -> fixtures.

## Discovery workflow

Local-mode tests automatically scan for parsing errors and unusual records. The results flow through a two-stage pipeline:

**Stage 1: Test output** (ephemeral)
Tests write JSON to `results/discoveries/` (gitignored). This happens automatically during `just test-local`.

**Stage 2: Import to state** (persistent)
```bash
just import        # deduplicate and convert to YAML in state/
just discoveries   # list all discoveries
just show disc-ia-20260226-0001   # view details of a specific discovery
```

The import step deduplicates by SHA-256 hash of the raw record bytes, so re-running tests and re-importing is safe.

## Verifying mrrc fixes

When the testbed discovers a bug, this is the full cycle from discovery
through fix verification to permanent regression test.

### 1. Identify the problematic record

After a local-mode test run, import and review discoveries:

```bash
just import
just discoveries
```

Output:

```
ID                        Date         Category           Dataset       Control#
disc-ia-20260226-0042     2026-02-26   truncated_record   ia_lendable   ocm12345678
disc-2026-02-27-001       2026-02-27   malformed_record   ia_lendable   unknown
...
```

Each row is a distinct problematic record. View full details with:

```bash
just show disc-ia-20260226-0042
```

The discovery YAML includes the error message, source dataset, byte offset,
and path to an extracted copy of the record in `state/records/`.

### 2. File the issue

```bash
just report disc-ia-20260226-0042
```

This creates a GitHub issue on `dchud/mrrc` with the error details, source
dataset, reproduction info, and a link back to the testbed discovery.
Copy the issue URL for the promote step later.

### 3. Point testbed at the fix

Once there's a fix in your local mrrc checkout (any branch):

```bash
just use-local-mrrc ../mrrc
```

This patches both the Rust and Python dependencies and confirms the switch:

```
mrrc source: local (/Users/you/mrrc)
  Rust:   mrrc v0.7.3
  Python: mrrc 0.7.3 (/Users/you/mrrc)
```

Check the current state at any time with:

```bash
just mrrc-status
```

### 4. Promote the discovery and verify the fix

```bash
just promote disc-ia-20260226-0042
just test
```

The promote step copies the extracted record into `data/fixtures/edge_cases/`,
making it a permanent regression test. CI tests validate all fixtures parse
cleanly — if the fix works, tests pass.

Optionally link the mrrc issue for provenance:

```bash
just promote disc-ia-20260226-0042 edge_cases --issue=https://github.com/dchud/mrrc/issues/42
```

### 5. Revert to released mrrc

After the fix ships in a new mrrc release, update the version pins in
`Cargo.toml` and `pyproject.toml`, then switch back:

```bash
just use-released-mrrc
just test
```

The promoted fixture stays permanently as a regression test.

## Justfile recipe reference

| Recipe | Description |
|--------|-------------|
| `just setup` | Build Rust, install Python deps, create `.env` |
| `just test` | CI-mode tests (Rust + Python, fixtures only) |
| `just test-local` | Local-mode tests (all datasets) |
| `just test-rust` | Rust CI-mode tests only |
| `just test-python` | Python CI-mode tests only |
| `just test-stress` | Stress tests with verbose output |
| `just bench` | Alias for `test-stress` |
| `just lint` | Check formatting and linting (cargo fmt, clippy, ruff) |
| `just fmt` | Auto-fix formatting |
| `just download NAME` | Download a specific dataset |
| `just download-verify` | Verify all downloaded datasets |
| `just validate` | Validate committed fixtures and manifests |
| `just import` | Import test results to persistent state |
| `just discoveries` | List all discoveries |
| `just show ID` | Show details of a specific discovery |
| `just promote ID [FIXTURE]` | Promote discovery to fixture (default: `edge_cases`) |
| `just report ID` | File an mrrc issue from a discovery (requires `gh`) |
| `just use-local-mrrc [PATH]` | Point testbed at a local mrrc checkout |
| `just use-released-mrrc` | Revert to released mrrc from crates.io / PyPI |
| `just mrrc-status` | Show which mrrc version is active |

## Discovery YAML format

Each discovery in `state/discoveries/` is a YAML file:

```yaml
discovery_id: disc-ia-20260226-0001
discovered_at: '2026-02-26T23:38:23'
discovered_in_run: run-2026-02-26-001
mrrc_version: 0.1.0
test_suite: ia_lendable_discovery
test_name: full_scan
record:
  sha256: f334f844...
  control_number: 8087primer00palm
  source_dataset: ia_lendable
  source_offset: 1039123
  extracted_file: state/records/ia_lendable_0001.mrc
error:
  category: truncated_record
  message: 'Invalid record: Truncated record: expected 930 bytes, got 930'
  mrrc_error: 'Invalid record: Truncated record: expected 930 bytes, got 930'
```

## Run YAML format

Each import creates a run record in `state/runs/`:

```yaml
run_id: run-2026-02-26-001
started_at: '2026-02-27T04:41:01'
completed_at: '2026-02-27T04:41:01'
environment:
  mrrc_version: 0.1.0
results:
  total_records: 233
  new_discoveries: 233
  duplicates_skipped: 0
discovery_ids:
  - disc-ia-20260226-0001
  - disc-ia-20260226-0002
  # ...
```

## Fixture manifest format

Each fixture directory contains a `manifest.json` with provenance for every committed record:

```json
[
  {
    "control_number": "2004436158",
    "source": "LOC Catalog SRU",
    "query": "bath.title=\"history\" and dc.date=\"2003\"",
    "retrieved_at": "2026-02-27T00:15:42",
    "record_index": 0,
    "sha256": "a1b2c3d4..."
  }
]
```

Validate fixture integrity with `just validate`.

## Project structure

```
crates/mrrc_testbed/     Rust test harness (lib + integration tests)
src/mrrc_testbed/        Python package (config, datasets, state, discovery)
suites/                  Python test suites (pymarc compat, encoding, discovery)
scripts/                 CLI tools (download, validate, import, curate)
data/fixtures/           Committed test records with manifest.json provenance
data/downloads/          Gitignored large public datasets
data/local/              Gitignored BYOD data
state/                   Discovery and run YAML files (committed)
results/                 Gitignored per-run output
```

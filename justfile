# mrrc-testbed task runner
# Run `just --list` for available recipes

# Setup — build Rust crate, install Python deps, create .env from template
setup:
    cargo build
    uv sync
    cp -n .env.example .env || true

# Run all CI-mode tests (fixtures only)
test: test-rust test-python

# Run all tests in local mode (downloads + local data)
test-local:
    MRRC_TEST_MODE=local cargo test -- --include-ignored
    MRRC_TEST_MODE=local uv run pytest suites/; status=$?; if [ $status -eq 5 ]; then exit 0; else exit $status; fi

# Run Rust tests only (CI mode)
test-rust:
    cargo test

# Run Python tests only (CI mode)
test-python:
    uv run pytest suites/; status=$?; if [ $status -eq 5 ]; then exit 0; else exit $status; fi

# Run stress tests only (local mode)
test-stress:
    MRRC_TEST_MODE=local cargo test stress -- --include-ignored --nocapture

# Run stress tests with verbose output (benchmarking)
bench:
    MRRC_TEST_MODE=local cargo test stress -- --include-ignored --nocapture

# Lint and format check
lint:
    cargo fmt --check
    cargo clippy -- -D warnings
    uv run ruff check

# Format code (auto-fix)
fmt:
    cargo fmt
    uv run ruff check --fix

# Download a specific dataset
download NAME:
    uv run python scripts/download_datasets.py {{NAME}}

# Verify integrity of all downloaded datasets
download-verify:
    uv run python scripts/download_datasets.py --verify

# Validate committed fixtures and manifests
validate:
    uv run python scripts/validate_fixtures.py --strict

# Import test results from results/discoveries/ into persistent state
import:
    uv run python scripts/import_run.py results/discoveries/

# List new/unreviewed discoveries
discoveries:
    uv run python scripts/import_run.py --list-new

# Show details of a specific discovery
show ID:
    cat state/discoveries/{{ID}}.yaml

# Promote a discovery to a committed fixture
promote ID FIXTURE="edge_cases" *ARGS="":
    uv run python scripts/promote_discovery.py {{ID}} --fixture={{FIXTURE}} {{ARGS}}

# Point testbed at a local mrrc checkout for verification
use-local-mrrc PATH="../mrrc":
    uv run python scripts/set_mrrc_source.py local {{PATH}}

# Revert to released mrrc from crates.io / PyPI
use-released-mrrc:
    uv run python scripts/set_mrrc_source.py released

# Show which mrrc version is active (released vs local)
mrrc-status:
    uv run python scripts/set_mrrc_source.py status

# File an mrrc issue from a discovery
report ID:
    uv run python scripts/report_issue.py {{ID}}

# Regenerate synthetic test data in data/synthetic/
generate-synthetic:
    cd data/synthetic/generators && uv run python generate_all.py

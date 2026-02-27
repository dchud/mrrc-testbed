# Ideas for Test Projects

Testbed design for verifying mrrc functionality. This document is intended for handoff to a project manager to create an implementation plan.

## Overview

A single monorepo (`mrrc-testbed`) containing test suites that exercise mrrc capabilities at scale with real-world data. The testbed supports two modes:

- **CI mode**: Uses small, committed fixture files for fast, reliable automated testing
- **Local mode**: Uses large downloaded datasets and optionally user-provided data (BYOD) for thorough manual validation

### Scope: Real-World Data and Scale Testing

**The testbed focuses exclusively on:**
1. **Real-world data** — Testing against actual MARC records from LOC, Internet Archive, and other sources to discover edge cases that synthetic fixtures miss
2. **Scale testing** — Running against millions of records to surface memory leaks, performance regressions, and concurrency issues invisible at small scale

**The testbed does NOT duplicate:**
- Unit tests for API compatibility (covered by mrrc's `test_pymarc_compatibility.py`)
- Format round-trip correctness (covered by mrrc's `test_format_fidelity.py`)
- Query DSL correctness (covered by mrrc's `test_query_dsl.py`)
- Basic concurrency/GIL tests (covered by mrrc's parallel benchmarks)

The mrrc project already has comprehensive test coverage (~21 test files, 177+ test functions). The testbed extends this by throwing real-world data at mrrc to find bugs that curated fixtures don't expose.

### Testing Layers

The testbed tests mrrc at two levels:

1. **Rust core** (primary focus) — Direct testing of the Rust library using `cargo test` with real-world data and stress tests
2. **Python bindings** (compatibility focus) — Verifying the Python wrapper works correctly, particularly pymarc API compatibility with latest pymarc release

Rust-level testing is the primary focus because:
- Performance-critical code lives in Rust
- Memory safety and concurrency bugs surface at the Rust level
- Rust tests run faster and can use more aggressive fuzzing

Python testing focuses on wrapper correctness and pymarc compatibility, not re-testing Rust logic through Python.

### Dependencies

The testbed consumes mrrc at both layers:

- **Rust**: The `mrrc_testbed` crate depends on the `mrrc` crate via a git dependency in `Cargo.toml`, pinned to a tag (e.g., `mrrc = { git = "https://github.com/dchud/mrrc", tag = "v0.6.0" }`). For local development against an unreleased mrrc, use a `[patch]` override pointing at a local checkout — this is standard Cargo practice and doesn't require editing the committed `Cargo.toml`.
- **Python**: The `mrrc` Python package is installed from the git repo at a pinned tag (e.g., `mrrc @ git+https://github.com/dchud/mrrc@v0.6.0`). For local development, override with an editable install (`uv pip install -e ../mrrc`).

Both approaches pin to a specific release by default and allow local overrides for development. When testing a new mrrc release, update the pinned tag in `Cargo.toml` and `pyproject.toml`.

`pymarc` is pinned to the latest release only. We don't test against older pymarc versions — if pymarc makes breaking API changes, that's a signal to update mrrc's compatibility layer.

### Interaction Models

The testbed supports two distinct usage patterns:

**1. Centralized Testbed (mrrc-testbed repository)**

A single canonical repository that accumulates discoveries over time:
- Maintainer runs periodic large-scale tests against LOC, IA, and other public datasets
- Discoveries are committed to the repo (YAML files)
- Fixtures grow as edge cases are discovered and fixed
- Anyone can clone and run verification tests
- Community can submit discovery PRs (single YAML file + record)

**2. Local/Private Testing (fork or standalone)**

Users can run the testbed privately against their own data without sharing:
- Fork the repo or use it standalone
- Configure custom data paths in `.env`
- Run tests repeatedly over time
- Keep discoveries local (gitignored `results/` directory)
- No obligation to contribute back

Both models use the same tools and workflows — the difference is whether discoveries are committed and shared.

---

## Repository Structure

```
mrrc-testbed/
├── .beads/                     # Beads issue tracking
├── .env.example                # Template for local configuration
├── .gitignore                  # Excludes data/downloads/, .env, etc.
├── Cargo.toml                  # Rust workspace (mrrc as git dependency)
├── pyproject.toml              # uv-managed Python project (mrrc + pymarc deps)
├── uv.lock                     # Locked dependencies
├── justfile                    # Task runner recipes (primary tester interface)
├── README.md                   # Setup, usage, and reference documentation
│
├── data/
│   ├── README.md               # Data sources, licenses, download instructions
│   ├── downloads/              # .gitignored - large datasets go here
│   ├── custom/                 # .gitignored - user's own datasets (BYOD)
│   ├── fixtures/               # Committed - small curated samples (~10MB total)
│   │   ├── bibliographic/      # Sample bibliographic records
│   │   ├── authority/          # Sample authority records
│   │   ├── holdings/           # Sample holdings records
│   │   └── edge_cases/         # Known problematic records
│   └── synthetic/              # Committed - generated test records
│       ├── README.md           # Documents how each was generated
│       ├── malformed/          # Intentionally broken records
│       ├── encoding/           # Encoding test vectors
│       └── generators/         # Scripts that created synthetic data
│
├── state/                      # Cross-run state tracking
│   ├── discoveries/            # Discovery YAML files (committed)
│   │   └── *.yaml
│   ├── runs/                   # Run history YAML files (committed)
│   │   └── *.yaml
│   └── records/                # Extracted problematic records (committed, imported from results/)
│       └── *.mrc
│
├── crates/
│   └── mrrc_testbed/           # Rust test harness crate
│       ├── Cargo.toml
│       ├── src/
│       │   ├── lib.rs          # Test utilities and dataset loading
│       │   ├── config.rs       # Configuration from .env
│       │   ├── datasets.rs     # Dataset abstraction (CI/local switching)
│       │   └── discovery.rs    # DiscoveryWriter for recording findings
│       └── tests/
│           ├── stress.rs       # Memory, throughput, scaling tests
│           ├── malformed.rs    # Error recovery with real bad data
│           ├── encoding.rs     # MARC-8/UTF-8 with international records
│           ├── concurrent.rs   # Thread safety under sustained load
│           └── discovery.rs    # Edge case discovery in real datasets
│
├── src/
│   └── mrrc_testbed/           # Python package
│       ├── __init__.py
│       ├── config.py           # Configuration loading (.env, defaults)
│       ├── datasets.py         # Dataset loading with CI/local switching
│       ├── download.py         # On-demand dataset fetching
│       ├── compare.py          # Deep record comparison utilities
│       └── state.py            # State management (YAML read/write)
│
├── suites/                     # Python test suites (focused on wrapper/compat)
│   ├── conftest.py             # Shared pytest fixtures
│   ├── pymarc_compat/          # pymarc API compatibility at scale
│   ├── encoding/               # Encoding through Python bindings
│   └── discovery/              # Edge case discovery via Python
│
├── scripts/
│   ├── download_datasets.py    # Fetch all/specific datasets
│   ├── validate_fixtures.py    # Verify fixtures valid + manifest in sync
│   ├── curate_fixtures.py      # Initial fixture selection from LOC
│   ├── extract_record.py       # Extract record at byte offset from large file
│   ├── import_run.py           # Import run results (JSON → YAML), update state
│   └── promote_discovery.py    # Promote discovery to fixture
│
├── results/                    # .gitignored - local test results
│   └── .gitkeep
│
└── .github/
    └── workflows/
        └── ci.yml              # CI workflow (fixtures only, see CI section)
```

### CI Workflow Summary

The CI workflow runs on every PR and push to main. It uses only committed data (fixtures + synthetic):

1. **Validate fixtures** — `validate_fixtures.py --strict` (manifest sync, size budget)
2. **Rust tests** — `cargo test` (CI mode, fixtures only)
3. **Python tests** — `uv run pytest suites/` (CI mode, fixtures only)
4. **Lint/format** — `cargo fmt --check`, `cargo clippy`, `ruff check`

All local-mode tests are skipped in CI via `#[ignore]` / `@pytest.mark.local`.

---

## Data Management Strategy

### Principle: Never commit downloaded public data

Large public datasets (LOC, Internet Archive, etc.) are **never** committed to git. Instead:

1. **Configuration points to local copies** via `.env` file
2. **Download scripts** fetch data on demand to `data/downloads/`
3. **CI uses committed fixtures** only - small, curated samples

### Four categories of test data

| Category | Location | In Git? | Purpose |
|----------|----------|---------|---------|
| **Downloaded** | `data/downloads/` | No | Large public datasets for thorough local testing |
| **Custom (BYOD)** | `data/custom/` | No | User's own MARC files for local testing |
| **Fixtures** | `data/fixtures/` | Yes | Small curated samples for CI and quick tests |
| **Synthetic** | `data/synthetic/` | Yes | Generated records for specific test scenarios |

### Bring Your Own Dataset (BYOD)

Users can test mrrc against their own MARC data in local mode. Custom datasets are just another data source available when running locally — no separate mode needed.

```bash
# Place your MARC files in the custom directory
cp /path/to/my_library.mrc data/custom/

# Or configure paths in .env
echo "MRRC_CUSTOM_DATASET=/path/to/my_library.mrc" >> .env

# Run tests in local mode (picks up custom data automatically)
MRRC_TEST_MODE=local uv run pytest suites/
MRRC_TEST_MODE=local cargo test
```

**Custom dataset configuration:**

```bash
# .env
# Point to individual custom files
MRRC_CUSTOM_DATASET=/path/to/my_records.mrc
MRRC_CUSTOM_AUTHORITY=/path/to/my_authorities.mrc

# Or point to a directory containing multiple .mrc files
MRRC_CUSTOM_DIR=/path/to/my_marc_collection/

# Custom dataset metadata (optional, for reporting)
MRRC_CUSTOM_NAME="My Library Catalog"
MRRC_CUSTOM_RECORD_COUNT=500000
```

The dataset abstraction layer resolves data sources in local mode with a priority cascade:

```python
# src/mrrc_testbed/datasets.py

def get_dataset(name: str = "default"):
    """
    Returns path to dataset based on mode and availability.

    In local mode, priority order:
    1. Custom dataset (if configured in .env)
    2. Downloaded dataset (if available in data/downloads/)
    3. Fixture dataset (always available, fallback)

    In CI mode:
    1. Fixture dataset only
    """
    mode = get_test_mode()

    if mode == "local":
        # Check custom paths first (BYOD)
        custom_path = get_custom_dataset_path(name)
        if custom_path and custom_path.exists():
            return custom_path

        # Then downloaded public datasets
        download_path = get_download_path(name)
        if download_path and download_path.exists():
            return download_path

    # Fall back to fixture (CI mode always lands here)
    return FIXTURES_DIR / name / "sample.mrc"
```

```rust
// crates/mrrc_testbed/src/datasets.rs

pub fn get_dataset(name: &str) -> Result<PathBuf, DatasetError> {
    let mode = TestMode::from_env();

    match mode {
        TestMode::Local => {
            // Custom paths first, then downloads, then fixtures
            get_custom_dataset(name)
                .or_else(|| get_download_path(name))
                .or_else(|| get_fixture_path(name))
                .ok_or_else(|| DatasetError::NotFound(name.to_string()))
        }
        TestMode::Ci => {
            get_fixture_path(name)
                .ok_or_else(|| DatasetError::NotFound(name.to_string()))
        }
    }
}
```

### Configuration via `.env`

```bash
# .env.example (committed)
# Copy to .env and customize (not committed)

# Test mode: "ci" (fixtures only) or "local" (downloads + custom data)
MRRC_TEST_MODE=local

# Dataset locations - absolute paths to downloaded data
MRRC_LOC_BOOKS=/path/to/loc_books_all.mrc
MRRC_LOC_NAMES=/path/to/loc_names.mrc
MRRC_LOC_SUBJECTS=/path/to/loc_subjects.mrc
MRRC_IA_LENDABLE=/path/to/ia_lendable.mrc
MRRC_WATSON=/path/to/watson_library.mrc

# Or use the downloads directory
MRRC_DOWNLOADS_DIR=/path/to/mrrc-testbed/data/downloads

# Custom datasets (BYOD) - used in local mode, takes priority over downloads
MRRC_CUSTOM_DATASET=/path/to/my_records.mrc
MRRC_CUSTOM_DIR=/path/to/my_collection/
```

### `.gitignore` essentials

```gitignore
# Local configuration
.env

# Downloaded datasets (never commit)
data/downloads/

# Custom datasets (never commit)
data/custom/

# Local test results
results/

# Rust build artifacts
target/

# Python artifacts
__pycache__/
*.pyc
.pytest_cache/
.venv/
```

### Synthetic data policy

Synthetic records in `data/synthetic/` **are committed** because:
- They're small (intentionally minimal for specific test cases)
- They need version control (changes affect test expectations)
- They document edge cases (each has accompanying documentation)
- They're reproducible (generator scripts are included)

Each synthetic dataset includes a README explaining:
- What it tests
- How it was generated
- Expected behavior when processed

### Fixture Curation Strategy

Committed fixtures (~1000 records, ~10MB) are sourced from **Library of Congress** data exports, which are US government works in the public domain.

**Selection approach:**

Two complementary methods:

1. **Random sampling** — Randomly select ~500 records from LOC Books All to get natural distribution of real-world patterns
2. **Targeted selection** — Select ~500 records that exercise specific MARC aspects:
   - Various record types (books, serials, maps, music, etc.)
   - Different encoding levels
   - Complex field structures (many subfields, repeated fields)
   - International content (CJK, Cyrillic, diacritics)
   - Edge cases discovered during testing

**Provenance tracking:**

Every committed fixture record includes provenance metadata. This is critical for:
- Crediting data sources appropriately
- Reproducing issues with original records
- Verifying fixtures against updated source data
- Legal clarity on data licensing

Provenance is tracked via a manifest file:

```
data/fixtures/
├── bibliographic/
│   ├── sample.mrc           # The actual records
│   └── manifest.json        # Provenance for each record
├── authority/
│   ├── sample.mrc
│   └── manifest.json
└── edge_cases/
    ├── sample.mrc
    └── manifest.json
```

**Manifest format:**

```json
{
  "source": "Library of Congress Books All",
  "source_url": "https://www.loc.gov/cds/products/marcDist.php",
  "download_date": "2024-01-15",
  "license": "Public Domain (US Government Work)",
  "records": [
    {
      "index": 0,
      "control_number": "12345678",
      "source_offset": 1048576,
      "selection_reason": "random_sample",
      "notes": null
    },
    {
      "index": 1,
      "control_number": "87654321",
      "source_offset": 2097152,
      "selection_reason": "targeted:cjk_content",
      "notes": "Contains CJK characters in 245$a"
    },
    {
      "index": 42,
      "control_number": "11223344",
      "source_offset": null,
      "source_file": "ia_lendable_books.mrc",
      "selection_reason": "edge_case:discovered",
      "notes": "Truncated directory - discovered in malformed.rs testing",
      "discovered_by": "testbed discovery run 2024-02-01",
      "mrrc_issue": "https://github.com/dchud/mrrc/issues/123"
    }
  ]
}
```

**Selection reasons:**
- `random_sample` — Randomly selected from source
- `targeted:<aspect>` — Selected to test specific aspect (e.g., `targeted:cjk_content`, `targeted:many_subfields`)
- `edge_case:discovered` — Discovered during testbed runs, promoted to fixture
- `edge_case:reported` — Reported by user, added to fixtures

### Initial Fixture Curation

The `curate_fixtures.py` script handles initial fixture population:

```bash
# Random sample from LOC Books All
uv run python scripts/curate_fixtures.py \
    --source /path/to/loc_books_all.mrc \
    --output data/fixtures/bibliographic/ \
    --count 500 \
    --method random \
    --source-name "Library of Congress Books All" \
    --source-url "https://www.loc.gov/cds/products/marcDist.php"

# Targeted selection (interactive or via criteria file)
uv run python scripts/curate_fixtures.py \
    --source /path/to/loc_books_all.mrc \
    --output data/fixtures/bibliographic/ \
    --count 500 \
    --method targeted \
    --criteria criteria/bibliographic_coverage.json
```

**Targeted selection criteria file:**

```json
{
  "criteria": [
    {"name": "cjk_content", "count": 50, "filter": "has_cjk_in_245"},
    {"name": "cyrillic_content", "count": 30, "filter": "has_cyrillic"},
    {"name": "many_subfields", "count": 30, "filter": "max_subfields > 20"},
    {"name": "long_fields", "count": 30, "filter": "max_field_length > 5000"},
    {"name": "serials", "count": 50, "filter": "leader[7] == 's'"},
    {"name": "maps", "count": 30, "filter": "leader[6] == 'e'"},
    {"name": "music", "count": 30, "filter": "leader[6] in ['c', 'd', 'j']"},
    {"name": "pre_1900", "count": 50, "filter": "pub_year < 1900"},
    {"name": "authority_links", "count": 50, "filter": "has_field('100') and subfield_count('100', '0') > 0"},
    {"name": "complex_subjects", "count": 50, "filter": "field_count('650') > 5"},
    {"name": "mixed_scripts", "count": 50, "filter": "has_mixed_scripts_in_245"},
    {"name": "many_fields", "count": 50, "filter": "field_count > 50"}
  ]
}
```

The script generates manifest.json automatically with full provenance.

### Record Extraction Utility

Extracting a single record from a multi-GB file at a known byte offset:

```bash
# Extract record at offset 1234567 from large file
uv run python scripts/extract_record.py \
    /path/to/large_file.mrc \
    --offset 1234567 \
    --output extracted_record.mrc

# Extract by control number (slower - scans file)
uv run python scripts/extract_record.py \
    /path/to/large_file.mrc \
    --control-number "ocm12345678" \
    --output extracted_record.mrc

# Extract and display info without saving
uv run python scripts/extract_record.py \
    /path/to/large_file.mrc \
    --offset 1234567 \
    --info
```

This is essential for reproducing issues found during discovery runs.

### Fixture Validation and Size Monitoring

The `validate_fixtures.py` script enforces fixture integrity:

```bash
# Full validation
uv run python scripts/validate_fixtures.py

# Output:
# Validating data/fixtures/bibliographic/...
#   ✓ sample.mrc: 523 records, 4.2 MB
#   ✓ manifest.json: 523 entries, all records accounted for
#   ✓ No orphaned manifest entries
#   ✓ No untracked records in .mrc file
# Validating data/fixtures/edge_cases/...
#   ✓ sample.mrc: 47 records, 892 KB
#   ✓ manifest.json: 47 entries, all records accounted for
#
# Total fixture size: 8.7 MB (target: <10 MB)
# Status: OK
```

**Validation checks:**

1. **Manifest sync** — Every record in .mrc has a manifest entry, and vice versa
2. **Control number match** — Manifest control_number matches actual record
3. **Size budget** — Total fixtures under 10MB target (warning at 8MB, error at 10MB)
4. **Provenance completeness** — Every record has source, selection_reason
5. **Record validity** — All records parse without error

**CI integration:**

```yaml
# .github/workflows/ci.yml
- name: Validate fixtures
  run: uv run python scripts/validate_fixtures.py --strict
```

Fails CI if fixtures are invalid or over size budget.

---

## CI vs Local Testing

### CI Mode (GitHub Actions)

**Characteristics:**
- Uses only committed fixtures (`data/fixtures/`, `data/synthetic/`)
- Fast execution (target: <10 minutes)
- Runs on every PR and push to main
- No external downloads during CI
- Validates that testbed infrastructure works

**What CI tests:**
- Rust test harness compiles and runs with fixtures
- Python test infrastructure works
- Synthetic malformed record handling
- Basic encoding test vectors

**What CI skips:**
- Large-scale stress tests
- Memory leak detection (requires sustained load)
- Concurrency scaling tests
- Real-world dataset coverage

### Local Mode (Developer workstation)

**Characteristics:**
- Uses full downloaded datasets, plus any custom (BYOD) data configured in `.env`
- Thorough testing (may take hours for full suite)
- Run manually before releases or when investigating issues
- Catches issues that only appear at scale

**What local mode adds:**
- Memory profiling over millions of records
- Concurrency scaling (1-16+ threads)
- Real-world malformed record discovery
- Full encoding coverage from international data
- Performance benchmarks at scale
- Validation against institutional data (if BYOD configured)

### Switching modes

```bash
# CI mode (default if MRRC_TEST_MODE not set)
cargo test
uv run pytest suites/

# Local mode with full datasets (+ custom data if configured)
MRRC_TEST_MODE=local cargo test
MRRC_TEST_MODE=local uv run pytest suites/

# Or set in .env file
echo "MRRC_TEST_MODE=local" >> .env
```

---

## Reporting

Test output is the report. Both `cargo test` and `pytest` produce readable output directly; no separate report generation step is needed.

**CI:** Standard test output in GitHub Actions — green/red checks visible in PRs, failure details in CI logs.

**Local:** Use verbose flags for detailed output:

```bash
# Run Rust tests
cargo test

# Run Rust tests with local datasets
MRRC_TEST_MODE=local cargo test

# Run Rust stress tests only
MRRC_TEST_MODE=local cargo test stress

# Run Python tests
uv run pytest suites/

# Run with verbose output
cargo test -- --nocapture
uv run pytest suites/ -v
```

Discovery tests print an actionable summary to stdout when they finish (see "Rust Discovery Output" in Test Suites). This summary is the primary way testers see what was found.

---

## Public MARC Datasets

### Primary sources

| Short Name | Source | URL | Size | Records | Best For |
|------------|--------|-----|------|---------|----------|
| `loc_books` | **LOC Books All** | https://www.loc.gov/cds/products/marcDist.php | ~15GB | ~25M | Stress, scale testing |
| `loc_names` | **LOC Name Authority** | https://www.loc.gov/cds/products/marcDist.php | ~5GB | ~10M | Authority testing |
| `loc_subjects` | **LOC Subject Authority** | https://www.loc.gov/cds/products/marcDist.php | ~200MB | ~400K | Authority testing |
| `ia_lendable` | **Internet Archive Lendable** | https://archive.org/details/marc_lendable_books | ~1GB | ~1.4M | Malformed discovery, encoding |
| `watson` | **Watson Library (Met)** | https://github.com/Thomas-J-Watson-Library/Marc-Record-Sets | ~100MB | ~200K | Quick local testing |

These short names are used throughout the testbed: in `just download`, `.env` variable names (`MRRC_WATSON`, `MRRC_IA_LENDABLE`, etc.), dataset abstraction calls (`get_dataset("watson")`), and discovery/run YAML files.

### Supplementary sources for encoding tests (future)

The initial focus is US library data (LOC, IA, Watson), which already contains substantial international content — LOC catalogs materials in hundreds of languages. If encoding coverage proves insufficient, these international sources could be added later:

| Source | Content | Notes |
|--------|---------|-------|
| **National Diet Library (Japan)** | CJK records | May require account |
| **Deutsche Nationalbibliothek** | German diacritics | Free access |
| **Russian State Library** | Cyrillic | Check licensing |

### Download script usage

```bash
# List available datasets
uv run python scripts/download_datasets.py --list

# Download specific dataset
uv run python scripts/download_datasets.py watson

# Download all primary datasets (large!)
uv run python scripts/download_datasets.py --all

# Verify downloads
uv run python scripts/download_datasets.py --verify
```

---

## Test Suites

### Rust Test Suites (Primary)

#### `stress.rs` - Scale and Memory Testing

**Purpose:** Validate performance and memory behavior at production scale. This is where bugs invisible at small scale surface.

**Focus:** Issues that only appear with millions of records:
- Cumulative memory leaks (1KB/record = 25GB leak on LOC)
- Unbounded queue/buffer growth
- Allocator fragmentation under sustained load
- Thread pool exhaustion
- File handle leaks

**Key tests:**
| Test | CI | Local | Description |
|------|-----|-------|-------------|
| `memory_stability` | Skip | Full | No memory growth over 10M+ records |
| `throughput_sustained` | Skip | Full | Stable throughput over extended runs |
| `thread_scaling` | Skip | Full | Near-linear scaling to core count |
| `resource_cleanup` | Basic | Full | No leaked handles/buffers |

**Success criteria:**
- Memory stable (±5%) over extended runs
- No resource leaks after processing completes
- Throughput remains stable (no degradation over time)

---

#### `malformed.rs` - Error Recovery Discovery

**Purpose:** Discover real-world malformed record patterns and verify graceful handling.

**Focus:** Finding unknown malformed patterns in real data, not testing known synthetic cases (mrrc unit tests can cover those).

**Key tests:**
| Test | CI | Local | Description |
|------|-----|-------|-------------|
| `discover_malformed_patterns` | Skip | Full | Catalog malformed records in IA Lendable |
| `no_panics` | Basic | Full | No panics on any input |
| `error_messages_useful` | Basic | Full | Errors identify the problem |

**Discovered malformed patterns are cataloged:**
```rust
// Malformed pattern discovered in IA Lendable
// Record offset: 1234567, Pattern: truncated_directory
// Details: Directory ends mid-entry at byte 45
```

**Success criteria:**
- No crashes or panics on any real-world input
- Catalog of malformed patterns discovered
- Error messages identify specific problems

---

#### `encoding.rs` - International Character Testing

**Purpose:** Verify MARC-8 and UTF-8 handling with real international records.

**Focus:** Real international records from LOC and other available sources, not synthetic test vectors.

**Key tests:**
| Test | CI | Local | Description |
|------|-----|-------|-------------|
| `cjk_roundtrip` | Skip | Full | CJK records from LOC and IA |
| `cyrillic_roundtrip` | Skip | Full | Cyrillic records from LOC |
| `diacritics_roundtrip` | Skip | Full | European diacritics from LOC |
| `mixed_encoding` | Skip | Full | Records mixing MARC-8 and UTF-8 |

**Success criteria:**
- No mojibake in round-trips of real international records
- Encoding detection works on real data
- Combining characters handled properly

---

#### `concurrent.rs` - Thread Safety at Scale

**Purpose:** Verify thread safety under sustained parallel load.

**Focus:** Race conditions and deadlocks that only surface under sustained load, not basic thread safety (covered by mrrc unit tests).

**Key tests:**
| Test | CI | Local | Description |
|------|-----|-------|-------------|
| `sustained_parallel_read` | Skip | Full | 16+ threads for 10M+ records |
| `producer_consumer_stress` | Skip | Full | Pipeline under sustained load |
| `no_data_corruption` | Skip | Full | Verify data integrity under load |

**Success criteria:**
- No race conditions or data corruption
- No deadlocks under sustained load
- Stable performance across thread counts

---

#### `discovery.rs` - Edge Case Discovery

**Purpose:** Systematically discover edge cases in real-world data.

**Focus:** Finding unusual patterns that break assumptions.

**Key tests:**
| Test | CI | Local | Description |
|------|-----|-------|-------------|
| `unusual_field_combinations` | Skip | Full | Rare field patterns in LOC |
| `extreme_values` | Skip | Full | Unusually long fields, many subfields |
| `encoding_edge_cases` | Skip | Full | Unusual encoding patterns |

**Output:** Catalog of discovered edge cases for potential addition to mrrc test fixtures.

#### Rust Discovery Output

Rust tests use a shared discovery library to output findings in the standard JSON format:

```rust
// crates/mrrc_testbed/src/discovery.rs

use crate::discovery::{Discovery, DiscoveryWriter};

#[test]
fn discover_malformed_patterns() {
    let mut writer = DiscoveryWriter::new("malformed.rs", "discover_malformed_patterns");

    let dataset = get_dataset("ia_lendable").unwrap();
    let mut reader = MarcReader::new(File::open(&dataset).unwrap());
    let mut offset = 0u64;

    loop {
        match reader.read_record() {
            Ok(Some(record)) => {
                offset = reader.position();
            }
            Ok(None) => break,  // EOF
            Err(e) => {
                // Record the discovery
                writer.record_error(
                    &dataset,
                    offset,
                    reader.last_raw_bytes(),  // Raw bytes of problematic record
                    &e,
                );
                // Continue to next record
                offset = reader.position();
            }
        }
    }

    // Write discoveries to results/discoveries/
    writer.finalize().unwrap();
}
```

The `DiscoveryWriter` handles:
- Extracting problematic records to individual .mrc files
- Computing sha256 for deduplication
- Writing JSON in the standard format to `results/discoveries/`
- Printing a human-readable summary to stdout when `finalize()` is called

**What the tester sees after a discovery run:**

```
Discovery run complete (malformed.rs::discover_malformed_patterns):
  Dataset: ia_lendable (1,423,567 records)
  Errors found: 47
  New patterns: 12 (wrote to results/discoveries/)
  Duplicates skipped: 35
  Run: just import → just discoveries to review
```

The final line tells the tester what to do next. All discovery tests should print this kind of actionable summary rather than just pass/fail.

---

### Python Test Suites (Compatibility Focus)

#### `pymarc_compat/` - API Compatibility with Real Data

**Purpose:** Verify pymarc API compatibility holds up with real-world data patterns.

**Focus:** Testing against latest pymarc release only. Verifies that real-world usage patterns work through the Python bindings.

**Key tests:**
| Test | CI | Local | Description |
|------|-----|-------|-------------|
| `test_real_scripts.py` | Skip | Full | Port actual pymarc scripts from the wild |
| `test_iteration_scale.py` | Skip | Full | Iterator behavior over large files |

**Success criteria:**
- Real pymarc scripts work unmodified with mrrc
- No behavioral differences at scale

---

#### `encoding/` - Encoding Through Python Bindings

**Purpose:** Verify encoding handling works correctly through Python bindings.

**Key tests:**
| Test | CI | Local | Description |
|------|-----|-------|-------------|
| `test_string_handling.py` | Skip | Full | Unicode strings from real records |

---

#### `discovery/` - Edge Case Discovery via Python

**Purpose:** Python-friendly interface for cataloging discovered edge cases.

---

## Development Workflow

### Initial setup

```bash
git clone https://github.com/dchud/mrrc-testbed.git
cd mrrc-testbed
just setup    # cargo build, uv sync, copy .env.example → .env
```

### Justfile recipes

The justfile provides a single entry point for all common operations. Testers shouldn't need to remember raw `cargo`/`uv`/`python scripts/` incantations for standard workflows.

```just
# Setup
setup:          cargo build && uv sync && cp -n .env.example .env

# Testing
test:           cargo test && uv run pytest suites/
test-local:     MRRC_TEST_MODE=local cargo test && MRRC_TEST_MODE=local uv run pytest suites/
test-rust:      cargo test
test-python:    uv run pytest suites/
test-stress:    MRRC_TEST_MODE=local cargo test stress
bench:          MRRC_TEST_MODE=local cargo test stress -- --nocapture
lint:           cargo fmt --check && cargo clippy && uv run ruff check

# Data
download NAME:  uv run python scripts/download_datasets.py {{NAME}}
download-verify: uv run python scripts/download_datasets.py --verify
validate:       uv run python scripts/validate_fixtures.py --strict

# Discovery workflow
import:         uv run python scripts/import_run.py results/discoveries/
discoveries:    uv run python scripts/import_run.py --list-new
show ID:        cat state/discoveries/{{ID}}.yaml
```

### Typical tester session

This is the end-to-end flow a tester follows, from first clone to understanding results.

**1. Verify everything works with fixtures:**

```bash
just test     # runs CI-mode tests against committed fixtures
```

All tests should pass. This confirms the testbed infrastructure is working.

**2. Download a dataset and run local tests:**

```bash
just download watson         # smallest dataset, ~100MB, good starting point
just test-local              # runs all suites against downloaded data
```

For discovery-focused testing, start with Internet Archive Lendable (`just download ia_lendable`) — it has the highest density of malformed records.

**3. Review what tests found:**

After local-mode tests complete, discovery tests print a summary to stdout:

```
Discovery run complete:
  Records processed: 1,423,567
  Errors found: 47
  New discoveries: 12 (wrote to results/discoveries/)
  Duplicates skipped: 35
```

Raw JSON output is in `results/discoveries/`. To import into persistent state:

```bash
just import                  # reads results/discoveries/, deduplicates, writes YAML to state/
just discoveries             # list new discoveries
just show disc-2024-02-01-001   # details on a specific discovery
```

Each discovery YAML file contains the error details, source dataset, byte offset, and an extracted copy of the problematic record — everything needed to file an issue manually or reproduce the problem.

**4. Point at your own data (optional):**

Add BYOD paths to `.env` and re-run. No mode change needed — local mode picks up custom paths automatically:

```bash
echo "MRRC_CUSTOM_DATASET=/path/to/my_records.mrc" >> .env
just test-local
just import
just discoveries
```

### Downloading datasets

```bash
just download watson         # Watson Library (Met), ~100MB — good starting point
just download ia_lendable    # Internet Archive Lendable, ~1GB — best for malformed discovery
just download loc_books      # LOC Books All, ~15GB — for stress/scale testing
just download-verify         # verify all downloads
```

### Adding new tests

1. For Rust tests: Add to appropriate file in `crates/mrrc_testbed/tests/`
2. For Python tests: Add to appropriate directory in `suites/`
3. Use dataset abstraction for data access (handles CI/local switching)
4. Mark tests requiring local mode with `#[ignore]` (Rust) or `@pytest.mark.local` (Python)
5. Document any discovered edge cases

---

## Edge Case to Issue Workflow

When the testbed discovers a record that breaks mrrc (or exhibits unexpected behavior), the goal is to make it easy to understand what happened and reproduce the problem.

### Two-stage discovery pipeline

Discovery data flows through two stages:

1. **Test output (ephemeral)**: Tests write JSON to `results/discoveries/` — gitignored, per-run, includes raw records. This is the immediate output of `cargo test` and `pytest`.
2. **Persistent state (committed)**: `import_run.py` reads the JSON output, deduplicates against existing discoveries by sha256, and writes YAML to `state/discoveries/` — git-tracked, accumulates across runs, serves as the source of truth.

Separating these stages means tests can run without touching shared state, and imports are explicit, reviewable operations.

### Discovery output format

When tests discover problematic records, they write structured JSON to `results/discoveries/` (gitignored):

```
results/discoveries/
├── 2024-02-01_malformed_discovery.json
├── 2024-02-01_encoding_issues.json
└── records/                      # Extracted problematic records
    ├── disc-2024-02-01-001.mrc
    └── disc-2024-02-01-002.mrc
```

**Discovery record format:**

```json
{
  "discovery_id": "disc-2024-02-01-001",
  "discovered_at": "2024-02-01T14:32:00Z",
  "test_suite": "malformed.rs",
  "test_name": "discover_malformed_patterns",
  "source_dataset": "ia_lendable",
  "source_file": "/path/to/ia_lendable_books.mrc",
  "record": {
    "offset_bytes": 1234567,
    "control_number": "ocm12345678",
    "raw_bytes_base64": "MDEyMzQ1Njc4OTAxMjM0NTY3ODkw...",
    "sha256": "a1b2c3d4...",
    "extracted_to": "results/discoveries/records/disc-2024-02-01-001.mrc"
  },
  "error": {
    "category": "malformed_record",
    "message": "Directory ends mid-entry at byte 45",
    "mrrc_error": "ParseError::InvalidDirectory"
  },
  "context": {
    "mrrc_version": "0.6.0",
    "rust_version": "1.75.0",
    "os": "linux-x86_64"
  }
}
```

### Deduplication

The `import_run.py` script deduplicates discoveries by record sha256 when importing from `results/` to `state/`. If the same record (by content hash) already exists in `state/discoveries/`, the new occurrence is skipped. This prevents the same problematic record from being recorded multiple times across runs.

### Filing issues

Issues are filed manually. Each discovery YAML file in `state/discoveries/` contains everything needed:

1. **Error details**: What went wrong and the mrrc error type
2. **Extracted record**: The `.mrc` file in `state/records/`, ready to attach or base64-encode
3. **Provenance**: Source dataset, byte offset, control number for reproduction
4. **Environment**: mrrc version, Rust version, OS

Copy the relevant details into a new issue at https://github.com/dchud/mrrc/issues.

### Promoting discoveries to fixtures

After an issue is fixed in mrrc, the problematic record can be promoted to committed fixtures for regression testing:

```bash
uv run python scripts/promote_discovery.py disc-2024-02-01-001 \
    --fixture=edge_cases \
    --issue https://github.com/dchud/mrrc/issues/123
```

This copies the record to `data/fixtures/edge_cases/sample.mrc`, updates `manifest.json` with provenance (source dataset, discovery date, issue link), and runs `validate_fixtures.py` to ensure consistency.

### Workflow summary

```
Run tests → Review discoveries → File issue manually → Fix in mrrc → Promote to fixture
```

Every step after running tests is optional. The testbed's job is to find problems and record them clearly; what happens next is up to the operator.

---

## State Management

Running the testbed repeatedly over time requires tracking state across runs: which discoveries are new vs. duplicates. State is stored as YAML files — human-readable, git-friendly, and simple.

```
state/
├── discoveries/           # YAML files (git-tracked)
│   ├── disc-2024-02-01-001.yaml
│   ├── disc-2024-02-01-002.yaml
│   └── ...
├── runs/                  # YAML files (git-tracked)
│   ├── run-2024-02-01-001.yaml
│   └── ...
└── records/               # Extracted problematic .mrc files (git-tracked)
    └── disc-2024-02-01-001.mrc
```

### Discovery YAML

```yaml
# state/discoveries/disc-2024-02-01-001.yaml
discovery_id: disc-2024-02-01-001
discovered_at: 2024-02-01T14:32:00Z
discovered_in_run: run-2024-02-01-001
mrrc_version: 0.6.0
test_suite: malformed.rs
test_name: discover_malformed_patterns

record:
  sha256: a1b2c3d4e5f6...
  control_number: ocm12345678
  source_dataset: ia_lendable
  source_offset: 1234567
  extracted_file: state/records/disc-2024-02-01-001.mrc

error:
  category: malformed_record
  message: "Directory ends mid-entry at byte 45"
  mrrc_error: "ParseError::InvalidDirectory"
```

Note: `import_run.py` normalizes field names when converting from JSON output to YAML state (e.g., `offset_bytes` → `source_offset`, `extracted_to` → `extracted_file`). Run-level metadata (Rust version, OS) is stored in the Run YAML, not repeated per discovery.

### Run YAML

```yaml
# state/runs/run-2024-02-01-001.yaml
run_id: run-2024-02-01-001
started_at: 2024-02-01T14:00:00Z
completed_at: 2024-02-01T16:30:00Z

environment:
  mrrc_version: 0.6.0
  rust_version: 1.75.0
  python_version: 3.12.1
  os: linux-x86_64

datasets:
  - name: ia_lendable
    records_processed: 1423567

results:
  total_records: 1423567
  errors_found: 47
  new_discoveries: 12
  duplicate_discoveries: 35

discoveries:
  - disc-2024-02-01-001
  - disc-2024-02-01-002
```

### Importing Results

```bash
# After a run, import results and update state
just import

# Output:
# Importing run results...
#   Total errors found: 47
#   New discoveries: 12
#   Duplicates skipped: 35
#
# Updated state/discoveries/ (12 new files)
# Updated state/runs/run-2024-02-01-001.yaml
```

### Centralized vs Local State

**Centralized (mrrc-testbed repo):**
- `state/discoveries/*.yaml` — Committed, shared
- `state/runs/*.yaml` — Committed
- `state/records/*.mrc` — Committed

**Local/Private use (fork):**
- Same structure, but gitignored or kept in a private fork
- No obligation to share discoveries

---

## Documentation

The project uses `README.md` as its primary documentation. A separate documentation site is not needed for the expected audience (mrrc developers and evaluators).

The README covers:
- What the testbed is and what it tests (scope)
- Setup instructions (`just setup`)
- Running tests in CI and local modes
- Downloading datasets
- Using your own data (BYOD)
- Understanding discovery output
- Justfile recipe reference
- Discovery and run YAML format reference
- Fixture provenance and manifest format

---

## Project Management

### Using beads for issue tracking

The testbed uses beads for tracking work:

```bash
# Initialize beads (done once during repo setup)
br init

# View available work
br ready

# Create new issue
br create --title="Implement Rust stress suite" --type=task --priority=2

# Start work
br update beads-xxx --status=in_progress

# Complete work
br close beads-xxx

# Sync with git
br sync --flush-only
```

### Implementation plan

The plan below is structured for conversion into beads epics, sub-epics, and tasks. Each phase maps to an epic. Dependencies are marked explicitly — items without a dependency marker depend only on their parent phase's prerequisites. Parallel tracks within a phase are called out.

Three **review gates** separate the phases. A gate is a code review epic that blocks all downstream work: the reviewer assesses everything completed so far, files blocker beads on anything that needs fixing, and the gate doesn't open until all blockers are resolved. This prevents compounding errors across phases.

---

**Phase 1: Repository Scaffold** (epic)

Everything else depends on this. Goal: `just setup` builds the empty crate and installs Python deps; `just test` runs placeholder tests. No real implementation — just structure.

- 1.1: Initialize repo structure — directory tree, Cargo workspace with empty crate, pyproject.toml, .gitignore, .env.example
- 1.2: Create justfile with setup, test, lint recipes [depends on 1.1]
- 1.3: Set up CI workflow skeleton [depends on 1.1, 1.2]

---

**Phase 2: Test Infrastructure** (epic) [blocked by Phase 1]

The shared machinery that all test suites use. Two parallel tracks:

- 2a: Rust test harness (sub-epic)
  - 2a.1: Configuration and dataset abstraction — config.rs, datasets.rs
  - 2a.2: Crate entry point and test utilities — lib.rs [depends on 2a.1]
  - 2a.3: DiscoveryWriter — discovery.rs [depends on 2a.2]
- 2b: Python test infrastructure (sub-epic)
  - 2b.1: Python package — config.py, datasets.py, download.py, compare.py
  - 2b.2: conftest.py with shared pytest fixtures [depends on 2b.1]
  - 2b.3: download_datasets.py script — CLI for fetching public datasets [depends on 2b.1]

Tracks 2a and 2b can proceed in parallel.

---

> **REVIEW GATE A: Foundation Review** (epic) [blocked by Phase 2]
>
> Scope: Repo structure, configuration, dataset abstraction, test harness, DiscoveryWriter, Python infrastructure. Everything built so far.
>
> Key questions: Is the project structure sound? Does the dataset abstraction handle all three data categories cleanly? Is the DiscoveryWriter output format right — it defines the data model that everything downstream consumes? Is the CI workflow green?
>
> Blocks: Phases 3, 4, 5.

---

**Phase 3: Discovery Pipeline** (epic) [blocked by Gate A]

The state management system and import tooling. This defines the persistent data model — getting it wrong here is expensive to fix later. Depends on DiscoveryWriter (2a.3) for the JSON format that import_run.py consumes.

- 3.1: Implement discovery and run YAML schemas
- 3.2: Implement state.py library module and import_run.py — YAML read/write, sha256 deduplication, JSON → YAML import [depends on 3.1]
- 3.3: Add justfile recipes — import, discoveries, show [depends on 3.2]

---

**Phase 4: Test Suites** (epic) [blocked by Gate A]

The actual tests. Two parallel sub-epics; all items within each are independent of each other. Each test module creates its associated synthetic test data in `data/synthetic/` as part of implementation (generator scripts + generated records are committed together). All Rust tests use the harness from 2a; all Python tests use the infrastructure from 2b.

- 4a: Rust test suites (sub-epic)
  - 4a.1: stress.rs — memory and scaling
  - 4a.2: malformed.rs — error recovery discovery
  - 4a.3: discovery.rs — edge case cataloging
  - 4a.4: encoding.rs — international character testing
  - 4a.5: concurrent.rs — sustained parallel load
- 4b: Python test suites (sub-epic)
  - 4b.1: pymarc_compat/ — real script compatibility
  - 4b.2: encoding/ — encoding through bindings
  - 4b.3: discovery/ — edge case discovery via Python

---

**Phase 5: Fixture Tooling** (epic) [blocked by Gate A]

Fixture curation, validation, extraction, and promotion scripts. All scripts use the dataset abstraction from Phase 2. Independent of the discovery pipeline and test suites except for `promote_discovery.py`, which reads discovery YAML.

- 5.1: curate_fixtures.py — initial fixture selection
- 5.2: validate_fixtures.py — fixture validation
- 5.3: extract_record.py — record extraction utility
- 5.4: promote_discovery.py — promote discovery to fixture [depends on 3.1]

**Phases 3, 4, and 5 can all proceed in parallel after Gate A.** Test suites write to ephemeral JSON in `results/` (via DiscoveryWriter). The discovery pipeline reads from there and writes to persistent YAML in `state/`. Fixture tooling is independent of both except for 5.4, which depends on the discovery YAML schema from 3.1. All three share the format definitions from Phase 2 but not implementation.

---

> **REVIEW GATE B: Pipeline + Suites + Fixtures Review** (epic) [blocked by Phase 3, Phase 4, Phase 5]
>
> Scope: State management design, import pipeline, all test suites, fixture tooling.
>
> Key questions: Does `import_run.py` correctly deduplicate? Do test suites generate useful discoveries and handle all error paths without panics? Does fixture validation catch all integrity issues? Do the components work correctly in isolation?
>
> Blocks: Phase 6.

---

**Phase 6: Initial Data + End-to-End Validation** (epic) [blocked by Gate B]

Actually run the system against real data, verify the full tester experience, and write the README. All prior components are complete; this phase is purely operational (plus the README). Two parallel tracks after 6.1: fixture curation (6.2–6.3) and discovery (6.4–6.5).

- 6.1: Download and verify Watson, IA Lendable, and LOC Books All datasets
- 6.2: Run initial fixture curation from LOC [depends on 6.1]
- 6.3: Validate and commit initial fixtures [depends on 6.2]
- 6.4: Run first discovery pass against IA Lendable [depends on 6.1]
- 6.5: Import results and verify state management [depends on 6.4]
- 6.6: End-to-end walkthrough of full tester workflow [depends on 6.3, 6.5]
- 6.7: Write README.md [depends on 6.6]

---

> **REVIEW GATE C: End-to-End Review** (epic) [blocked by Phase 6]
>
> Scope: The complete system. Walk through the entire tester journey documented in "Typical tester session": clone → setup → test fixtures → download data → test local → import → review discoveries.
>
> Key questions: Does `just setup && just test` work from a clean clone? Does `just test-local` generate discoveries? Does `just import && just discoveries` show results? Is the README sufficient for a new user to get started?

---

### Dependency summary

```
Phase 1 (Scaffold)
  └─→ Phase 2 (Infrastructure)
        └─→ GATE A (Foundation Review)
              ├─→ Phase 3 (Discovery Pipeline) ─┐
              ├─→ Phase 4 (Test Suites) ─────────┼─→ GATE B (Pipeline + Suites + Fixtures Review)
              └─→ Phase 5 (Fixture Tooling) ─────┘         │
                                                            └─→ Phase 6 (Initial Data + E2E + README)
                                                                  └─→ GATE C (End-to-End Review)
```

### Dependency encoding in beads

Gate epics are the primary dependency mechanism between phases. Individual tasks only need intra-phase dependencies and any cross-phase dependencies within a parallel block (e.g., 5.4 depends on 3.1). Cross-phase task dependencies covered by a gate do not need separate beads links — the plan notes them for context (e.g., "all Rust tests use the harness from 2a") but the gate already enforces the ordering.

### Review gate protocol

Each gate is a beads epic with type `chore`. When a gate is reached:

1. Create a gate epic (e.g., "Gate A: Foundation Review") that blocks all downstream phase epics
2. The reviewer examines all code from the phases being reviewed
3. Issues found become blocker beads linked to the gate epic
4. The gate epic is closed only when all blocker beads are resolved
5. Closing the gate epic unblocks downstream phases

---

## Open Questions for Implementation Planning

No critical blockers remain. The following are deferred for future consideration:

1. **Holdings data**: Deferred. No readily available public holdings datasets. Revisit if an academic library partnership materializes.

2. **International data sources**: Deferred. The initial focus is US library data (LOC, IA, Watson), which already contains substantial multilingual content. International sources (National Diet Library, DNB, Russian State Library) can be added later if encoding test coverage proves insufficient.

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- Renamed "custom" to "local" for BYOD data: `data/custom/` → `data/local/`,
  `MRRC_CUSTOM_*` → `MRRC_LOCAL_*` env vars, function names updated in Rust
  and Python

### Fixed

- `promote_discovery.py` now uses `extracted_file` field from discovery YAML
  instead of constructing the path from the discovery ID, fixing lookups for
  records with non-standard filenames

### Added

- `scripts/set_mrrc_source.py` — switch mrrc dependency between local checkout
  and released packages (`just use-local-mrrc`, `just use-released-mrrc`,
  `just mrrc-status`)
- `scripts/report_issue.py` — file GitHub issues on dchud/mrrc from discovery
  YAML via `gh` CLI (`just report`)
- Rewrote README "Verifying mrrc fixes" section with streamlined 5-step
  workflow using the new recipes
- Synthetic test data generators for malformed records and encoding edge cases,
  with committed `.mrc` output in `data/synthetic/`

## [0.1.0] - 2026-02-26

Initial implementation of the mrrc testbed.

### Added

- Two-mode test architecture: CI mode (fixtures only) and local mode
  (downloaded + BYOD datasets)
- Rust test harness (`crates/mrrc_testbed/`) with stress, malformed record,
  encoding, concurrency, and discovery test suites
- Python test suites (`suites/`) for pymarc API compatibility, encoding
  through bindings, and discovery at scale
- Dataset priority cascade: env override → local paths → downloads → fixtures
- Two-stage discovery pipeline: ephemeral JSON output → persistent YAML state
  with SHA-256 deduplication
- Dataset download scripts for Watson, Internet Archive, and LOC collections
- Fixture curation tooling with LOC SRU integration and `manifest.json`
  provenance tracking
- Justfile recipes for all common workflows (`test`, `test-local`, `lint`,
  `download`, `import`, `discoveries`, etc.)
- README with setup, usage, BYOD, and discovery workflow documentation
- Design document (`testbed-proposal.md`) with full architectural spec

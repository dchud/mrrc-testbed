# Synthetic Test Data

Generated records for specific test scenarios. Unlike downloaded data, synthetic records are committed to git because they are small, version-controlled, and reproducible.

## Directories

- `malformed/` — Intentionally broken records (truncated leaders, invalid indicators, bad lengths)
- `encoding/` — Encoding test vectors (MARC-8, UTF-8, mixed, edge cases)
- `generators/` — Scripts used to create synthetic records

Each dataset should include documentation explaining what it tests, how it was generated, and expected behavior when processed.

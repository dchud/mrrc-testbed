# Test Data

Four categories of test data, organized by commitment policy:

| Category | Location | In Git? | Purpose |
|----------|----------|---------|---------|
| **Fixtures** | `fixtures/` | Yes | Small curated samples for CI and quick tests |
| **Synthetic** | `synthetic/` | Yes | Generated records for specific test scenarios |
| **Downloaded** | `downloads/` | No | Large public datasets for thorough local testing |
| **Local (BYOD)** | `local/` | No | User's own MARC files for local testing |

## Fixtures

Small curated samples (~10MB total) from Library of Congress data exports. Each fixture directory contains a `manifest.json` documenting record provenance.

## Synthetic

Intentionally crafted records for targeted test scenarios (malformed records, encoding edge cases). Each subdirectory includes documentation on how the records were generated.

## Downloads

Large public datasets fetched on demand via `just download`. Never committed to git.

## Local (BYOD)

Place your own MARC files here or configure paths in `.env`. Never committed to git.

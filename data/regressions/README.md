# Regression corpus (`data/regressions/`)

Real-world and generated MARC inputs that once caused **mrrc** to mishandle a
record — a panic, a hang, silent data loss, or a wrong/opaque error. Each file
here is a permanent **regression guard**: mrrc must keep handling it gracefully.

This corpus is deliberately a **sibling of** `data/fixtures/`, not a child of it.
Fixtures are *curated, well-formed* records that must **parse cleanly** — the
CI-safe `fixture_records_parse_cleanly()` test and `scripts/validate_fixtures.py`
both assert zero parse errors across `data/fixtures/`. Regression inputs are the
opposite: **malformed by design**. Keeping them separate leaves the fixtures'
parse-clean invariant untouched.

## The invariant

For every committed input, across all recovery modes
(`Strict` / `Lenient` / `Permissive`), mrrc must:

- **not panic** and **not hang**, and
- either recover the record or return a clean, specific `Err`.

A returned error is acceptable and often expected — this corpus guards against
*panics and silent pathologies*, not against error returns. The CI-safe test
`crates/mrrc_testbed/tests/regressions.rs::regression_inputs_no_panic` enforces
the no-panic guarantee; `just validate` checks the manifest.

## Layout

- One input per file, named `crash_NNNN.mrc` (zero-padded, e.g. `crash_0001.mrc`).
- `manifest.json` records provenance for every file (schema below).

## Manifest schema

Top-level of `manifest.json`:

| field            | type    | meaning                          |
|------------------|---------|----------------------------------|
| `description`    | string  | what this corpus is              |
| `schema_version` | integer | currently `1`                    |
| `records`        | array   | one entry per input file (below) |

Each entry in `records`:

| field               | type           | required | meaning |
|---------------------|----------------|----------|---------|
| `filename`          | string         | yes | e.g. `crash_0001.mrc` |
| `sha256`            | string         | yes | hex SHA-256 of the file bytes (integrity + dedupe) |
| `source`            | enum           | yes | how the input was produced: `fuzzer` \| `synthetic` \| `reduction` \| `manual` |
| `origin`            | string \| null | no  | external corpus it came from or was derived from: `mrrc-fuzz`, `marc4j`, `pymarc`, `field-report`, … |
| `fuzz_target`       | string \| null | no  | fuzz target that found it (e.g. `parse_record`) |
| `mrrc_source`       | string         | yes | mrrc version or commit where the pathology was observed |
| `upstream_issue`    | string \| null | no  | e.g. `mrrc#93` |
| `discovered`        | string (date)  | yes | `YYYY-MM-DD` |
| `crash_summary`     | string         | yes | one line: what went wrong |
| `expected_behavior` | string         | yes | what mrrc must now do, e.g. `no panic; Err(E1xx)` |
| `notes`             | string \| null | no  | anything else |

### `source` kinds

- `fuzzer` — produced by mrrc's cargo-fuzz corpus (typically `origin: mrrc-fuzz`).
- `synthetic` — hand-authored malformed input.
- `reduction` — minimized from a larger real-world or external record (see licensing).
- `manual` — captured by hand from some other source.

`source` records *how the bytes were produced*; `origin` records *where they came
from*. That split means a pathological record from any external library is just
`source: reduction, origin: <library>` — no per-library category is needed.

## Licensing guardrail (read before adding a `reduction`)

Never commit another project's record bytes verbatim. Some corpora we compare
against are copyleft or otherwise restrictively licensed (e.g. marc4j is
LGPL-2.1). A `reduction` whose `origin` is an externally-licensed corpus **must
be a license-clean minimization** — reduced far enough that it no longer carries
the upstream's copyrightable expression, only the structural defect that
reproduces the pathology. If you cannot produce a clean reduction, do **not**
commit the input: keep it as a discovery and file an upstream report instead.

## Adding an input

Use the import helper, which writes the file, computes its SHA-256, and appends
the manifest entry in one step:

```
just add-regression <path-to-input> \
    --source fuzzer --target parse_record \
    --mrrc-source <version-or-sha> --issue mrrc#NN \
    --summary "one-line description of the defect"
```

Optional flags mirror the schema: `--origin <corpus>`, `--notes "..."`. Then
verify:

```
just validate                                             # manifest sync + provenance
cargo test --test regressions regression_inputs_no_panic  # no-panic guarantee
```

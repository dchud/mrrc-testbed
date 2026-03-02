# Formal Methods Verification Strategy for mrrc

## Background

mrrc-testbed currently exercises the mrrc library through two complementary
approaches: CI-mode fixture tests that run against committed MARC records, and
local-mode discovery tests that scan large public datasets for parsing errors
and unusual records. mrrc itself has a conventional test suite — integration
tests, benchmark harnesses, and an existing `memory_safety_asan.rs` test file.

This is effective at finding crashes and regressions, but it tests against
*known* inputs. What neither repo yet does systematically is *specify* correct
behavior — asserting invariants that must hold across any structurally valid
input, not just the ones we happened to collect. Nor do they prove that critical
parsing logic is correct for *all* inputs, or verify that the test suites
themselves are strong enough to catch real bugs.

Formal verification methods fill these gaps. The term covers a spectrum from
lightweight (property-based testing) to heavyweight (bounded model checking),
with different cost/benefit tradeoffs at each level. This document describes the
verification strategy for mrrc: which methods to use, why each one matters, and
where each belongs across the two repositories.

For the implementation plan — phases, sequencing, effort estimates — see
`formal-methods-implementation-plan.md`.

## The Verification Pyramid

Each layer builds on the ones below it. Lower layers are cheaper, faster, and
should be adopted first. Higher layers are more powerful but more expensive.

```
             /\
            /  \   Bounded model checking (Kani)
           / 5  \  Proves properties for ALL inputs up to a bound
          /------\
         /        \   Coverage-guided fuzzing (cargo-fuzz)
        /    4     \  Finds inputs random generation misses
       /------------\
      /              \   Property-based testing (proptest, hypothesis)
     /       3        \  Specifies invariants, generates random inputs
    /------------------\
   /                    \   Runtime verification (Miri, sanitizers)
  /         2            \  Detects UB and memory errors at runtime
 /------------------------\
/                          \   Test quality & API stability
/            1              \  (cargo-mutants, cargo-semver-checks)
\____________________________/  Validates the tests themselves
```

The pyramid is not about prestige — level 1 tools can catch bugs that level 5
tools miss, and vice versa. The point is sequencing: there is no value in
proving properties with Kani if your test suite has blind spots that
cargo-mutants would have revealed, and there is no value in fuzzing if you have
not first defined what "correct" means via property tests.

### mrrc's specific profile

mrrc has characteristics that shape which methods are most valuable:

- **Zero unsafe code.** `unsafe_code = "deny"` in Cargo.toml. Miri and
  sanitizers are less critical than for a library with unsafe blocks, but still
  useful for validating dependencies (nom, encoding_rs, quick-xml, smallvec).
- **Parser for a binary format.** The ISO 2709 reader (`reader.rs`, ~700 lines)
  and MARC-8 encoding state machine (`encoding.rs`, ~860 lines) are the highest-
  value targets for fuzzing and bounded verification. Parsers are where input-
  dependent bugs live.
- **Multiple serialization formats.** Binary MARC, MARCXML, MARCJSON, JSON,
  MODS, Dublin Core, CSV, BIBFRAME/RDF. Some are bidirectional (round-trip
  fidelity surfaces), others are export-only (correctness of the one-way
  transform). Property testing excels at both.
- **Parallel processing.** Rayon-based batch parsing and a producer-consumer
  pipeline — ThreadSanitizer is relevant despite no unsafe code, because data
  races can occur through shared mutable state in safe Rust (e.g., `Rc` misuse
  caught at compile time, but logical races in `Arc<Mutex<_>>` are not).
- **Python bindings via PyO3.** Cross-layer consistency (Rust vs. Python
  producing identical results) is the testbed's unique verification contribution.
- **Published crate.** API stability matters — accidental breaking changes in
  0.7.x affect downstream users.

## What Belongs Where

The same principle from the original property-testing proposal applies across
all verification methods: **tools that verify what mrrc promises belong in mrrc;
tools that verify mrrc against the wider world belong in the testbed.**

### mrrc (the library)

- **proptest** — core round-trip, accessor, encoding, and builder properties
- **cargo-fuzz** — fuzz targets for the parser and encoding layers
- **Kani** — bounded proofs for leader parsing, directory decoding, boundary
  scanning
- **Miri** — UB detection across the dependency chain
- **cargo-mutants** — test suite quality assessment
- **cargo-semver-checks** — API compatibility verification before publish
- **Sanitizers** — ASan/TSan in CI for parallel processing paths

proptest strategies (`arb_record()`, `arb_field()`, etc.) are reusable test
infrastructure and belong in mrrc. The testbed imports them.

### mrrc-testbed (this repo)

- **proptest** — fixture-seeded properties, scale properties over large datasets
- **Hypothesis** — cross-layer consistency (Rust vs. Python), pymarc equivalence
- **cargo-mutants** — validates that testbed assertions catch real regressions

### Migration path

Since mrrc does not yet have formal verification tooling, the practical approach
is the same as before:

1. **Start in the testbed** — write proptest strategies and properties here
   first, where we can iterate quickly alongside real data.
2. **Upstream to mrrc** — once stable, move strategies and core properties into
   mrrc's own test suite. Add cargo-fuzz targets and Kani proofs directly in
   mrrc.
3. **Testbed keeps** the cross-layer, fixture-seeded, and scale properties that
   need its infrastructure.

This avoids blocking testbed work on mrrc releases while ensuring the right
code ends up in the right place.

## Level 1: Test Quality and API Stability

These tools validate the verification infrastructure itself — they are the
foundation.

### cargo-mutants

Mutation testing injects faults into source code (swapping operators, replacing
return values, deleting statements) and checks whether existing tests catch each
mutation. Surviving mutants reveal blind spots that line-coverage metrics miss.

```bash
cargo install cargo-mutants
cargo mutants                      # run all mutations
cargo mutants -f src/reader.rs     # focus on parser module
```

**Version:** 26.2.0. Calendar-versioned, actively maintained. Works with both
`cargo test` and `cargo nextest`.

**Where:** Both repos. In mrrc, it assesses whether unit and property tests are
strong enough. In the testbed, it validates that integration assertions are
meaningful. Run weekly or on demand — too slow for every PR.

**Sequencing:** Run after property tests are written (Phase 2+) to evaluate
their strength. Use surviving mutants to guide writing additional properties.

### cargo-semver-checks

Scans the public API against the previous published release and reports semver
violations: removed items, changed signatures, altered trait implementations.

```bash
cargo install cargo-semver-checks
cargo semver-checks check-release
```

**Version:** 0.44.0. 245 lint rules. On track to merge into `cargo publish`
itself. Also available as a GitHub Action.

**Where:** mrrc CI only (the testbed does not publish a public API). Run on PRs
that modify public API surface, or as a pre-publish gate.

## Level 2: Runtime Verification

These tools detect bugs at runtime that the type system cannot catch — undefined
behavior, memory errors, and data races.

### Miri

Miri interprets Rust's MIR and detects undefined behavior: out-of-bounds
access, use-after-free, uninitialized reads, invalid pointer provenance, and
data races. It runs your existing test suite under the interpreter — no special
harnesses needed.

```bash
rustup +nightly component add miri
cargo +nightly miri test
```

**Maturity:** Very high. Part of the official Rust toolchain. Peer-reviewed
paper at POPL 2026. Used in CI for the Rust standard library.

**Where:** mrrc CI. Despite zero unsafe in mrrc's own code, Miri validates the
transitive dependency chain (nom, encoding_rs, quick-xml, smallvec, indexmap).
If any dependency has a UB bug triggered by mrrc's usage patterns, Miri finds
it. Run on a subset of tests in CI (Miri is 10-100x slower than native).

**Practical note:** Miri cannot run code that performs I/O or calls into C
libraries. This excludes some tests but the core parsing and serialization logic
is pure Rust and Miri-compatible.

### Sanitizers (ASan, TSan)

LLVM sanitizers compiled into the binary at build time. AddressSanitizer (ASan)
detects buffer overflows and use-after-free. ThreadSanitizer (TSan) detects data
races. mrrc already has a `memory_safety_asan.rs` test file.

```bash
# AddressSanitizer
RUSTFLAGS="-Zsanitizer=address" \
  cargo +nightly test -Zbuild-std --target x86_64-unknown-linux-gnu

# ThreadSanitizer (for rayon/parallel tests)
RUSTFLAGS="-Zsanitizer=thread" \
  cargo +nightly test -Zbuild-std --target x86_64-unknown-linux-gnu
```

**Maturity:** ASan is nearly stabilized (PR #123617). TSan stabilization is a
2025 H2 Rust project goal. Both require nightly.

**Where:** mrrc CI (nightly job, Linux). TSan is particularly relevant for
`rayon_parser_pool.rs`, `producer_consumer_pipeline.rs`, and
`boundary_scanner.rs`. ASan is most useful when combined with fuzzing — run fuzz
targets under ASan to catch memory corruption that safe Rust should prevent but
dependencies might not.

## Level 3: Property-Based Testing

The core of the verification strategy. Define what "correct" means and let the
framework generate inputs to try to falsify it.

### Rust: proptest

`proptest` 1.9 is the standard choice. It integrates with `cargo test`, has
rich strategy composition, good shrinking, and supports both the `proptest!`
block macro and the `#[property_test]` attribute macro. mrrc already has
`proptest = "1"` in its dev-dependencies.

```toml
# crates/mrrc_testbed/Cargo.toml
[dev-dependencies]
proptest = "1"
```

The `#[property_test]` macro is preferred for new tests:

```rust
use proptest::prelude::*;

#[property_test]
fn binary_roundtrip(#[strategy(arb_record())] record: Record) {
    let bytes = record.to_bytes();
    let parsed = Record::from_bytes(&bytes).unwrap();
    assert_eq!(parsed.to_bytes(), bytes);
}
```

#### Strategies

The main investment is writing composable strategies for MARC types:

```rust
use proptest::prelude::*;

fn arb_tag() -> impl Strategy<Value = String> {
    (0u16..=999).prop_map(|n| format!("{:03}", n))
}

fn arb_data_tag() -> impl Strategy<Value = String> {
    (10u16..=999).prop_map(|n| format!("{:03}", n))
}

fn arb_indicator() -> impl Strategy<Value = char> {
    prop_oneof![Just(' '), ('0'..='9'), ('a'..='z')]
}

fn arb_subfield_code() -> impl Strategy<Value = char> {
    prop_oneof![('a'..='z'), ('0'..='9')]
}

fn arb_subfield() -> impl Strategy<Value = (char, String)> {
    (arb_subfield_code(), "[ -~]{0,200}")
}

fn arb_field() -> impl Strategy<Value = Field> {
    (arb_data_tag(), arb_indicator(), arb_indicator(),
     proptest::collection::vec(arb_subfield(), 1..=10))
        .prop_map(|(tag, ind1, ind2, sfs)| {
            let mut f = Field::new(tag, ind1, ind2);
            for (code, value) in sfs {
                f.add_subfield(code, value);
            }
            f
        })
}

fn arb_record() -> impl Strategy<Value = Record> {
    proptest::collection::vec(arb_field(), 0..=20)
        .prop_map(|fields| {
            let mut b = Record::builder().leader(Leader::default());
            for f in fields {
                b = b.field(f);
            }
            b.build()
        })
}
```

These generate structurally valid but not MARC-spec-valid records. That is
intentional — the goal is to stress the library's internal logic, not to
validate against the MARC specification. Spec-valid generation (constraining
tags to real MARC fields, indicators to spec-defined values) can be layered on
later.

#### Property families

**1. Round-trip fidelity** — the most important properties. These apply to
bidirectional formats only.

- Binary MARC: `to_bytes()` -> `from_bytes()` -> `to_bytes()` -> bytes match
- MARCXML: `to_marcxml()` -> `from_marcxml()` -> `to_marcxml()` -> match
- MODS: `to_mods()` -> `from_mods()` -> `to_mods()` -> match
- JSON: `to_json()` -> `from_json()` -> `to_json()` -> match
- MARCJSON: `to_marcjson()` -> `from_marcjson()` -> `to_marcjson()` -> match

Dublin Core and CSV are export-only (no `from_` path) — test those as
**one-way transform stability**: for any generated record, the output is
well-formed and deterministic (same input always produces same output).

BIBFRAME has bidirectional conversion but the round-trip is lossy by nature
(MARC -> RDF entity extraction -> MARC is not information-preserving). Test
BIBFRAME as a deferred, weaker property — see "Deferred and Out of Scope."

Round-trip equality for XML formats should be semantic (normalized whitespace,
stable attribute order), not byte-identical. Compare parsed structures.

**2. Accessor coherence** — accessors must agree with underlying field data.

- `record.title()` returns `Some` iff a 245 field exists with subfield `$a`
- `record.author()` returns `Some` iff a 1xx field (100, 110, or 111) exists
- `record.isbns()` first element equals `record.isbn()` when non-empty
- `record.fields_by_tag(tag)` is a subset of `record.fields()` for any tag
- `record.control_field(tag)` returns `Some` iff `record.control_fields()`
  contains that tag

**3. Encoding round-trips**

- For any UTF-8 string: encode -> decode -> original string
- For valid MARC-8 byte sequences: decode -> encode -> decoded text round-trips
- `MarcEncoding::from_leader_char` returns consistent encoding for all valid
  leader characters

**4. Builder stability**

- Adding a field with tag T then calling `fields_by_tag(T)` returns at least
  that field
- Adding a control field with tag T then calling `control_field(T)` returns the
  value
- A record built with `RecordBuilder` and immediately serialized is parseable

**5. Query DSL correctness**

- `FieldQuery` matching a tag range returns a subset of `fields_by_tag` results
  for each tag in that range
- `SubfieldPatternQuery` results are a subset of the parent field's subfields
- Query composition (and/or) satisfies boolean algebra identities

#### CI/local mode integration

Follow the existing convention: fast property tests (< 1s, 256 cases) run in
CI as regular `#[test]`s. High-case-count variants are `#[ignore]` and run via
`just test-local`.

```rust
fn ci_config() -> ProptestConfig {
    ProptestConfig { cases: 256, ..Default::default() }
}

fn local_config() -> ProptestConfig {
    ProptestConfig { cases: 10_000, ..Default::default() }
}
```

#### Failure persistence

Proptest saves failing inputs to `proptest-regressions/` files next to the test
source. Commit these — they represent discovered bugs, consistent with the
testbed's philosophy of committing `state/discoveries/`.

### Python: hypothesis

`hypothesis` 6.x integrates with pytest and supports profile-based
configuration for CI/local mode separation.

```toml
# pyproject.toml, under [dependency-groups] dev
"hypothesis>=6",
```

Configure profiles in `suites/conftest.py`:

```python
from hypothesis import settings, HealthCheck

settings.register_profile("ci",
    max_examples=200,
    derandomize=True,
    deadline=None,
)
settings.register_profile("local",
    max_examples=5000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
```

Load via `HYPOTHESIS_PROFILE` env var or default to `"ci"`.

#### Python property families

**1. Cross-layer consistency** — the testbed's unique contribution.

For any fixture record, the Python binding must produce the same results as the
Rust core:

- `mrrc.Record.from_bytes(data)` produces the same field count, control number,
  and leader as the Rust path
- JSON round-trip through Python matches JSON round-trip through Rust
- Accessor results (title, author, ISBNs) agree between layers

Seed from the committed fixture corpus with
`@given(st.sampled_from(fixture_records))`.

**2. Python API round-trips**

```python
@given(tag=st.from_regex(r'[0-9]{3}', fullmatch=True),
       value=st.text(max_size=200))
def test_json_roundtrip(tag, value):
    # Build minimal record, convert to JSON and back, verify field preserved
    ...
```

**3. pymarc behavioral equivalence**

For records from the fixture corpus, verify mrrc and pymarc agree on: iteration
order, field access, subfield extraction, control number. Mark with
`@pytest.mark.local` if loading large datasets.

**Important caveat:** pymarc is the reference for API shape and typical behavior,
but not an oracle for correctness. If property tests or cross-layer comparisons
reveal a case where pymarc produces *clearly incorrect* output (e.g., silently
dropping subfields, misinterpreting indicators, returning wrong encoding), mrrc
should do the correct thing — not replicate the bug for compatibility. When this
happens: document the divergence in the test with a comment, file a detailed
issue upstream with pymarc (including the reproducing record and expected vs.
actual output), and mark the specific assertion with a `pymarc_known_issue` tag
so it can be revisited when pymarc is fixed.

## Level 4: Coverage-Guided Fuzzing

Random property testing generates inputs uniformly. Coverage-guided fuzzing
instruments the binary and *steers* toward inputs that explore new code paths.
For parsers, this is dramatically more effective — it finds the malformed leader
that triggers an off-by-one, the encoding escape sequence that corrupts state,
the truncated record that panics.

### cargo-fuzz (via libFuzzer)

```bash
cargo install cargo-fuzz
cargo fuzz init                    # creates fuzz/ directory
cargo fuzz add parse_record        # add a fuzz target
```

**Version:** 0.13.1. Mature, backed by the rust-fuzz organization. Requires
nightly Rust.

Fuzz targets live in `fuzz/fuzz_targets/` with their own `Cargo.toml`:

```rust
// fuzz/fuzz_targets/parse_record.rs
#![no_main]
use libfuzzer_sys::fuzz_target;
use mrrc::MarcReader;
use std::io::Cursor;

fuzz_target!(|data: &[u8]| {
    // Must not panic on any input.
    // Returning Err is fine — panicking is not.
    let cursor = Cursor::new(data);
    let reader = MarcReader::new(cursor);
    for result in reader {
        let _ = result;  // consume, don't unwrap
    }
});
```

#### Recommended fuzz targets for mrrc

1. **`parse_record`** — feed arbitrary bytes to `MarcReader`. The highest-value
   target. Asserts that parsing never panics on any input.

2. **`parse_leader`** — feed arbitrary 24-byte sequences to leader parsing.
   Smaller state space = faster convergence.

3. **`decode_marc8`** — feed arbitrary bytes to the MARC-8 decoder state
   machine. The escape sequence handling (0x1B) is a rich source of edge cases.

4. **`roundtrip_binary`** — generate bytes, parse, re-serialize, parse again.
   Assert that if parsing succeeds, the round-trip is stable.

5. **`parse_marcxml`** — feed arbitrary bytes to `marcxml_to_record()`. XML
   parsers have their own edge cases beyond what the underlying quick-xml
   handles.

6. **`parse_json`** — feed arbitrary bytes to `json_to_record()`. JSON edge
   cases in field structure.

#### Corpus seeding

Seed the fuzzer corpus from real data for faster convergence:

```bash
# Copy fixture records as initial corpus
cp data/fixtures/*.mrc fuzz/corpus/parse_record/
```

The testbed's `data/fixtures/` and `state/discoveries/` provide excellent seeds.
Fuzzer-found inputs that trigger new bugs should flow back to the testbed as new
fixture data, closing the loop.

#### CI integration

Fuzzing is inherently open-ended. In CI, run timed campaigns:

```bash
cargo fuzz run parse_record -- -max_total_time=300   # 5 minutes
```

For deeper exploration, run extended campaigns locally or as a scheduled CI job
(nightly/weekly).

### Why not bolero?

bolero (0.13.4) provides a unified interface to libFuzzer, AFL, Honggfuzz, and
Kani. Write one `bolero::check!` harness and run it under multiple engines.
This is appealing in theory but adds a layer of indirection. For mrrc, the
recommendation is:

- Use **cargo-fuzz** for fuzzing (simpler, better documented, wider ecosystem)
- Use **proptest** for property testing (already adopted, richer strategies)
- Use **Kani** directly for bounded proofs (cleaner than through bolero)

If maintaining three separate tool integrations becomes burdensome, bolero can
replace all three later. But start with the focused tools — they are easier to
debug and better documented individually.

## Level 5: Bounded Model Checking

Kani (AWS) translates Rust MIR to CBMC and exhaustively explores all possible
execution paths within specified bounds. Unlike fuzzing (which finds *some* bugs)
or property testing (which tests *random* inputs), Kani proves that a property
holds for *all* inputs up to a given size.

```bash
cargo install --locked kani-verifier
cargo kani setup
cargo kani
```

**Version:** 0.66.0. Monthly releases. Used to verify parts of the Rust
standard library.

### Where Kani fits for mrrc

Kani is most valuable for small, critical functions where exhaustive proof is
tractable. For mrrc, the targets are:

**1. Leader parsing** — the 24-byte MARC leader has a fixed structure. Kani can
prove that `Leader::from_bytes()` never panics for any 24-byte input and that
round-trip fidelity holds for all valid leaders.

```rust
#[kani::proof]
fn leader_never_panics() {
    let bytes: [u8; 24] = kani::any();
    // Must not panic — errors are fine
    let _ = Leader::from_bytes(&bytes);
}

#[kani::proof]
fn leader_roundtrip() {
    let bytes: [u8; 24] = kani::any();
    if let Ok(leader) = Leader::from_bytes(&bytes) {
        let output = leader.to_bytes();
        assert_eq!(output, bytes);
    }
}
```

**2. Directory entry decoding** — each directory entry is 12 bytes (tag + length
+ offset). Kani can prove correct decoding for all possible 12-byte inputs.

**3. Record length validation** — the first 5 bytes of a MARC record encode its
total length. Kani can prove that length parsing is correct for all 5-digit
values and that invalid lengths are properly rejected.

**4. Encoding detection** — `MarcEncoding::from_leader_char()` maps a single
byte to an encoding enum. Kani can prove this is total (handles all 256 possible
values) and consistent.

### Limitations

Kani's verification time grows exponentially with input size. Proving properties
over a full MARC record (which can be up to 99,999 bytes) is not tractable.
Focus Kani on the small, critical parsing primitives — the building blocks that
the rest of the library depends on. Use property testing and fuzzing for the
composed operations.

**Where:** mrrc only. Proof harnesses live next to the functions they verify.

## What Each Method Catches

| Method | Catches | Misses |
|--------|---------|--------|
| **Property testing** | Round-trip bugs, accessor logic errors, encoding edge cases, builder defects | Inputs random generation does not produce |
| **Fuzzing** | Parser crashes, encoding state corruption, off-by-one in binary format, denial-of-service inputs | Logic errors that do not crash (silent data corruption) |
| **Kani** | All bugs in small functions (exhaustive within bounds) | Bugs beyond the bound, composed operations |
| **Miri** | UB in dependencies, pointer provenance errors, uninitialized reads | Logic errors in safe code |
| **Sanitizers** | Memory corruption, data races in parallel code, leaks | Same — focused on memory/thread safety |
| **Mutation testing** | Weak assertions, untested code paths, redundant tests | Not bugs in code — bugs in tests |
| **Semver checks** | Accidental API breakage | Behavioral changes that preserve the API surface |

The combination is greater than the sum: property testing defines correctness,
fuzzing explores the input space, Kani proves critical primitives, Miri and
sanitizers catch runtime errors, mutation testing validates the whole suite, and
semver checks protect downstream users.

## Deferred and Out of Scope

### Deductive verification (Prusti, Creusot)

Prusti and Creusot allow annotating Rust code with formal specifications
(preconditions, postconditions, invariants) and proving the code satisfies them.
Both are active research projects (Prusti from ETH Zurich, Creusot from INRIA
with a 0.9.0 release in January 2026 and a POPL 2026 paper).

**Not recommended for mrrc.** The annotation overhead is substantial, both tools
require pinning to specific nightly Rust versions, and neither handles the full
Rust language. For a data-format parsing library, the cost/benefit ratio is poor
compared to property testing + fuzzing + Kani. Revisit if mrrc ever adds
safety-critical features (e.g., cryptographic signing of records).

### Alloy / TLA+

Interesting for schema-level modeling of the MARC data model or the producer-
consumer pipeline's concurrency protocol, but orthogonal to runtime verification.
Could be a separate future effort in the mrrc repo if the concurrency model
becomes complex enough to warrant it.

### BIBFRAME properties

Defer. BIBFRAME conversion involves RDF graph output (via oxrdf/oxrdfio) with
complex entity extraction (Work/Instance/Item). The MARC -> BIBFRAME -> MARC
round-trip is inherently lossy — the RDF model restructures data into
Work/Instance/Item entities that do not map back to the original MARC fields
one-to-one. True round-trip fidelity is not achievable or expected.

When eventually tested, BIBFRAME properties should assert weaker invariants:
the forward conversion produces valid RDF, specific MARC fields map to expected
RDF predicates, and the reverse conversion produces a parseable MARC record
(even if not identical to the original). Add after core round-trip properties
are stable and the BIBFRAME API has settled.

## Resolved Questions

**Should `proptest-regressions/` be committed?** Yes. Consistent with committing
`state/discoveries/` — both represent discovered bugs that should be re-tested
permanently.

**Should there be a `just test-properties` recipe?** Yes. Also add
`just test-properties-local` for high-case-count runs.

**cargo-fuzz or bolero?** cargo-fuzz. Simpler, better documented, wider
ecosystem. bolero can replace it later if maintaining separate tool integrations
becomes burdensome.

**Kani in testbed?** No. Proof harnesses should live next to the functions they
verify. The testbed does not contain the parsing logic Kani would verify.

**Prusti/Creusot?** Not now. Annotation overhead is too high for the benefit.
Property testing + fuzzing + Kani cover the same ground with less investment.

**BIBFRAME properties?** Defer. The round-trip is inherently lossy, so standard
fidelity properties do not apply. When added, assert weaker invariants (valid
RDF output, expected predicate mapping, parseable reverse conversion).

**Alloy/TLA+ models?** Out of scope. Interesting for schema-level or concurrency
modeling but orthogonal to runtime verification.

**Sanitizer stabilization timeline?** ASan is nearly stable. TSan/MSan
stabilization is in progress (2025 H2 Rust project goal). Use nightly for now;
revisit when stable.

**bolero / fuzzing in testbed?** No — the testbed tests mrrc as an external
dependency, so coverage-guided fuzzing of mrrc's internals is better done in
mrrc itself. The testbed contributes corpus data (fixtures, discoveries) that
seed fuzzers, and receives fuzzer-found inputs back as new fixtures.

## Appendix: Existing Test Overlap and Migration Recommendations

This appendix audits existing tests in both repositories, identifies where the
proposed formal methods overlap with or improve upon current tests, and
recommends whether each existing test should be **kept as-is**, **augmented**
with a formal method, or **replaced** by a more effective approach.

Recommendations use these labels:

- **Keep** — the existing test serves a purpose no formal method replaces
- **Augment** — keep the existing test but add a formal method alongside it
- **Replace** — the formal method is strictly better; retire the existing test
  once the replacement is validated

### mrrc (the library)

#### `tests/integration_tests.rs` (~268 lines)

Covers read/write roundtrip for bibliographic and authority records using
hand-written fixture files. Each test reads a specific `.mrc` file and checks
known field values; roundtrip tests write to buffer and read back.

**Overlap:** Directly overlaps with the proposed round-trip fidelity properties.

**Recommendation: Augment.** Keep the fixture-based tests as regression anchors
(they document known-good behavior for specific real records). Add proptest
round-trip properties that generalize the invariant to arbitrary generated
records. The fixture tests catch "did we break this specific record?" while the
property tests catch "is the invariant itself correct?"

#### `src/reader.rs` inline tests (~280 lines)

Tests `MarcReader` with hand-built binary MARC records. Includes happy paths
(single record, multiple records, EOF) and error conditions (malformed leaders
with `record_length < 24`, `base_address < 24`).

**Overlap:** Directly overlaps with the proposed `parse_record` and
`parse_leader` fuzz targets.

**Recommendation: Augment.** The hand-written malformed leader tests document
*specific* known edge cases and should remain as regression tests. Add
cargo-fuzz targets that explore the full input space. The fuzzer will find
edge cases the hand-written tests miss; the hand-written tests document the
ones we already know about.

#### `src/writer.rs` inline tests (~222 lines)

Write-then-read roundtrip tests for single records, multiple subfields,
multiple fields with same tag, batch writing, and post-finish error handling.

**Overlap:** Directly overlaps with the proposed round-trip properties.

**Recommendation: Augment.** Same rationale as `integration_tests.rs`. Keep the
specific cases; add proptest for the general invariant.

#### `src/encoding.rs` inline tests (~445 lines)

Hand-crafted MARC-8 byte sequences with expected Unicode output. Covers escape
sequences (G0/G1 switching, subscript, superscript, Greek, EACC/CJK, Hebrew,
Arabic), combining marks, NFC normalization, control characters, and unknown
escape sequences. This is one of the best-covered modules.

**Overlap:** Overlaps with the proposed `decode_marc8` fuzz target and encoding
round-trip properties.

**Recommendation: Augment.** The hand-crafted byte sequences document specific
MARC-8 features and are excellent regression tests — do not remove them. Add
fuzzing to discover panic paths and incorrect state transitions the hand-written
cases miss. Add proptest for the `decode -> encode -> decode` round-trip on
ASCII subsets.

#### `src/leader.rs` inline tests (~187 lines)

Tests `Leader::from_bytes()` / `as_bytes()` roundtrip, too-short input, invalid
indicator count, `valid_values_at_position()`, `describe_value()`,
`validate_for_reading()`.

**Overlap:** Directly overlaps with the proposed Kani leader proofs.

**Recommendation: Replace (partially).** The roundtrip and no-panic properties
are exactly what Kani proves exhaustively for all 24-byte inputs. Once the Kani
proofs are in place, the hand-written roundtrip test is redundant (Kani covers
every case it covers plus all others). **Keep** the too-short input test and
the validation-specific tests, which test error paths that Kani proofs would
model differently.

#### `src/boundary_scanner.rs` inline tests (~109 lines)

Tests `RecordBoundaryScanner` with hand-crafted byte vectors: single/multiple
records, empty buffer, no terminators, limited scan, count, reuse.

**Overlap:** Overlaps with proposed fuzzing and proptest for boundary scanning.

**Recommendation: Augment.** The hand-written tests cover specific edge cases
(empty, no terminators, reuse). Add proptest for the algebraic property: "for
any byte buffer, `scan()` returns boundaries where every boundary ends at a
0x1D byte, and boundaries partition the buffer." Add fuzzing for no-panic.

#### `tests/indicator_validation.rs` (~428 lines)

Exhaustive enumeration of valid/invalid indicator combos for ~24 field tags.

**Overlap:** Overlaps with proposed property tests for accessor coherence and
validator consistency.

**Recommendation: Augment.** The existing tests enumerate specific
tag/indicator combinations well. Add proptest to assert consistency between
`validate_indicators()` and `get_indicator_meaning()` — if validation passes,
meaning should be defined (and vice versa). Since the domain is finite
(~24 tags x 256 x 256 indicator combinations), exhaustive proptest is
tractable and would be more thorough than the current hand-picked samples.

#### `tests/record_helpers_trait.rs` (~318 lines)

Tests `RecordHelpers` trait: `title()`, `control_number()`, `isbn()`,
`subjects()`, `authors()`, etc. Hand-built records with specific fields.

**Overlap:** Directly overlaps with the proposed accessor coherence properties.

**Recommendation: Augment.** Keep the hand-written tests (they document expected
behavior for specific field configurations). Add proptest properties: "for any
Record where tag 245 exists with subfield `$a` = V, `title()` returns
`Some(V)`", etc.

#### `tests/field_query_integration.rs` (~251 lines) and `tests/field_query_helpers_comprehensive.rs` (~608 lines)

Tests the `FieldQuery` builder, `TagRangeQuery`, indicator filtering, subfield
matching, and Phase 2 query helpers (regex ISBN matching, subdivision queries).

**Overlap:** Overlaps with proposed Query DSL correctness properties.

**Recommendation: Augment.** The existing tests are thorough for specific
queries against a known record. Add proptest for algebraic properties: default
query matches all fields, composing two filters returns a subset of either
alone, `fields_by_indicator(tag, None, None)` equals `get_fields(tag)`. Also
fuzz the regex interface (assert invalid patterns return `Err`, never panic).

#### `tests/field_linkage_integration.rs` (~483 lines)

Tests MARC 880 field linkage with Arabic, Chinese, and English linked fields.
Covers malformed linkage, missing 880s, duplicate occurrences.

**Overlap:** Partially overlaps with proposed round-trip properties (the
roundtrip invariant `get_linked_field(f) -> get_original_field(linked) == f`).

**Recommendation: Augment.** Keep the hand-written multilingual tests. Add
proptest for the bidirectional linkage invariant over generated fields with
valid `$6` subfields. Fuzz `LinkageInfo::parse()` with arbitrary strings.

#### `tests/memory_safety_asan.rs` (~304 lines)

Tests standard library types (Vec, Box, String, RefCell, Mutex, Arc) under
ASAN. One minimal MARC-specific test.

**Overlap:** Overlaps with proposed Miri and sanitizer CI jobs.

**Recommendation: Replace.** Most of these tests exercise standard library
operations that Rust already guarantees memory safety for. Once Miri and ASAN
are running in CI against the actual test suite, these artificial ASAN smoke
tests are redundant. The one MARC-specific test is subsumed by the broader
round-trip properties under Miri.

#### `tests/concurrent_gil_tests.rs` (~332 lines)

Tests queue-based state machine for batched reading, EOF idempotence, batch
size hard limits, SmallVec stack/heap behavior.

**Overlap:** Partially overlaps with proposed Kani proofs (the state machine
has a finite state space).

**Recommendation: Augment.** Keep the existing tests (they document the state
machine contract). The state machine has a small state space (queue empty/non-
empty, EOF reached/not, batch count) that Kani could exhaustively prove
correct. Add Kani proofs for idempotence and batch-limit invariants.

#### `tests/bibframe_*.rs` (~3,736 lines across 5 files)

Unit tests, validation, integration, roundtrip, and baseline comparison for
BIBFRAME conversion. The roundtrip tests document expected data loss.

**Overlap:** Partially overlaps with deferred BIBFRAME properties.

**Recommendation: Keep (for now).** BIBFRAME properties are deferred in this
proposal. The existing tests are valuable and well-structured. When BIBFRAME
properties are eventually added, the roundtrip tests can be augmented with
proptest asserting weaker invariants (valid RDF output, no panic, expected
entity types from leader values). The baseline comparison tests have no formal
methods equivalent — they are conformance tests against an external standard.

#### `tests/mods_conformance_tests.rs` (~231 lines)

MODS XML to MARC conversion against LOC reference fixtures.

**Overlap:** Overlaps with the proposed `parse_marcxml` fuzz target and MODS
round-trip properties.

**Recommendation: Augment.** Keep the conformance tests (reference data is
irreplaceable). Add fuzzing for `mods_xml_to_record()` with arbitrary/malformed
XML to find parsing crashes. Add proptest for the MODS round-trip once
strategies exist.

#### `src/record.rs` inline tests (~1,100 lines)

Comprehensive tests for Record/Field/Subfield creation, control field access,
helpers, builder API, iterators, index access, `format_field()`, insertion order.

**Overlap:** Overlaps broadly with proposed accessor coherence and builder
stability properties.

**Recommendation: Augment.** The inline tests document expected API behavior at
a granular level — keep them. Add proptest for the structural invariants:
`add_field(f); get_fields(f.tag).contains(f)`, `add_subfield('a', v);
get_subfield('a') == Some(v)`, insertion order preservation. Mutation testing
via cargo-mutants would also be valuable here — many of these tests use
specific assertions that might not catch subtle logic changes.

#### Python binding tests (`tests/python/`, ~9,100 lines across 27 files)

Covers the full Python API surface: basic and advanced operations, pymarc
compatibility, iterator protocol, boundary scanner, GIL release, concurrency,
and benchmarks.

**Overlap:** The pymarc compatibility tests (`test_pymarc_compatibility.py`,
~1,002 lines and `test_pymarc_compliance.py`, ~597 lines) overlap with the
proposed Hypothesis pymarc equivalence tests. The roundtrip tests overlap with
proposed Python round-trip properties.

**Recommendation: Augment.** The existing pymarc compatibility tests document
specific API compatibility guarantees and should remain. Add Hypothesis tests
for differential testing (same operations through both pymarc and mrrc, compare
output) and for round-trip properties over generated input. The GIL and
performance tests have no formal methods equivalent — keep as-is.

### mrrc-testbed (this repo)

#### `crates/mrrc_testbed/tests/malformed.rs` (~895 lines)

Hand-crafted malformed MARC byte sequences (~25 inputs) tested across strict,
lenient, and permissive recovery modes. Asserts no panics via `catch_unwind`.
Documents known upstream panics (arithmetic overflow when `record_length < 24`
or `base_address < 24`).

**Overlap:** The `no_panics_on_any_input` function is essentially a hand-
enumerated fuzz test. Directly overlaps with the proposed `parse_record`
fuzz target and the proptest "no panic on arbitrary input" property.

**Recommendation: Replace (the enumerated part).** The 25 hand-crafted inputs
in `no_panics_on_any_input` are subsumed by fuzzing — a 5-minute fuzz run
explores orders of magnitude more inputs. **Keep** the `upstream_subtraction_
overflow_panics` test (it documents known mrrc bugs) and the
`error_messages_useful` test (it checks diagnostic quality, not just
no-panic). **Keep** the `discover_malformed_patterns` local-mode test
(real-data discovery is not replaceable by generated inputs). Retire the
enumerated byte sequences once fuzzing is running.

#### `crates/mrrc_testbed/tests/encoding.rs` (~403 lines)

UTF-8 and MARC-8 roundtrip tests using both hand-crafted synthetic records (CI)
and real-world dataset records filtered by character content (local mode).
Covers CJK, Cyrillic, diacritics, encoding detection, and replacement character
detection.

**Overlap:** Directly overlaps with proposed encoding round-trip properties
(both proptest and Hypothesis).

**Recommendation: Augment.** Keep the local-mode tests (they use real-world
data that generated inputs cannot replicate). Keep the CI tests as regression
anchors for specific Unicode strings. Add proptest with `any::<String>()` (or
`"\\PC+"` for non-control) asserting the round-trip invariant and absence of
U+FFFD across a vastly wider Unicode range than the 4 hand-picked strings.

#### `crates/mrrc_testbed/tests/concurrent.rs` (~412 lines)

Thread safety and data integrity tests: parallel reads, producer-consumer
stress, data corruption checks.

**Overlap:** Partially overlaps with proposed proptest for concurrent roundtrip.

**Recommendation: Augment.** The existing tests verify specific thread-count
configurations with specific data. Add proptest to generate records with
varying field counts and content, then assert the multi-threaded read property
(`parallel_read(write(records)) == single_thread_read(write(records))`).

#### `crates/mrrc_testbed/tests/discovery.rs` (~516 lines)

Edge case cataloging: unusual field combinations, extreme values, encoding edge
cases (local mode), plus a CI fixture parse-cleanly test.

**Overlap:** Minimal overlap. Discovery tests scan real data for outliers — this
is fundamentally different from generated-input testing.

**Recommendation: Keep.** Discovery tests serve a unique purpose (finding
interesting real-world records) that formal methods do not address. The CI
`fixture_records_parse_cleanly` test is a simple universal property already.
No change needed.

#### `crates/mrrc_testbed/tests/stress.rs` (~381 lines)

Memory stability, throughput, thread scaling, resource cleanup. Uses a custom
`CountingAllocator`.

**Overlap:** None. These are non-functional property tests (memory, performance).

**Recommendation: Keep.** Formal methods do not address performance or resource
usage.

#### `crates/mrrc_testbed/tests/synthetic.rs` (~365 lines)

Validates committed synthetic test data: file existence, malformed files cause
errors not panics, encoding roundtrip preservation.

**Overlap:** The "no panics on malformed" assertion overlaps with fuzzing. The
encoding roundtrip overlaps with proptest.

**Recommendation: Augment.** Keep the file existence and specific-value tests
(they validate the synthetic data generators). The no-panic and roundtrip
assertions are strengthened by proptest and fuzzing but not replaced — these
tests validate the *committed synthetic data* specifically.

#### `crates/mrrc_testbed/src/discovery.rs` inline tests (~194 lines)

Tests `DiscoveryWriter`, `extract_control_number`, `categorize_error`,
deduplication.

**Overlap:** Partially overlaps with proposed proptest for testbed helper
functions.

**Recommendation: Augment.** Add proptest for `extract_control_number`
("for any byte sequence, returns either a valid string or 'unknown' without
panicking") and for `categorize_error` ("every string maps to exactly one
category"). Keep the existing integration test for `DiscoveryWriter`.

#### `suites/encoding/test_string_handling.py` (~332 lines)

Python encoding correctness: type checking (str not bytes), no U+FFFD in
fixtures, write/read roundtrip, large-dataset encoding variety detection,
mojibake detection.

**Overlap:** The roundtrip and encoding quality tests directly overlap with
proposed Hypothesis encoding properties.

**Recommendation: Augment.** Keep the fixture-based and dataset-based tests.
Add Hypothesis with `st.text()` for roundtrip and no-mojibake properties
across the full Unicode range. The type-checking tests (`str` not `bytes`)
are trivially true for any input and do not benefit from Hypothesis.

#### `suites/pymarc_compat/test_real_scripts.py` (~214 lines)

Replicates common pymarc usage patterns: iterate, access fields, convert to
dict, search by tag, roundtrip.

**Overlap:** The write and JSON roundtrips overlap with proposed Python
round-trip properties. The pymarc patterns overlap with proposed pymarc
equivalence tests.

**Recommendation: Augment.** Keep these tests — they document specific pymarc
usage patterns and serve as compatibility regression tests. Add Hypothesis
tests for differential comparison (same operations through pymarc and mrrc)
and for roundtrip properties over generated records with unusual structures
(empty fields, repeated tags, missing 245).

#### `suites/discovery/test_edge_cases.py` (~471 lines)

Python-side edge case discovery: fixture parse, DiscoveryWriter unit test,
local-mode parsing error/unusual leader/oversized record discovery.

**Overlap:** The Python `DiscoveryWriter` unit test overlaps with proposed
Hypothesis testing of helper functions. The local-mode discovery tests have no
formal methods equivalent.

**Recommendation: Augment (DiscoveryWriter), Keep (discovery scans).** Add
Hypothesis for `_extract_control_number()` and `_categorize_error()`. Keep the
local-mode discovery scans unchanged.

#### `suites/pymarc_compat/test_iteration_scale.py` (~92 lines)

Large-scale iteration and memory behavior (local mode).

**Overlap:** None.

**Recommendation: Keep.** Scale and memory tests are not addressable by formal
methods.

### Summary

| Repo | Existing test lines | Keep as-is | Augment | Replace |
|------|--------------------:|:----------:|:-------:|:-------:|
| **mrrc** | ~16,800 | ~5,400 | ~11,000 | ~400 |
| **mrrc-testbed** | ~5,000 | ~1,500 | ~3,300 | ~200 |

The overwhelming recommendation is **augment, not replace.** Existing tests
document specific known-good behavior and edge cases. Formal methods generalize
those same invariants to arbitrary inputs. The two approaches complement each
other: hand-written tests say "this specific case works," while property tests
and fuzzing say "the general rule holds." The few replacements are tests whose
entire purpose is subsumed (ASAN smoke tests for standard library types,
hand-enumerated byte sequences that fuzzing covers more thoroughly).

# Formal Methods Implementation Plan

This document is the actionable playbook for adding formal verification methods
to mrrc and mrrc-testbed. For the rationale behind each method — what it is,
why it matters, where it belongs — see `formal-methods-verification-strategy.md`.

## Implementation Phases

### Phase 1: Foundation

Add dependencies and write the first property tests. Get the feedback loop
working.

**Testbed:**
- Add `proptest = "1"` to `crates/mrrc_testbed/Cargo.toml` dev-dependencies
- Add `hypothesis>=6` to `pyproject.toml` dev dependencies
- Write `arb_record()` and supporting strategies in
  `crates/mrrc_testbed/tests/properties.rs`
- Implement binary MARC round-trip property (single highest-value test)
- Add `just test-properties` and `just test-properties-local` recipes
- Commit `proptest-regressions/` files

**mrrc:**
- Enable the existing `proptest` dev-dependency (already in Cargo.toml)
- Add `cargo-semver-checks` to CI (one-line GitHub Action addition)
- Add `cargo +nightly miri test` job to CI (nightly schedule)

### Phase 2: Broaden property tests

Fill out the remaining property groups.

**Testbed:**
- MARCXML and JSON round-trip properties
- Accessor coherence properties
- Builder stability properties
- Encoding round-trip properties (UTF-8 first; MARC-8 requires a valid byte
  sequence strategy — more work)
- Query DSL correctness properties

**mrrc:**
- Port strategies and core round-trip/accessor/encoding properties upstream
- Run `cargo mutants -f src/reader.rs -f src/encoding.rs` to assess test
  strength on the critical modules
- Write additional properties to kill surviving mutants

### Phase 3: Python properties

Add Hypothesis tests focused on cross-layer consistency.

**Testbed:**
- Register CI/local Hypothesis profiles in `suites/conftest.py`
- Cross-layer consistency tests seeded from fixtures
- Python API round-trip tests
- pymarc equivalence tests (if pymarc is available as a dev dependency)

### Phase 4: Fuzzing

Add coverage-guided fuzzing to mrrc.

**mrrc:**
- `cargo fuzz init` and add fuzz targets: `parse_record`, `parse_leader`,
  `decode_marc8`, `roundtrip_binary`
- Seed corpus from testbed fixtures
- Add timed fuzzing job to CI (5-minute run on each target per PR, extended
  runs nightly/weekly)
- Feed fuzzer-found crash inputs back to testbed as new fixture data

**Testbed:**
- Add `just fuzz-seed` recipe to export fixture data as fuzzer corpus

### Phase 5: Bounded proofs

Add Kani proofs for critical parsing primitives in mrrc.

**mrrc:**
- Leader parsing proof (no-panic + round-trip for all 24-byte inputs)
- Directory entry decoding proof (all 12-byte inputs)
- Record length validation proof (all 5-byte inputs)
- Encoding detection proof (all 256 leader byte values)
- Add `cargo kani` job to CI

### Phase 6: Continuous quality

Ongoing verification infrastructure.

**mrrc:**
- Run `cargo mutants` weekly; track surviving mutant count as a quality metric
- Run extended fuzzing campaigns (hours/days) periodically
- Review Kani bounds — can we increase them as the tool improves?

**Testbed:**
- Run `cargo mutants` on testbed's own test infrastructure
- Keep fixture corpus synchronized with fuzzer findings

## Cross-Repository Execution Plan

### The fundamental constraint

mrrc-testbed depends on mrrc. Changes to mrrc require a release (or at minimum
a commit-pinned git dependency bump) before the testbed can use them. Changes to
the testbed have no downstream impact. This asymmetry dictates the strategy:

- **Fast iteration happens in the testbed.** New strategies, new property
  families, experimental assertions — write them here first where the feedback
  loop is immediate.
- **Stable, proven work moves to mrrc.** Once a property or strategy is stable
  and has caught real bugs (or confirmed it will not produce false positives),
  upstream it. This is a one-way gate: upstreaming is a deliberate act, not an
  automatic process.
- **Some work starts and stays in mrrc.** Fuzzing targets, Kani proofs, Miri,
  cargo-semver-checks, and sanitizers operate on mrrc's internals and have no
  testbed equivalent. These go directly into mrrc.

### Execution waves

The six phases describe *what* to build. This section describes *how* to
sequence the work across the two repos. The phases do not need to be executed
strictly serially — they are grouped into three waves that can overlap.

#### Wave A: Low-hanging fruit (Phases 1 + beginning of 3)

Two workstreams running in parallel, one per repo.

**mrrc workstream (CI hardening):**

1. Add `cargo-semver-checks` GitHub Action. This is a single workflow file
   addition — no code changes, no dependency changes, immediate value. Run it
   on PRs that touch `src/`.
2. Add a nightly CI job that runs `cargo +nightly miri test` on the existing
   test suite. Start with the unit tests only (skip integration tests that do
   file I/O, which Miri cannot handle). Fix any issues Miri finds in the
   dependency chain.
3. Enable the existing `proptest` dev-dependency in Cargo.toml (it is already
   present but may be commented out). Write the first property test directly in
   mrrc: binary MARC round-trip for a generated record. This proves the tooling
   works before the testbed starts writing strategies.

These three steps are independent of each other and independent of the testbed.
They can be three separate PRs landing in any order.

**Testbed workstream (property testing foundation):**

1. Add `proptest = "1"` to `crates/mrrc_testbed/Cargo.toml` and `hypothesis>=6`
   to `pyproject.toml`.
2. Write `arb_record()` and supporting strategies in a new
   `crates/mrrc_testbed/tests/properties.rs`. Start with the simplest strategy
   that produces a parseable record.
3. Write the first Rust property: binary round-trip. This duplicates what mrrc
   is doing in its own repo — that is intentional. The testbed version iterates
   faster (no release cycle) and tests mrrc-as-dependency (catching issues at
   the integration boundary).
4. Add `just test-properties` and `just test-properties-local` recipes.
5. Register Hypothesis CI/local profiles in `suites/conftest.py`. Write the
   first Python property: encoding round-trip with `@given(st.text())`.

**Coordination point:** When the testbed's strategies are stable (they generate
valid records reliably, the round-trip property passes at 10,000 cases), compare
them with the strategies written directly in mrrc. Reconcile any differences.
The mrrc version becomes the canonical one; the testbed version can either
import it (once mrrc releases with the strategies exposed as test infrastructure)
or maintain a copy that tracks the mrrc version.

#### Wave B: Depth (Phases 2 + 3 + 4)

Three workstreams, partially overlapping.

**mrrc workstream 1 (broaden properties):**

1. Port the testbed's strategies upstream if they are more mature than the ones
   written directly in mrrc. Or vice versa — whichever version is better becomes
   the canonical one.
2. Fill out the remaining property families: MARCXML/JSON round-trips, accessor
   coherence, builder stability, encoding round-trips, query DSL. Write these
   directly in mrrc's `tests/properties.rs`.
3. Run `cargo mutants` on `src/reader.rs` and `src/encoding.rs` to assess
   whether the new properties are strong enough. Write additional properties to
   kill surviving mutants.

**mrrc workstream 2 (fuzzing):**

1. `cargo fuzz init` and add the first fuzz target: `parse_record`. This is
   independent of the property testing work.
2. Copy fixture `.mrc` files from the testbed's `data/fixtures/` into the fuzz
   corpus directory as seeds. (This is a manual copy, not a dependency — the
   fuzzer does not need the testbed at runtime.)
3. Run the fuzzer locally for an extended session (hours). Triage any crashes.
   For each crash that reveals a real bug: fix it in mrrc, add a regression
   test, and copy the crashing input to the testbed's `data/fixtures/` with
   provenance in `manifest.json`.
4. Add remaining fuzz targets: `parse_leader`, `decode_marc8`,
   `roundtrip_binary`, `parse_marcxml`, `parse_json`.
5. Add timed fuzzing to CI (5 minutes per target per PR; extended runs nightly).

**Testbed workstream (Python properties + corpus feedback):**

1. Write Hypothesis cross-layer consistency tests: for fixture records, assert
   Python and Rust produce identical field counts, control numbers, leaders,
   and accessor results.
2. Write Hypothesis pymarc equivalence tests (if pymarc is a dev dependency).
   Document any cases where pymarc is clearly wrong; file upstream issues.
3. Write a `just fuzz-seed` recipe that copies `data/fixtures/*.mrc` to a
   directory suitable for `cargo fuzz` corpus seeding.
4. As mrrc's fuzzer finds crashes, receive the crashing inputs as new fixtures.
   Add them to `data/fixtures/` with `manifest.json` provenance noting they
   came from fuzzing. Run the testbed's property tests against them to verify
   the fix.

**Coordination points:**

- Fuzzer-found crashes flow from mrrc to testbed as new fixtures (mrrc -> testbed).
- Fixture data flows from testbed to mrrc as fuzzer corpus seeds (testbed -> mrrc).
- Strategy improvements flow from testbed to mrrc as upstreamed code (testbed -> mrrc).
- mrrc releases with new fixes and strategies flow back (mrrc -> testbed via version bump).

This is a feedback loop, not a one-way pipeline. Expect to iterate.

#### Wave C: Advanced methods (Phases 5 + 6)

This wave depends on Waves A and B being substantially complete. Property tests
and fuzz targets should be stable before investing in bounded proofs and
continuous quality metrics.

**mrrc only:**

1. Install Kani and write the first proof: leader parsing (no-panic + roundtrip
   for all 24-byte inputs). Start with the simplest proof and verify the tooling
   works before writing more.
2. Add directory entry decoding proof, record length validation proof, encoding
   detection proof.
3. Add `cargo kani` to CI. Kani proofs are deterministic and relatively fast
   for small inputs — they can run on every PR.
4. Set up weekly `cargo mutants` runs. Track the surviving mutant count as a
   quality metric over time.
5. Schedule extended fuzzing campaigns (multi-hour or overnight) as periodic
   CI jobs. Review corpus growth and coverage reports.

**Testbed:**

1. Run `cargo mutants` on the testbed's own Rust tests to verify the assertions
   are meaningful.
2. Keep the fixture corpus synchronized with fuzzer findings from mrrc.
3. Periodically re-run Hypothesis tests at higher case counts (local mode) to
   look for rare failures.

## Managing the Work

### Tracking

This is a multi-session effort spanning weeks or months. Track it with beads
issues, not mental bookkeeping. Suggested issue structure:

- One **epic** per wave (Wave A, Wave B, Wave C).
- One **task** per discrete deliverable (e.g., "Add cargo-semver-checks to mrrc
  CI", "Write arb_record() strategy in testbed", "Add parse_record fuzz target
  to mrrc").
- Use **dependencies** to express sequencing constraints (e.g., "upstream
  strategies to mrrc" is blocked by "strategies stable in testbed").
- Tasks that span both repos get a note in the description saying which repo
  they touch.

Do not create all tasks upfront. Create Wave A tasks now. Create Wave B tasks
when Wave A is substantially done and the picture is clearer. Wave C tasks can
wait until Wave B is underway.

### Branch and PR strategy

**mrrc:** Each deliverable (CI addition, property test group, fuzz target set,
Kani proof) is one PR. Keep PRs focused — a PR that adds proptest should not
also add fuzzing. This makes review easier and keeps the commit history clean.

**Testbed:** Same principle, but PRs can be larger since the testbed is not a
published library and the review burden is lower.

**Cross-repo PRs:** When upstreaming strategies from testbed to mrrc, open the
mrrc PR first, get it merged and released (or commit-pinned), then open a
testbed PR that bumps the mrrc dependency and removes the testbed's duplicate
strategies. Do not try to land both simultaneously — the dependency relationship
makes that fragile.

### What "done" looks like for each wave

**Wave A is done when:**
- mrrc CI runs cargo-semver-checks, Miri, and at least one proptest property
- Testbed has `arb_record()`, at least one Rust property, at least one
  Hypothesis property, and `just test-properties` works
- Both repos' CI is green

**Wave B is done when:**
- mrrc has property tests covering all five families (round-trip, accessor,
  encoding, builder, query DSL)
- mrrc has at least `parse_record` and `decode_marc8` fuzz targets running in
  CI
- Testbed has Hypothesis cross-layer and pymarc equivalence tests
- `cargo mutants` has been run at least once on mrrc's critical modules and
  surviving mutants are documented
- The fixture corpus feedback loop has been exercised at least once (fuzzer
  finding -> testbed fixture -> testbed property test)

**Wave C is done when:**
- mrrc has Kani proofs for leader, directory, record length, and encoding
  detection
- `cargo mutants` and extended fuzzing are running on a schedule
- Surviving mutant count is tracked as a metric

### Effort estimates

Rough estimates, assuming familiarity with the tools:

| Deliverable | Effort | Repo |
|-------------|--------|------|
| cargo-semver-checks CI | 1 hour | mrrc |
| Miri CI job | 2-4 hours | mrrc |
| First proptest property + strategies | 1-2 days | testbed |
| Enable proptest + first property in mrrc | half day | mrrc |
| Hypothesis profiles + first property | half day | testbed |
| Remaining Rust property families | 2-3 days | mrrc |
| Upstream strategies testbed -> mrrc | half day | both |
| cargo-fuzz init + first target | half day | mrrc |
| Remaining fuzz targets (5) | 1-2 days | mrrc |
| Fuzzing CI integration | 2-4 hours | mrrc |
| Hypothesis cross-layer tests | 1-2 days | testbed |
| Hypothesis pymarc equivalence | 1 day | testbed |
| Kani setup + first proof | 1 day | mrrc |
| Remaining Kani proofs (3) | 1-2 days | mrrc |
| cargo-mutants first run + triage | half day | mrrc |
| Fixture corpus feedback loop | ongoing | both |

Total: roughly **2-3 weeks of focused work** spread across both repos, or
**4-6 weeks** at a sustainable part-time pace. Wave A can be done in a few
days. Wave B is the bulk of the effort. Wave C is incremental.

### When to stop

Not everything in this plan needs to happen. The value curve is steep
at the beginning and flattens out. A practical stopping point for each level:

- **Property testing:** Stop adding new property families when `cargo mutants`
  shows few surviving mutants in the modules you care about. Diminishing returns
  after the core five families are covered.
- **Fuzzing:** Stop adding new fuzz targets when the existing ones have run for
  hours without finding new crashes. Keep the CI job running indefinitely — it
  costs little and occasionally finds something.
- **Kani:** Stop after the small-input proofs (leader, directory, record length,
  encoding). Extending bounds further has rapidly diminishing returns for a
  parsing library.
- **Mutation testing:** Use it as a periodic check, not a continuous gate. A
  surviving mutant count of zero is not a realistic goal and pursuing it leads
  to over-specified tests.

The goal is a safe, reliable, consistent, and fast library — not a research
project in formal verification. Use each tool until it stops finding bugs, then
move on.

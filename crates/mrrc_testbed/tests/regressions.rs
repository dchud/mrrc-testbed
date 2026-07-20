//! Regression corpus: inputs that once made mrrc mishandle a record.
//!
//! Files live in `data/regressions/` — a committed *sibling* of
//! `data/fixtures/`, kept separate so the fixtures' parse-clean invariant is
//! not disturbed (see `data/regressions/README.md`). Each input is malformed or
//! otherwise pathological by design; the guarantee enforced here is **no panic
//! and no hang** across every recovery mode. A returned `Err` is acceptable and
//! often expected — this test guards against panics and silent pathologies, not
//! against error returns.
//!
//! CI-safe: no `#[ignore]`. While the corpus is empty the test is a no-op.

use std::io::Cursor;
use std::panic;

use mrrc::{MarcReader, RecoveryMode};

/// Drain every record from `data` in `mode`, discarding results. Returns
/// `false` only if the reader panicked (caught via `catch_unwind`); parse
/// errors are swallowed on purpose — they are an acceptable outcome.
fn reads_without_panic(data: &[u8], mode: RecoveryMode) -> bool {
    let data = data.to_vec();
    panic::catch_unwind(move || {
        let cursor = Cursor::new(data);
        let mut reader = MarcReader::new(cursor).with_recovery_mode(mode);
        // Drain until end-of-stream (`Ok(None)`) or a parse error (`Err`).
        // Errors are an acceptable outcome; only a panic fails the test.
        while let Ok(Some(_)) = reader.read_record() {}
    })
    .is_ok()
}

/// Every committed regression input must be handled without a panic in all
/// three recovery modes. Errors are fine; panics are not.
#[test]
fn regression_inputs_no_panic() {
    let dir = mrrc_testbed::project_root()
        .join("data")
        .join("regressions");
    let files = mrrc_testbed::iter_mrc_files(&dir);

    if files.is_empty() {
        println!(
            "No regression inputs in {}; nothing to exercise.",
            dir.display()
        );
        return;
    }

    let modes = [
        ("strict", RecoveryMode::Strict),
        ("lenient", RecoveryMode::Lenient),
        ("permissive", RecoveryMode::Permissive),
    ];

    let mut panics: Vec<String> = Vec::new();

    for path in &files {
        let data = std::fs::read(path)
            .unwrap_or_else(|e| panic!("Failed to read regression input {}: {e}", path.display()));
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("<unknown>");

        for (mode_name, mode) in modes {
            if !reads_without_panic(&data, mode) {
                panics.push(format!("{name} in {mode_name} mode"));
            }
        }
    }

    if !panics.is_empty() {
        let list = panics.join("\n  - ");
        panic!(
            "mrrc panicked on committed regression inputs:\n  - {list}\n\
             Panics are not acceptable — errors are fine, panics are not."
        );
    }

    println!(
        "Regression corpus: {} file(s) x {} mode(s), no panics.",
        files.len(),
        modes.len()
    );
}

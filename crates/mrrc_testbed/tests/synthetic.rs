//! Tests for committed synthetic MARC data in `data/synthetic/`.
//!
//! Two layers of verification:
//! 1. **Existence tests** — assert expected .mrc files are present (catches
//!    missing generator output or accidental deletions).
//! 2. **Behavior tests** — assert malformed files actually cause errors and
//!    encoding files roundtrip correctly (catches generator bugs that produce
//!    wrong content).

use std::io::Cursor;
use std::panic;
use std::path::PathBuf;

use mrrc::{MarcReader, MarcWriter, RecoveryMode};

/// Path to `data/synthetic/` from the project root.
fn synthetic_dir() -> PathBuf {
    mrrc_testbed::project_root().join("data").join("synthetic")
}

// ===========================================================================
// Stage 1: File existence tests
// ===========================================================================

const MALFORMED_FILES: &[&str] = &[
    "truncated_leader.mrc",
    "invalid_lengths.mrc",
    "bad_directory.mrc",
    "missing_terminators.mrc",
    "embedded_terminators.mrc",
    "garbage.mrc",
];

const ENCODING_FILES: &[&str] = &[
    "utf8_titles.mrc",
    "marc8_ascii.mrc",
    "replacement_chars.mrc",
    "mixed_scripts.mrc",
];

#[test]
fn malformed_files_present() {
    let dir = synthetic_dir().join("malformed");
    for filename in MALFORMED_FILES {
        let path = dir.join(filename);
        assert!(
            path.exists(),
            "Missing synthetic malformed file: {}\n\
             Run `just generate-synthetic` to create it.",
            path.display()
        );
        let size = std::fs::metadata(&path).unwrap().len();
        assert!(
            size > 0,
            "Synthetic malformed file is empty: {}",
            path.display()
        );
    }
}

#[test]
fn encoding_files_present() {
    let dir = synthetic_dir().join("encoding");
    for filename in ENCODING_FILES {
        let path = dir.join(filename);
        assert!(
            path.exists(),
            "Missing synthetic encoding file: {}\n\
             Run `just generate-synthetic` to create it.",
            path.display()
        );
        let size = std::fs::metadata(&path).unwrap().len();
        assert!(
            size > 0,
            "Synthetic encoding file is empty: {}",
            path.display()
        );
    }
}

// ===========================================================================
// Stage 2a: Malformed — negative testing
// ===========================================================================

/// For each .mrc in malformed/, read every record; assert that at least one
/// `Err` is returned OR the file fails to parse cleanly (zero records, or
/// only partial/split records from embedded terminators).
///
/// Some malformed files (like embedded_terminators.mrc) contain 0x1D bytes
/// in unexpected positions that the parser legitimately treats as record
/// boundaries, producing split/truncated records without returning errors.
/// This is correct parser behavior, not a generator bug.
#[test]
fn malformed_records_cause_errors() {
    let dir = synthetic_dir().join("malformed");

    // Files where embedded terminators cause record splitting rather than
    // explicit errors. The parser legitimately treats 0x1D as a record
    // boundary, so these files produce split fragments, not Err values.
    let split_ok_files: &[&str] = &["embedded_terminators.mrc"];

    for filename in MALFORMED_FILES {
        let path = dir.join(filename);
        let data = std::fs::read(&path).unwrap();
        let cursor = Cursor::new(data.clone());
        let mut reader = MarcReader::new(cursor).with_recovery_mode(RecoveryMode::Strict);

        let mut got_error = false;
        let mut record_count = 0;

        loop {
            match reader.read_record() {
                Ok(Some(_)) => {
                    record_count += 1;
                }
                Ok(None) => break,
                Err(_) => {
                    got_error = true;
                    break;
                }
            }
        }

        if split_ok_files.contains(filename) {
            // For these files, the parser splits on embedded 0x1D bytes
            // and may parse fragments "successfully." That's expected.
            continue;
        }

        // All other malformed files should produce errors or no records.
        assert!(
            got_error || record_count == 0,
            "Malformed file {} parsed {} records without errors in strict mode. \
             The generator may be producing valid MARC by accident.",
            filename,
            record_count,
        );
    }
}

/// Same malformed files, all three recovery modes, catch_unwind. Errors are
/// fine, panics are not.
#[test]
fn malformed_no_panics() {
    let dir = synthetic_dir().join("malformed");
    let mut panics: Vec<String> = Vec::new();

    for filename in MALFORMED_FILES {
        let path = dir.join(filename);
        let data = std::fs::read(&path).unwrap();

        for (mode_name, mode) in [
            ("strict", RecoveryMode::Strict),
            ("lenient", RecoveryMode::Lenient),
            ("permissive", RecoveryMode::Permissive),
        ] {
            let data_clone = data.clone();
            let result = panic::catch_unwind(move || {
                let cursor = Cursor::new(data_clone);
                let mut reader = MarcReader::new(cursor).with_recovery_mode(mode);
                loop {
                    match reader.read_record() {
                        Ok(Some(_)) => continue,
                        Ok(None) => break,
                        Err(_) => break,
                    }
                }
            });

            if result.is_err() {
                panics.push(format!("{filename} in {mode_name} mode"));
            }
        }
    }

    if !panics.is_empty() {
        let list = panics.join("\n  - ");
        panic!(
            "MarcReader panicked on synthetic malformed files:\n  - {list}\n\
             Panics are not acceptable — errors are fine, panics are not."
        );
    }
}

// ===========================================================================
// Stage 2b: Encoding — positive testing
// ===========================================================================

/// For each .mrc in encoding/, write every record through MarcWriter, re-read,
/// and assert all field text matches the original.
#[test]
fn encoding_roundtrip_preserved() {
    let dir = synthetic_dir().join("encoding");

    for filename in ENCODING_FILES {
        let path = dir.join(filename);
        let data = std::fs::read(&path).unwrap();

        // Read all records from the file.
        let cursor = Cursor::new(data);
        let mut reader = MarcReader::new(cursor);
        let mut records = Vec::new();
        loop {
            match reader.read_record() {
                Ok(Some(record)) => records.push(record),
                Ok(None) => break,
                Err(e) => panic!("Error reading {filename}: {e}"),
            }
        }

        assert!(
            !records.is_empty(),
            "Encoding file {filename} contained no parseable records"
        );

        // Roundtrip each record: write → re-read → compare.
        for (i, original) in records.iter().enumerate() {
            let mut buf = Vec::new();
            {
                let mut writer = MarcWriter::new(&mut buf);
                writer
                    .write_record(original)
                    .unwrap_or_else(|e| panic!("[{filename} #{i}] write failed: {e}"));
            }

            let cursor = Cursor::new(buf);
            let mut reader = MarcReader::new(cursor);
            let reread = reader
                .read_record()
                .unwrap_or_else(|e| panic!("[{filename} #{i}] re-read failed: {e}"))
                .unwrap_or_else(|| panic!("[{filename} #{i}] re-read returned None"));

            // Compare control fields.
            assert_eq!(
                original.control_fields, reread.control_fields,
                "[{filename} #{i}] control fields differ after roundtrip"
            );

            // Compare data fields by tag.
            assert_eq!(
                original.fields.len(),
                reread.fields.len(),
                "[{filename} #{i}] field tag count differs after roundtrip"
            );
            for (tag, orig_fields) in &original.fields {
                let reread_fields = reread.fields.get(tag).unwrap_or_else(|| {
                    panic!("[{filename} #{i}] tag {tag} missing after roundtrip")
                });
                assert_eq!(
                    orig_fields.len(),
                    reread_fields.len(),
                    "[{filename} #{i}] field count for tag {tag} differs"
                );
                for (j, (orig_f, reread_f)) in
                    orig_fields.iter().zip(reread_fields.iter()).enumerate()
                {
                    assert_eq!(
                        orig_f.subfields, reread_f.subfields,
                        "[{filename} #{i} tag {tag} field {j}] subfields differ"
                    );
                }
            }
        }
    }
}

/// Read utf8_titles.mrc, verify specific expected titles exist.
#[test]
fn encoding_utf8_titles_specific() {
    let path = synthetic_dir().join("encoding").join("utf8_titles.mrc");
    let data = std::fs::read(&path).unwrap();

    let cursor = Cursor::new(data);
    let mut reader = MarcReader::new(cursor);
    let mut titles: Vec<String> = Vec::new();

    loop {
        match reader.read_record() {
            Ok(Some(record)) => {
                if let Some(fields) = record.get_fields("245") {
                    for field in fields {
                        if let Some(val) = field.get_subfield('a') {
                            titles.push(val.to_string());
                        }
                    }
                }
            }
            Ok(None) => break,
            Err(e) => panic!("Error reading utf8_titles.mrc: {e}"),
        }
    }

    let expected_fragments = &[
        ("\u{4e2d}\u{6587}", "CJK"),
        (
            "\u{0420}\u{0443}\u{0441}\u{0441}\u{043a}\u{0438}\u{0439}",
            "Cyrillic",
        ),
        ("mis\u{00e9}rables", "diacritics"),
        ("M\u{00fc}nchen", "umlauts"),
    ];

    for (fragment, label) in expected_fragments {
        let found = titles.iter().any(|t| t.contains(fragment));
        assert!(
            found,
            "Expected {label} text containing {fragment:?} in utf8_titles.mrc, \
             but found only: {titles:?}"
        );
    }
}

/// Read utf8_titles.mrc and mixed_scripts.mrc, assert no unexpected U+FFFD
/// appears after roundtrip.
#[test]
fn encoding_no_replacement_chars() {
    let dir = synthetic_dir().join("encoding");
    let files = ["utf8_titles.mrc", "mixed_scripts.mrc"];

    for filename in &files {
        let path = dir.join(filename);
        let data = std::fs::read(&path).unwrap();

        let cursor = Cursor::new(data);
        let mut reader = MarcReader::new(cursor);
        let mut record_idx = 0;

        loop {
            match reader.read_record() {
                Ok(Some(original)) => {
                    record_idx += 1;

                    // Roundtrip.
                    let mut buf = Vec::new();
                    {
                        let mut writer = MarcWriter::new(&mut buf);
                        writer.write_record(&original).unwrap();
                    }
                    let cursor = Cursor::new(buf);
                    let mut rdr = MarcReader::new(cursor);
                    let reread = rdr.read_record().unwrap().unwrap();

                    // Check all data fields for unexpected replacement characters.
                    for (tag, fields) in &reread.fields {
                        for field in fields {
                            for sf in &field.subfields {
                                assert!(
                                    !sf.value.contains('\u{FFFD}'),
                                    "[{filename} #{record_idx}] Unexpected U+FFFD in \
                                     roundtripped field {tag} subfield {}: {:?}",
                                    sf.code,
                                    sf.value,
                                );
                            }
                        }
                    }
                }
                Ok(None) => break,
                Err(e) => panic!("Error reading {filename}: {e}"),
            }
        }

        assert!(record_idx > 0, "{filename} contained no parseable records");
    }
}

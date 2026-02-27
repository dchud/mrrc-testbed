//! International character and encoding tests for mrrc.
//!
//! Tests encoding roundtrips, UTF-8 detection, MARC-8 handling, and replacement
//! character detection. CI-safe tests use synthetic records; local-mode tests
//! exercise real-world datasets from LOC.

use std::io::Cursor;

use mrrc::encoding::{MarcEncoding, decode_bytes, encode_string};
use mrrc::encoding_validation::{EncodingAnalysis, EncodingValidator};
use mrrc::{Field, Leader, MarcReader, MarcWriter, Record};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Build a Leader suitable for test records. The `character_coding` field
/// controls position 9 of the serialised leader ('a' = UTF-8, ' ' = MARC-8).
fn test_leader(character_coding: char) -> Leader {
    Leader {
        record_length: 0,
        record_status: 'n',
        record_type: 'a',
        bibliographic_level: 'm',
        control_record_type: ' ',
        character_coding,
        indicator_count: 2,
        subfield_code_count: 2,
        data_base_address: 0,
        encoding_level: ' ',
        cataloging_form: ' ',
        multipart_level: ' ',
        reserved: "4500".to_string(),
    }
}

/// Write a single `Record` to an in-memory buffer and read it back, returning
/// the reconstituted record. Panics on any I/O or parse error.
fn roundtrip_record(record: &Record) -> Record {
    let mut buf = Vec::new();
    {
        let mut writer = MarcWriter::new(&mut buf);
        writer.write_record(record).unwrap();
    }
    let cursor = Cursor::new(buf);
    let mut reader = MarcReader::new(cursor);
    reader.read_record().unwrap().expect("expected one record")
}

/// Build a minimal synthetic record with a single 245$a value and the given
/// character coding in the leader.
fn synthetic_record(character_coding: char, title: &str) -> Record {
    let mut record = Record::new(test_leader(character_coding));
    record.add_control_field("001".to_string(), "test-001".to_string());
    let mut field = Field::new("245".to_string(), '1', '0');
    field.add_subfield('a', title.to_string());
    record.add_field(field);
    record
}

/// Extract all text from the given tags/subfield-codes of a record.
/// Returns a single concatenated string for easy inspection.
fn extract_text(record: &Record, tags: &[&str], codes: &[char]) -> String {
    let mut parts = Vec::new();
    for &tag in tags {
        if let Some(fields) = record.get_fields(tag) {
            for field in fields {
                for code in codes {
                    if let Some(val) = field.get_subfield(*code) {
                        parts.push(val.to_string());
                    }
                }
            }
        }
    }
    parts.join(" ")
}

/// Return `true` if the string contains the Unicode replacement character
/// U+FFFD that was not already present in `original`.
fn has_new_replacement_chars(original: &str, output: &str) -> bool {
    let orig_count = original.matches('\u{FFFD}').count();
    let out_count = output.matches('\u{FFFD}').count();
    out_count > orig_count
}

// ---------------------------------------------------------------------------
// Local-mode roundtrip tests (require downloaded datasets)
// ---------------------------------------------------------------------------

/// Helper: for every record across available datasets, extract text fields,
/// write through MarcWriter, re-read, and verify the text matches. Returns the
/// number of records successfully roundtripped.
///
/// Tries each dataset name in `preferred_datasets` first, then falls back to
/// all standard datasets. Uses whichever files are available.
fn roundtrip_dataset_records(
    preferred_datasets: &[&str],
    tags: &[&str],
    codes: &[char],
    filter: impl Fn(&str) -> bool,
    max_records: usize,
) -> usize {
    mrrc_testbed::require_local_mode();

    // Build file list: try preferred datasets first, then all standard ones.
    let mut files = mrrc_testbed::collect_dataset_files(preferred_datasets);
    if files.is_empty() {
        files = mrrc_testbed::collect_dataset_files(mrrc_testbed::DATASET_NAMES);
    }
    assert!(
        !files.is_empty(),
        "No .mrc files found for any available dataset"
    );

    let mut tested = 0usize;
    let mut total_scanned = 0usize;

    for file_path in &files {
        if tested >= max_records {
            break;
        }

        let file = match std::fs::File::open(file_path) {
            Ok(f) => f,
            Err(e) => {
                eprintln!("Warning: cannot open {}: {e}", file_path.display());
                continue;
            }
        };
        // Use lenient mode so we can scan past malformed records in large datasets.
        let mut reader = MarcReader::new(file).with_recovery_mode(mrrc::RecoveryMode::Lenient);

        let mut record_idx = 0usize;

        loop {
            if tested >= max_records {
                break;
            }
            match reader.read_record() {
                Ok(Some(record)) => {
                    record_idx += 1;
                    total_scanned += 1;
                    let original_text = extract_text(&record, tags, codes);
                    if original_text.is_empty() || !filter(&original_text) {
                        continue;
                    }

                    let reread = roundtrip_record(&record);
                    let reread_text = extract_text(&reread, tags, codes);

                    assert_eq!(
                        original_text,
                        reread_text,
                        "Roundtrip mismatch at record #{record_idx} in {}",
                        file_path.display()
                    );
                    assert!(
                        !has_new_replacement_chars(&original_text, &reread_text),
                        "New replacement characters (mojibake) at record #{record_idx} in {}",
                        file_path.display()
                    );
                    tested += 1;
                }
                Ok(None) => break,
                Err(e) => {
                    eprintln!(
                        "Warning: skipping malformed record #{record_idx} in {}: {e}",
                        file_path.display()
                    );
                    break;
                }
            }
        }
    }

    if tested == 0 {
        eprintln!(
            "Warning: No matching records found across available datasets \
             (scanned {total_scanned} records). Download LOC datasets for \
             comprehensive encoding coverage."
        );
    }
    tested
}

/// Returns `true` if the string contains at least one CJK Unified Ideograph
/// (U+4E00..U+9FFF) or CJK compatibility character.
fn contains_cjk(s: &str) -> bool {
    s.chars()
        .any(|c| ('\u{4E00}'..='\u{9FFF}').contains(&c) || ('\u{3400}'..='\u{4DBF}').contains(&c))
}

/// Returns `true` if the string contains at least one Cyrillic character
/// (U+0400..U+04FF).
fn contains_cyrillic(s: &str) -> bool {
    s.chars().any(|c| ('\u{0400}'..='\u{04FF}').contains(&c))
}

/// Returns `true` if the string contains at least one Latin character with
/// a diacritical mark (common in French, German, Spanish, Portuguese).
fn contains_diacritics(s: &str) -> bool {
    s.chars().any(|c| {
        ('\u{00C0}'..='\u{00FF}').contains(&c) // Latin-1 Supplement accented
            || ('\u{0100}'..='\u{017F}').contains(&c) // Latin Extended-A
            || ('\u{0180}'..='\u{024F}').contains(&c) // Latin Extended-B
    })
}

#[test]
#[ignore] // local mode only
fn cjk_roundtrip() {
    let count = roundtrip_dataset_records(
        &["loc_books", "ia_lendable", "watson"],
        &["245", "100", "700"],
        &['a', 'b', 'c'],
        contains_cjk,
        200,
    );
    eprintln!("CJK roundtrip: {count} records verified");
}

#[test]
#[ignore] // local mode only
fn cyrillic_roundtrip() {
    let count = roundtrip_dataset_records(
        &["loc_names", "loc_books", "ia_lendable", "watson"],
        &["245", "100", "700"],
        &['a', 'b', 'c', 'd'],
        contains_cyrillic,
        200,
    );
    eprintln!("Cyrillic roundtrip: {count} records verified");
}

#[test]
#[ignore] // local mode only
fn diacritics_roundtrip() {
    let count = roundtrip_dataset_records(
        &["loc_books", "ia_lendable", "watson"],
        &["245", "100", "700"],
        &['a', 'b', 'c'],
        contains_diacritics,
        200,
    );
    eprintln!("Diacritics roundtrip: {count} records verified");
}

// ---------------------------------------------------------------------------
// CI-safe encoding tests (synthetic records)
// ---------------------------------------------------------------------------

#[test]
fn utf8_detection() {
    // Test cases: (label, title text, character_coding)
    // All use leader pos 9 = 'a' (UTF-8).
    let cases: &[(&str, &str)] = &[
        ("ascii_only", "A simple ASCII title"),
        (
            "latin_diacritics",
            "Les mis\u{00E9}rables : \u{00F1}o\u{00F1}o \u{00FC}ber",
        ),
        (
            "cjk_characters",
            "\u{4E2D}\u{6587}\u{6D4B}\u{8BD5}\u{6807}\u{9898}",
        ),
        (
            "cyrillic_text",
            "\u{0420}\u{0443}\u{0441}\u{0441}\u{043A}\u{0438}\u{0439} \u{0442}\u{0435}\u{043A}\u{0441}\u{0442}",
        ),
    ];

    for &(label, title) in cases {
        let record = synthetic_record('a', title);

        // Verify encoding detection via EncodingValidator.
        let analysis = EncodingValidator::analyze_encoding(&record)
            .unwrap_or_else(|e| panic!("[{label}] analyze_encoding failed: {e}"));
        match &analysis {
            EncodingAnalysis::Consistent(MarcEncoding::Utf8) => { /* expected */ }
            other => {
                // Mixed or Marc8 is acceptable only if the content is pure
                // ASCII (which is ambiguous).
                if label != "ascii_only" {
                    panic!("[{label}] Expected Consistent(Utf8), got {other:?}");
                }
            }
        }

        // Roundtrip through write/read and verify content is preserved.
        let reread = roundtrip_record(&record);

        // Leader position 9 should be preserved.
        assert_eq!(
            reread.leader.character_coding, 'a',
            "[{label}] leader character_coding not preserved"
        );

        // The 245$a text should survive the roundtrip.
        let original_title = record
            .get_field("245")
            .and_then(|f| f.get_subfield('a'))
            .unwrap();
        let reread_title = reread
            .get_field("245")
            .and_then(|f| f.get_subfield('a'))
            .unwrap();
        assert_eq!(
            original_title, reread_title,
            "[{label}] title not preserved through roundtrip"
        );
    }
}

#[test]
fn marc8_handling() {
    // Create a synthetic record with leader pos 9 = ' ' (MARC-8 indicator).
    // Fill it with pure ASCII content so the binary representation is valid
    // under both MARC-8 and UTF-8 — this lets us verify that mrrc does not
    // crash and that the leader value is preserved through a roundtrip.
    let record = synthetic_record(' ', "A MARC-8 record with ASCII content");

    // Verify leader value.
    assert_eq!(record.leader.character_coding, ' ');

    // Roundtrip.
    let reread = roundtrip_record(&record);
    assert_eq!(
        reread.leader.character_coding, ' ',
        "MARC-8 character coding should be preserved"
    );

    let original_title = record
        .get_field("245")
        .and_then(|f| f.get_subfield('a'))
        .unwrap();
    let reread_title = reread
        .get_field("245")
        .and_then(|f| f.get_subfield('a'))
        .unwrap();
    assert_eq!(
        original_title, reread_title,
        "ASCII content should survive MARC-8 roundtrip"
    );

    // Additionally test the encoding module's decode_bytes/encode_string
    // with the Marc8 variant to confirm it does not panic on simple input.
    let ascii_bytes = b"Hello World";
    let decoded = decode_bytes(ascii_bytes, MarcEncoding::Marc8)
        .expect("decode_bytes(Marc8) should not fail on ASCII");
    assert_eq!(decoded, "Hello World");

    let encoded = encode_string("Hello World", MarcEncoding::Marc8)
        .expect("encode_string(Marc8) should not fail on ASCII");
    let re_decoded =
        decode_bytes(&encoded, MarcEncoding::Marc8).expect("re-decode should not fail");
    assert_eq!(re_decoded, "Hello World");
}

#[test]
fn replacement_character_detection() {
    // Build a well-formed UTF-8 record and roundtrip it. No replacement
    // characters should appear in the output.
    let titles = &[
        "A plain ASCII title",
        "Caf\u{00E9} \u{00E0} la carte",
        "\u{4E2D}\u{6587}\u{56FE}\u{4E66}\u{9986}",
        "\u{041C}\u{043E}\u{0441}\u{043A}\u{0432}\u{0430}",
        "M\u{00FC}nchen \u{00D6}sterreich Stra\u{00DF}e",
    ];

    for &title in titles {
        let record = synthetic_record('a', title);
        let reread = roundtrip_record(&record);
        let reread_title = reread
            .get_field("245")
            .and_then(|f| f.get_subfield('a'))
            .unwrap();

        assert!(
            !reread_title.contains('\u{FFFD}'),
            "Replacement character U+FFFD found in roundtripped title: {title:?} -> {reread_title:?}"
        );
        assert_eq!(
            title, reread_title,
            "Title not preserved: {title:?} -> {reread_title:?}"
        );
    }

    // Build a record that already contains a replacement character and verify
    // we can detect it.
    let bad_title = "Broken \u{FFFD} encoding";
    let record = synthetic_record('a', bad_title);
    let reread = roundtrip_record(&record);
    let reread_title = reread
        .get_field("245")
        .and_then(|f| f.get_subfield('a'))
        .unwrap();
    assert!(
        reread_title.contains('\u{FFFD}'),
        "Pre-existing replacement character should survive roundtrip"
    );
}

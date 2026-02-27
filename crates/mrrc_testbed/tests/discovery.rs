//! Edge case cataloging tests.
//!
//! These tests scan real-world MARC datasets for records with unusual or extreme
//! characteristics. Local-mode tests target downloaded datasets (Watson, LOC) to
//! discover edge cases that curated fixtures miss.  The CI-safe test validates
//! that all committed fixture records parse without error.

use std::collections::HashMap;
use std::fs::File;
use std::io::Cursor;
use std::path::Path;

use mrrc::encoding::MarcEncoding;
use mrrc::encoding_validation::EncodingAnalysis;
use mrrc::{EncodingValidator, MarcReader, RecoveryMode};
use mrrc_testbed::discovery::DiscoveryWriter;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Tags that the MARC 21 standard defines as non-repeatable.
/// A subset used for heuristic detection of unusual repetition.
const NON_REPEATABLE_TAGS: &[&str] = &[
    "001", "003", "005", "008", "010", "018", "036", "038", "040", "042", "043", "044", "045",
    "066", "100", "110", "111", "130", "240", "243", "245", "254", "256", "263",
];

/// Try to read all records from a file using the given recovery mode.
/// Returns (records_ok, records_err, raw errors with byte offsets).
fn scan_file_records(
    path: &Path,
    recovery_mode: RecoveryMode,
) -> (Vec<mrrc::Record>, Vec<(u64, mrrc::MarcError)>) {
    let data = match std::fs::read(path) {
        Ok(d) => d,
        Err(_) => return (Vec::new(), Vec::new()),
    };

    let mut reader = MarcReader::new(Cursor::new(data.clone())).with_recovery_mode(recovery_mode);

    let mut ok_records = Vec::new();
    let mut errors = Vec::new();
    let mut offset: u64 = 0;

    loop {
        match reader.read_record() {
            Ok(Some(record)) => {
                // Advance offset past this record (approximate via leader length).
                offset += record.leader.record_length as u64;
                ok_records.push(record);
            }
            Ok(None) => break,
            Err(e) => {
                errors.push((offset, e));
                // We cannot reliably skip to the next record after a parse error
                // in strict mode, so stop scanning this file.
                break;
            }
        }
    }

    (ok_records, errors)
}

// ---------------------------------------------------------------------------
// 1. Unusual field combinations — local mode
// ---------------------------------------------------------------------------

#[test]
#[ignore]
fn unusual_field_combinations() {
    mrrc_testbed::require_local_mode();

    let mrc_files = mrrc_testbed::collect_dataset_files(mrrc_testbed::DATASET_NAMES);
    assert!(
        !mrc_files.is_empty(),
        "No .mrc files found for any available dataset"
    );

    let mut total_records: u64 = 0;
    let mut high_field_count_records: u64 = 0;
    let mut nine_xx_records: u64 = 0;
    let mut repeated_non_repeatable: u64 = 0;
    let mut max_field_count: usize = 0;
    let mut tag_frequency: HashMap<String, u64> = HashMap::new();

    for file_path in &mrc_files {
        println!("Scanning: {}", file_path.display());
        let (records, _errors) = scan_file_records(file_path, RecoveryMode::Lenient);

        for record in &records {
            total_records += 1;

            // Count all data fields.
            let field_count: usize = record.fields.values().map(|v| v.len()).sum();

            if field_count > max_field_count {
                max_field_count = field_count;
            }

            // High field count (>50).
            if field_count > 50 {
                high_field_count_records += 1;
                if high_field_count_records <= 5 {
                    let cn = record.get_control_field("001").unwrap_or("unknown");
                    println!("  High field count ({field_count}): control number = {cn}");
                }
            }

            // 9xx local fields.
            let has_nine_xx = record.fields.keys().any(|tag| tag.starts_with('9'));
            if has_nine_xx {
                nine_xx_records += 1;
            }

            // Repeated non-repeatable tags.
            for tag in NON_REPEATABLE_TAGS {
                if let Some(fields) = record.get_fields(tag) {
                    if fields.len() > 1 {
                        repeated_non_repeatable += 1;
                        if repeated_non_repeatable <= 5 {
                            let cn = record.get_control_field("001").unwrap_or("unknown");
                            println!(
                                "  Repeated non-repeatable tag {tag} ({} times): cn = {cn}",
                                fields.len()
                            );
                        }
                    }
                }
            }

            // Tag frequency accumulation.
            for tag in record.fields.keys() {
                *tag_frequency.entry(tag.clone()).or_insert(0) += 1;
            }
        }
    }

    // Summary
    println!("\n=== Unusual Field Combinations Summary ===");
    println!("Total records scanned: {total_records}");
    println!("Records with >50 fields: {high_field_count_records}");
    println!("Records with 9xx local fields: {nine_xx_records}");
    println!("Repeated non-repeatable tag occurrences: {repeated_non_repeatable}");
    println!("Max field count in a single record: {max_field_count}");

    // Print the 10 least common tags.
    let mut freq_vec: Vec<_> = tag_frequency.iter().collect();
    freq_vec.sort_by_key(|(_, count)| *count);
    println!("\nLeast common tags (bottom 10):");
    for (tag, count) in freq_vec.iter().take(10) {
        println!("  {tag}: {count}");
    }
}

// ---------------------------------------------------------------------------
// 2. Extreme values — local mode
// ---------------------------------------------------------------------------

#[test]
#[ignore]
fn extreme_values() {
    mrrc_testbed::require_local_mode();

    let mrc_files = mrrc_testbed::collect_dataset_files(mrrc_testbed::DATASET_NAMES);
    assert!(
        !mrc_files.is_empty(),
        "No .mrc files found for any available dataset"
    );

    let mut writer = DiscoveryWriter::new("discovery.rs", "extreme_values");

    let mut total_records: u64 = 0;
    let mut large_record_count: u64 = 0;
    let mut long_field_count: u64 = 0;
    let mut many_subfield_count: u64 = 0;
    let mut long_subfield_count: u64 = 0;

    for file_path in &mrc_files {
        println!("Scanning for extreme values: {}", file_path.display());

        // Read the raw file for offset tracking and DiscoveryWriter.
        let raw_data = match std::fs::read(file_path) {
            Ok(d) => d,
            Err(e) => {
                println!("  Failed to read file: {e}");
                continue;
            }
        };

        let mut reader = MarcReader::new(Cursor::new(raw_data.clone()))
            .with_recovery_mode(RecoveryMode::Lenient);

        let mut offset: u64 = 0;

        loop {
            match reader.read_record() {
                Ok(Some(record)) => {
                    total_records += 1;
                    writer.add_records_processed(1);
                    let record_len = record.leader.record_length as u64;

                    // Very large total record size (>50KB as declared in leader).
                    if record_len > 50_000 {
                        large_record_count += 1;
                        let cn = record.get_control_field("001").unwrap_or("unknown");
                        println!("  Large record ({record_len} bytes): cn = {cn}");
                    }

                    for (tag, fields) in &record.fields {
                        for field in fields {
                            // Estimate serialized field size from subfield values.
                            let field_size: usize = field
                                .subfields
                                .iter()
                                .map(|sf| sf.value.len() + 2) // code + delimiter + value
                                .sum::<usize>()
                                + 2; // indicators

                            // Very long field (>10KB).
                            if field_size > 10_000 {
                                long_field_count += 1;
                                if long_field_count <= 10 {
                                    let cn = record.get_control_field("001").unwrap_or("unknown");
                                    println!("  Long field {tag} ({field_size} bytes): cn = {cn}");
                                }
                            }

                            // Very many subfields in a single field (>20).
                            if field.subfields.len() > 20 {
                                many_subfield_count += 1;
                                if many_subfield_count <= 10 {
                                    let cn = record.get_control_field("001").unwrap_or("unknown");
                                    println!(
                                        "  Many subfields in {tag} ({} subfields): cn = {cn}",
                                        field.subfields.len()
                                    );
                                }
                            }

                            // Very long individual subfield values (>4KB).
                            for sf in &field.subfields {
                                if sf.value.len() > 4_000 {
                                    long_subfield_count += 1;
                                    if long_subfield_count <= 10 {
                                        let cn =
                                            record.get_control_field("001").unwrap_or("unknown");
                                        println!(
                                            "  Long subfield {tag}${} ({} bytes): cn = {cn}",
                                            sf.code,
                                            sf.value.len()
                                        );
                                    }
                                }
                            }
                        }
                    }

                    offset += record_len;
                }
                Ok(None) => break,
                Err(e) => {
                    // Record an error discovery for records that cause mrrc issues.
                    // Extract approximate raw bytes around the current offset.
                    let raw_end = std::cmp::min(offset as usize + 100_000, raw_data.len());
                    let raw_start = offset as usize;
                    if raw_start < raw_data.len() {
                        writer.record_error(file_path, offset, &raw_data[raw_start..raw_end], &e);
                    }
                    break;
                }
            }
        }
    }

    // Finalize discovery output.
    if let Err(e) = writer.finalize() {
        println!("Warning: failed to finalize discovery output: {e}");
    }

    println!("\n=== Extreme Values Summary ===");
    println!("Total records scanned: {total_records}");
    println!("Records >50KB: {large_record_count}");
    println!("Fields >10KB: {long_field_count}");
    println!("Fields with >20 subfields: {many_subfield_count}");
    println!("Subfield values >4KB: {long_subfield_count}");
}

// ---------------------------------------------------------------------------
// 3. Encoding edge cases — local mode
// ---------------------------------------------------------------------------

#[test]
#[ignore]
fn encoding_edge_cases_discovery() {
    mrrc_testbed::require_local_mode();

    let mrc_files = mrrc_testbed::collect_dataset_files(mrrc_testbed::DATASET_NAMES);
    assert!(
        !mrc_files.is_empty(),
        "No .mrc files found for any available dataset"
    );

    let mut writer = DiscoveryWriter::new("discovery.rs", "encoding_edge_cases");

    let mut total_records: u64 = 0;
    let mut marc8_records: u64 = 0;
    let mut utf8_records: u64 = 0;
    let mut mixed_encoding_records: u64 = 0;
    let mut unknown_encoding_records: u64 = 0;
    let mut non_utf8_bytes_in_utf8: u64 = 0;

    for file_path in &mrc_files {
        println!("Scanning encodings: {}", file_path.display());

        let raw_data = match std::fs::read(file_path) {
            Ok(d) => d,
            Err(e) => {
                println!("  Failed to read file: {e}");
                continue;
            }
        };

        let mut reader = MarcReader::new(Cursor::new(raw_data.clone()))
            .with_recovery_mode(RecoveryMode::Lenient);

        let mut offset: u64 = 0;

        loop {
            match reader.read_record() {
                Ok(Some(record)) => {
                    total_records += 1;
                    writer.add_records_processed(1);
                    let record_len = record.leader.record_length as u64;

                    // Classify encoding from leader position 9.
                    let encoding_char = record.leader.character_coding;
                    match MarcEncoding::from_leader_char(encoding_char) {
                        Ok(MarcEncoding::Marc8) => marc8_records += 1,
                        Ok(MarcEncoding::Utf8) => utf8_records += 1,
                        Err(_) => {
                            unknown_encoding_records += 1;
                            if unknown_encoding_records <= 5 {
                                let cn = record.get_control_field("001").unwrap_or("unknown");
                                println!(
                                    "  Unknown encoding indicator '{}': cn = {cn}",
                                    encoding_char
                                );
                            }
                        }
                    }

                    // Use EncodingValidator to detect mixed encodings.
                    match EncodingValidator::analyze_encoding(&record) {
                        Ok(EncodingAnalysis::Mixed {
                            primary,
                            secondary,
                            field_count,
                        }) => {
                            mixed_encoding_records += 1;
                            if mixed_encoding_records <= 10 {
                                let cn = record.get_control_field("001").unwrap_or("unknown");
                                println!(
                                    "  Mixed encoding: primary={primary:?}, secondary={secondary:?}, \
                                     {field_count} inconsistent fields: cn = {cn}"
                                );
                            }
                        }
                        Ok(EncodingAnalysis::Consistent(_)) => {
                            // Check UTF-8 records for non-UTF8 byte artifacts in subfield data.
                            // Since MarcReader uses from_utf8_lossy, replacement characters
                            // indicate original non-UTF8 bytes in a supposedly-UTF8 record.
                            if encoding_char == 'a' {
                                let has_replacement = record.fields.values().any(|fields| {
                                    fields.iter().any(|field| {
                                        field
                                            .subfields
                                            .iter()
                                            .any(|sf| sf.value.contains('\u{FFFD}'))
                                    })
                                });
                                if has_replacement {
                                    non_utf8_bytes_in_utf8 += 1;
                                    if non_utf8_bytes_in_utf8 <= 10 {
                                        let cn =
                                            record.get_control_field("001").unwrap_or("unknown");
                                        println!(
                                            "  UTF-8 record with replacement chars: cn = {cn}"
                                        );
                                    }
                                }
                            }
                        }
                        Ok(EncodingAnalysis::Undetermined) => {
                            // Not actionable; skip.
                        }
                        Err(e) => {
                            // Encoding analysis itself failed; log as discovery.
                            let raw_start = offset as usize;
                            let raw_end =
                                std::cmp::min(raw_start + record_len as usize, raw_data.len());
                            if raw_start < raw_data.len() {
                                writer.record_error(
                                    file_path,
                                    offset,
                                    &raw_data[raw_start..raw_end],
                                    &e,
                                );
                            }
                        }
                    }

                    offset += record_len;
                }
                Ok(None) => break,
                Err(e) => {
                    let raw_start = offset as usize;
                    let raw_end = std::cmp::min(raw_start + 100_000, raw_data.len());
                    if raw_start < raw_data.len() {
                        writer.record_error(file_path, offset, &raw_data[raw_start..raw_end], &e);
                    }
                    break;
                }
            }
        }
    }

    if let Err(e) = writer.finalize() {
        println!("Warning: failed to finalize discovery output: {e}");
    }

    println!("\n=== Encoding Edge Cases Summary ===");
    println!("Total records scanned: {total_records}");
    println!("MARC-8 records: {marc8_records}");
    println!("UTF-8 records: {utf8_records}");
    println!("Unknown encoding indicator: {unknown_encoding_records}");
    println!("Mixed encoding records: {mixed_encoding_records}");
    println!("UTF-8 records with replacement characters: {non_utf8_bytes_in_utf8}");
}

// ---------------------------------------------------------------------------
// 4. Fixture records parse cleanly — CI-safe
// ---------------------------------------------------------------------------

#[test]
fn fixture_records_parse_cleanly() {
    let root = mrrc_testbed::project_root();
    let fixtures_dir = root.join("data").join("fixtures");

    // Collect .mrc files from all subdirectories of data/fixtures/.
    let mut all_mrc_files: Vec<std::path::PathBuf> = Vec::new();

    if fixtures_dir.is_dir() {
        if let Ok(entries) = std::fs::read_dir(&fixtures_dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    let mrc_files = mrrc_testbed::iter_mrc_files(&path);
                    all_mrc_files.extend(mrc_files);
                } else if path.extension().and_then(|e| e.to_str()) == Some("mrc") {
                    all_mrc_files.push(path);
                }
            }
        }
    }

    if all_mrc_files.is_empty() {
        // Gracefully handle empty fixture directories — nothing to check.
        println!(
            "No .mrc fixture files found in {}; skipping parse validation.",
            fixtures_dir.display()
        );
        return;
    }

    all_mrc_files.sort();

    let mut total_records: u64 = 0;
    let mut total_errors: u64 = 0;

    for file_path in &all_mrc_files {
        let file = File::open(file_path).unwrap_or_else(|e| {
            panic!("Failed to open fixture file {}: {e}", file_path.display());
        });
        let mut reader = MarcReader::new(file);

        loop {
            match reader.read_record() {
                Ok(Some(_record)) => {
                    total_records += 1;
                }
                Ok(None) => break,
                Err(e) => {
                    total_errors += 1;
                    eprintln!("Parse error in fixture file {}: {e}", file_path.display());
                    // Continue to the next file — strict mode cannot skip
                    // past a bad record in the same stream.
                    break;
                }
            }
        }
    }

    println!(
        "Fixture validation: {} file(s), {} record(s) parsed, {} error(s).",
        all_mrc_files.len(),
        total_records,
        total_errors
    );

    assert_eq!(
        total_errors, 0,
        "Committed fixture records must parse without errors, but {total_errors} error(s) found."
    );
}

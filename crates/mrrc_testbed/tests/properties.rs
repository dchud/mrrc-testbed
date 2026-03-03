//! Property-based tests for mrrc using proptest.
//!
//! Strategies generate structurally valid MARC records and verify invariants
//! like binary round-trip fidelity. These complement the example-based tests
//! in other test modules.

use std::io::Cursor;

use mrrc::{Field, Leader, MarcReader, MarcWriter, Record};
use proptest::prelude::*;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/// Valid values for leader position 5 (record status).
const RECORD_STATUSES: &[char] = &['a', 'c', 'd', 'n', 'p'];

/// Valid values for leader position 6 (record type).
const RECORD_TYPES: &[char] = &[
    'a', 'c', 'd', 'e', 'f', 'g', 'i', 'j', 'k', 'm', 'o', 'p', 'r', 't',
];

/// Valid values for leader position 7 (bibliographic level).
const BIB_LEVELS: &[char] = &['a', 'b', 'c', 'd', 'i', 'm', 's'];

/// Valid indicator characters (space or digit).
const INDICATOR_CHARS: &[char] = &[' ', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'];

/// Valid subfield codes (lowercase letters and digits).
const SUBFIELD_CODES: &[char] = &[
    'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's',
    't', 'u', 'v', 'w', 'x', 'y', 'z', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
];

// ---------------------------------------------------------------------------
// Strategies
// ---------------------------------------------------------------------------

/// Generate a valid MARC leader.
fn arb_leader() -> impl Strategy<Value = Leader> {
    (
        prop::sample::select(RECORD_STATUSES),
        prop::sample::select(RECORD_TYPES),
        prop::sample::select(BIB_LEVELS),
    )
        .prop_map(|(status, rec_type, bib_level)| Leader {
            record_length: 0,
            record_status: status,
            record_type: rec_type,
            bibliographic_level: bib_level,
            control_record_type: ' ',
            character_coding: 'a', // UTF-8
            indicator_count: 2,
            subfield_code_count: 2,
            data_base_address: 0,
            encoding_level: ' ',
            cataloging_form: ' ',
            multipart_level: ' ',
            reserved: "4500".to_string(),
        })
}

/// Generate a valid control field tag (001-009).
fn arb_control_tag() -> impl Strategy<Value = String> {
    (1..=9u32).prop_map(|n| format!("{n:03}"))
}

/// Generate control field content: printable ASCII, 1-50 bytes.
fn arb_control_value() -> impl Strategy<Value = String> {
    "[[:print:]]{1,50}"
}

/// Generate a valid data field tag (010-999).
fn arb_data_tag() -> impl Strategy<Value = String> {
    (10..=999u32).prop_map(|n| format!("{n:03}"))
}

/// Generate a subfield value: UTF-8 text without MARC delimiters.
/// Excludes \x1D (record terminator), \x1E (field terminator),
/// \x1F (subfield delimiter), and \x00 (null).
fn arb_subfield_value() -> impl Strategy<Value = String> {
    "[\\x20-\\x7E]{1,80}".prop_map(|s| s)
}

/// Generate a single subfield (code + value).
fn arb_subfield() -> impl Strategy<Value = (char, String)> {
    (prop::sample::select(SUBFIELD_CODES), arb_subfield_value())
}

/// Generate a data field with indicators and 1-5 subfields.
fn arb_data_field() -> impl Strategy<Value = (String, char, char, Vec<(char, String)>)> {
    (
        arb_data_tag(),
        prop::sample::select(INDICATOR_CHARS),
        prop::sample::select(INDICATOR_CHARS),
        prop::collection::vec(arb_subfield(), 1..=5),
    )
}

/// Generate a control field (tag + value).
fn arb_control_field() -> impl Strategy<Value = (String, String)> {
    (arb_control_tag(), arb_control_value())
}

/// Generate a complete, structurally valid MARC record.
///
/// The record has:
/// - A valid leader
/// - 0-3 control fields (unique tags)
/// - 1-8 data fields
///
/// All generated records should survive a binary round-trip through
/// MarcWriter -> MarcReader without data loss.
fn arb_record() -> impl Strategy<Value = Record> {
    (
        arb_leader(),
        prop::collection::vec(arb_control_field(), 0..=3),
        prop::collection::vec(arb_data_field(), 1..=8),
    )
        .prop_map(|(leader, control_fields, data_fields)| {
            let mut record = Record::new(leader);

            // Deduplicate control field tags (MARC allows only one per tag).
            let mut seen_tags = std::collections::HashSet::new();
            for (tag, value) in control_fields {
                if seen_tags.insert(tag.clone()) {
                    record.add_control_field(tag, value);
                }
            }

            for (tag, ind1, ind2, subfields) in data_fields {
                let mut field = Field::new(tag, ind1, ind2);
                for (code, value) in subfields {
                    field.add_subfield(code, value);
                }
                record.add_field(field);
            }

            record
        })
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Write a record to an in-memory buffer and read it back.
fn roundtrip(record: &Record) -> Record {
    let mut buf = Vec::new();
    {
        let mut writer = MarcWriter::new(&mut buf);
        writer.write_record(record).unwrap();
    }
    let cursor = Cursor::new(buf);
    let mut reader = MarcReader::new(cursor);
    reader.read_record().unwrap().expect("expected one record")
}

// ---------------------------------------------------------------------------
// Property tests
// ---------------------------------------------------------------------------

proptest! {
    /// Any record we can build should serialize and parse back identically.
    #[test]
    fn binary_roundtrip(record in arb_record()) {
        let parsed = roundtrip(&record);

        // Leader fields that are semantically meaningful should match.
        // record_length and data_base_address are recomputed by MarcWriter,
        // so we compare the fields that carry user data.
        let orig = &record.leader;
        let rt = &parsed.leader;
        prop_assert_eq!(orig.record_status, rt.record_status);
        prop_assert_eq!(orig.record_type, rt.record_type);
        prop_assert_eq!(orig.bibliographic_level, rt.bibliographic_level);
        prop_assert_eq!(orig.character_coding, rt.character_coding);

        // Control fields
        for (tag, value) in &record.control_fields {
            let rt_value = parsed.get_control_field(tag);
            prop_assert!(
                rt_value.is_some(),
                "Control field {} missing after roundtrip", tag
            );
            prop_assert_eq!(value.as_str(), rt_value.unwrap());
        }

        // Data fields: compare tag by tag
        for (tag, fields) in &record.fields {
            let rt_fields = parsed.get_fields(tag);
            prop_assert!(
                rt_fields.is_some(),
                "Data field tag {} missing after roundtrip", tag
            );
            let rt_fields = rt_fields.unwrap();
            prop_assert_eq!(
                fields.len(), rt_fields.len(),
                "Field count mismatch for tag {}", tag
            );

            for (orig_field, rt_field) in fields.iter().zip(rt_fields.iter()) {
                prop_assert_eq!(orig_field.indicator1, rt_field.indicator1);
                prop_assert_eq!(orig_field.indicator2, rt_field.indicator2);

                let orig_subs = &orig_field.subfields;
                let rt_subs = &rt_field.subfields;
                prop_assert_eq!(
                    orig_subs.len(), rt_subs.len(),
                    "Subfield count mismatch for tag {}", tag
                );

                for (os, rs) in orig_subs.iter().zip(rt_subs.iter()) {
                    prop_assert_eq!(&os.code, &rs.code);
                    prop_assert_eq!(&os.value, &rs.value);
                }
            }
        }
    }

    /// Serialization should always produce valid bytes (no panic, no error).
    #[test]
    fn serialization_never_panics(record in arb_record()) {
        let mut buf = Vec::new();
        let mut writer = MarcWriter::new(&mut buf);
        let result = writer.write_record(&record);
        prop_assert!(result.is_ok(), "MarcWriter failed: {:?}", result.err());
        prop_assert!(!buf.is_empty(), "Serialized record is empty");
    }
}

use std::collections::HashSet;
use std::error::Error;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use base64::Engine;
use base64::engine::general_purpose::STANDARD as BASE64;
use chrono::Utc;
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::config::project_root;

/// A single discovery recorded during a test run.
#[derive(Debug, Clone, Serialize)]
pub struct Discovery {
    pub discovery_id: String,
    pub discovered_at: String,
    pub test_suite: String,
    pub test_name: String,
    pub source_dataset: String,
    pub source_file: String,
    pub record: RecordInfo,
    pub error: ErrorInfo,
    pub context: ContextInfo,
}

/// Information about the MARC record that triggered the discovery.
#[derive(Debug, Clone, Serialize)]
pub struct RecordInfo {
    pub offset_bytes: u64,
    pub control_number: String,
    pub raw_bytes_base64: String,
    pub sha256: String,
    pub extracted_to: String,
}

/// Information about the error that was discovered.
#[derive(Debug, Clone, Serialize)]
pub struct ErrorInfo {
    pub category: String,
    pub message: String,
    pub mrrc_error: String,
}

/// Contextual information about the environment.
#[derive(Debug, Clone, Serialize)]
pub struct ContextInfo {
    pub mrrc_version: String,
    pub rust_version: String,
    pub os: String,
}

/// Accumulates discoveries during a test run and writes them to disk.
///
/// Test suites create a `DiscoveryWriter`, call [`record_error`](DiscoveryWriter::record_error)
/// for each problem found, then call [`finalize`](DiscoveryWriter::finalize) to persist results.
pub struct DiscoveryWriter {
    pub test_suite: String,
    pub test_name: String,
    pub discoveries: Vec<Discovery>,
    pub duplicates_skipped: u64,
    pub seen_hashes: HashSet<String>,
    pub records_processed: u64,
    output_root: PathBuf,
}

impl DiscoveryWriter {
    /// Create a new `DiscoveryWriter` for the given test suite and test name.
    ///
    /// Results will be written under `{project_root}/results/discoveries/`.
    pub fn new(test_suite: &str, test_name: &str) -> Self {
        Self {
            test_suite: test_suite.to_string(),
            test_name: test_name.to_string(),
            discoveries: Vec::new(),
            duplicates_skipped: 0,
            seen_hashes: HashSet::new(),
            records_processed: 0,
            output_root: project_root().join("results").join("discoveries"),
        }
    }

    /// Create a `DiscoveryWriter` that writes output to a custom root directory.
    ///
    /// This is useful for testing where you want to write to a temp directory
    /// instead of the project's `results/discoveries/` directory.
    #[cfg(test)]
    pub fn with_output_root(test_suite: &str, test_name: &str, output_root: PathBuf) -> Self {
        Self {
            test_suite: test_suite.to_string(),
            test_name: test_name.to_string(),
            discoveries: Vec::new(),
            duplicates_skipped: 0,
            seen_hashes: HashSet::new(),
            records_processed: 0,
            output_root,
        }
    }

    /// Record the number of records processed so far.
    pub fn add_records_processed(&mut self, count: u64) {
        self.records_processed += count;
    }

    /// Record an error discovered while processing a MARC record.
    ///
    /// Deduplicates by SHA-256 hash of the raw bytes -- if the same record has
    /// already been seen in this run, the call increments `duplicates_skipped`
    /// and returns without creating a new discovery.
    pub fn record_error(
        &mut self,
        dataset_path: &Path,
        offset: u64,
        raw_bytes: &[u8],
        error: &dyn Error,
    ) {
        // 1. Compute sha256
        let mut hasher = Sha256::new();
        hasher.update(raw_bytes);
        let hash_hex = format!("{:x}", hasher.finalize());

        // 2. Deduplicate
        if self.seen_hashes.contains(&hash_hex) {
            self.duplicates_skipped += 1;
            return;
        }
        self.seen_hashes.insert(hash_hex.clone());

        // 3. Generate discovery_id
        let today = Utc::now().format("%Y-%m-%d").to_string();
        let seq = self.discoveries.len() + 1;
        let discovery_id = format!("disc-{today}-{seq:03}");

        // 4. Base64-encode raw bytes
        let raw_bytes_base64 = BASE64.encode(raw_bytes);

        // 5. Extract control number from raw bytes
        let control_number = extract_control_number(raw_bytes);

        // 6. Derive dataset name from path
        let source_dataset = dataset_name_from_path(dataset_path);
        let source_file = dataset_path.to_string_lossy().to_string();

        // 7. Categorize the error
        let category = categorize_error(error);

        let discovery = Discovery {
            discovery_id,
            discovered_at: Utc::now().to_rfc3339(),
            test_suite: self.test_suite.clone(),
            test_name: self.test_name.clone(),
            source_dataset,
            source_file,
            record: RecordInfo {
                offset_bytes: offset,
                control_number,
                raw_bytes_base64,
                sha256: hash_hex,
                extracted_to: String::new(), // filled in during finalize
            },
            error: ErrorInfo {
                category,
                message: error.to_string(),
                mrrc_error: format!("{error:?}"),
            },
            context: ContextInfo {
                mrrc_version: "unknown".to_string(),
                rust_version: env!("CARGO_PKG_RUST_VERSION", "unknown").to_string(),
                os: format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH),
            },
        };

        self.discoveries.push(discovery);
    }

    /// Write all accumulated discoveries to disk and print a summary.
    ///
    /// Creates:
    /// - `results/discoveries/records/{discovery_id}.mrc` for each discovery
    /// - `results/discoveries/{test_suite}_{test_name}_{timestamp}.json` with all discoveries
    pub fn finalize(&mut self) -> Result<(), io::Error> {
        // 1. Ensure output directories exist
        let records_dir = self.output_root.join("records");
        fs::create_dir_all(&records_dir)?;

        // 2. Write individual .mrc files and update extracted_to
        for discovery in &mut self.discoveries {
            let mrc_path = records_dir.join(format!("{}.mrc", discovery.discovery_id));

            // Decode base64 to get the raw bytes back
            let raw_bytes = BASE64
                .decode(&discovery.record.raw_bytes_base64)
                .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;

            fs::write(&mrc_path, &raw_bytes)?;
            discovery.record.extracted_to = mrc_path.to_string_lossy().to_string();
        }

        // 3. Write JSON file with all discoveries
        let timestamp = Utc::now().format("%Y%m%d_%H%M%S").to_string();
        let json_filename = format!("{}_{}_{}.json", self.test_suite, self.test_name, timestamp);
        let json_path = self.output_root.join(json_filename);

        let json = serde_json::to_string_pretty(&self.discoveries).map_err(io::Error::other)?;
        fs::write(&json_path, json)?;

        // 4. Print summary
        let total = self.discoveries.len();
        println!(
            "Discovery run complete ({}::{}):",
            self.test_suite, self.test_name
        );
        println!("  Errors found: {total}");
        println!("  New patterns: {total} (wrote to results/discoveries/)");
        println!("  Duplicates skipped: {}", self.duplicates_skipped);
        println!("  Run: just import -> just discoveries to review");

        Ok(())
    }
}

/// Try to extract the MARC control number (field 001) from raw record bytes.
///
/// MARC records have a 24-byte leader. The directory starts at byte 24 and
/// consists of 12-byte entries (3-byte tag + 4-byte field length + 5-byte
/// starting position) terminated by a field terminator (0x1E). We look for
/// tag "001" and extract the corresponding field data.
fn extract_control_number(raw_bytes: &[u8]) -> String {
    // Need at least the leader (24 bytes) + one directory entry (12 bytes) + terminator
    if raw_bytes.len() < 37 {
        return "unknown".to_string();
    }

    // Parse base address of data from leader bytes 12..17
    let base_address = match std::str::from_utf8(&raw_bytes[12..17]) {
        Ok(s) => match s.trim().parse::<usize>() {
            Ok(addr) => addr,
            Err(_) => return "unknown".to_string(),
        },
        Err(_) => return "unknown".to_string(),
    };

    // Scan directory entries starting at byte 24
    let mut pos = 24;
    while pos + 12 <= raw_bytes.len() {
        // Check for field terminator marking end of directory
        if raw_bytes[pos] == 0x1E {
            break;
        }

        // Need a full 12-byte directory entry
        if pos + 12 > raw_bytes.len() {
            break;
        }

        let tag = match std::str::from_utf8(&raw_bytes[pos..pos + 3]) {
            Ok(t) => t,
            Err(_) => {
                pos += 12;
                continue;
            }
        };

        let field_len = match std::str::from_utf8(&raw_bytes[pos + 3..pos + 7]) {
            Ok(s) => match s.trim().parse::<usize>() {
                Ok(l) => l,
                Err(_) => {
                    pos += 12;
                    continue;
                }
            },
            Err(_) => {
                pos += 12;
                continue;
            }
        };

        let field_start = match std::str::from_utf8(&raw_bytes[pos + 7..pos + 12]) {
            Ok(s) => match s.trim().parse::<usize>() {
                Ok(p) => p,
                Err(_) => {
                    pos += 12;
                    continue;
                }
            },
            Err(_) => {
                pos += 12;
                continue;
            }
        };

        if tag == "001" {
            // Extract field data
            let data_start = base_address + field_start;
            let data_end = data_start + field_len;

            if data_end > raw_bytes.len() {
                return "unknown".to_string();
            }

            let field_data = &raw_bytes[data_start..data_end];

            // Strip field terminator (0x1E) and record terminator (0x1D) from the end
            let trimmed = field_data
                .iter()
                .copied()
                .take_while(|&b| b != 0x1E && b != 0x1D)
                .collect::<Vec<u8>>();

            return String::from_utf8(trimmed).unwrap_or_else(|_| "unknown".to_string());
        }

        pos += 12;
    }

    "unknown".to_string()
}

/// Derive a dataset short name from a file path.
///
/// Uses the parent directory name if available, otherwise the file stem.
fn dataset_name_from_path(path: &Path) -> String {
    path.parent()
        .and_then(|p| p.file_name())
        .and_then(|n| n.to_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| {
            path.file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("unknown")
                .to_string()
        })
}

/// Attempt to categorize an error based on its message.
fn categorize_error(error: &dyn Error) -> String {
    let msg = error.to_string().to_lowercase();
    if msg.contains("malform") || msg.contains("invalid record") || msg.contains("leader") {
        "malformed_record".to_string()
    } else if msg.contains("encod") || msg.contains("utf") || msg.contains("charset") {
        "encoding_error".to_string()
    } else if msg.contains("parse") || msg.contains("unexpected") {
        "parse_error".to_string()
    } else {
        "unknown_error".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    /// Build a minimal valid MARC record with a 001 control field.
    fn make_test_marc_record(control_number: &str) -> Vec<u8> {
        // Field data: control number + field terminator
        let field_data = format!("{}\x1E", control_number);
        let field_len = field_data.len();

        // Directory entry for 001: tag(3) + length(4) + start(5)
        let dir_entry = format!("001{:04}{:05}", field_len, 0);
        // Directory terminator
        let dir_terminator = b"\x1E";

        // Calculate sizes
        let base_address = 24 + dir_entry.len() + dir_terminator.len();
        let record_length = base_address + field_data.len() + 1; // +1 for record terminator

        // Build leader (24 bytes)
        // MARC21 leader: 5-char length, status, type, level, control, encoding,
        // indicator count ('2'), subfield count ('2'), 5-char base address,
        // 3 impl-defined, entry map '4500'
        let leader = format!("{:05}nam  22{:05}   4500", record_length, base_address);

        let mut record = Vec::new();
        record.extend_from_slice(leader.as_bytes());
        record.extend_from_slice(dir_entry.as_bytes());
        record.extend_from_slice(dir_terminator);
        record.extend_from_slice(field_data.as_bytes());
        record.push(0x1D); // record terminator

        record
    }

    #[derive(Debug)]
    struct FakeError(String);

    impl std::fmt::Display for FakeError {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            write!(f, "{}", self.0)
        }
    }

    impl std::error::Error for FakeError {}

    #[test]
    fn test_extract_control_number() {
        let record = make_test_marc_record("ocm12345678");
        let cn = extract_control_number(&record);
        assert_eq!(cn, "ocm12345678");
    }

    #[test]
    fn test_extract_control_number_too_short() {
        let cn = extract_control_number(b"too short");
        assert_eq!(cn, "unknown");
    }

    #[test]
    fn test_extract_control_number_garbage() {
        let cn = extract_control_number(&[0xFF; 100]);
        assert_eq!(cn, "unknown");
    }

    #[test]
    fn test_dataset_name_from_path() {
        let path = PathBuf::from("/data/downloads/watson/watson.mrc");
        assert_eq!(dataset_name_from_path(&path), "watson");

        let path = PathBuf::from("standalone.mrc");
        assert_eq!(dataset_name_from_path(&path), "standalone");
    }

    #[test]
    fn test_categorize_error() {
        let e = FakeError("malformed leader in record".to_string());
        assert_eq!(categorize_error(&e), "malformed_record");

        let e = FakeError("invalid UTF-8 encoding".to_string());
        assert_eq!(categorize_error(&e), "encoding_error");

        let e = FakeError("unexpected end of input while parsing".to_string());
        assert_eq!(categorize_error(&e), "parse_error");

        let e = FakeError("something went wrong".to_string());
        assert_eq!(categorize_error(&e), "unknown_error");
    }

    #[test]
    fn test_discovery_writer_record_and_finalize() {
        let tmp_dir = std::env::temp_dir().join("mrrc_testbed_discovery_test");
        let _ = fs::remove_dir_all(&tmp_dir);
        fs::create_dir_all(&tmp_dir).unwrap();

        let mut writer =
            DiscoveryWriter::with_output_root("malformed.rs", "discover_patterns", tmp_dir.clone());

        // Build a test MARC record
        let marc_bytes = make_test_marc_record("ocm99999");
        let dataset_path = PathBuf::from("/data/downloads/watson/watson.mrc");
        let error = FakeError("malformed leader in record".to_string());

        writer.add_records_processed(100);
        writer.record_error(&dataset_path, 4096, &marc_bytes, &error);

        assert_eq!(writer.discoveries.len(), 1);
        assert_eq!(writer.duplicates_skipped, 0);
        assert_eq!(writer.records_processed, 100);

        // Recording the same bytes again should be a duplicate
        writer.record_error(&dataset_path, 8192, &marc_bytes, &error);
        assert_eq!(writer.discoveries.len(), 1);
        assert_eq!(writer.duplicates_skipped, 1);

        // Recording different bytes should create a new discovery
        let other_bytes = make_test_marc_record("ocm11111");
        writer.record_error(&dataset_path, 12288, &other_bytes, &error);
        assert_eq!(writer.discoveries.len(), 2);
        assert_eq!(writer.duplicates_skipped, 1);

        // Finalize and check output
        writer.finalize().unwrap();

        // Check that records directory was created
        let records_dir = tmp_dir.join("records");
        assert!(records_dir.is_dir());

        // Check that .mrc files were written
        let mrc_files: Vec<_> = fs::read_dir(&records_dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.path().extension().and_then(|ext| ext.to_str()) == Some("mrc"))
            .collect();
        assert_eq!(mrc_files.len(), 2);

        // Check that JSON file was written
        let json_files: Vec<_> = fs::read_dir(&tmp_dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.path().extension().and_then(|ext| ext.to_str()) == Some("json"))
            .collect();
        assert_eq!(json_files.len(), 1);

        // Parse the JSON to verify structure
        let json_content = fs::read_to_string(json_files[0].path()).unwrap();
        let parsed: Vec<serde_json::Value> = serde_json::from_str(&json_content).unwrap();
        assert_eq!(parsed.len(), 2);

        let first = &parsed[0];
        assert!(first["discovery_id"].as_str().unwrap().starts_with("disc-"));
        assert_eq!(first["test_suite"].as_str().unwrap(), "malformed.rs");
        assert_eq!(first["test_name"].as_str().unwrap(), "discover_patterns");
        assert_eq!(first["source_dataset"].as_str().unwrap(), "watson");
        assert_eq!(
            first["record"]["control_number"].as_str().unwrap(),
            "ocm99999"
        );
        assert_eq!(
            first["error"]["category"].as_str().unwrap(),
            "malformed_record"
        );
        assert!(!first["record"]["extracted_to"].as_str().unwrap().is_empty());

        // Clean up
        let _ = fs::remove_dir_all(&tmp_dir);
    }

    #[test]
    fn test_discovery_writer_empty_finalize() {
        let tmp_dir = std::env::temp_dir().join("mrrc_testbed_discovery_empty_test");
        let _ = fs::remove_dir_all(&tmp_dir);
        fs::create_dir_all(&tmp_dir).unwrap();

        let mut writer =
            DiscoveryWriter::with_output_root("stress.rs", "no_errors", tmp_dir.clone());

        writer.finalize().unwrap();

        // JSON file should exist with empty array
        let json_files: Vec<_> = fs::read_dir(&tmp_dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.path().extension().and_then(|ext| ext.to_str()) == Some("json"))
            .collect();
        assert_eq!(json_files.len(), 1);

        let json_content = fs::read_to_string(json_files[0].path()).unwrap();
        let parsed: Vec<serde_json::Value> = serde_json::from_str(&json_content).unwrap();
        assert!(parsed.is_empty());

        let _ = fs::remove_dir_all(&tmp_dir);
    }
}

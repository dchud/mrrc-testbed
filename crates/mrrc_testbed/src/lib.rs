pub mod config;
pub mod datasets;
pub mod discovery;

// Convenience re-exports so tests can `use mrrc_testbed::TestMode` etc.
pub use config::{get_env, get_test_mode, load_config, project_root};
pub use datasets::{DatasetError, TestMode, get_dataset};

use std::fs;
use std::io;
use std::path::{Path, PathBuf};

/// Panic with a descriptive message if the current test mode is not Local.
///
/// Call this at the start of any test that requires downloaded or local datasets.
/// In CI mode the test will fail immediately with a clear explanation rather than
/// producing confusing "dataset not found" errors.
pub fn require_local_mode() {
    let mode = config::get_test_mode();
    if mode != TestMode::Local {
        panic!(
            "This test requires local mode. Set MRRC_TEST_MODE=local to run it.\n\
             Current mode: {:?}",
            mode
        );
    }
}

/// Look up a dataset by short name, panicking on failure with a helpful message.
///
/// This is a convenience wrapper around [`datasets::get_dataset`] for use in tests
/// where a missing dataset should be a hard failure.
pub fn require_dataset(name: &str) -> PathBuf {
    datasets::get_dataset(name).unwrap_or_else(|e| {
        panic!(
            "Required dataset '{name}' not available: {e}\n\
             In local mode, ensure the dataset is downloaded or a local path is set in .env."
        );
    })
}

/// Collect all `.mrc` files from all available datasets.
///
/// Tries each dataset name in `names`, collecting `.mrc` files from each.
/// If a dataset returns a single file, includes that file.
/// If it returns a directory, includes all `.mrc` files in the directory.
/// Silently skips datasets that are not available.
pub fn collect_dataset_files(names: &[&str]) -> Vec<PathBuf> {
    let mut files = Vec::new();
    for name in names {
        if let Ok(path) = datasets::get_dataset(name) {
            let scan_dir = if path.is_file() {
                path.parent().unwrap().to_path_buf()
            } else {
                path.clone()
            };
            let mut mrc_files = iter_mrc_files(&scan_dir);
            if mrc_files.is_empty() && path.is_file() {
                mrc_files.push(path);
            }
            files.extend(mrc_files);
        }
    }
    files
}

/// The standard set of dataset names to scan in local mode.
pub const DATASET_NAMES: &[&str] = &["watson", "ia_lendable", "loc_books"];

/// Collect all `.mrc` files in a directory (non-recursive).
///
/// Returns an empty `Vec` if the directory does not exist or cannot be read.
/// The returned paths are sorted for deterministic ordering.
pub fn iter_mrc_files(dir: &Path) -> Vec<PathBuf> {
    let entries = match fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(_) => return Vec::new(),
    };

    let mut paths: Vec<PathBuf> = entries
        .filter_map(|entry| {
            let path = entry.ok()?.path();
            if path.extension().and_then(|e| e.to_str()) == Some("mrc") {
                Some(path)
            } else {
                None
            }
        })
        .collect();

    paths.sort();
    paths
}

/// Count MARC records in a file by scanning for record terminator bytes (0x1D).
///
/// This performs a simple byte scan without parsing records, so it is fast and
/// works even on files containing malformed records. The count will be wrong if
/// 0x1D appears in non-terminator positions, but that is extremely rare in
/// practice for MARC data.
pub fn count_records_in_file(path: &Path) -> Result<usize, io::Error> {
    let data = fs::read(path)?;
    let count = data.iter().filter(|&&b| b == 0x1D).count();
    Ok(count)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn test_require_local_mode_in_ci() {
        // In CI mode (default), require_local_mode should panic.
        // We can't easily set env vars without affecting other tests,
        // so just verify the current mode check works.
        let mode = get_test_mode();
        if mode == TestMode::Ci {
            let result = std::panic::catch_unwind(require_local_mode);
            assert!(
                result.is_err(),
                "require_local_mode should panic in CI mode"
            );
        }
    }

    #[test]
    fn test_iter_mrc_files_nonexistent_dir() {
        let files = iter_mrc_files(Path::new("/nonexistent/path"));
        assert!(files.is_empty());
    }

    #[test]
    fn test_iter_mrc_files_finds_mrc() {
        let dir = std::env::temp_dir().join("mrrc_testbed_iter_test");
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();

        // Create some files: two .mrc and one .txt
        fs::write(dir.join("a.mrc"), b"").unwrap();
        fs::write(dir.join("b.mrc"), b"").unwrap();
        fs::write(dir.join("c.txt"), b"").unwrap();
        // Create a subdirectory with an .mrc file (should not be found)
        let subdir = dir.join("sub");
        fs::create_dir_all(&subdir).unwrap();
        fs::write(subdir.join("d.mrc"), b"").unwrap();

        let files = iter_mrc_files(&dir);
        assert_eq!(files.len(), 2);
        assert!(files.iter().all(|p| p.extension().unwrap() == "mrc"));
        // Verify sorted order
        assert!(files[0].file_name().unwrap() < files[1].file_name().unwrap());

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_count_records_in_file() {
        let dir = std::env::temp_dir().join("mrrc_testbed_count_test");
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();

        let path = dir.join("test.mrc");

        // Empty file -> 0 records
        fs::write(&path, b"").unwrap();
        assert_eq!(count_records_in_file(&path).unwrap(), 0);

        // File with 3 record terminators
        let mut data = Vec::new();
        data.extend_from_slice(b"record1");
        data.push(0x1D);
        data.extend_from_slice(b"record2");
        data.push(0x1D);
        data.extend_from_slice(b"record3");
        data.push(0x1D);
        fs::write(&path, &data).unwrap();
        assert_eq!(count_records_in_file(&path).unwrap(), 3);

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_count_records_nonexistent_file() {
        let result = count_records_in_file(Path::new("/nonexistent/file.mrc"));
        assert!(result.is_err());
    }
}

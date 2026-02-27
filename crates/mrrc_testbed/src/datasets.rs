use std::env;
use std::fmt;
use std::path::{Path, PathBuf};

use crate::config;

/// Test mode determines which datasets are available.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TestMode {
    /// CI mode: fixtures only, no downloads or custom data.
    Ci,
    /// Local mode: custom paths -> downloads -> fixtures.
    Local,
}

impl TestMode {
    /// Read test mode from MRRC_TEST_MODE env var.
    /// Defaults to Ci if unset or set to "ci".
    pub fn from_env() -> Self {
        match env::var("MRRC_TEST_MODE").ok().as_deref() {
            Some("local") => TestMode::Local,
            _ => TestMode::Ci,
        }
    }
}

/// Error type for dataset lookup failures.
#[derive(Debug)]
pub enum DatasetError {
    /// The requested dataset was not found.
    NotFound(String),
}

impl fmt::Display for DatasetError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            DatasetError::NotFound(name) => write!(f, "dataset not found: {name}"),
        }
    }
}

impl std::error::Error for DatasetError {}

/// Known dataset short names and their corresponding env var overrides.
const DATASET_ENV_VARS: &[(&str, &str)] = &[
    ("watson", "MRRC_WATSON"),
    ("ia_lendable", "MRRC_IA_LENDABLE"),
    ("loc_books", "MRRC_LOC_BOOKS"),
    ("loc_names", "MRRC_LOC_NAMES"),
    ("loc_subjects", "MRRC_LOC_SUBJECTS"),
];

/// Look up a dataset by short name, following the priority cascade.
///
/// In local mode: custom paths (.env) -> downloads -> fixtures.
/// In CI mode: fixtures only.
pub fn get_dataset(name: &str) -> Result<PathBuf, DatasetError> {
    config::load_config();
    let mode = config::get_test_mode();

    match mode {
        TestMode::Local => {
            // 1. Check for a direct env var override (e.g. MRRC_WATSON=/path/to/file.mrc)
            if let Some(path) = get_env_override(name)
                && path.exists()
            {
                return Ok(path);
            }

            // 2. Check custom dataset paths
            if let Some(path) = get_custom_dataset(name) {
                return Ok(path);
            }

            // 3. Check downloads directory
            if let Some(path) = get_download_path(name) {
                return Ok(path);
            }

            // 4. Fall through to fixtures
            if let Some(path) = get_fixture_path(name) {
                return Ok(path);
            }
        }
        TestMode::Ci => {
            // CI mode: fixtures only
            if let Some(path) = get_fixture_path(name) {
                return Ok(path);
            }
        }
    }

    Err(DatasetError::NotFound(name.to_string()))
}

/// Check if there's a direct env var override for a known dataset name.
fn get_env_override(name: &str) -> Option<PathBuf> {
    for (dataset_name, env_var) in DATASET_ENV_VARS {
        if *dataset_name == name {
            return env::var(env_var).ok().map(PathBuf::from);
        }
    }
    None
}

/// Check custom dataset paths from MRRC_CUSTOM_DATASET and MRRC_CUSTOM_DIR.
fn get_custom_dataset(name: &str) -> Option<PathBuf> {
    // Check MRRC_CUSTOM_DATASET - a single file path
    if let Ok(path_str) = env::var("MRRC_CUSTOM_DATASET") {
        let path = PathBuf::from(&path_str);
        if path.exists() && path_matches_name(&path, name) {
            return Some(path);
        }
    }

    // Check MRRC_CUSTOM_DIR - a directory that may contain subdirectories
    if let Ok(dir_str) = env::var("MRRC_CUSTOM_DIR") {
        let dir = PathBuf::from(&dir_str).join(name);
        if let Some(mrc) = find_mrc_file(&dir) {
            return Some(mrc);
        }
    }

    None
}

/// Check the downloads directory for a dataset.
fn get_download_path(name: &str) -> Option<PathBuf> {
    let downloads_dir = match env::var("MRRC_DOWNLOADS_DIR") {
        Ok(dir) => PathBuf::from(dir),
        Err(_) => config::project_root().join("data").join("downloads"),
    };

    let dataset_dir = downloads_dir.join(name);
    find_mrc_file(&dataset_dir)
}

/// Check the fixtures directory for a dataset.
fn get_fixture_path(name: &str) -> Option<PathBuf> {
    let fixtures_dir = config::project_root().join("data").join("fixtures");
    let dataset_dir = fixtures_dir.join(name);
    find_mrc_file(&dataset_dir)
}

/// Find the first .mrc file in a directory.
fn find_mrc_file(dir: &Path) -> Option<PathBuf> {
    if !dir.is_dir() {
        return None;
    }

    let entries = std::fs::read_dir(dir).ok()?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) == Some("mrc") {
            return Some(path);
        }
    }

    None
}

/// Check if a file path matches a dataset name (by file stem or parent directory).
fn path_matches_name(path: &Path, name: &str) -> bool {
    if let Some(stem) = path.file_stem().and_then(|s| s.to_str())
        && stem.contains(name)
    {
        return true;
    }
    if let Some(parent) = path
        .parent()
        .and_then(|p| p.file_name())
        .and_then(|n| n.to_str())
        && parent.contains(name)
    {
        return true;
    }
    false
}

use std::env;
use std::path::PathBuf;
use std::sync::Once;

use crate::datasets::TestMode;

static INIT: Once = Once::new();

/// Load .env file from the project root. No-op if the file is missing.
/// Safe to call multiple times; only loads once.
pub fn load_config() {
    INIT.call_once(|| {
        let root = project_root();
        let env_path = root.join(".env");
        // Ignore errors — .env is optional
        let _ = dotenvy::from_path(&env_path);
    });
}

/// Read an environment variable after ensuring .env is loaded.
pub fn get_env(key: &str) -> Option<String> {
    load_config();
    env::var(key).ok()
}

/// Read the test mode from the MRRC_TEST_MODE environment variable.
pub fn get_test_mode() -> TestMode {
    load_config();
    TestMode::from_env()
}

/// Find the project root by walking up from the manifest directory
/// looking for the workspace Cargo.toml.
pub fn project_root() -> PathBuf {
    // Start from the crate's manifest directory (set by cargo at compile time)
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));

    // Walk up to find the workspace root (the directory containing
    // a Cargo.toml with [workspace])
    let mut dir = manifest_dir.as_path();
    loop {
        let cargo_toml = dir.join("Cargo.toml");
        if cargo_toml.exists()
            && let Ok(contents) = std::fs::read_to_string(&cargo_toml)
            && contents.contains("[workspace]")
        {
            return dir.to_path_buf();
        }
        match dir.parent() {
            Some(parent) => dir = parent,
            None => break,
        }
    }

    // Fallback: two levels up from crates/mrrc_testbed/
    manifest_dir
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.to_path_buf())
        .unwrap_or(manifest_dir)
}

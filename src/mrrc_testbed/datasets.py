import os
from pathlib import Path
from typing import Optional

from mrrc_testbed.config import get_test_mode, is_local_mode, project_root

FIXTURES_DIR: Path = project_root() / "data" / "fixtures"
DOWNLOADS_DIR: Path = project_root() / "data" / "downloads"
CUSTOM_DIR: Path = project_root() / "data" / "custom"

# Mapping from dataset short names to their env var names
_DATASET_ENV_VARS: dict[str, str] = {
    "watson": "MRRC_WATSON",
    "ia_lendable": "MRRC_IA_LENDABLE",
    "loc_books": "MRRC_LOC_BOOKS",
    "loc_names": "MRRC_LOC_NAMES",
    "loc_subjects": "MRRC_LOC_SUBJECTS",
}


def _get_env_override(name: str) -> Optional[Path]:
    # Check for a direct env var override (e.g. MRRC_WATSON=/path/to/file.mrc)
    env_var = _DATASET_ENV_VARS.get(name)
    if env_var:
        env_val = os.environ.get(env_var)
        if env_val:
            p = Path(env_val)
            if p.is_file():
                return p

    return None


def _get_custom_dataset_path(name: str) -> Optional[Path]:
    # Check MRRC_CUSTOM_DATASET for a direct file path.
    # Only return it if the filename contains the dataset name, matching
    # the Rust behavior in datasets.rs::get_custom_dataset.
    custom_file = os.environ.get("MRRC_CUSTOM_DATASET")
    if custom_file:
        p = Path(custom_file)
        if p.is_file() and name in p.stem:
            return p

    # Check MRRC_CUSTOM_DIR for a directory containing .mrc files
    custom_dir = os.environ.get("MRRC_CUSTOM_DIR")
    if custom_dir:
        d = Path(custom_dir) / name
        if d.is_dir():
            mrc_files = sorted(d.glob("*.mrc"))
            if mrc_files:
                return mrc_files[0]

    return None


def _get_download_path(name: str) -> Optional[Path]:
    # Look in the downloads directory
    dataset_dir = DOWNLOADS_DIR / name
    if dataset_dir.is_dir():
        mrc_files = sorted(dataset_dir.glob("*.mrc"))
        if mrc_files:
            return mrc_files[0]

    return None


def _get_fixture_path(name: str) -> Optional[Path]:
    # Look for .mrc files in the named fixture subdirectory
    dataset_dir = FIXTURES_DIR / name
    if dataset_dir.is_dir():
        mrc_files = sorted(dataset_dir.glob("*.mrc"))
        if mrc_files:
            return mrc_files[0]

    return None


def get_dataset(name: str = "default") -> Path:
    if is_local_mode():
        # Priority cascade: env override → custom → downloads → fixtures
        path = _get_env_override(name)
        if path:
            return path

        path = _get_custom_dataset_path(name)
        if path:
            return path

        path = _get_download_path(name)
        if path:
            return path

    # CI mode, or local mode fallback to fixtures
    path = _get_fixture_path(name)
    if path:
        return path

    mode = get_test_mode()
    if mode == "local":
        hint = "Configure paths in .env or download datasets."
    else:
        hint = "Add fixture files to data/fixtures/."
    raise FileNotFoundError(
        f"No dataset found for '{name}' in {mode} mode. {hint}"
    )

"""Shared fixtures for pymarc API compatibility tests."""

from pathlib import Path

import mrrc
import pytest

from mrrc_testbed.datasets import FIXTURES_DIR


@pytest.fixture(scope="session")
def fixture_mrc_files() -> list[Path]:
    """Return all .mrc files found under data/fixtures/.

    Returns an empty list if no .mrc files exist (fixture dirs may only
    contain .gitkeep during early setup).
    """
    return sorted(FIXTURES_DIR.rglob("*.mrc"))


@pytest.fixture(scope="session")
def sample_records(fixture_mrc_files: list[Path]) -> list[mrrc.Record]:
    """Read a small number of records from fixture .mrc files.

    Returns up to 20 records across all fixture files.  Returns an empty
    list when no fixture .mrc files are present.
    """
    records: list[mrrc.Record] = []
    limit = 20
    for mrc_path in fixture_mrc_files:
        if len(records) >= limit:
            break
        reader = mrrc.MARCReader(str(mrc_path))
        for record in reader:
            records.append(record)
            if len(records) >= limit:
                break
    return records

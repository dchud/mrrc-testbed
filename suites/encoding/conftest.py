"""Shared fixtures for encoding tests."""

import mrrc
import pytest

from mrrc_testbed.datasets import FIXTURES_DIR


@pytest.fixture(scope="session")
def fixture_records() -> list[mrrc.Record]:
    """Yield records from all fixture .mrc files for encoding tests.

    Returns an empty list when no .mrc fixture files are present (fixture
    directories may only contain .gitkeep during early setup).
    """
    records: list[mrrc.Record] = []
    for mrc_path in sorted(FIXTURES_DIR.rglob("*.mrc")):
        reader = mrrc.MARCReader(str(mrc_path))
        for record in reader:
            records.append(record)
    return records

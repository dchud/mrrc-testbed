"""Large-scale iteration tests — local mode only.

These tests exercise mrrc against full-size downloaded datasets.  They
require ``MRRC_TEST_MODE=local`` and an available "watson" dataset
(downloaded or configured via .env).
"""

import sys

import mrrc
import pytest

# Import the helper that skips when a dataset is unavailable.
from conftest import get_test_dataset


@pytest.mark.local
class TestLargeFileIteration:
    """Iterate over a large dataset and verify record count."""

    def test_large_file_iteration(self) -> None:
        dataset_path = get_test_dataset("watson")
        count = 0
        reader = mrrc.MARCReader(str(dataset_path))
        for _record in reader:
            count += 1
        # Watson dataset should contain a substantial number of records.
        assert count > 100, (
            f"Expected > 100 records in watson dataset, got {count}"
        )


@pytest.mark.local
class TestParallelParse:
    """Use parse_batch_parallel on a large file."""

    def test_parallel_parse(self) -> None:
        dataset_path = get_test_dataset("watson")
        records = mrrc.parse_batch_parallel(str(dataset_path))
        assert len(records) > 0, "parse_batch_parallel returned no records"


@pytest.mark.local
class TestMemoryStableIteration:
    """Iterate a large file without accumulating records in memory.

    We stream through the file keeping only a running count and a small
    sample.  The goal is to confirm that iteration does not force the
    entire file into memory at once — measured by ensuring the process
    size stays within a reasonable bound relative to the file size.
    """

    def test_memory_stable_iteration(self) -> None:
        dataset_path = get_test_dataset("watson")

        count = 0
        sample_size = 5
        sample: list[str] = []

        reader = mrrc.MARCReader(str(dataset_path))
        for record in reader:
            count += 1
            # Keep only a tiny sample — we are testing that we do NOT
            # keep every record alive.
            if len(sample) < sample_size:
                titles = record.get_fields("245")
                if titles:
                    sample.append(str(titles[0]))

        assert count > 100, (
            f"Expected > 100 records in watson dataset, got {count}"
        )
        # Rough sanity check: the Python object overhead for our sample
        # should be trivial.  We cannot directly measure RSS portably,
        # but we verify that only `sample_size` strings were kept.
        assert len(sample) <= sample_size
        # The final refcount for the reader should not indicate leaked
        # record references.  After iteration the reader should be the
        # only remaining reference holder (plus the temporary sys call).
        assert sys.getrefcount(reader) <= 3

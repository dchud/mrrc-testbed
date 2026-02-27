"""Edge case discovery tests using mrrc Python bindings.

CI-safe tests run against committed fixture files. Local-mode tests run
against large downloaded datasets and are marked with @pytest.mark.local.

Discoveries are written as JSON to results/discoveries/ for later import
by scripts/import_run.py.
"""

import json
from pathlib import Path

import mrrc
import pytest
from conftest import get_test_dataset

from discovery.helpers import DiscoveryWriter

# ---------------------------------------------------------------------------
# CI-safe tests
# ---------------------------------------------------------------------------


def test_fixture_records_parse_cleanly(
    results_dir: Path, fixtures_dir: Path
) -> None:
    """Read all fixture .mrc files through mrrc and verify no exceptions.

    Any records that raise exceptions are recorded as discoveries. The test
    itself passes as long as the discovery machinery works -- the point is
    to *find* problems, not to assert zero errors.
    """
    mrc_files = sorted(fixtures_dir.rglob("*.mrc"))
    if not mrc_files:
        pytest.skip("no fixture .mrc files found")

    writer = DiscoveryWriter(
        test_suite="discovery.test_edge_cases",
        results_dir=results_dir,
    )

    for mrc_path in mrc_files:
        raw_data = mrc_path.read_bytes()

        # Walk raw bytes to identify record boundaries.
        offset = 0
        while offset < len(raw_data):
            if offset + 5 > len(raw_data):
                break
            try:
                rec_len = int(raw_data[offset : offset + 5].decode("ascii"))
            except (ValueError, UnicodeDecodeError):
                writer.record_error(
                    test_name="test_fixture_records_parse_cleanly",
                    source_path=mrc_path,
                    record_offset=offset,
                    raw_bytes=raw_data[offset : offset + 100],
                    error_message="Cannot parse record length from leader",
                    category="malformed_record",
                )
                break

            if rec_len <= 0 or offset + rec_len > len(raw_data):
                break

            offset += rec_len

        # Parse through mrrc to find runtime exceptions.
        try:
            reader = mrrc.MARCReader(str(mrc_path))
            for _record in reader:
                pass
        except Exception as exc:
            writer.record_error(
                test_name="test_fixture_records_parse_cleanly",
                source_path=mrc_path,
                record_offset=0,
                raw_bytes=raw_data[:200],
                error_message=str(exc),
            )

    output = writer.finalize()
    assert output.exists()
    assert output.suffix == ".json"


def test_discovery_writer_works(tmp_path: Path) -> None:
    """Unit test: create a DiscoveryWriter, record a fake error, finalize.

    Verifies the JSON output file exists and contains valid structure.
    """
    writer = DiscoveryWriter(
        test_suite="test_suite",
        results_dir=tmp_path,
    )

    # Record a fake discovery.
    fake_raw = b"00046nam  2200037   4500001000800000\x1etest123\x1e\x1d"
    writer.record_error(
        test_name="test_fake",
        source_path=Path("/data/fixtures/edge_cases/fake.mrc"),
        record_offset=0,
        raw_bytes=fake_raw,
        error_message="simulated parse error for testing",
        category="parse_error",
    )

    # Recording the same bytes again should be deduplicated.
    writer.record_error(
        test_name="test_fake",
        source_path=Path("/data/fixtures/edge_cases/fake.mrc"),
        record_offset=100,
        raw_bytes=fake_raw,
        error_message="same record again",
        category="parse_error",
    )

    assert len(writer.discoveries) == 1
    assert writer.duplicates_skipped == 1

    # Record a different discovery.
    other_raw = b"00050nam  2200037   4500001001200000\x1eother456\x1e\x1d"
    writer.record_error(
        test_name="test_fake",
        source_path=Path("/data/fixtures/edge_cases/fake.mrc"),
        record_offset=200,
        raw_bytes=other_raw,
        error_message="malformed leader in record",
        category="malformed_record",
    )

    assert len(writer.discoveries) == 2
    assert writer.duplicates_skipped == 1

    output = writer.finalize()
    assert output.exists()

    with open(output) as f:
        data = json.load(f)

    assert isinstance(data, list)
    assert len(data) == 2

    first = data[0]
    assert first["discovery_id"].startswith("disc-")
    assert first["test_suite"] == "test_suite"
    assert first["test_name"] == "test_fake"
    assert first["source_dataset"] == "edge_cases"
    assert first["record"]["sha256"]
    assert first["record"]["offset_bytes"] == 0
    assert first["error"]["category"] == "parse_error"
    assert first["error"]["message"] == "simulated parse error for testing"

    second = data[1]
    assert second["error"]["category"] == "malformed_record"
    assert second["record"]["offset_bytes"] == 200


# ---------------------------------------------------------------------------
# Local-mode tests
# ---------------------------------------------------------------------------


@pytest.mark.local
def test_discover_parsing_errors(
    results_dir: Path, skip_unless_local: None
) -> None:
    """Iterate over a large dataset and record any records that raise exceptions.

    This test scans a dataset record by record. Any record that causes mrrc
    to raise an exception is recorded via DiscoveryWriter for later analysis.
    """
    import os
    import tempfile

    dataset_path = get_test_dataset("watson")

    writer = DiscoveryWriter(
        test_suite="discovery.test_edge_cases",
        results_dir=results_dir,
    )

    raw_data = dataset_path.read_bytes()
    offset = 0
    records_parsed = 0
    errors = 0

    while offset < len(raw_data):
        if offset + 5 > len(raw_data):
            break

        try:
            rec_len = int(raw_data[offset : offset + 5].decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            writer.record_error(
                test_name="test_discover_parsing_errors",
                source_path=dataset_path,
                record_offset=offset,
                raw_bytes=raw_data[
                    offset : offset + min(100, len(raw_data) - offset)
                ],
                error_message="Cannot parse record length from leader",
                category="malformed_record",
            )
            break

        if rec_len <= 0:
            break
        if offset + rec_len > len(raw_data):
            writer.record_error(
                test_name="test_discover_parsing_errors",
                source_path=dataset_path,
                record_offset=offset,
                raw_bytes=raw_data[
                    offset : offset + min(rec_len, len(raw_data) - offset)
                ],
                error_message=f"Record length {rec_len} exceeds remaining data",
                category="malformed_record",
            )
            break

        record_bytes = raw_data[offset : offset + rec_len]

        # Parse the single record via a temp file to isolate per-record errors.
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mrc")
        try:
            os.write(tmp_fd, record_bytes)
            os.close(tmp_fd)
            reader = mrrc.MARCReader(tmp_path)
            for _record in reader:
                pass
            records_parsed += 1
        except Exception as exc:
            errors += 1
            writer.record_error(
                test_name="test_discover_parsing_errors",
                source_path=dataset_path,
                record_offset=offset,
                raw_bytes=record_bytes,
                error_message=str(exc),
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        offset += rec_len

    output = writer.finalize()
    print(f"Parsed {records_parsed} records, found {errors} errors")
    assert output.exists()


@pytest.mark.local
def test_discover_unusual_leaders(
    results_dir: Path, skip_unless_local: None
) -> None:
    """Scan records for unusual leader values and log statistics.

    Checks record status (leader[5]), type of record (leader[6]), and
    bibliographic level (leader[7]) against the standard MARC 21 values.
    Records with values outside the standard set are recorded as discoveries.
    """
    dataset_path = get_test_dataset("watson")

    writer = DiscoveryWriter(
        test_suite="discovery.test_edge_cases",
        results_dir=results_dir,
    )

    # Standard MARC 21 leader values per LC specification.
    valid_record_status = {"a", "c", "d", "n", "p"}
    valid_record_type = {
        "a", "c", "d", "e", "f", "g", "i", "j", "k", "m",
        "o", "p", "r", "t",
    }
    valid_bib_level = {"a", "b", "c", "d", "i", "m", "s"}

    stats: dict[str, dict[str, int]] = {
        "record_status": {},
        "record_type": {},
        "bibliographic_level": {},
    }

    raw_data = dataset_path.read_bytes()
    offset = 0
    total_records = 0

    while offset < len(raw_data):
        if offset + 24 > len(raw_data):
            break

        try:
            rec_len = int(raw_data[offset : offset + 5].decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            break

        if rec_len <= 0 or offset + rec_len > len(raw_data):
            break

        record_bytes = raw_data[offset : offset + rec_len]
        total_records += 1

        # Leader positions: 5 = record status, 6 = type, 7 = bib level.
        try:
            status = chr(record_bytes[5])
            rec_type = chr(record_bytes[6])
            bib_level = chr(record_bytes[7])
        except (IndexError, ValueError):
            offset += rec_len
            continue

        stats["record_status"][status] = (
            stats["record_status"].get(status, 0) + 1
        )
        stats["record_type"][rec_type] = (
            stats["record_type"].get(rec_type, 0) + 1
        )
        stats["bibliographic_level"][bib_level] = (
            stats["bibliographic_level"].get(bib_level, 0) + 1
        )

        unusual = []
        if status not in valid_record_status:
            unusual.append(f"record_status='{status}'")
        if rec_type not in valid_record_type:
            unusual.append(f"record_type='{rec_type}'")
        if bib_level not in valid_bib_level:
            unusual.append(f"bibliographic_level='{bib_level}'")

        if unusual:
            writer.record_error(
                test_name="test_discover_unusual_leaders",
                source_path=dataset_path,
                record_offset=offset,
                raw_bytes=record_bytes,
                error_message=f"Unusual leader values: {', '.join(unusual)}",
                category="unusual_leader",
            )

        offset += rec_len

    output = writer.finalize()

    print(f"\nLeader statistics over {total_records} records:")
    for field_name, counts in stats.items():
        print(f"  {field_name}:")
        for value, count in sorted(counts.items(), key=lambda x: -x[1]):
            pct = 100.0 * count / total_records if total_records else 0
            print(f"    '{value}': {count} ({pct:.1f}%)")

    assert output.exists()


@pytest.mark.local
def test_discover_oversized_records(
    results_dir: Path, skip_unless_local: None
) -> None:
    """Find records larger than 99999 bytes or with fields larger than 9999 bytes.

    MARC 21 limits record length to 99999 bytes (5-digit leader field) and
    individual field length to 9999 bytes (4-digit directory entry). Records
    or fields exceeding these limits are recorded as discoveries.
    """
    dataset_path = get_test_dataset("watson")

    writer = DiscoveryWriter(
        test_suite="discovery.test_edge_cases",
        results_dir=results_dir,
    )

    MARC_RECORD_LIMIT = 99999
    MARC_FIELD_LIMIT = 9999

    raw_data = dataset_path.read_bytes()
    offset = 0
    total_records = 0
    oversized_records = 0
    oversized_fields = 0

    while offset < len(raw_data):
        if offset + 5 > len(raw_data):
            break

        try:
            rec_len = int(raw_data[offset : offset + 5].decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            break

        if rec_len <= 0 or offset + rec_len > len(raw_data):
            break

        record_bytes = raw_data[offset : offset + rec_len]
        total_records += 1

        # Check record size.
        if rec_len > MARC_RECORD_LIMIT:
            oversized_records += 1
            writer.record_error(
                test_name="test_discover_oversized_records",
                source_path=dataset_path,
                record_offset=offset,
                raw_bytes=record_bytes[:200],
                error_message=(
                    f"Record size {rec_len} exceeds "
                    f"MARC limit of {MARC_RECORD_LIMIT}"
                ),
                category="oversized_record",
            )
            offset += rec_len
            continue

        # Check individual field sizes via the directory.
        if len(record_bytes) >= 25:
            try:
                _base_address = int(
                    record_bytes[12:17].decode("ascii").strip()
                )
            except (ValueError, UnicodeDecodeError):
                offset += rec_len
                continue

            dir_pos = 24
            oversized_field_len = 0
            has_oversized_field = False
            while dir_pos + 12 <= len(record_bytes):
                if record_bytes[dir_pos] == 0x1E:
                    break

                try:
                    field_len = int(
                        record_bytes[dir_pos + 3 : dir_pos + 7]
                        .decode("ascii")
                        .strip()
                    )
                except (ValueError, UnicodeDecodeError):
                    dir_pos += 12
                    continue

                if field_len > MARC_FIELD_LIMIT:
                    has_oversized_field = True
                    oversized_field_len = field_len
                    break

                dir_pos += 12

            if has_oversized_field:
                oversized_fields += 1
                writer.record_error(
                    test_name="test_discover_oversized_records",
                    source_path=dataset_path,
                    record_offset=offset,
                    raw_bytes=record_bytes[:200],
                    error_message=(
                        f"Field length {oversized_field_len} exceeds "
                        f"MARC limit of {MARC_FIELD_LIMIT} "
                        f"in record of size {rec_len}"
                    ),
                    category="oversized_field",
                )

        offset += rec_len

    output = writer.finalize()

    print(f"\nOversized record scan over {total_records} records:")
    print(f"  Records > {MARC_RECORD_LIMIT} bytes: {oversized_records}")
    print(f"  Records with fields > {MARC_FIELD_LIMIT} bytes: {oversized_fields}")

    assert output.exists()

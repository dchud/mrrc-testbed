"""Tests that replicate common pymarc usage patterns against real MARC data.

All tests in this module run in CI mode using committed fixture data.
When no fixture .mrc files exist yet, tests skip gracefully.
"""

from pathlib import Path

import mrrc
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _skip_if_no_records(records: list) -> None:
    """Skip the current test when no records are available."""
    if not records:
        pytest.skip("No fixture records available")


def _skip_if_no_files(files: list[Path]) -> None:
    """Skip the current test when no .mrc fixture files exist."""
    if not files:
        pytest.skip("No fixture .mrc files found")


# ---------------------------------------------------------------------------
# CI-mode tests
# ---------------------------------------------------------------------------


class TestIterateAllRecords:
    """Read every fixture .mrc file and iterate all records without error."""

    def test_iterate_all_records(self, fixture_mrc_files: list[Path]) -> None:
        _skip_if_no_files(fixture_mrc_files)
        total = 0
        for mrc_path in fixture_mrc_files:
            reader = mrrc.MARCReader(str(mrc_path))
            for _record in reader:
                total += 1
        assert total > 0, "Expected at least one record across fixture files"


class TestAccessCommonFields:
    """Access commonly-used MARC fields without crashing."""

    def test_access_common_fields(self, sample_records: list[mrrc.Record]) -> None:
        _skip_if_no_records(sample_records)
        for record in sample_records:
            # Title — 245
            record.get_fields("245")
            # Author — 100 (personal) or 110 (corporate)
            record.get_fields("100")
            record.get_fields("110")
            # Subject headings — 6xx range
            for tag in ("600", "610", "650", "651"):
                record.get_fields(tag)
            # ISBN — 020
            record.get_fields("020")


class TestFieldToString:
    """Convert fields to strings and verify non-empty output."""

    def test_field_to_string(self, sample_records: list[mrrc.Record]) -> None:
        _skip_if_no_records(sample_records)
        for record in sample_records:
            for field in record.fields():
                # Build a text representation from subfields.
                # str(field) gives an object repr, not formatted content.
                subs = field.subfields()
                if subs:
                    text = " ".join(sf.value for sf in subs)
                else:
                    # Control field -- try record.control_field(tag)
                    text = record.control_field(field.tag) or ""
                assert isinstance(text, str)
                # Every field should produce *something*.
                assert len(text) > 0, f"Empty string for field {field.tag}"


class TestRecordToDictPattern:
    """Common pymarc pattern: convert record to a dict-like structure."""

    def test_record_to_dict_pattern(
        self, sample_records: list[mrrc.Record]
    ) -> None:
        _skip_if_no_records(sample_records)
        for record in sample_records:
            # Leader access
            leader = record.leader()
            assert leader is not None

            # Iterate all fields and gather tag -> subfield data
            extracted: dict[str, list[str]] = {}
            for field in record.fields():
                tag = field.tag
                if tag not in extracted:
                    extracted[tag] = []
                subs = field.subfields()
                if subs:
                    for sf in subs:
                        extracted[tag].append(sf.value)
                else:
                    # Control field -- get value via record API
                    value = record.control_field(tag)
                    if value is not None:
                        extracted[tag].append(value)

            # We should have extracted at least some fields
            assert len(extracted) > 0


class TestSearchByTag:
    """Search records for specific tags and verify Field objects."""

    def test_search_by_tag(self, sample_records: list[mrrc.Record]) -> None:
        _skip_if_no_records(sample_records)
        search_tags = ("245", "100", "650")
        found_any = False
        for record in sample_records:
            for tag in search_tags:
                fields = record.get_fields(tag)
                for field in fields:
                    found_any = True
                    assert field.tag == tag
        # At least one searched tag should appear across all sample records
        assert found_any, (
            "Expected at least one of tags 245/100/650 in sample records"
        )


class TestWriteRoundtrip:
    """Read a record, write via MARCWriter, re-read, verify key fields."""

    def test_write_roundtrip(
        self,
        sample_records: list[mrrc.Record],
        tmp_path: Path,
    ) -> None:
        _skip_if_no_records(sample_records)
        record = sample_records[0]

        out_path = tmp_path / "roundtrip.mrc"
        writer = mrrc.MARCWriter(str(out_path))
        writer.write(record)
        writer.close()

        reader = mrrc.MARCReader(str(out_path))
        records_back = list(reader)
        assert len(records_back) == 1

        original_titles = record.get_fields("245")
        roundtrip_titles = records_back[0].get_fields("245")
        assert len(original_titles) == len(roundtrip_titles)
        if original_titles:
            orig_text = " ".join(
                sf.value for sf in original_titles[0].subfields()
            )
            rt_text = " ".join(
                sf.value for sf in roundtrip_titles[0].subfields()
            )
            assert orig_text == rt_text


class TestJsonRoundtrip:
    """Convert record to JSON and back, verify key fields preserved."""

    def test_json_roundtrip(self, sample_records: list[mrrc.Record]) -> None:
        _skip_if_no_records(sample_records)
        record = sample_records[0]

        json_str = record.to_json()
        assert isinstance(json_str, str)
        assert len(json_str) > 0

        restored = mrrc.json_to_record(json_str)
        assert restored is not None

        # Leader should survive the round trip
        orig_leader = record.leader()
        rest_leader = restored.leader()
        assert orig_leader is not None
        assert rest_leader is not None
        assert orig_leader.record_type == rest_leader.record_type

        # Title (245) should survive
        orig_245 = record.get_fields("245")
        rest_245 = restored.get_fields("245")
        assert len(orig_245) == len(rest_245)
        if orig_245:
            orig_text = " ".join(
                sf.value for sf in orig_245[0].subfields()
            )
            rest_text = " ".join(
                sf.value for sf in rest_245[0].subfields()
            )
            assert orig_text == rest_text


class TestBatchReadFixtures:
    """Read all fixture files with MARCReader and verify records exist."""

    def test_batch_read_fixtures(self, fixture_mrc_files: list[Path]) -> None:
        _skip_if_no_files(fixture_mrc_files)
        total = 0
        for mrc_path in fixture_mrc_files:
            reader = mrrc.MARCReader(str(mrc_path))
            for _record in reader:
                total += 1
        assert total > 0, "Expected > 0 records across all fixture files"

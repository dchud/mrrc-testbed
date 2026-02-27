"""Encoding tests for mrrc Python bindings.

CI-safe tests verify that mrrc exposes all MARC data as proper Python
strings (not raw bytes) and that no replacement characters or encoding
artifacts sneak through the bindings layer.  Local-mode tests extend
coverage to large real-world datasets.
"""

import re

import mrrc
import pytest
from conftest import get_test_dataset

# ---------------------------------------------------------------------------
# Common mojibake patterns indicating double-encoded UTF-8
# ---------------------------------------------------------------------------
# These byte sequences appear when UTF-8 text is mistakenly decoded as
# Latin-1 and then re-encoded as UTF-8.
_MOJIBAKE_PATTERNS = re.compile(
    r"[\xc3][\x80-\xbf]"  # Ã followed by a Latin-1 continuation byte
)


# ===================================================================
# CI-safe tests — use fixture data only
# ===================================================================


class TestStringTypes:
    """Verify that mrrc exposes all field data as Python str, not bytes."""

    def test_ascii_fields_are_strings(
        self, fixture_records: list[mrrc.Record]
    ) -> None:
        """All field data accessed via Python must be str type."""
        if not fixture_records:
            pytest.skip("no fixture .mrc files available")

        for record in fixture_records:
            # Check control fields via record.control_fields()
            for _tag, value in record.control_fields():
                assert isinstance(value, str), (
                    f"Control field value is {type(value)}, expected str"
                )
            # Check data field subfields
            for field in record.fields():
                subs = field.subfields()
                for subfield in subs:
                    assert isinstance(subfield.value, str), (
                        f"Subfield value in {field.tag} is "
                        f"{type(subfield.value)}, expected str"
                    )

    def test_control_fields_are_strings(
        self, fixture_records: list[mrrc.Record]
    ) -> None:
        """Control fields (001, 003, 005, 008) are accessible as strings."""
        if not fixture_records:
            pytest.skip("no fixture .mrc files available")

        control_tags = {"001", "003", "005", "008"}
        found_any = False
        for record in fixture_records:
            for tag in control_tags:
                value = record.control_field(tag)
                if value is not None:
                    found_any = True
                    assert isinstance(value, str), (
                        f"Control field {tag} data is {type(value)}, "
                        f"expected str"
                    )

        if not found_any:
            pytest.skip("no control fields found in fixture records")

    def test_leader_is_accessible(
        self, fixture_records: list[mrrc.Record]
    ) -> None:
        """record.leader() is accessible and returns a Leader object."""
        if not fixture_records:
            pytest.skip("no fixture .mrc files available")

        for record in fixture_records:
            leader = record.leader()
            assert leader is not None, "record.leader() returned None"
            # Leader is a mrrc.Leader object with properties like
            # record_type, bibliographic_level, etc.
            # str(leader) gives an object repr, not a 24-char string.
            assert hasattr(leader, "record_type")

    def test_subfield_data_is_string(
        self, fixture_records: list[mrrc.Record]
    ) -> None:
        """For data fields, subfield values are strings."""
        if not fixture_records:
            pytest.skip("no fixture .mrc files available")

        found_any = False
        for record in fixture_records:
            for field in record.fields():
                subs = field.subfields()
                if not subs:
                    continue
                for subfield in subs:
                    found_any = True
                    assert isinstance(subfield.value, str), (
                        f"Subfield value in field {field.tag} is "
                        f"{type(subfield.value)}, expected str"
                    )

        if not found_any:
            pytest.skip("no subfields found in fixture records")


class TestEncodingQuality:
    """Check that fixture data is free of encoding artifacts."""

    def test_no_replacement_characters_in_fixtures(
        self, fixture_records: list[mrrc.Record]
    ) -> None:
        """No field data should contain U+FFFD replacement character."""
        if not fixture_records:
            pytest.skip("no fixture .mrc files available")

        violations: list[str] = []
        for record in fixture_records:
            # Check control fields
            for tag, value in record.control_fields():
                if value and "\ufffd" in value:
                    violations.append(
                        f"Field {tag}: replacement char in data"
                    )
            # Check data field subfields
            for field in record.fields():
                for subfield in field.subfields():
                    if "\ufffd" in subfield.value:
                        violations.append(
                            f"Field {field.tag}: replacement char in subfield"
                        )

        assert not violations, (
            f"Found {len(violations)} replacement character(s):\n"
            + "\n".join(violations[:20])
        )


class TestRoundTrip:
    """Verify that writing and re-reading preserves encoding."""

    def test_write_preserves_encoding(
        self, fixture_records: list[mrrc.Record], tmp_path
    ) -> None:
        """Write records to a temp file, re-read, verify text matches."""
        if not fixture_records:
            pytest.skip("no fixture .mrc files available")

        out_path = tmp_path / "roundtrip.mrc"
        mrrc.write(fixture_records, str(out_path))

        reread_records = list(mrrc.MARCReader(str(out_path)))
        assert len(reread_records) == len(fixture_records), (
            f"Wrote {len(fixture_records)} records but re-read "
            f"{len(reread_records)}"
        )

        for orig, reread in zip(fixture_records, reread_records):
            orig_leader = orig.leader()
            reread_leader = reread.leader()
            assert orig_leader is not None
            assert reread_leader is not None
            # Compare leader record_type as a proxy for leader equality
            assert orig_leader.record_type == reread_leader.record_type, (
                f"Leader record_type mismatch: "
                f"{orig_leader.record_type!r} != {reread_leader.record_type!r}"
            )

            orig_fields = orig.fields()
            reread_fields = reread.fields()
            assert len(orig_fields) == len(reread_fields), (
                f"Field count mismatch: {len(orig_fields)} vs "
                f"{len(reread_fields)}"
            )

            for of, rf in zip(orig_fields, reread_fields):
                assert of.tag == rf.tag, (
                    f"Tag mismatch: {of.tag} != {rf.tag}"
                )
                # Compare subfield values for data fields
                orig_subs = of.subfields()
                reread_subs = rf.subfields()
                for os_f, rs_f in zip(orig_subs, reread_subs):
                    assert os_f.value == rs_f.value, (
                        f"Data mismatch in field {of.tag}: "
                        f"{os_f.value!r} != {rs_f.value!r}"
                    )


# ===================================================================
# Local-mode tests — require downloaded datasets
# ===================================================================


@pytest.mark.local
class TestLargeDatasetEncoding:
    """Encoding tests that run against large downloaded datasets."""

    def test_unicode_roundtrip_large_dataset(self, tmp_path) -> None:
        """Read a large dataset, write records with non-ASCII 245 content
        to a temp file, re-read, and verify content matches.
        """
        dataset_path = get_test_dataset("watson")
        reader = mrrc.MARCReader(str(dataset_path))

        non_ascii_records: list[mrrc.Record] = []
        limit = 500  # cap to keep test runtime reasonable

        for record in reader:
            if len(non_ascii_records) >= limit:
                break
            title_fields = record.get_fields("245")
            for field in title_fields:
                subs = field.subfields()
                if not subs:
                    continue
                for subfield in subs:
                    if not subfield.value.isascii():
                        non_ascii_records.append(record)
                        break
                else:
                    continue
                break

        if not non_ascii_records:
            pytest.skip("no non-ASCII 245 records found in dataset")

        out_path = tmp_path / "unicode_roundtrip.mrc"
        mrrc.write(non_ascii_records, str(out_path))

        reread = list(mrrc.MARCReader(str(out_path)))
        assert len(reread) == len(non_ascii_records)

        for orig, rt in zip(non_ascii_records, reread):
            orig_titles = orig.get_fields("245")
            rt_titles = rt.get_fields("245")
            assert len(orig_titles) == len(rt_titles)
            for ot, rtt in zip(orig_titles, rt_titles):
                orig_subs = ot.subfields()
                rt_subs = rtt.subfields()
                for os_f, rs_f in zip(orig_subs, rt_subs):
                    assert os_f.value == rs_f.value, (
                        f"Unicode roundtrip mismatch in 245: "
                        f"{os_f.value!r} != {rs_f.value!r}"
                    )

    def test_encoding_variety_detection(self) -> None:
        """Scan a large dataset, categorize records by leader position 9
        encoding indicator, and report the distribution.
        """
        dataset_path = get_test_dataset("watson")
        reader = mrrc.MARCReader(str(dataset_path))

        encoding_counts: dict[str, int] = {}
        total = 0

        for record in reader:
            total += 1
            # The leader encoding indicator is not directly accessible
            # as a character position on the Leader object.  Fall back to
            # reading the raw bytes from the file for this specific test.
            # For now, just count records by record_type as a proxy.
            leader = record.leader()
            if leader is not None and hasattr(leader, "character_coding_scheme"):
                enc_char = leader.character_coding_scheme or "?"
            else:
                enc_char = "?"
            encoding_counts[enc_char] = encoding_counts.get(enc_char, 0) + 1

        assert total > 0, "dataset contained no records"

        # Report distribution — not a pass/fail assertion, but useful
        # diagnostics.  Print so it appears with --nocapture / -s.
        print(f"\nEncoding distribution across {total} records:")
        for char, count in sorted(
            encoding_counts.items(), key=lambda x: -x[1]
        ):
            label = {
                "a": "UTF-8",
                " ": "MARC-8",
            }.get(char, f"unknown ({char!r})")
            pct = 100.0 * count / total
            print(f"  {label}: {count} ({pct:.1f}%)")

        # At minimum, at least one encoding type should be present
        assert len(encoding_counts) >= 1

    def test_no_mojibake_in_titles(self) -> None:
        """Check that title fields (245) don't contain common mojibake
        patterns indicating double-encoding.
        """
        dataset_path = get_test_dataset("watson")
        reader = mrrc.MARCReader(str(dataset_path))

        mojibake_examples: list[str] = []
        records_checked = 0

        for record in reader:
            records_checked += 1
            title_fields = record.get_fields("245")
            for field in title_fields:
                subs = field.subfields()
                if not subs:
                    continue
                for subfield in subs:
                    if _MOJIBAKE_PATTERNS.search(subfield.value):
                        mojibake_examples.append(subfield.value[:120])
                        if len(mojibake_examples) >= 50:
                            break
                if len(mojibake_examples) >= 50:
                    break
            if len(mojibake_examples) >= 50:
                break

        assert records_checked > 0, "dataset contained no records"

        if mojibake_examples:
            sample = "\n".join(f"  - {ex}" for ex in mojibake_examples[:10])
            pytest.fail(
                f"Found {len(mojibake_examples)} title(s) with potential "
                f"mojibake (double-encoding) out of {records_checked} "
                f"records checked. Examples:\n{sample}"
            )

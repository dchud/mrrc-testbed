"""Tests for mrrc_testbed.compare record comparison utilities."""

import mrrc
import pytest

from mrrc_testbed.compare import compare_records, diff_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    leader_mods: dict[int, str] | None = None,
    control_fields: list[tuple[str, str]] | None = None,
    fields: list[mrrc.Field] | None = None,
) -> mrrc.Record:
    """Build a Record with optional leader modifications, control fields, and data fields."""
    rec = mrrc.Record()
    if leader_mods:
        leader = rec.leader()
        for pos, char in leader_mods.items():
            leader[pos] = char
    if control_fields:
        for tag, value in control_fields:
            rec.add_control_field(tag, value)
    if fields:
        for field in fields:
            rec.add_field(field)
    return rec


def _field(tag, ind1, ind2, *subfield_pairs):
    """Shorthand for creating a Field with subfields from code/value pairs."""
    subs = [mrrc.Subfield(code, value) for code, value in subfield_pairs]
    return mrrc.Field(tag, ind1, ind2, subfields=subs)


# ===========================================================================
# compare_records tests
# ===========================================================================


class TestIdenticalRecords:
    """Records that should compare as equal."""

    def test_empty_records(self):
        a = mrrc.Record()
        b = mrrc.Record()
        result = compare_records(a, b)
        assert result["equal"] is True
        assert result["leader"] is None
        assert result["control_fields"] == []
        assert result["fields"] == []

    def test_records_with_same_content(self):
        a = _make_record(
            control_fields=[("001", "abc123")],
            fields=[_field("245", "1", "0", ("a", "Test Title"))],
        )
        b = _make_record(
            control_fields=[("001", "abc123")],
            fields=[_field("245", "1", "0", ("a", "Test Title"))],
        )
        result = compare_records(a, b)
        assert result["equal"] is True


class TestLeaderDiffs:
    """Leader comparison tests."""

    def test_different_leader_position(self):
        a = _make_record(leader_mods={5: "a"})
        b = _make_record(leader_mods={5: "n"})
        result = compare_records(a, b)
        assert result["equal"] is False
        assert result["leader"] is not None
        assert 5 in result["leader"]
        assert result["leader"][5] == {"a": "a", "b": "n"}

    def test_multiple_leader_diffs(self):
        a = _make_record(leader_mods={5: "a", 6: "m"})
        b = _make_record(leader_mods={5: "n", 6: "a"})
        result = compare_records(a, b)
        assert result["leader"] is not None
        assert len(result["leader"]) == 2


class TestControlFieldDiffs:
    """Control field comparison tests."""

    def test_changed_control_field(self):
        a = _make_record(control_fields=[("001", "old_id")])
        b = _make_record(control_fields=[("001", "new_id")])
        result = compare_records(a, b)
        assert result["equal"] is False
        assert len(result["control_fields"]) == 1
        diff = result["control_fields"][0]
        assert diff["type"] == "changed"
        assert diff["a"]["value"] == "old_id"
        assert diff["b"]["value"] == "new_id"

    def test_control_field_only_in_a(self):
        a = _make_record(control_fields=[("001", "id1"), ("003", "DLC")])
        b = _make_record(control_fields=[("001", "id1")])
        result = compare_records(a, b)
        assert result["equal"] is False
        only_a = [d for d in result["control_fields"] if d["type"] == "only_in_a"]
        assert len(only_a) == 1
        assert only_a[0]["tag"] == "003"

    def test_control_field_only_in_b(self):
        a = _make_record(control_fields=[("001", "id1")])
        b = _make_record(control_fields=[("001", "id1"), ("003", "DLC")])
        result = compare_records(a, b)
        assert result["equal"] is False
        only_b = [d for d in result["control_fields"] if d["type"] == "only_in_b"]
        assert len(only_b) == 1
        assert only_b[0]["tag"] == "003"


class TestDataFieldDiffs:
    """Data field comparison tests."""

    def test_added_field(self):
        a = _make_record(fields=[_field("245", "1", "0", ("a", "Title"))])
        b = _make_record(
            fields=[
                _field("245", "1", "0", ("a", "Title")),
                _field("650", "0", "0", ("a", "Subject")),
            ],
        )
        result = compare_records(a, b)
        assert result["equal"] is False
        only_b = [d for d in result["fields"] if d["type"] == "only_in_b"]
        assert len(only_b) == 1
        assert only_b[0]["tag"] == "650"

    def test_removed_field(self):
        a = _make_record(
            fields=[
                _field("245", "1", "0", ("a", "Title")),
                _field("650", "0", "0", ("a", "Subject")),
            ],
        )
        b = _make_record(fields=[_field("245", "1", "0", ("a", "Title"))])
        result = compare_records(a, b)
        assert result["equal"] is False
        only_a = [d for d in result["fields"] if d["type"] == "only_in_a"]
        assert len(only_a) == 1
        assert only_a[0]["tag"] == "650"

    def test_different_indicators(self):
        a = _make_record(fields=[_field("245", "1", "0", ("a", "Title"))])
        b = _make_record(fields=[_field("245", "0", "4", ("a", "Title"))])
        result = compare_records(a, b)
        assert result["equal"] is False
        diff = result["fields"][0]
        assert diff["type"] == "changed"
        assert "indicators" in diff
        assert diff["indicators"]["indicator1"] == {"a": "1", "b": "0"}
        assert diff["indicators"]["indicator2"] == {"a": "0", "b": "4"}

    def test_different_subfield_value(self):
        a = _make_record(fields=[_field("245", "1", "0", ("a", "Old Title"))])
        b = _make_record(fields=[_field("245", "1", "0", ("a", "New Title"))])
        result = compare_records(a, b)
        assert result["equal"] is False
        diff = result["fields"][0]
        assert diff["type"] == "changed"
        assert len(diff["subfields"]) == 1
        sd = diff["subfields"][0]
        assert sd["type"] == "changed"
        assert sd["a"]["value"] == "Old Title"
        assert sd["b"]["value"] == "New Title"

    def test_different_subfield_code(self):
        a = _make_record(fields=[_field("245", "1", "0", ("a", "Title"))])
        b = _make_record(fields=[_field("245", "1", "0", ("b", "Title"))])
        result = compare_records(a, b)
        assert result["equal"] is False
        sd = result["fields"][0]["subfields"][0]
        assert sd["type"] == "changed"
        assert sd["a"]["code"] == "a"
        assert sd["b"]["code"] == "b"

    def test_added_subfield(self):
        a = _make_record(fields=[_field("245", "1", "0", ("a", "Title"))])
        b = _make_record(
            fields=[_field("245", "1", "0", ("a", "Title"), ("b", "Subtitle"))],
        )
        result = compare_records(a, b)
        assert result["equal"] is False
        sd = result["fields"][0]["subfields"][0]
        assert sd["type"] == "only_in_b"
        assert sd["code"] == "b"
        assert sd["value"] == "Subtitle"

    def test_removed_subfield(self):
        a = _make_record(
            fields=[_field("245", "1", "0", ("a", "Title"), ("b", "Subtitle"))],
        )
        b = _make_record(fields=[_field("245", "1", "0", ("a", "Title"))])
        result = compare_records(a, b)
        assert result["equal"] is False
        sd = result["fields"][0]["subfields"][0]
        assert sd["type"] == "only_in_a"
        assert sd["code"] == "b"
        assert sd["value"] == "Subtitle"


# ===========================================================================
# diff_summary tests
# ===========================================================================


class TestDiffSummary:
    """Human-readable diff summary tests."""

    def test_identical_records(self):
        a = mrrc.Record()
        b = mrrc.Record()
        result = compare_records(a, b)
        assert diff_summary(result) == "Records are identical"

    def test_leader_diff_summary(self):
        a = _make_record(leader_mods={5: "a"})
        b = _make_record(leader_mods={5: "n"})
        result = compare_records(a, b)
        summary = diff_summary(result)
        assert "Records differ:" in summary
        assert "Leader: position 5: 'a' vs 'n'" in summary

    def test_control_field_diff_summary(self):
        a = _make_record(control_fields=[("001", "old")])
        b = _make_record(control_fields=[("001", "new")])
        result = compare_records(a, b)
        summary = diff_summary(result)
        assert "Control field 001: 'old' vs 'new'" in summary

    def test_control_field_only_in_a_summary(self):
        a = _make_record(control_fields=[("003", "DLC")])
        b = mrrc.Record()
        result = compare_records(a, b)
        summary = diff_summary(result)
        assert "Control field 003: only in record A" in summary

    def test_field_only_in_a_summary(self):
        a = _make_record(fields=[_field("650", "0", "0", ("a", "Subject"))])
        b = mrrc.Record()
        result = compare_records(a, b)
        summary = diff_summary(result)
        assert "Field 0 (650): only in record A" in summary

    def test_indicator_diff_summary(self):
        a = _make_record(fields=[_field("245", "1", "0", ("a", "Title"))])
        b = _make_record(fields=[_field("245", "0", "0", ("a", "Title"))])
        result = compare_records(a, b)
        summary = diff_summary(result)
        assert "indicator1 '1' vs '0'" in summary

    def test_subfield_diff_summary(self):
        a = _make_record(fields=[_field("245", "1", "0", ("a", "Old Title"))])
        b = _make_record(fields=[_field("245", "1", "0", ("a", "New Title"))])
        result = compare_records(a, b)
        summary = diff_summary(result)
        assert "subfield $a: 'Old Title' vs 'New Title'" in summary

    def test_subfield_only_in_b_summary(self):
        a = _make_record(fields=[_field("245", "1", "0", ("a", "Title"))])
        b = _make_record(
            fields=[_field("245", "1", "0", ("a", "Title"), ("b", "Sub"))],
        )
        result = compare_records(a, b)
        summary = diff_summary(result)
        assert "subfield $b: only in record B" in summary

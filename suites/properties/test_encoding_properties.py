"""Property-based encoding tests for mrrc Python bindings.

Uses Hypothesis to generate arbitrary text and verify encoding round-trips
through mrrc's record construction and serialization pipeline.
"""

import tempfile
from pathlib import Path

import mrrc
from hypothesis import given
from hypothesis import strategies as st

# MARC control characters that cannot appear in subfield/field data.
# \x1d = record terminator, \x1e = field terminator, \x1f = subfield delimiter
_MARC_DELIMITERS = {"\x1d", "\x1e", "\x1f"}

# Strategy for text safe to embed in MARC subfield values.
_safe_marc_text = st.text(
    alphabet=st.characters(
        exclude_characters="\x00\x1d\x1e\x1f",
        exclude_categories=("Cs",),  # exclude surrogates (not valid UTF-8)
    ),
    min_size=1,
    max_size=200,
)


def _roundtrip_record(record: mrrc.Record, tmp_dir: Path) -> mrrc.Record:
    """Write a record to a temp file and read it back."""
    out_path = tmp_dir / "roundtrip.mrc"
    mrrc.write([record], str(out_path))
    records = list(mrrc.MARCReader(str(out_path)))
    assert len(records) == 1
    return records[0]


def _make_record_with_title(title: str) -> mrrc.Record:
    """Build a minimal record with the given title in 245$a."""
    record = mrrc.Record()
    record.add_control_field("001", "prop-test-001")
    field = mrrc.Field("245", "1", "0", subfields=[mrrc.Subfield("a", title)])
    record.add_field(field)
    return record


@given(title=_safe_marc_text)
def test_utf8_roundtrip(title: str) -> None:
    """Arbitrary UTF-8 text in a subfield should survive a write/read cycle."""
    record = _make_record_with_title(title)
    with tempfile.TemporaryDirectory() as tmp:
        parsed = _roundtrip_record(record, Path(tmp))
        result_fields = parsed.get_fields("245")
        assert len(result_fields) > 0
        subs = result_fields[0].subfields()
        assert len(subs) > 0
        assert subs[0].value == title


@given(value=st.text(min_size=1, max_size=100))
def test_control_field_roundtrip(value: str) -> None:
    """Arbitrary text in a control field should survive a write/read cycle."""
    record = mrrc.Record()
    record.add_control_field("001", value)
    with tempfile.TemporaryDirectory() as tmp:
        parsed = _roundtrip_record(record, Path(tmp))
        result = parsed.control_field("001")
        assert result == value


@given(
    ind1=st.sampled_from([" ", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]),
    ind2=st.sampled_from([" ", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]),
)
def test_indicator_roundtrip(ind1: str, ind2: str) -> None:
    """Indicator values should survive a write/read cycle."""
    record = mrrc.Record()
    record.add_control_field("001", "prop-test-001")
    field = mrrc.Field("245", ind1, ind2, subfields=[mrrc.Subfield("a", "Test title")])
    record.add_field(field)
    with tempfile.TemporaryDirectory() as tmp:
        parsed = _roundtrip_record(record, Path(tmp))
        result_fields = parsed.get_fields("245")
        assert len(result_fields) > 0
        assert result_fields[0].indicator1 == ind1
        assert result_fields[0].indicator2 == ind2

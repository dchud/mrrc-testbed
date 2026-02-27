"""Generate encoding test MARC files using the mrrc Python API.

Uses mrrc's Record, Field, and MARCWriter to create well-formed records with
specific encoding content. This also validates that mrrc's writer produces
what we expect.
"""

from __future__ import annotations

import io
from pathlib import Path

from mrrc import Field, Leader, MARCReader, MARCWriter, Record, Subfield

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "encoding"


def make_record(
    control_number: str,
    title: str,
    character_coding: str = "a",
) -> Record:
    """Build a Record with a 001 control field and a 245$a title."""
    leader = Leader()
    leader[9] = character_coding  # 'a' = UTF-8, ' ' = MARC-8

    record = Record(leader)
    record.add_control_field("001", control_number)
    field = Field("245", indicators=["1", "0"], subfields=[Subfield("a", title)])
    record.add_field(field)
    return record


def write_records(records: list[Record], path: Path) -> int:
    """Write records to a .mrc file. Returns byte count."""
    buf = io.BytesIO()
    writer = MARCWriter(buf)
    for record in records:
        writer.write(record)
    writer.close()
    data = buf.getvalue()
    path.write_bytes(data)
    return len(data)


def generate_utf8_titles() -> list[Record]:
    """UTF-8 titles: ASCII, diacritics, CJK, Cyrillic, umlauts."""
    return [
        make_record("utf8-001", "A simple ASCII title"),
        make_record("utf8-002", "Les mis\u00e9rables : \u00f1o\u00f1o \u00fcber"),
        make_record("utf8-003", "\u4e2d\u6587\u6d4b\u8bd5\u6807\u9898"),
        make_record(
            "utf8-004",
            "\u0420\u0443\u0441\u0441\u043a\u0438\u0439 \u0442\u0435\u043a\u0441\u0442",
        ),
        make_record("utf8-005", "M\u00fcnchen \u00d6sterreich Stra\u00dfe"),
        make_record("utf8-006", "Caf\u00e9 \u00e0 la carte"),
    ]


def generate_marc8_ascii() -> list[Record]:
    """MARC-8 (leader pos 9 = ' ') with pure ASCII content."""
    return [
        make_record("m8-001", "Pure ASCII in MARC-8 mode", character_coding=" "),
        make_record("m8-002", "Another MARC-8 ASCII record", character_coding=" "),
        make_record("m8-003", "Library of Congress record", character_coding=" "),
    ]


def generate_replacement_chars() -> list[Record]:
    """Records with pre-existing U+FFFD replacement characters."""
    return [
        make_record("repl-001", "Broken \ufffd encoding here"),
        make_record("repl-002", "Multiple \ufffd\ufffd replacements"),
        make_record("repl-003", "End replacement\ufffd"),
    ]


def generate_mixed_scripts() -> list[Record]:
    """Records with multiple scripts in a single title."""
    return [
        make_record(
            "mix-001",
            "English \u4e2d\u6587 \u041c\u043e\u0441\u043a\u0432\u0430 caf\u00e9",
        ),
        make_record(
            "mix-002", "Tokyo \u6771\u4eac Berlin M\u00fcnchen"
        ),
        make_record(
            "mix-003",
            "\u0410\u043b\u0435\u043a\u0441\u0430\u043d\u0434\u0440 meets \u5f20\u4f1f",
        ),
    ]


def generate_all() -> None:
    """Generate all encoding .mrc files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    files = {
        "utf8_titles.mrc": generate_utf8_titles,
        "marc8_ascii.mrc": generate_marc8_ascii,
        "replacement_chars.mrc": generate_replacement_chars,
        "mixed_scripts.mrc": generate_mixed_scripts,
    }

    for filename, generator in files.items():
        records = generator()
        path = OUTPUT_DIR / filename
        size = write_records(records, path)
        rel = path.relative_to(OUTPUT_DIR.parent.parent)
        print(f"  wrote {rel} ({size} bytes, {len(records)} records)")

    # Verification: read back each file and confirm record count
    print("  verifying readback...")
    for filename, generator in files.items():
        path = OUTPUT_DIR / filename
        expected_count = len(generator())
        reader = MARCReader(str(path))
        actual_count = sum(1 for _ in reader)
        assert actual_count == expected_count, (
            f"{filename}: expected {expected_count} records, got {actual_count}"
        )
    print("  all files verified OK")


if __name__ == "__main__":
    generate_all()

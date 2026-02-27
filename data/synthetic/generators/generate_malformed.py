"""Generate malformed MARC binary files for negative testing.

Builds raw bytes directly — no mrrc API — since the point is to produce
intentionally invalid binary that should cause parse errors.

Ported from the proven construction logic in malformed.rs helpers.
"""

from __future__ import annotations

from pathlib import Path

FIELD_TERMINATOR = 0x1E
RECORD_TERMINATOR = 0x1D
SUBFIELD_DELIMITER = 0x1F

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "malformed"


def make_valid_record(control_number: str) -> bytearray:
    """Build a minimal valid MARC record with a single 001 control field."""
    field_data = control_number.encode("ascii") + bytes([FIELD_TERMINATOR])
    dir_entry = f"001{len(field_data):04d}{0:05d}".encode("ascii")
    base_address = 24 + len(dir_entry) + 1  # +1 for dir terminator
    record_length = base_address + len(field_data) + 1  # +1 for rec terminator
    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")

    buf = bytearray()
    buf.extend(leader)
    buf.extend(dir_entry)
    buf.append(FIELD_TERMINATOR)  # directory terminator
    buf.extend(field_data)
    buf.append(RECORD_TERMINATOR)
    return buf


def make_record_with_title(control_number: str, title: str) -> bytearray:
    """Build a valid MARC record with 001 and 245 fields."""
    field_001 = control_number.encode("ascii") + bytes([FIELD_TERMINATOR])

    field_245 = bytearray()
    field_245.extend(b"10")  # indicators
    field_245.append(SUBFIELD_DELIMITER)
    field_245.append(ord("a"))
    field_245.extend(title.encode("utf-8"))
    field_245.append(FIELD_TERMINATOR)

    dir_001 = f"001{len(field_001):04d}{0:05d}".encode("ascii")
    dir_245 = f"245{len(field_245):04d}{len(field_001):05d}".encode("ascii")

    base_address = 24 + len(dir_001) + len(dir_245) + 1
    record_length = base_address + len(field_001) + len(field_245) + 1

    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")

    buf = bytearray()
    buf.extend(leader)
    buf.extend(dir_001)
    buf.extend(dir_245)
    buf.append(FIELD_TERMINATOR)
    buf.extend(field_001)
    buf.extend(field_245)
    buf.append(RECORD_TERMINATOR)
    return buf


# ---- Generator functions for each malformed file ----


def generate_truncated_leader() -> bytes:
    """Records with leaders shorter than 24 bytes."""
    records = bytearray()

    # 10-byte truncated leader
    records.extend(b"00050nam  ")

    # 15-byte truncated leader
    records.extend(b"00100nam  22000")

    # 23-byte leader (one byte short)
    records.extend(b"00100nam  22000370  450")

    # A valid record followed by a truncated one, to test stream recovery
    records.extend(make_valid_record("trunc-ok"))
    records.extend(b"00050nam  22000")

    return bytes(records)


def generate_invalid_lengths() -> bytes:
    """Records where leader length doesn't match actual size."""
    records = bytearray()

    # Record claims 50000 bytes but only has leader + terminator
    leader = f"{50000:05d}nam  22{25:05d}   4500".encode("ascii")
    records.extend(leader)
    records.append(RECORD_TERMINATOR)

    # Record claims 25 bytes but actually has 60
    short_claim = make_valid_record("len-short")
    # Overwrite length field to claim 25
    records.extend(b"00025" + short_claim[5:])

    # Record claims 99999 bytes (maximum) but has minimal content
    leader = f"{99999:05d}nam  22{25:05d}   4500".encode("ascii")
    records.extend(leader)
    records.append(RECORD_TERMINATOR)

    # A valid record so parsers can potentially resync
    records.extend(make_valid_record("len-ok"))

    return bytes(records)


def generate_bad_directory() -> bytes:
    """Records with corrupted directory entries."""
    records = bytearray()

    # Non-digit characters in tag field
    base_address = 37  # 24 + 12 + 1
    record_length = 38
    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")
    buf = bytearray(leader)
    buf.extend(bytes([0xFF, 0xFE, 0xFD]) + b"000100000")  # corrupted tag
    buf.append(FIELD_TERMINATOR)
    buf.append(RECORD_TERMINATOR)
    records.extend(buf)

    # Non-digit in field length portion
    buf = bytearray(leader)
    buf.extend(b"245XXXX00000")
    buf.append(FIELD_TERMINATOR)
    buf.append(RECORD_TERMINATOR)
    records.extend(buf)

    # Incomplete directory entry (8 of 12 bytes)
    base_address = 24 + 8 + 1
    record_length = base_address + 1
    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")
    buf = bytearray(leader)
    buf.extend(b"24500150")  # only 8 bytes, need 12
    buf.append(FIELD_TERMINATOR)
    buf.append(RECORD_TERMINATOR)
    records.extend(buf)

    # Overlapping directory entries (both claim same offset)
    field_data = (
        b"10" + bytes([SUBFIELD_DELIMITER]) + b"atest"
        + bytes([FIELD_TERMINATOR])
    )
    dir_1 = f"245{len(field_data):04d}{0:05d}".encode("ascii")
    dir_2 = f"650{len(field_data):04d}{0:05d}".encode("ascii")
    base_address = 24 + 12 + 12 + 1
    record_length = base_address + len(field_data) + 1
    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")
    buf = bytearray(leader)
    buf.extend(dir_1)
    buf.extend(dir_2)
    buf.append(FIELD_TERMINATOR)
    buf.extend(field_data)
    buf.append(RECORD_TERMINATOR)
    records.extend(buf)

    # Directory entry pointing past end of record
    field_data = b"test" + bytes([FIELD_TERMINATOR])
    dir_entry = b"001005099999"  # start offset = 99999
    base_address = 24 + 12 + 1
    record_length = base_address + len(field_data) + 1
    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")
    buf = bytearray(leader)
    buf.extend(dir_entry)
    buf.append(FIELD_TERMINATOR)
    buf.extend(field_data)
    buf.append(RECORD_TERMINATOR)
    records.extend(buf)

    return bytes(records)


def generate_missing_terminators() -> bytes:
    """Records missing field or record terminators."""
    records = bytearray()

    # Valid record with record terminator removed
    valid = make_valid_record("no-rec-term")
    records.extend(valid[:-1])  # strip trailing 0x1D

    # Record where field data lacks field terminator
    field_data = b"notermhere"  # no 0x1E
    dir_entry = f"001{len(field_data):04d}{0:05d}".encode("ascii")
    base_address = 24 + 12 + 1
    record_length = base_address + len(field_data) + 1
    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")
    buf = bytearray(leader)
    buf.extend(dir_entry)
    buf.append(FIELD_TERMINATOR)  # directory terminator present
    buf.extend(field_data)
    buf.append(RECORD_TERMINATOR)
    records.extend(buf)

    # Missing directory terminator (field data starts where dir term should be)
    field_data = b"test" + bytes([FIELD_TERMINATOR])
    dir_entry = f"001{len(field_data):04d}{0:05d}".encode("ascii")
    # Claim base_address = 24 + 12 (no +1 for dir term)
    base_address = 24 + 12
    record_length = base_address + len(field_data) + 1
    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")
    buf = bytearray(leader)
    buf.extend(dir_entry)
    # No directory terminator — jump straight to field data
    buf.extend(field_data)
    buf.append(RECORD_TERMINATOR)
    records.extend(buf)

    # A valid record for potential stream recovery
    records.extend(make_valid_record("term-ok"))

    return bytes(records)


def generate_embedded_terminators() -> bytes:
    """Records with 0x1D/0x1E in unexpected positions."""
    records = bytearray()

    # 0x1D (record terminator) embedded in control field data
    field_data = (
        b"ctrl" + bytes([RECORD_TERMINATOR])
        + b"number" + bytes([FIELD_TERMINATOR])
    )
    dir_entry = f"001{len(field_data):04d}{0:05d}".encode("ascii")
    base_address = 24 + len(dir_entry) + 1
    record_length = base_address + len(field_data) + 1
    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")
    buf = bytearray(leader)
    buf.extend(dir_entry)
    buf.append(FIELD_TERMINATOR)
    buf.extend(field_data)
    buf.append(RECORD_TERMINATOR)
    records.extend(buf)

    # 0x1E (field terminator) in middle of a data field
    field_245 = (
        b"10"
        + bytes([SUBFIELD_DELIMITER])
        + b"aSplit"
        + bytes([FIELD_TERMINATOR])  # premature
        + b"Title"
        + bytes([FIELD_TERMINATOR])
    )
    dir_001 = f"001{5:04d}{0:05d}".encode("ascii")
    dir_245 = f"245{len(field_245):04d}{5:05d}".encode("ascii")
    field_001 = b"emb1" + bytes([FIELD_TERMINATOR])
    base_address = 24 + 12 + 12 + 1
    record_length = base_address + len(field_001) + len(field_245) + 1
    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")
    buf = bytearray(leader)
    buf.extend(dir_001)
    buf.extend(dir_245)
    buf.append(FIELD_TERMINATOR)
    buf.extend(field_001)
    buf.extend(field_245)
    buf.append(RECORD_TERMINATOR)
    records.extend(buf)

    # 0x1D right at the start of field data area
    field_data = bytes([RECORD_TERMINATOR]) + b"afterterm" + bytes([FIELD_TERMINATOR])
    dir_entry = f"001{len(field_data):04d}{0:05d}".encode("ascii")
    base_address = 24 + 12 + 1
    record_length = base_address + len(field_data) + 1
    leader = f"{record_length:05d}nam  22{base_address:05d}   4500".encode("ascii")
    buf = bytearray(leader)
    buf.extend(dir_entry)
    buf.append(FIELD_TERMINATOR)
    buf.extend(field_data)
    buf.append(RECORD_TERMINATOR)
    records.extend(buf)

    return bytes(records)


def generate_garbage() -> bytes:
    """All-zeros, all-0xFF, and pseudo-random byte sequences."""
    records = bytearray()

    # 100 bytes of all zeros
    records.extend(bytes(100))

    # 100 bytes of all 0xFF
    records.extend(bytes([0xFF] * 100))

    # 100 bytes of all spaces
    records.extend(b" " * 100)

    # 256 bytes of deterministic pseudo-random (same PRNG as malformed.rs)
    state = 0xDEAD_BEEF
    for _ in range(256):
        state = (state * 1103515245 + 12345) & 0xFFFF_FFFF
        records.append((state >> 16) & 0xFF)

    # A mix: valid leader prefix followed by garbage
    records.extend(b"00100nam  2200037   4500")
    records.extend(bytes([0xDE, 0xAD, 0xBE, 0xEF] * 10))

    return bytes(records)


def generate_all() -> None:
    """Generate all malformed .mrc files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    files = {
        "truncated_leader.mrc": generate_truncated_leader,
        "invalid_lengths.mrc": generate_invalid_lengths,
        "bad_directory.mrc": generate_bad_directory,
        "missing_terminators.mrc": generate_missing_terminators,
        "embedded_terminators.mrc": generate_embedded_terminators,
        "garbage.mrc": generate_garbage,
    }

    for filename, generator in files.items():
        path = OUTPUT_DIR / filename
        data = generator()
        path.write_bytes(data)
        rel = path.relative_to(OUTPUT_DIR.parent.parent)
        print(f"  wrote {rel} ({len(data)} bytes)")


if __name__ == "__main__":
    generate_all()

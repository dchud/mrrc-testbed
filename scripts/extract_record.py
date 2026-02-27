"""Extract a single MARC record from a large binary MARC file.

Supports extraction by byte offset (fast, direct seek) or by control
number (slower, scans the file). Can display record info and/or write
the raw record bytes to an output file.
"""

import argparse
import sys
from pathlib import Path

# MARC structural constants
LEADER_LEN = 24
DIRECTORY_ENTRY_LEN = 12
FIELD_TERMINATOR = 0x1E
RECORD_TERMINATOR = 0x1D


def read_record_at_offset(f, offset: int) -> bytes:
    """Seek to offset, read the 5-byte length prefix, then read the full record.

    Returns the raw record bytes (including the leader).
    """
    f.seek(offset)
    length_bytes = f.read(5)
    if len(length_bytes) < 5:
        raise ValueError(
            f"Could not read 5-byte length at offset {offset} "
            f"(got {len(length_bytes)} bytes)"
        )
    try:
        record_length = int(length_bytes)
    except ValueError:
        raise ValueError(
            f"Invalid record length at offset {offset}: {length_bytes!r}"
        )
    if record_length < LEADER_LEN:
        raise ValueError(
            f"Record length {record_length} at offset {offset} "
            f"is shorter than the 24-byte leader"
        )
    f.seek(offset)
    raw = f.read(record_length)
    if len(raw) < record_length:
        raise ValueError(
            f"Truncated record at offset {offset}: "
            f"expected {record_length} bytes, got {len(raw)}"
        )
    return raw


def extract_control_number(raw_bytes: bytes) -> str | None:
    """Parse the directory to find the 001 tag and extract its field value.

    Returns the control number string, or None if no 001 field is found.
    """
    if len(raw_bytes) < LEADER_LEN:
        return None

    try:
        base_address = int(raw_bytes[12:17])
    except ValueError:
        return None

    # Walk the directory starting at byte 24
    pos = LEADER_LEN
    while pos + DIRECTORY_ENTRY_LEN <= len(raw_bytes):
        # Check for directory terminator
        if raw_bytes[pos] == FIELD_TERMINATOR:
            break

        tag = raw_bytes[pos : pos + 3].decode("ascii", errors="replace")
        try:
            field_length = int(raw_bytes[pos + 3 : pos + 7])
            field_offset = int(raw_bytes[pos + 7 : pos + 12])
        except ValueError:
            pos += DIRECTORY_ENTRY_LEN
            continue

        if tag == "001":
            start = base_address + field_offset
            end = start + field_length
            if end > len(raw_bytes):
                return None
            value = raw_bytes[start:end]
            # Strip field terminator and record terminator bytes
            value = value.rstrip(bytes([FIELD_TERMINATOR, RECORD_TERMINATOR]))
            return value.decode("ascii", errors="replace").strip()

        pos += DIRECTORY_ENTRY_LEN

    return None


def find_record_by_control_number(
    path: Path, target_cn: str
) -> tuple[int, bytes] | None:
    """Iterate through a MARC file, returning (offset, raw_bytes) for a match.

    Prints progress every 100,000 records scanned.
    """
    count = 0
    with open(path, "rb") as f:
        while True:
            offset = f.tell()
            length_bytes = f.read(5)
            if len(length_bytes) < 5:
                break

            try:
                record_length = int(length_bytes)
            except ValueError:
                break

            if record_length < LEADER_LEN:
                break

            # Seek back and read the full record
            f.seek(offset)
            raw = f.read(record_length)
            if len(raw) < record_length:
                break

            count += 1
            if count % 100_000 == 0:
                print(f"  Scanned {count:,} records...", file=sys.stderr)

            cn = extract_control_number(raw)
            if cn == target_cn:
                print(
                    f"  Found after scanning {count:,} records.", file=sys.stderr
                )
                return (offset, raw)

    print(
        f"  Control number '{target_cn}' not found "
        f"after scanning {count:,} records.",
        file=sys.stderr,
    )
    return None


def record_info(raw_bytes: bytes, offset: int | None = None) -> dict:
    """Return a dict of key metadata about a MARC record.

    Keys: record_length, control_number, field_count, encoding,
    record_type, bib_level, offset (if provided).
    """
    leader = raw_bytes[:LEADER_LEN]
    record_length = len(raw_bytes)
    control_number = extract_control_number(raw_bytes)

    # Count directory entries
    field_count = 0
    pos = LEADER_LEN
    while pos + DIRECTORY_ENTRY_LEN <= len(raw_bytes):
        if raw_bytes[pos] == FIELD_TERMINATOR:
            break
        field_count += 1
        pos += DIRECTORY_ENTRY_LEN

    # Leader byte 9: character coding scheme
    encoding_byte = chr(leader[9]) if len(leader) > 9 else "?"
    encoding = "UTF-8" if encoding_byte == "a" else f"MARC-8 ('{encoding_byte}')"

    # Leader byte 6: type of record
    record_type = chr(leader[6]) if len(leader) > 6 else "?"

    # Leader byte 7: bibliographic level
    bib_level = chr(leader[7]) if len(leader) > 7 else "?"

    info = {
        "record_length": record_length,
        "control_number": control_number,
        "field_count": field_count,
        "encoding": encoding,
        "record_type": record_type,
        "bib_level": bib_level,
    }
    if offset is not None:
        info["offset"] = offset
    return info


def format_info(info: dict) -> str:
    """Pretty-print a record info dict as a human-readable string."""
    lines = []
    if "offset" in info:
        lines.append(f"  Offset:         {info['offset']:,}")
    lines.append(f"  Record length:  {info['record_length']:,} bytes")
    lines.append(f"  Control number: {info['control_number'] or '(none)'}")
    lines.append(f"  Field count:    {info['field_count']}")
    lines.append(f"  Encoding:       {info['encoding']}")
    lines.append(f"  Record type:    {info['record_type']}")
    lines.append(f"  Bib level:      {info['bib_level']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="Extract a single MARC record from a large binary MARC file.",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to the source MARC file",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=None,
        help="Byte offset of the record in the source file",
    )
    parser.add_argument(
        "--control-number",
        type=str,
        default=None,
        help="Control number (001 field) to search for",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file path to write the extracted raw record",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Display record metadata",
    )
    return parser


def main() -> int:
    """Main entry point. Returns exit code."""
    parser = build_parser()
    args = parser.parse_args()

    # Validate: must provide at least one of --offset or --control-number
    if args.offset is None and args.control_number is None:
        parser.error("Must provide at least one of --offset or --control-number")

    # Validate: source file exists
    source: Path = args.source
    if not source.is_file():
        print(f"ERROR: Source file does not exist: {source}", file=sys.stderr)
        return 1

    # Validate: offset within file size
    file_size = source.stat().st_size
    if args.offset is not None and args.offset >= file_size:
        print(
            f"ERROR: Offset {args.offset:,} is beyond file size "
            f"({file_size:,} bytes): {source}",
            file=sys.stderr,
        )
        return 1

    # Extract the record
    raw_bytes: bytes | None = None
    offset: int | None = args.offset

    if args.offset is not None:
        try:
            with open(source, "rb") as f:
                raw_bytes = read_record_at_offset(f, args.offset)
        except ValueError as e:
            print(f"WARNING: {e}", file=sys.stderr)
            return 1
    elif args.control_number is not None:
        print(
            f"Searching for control number '{args.control_number}' "
            f"in {source}...",
            file=sys.stderr,
        )
        result = find_record_by_control_number(source, args.control_number)
        if result is None:
            return 1
        offset, raw_bytes = result

    if raw_bytes is None:
        print("ERROR: No record extracted.", file=sys.stderr)
        return 1

    # Display info if requested (or if no --output)
    if args.info or args.output is None:
        info = record_info(raw_bytes, offset=offset)
        print(format_info(info))

    # Write output if requested
    if args.output is not None:
        args.output.write_bytes(raw_bytes)
        print(f"Wrote {len(raw_bytes):,} bytes to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

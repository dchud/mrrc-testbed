"""CLI for selecting MARC records from source files to create committed fixture sets.

Supports random sampling (fully implemented) and targeted selection via criteria
files (stub, requires mrrc for record parsing).
"""

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path


def iterate_records(path: Path):
    """Yield (offset, raw_bytes) for each MARC record in a .mrc file.

    MARC binary format: each record starts with a 5-byte ASCII length prefix
    giving the total record length. Records are terminated by 0x1D.
    """
    with open(path, "rb") as f:
        while True:
            offset = f.tell()
            length_bytes = f.read(5)
            if len(length_bytes) == 0:
                break
            if len(length_bytes) < 5:
                print(
                    f"WARNING: Incomplete length prefix at offset {offset}, "
                    f"got {len(length_bytes)} bytes. Stopping.",
                    file=sys.stderr,
                )
                break
            try:
                record_length = int(length_bytes)
            except ValueError:
                print(
                    f"WARNING: Invalid record length "
                    f"{length_bytes!r} at offset {offset}. Stopping.",
                    file=sys.stderr,
                )
                break
            if record_length < 25:
                print(
                    f"WARNING: Record length {record_length} too small "
                    f"at offset {offset}. Stopping.",
                    file=sys.stderr,
                )
                break
            # We already read 5 bytes of the record; read the rest
            remaining = f.read(record_length - 5)
            if len(remaining) < record_length - 5:
                print(
                    f"WARNING: Truncated record at offset {offset}, "
                    f"expected {record_length} bytes. Stopping.",
                    file=sys.stderr,
                )
                break
            raw_bytes = length_bytes + remaining
            yield (offset, raw_bytes)


def extract_control_number(raw_bytes: bytes) -> str | None:
    """Extract the 001 control number field from raw MARC bytes.

    Parses the directory (starting at byte 24) to find a "001" tag entry,
    then extracts the field data from the record body. Returns None if
    no 001 field is found.
    """
    if len(raw_bytes) < 25:
        return None

    # Base address of data is bytes 12-16 of the leader
    try:
        base_address = int(raw_bytes[12:17])
    except ValueError:
        return None

    # Directory starts at byte 24 and consists of 12-byte entries
    # terminated by field terminator 0x1E
    directory_start = 24
    pos = directory_start

    while pos + 12 <= len(raw_bytes):
        # Check for directory terminator
        if raw_bytes[pos] == 0x1E:
            break

        tag = raw_bytes[pos : pos + 3].decode("ascii", errors="replace")
        try:
            field_length = int(raw_bytes[pos + 3 : pos + 7])
            field_position = int(raw_bytes[pos + 7 : pos + 12])
        except ValueError:
            pos += 12
            continue

        if tag == "001":
            # Field data is at base_address + field_position
            start = base_address + field_position
            end = start + field_length
            if end <= len(raw_bytes):
                field_data = raw_bytes[start:end]
                # Strip field terminator (0x1E) and any whitespace
                value = field_data.rstrip(b"\x1e").decode(
                    "ascii", errors="replace"
                ).strip()
                return value if value else None
            return None

        pos += 12

    return None


def count_records(source_path: Path) -> int:
    """Count the total number of records in a .mrc file."""
    count = 0
    for _ in iterate_records(source_path):
        count += 1
    return count


def random_sample(source_path: Path, count: int):
    """Two-pass random sampling of MARC records.

    First pass: count total records. Then select random indices.
    Second pass: collect the selected records.

    Yields (offset, raw_bytes, control_number) tuples.
    """
    # First pass: count records
    print(f"Pass 1: Counting records in {source_path}...")
    total = count_records(source_path)
    print(f"  Found {total} records.")

    if total == 0:
        print("WARNING: Source file contains no records.", file=sys.stderr)
        return

    actual_count = min(count, total)
    if actual_count < count:
        print(
            f"  Requested {count} but only {total} available. "
            f"Selecting all {total}."
        )

    # Select random indices
    selected_indices = set(random.sample(range(total), actual_count))
    print(f"  Selected {actual_count} random indices.")

    # Second pass: collect selected records
    print("Pass 2: Extracting selected records...")
    collected = 0
    for idx, (offset, raw_bytes) in enumerate(iterate_records(source_path)):
        if idx in selected_indices:
            control_number = extract_control_number(raw_bytes)
            yield (offset, raw_bytes, control_number)
            collected += 1
            if collected >= actual_count:
                break

    print(f"  Extracted {collected} records.")


def targeted_sample(source_path: Path, criteria_path: Path, count: int):
    """Targeted selection of MARC records based on criteria.

    Not yet implemented — requires mrrc for full record parsing.
    """
    raise NotImplementedError(
        "Targeted selection requires mrrc for record parsing"
    )


def write_fixtures(
    records: list[tuple[int, bytes, str | None]],
    output_dir: Path,
    source_name: str,
    source_url: str,
) -> None:
    """Write selected records as a fixture set.

    Creates:
    - sample.mrc: concatenated raw MARC bytes
    - manifest.json: provenance metadata for each record
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    sample_path = output_dir / "sample.mrc"
    manifest_path = output_dir / "manifest.json"

    # Write concatenated MARC binary
    with open(sample_path, "wb") as f:
        for _, raw_bytes, _ in records:
            f.write(raw_bytes)

    # Build manifest
    manifest = {
        "source": source_name,
        "source_url": source_url,
        "download_date": date.today().isoformat(),
        "license": "Public Domain (US Government Work)",
        "records": [],
    }

    for idx, (offset, raw_bytes, control_number) in enumerate(records):
        manifest["records"].append(
            {
                "index": idx,
                "control_number": control_number,
                "source_offset": offset,
                "selection_reason": "random_sample",
                "notes": None,
            }
        )

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    sample_size = sample_path.stat().st_size
    size_kb = sample_size / 1024
    print(f"Wrote {len(records)} records to {sample_path} ({size_kb:.1f} KB)")
    print(f"Wrote manifest to {manifest_path}")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Select MARC records from source files to create "
            "committed fixture sets."
        ),
    )
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Path to source .mrc file",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output directory for fixture files",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=500,
        help="Number of records to select (default: 500)",
    )
    parser.add_argument(
        "--method",
        choices=["random", "targeted"],
        default="random",
        help="Selection method (default: random)",
    )
    parser.add_argument(
        "--criteria",
        type=Path,
        help="Path to criteria JSON file (required if method=targeted)",
    )
    parser.add_argument(
        "--source-name",
        default=None,
        help="Human-readable source name (default: derived from filename)",
    )
    parser.add_argument(
        "--source-url",
        default="",
        help="URL where source data was obtained",
    )
    return parser


def main() -> int:
    """Main entry point. Returns exit code."""
    parser = build_parser()
    args = parser.parse_args()

    # Validate source file
    if not args.source.is_file():
        print(f"ERROR: Source file not found: {args.source}", file=sys.stderr)
        return 1

    if args.source.stat().st_size == 0:
        print(f"ERROR: Source file is empty: {args.source}", file=sys.stderr)
        return 1

    # Validate targeted method requirements
    if args.method == "targeted" and args.criteria is None:
        print(
            "ERROR: --criteria is required when --method=targeted",
            file=sys.stderr,
        )
        return 1

    if args.criteria is not None and not args.criteria.is_file():
        print(
            f"ERROR: Criteria file not found: {args.criteria}",
            file=sys.stderr,
        )
        return 1

    # Derive source name from filename if not provided
    source_name = args.source_name
    if source_name is None:
        source_name = args.source.stem.replace("_", " ").title()

    # Run the selected method
    if args.method == "random":
        records = list(random_sample(args.source, args.count))
    elif args.method == "targeted":
        try:
            records = list(
                targeted_sample(args.source, args.criteria, args.count)
            )
        except NotImplementedError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
    else:
        print(f"ERROR: Unknown method: {args.method}", file=sys.stderr)
        return 1

    if not records:
        print("ERROR: No records were selected.", file=sys.stderr)
        return 1

    # Write output
    write_fixtures(records, args.output, source_name, args.source_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())

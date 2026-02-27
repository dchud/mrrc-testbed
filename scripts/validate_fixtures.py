"""Validate committed fixtures and manifests.

Checks: manifest sync, control number match, size budget, provenance
completeness, record validity.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Generator

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"

SIZE_WARNING_BYTES = 8 * 1024 * 1024  # 8 MB
SIZE_ERROR_BYTES = 10 * 1024 * 1024  # 10 MB

REQUIRED_PROVENANCE_FIELDS = {"source", "selection_reason"}


def iterate_records(
    path: Path,
) -> Generator[tuple[int, int, bytes], None, None]:
    """Yield (index, offset, raw_bytes) for each MARC record in a file.

    MARC binary format:
    - First 5 bytes of each record are the ASCII-encoded record length.
    - Read that many bytes total (including the 5-byte prefix) to get
      the full record.
    """
    data = path.read_bytes()
    offset = 0
    index = 0
    while offset < len(data):
        if offset + 5 > len(data):
            # Not enough bytes for a length prefix; malformed trailing data.
            yield (index, offset, data[offset:])
            break
        length_str = data[offset : offset + 5]
        try:
            record_length = int(length_str)
        except ValueError:
            # Cannot parse length; yield remaining data as one bad record.
            yield (index, offset, data[offset:])
            break
        if record_length < 5:
            yield (index, offset, data[offset:])
            break
        end = offset + record_length
        if end > len(data):
            # Record extends past end of file.
            yield (index, offset, data[offset:])
            break
        yield (index, offset, data[offset:end])
        offset = end
        index += 1


def extract_control_number(raw: bytes) -> str | None:
    """Extract the 001 control number from a raw MARC record.

    Directory starts at byte 24. Each entry is 12 bytes:
      tag (3) + field_length (4) + field_position (5)
    Directory is terminated by 0x1E (field terminator).
    Base address of data is in leader bytes 12-16.
    """
    if len(raw) < 25:
        return None

    try:
        base_address = int(raw[12:17])
    except ValueError:
        return None

    directory = raw[24:]
    pos = 0
    while pos + 12 <= len(directory):
        if directory[pos] == 0x1E:
            break
        tag = directory[pos : pos + 3]
        try:
            field_length = int(directory[pos + 3 : pos + 7])
            field_position = int(directory[pos + 7 : pos + 12])
        except ValueError:
            pos += 12
            continue
        if tag == b"001":
            start = base_address + field_position
            end = start + field_length
            if end <= len(raw):
                value = raw[start:end]
                # Strip field terminator (0x1E) and any leading/trailing whitespace.
                return value.rstrip(b"\x1e").decode("ascii", errors="replace").strip()
            return None
        pos += 12
    return None


def validate_record(raw: bytes) -> list[str]:
    """Check structural validity of a single MARC record.

    Returns a list of issue strings (empty means valid).
    """
    issues: list[str] = []

    if len(raw) < 25:
        issues.append(f"Record too short ({len(raw)} bytes, need at least 25)")
        return issues

    # Leader length check.
    try:
        stated_length = int(raw[0:5])
    except ValueError:
        issues.append(f"Cannot parse leader length: {raw[0:5]!r}")
        return issues

    if stated_length != len(raw):
        issues.append(
            f"Leader length ({stated_length}) != actual length ({len(raw)})"
        )

    # Record terminator.
    if raw[-1] != 0x1D:
        issues.append(f"Missing record terminator 0x1D (got 0x{raw[-1]:02X})")

    # Base address.
    try:
        base_address = int(raw[12:17])
    except ValueError:
        issues.append(f"Cannot parse base address: {raw[12:17]!r}")
        return issues

    if base_address < 25 or base_address > len(raw):
        issues.append(f"Base address out of range: {base_address}")
        return issues

    # Directory parsing.
    directory = raw[24:base_address]
    if len(directory) == 0:
        issues.append("Empty directory")
        return issues

    # Directory should end with 0x1E.
    if directory[-1] != 0x1E:
        issues.append(
            f"Directory not terminated by 0x1E (got 0x{directory[-1]:02X})"
        )

    # Entries before the terminator should be a multiple of 12 bytes.
    dir_entries = directory.rstrip(b"\x1e")
    if len(dir_entries) % 12 != 0:
        issues.append(
            f"Directory entry region is {len(dir_entries)} bytes "
            f"(not a multiple of 12)"
        )

    return issues


def _format_size(size_bytes: int) -> str:
    """Format byte count as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def validate_fixture_dir(
    dir_path: Path, strict: bool
) -> tuple[bool, list[str], list[str]]:
    """Validate one fixture directory.

    Returns (ok, warnings, errors).
    """
    warnings: list[str] = []
    errors: list[str] = []

    sample_path = dir_path / "sample.mrc"
    manifest_path = dir_path / "manifest.json"

    if not sample_path.exists():
        # No sample.mrc means nothing to validate (skip).
        return True, warnings, errors

    if not manifest_path.exists():
        errors.append("manifest.json is missing")
        return False, warnings, errors

    # Parse records from sample.mrc.
    records: list[tuple[int, int, bytes]] = []
    record_issues: dict[int, list[str]] = {}
    record_control_numbers: dict[int, str | None] = {}

    for index, offset, raw in iterate_records(sample_path):
        records.append((index, offset, raw))
        issues = validate_record(raw)
        if issues:
            record_issues[index] = issues
        record_control_numbers[index] = extract_control_number(raw)

    file_size = sample_path.stat().st_size
    record_count = len(records)

    print(f"  \u2713 sample.mrc: {record_count} records, {_format_size(file_size)}")

    # Report record validity issues.
    if record_issues:
        for idx, issues in record_issues.items():
            for issue in issues:
                errors.append(f"Record {idx}: {issue}")

    # Load manifest.
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        errors.append(f"Cannot parse manifest.json: {exc}")
        return False, warnings, errors

    manifest_records = manifest.get("records", [])
    manifest_count = len(manifest_records)

    # Build lookup by index from manifest.
    manifest_by_index: dict[int, dict] = {}
    for entry in manifest_records:
        idx = entry.get("index")
        if idx is not None:
            manifest_by_index[idx] = entry

    # Count sync check.
    if manifest_count == record_count:
        print(
            f"  \u2713 manifest.json: {manifest_count} entries, "
            f"all records accounted for"
        )
    else:
        errors.append(
            f"Record count mismatch: sample.mrc has {record_count}, "
            f"manifest.json has {manifest_count}"
        )

    # Cross-check: orphaned manifest entries (in manifest but not in .mrc).
    mrc_indices = set(range(record_count))
    manifest_indices = set(manifest_by_index.keys())

    orphaned = manifest_indices - mrc_indices
    if orphaned:
        errors.append(
            f"Orphaned manifest entries (no matching record): "
            f"indices {sorted(orphaned)}"
        )
    else:
        print("  \u2713 No orphaned manifest entries")

    # Cross-check: untracked records (in .mrc but not in manifest).
    untracked = mrc_indices - manifest_indices
    if untracked:
        errors.append(
            f"Untracked records in .mrc file (no manifest entry): "
            f"indices {sorted(untracked)}"
        )
    else:
        print("  \u2713 No untracked records in .mrc file")

    # Control number match.
    control_mismatches: list[str] = []
    for idx in sorted(mrc_indices & manifest_indices):
        manifest_cn = manifest_by_index[idx].get("control_number")
        actual_cn = record_control_numbers.get(idx)
        if manifest_cn is not None and actual_cn is not None:
            if str(manifest_cn).strip() != str(actual_cn).strip():
                control_mismatches.append(
                    f"Record {idx}: manifest says '{manifest_cn}', "
                    f"actual is '{actual_cn}'"
                )

    if control_mismatches:
        for msg in control_mismatches:
            errors.append(f"Control number mismatch: {msg}")
    else:
        print("  \u2713 Control numbers match")

    # Provenance completeness.
    provenance_issues: list[str] = []
    for entry in manifest_records:
        idx = entry.get("index", "?")
        for field in REQUIRED_PROVENANCE_FIELDS:
            if field == "source":
                # source can be at top level or per-record.
                if not entry.get(field) and not manifest.get(field):
                    provenance_issues.append(
                        f"Record {idx}: missing '{field}'"
                    )
            else:
                if not entry.get(field):
                    provenance_issues.append(
                        f"Record {idx}: missing '{field}'"
                    )

    if provenance_issues:
        for msg in provenance_issues:
            warnings.append(f"Provenance: {msg}")
    else:
        print("  \u2713 Provenance complete for all records")

    ok = len(errors) == 0 and (not strict or len(warnings) == 0)
    return ok, warnings, errors


def main() -> int:
    """Validate all fixture directories under data/fixtures/."""
    parser = argparse.ArgumentParser(
        description="Validate fixtures and manifests"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on any warning",
    )
    args = parser.parse_args()

    if not FIXTURES_DIR.is_dir():
        print(f"Fixtures directory not found: {FIXTURES_DIR}")
        return 1

    fixture_dirs = sorted(
        d for d in FIXTURES_DIR.iterdir() if d.is_dir()
    )

    total_size = 0
    any_validated = False
    all_warnings: list[str] = []
    all_errors: list[str] = []

    for fixture_dir in fixture_dirs:
        sample_path = fixture_dir / "sample.mrc"
        if not sample_path.exists():
            # Skip directories without sample.mrc (e.g. .gitkeep only).
            continue

        any_validated = True
        print(f"Validating {fixture_dir.relative_to(FIXTURES_DIR.parent.parent)}/...")

        _ok, warnings, errors = validate_fixture_dir(fixture_dir, args.strict)

        total_size += sample_path.stat().st_size

        for w in warnings:
            print(f"  WARNING: {w}")
        for e in errors:
            print(f"  ERROR: {e}")

        all_warnings.extend(warnings)
        all_errors.extend(errors)

    if not any_validated:
        print("No fixtures to validate.")
        print("Status: OK")
        return 0

    # Size budget.
    print()
    size_str = _format_size(total_size)
    print(f"Total fixture size: {size_str} (target: <10 MB)")

    if total_size >= SIZE_ERROR_BYTES:
        all_errors.append(
            f"Total fixture size ({size_str}) exceeds 10 MB limit"
        )
    elif total_size >= SIZE_WARNING_BYTES:
        msg = f"Total fixture size ({size_str}) exceeds 8 MB warning threshold"
        all_warnings.append(msg)
        print(f"WARNING: {msg}")

    # Final status.
    if all_errors:
        print(f"Status: FAILED ({len(all_errors)} error(s))")
        return 1
    elif all_warnings and args.strict:
        print(f"Status: FAILED ({len(all_warnings)} warning(s) in strict mode)")
        return 1
    elif all_warnings:
        print(f"Status: OK ({len(all_warnings)} warning(s))")
        return 0
    else:
        print("Status: OK")
        return 0


if __name__ == "__main__":
    sys.exit(main())

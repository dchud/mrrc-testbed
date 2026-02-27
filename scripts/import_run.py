"""CLI script for importing test run results into persistent state.

Reads JSON discovery files from results/discoveries/, deduplicates against
existing state, normalizes field names, and writes YAML to state/. This is
the bridge between DiscoveryWriter (Rust) output and persistent state.
"""

import argparse
import json
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from mrrc_testbed.config import project_root
from mrrc_testbed.state import (
    RECORDS_DIR,
    RUNS_DIR,
    discovery_exists,
    list_discoveries,
    save_discovery,
    save_run,
)


def generate_run_id() -> str:
    """Generate a sequential run ID for today: run-YYYY-MM-DD-NNN.

    Scans existing run YAML files to find the next sequence number for
    today's date.
    """
    today = date.today().isoformat()
    prefix = f"run-{today}-"

    existing = sorted(RUNS_DIR.glob(f"{prefix}*.yaml"))
    if not existing:
        return f"{prefix}001"

    # Find the highest sequence number among today's runs
    max_seq = 0
    for path in existing:
        stem = path.stem  # e.g. "run-2024-02-01-003"
        suffix = stem[len(prefix) :]
        try:
            seq = int(suffix)
            max_seq = max(max_seq, seq)
        except ValueError:
            continue

    return f"{prefix}{max_seq + 1:03d}"


def load_json_files(input_dir: Path) -> list[tuple[Path, list[dict]]]:
    """Load all JSON files from the input directory.

    Returns a list of (path, data) tuples. Corrupt JSON files are skipped
    with a warning to stderr.
    """
    results = []
    json_files = sorted(input_dir.glob("*.json"))

    for path in json_files:
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"WARNING: Skipping corrupt JSON file {path}: {e}",
                file=sys.stderr,
            )
            continue

        if not isinstance(data, list):
            print(
                f"WARNING: Skipping {path}: expected JSON array, "
                f"got {type(data).__name__}",
                file=sys.stderr,
            )
            continue

        results.append((path, data))

    return results


def normalize_discovery(raw: dict, run_id: str) -> dict:
    """Normalize a raw JSON discovery into the persistent YAML format.

    Applies the field mapping:
    - record.offset_bytes -> record.source_offset
    - record.extracted_to -> record.extracted_file (rewritten to state/records/ path)
    - record.raw_bytes_base64 -> dropped
    - context.mrrc_version -> top-level mrrc_version
    - context -> dropped (stored in Run YAML instead)
    - discovered_in_run -> added from run_id
    """
    discovery_id = raw.get("discovery_id", "")
    record = raw.get("record", {})
    error = raw.get("error", {})
    context = raw.get("context", {})

    # Rewrite extracted_to path from results/ to state/records/
    extracted_to = record.get("extracted_to", "")
    if extracted_to:
        extracted_file = f"state/records/{Path(extracted_to).name}"
    else:
        extracted_file = ""

    normalized = {
        "discovery_id": discovery_id,
        "discovered_at": raw.get("discovered_at", ""),
        "discovered_in_run": run_id,
        "mrrc_version": context.get("mrrc_version", ""),
        "test_suite": raw.get("test_suite", ""),
        "test_name": raw.get("test_name", ""),
        "record": {
            "sha256": record.get("sha256", ""),
            "control_number": record.get("control_number", ""),
            "source_dataset": raw.get("source_dataset", ""),
            "source_offset": record.get("offset_bytes", 0),
            "extracted_file": extracted_file,
        },
        "error": {
            "category": error.get("category", ""),
            "message": error.get("message", ""),
            "mrrc_error": error.get("mrrc_error", ""),
        },
    }

    return normalized


def copy_extracted_record(raw: dict) -> bool:
    """Copy an extracted .mrc file from results/ to state/records/.

    Returns True if the file was copied, False if no file to copy or
    the source does not exist.
    """
    record = raw.get("record", {})
    extracted_to = record.get("extracted_to", "")
    if not extracted_to:
        return False

    root = project_root()
    source = root / extracted_to
    if not source.is_file():
        return False

    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    dest = RECORDS_DIR / source.name
    shutil.copy2(source, dest)
    return True


def import_results(input_dir: Path) -> int:
    """Import all JSON results from input_dir into persistent state.

    Returns exit code (0 for success, 1 for error).
    """
    if not input_dir.is_dir():
        print(f"ERROR: Input directory not found: {input_dir}", file=sys.stderr)
        return 1

    print("Importing run results...")

    # Load all JSON files
    loaded = load_json_files(input_dir)
    json_count = len(loaded)

    if json_count == 0:
        print("  JSON files found: 0")
        print("  No results to import.")
        return 0

    # Flatten all discoveries from all files
    all_raw: list[dict] = []
    for _path, data in loaded:
        all_raw.extend(data)

    total_count = len(all_raw)

    # Generate run ID
    run_id = generate_run_id()

    # Process discoveries with dedup
    new_count = 0
    dup_count = 0
    discovery_ids: list[str] = []
    first_context: dict = {}

    for raw in all_raw:
        sha256 = raw.get("record", {}).get("sha256", "")

        # Dedup check
        if sha256 and discovery_exists(sha256):
            dup_count += 1
            continue

        # Capture context from first discovery for the run record
        if not first_context and raw.get("context"):
            first_context = raw["context"]

        # Normalize and save
        normalized = normalize_discovery(raw, run_id)
        copy_extracted_record(raw)
        save_discovery(normalized)
        discovery_ids.append(normalized["discovery_id"])
        new_count += 1

    dup_count = total_count - new_count

    # Print summary
    print(f"  JSON files found: {json_count}")
    print(f"  Total errors found: {total_count}")
    print(f"  New discoveries: {new_count}")
    print(f"  Duplicates skipped: {dup_count}")

    if new_count == 0:
        print("\nNo new discoveries to import.")
        return 0

    # Create and save the run record
    now = datetime.now(timezone.utc).isoformat()
    run_record = {
        "run_id": run_id,
        "started_at": now,
        "completed_at": now,
        "environment": {
            "mrrc_version": first_context.get("mrrc_version", ""),
            "rust_version": first_context.get("rust_version", ""),
            "os": first_context.get("os", ""),
        },
        "results": {
            "total_records": total_count,
            "new_discoveries": new_count,
            "duplicates_skipped": dup_count,
        },
        "discovery_ids": discovery_ids,
    }
    run_path = save_run(run_record)

    print(f"\nUpdated state/discoveries/ ({new_count} new files)")
    print(f"Updated {run_path.relative_to(project_root())}")

    return 0


def list_new_discoveries() -> int:
    """List all discoveries sorted by date.

    Returns exit code (0 for success).
    """
    discoveries = list_discoveries()

    if not discoveries:
        print("No discoveries found.")
        return 0

    # Sort by discovered_at date
    discoveries.sort(key=lambda d: d.get("discovered_at") or "")

    # Column headers
    headers = ("ID", "Date", "Category", "Dataset", "Control#")

    # Compute column widths
    rows = []
    for d in discoveries:
        disc_date = d.get("discovered_at") or ""
        # Truncate to date portion if it's a full timestamp
        if "T" in disc_date:
            disc_date = disc_date.split("T")[0]
        rows.append(
            (
                d.get("discovery_id", ""),
                disc_date,
                d.get("category") or "",
                d.get("source_dataset") or "",
                d.get("control_number") or "",
            )
        )

    col_widths = []
    for i, header in enumerate(headers):
        width = len(header)
        for row in rows:
            width = max(width, len(row[i]))
        col_widths.append(width)

    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)

    print(fmt.format(*headers))
    for row in rows:
        print(fmt.format(*row))

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Import test run results from JSON into persistent YAML state, "
            "or list existing discoveries."
        ),
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        type=Path,
        help="Directory containing JSON discovery files (e.g. results/discoveries/)",
    )
    parser.add_argument(
        "--list-new",
        action="store_true",
        dest="list_new",
        help="List all discoveries sorted by date",
    )
    return parser


def main() -> int:
    """Main entry point. Returns exit code."""
    parser = build_parser()
    args = parser.parse_args()

    if args.list_new:
        return list_new_discoveries()

    if args.input_dir:
        return import_results(args.input_dir)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

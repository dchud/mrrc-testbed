"""Promote a discovery to a committed fixture.

Copies the extracted record from state/records/ into a fixture set under
data/fixtures/, updates (or creates) the fixture manifest with provenance,
and runs validate_fixtures.py to verify.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from mrrc_testbed.config import project_root
from mrrc_testbed.state import RECORDS_DIR, load_discovery

FIXTURES_DIR = project_root() / "data" / "fixtures"


def load_manifest(manifest_path: Path) -> dict:
    """Load an existing manifest.json, or return None if it doesn't exist."""
    if not manifest_path.exists():
        return None
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def control_number_in_manifest(manifest: dict, control_number: str) -> bool:
    """Check if a control number already exists in the manifest records."""
    for entry in manifest.get("records", []):
        if entry.get("control_number") == control_number:
            return True
    return False


def next_index(manifest: dict) -> int:
    """Determine the next record index for the manifest."""
    records = manifest.get("records", [])
    if not records:
        return 0
    return max(entry.get("index", 0) for entry in records) + 1


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="Promote a discovery to a committed fixture.",
    )
    parser.add_argument(
        "discovery_id",
        help="Discovery ID (e.g. disc-2024-02-01-001)",
    )
    parser.add_argument(
        "--fixture",
        required=True,
        help="Fixture set name (e.g. edge_cases, bibliographic)",
    )
    parser.add_argument(
        "--issue",
        default=None,
        help="URL to the mrrc issue (optional)",
    )
    return parser


def main() -> int:
    """Main entry point. Returns exit code."""
    parser = build_parser()
    args = parser.parse_args()

    discovery_id: str = args.discovery_id
    fixture_set: str = args.fixture
    issue_url: str | None = args.issue

    # 1. Load the discovery YAML.
    try:
        discovery = load_discovery(discovery_id)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    record_info = discovery.get("record", {})
    error_info = discovery.get("error", {})
    control_number = record_info.get("control_number")
    source_dataset = record_info.get("source_dataset")
    error_message = error_info.get("message")

    # 2. Find the extracted record file.
    record_path = RECORDS_DIR / f"{discovery_id}.mrc"
    if not record_path.exists():
        print(
            f"ERROR: Record file not found: {record_path}",
            file=sys.stderr,
        )
        return 1

    # 3. Set up fixture directory.
    fixture_dir = FIXTURES_DIR / fixture_set
    if not fixture_dir.exists():
        fixture_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created fixture directory: {fixture_dir}")

    sample_path = fixture_dir / "sample.mrc"
    manifest_path = fixture_dir / "manifest.json"

    # 4. Load or create manifest; check for duplicates.
    manifest = load_manifest(manifest_path)

    if manifest is not None and control_number is not None:
        if control_number_in_manifest(manifest, control_number):
            print(
                f"WARNING: Control number '{control_number}' already exists "
                f"in {fixture_set} manifest. Skipping.",
                file=sys.stderr,
            )
            return 0

    if manifest is None:
        manifest = {
            "source": "Testbed Discovery",
            "source_url": "",
            "download_date": date.today().isoformat(),
            "license": "See source dataset",
            "records": [],
        }

    # 5. Append the record bytes to sample.mrc.
    record_bytes = record_path.read_bytes()
    with open(sample_path, "ab") as f:
        f.write(record_bytes)

    # 6. Add the new entry to the manifest.
    idx = next_index(manifest)
    new_entry = {
        "index": idx,
        "control_number": control_number,
        "source_offset": None,
        "source_file": source_dataset,
        "selection_reason": "edge_case:discovered",
        "notes": error_message,
        "discovered_by": f"testbed discovery {discovery_id}",
        "mrrc_issue": issue_url,
    }
    manifest["records"].append(new_entry)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    # 7. Run validation.
    print(f"Promoted {discovery_id} to {fixture_set} (index {idx})")
    print(f"  Control number: {control_number}")
    print(f"  Source dataset:  {source_dataset}")
    print(f"  Record size:     {len(record_bytes)} bytes")
    if issue_url:
        print(f"  Issue:           {issue_url}")
    print()
    print("Running fixture validation...")

    result = subprocess.run(
        ["uv", "run", "python", "scripts/validate_fixtures.py"],
        cwd=project_root(),
    )

    if result.returncode == 0:
        print("Validation passed.")
    else:
        print(
            "WARNING: Validation returned non-zero exit code.",
            file=sys.stderr,
        )

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

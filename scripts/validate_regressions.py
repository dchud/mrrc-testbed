"""Validate the regression corpus and its manifest.

The regression corpus (`data/regressions/`) holds MARC inputs that once caused
mrrc to mishandle a record. Unlike `data/fixtures/`, these inputs are malformed
by design, so this validator does NOT check structural/parse validity — it only
checks that the manifest and the files on disk agree and that provenance is
complete. See `data/regressions/README.md`.

Checks: manifest<->file sync (both directions), sha256 integrity, required
provenance fields, known `source` kind, well-formed `discovered` date.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REGRESSIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "regressions"

SOURCE_KINDS = {"fuzzer", "synthetic", "reduction", "manual"}

# Required, non-empty per-record provenance fields.
REQUIRED_FIELDS = (
    "filename",
    "sha256",
    "source",
    "mrrc_source",
    "discovered",
    "crash_summary",
    "expected_behavior",
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(regressions_dir: Path) -> tuple[list[str], list[str]]:
    """Validate one regression corpus directory. Returns (warnings, errors)."""
    warnings: list[str] = []
    errors: list[str] = []

    manifest_path = regressions_dir / "manifest.json"
    if not manifest_path.exists():
        errors.append(f"manifest.json not found at {manifest_path}")
        return warnings, errors

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        errors.append(f"Cannot parse manifest.json: {exc}")
        return warnings, errors

    if manifest.get("schema_version") != 1:
        errors.append(
            f"Unsupported schema_version: "
            f"{manifest.get('schema_version')!r} (expected 1)"
        )

    records = manifest.get("records")
    if not isinstance(records, list):
        errors.append("manifest 'records' must be a list")
        return warnings, errors

    disk_files = {p.name for p in regressions_dir.glob("*.mrc")}
    manifest_files: set[str] = set()
    seen_sha: dict[str, str] = {}  # sha256 -> first filename seen

    for i, entry in enumerate(records):
        label = f"record[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{label}: not an object")
            continue

        filename = entry.get("filename")
        if filename:
            label = filename

        # Required fields present and non-empty.
        for field in REQUIRED_FIELDS:
            if not entry.get(field):
                errors.append(f"{label}: missing required field '{field}'")

        # Known source kind.
        source = entry.get("source")
        if source is not None and source not in SOURCE_KINDS:
            errors.append(
                f"{label}: unknown source '{source}' "
                f"(expected one of {sorted(SOURCE_KINDS)})"
            )

        # Well-formed discovered date.
        discovered = entry.get("discovered")
        if discovered and not DATE_RE.match(str(discovered)):
            errors.append(
                f"{label}: 'discovered' must be YYYY-MM-DD, got {discovered!r}"
            )

        if not filename:
            continue
        if filename in manifest_files:
            errors.append(f"{label}: duplicate manifest entry for '{filename}'")
        manifest_files.add(filename)

        # File must exist on disk.
        file_path = regressions_dir / filename
        if not file_path.exists():
            errors.append(f"{label}: referenced file not found on disk")
            continue

        # SHA-256 integrity.
        expected = entry.get("sha256")
        actual = _sha256(file_path)
        if expected and expected != actual:
            errors.append(
                f"{label}: sha256 mismatch (manifest {expected}, actual {actual})"
            )

        # Duplicate content across entries.
        if actual in seen_sha:
            warnings.append(
                f"{label}: identical bytes to '{seen_sha[actual]}' (duplicate input)"
            )
        else:
            seen_sha[actual] = filename

    # Untracked files: on disk but absent from the manifest.
    for name in sorted(disk_files - manifest_files):
        errors.append(f"{name}: present on disk but has no manifest entry")

    return warnings, errors


def main() -> int:
    """Validate the committed regression corpus under data/regressions/."""
    parser = argparse.ArgumentParser(description="Validate the regression corpus")
    parser.add_argument(
        "--strict", action="store_true", help="Exit non-zero on any warning"
    )
    args = parser.parse_args()

    if not REGRESSIONS_DIR.is_dir():
        print(f"Regression corpus directory not found: {REGRESSIONS_DIR}")
        return 1

    rel = REGRESSIONS_DIR.relative_to(REGRESSIONS_DIR.parent.parent)
    print(f"Validating {rel}/...")

    warnings, errors = validate(REGRESSIONS_DIR)

    mrc_count = len(list(REGRESSIONS_DIR.glob("*.mrc")))
    print(f"  {mrc_count} regression input(s)")

    for w in warnings:
        print(f"  WARNING: {w}")
    for e in errors:
        print(f"  ERROR: {e}")

    if errors:
        print(f"Status: FAILED ({len(errors)} error(s))")
        return 1
    if warnings and args.strict:
        print(f"Status: FAILED ({len(warnings)} warning(s) in strict mode)")
        return 1
    if warnings:
        print(f"Status: OK ({len(warnings)} warning(s))")
        return 0
    print("Status: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

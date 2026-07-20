"""Add a MARC input to the regression corpus (data/regressions/).

Copies the input to the next crash_NNNN.mrc, computes its SHA-256, and appends a
manifest.json entry. Idempotent: if an input with identical bytes is already
present, it is not added again. See data/regressions/README.md for the schema
and the licensing guardrail (never commit verbatim externally-licensed bytes).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

REGRESSIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "regressions"

SOURCE_KINDS = ("fuzzer", "synthetic", "reduction", "manual")
DEFAULT_EXPECTED = "no panic; Err acceptable"

_CRASH_RE = re.compile(r"crash_(\d+)\.mrc$")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _next_filename(existing: set[str]) -> str:
    """Return the next crash_NNNN.mrc name given the names already in use."""
    max_n = 0
    for name in existing:
        m = _CRASH_RE.match(name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"crash_{max_n + 1:04d}.mrc"


def add_regression(
    regressions_dir: Path,
    input_path: Path,
    *,
    source: str,
    mrrc_source: str,
    crash_summary: str,
    expected_behavior: str = DEFAULT_EXPECTED,
    origin: str | None = None,
    fuzz_target: str | None = None,
    upstream_issue: str | None = None,
    notes: str | None = None,
    discovered: str | None = None,
) -> tuple[str, dict, bool]:
    """Copy input into the corpus and append a manifest entry.

    Returns (filename, entry, added). `added` is False when an input with
    identical bytes is already present, in which case nothing is written.
    """
    data = input_path.read_bytes()
    sha = _sha256(data)

    manifest_path = regressions_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.setdefault("records", [])

    # Idempotence: identical bytes already captured.
    for existing in records:
        if existing.get("sha256") == sha:
            return existing.get("filename", "?"), existing, False

    on_disk = {p.name for p in regressions_dir.glob("*.mrc")}
    in_manifest = {r.get("filename") for r in records if r.get("filename")}
    filename = _next_filename(on_disk | in_manifest)

    if discovered is None:
        discovered = datetime.date.today().isoformat()

    entry = {
        "filename": filename,
        "sha256": sha,
        "source": source,
        "origin": origin,
        "fuzz_target": fuzz_target,
        "mrrc_source": mrrc_source,
        "upstream_issue": upstream_issue,
        "discovered": discovered,
        "crash_summary": crash_summary,
        "expected_behavior": expected_behavior,
        "notes": notes,
    }

    (regressions_dir / filename).write_bytes(data)
    records.append(entry)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return filename, entry, True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add a MARC input to the regression corpus"
    )
    parser.add_argument("input", type=Path, help="Path to the input file to capture")
    parser.add_argument(
        "--source",
        choices=SOURCE_KINDS,
        default="fuzzer",
        help="How the input was produced (default: fuzzer)",
    )
    parser.add_argument(
        "--mrrc-source",
        required=True,
        help="mrrc version or commit where the pathology was observed",
    )
    parser.add_argument(
        "--summary",
        required=True,
        dest="crash_summary",
        help="One-line description of the defect",
    )
    parser.add_argument(
        "--expected",
        dest="expected_behavior",
        default=DEFAULT_EXPECTED,
        help=f"What mrrc must now do (default: {DEFAULT_EXPECTED!r})",
    )
    parser.add_argument(
        "--origin", help="External corpus it came from (marc4j, pymarc, ...)"
    )
    parser.add_argument(
        "--target", dest="fuzz_target", help="Fuzz target that found it"
    )
    parser.add_argument(
        "--issue", dest="upstream_issue", help="Upstream issue, e.g. mrrc#93"
    )
    parser.add_argument("--notes", help="Free-form notes")
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"Input file not found: {args.input}")
        return 1
    if not REGRESSIONS_DIR.is_dir():
        print(f"Regression corpus directory not found: {REGRESSIONS_DIR}")
        return 1

    filename, entry, added = add_regression(
        REGRESSIONS_DIR,
        args.input,
        source=args.source,
        mrrc_source=args.mrrc_source,
        crash_summary=args.crash_summary,
        expected_behavior=args.expected_behavior,
        origin=args.origin,
        fuzz_target=args.fuzz_target,
        upstream_issue=args.upstream_issue,
        notes=args.notes,
    )

    if not added:
        print(f"Already present as {filename} (identical bytes); nothing added.")
        return 0

    print(f"Added {filename}:")
    print(json.dumps(entry, indent=2))

    if args.source == "reduction":
        print()
        print("Reminder: a 'reduction' must be a license-clean minimization —")
        print("it must NOT carry the upstream corpus's copyrightable bytes.")

    print()
    print("Next: verify with")
    print("  just validate")
    print("  cargo test --test regressions regression_inputs_no_panic")
    return 0


if __name__ == "__main__":
    sys.exit(main())

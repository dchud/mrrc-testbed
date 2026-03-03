"""Check test failures against the known-failures allow-list.

Modes:
    --list                          Show all known failures with reasons
    --runner cargo|pytest           Check failures (with --failures) against allow-list
      --failures "name1,name2"
    --update                        Remove stale entries (no longer failing)
    --add TEST_ID                   Add a new entry (requires --runner and --reason)
      --runner cargo|pytest
      --reason "description"
      [--mrrc-source released|local|any]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import yaml

from mrrc_testbed.config import project_root

KNOWN_FAILURES_PATH = project_root() / "state" / "known-failures.yaml"
CARGO_TOML_PATH = project_root() / "Cargo.toml"


def load_known_failures() -> dict:
    """Load the known-failures YAML file."""
    if not KNOWN_FAILURES_PATH.exists():
        return {"failures": []}
    return yaml.safe_load(KNOWN_FAILURES_PATH.read_text()) or {"failures": []}


def save_known_failures(data: dict) -> None:
    """Write the known-failures YAML file with header comment."""
    header = (
        "# Known test failures in mrrc-testbed.\n"
        "#\n"
        "# Tests listed here fail due to known upstream (mrrc) issues.\n"
        "# Git hooks and CI use this file to distinguish expected failures\n"
        "# from regressions. Managed via: just check-known-failures\n"
        "#\n"
        '# mrrc_source: "released", "local", or "any"\n'
        "\n"
    )
    body = yaml.dump(data, default_flow_style=False, sort_keys=False)
    KNOWN_FAILURES_PATH.write_text(header + body)


def detect_mrrc_source() -> str:
    """Auto-detect mrrc source from Cargo.toml."""
    text = CARGO_TOML_PATH.read_text()
    if "[patch.crates-io]" in text:
        return "local"
    return "released"


def get_known_for_runner(data: dict, runner: str, mrrc_source: str) -> dict[str, dict]:
    """Return known failures for a runner, filtered by mrrc_source scope."""
    result = {}
    for entry in data.get("failures", []):
        if entry["runner"] != runner:
            continue
        scope = entry.get("mrrc_source", "any")
        if scope == "any" or scope == mrrc_source:
            result[entry["test_id"]] = entry
    return result


def cmd_list(data: dict) -> int:
    """Show all known failures."""
    failures = data.get("failures", [])
    if not failures:
        print("No known failures.")
        return 0

    print("=== Known Failures ===")
    print()
    for entry in failures:
        scope = entry.get("mrrc_source", "any")
        print(f"  [{entry['runner']}] {entry['test_id']} (mrrc_source: {scope})")
        print(f"    {entry['reason']}")
        print(f"    added: {entry.get('added', 'unknown')}")
        print()
    return 0


def cmd_check(data: dict, runner: str, failures_str: str) -> int:
    """Check failures against the allow-list. Exit 0 if all known, 1 if unexpected."""
    mrrc_source = detect_mrrc_source()
    failure_names = [f.strip() for f in failures_str.split(",") if f.strip()]

    if not failure_names:
        return 0

    known = get_known_for_runner(data, runner, mrrc_source)

    expected = []
    unexpected = []
    for name in failure_names:
        if name in known:
            expected.append((name, known[name]))
        else:
            unexpected.append(name)

    print("=== Known Failures Check ===")
    print(f"mrrc source: {mrrc_source}")
    print()

    if expected:
        print("Known (expected):")
        for name, entry in expected:
            print(f"  [{runner}] {name} — {entry['reason']}")
        print()

    if unexpected:
        print("Unexpected failures (BLOCKING):")
        for name in unexpected:
            print(f"  [{runner}] {name}")
        print()
        print(f"To add:  just add-known-failure {runner} <test_id> \"reason here\"")
        return 1

    print("No unexpected failures. OK")
    return 0


def cmd_update(data: dict) -> int:
    """Remove stale entries (listed but no longer failing).

    This is a safe operation — it only tightens the allow-list.
    We can't auto-detect staleness without running tests, so this
    is typically called after a test run.
    """
    # Without test results, we just report what's in the file
    # The actual staleness check happens when called from `just check-known-failures`
    # which pipes in test results
    failures = data.get("failures", [])
    if not failures:
        print("No known failures to update.")
        return 0

    print("=== Known Failures (review for staleness) ===")
    print()
    mrrc_source = detect_mrrc_source()
    print(f"mrrc source: {mrrc_source}")
    print()
    for entry in failures:
        scope = entry.get("mrrc_source", "any")
        active = scope == "any" or scope == mrrc_source
        status = "ACTIVE" if active else "not applicable (different mrrc_source)"
        print(f"  [{entry['runner']}] {entry['test_id']} — {status}")
        print(f"    {entry['reason']}")
    print()
    print("To remove an entry, edit state/known-failures.yaml directly")
    print("or run tests and use 'just check-known-failures' to identify stale entries.")
    return 0


def cmd_update_from_results(data: dict, runner: str, passing_str: str) -> int:
    """Remove entries that are now passing."""
    passing_names = [f.strip() for f in passing_str.split(",") if f.strip()]
    if not passing_names:
        return 0

    mrrc_source = detect_mrrc_source()
    removed = []

    new_failures = []
    for entry in data.get("failures", []):
        if entry["runner"] == runner and entry["test_id"] in passing_names:
            scope = entry.get("mrrc_source", "any")
            if scope == "any" or scope == mrrc_source:
                removed.append(entry)
                continue
        new_failures.append(entry)

    if removed:
        data["failures"] = new_failures
        save_known_failures(data)
        print(f"Removed {len(removed)} stale entries:")
        for entry in removed:
            print(f"  [{entry['runner']}] {entry['test_id']} — was: {entry['reason']}")
    else:
        print("No stale entries found.")

    return 0


def cmd_add(
    data: dict,
    test_id: str,
    runner: str,
    reason: str,
    mrrc_source: str | None,
) -> int:
    """Add a new entry to the known-failures file."""
    if mrrc_source is None:
        mrrc_source = detect_mrrc_source()

    # Check for duplicate
    for entry in data.get("failures", []):
        if entry["test_id"] == test_id and entry["runner"] == runner:
            print(f"Entry already exists: [{runner}] {test_id}")
            print(f"  {entry['reason']}")
            return 1

    new_entry = {
        "test_id": test_id,
        "runner": runner,
        "reason": reason,
        "added": str(date.today()),
        "mrrc_source": mrrc_source,
    }
    data.setdefault("failures", []).append(new_entry)
    save_known_failures(data)

    print(f"Added: [{runner}] {test_id} (mrrc_source: {mrrc_source})")
    print(f"  {reason}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check test failures against the known-failures allow-list.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="Show all known failures")
    group.add_argument(
        "--check",
        action="store_true",
        help="Check failures against allow-list (requires --runner, --failures)",
    )
    group.add_argument(
        "--update",
        action="store_true",
        help="Review/remove stale entries",
    )
    group.add_argument(
        "--update-from-results",
        action="store_true",
        help="Remove entries that are now passing (requires --runner, --passing)",
    )
    group.add_argument(
        "--add",
        metavar="TEST_ID",
        help="Add a new known failure entry",
    )

    parser.add_argument(
        "--runner",
        choices=["cargo", "pytest"],
        help="Test runner (cargo or pytest)",
    )
    parser.add_argument(
        "--failures",
        help="Comma-separated list of failed test names",
    )
    parser.add_argument(
        "--passing",
        help="Comma-separated list of passing test names (for --update-from-results)",
    )
    parser.add_argument(
        "--reason",
        help="Reason for the known failure (for --add)",
    )
    parser.add_argument(
        "--mrrc-source",
        choices=["released", "local", "any"],
        help="Override auto-detected mrrc source scope (for --add or --check)",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    data = load_known_failures()

    if args.list:
        return cmd_list(data)

    if args.check:
        if not args.runner or args.failures is None:
            parser.error("--check requires --runner and --failures")
        return cmd_check(data, args.runner, args.failures)

    if args.update:
        return cmd_update(data)

    if args.update_from_results:
        if not args.runner or args.passing is None:
            parser.error("--update-from-results requires --runner and --passing")
        return cmd_update_from_results(data, args.runner, args.passing)

    if args.add:
        if not args.runner or not args.reason:
            parser.error("--add requires --runner and --reason")
        return cmd_add(data, args.add, args.runner, args.reason, args.mrrc_source)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

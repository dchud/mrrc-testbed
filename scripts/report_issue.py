"""Create a GitHub issue on dchud/mrrc from a testbed discovery.

Reads the discovery YAML and assembles a structured issue with error details,
source dataset, reproduction info, and a link back to the testbed discovery.

Requires the gh CLI (https://cli.github.com/) installed and authenticated.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from mrrc_testbed.state import load_discovery

REPO = "dchud/mrrc"


def check_gh() -> bool:
    """Verify gh CLI is installed and authenticated."""
    if not shutil.which("gh"):
        print(
            "ERROR: gh CLI not found. Install from https://cli.github.com/",
            file=sys.stderr,
        )
        return False

    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            "ERROR: gh not authenticated. Run 'gh auth login' first.",
            file=sys.stderr,
        )
        return False

    return True


def build_issue(discovery: dict) -> tuple[str, str]:
    """Build issue title and body from a discovery dict."""
    error = discovery.get("error", {})
    record = discovery.get("record", {})
    discovery_id = discovery.get("discovery_id", "unknown")

    category = error.get("category", "unknown")
    message = error.get("message", "")

    # Title: truncate sensibly
    title = f"[testbed] {category}: {message}"
    if len(title) > 120:
        title = title[:117] + "..."

    body_parts = [
        "## Testbed Discovery",
        "",
        f"**Discovery ID:** `{discovery_id}`",
        f"**Discovered:** {discovery.get('discovered_at', 'unknown')}",
        f"**mrrc version:** {discovery.get('mrrc_version', 'unknown')}",
        "",
        "## Error",
        "",
        f"**Category:** `{category}`",
        f"**Message:** `{message}`",
    ]

    mrrc_error = error.get("mrrc_error")
    if mrrc_error and mrrc_error != message:
        body_parts.append(f"**Raw mrrc error:** `{mrrc_error}`")

    body_parts.extend([
        "",
        "## Source Record",
        "",
        f"- **Dataset:** {record.get('source_dataset', 'unknown')}",
        f"- **Control number:** `{record.get('control_number', 'unknown')}`",
        f"- **Byte offset:** {record.get('source_offset', 'unknown')}",
        f"- **SHA-256:** `{record.get('sha256', 'unknown')}`",
    ])

    extracted = record.get("extracted_file")
    if extracted:
        body_parts.append(f"- **Extracted file:** `{extracted}`")

    body_parts.extend([
        "",
        "## Reproduction",
        "",
        "From the [mrrc-testbed](https://github.com/dchud/mrrc-testbed):",
        "",
        "```bash",
        f"just show {discovery_id}",
        "```",
        "",
        "The extracted `.mrc` file is committed in the testbed"
        f" at `{extracted or 'state/records/'}`.",
    ])

    body = "\n".join(body_parts)
    return title, body


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: report_issue.py DISCOVERY_ID", file=sys.stderr)
        return 1

    discovery_id = sys.argv[1]

    if not check_gh():
        return 1

    try:
        discovery = load_discovery(discovery_id)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    title, body = build_issue(discovery)

    # Try to create with label, fall back without if label doesn't exist
    cmd = [
        "gh", "issue", "create",
        "--repo", REPO,
        "--title", title,
        "--body", body,
    ]

    # Try with label first
    result = subprocess.run(
        cmd + ["--label", "testbed-discovery"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and "label" in result.stderr.lower():
        # Label doesn't exist, create without it
        result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ERROR: gh issue create failed:\n{result.stderr}", file=sys.stderr)
        return 1

    issue_url = result.stdout.strip()
    print(f"Created issue: {issue_url}")
    print("\nTo promote this discovery with the issue link:")
    print(f"  just promote {discovery_id} edge_cases --issue={issue_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

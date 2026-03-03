"""Switch mrrc dependency source between local checkout and released packages.

Subcommands:
    local PATH   — patch Cargo.toml and install Python bindings from local checkout
    released     — revert to released mrrc from crates.io / PyPI
    status       — show current mrrc dependency state (no changes)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from mrrc_testbed.config import project_root

WORKSPACE_CARGO = project_root() / "Cargo.toml"


def read_cargo_toml() -> str:
    return WORKSPACE_CARGO.read_text()


def has_patch_section(text: str) -> bool:
    return "[patch.crates-io]" in text


def add_patch_section(text: str, mrrc_path: str) -> str:
    """Append a [patch.crates-io] section pointing mrrc at a local path."""
    if has_patch_section(text):
        text = remove_patch_section(text)
    return text.rstrip() + f'\n\n[patch.crates-io]\nmrrc = {{ path = "{mrrc_path}" }}\n'


def remove_patch_section(text: str) -> str:
    """Remove the [patch.crates-io] section and everything below it."""
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    in_patch = False
    for line in lines:
        if line.strip() == "[patch.crates-io]":
            in_patch = True
            continue
        if in_patch:
            # A new section header ends the patch section
            if line.strip().startswith("[") and line.strip() != "[patch.crates-io]":
                in_patch = False
                result.append(line)
            continue
        result.append(line)
    # Strip trailing blank lines, add single newline
    return "".join(result).rstrip() + "\n"


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=project_root(), check=check, capture_output=True, text=True,
    )


def cmd_local(path_str: str) -> int:
    mrrc_path = Path(path_str).resolve()
    if not mrrc_path.is_dir():
        print(f"ERROR: Not a directory: {mrrc_path}", file=sys.stderr)
        return 1
    if not (mrrc_path / "Cargo.toml").exists():
        print(f"ERROR: No Cargo.toml found in {mrrc_path}", file=sys.stderr)
        return 1

    # 1. Patch workspace Cargo.toml
    text = read_cargo_toml()
    text = add_patch_section(text, str(mrrc_path))
    WORKSPACE_CARGO.write_text(text)
    print(f"Patched {WORKSPACE_CARGO.relative_to(project_root())} -> {mrrc_path}")

    # 2. Install Python bindings from local checkout
    print("Installing Python bindings from local checkout...")
    result = run(["uv", "pip", "install", "-e", str(mrrc_path)], check=False)
    if result.returncode != 0:
        print(f"WARNING: uv pip install failed:\n{result.stderr}", file=sys.stderr)
    else:
        print("Python bindings installed.")

    # 3. Verify Rust patch resolves
    print("Verifying Rust dependency resolves...")
    result = run(["cargo", "check"], check=False)
    if result.returncode != 0:
        print(f"ERROR: cargo check failed:\n{result.stderr}", file=sys.stderr)
        return 1
    print("Rust dependency resolved.")

    # 4. Print status
    print()
    print(f"mrrc source: local ({mrrc_path})")
    _print_versions()
    print()
    print("Tip: Run 'just check-known-failures' to verify state/known-failures.yaml")
    return 0


def cmd_released() -> int:
    text = read_cargo_toml()
    if not has_patch_section(text):
        print("No [patch.crates-io] section found — already using released mrrc.")
    else:
        text = remove_patch_section(text)
        WORKSPACE_CARGO.write_text(text)
        rel = WORKSPACE_CARGO.relative_to(project_root())
        print(f"Removed [patch.crates-io] from {rel}")

    # Restore Python from pyproject.toml pins
    print("Restoring Python dependencies from pyproject.toml...")
    result = run(["uv", "sync"], check=False)
    if result.returncode != 0:
        print(f"WARNING: uv sync failed:\n{result.stderr}", file=sys.stderr)
    else:
        print("Python dependencies restored.")

    # Verify Rust resolves
    print("Verifying Rust dependency resolves...")
    result = run(["cargo", "check"], check=False)
    if result.returncode != 0:
        print(f"ERROR: cargo check failed:\n{result.stderr}", file=sys.stderr)
        return 1
    print("Rust dependency resolved.")

    print()
    print("mrrc source: released (crates.io / PyPI)")
    _print_versions()
    print()
    print("Tip: Run 'just check-known-failures' to verify state/known-failures.yaml")
    return 0


def cmd_status() -> int:
    text = read_cargo_toml()
    if has_patch_section(text):
        # Extract path from the patch section
        for line in text.splitlines():
            if line.strip().startswith("mrrc") and "path" in line:
                print("mrrc source: local (patched)")
                print(f"  Cargo.toml patch: {line.strip()}")
                break
    else:
        print("mrrc source: released (crates.io / PyPI)")

    _print_versions()
    return 0


def _print_versions() -> None:
    """Print Rust and Python mrrc version info."""
    # Rust version via cargo tree
    result = run(["cargo", "tree", "-p", "mrrc", "--depth=0"], check=False)
    if result.returncode == 0:
        rust_ver = result.stdout.strip()
        print(f"  Rust:   {rust_ver}")
    else:
        print("  Rust:   (could not determine)")

    # Python version via uv pip show
    result = run(["uv", "pip", "show", "mrrc"], check=False)
    if result.returncode == 0:
        version = ""
        location = ""
        for line in result.stdout.splitlines():
            if line.startswith("Version:"):
                version = line.split(":", 1)[1].strip()
            if line.startswith("Location:"):
                location = line.split(":", 1)[1].strip()
        py_info = f"mrrc {version}"
        if location:
            py_info += f" ({location})"
        print(f"  Python: {py_info}")
    else:
        print("  Python: (could not determine)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Switch mrrc dependency source between local and released.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    local_p = sub.add_parser("local", help="Point at a local mrrc checkout")
    local_p.add_argument("path", help="Path to local mrrc checkout")

    sub.add_parser("released", help="Revert to released mrrc")
    sub.add_parser("status", help="Show current mrrc dependency state")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "local":
        return cmd_local(args.path)
    elif args.command == "released":
        return cmd_released()
    elif args.command == "status":
        return cmd_status()
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

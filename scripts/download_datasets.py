"""CLI script for downloading and managing mrrc-testbed datasets."""

import argparse
import sys

from mrrc_testbed.config import project_root
from mrrc_testbed.download import (
    DATASET_REGISTRY,
    download_dataset,
    list_datasets,
    verify_download,
)


def print_dataset_table() -> None:
    """Print a formatted table of available datasets."""
    datasets = list_datasets()
    # Column headers
    headers = ("Name", "Description", "Size", "Records")
    # Determine column widths
    name_w = max(len(headers[0]), *(len(d["name"]) for d in datasets))
    desc_w = max(len(headers[1]), *(len(d["description"]) for d in datasets))
    size_w = max(len(headers[2]), *(len(d["approx_size"]) for d in datasets))
    recs_w = max(len(headers[3]), *(len(d["approx_records"]) for d in datasets))

    row_fmt = f"  {{:<{name_w}}}  {{:<{desc_w}}}  {{:<{size_w}}}  {{:<{recs_w}}}"
    header_line = row_fmt.format(*headers)
    separator = "  " + "  ".join(
        ["-" * name_w, "-" * desc_w, "-" * size_w, "-" * recs_w]
    )

    print("Available datasets:\n")
    print(header_line)
    print(separator)
    for d in datasets:
        print(
            row_fmt.format(
                d["name"], d["description"], d["approx_size"], d["approx_records"]
            )
        )
    print()


def download_one(name: str) -> int:
    """Attempt to download a single dataset. Returns exit code."""
    if name not in DATASET_REGISTRY:
        print(f"ERROR: Unknown dataset '{name}'.")
        print(f"Available datasets: {', '.join(DATASET_REGISTRY)}")
        return 1

    print(f"Downloading {name}...")
    try:
        download_dataset(name)
    except NotImplementedError as e:
        print(f"  {e}")
        return 1
    except Exception as e:
        print(f"ERROR: Download failed: {e}", file=sys.stderr)
        return 1

    print("  Done. Verifying...")
    if verify_download(name):
        downloads_dir = project_root() / "data" / "downloads" / name
        mrc_files = list(downloads_dir.glob("*.mrc"))
        total_size = sum(f.stat().st_size for f in mrc_files)
        size_mb = total_size / (1024 * 1024)
        print(f"  Verified: {len(mrc_files)} .mrc file(s), {size_mb:.1f} MB")
    else:
        print("  WARNING: Verification failed — no .mrc files found.")
        return 1

    return 0


def download_all() -> int:
    """Attempt to download all primary datasets. Returns exit code."""
    exit_code = 0
    for name in DATASET_REGISTRY:
        result = download_one(name)
        if result != 0:
            exit_code = result
        print()
    return exit_code


def verify_downloads() -> None:
    """Check which datasets exist locally and contain .mrc files."""
    print("Verifying downloads...\n")
    downloads_dir = project_root() / "data" / "downloads"

    for name in DATASET_REGISTRY:
        dataset_dir = downloads_dir / name
        if not dataset_dir.is_dir():
            print(f"  {name}: NOT FOUND ({dataset_dir})")
            continue
        mrc_files = list(dataset_dir.glob("*.mrc"))
        if mrc_files:
            total_size = sum(f.stat().st_size for f in mrc_files)
            size_mb = total_size / (1024 * 1024)
            print(
                f"  {name}: OK ({len(mrc_files)} .mrc file(s), {size_mb:.1f} MB)"
            )
        else:
            print(f"  {name}: EMPTY (directory exists but no .mrc files)")

    print()


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="Download and manage mrrc-testbed datasets.",
    )
    parser.add_argument(
        "dataset",
        nargs="?",
        help="Name of dataset to download (e.g. watson, ia_lendable)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_datasets",
        help="List available datasets with descriptions and sizes",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="download_all",
        help="Download all primary datasets",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing downloads",
    )
    return parser


def main() -> int:
    """Main entry point. Returns exit code."""
    parser = build_parser()
    args = parser.parse_args()

    # Dispatch based on arguments
    if args.list_datasets:
        print_dataset_table()
        return 0

    if args.verify:
        verify_downloads()
        return 0

    if args.download_all:
        return download_all()

    if args.dataset:
        return download_one(args.dataset)

    # No arguments provided
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

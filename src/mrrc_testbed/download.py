"""Dataset download and verification utilities.

Handles downloading MARC datasets from various public sources. Uses only
stdlib (urllib) to avoid adding network dependencies to the project.
"""

import io
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from mrrc_testbed.config import project_root

DOWNLOADS_DIR = project_root() / "data" / "downloads"

# Direct download URLs for datasets that support automated retrieval.
# Watson: GitHub repo archive containing zipped .mrc files.
# IA Lendable: archive.org bulk download.
# LOC datasets: require manual download from LOC CDS.
DATASET_REGISTRY: dict[str, dict[str, Any]] = {
    "watson": {
        "url": "https://github.com/Thomas-J-Watson-Library/Marc-Record-Sets",
        "download_url": (
            "https://github.com/Thomas-J-Watson-Library/"
            "Marc-Record-Sets/archive/refs/heads/master.zip"
        ),
        "download_method": "github_zip",
        "description": "Watson Library (Met)",
        "approx_size": "~8MB",
        "approx_records": "~10K",
    },
    "ia_lendable": {
        "url": "https://archive.org/details/marc_lendable_books",
        "download_url": (
            "https://archive.org/download/marc_lendable_books/"
            "all_meta.mrc"
        ),
        "download_method": "direct",
        "description": "Internet Archive Lendable",
        "approx_size": "~1GB",
        "approx_records": "~1.4M",
    },
    "loc_books": {
        "url": "https://www.loc.gov/cds/products/marcDist.php",
        "download_url": None,
        "download_method": "manual",
        "description": "LOC Books All",
        "approx_size": "~15GB",
        "approx_records": "~25M",
    },
    "loc_names": {
        "url": "https://www.loc.gov/cds/products/marcDist.php",
        "download_url": None,
        "download_method": "manual",
        "description": "LOC Name Authority",
        "approx_size": "~5GB",
        "approx_records": "~10M",
    },
    "loc_subjects": {
        "url": "https://www.loc.gov/cds/products/marcDist.php",
        "download_url": None,
        "download_method": "manual",
        "description": "LOC Subject Authority",
        "approx_size": "~200MB",
        "approx_records": "~400K",
    },
}


def _download_url(url: str, desc: str) -> bytes:
    """Download a URL with progress indication. Returns bytes."""
    print(f"  Downloading {desc}...")
    print(f"  URL: {url}")
    req = urllib.request.Request(
        url, headers={"User-Agent": "mrrc-testbed/0.1"}
    )
    with urllib.request.urlopen(req) as resp:
        total = resp.headers.get("Content-Length")
        if total:
            total = int(total)
            print(f"  Size: {total / (1024 * 1024):.1f} MB")
        data = resp.read()
        print(f"  Downloaded: {len(data) / (1024 * 1024):.1f} MB")
    return data


def _download_github_zip(info: dict, target_dir: Path) -> Path:
    """Download a GitHub repo archive, extract .mrc files from inner zips."""
    target_dir.mkdir(parents=True, exist_ok=True)

    data = _download_url(info["download_url"], info["description"])
    repo_zip = zipfile.ZipFile(io.BytesIO(data))

    # The repo archive contains a top-level directory. Inside it are zip files
    # that each contain .mrc, .mrk, and .rec files. Extract all .mrc files.
    mrc_count = 0
    total_bytes = 0

    for name in repo_zip.namelist():
        if name.endswith(".zip"):
            print(f"  Extracting {name}...")
            inner_data = repo_zip.read(name)
            try:
                inner_zip = zipfile.ZipFile(io.BytesIO(inner_data))
            except zipfile.BadZipFile:
                print(f"    Skipping (bad zip): {name}")
                continue
            for inner_name in inner_zip.namelist():
                if inner_name.lower().endswith(".mrc"):
                    content = inner_zip.read(inner_name)
                    out_name = Path(inner_name).name
                    out_path = target_dir / out_name
                    out_path.write_bytes(content)
                    mrc_count += 1
                    total_bytes += len(content)

    print(f"  Extracted {mrc_count} .mrc files ({total_bytes / 1024:.0f} KB)")
    return target_dir


def _download_direct(info: dict, target_dir: Path) -> Path:
    """Download a single file directly."""
    target_dir.mkdir(parents=True, exist_ok=True)

    url = info["download_url"]
    filename = url.rsplit("/", 1)[-1]
    target_path = target_dir / filename

    if target_path.exists():
        size_mb = target_path.stat().st_size / (1024 * 1024)
        print(f"  Already exists: {target_path} ({size_mb:.1f} MB)")
        return target_path

    data = _download_url(url, info["description"])
    target_path.write_bytes(data)
    return target_path


def download_dataset(name: str, target_dir: Path | None = None) -> Path:
    """Download a dataset by name.

    Args:
        name: Dataset short name (e.g. 'watson', 'ia_lendable').
        target_dir: Override download directory. Defaults to data/downloads/{name}/.

    Returns:
        Path to the download directory containing .mrc files.

    Raises:
        ValueError: If the dataset name is unknown.
        NotImplementedError: If the dataset requires manual download.
    """
    if name not in DATASET_REGISTRY:
        raise ValueError(
            f"Unknown dataset '{name}'. "
            f"Available: {', '.join(DATASET_REGISTRY)}"
        )

    info = DATASET_REGISTRY[name]
    method = info["download_method"]

    if target_dir is None:
        target_dir = DOWNLOADS_DIR / name

    if method == "github_zip":
        return _download_github_zip(info, target_dir)
    elif method == "direct":
        return _download_direct(info, target_dir)
    elif method == "manual":
        raise NotImplementedError(
            f"Dataset '{name}' requires manual download.\n"
            f"  Visit: {info['url']}\n"
            f"  Place .mrc files in: {target_dir}/"
        )
    else:
        raise ValueError(f"Unknown download method: {method}")


def verify_download(name: str, target_dir: Path | None = None) -> bool:
    """Check if a dataset has been downloaded and contains .mrc files.

    Returns True if the dataset directory exists and contains at least one
    .mrc file.
    """
    if target_dir is None:
        target_dir = DOWNLOADS_DIR / name

    if not target_dir.is_dir():
        return False

    mrc_files = list(target_dir.glob("*.mrc"))
    return len(mrc_files) > 0


def list_datasets() -> list[dict[str, Any]]:
    """Return a list of dataset info dicts for display."""
    return [
        {"name": name, **{k: v for k, v in info.items()
                          if k not in ("download_url", "download_method")}}
        for name, info in DATASET_REGISTRY.items()
    ]

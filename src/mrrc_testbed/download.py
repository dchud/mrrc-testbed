from pathlib import Path
from typing import Any

DATASET_REGISTRY: dict[str, dict[str, Any]] = {
    "watson": {
        "url": "https://github.com/Thomas-J-Watson-Library/Marc-Record-Sets",
        "description": "Watson Library (Met)",
        "approx_size": "~100MB",
        "approx_records": "~200K",
    },
    "ia_lendable": {
        "url": "https://archive.org/details/marc_lendable_books",
        "description": "Internet Archive Lendable",
        "approx_size": "~1GB",
        "approx_records": "~1.4M",
    },
    "loc_books": {
        "url": "https://www.loc.gov/cds/products/marcDist.php",
        "description": "LOC Books All",
        "approx_size": "~15GB",
        "approx_records": "~25M",
    },
    "loc_names": {
        "url": "https://www.loc.gov/cds/products/marcDist.php",
        "description": "LOC Name Authority",
        "approx_size": "~5GB",
        "approx_records": "~10M",
    },
    "loc_subjects": {
        "url": "https://www.loc.gov/cds/products/marcDist.php",
        "description": "LOC Subject Authority",
        "approx_size": "~200MB",
        "approx_records": "~400K",
    },
}


def download_dataset(name: str, target_dir: Path) -> Path:
    raise NotImplementedError(f"Dataset downloading not yet implemented for '{name}'")


def verify_download(name: str, target_dir: Path) -> bool:
    raise NotImplementedError(
        f"Download verification not yet implemented for '{name}'"
    )


def list_datasets() -> list[dict[str, Any]]:
    return [
        {"name": name, **info}
        for name, info in DATASET_REGISTRY.items()
    ]

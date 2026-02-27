from pathlib import Path

import yaml

from mrrc_testbed.config import project_root

STATE_DIR = project_root() / "state"
DISCOVERIES_DIR = STATE_DIR / "discoveries"
RUNS_DIR = STATE_DIR / "runs"
RECORDS_DIR = STATE_DIR / "records"


def load_discovery(discovery_id: str) -> dict:
    """Read and parse a discovery YAML file by its ID.

    Args:
        discovery_id: The discovery identifier, e.g. 'disc-2024-02-01-001'.

    Returns:
        The parsed discovery as a dict.

    Raises:
        FileNotFoundError: If no YAML file exists for this discovery ID.
    """
    path = DISCOVERIES_DIR / f"{discovery_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Discovery not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def load_run(run_id: str) -> dict:
    """Read and parse a run YAML file by its ID.

    Args:
        run_id: The run identifier, e.g. 'run-2024-02-01-001'.

    Returns:
        The parsed run as a dict.

    Raises:
        FileNotFoundError: If no YAML file exists for this run ID.
    """
    path = RUNS_DIR / f"{run_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Run not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def list_discoveries() -> list[dict]:
    """List all discovery YAML files, returning basic info for each.

    Returns:
        A list of dicts, each containing 'discovery_id' and summary fields
        extracted from the YAML. Sorted by discovery_id.
    """
    results = []
    for path in sorted(DISCOVERIES_DIR.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f)
        if data is None:
            continue
        results.append(
            {
                "discovery_id": data.get("discovery_id", path.stem),
                "discovered_at": data.get("discovered_at"),
                "category": data.get("error", {}).get("category"),
                "source_dataset": data.get("record", {}).get("source_dataset"),
                "control_number": data.get("record", {}).get("control_number"),
            }
        )
    return results


def list_runs() -> list[dict]:
    """List all run YAML files, returning basic info for each.

    Returns:
        A list of dicts, each containing 'run_id' and summary fields
        extracted from the YAML. Sorted by run_id.
    """
    results = []
    for path in sorted(RUNS_DIR.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f)
        if data is None:
            continue
        results.append(
            {
                "run_id": data.get("run_id", path.stem),
                "started_at": data.get("started_at"),
                "completed_at": data.get("completed_at"),
                "mrrc_version": data.get("environment", {}).get("mrrc_version"),
                "total_records": data.get("results", {}).get("total_records"),
                "new_discoveries": data.get("results", {}).get("new_discoveries"),
            }
        )
    return results


def save_discovery(discovery: dict) -> Path:
    """Write a discovery dict as YAML to state/discoveries/{id}.yaml.

    The discovery dict must contain a 'discovery_id' key.

    Args:
        discovery: The discovery data to persist.

    Returns:
        The Path to the written YAML file.

    Raises:
        ValueError: If 'discovery_id' is missing from the dict.
    """
    discovery_id = discovery.get("discovery_id")
    if not discovery_id:
        raise ValueError("Discovery dict must contain 'discovery_id'")
    DISCOVERIES_DIR.mkdir(parents=True, exist_ok=True)
    path = DISCOVERIES_DIR / f"{discovery_id}.yaml"
    with open(path, "w") as f:
        yaml.dump(discovery, f, default_flow_style=False, sort_keys=False)
    return path


def save_run(run: dict) -> Path:
    """Write a run dict as YAML to state/runs/{id}.yaml.

    The run dict must contain a 'run_id' key.

    Args:
        run: The run data to persist.

    Returns:
        The Path to the written YAML file.

    Raises:
        ValueError: If 'run_id' is missing from the dict.
    """
    run_id = run.get("run_id")
    if not run_id:
        raise ValueError("Run dict must contain 'run_id'")
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{run_id}.yaml"
    with open(path, "w") as f:
        yaml.dump(run, f, default_flow_style=False, sort_keys=False)
    return path


def discovery_exists(sha256: str) -> bool:
    """Check if a discovery with the given record sha256 already exists.

    Scans all discovery YAML files looking for a matching sha256 in the
    record section. Used for deduplication during import.

    Args:
        sha256: The SHA-256 hash of the record to check.

    Returns:
        True if a discovery with this sha256 already exists.
    """
    return sha256 in load_known_hashes()


def load_known_hashes() -> set[str]:
    """Load all sha256 hashes from existing discovery YAML files.

    Returns a set for O(1) membership testing. Call once per import batch
    rather than per-discovery to avoid O(N*M) performance.
    """
    hashes: set[str] = set()
    if not DISCOVERIES_DIR.is_dir():
        return hashes
    for path in DISCOVERIES_DIR.glob("*.yaml"):
        with open(path) as f:
            data = yaml.safe_load(f)
        if data is None:
            continue
        sha = data.get("record", {}).get("sha256")
        if sha:
            hashes.add(sha)
    return hashes

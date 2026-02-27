from mrrc_testbed.config import project_root

STATE_DIR = project_root() / "state"
DISCOVERIES_DIR = STATE_DIR / "discoveries"
RUNS_DIR = STATE_DIR / "runs"
RECORDS_DIR = STATE_DIR / "records"


def load_discovery(discovery_id: str) -> dict:
    raise NotImplementedError("Discovery loading not yet implemented")


def load_run(run_id: str) -> dict:
    raise NotImplementedError("Run loading not yet implemented")


def list_discoveries() -> list[dict]:
    raise NotImplementedError("Discovery listing not yet implemented")

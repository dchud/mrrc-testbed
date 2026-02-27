import os
from pathlib import Path

from dotenv import load_dotenv


def project_root() -> Path:
    """Walk up from this file to find the directory containing pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find project root (no pyproject.toml found)")


def load_config() -> None:
    env_path = project_root() / ".env"
    load_dotenv(env_path)


def get_test_mode() -> str:
    return os.environ.get("MRRC_TEST_MODE", "ci").lower()


def is_local_mode() -> bool:
    return get_test_mode() == "local"

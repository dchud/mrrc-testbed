"""Shared pytest fixtures and helpers for mrrc-testbed test suites."""

import os
from pathlib import Path

import pytest
from hypothesis import HealthCheck, Phase, settings

from mrrc_testbed.config import get_test_mode, is_local_mode, load_config
from mrrc_testbed.datasets import DOWNLOADS_DIR, FIXTURES_DIR, get_dataset

# ---------------------------------------------------------------------------
# Hypothesis profiles
# ---------------------------------------------------------------------------

settings.register_profile(
    "ci",
    max_examples=200,
    deadline=500,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "local",
    max_examples=10_000,
    deadline=None,
    phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

# Re-export the local marker for convenience.
local = pytest.mark.local


def get_test_dataset(name: str = "default") -> Path:
    """Wrapper around get_dataset() that skips instead of erroring.

    Call this from tests to get the path to a dataset file. If the dataset
    is not available (e.g. not downloaded in CI mode), the test is skipped
    gracefully rather than failing with FileNotFoundError.
    """
    try:
        return get_dataset(name)
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="session", autouse=True)
def _load_env() -> None:
    """Load .env configuration once per session."""
    load_config()


@pytest.fixture(scope="session")
def test_mode() -> str:
    """Return the current test mode ('ci' or 'local')."""
    return get_test_mode()


@pytest.fixture(scope="session")
def is_local() -> bool:
    """Return True if running in local mode."""
    return is_local_mode()


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Return the path to the committed fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def downloads_dir() -> Path:
    """Return the path to the downloads directory."""
    return DOWNLOADS_DIR


@pytest.fixture()
def skip_unless_local() -> None:
    """Skip the current test unless running in local mode.

    Usage: include ``skip_unless_local`` in a test's parameter list.
    """
    if not is_local_mode():
        pytest.skip("requires MRRC_TEST_MODE=local")

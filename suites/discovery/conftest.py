"""Shared fixtures for the discovery test suite."""

from pathlib import Path

import pytest

from discovery.helpers import DiscoveryWriter
from mrrc_testbed.config import project_root


@pytest.fixture(scope="session")
def results_dir() -> Path:
    """Create and return the results/discoveries/ directory."""
    path = project_root() / "results" / "discoveries"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture()
def discovery_writer(results_dir: Path) -> DiscoveryWriter:
    """Return a DiscoveryWriter configured for the discovery test suite."""
    return DiscoveryWriter(test_suite="discovery", results_dir=results_dir)

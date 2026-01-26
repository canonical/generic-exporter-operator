# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from typing import Generator

import distro
import jubilant
import pytest
import yaml
from helpers import TIMEOUT

logger = logging.getLogger(__name__)


def pytest_addoption(parser) -> None:
    """Add custom command-line options to pytest."""
    parser.addoption(
        "--keep-models",
        action="store_true",
        default=False,
        help="keep temporarily-created models",
    )

@pytest.fixture(scope="module")
def base() -> str:
    """Determine the base for the charm tests."""
    return f"{distro.id()}@{distro.version()}"

@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest) -> Generator[jubilant.Juju, None, None]:
    """Juju controller fixture."""
    keep_models = bool(request.config.getoption("--keep-models"))

    with jubilant.temp_model(keep=keep_models) as juju:
        juju.wait_timeout = TIMEOUT

        yield juju  # run the test

        if request.session.testsfailed:
            log = juju.debug_log(limit=300)
            print(log, end="")

@pytest.fixture(scope="module")
def charm(base: str) -> Path:
    """Path to the packed charm."""
    if not (path := next(iter(Path.cwd().glob(f"*_{base}-*.charm")), None)):
        raise FileNotFoundError(
            f"Could not find the packed charm for current system base: {base}."
        )

    return path

@pytest.fixture(scope="module")
def app_name() -> str:
    """Get the charm application name from charmcraft.yaml."""
    metadata = yaml.safe_load(Path("./charmcraft.yaml").read_text())
    return metadata["name"]

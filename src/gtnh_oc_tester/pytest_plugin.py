"""pytest plugin providing the `oc_env` fixture and `--oc-jar` / `--oc-dag-dir` flags."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest

from .environment import OCEnvironment


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("gtnh-oc-tester")
    group.addoption(
        "--oc-jar",
        action="store",
        default=None,
        help="Path to OpenComputers-1.12.62-GTNH.jar",
    )
    group.addoption(
        "--oc-dag-dir",
        action="store",
        default=None,
        help="Directory to write execution DAGs and GPU screen snapshots for each test",
    )


@pytest.fixture
def oc_env(request: pytest.FixtureRequest) -> Generator[OCEnvironment, None, None]:
    """Provide an isolated GTNH 2.9 OpenComputers simulation environment for each test."""
    jar_path = request.config.getoption("--oc-jar")
    env = OCEnvironment(jar_path=jar_path)
    yield env
    dag_dir = request.config.getoption("--oc-dag-dir")
    if dag_dir:
        safe_name = request.node.name.replace("[", "_").replace("]", "_").replace("/", "_")
        env.save_artifacts(Path(dag_dir), prefix=safe_name)

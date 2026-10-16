"""pytest plugin providing the `oc_env` fixture and OpenComputers hardware/runtime CLI flags."""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any, Dict, Generator

import pytest

from .environment import OCEnvironment
from .screen.window import OCPygameWindow


RAM_TIER_KB: Dict[int, int] = {
    1: 192,
    2: 256,
    3: 384,
    4: 512,
    5: 768,
    6: 1024,
}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("gtnh-oc-tester")
    group.addoption(
        "--oc-jar",
        action="store",
        default=None,
        help="Path to OpenComputers GTNH .jar file",
    )
    group.addoption(
        "--oc-jar-version",
        action="store",
        default="1.12.64-GTNH",
        help="OpenComputers GTNH JAR version (e.g. 1.12.64-GTNH or 1.12.62-GTNH)",
    )
    group.addoption(
        "--oc-lua-version",
        action="store",
        default="5.3",
        choices=["5.2", "5.3", "Lua 5.2", "Lua 5.3"],
        help="CPU Lua architecture version (5.3 or 5.2, default 5.3)",
    )
    group.addoption(
        "--oc-cpu-tier",
        action="store",
        type=int,
        default=3,
        choices=[1, 2, 3],
        help="CPU tier (1, 2, or 3, default 3)",
    )
    group.addoption(
        "--oc-ram-tier",
        action="store",
        type=int,
        default=6,
        choices=[1, 2, 3, 4, 5, 6],
        help="RAM tier (1..6 corresponding to 192..1024 KB, default 6)",
    )
    group.addoption(
        "--oc-config",
        action="store",
        default=None,
        help="Path to custom OpenComputers.cfg file",
    )
    group.addoption(
        "--oc-window",
        action="store_true",
        default=False,
        help="Open the Pygame OpenComputers screen window during test execution",
    )
    group.addoption(
        "--oc-dag-dir",
        action="store",
        default=None,
        help="Directory to write execution DAGs and GPU screen snapshots for each test",
    )


def _create_configured_env(
    *,
    jar_path: Any = None,
    jar_version: str = "1.12.64-GTNH",
    lua_version: str = "5.3",
    cpu_tier: int = 3,
    ram_tier: int = 6,
    oc_config: Any = None,
) -> OCEnvironment:
    sig = inspect.signature(OCEnvironment.__init__)
    params = sig.parameters
    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

    candidate_kwargs: Dict[str, Any] = {
        "jar_path": jar_path,
        "jar_version": jar_version,
        "lua_version": lua_version,
        "cpu_tier": int(cpu_tier),
        "ram_tier": int(ram_tier),
        "oc_config": oc_config,
        "config_path": oc_config,
    }
    filtered_kwargs = {
        k: v
        for k, v in candidate_kwargs.items()
        if v is not None and (accepts_var_kw or k in params)
    }
    if "jar_path" in params and "jar_path" not in filtered_kwargs:
        filtered_kwargs["jar_path"] = jar_path

    env = OCEnvironment(**filtered_kwargs)
    setattr(env, "jar_version", jar_version)
    setattr(env, "lua_version", lua_version)
    setattr(env, "cpu_tier", int(cpu_tier))
    setattr(env, "ram_tier", int(ram_tier))
    setattr(env, "oc_config", oc_config)

    ram_bytes = RAM_TIER_KB.get(int(ram_tier), 1024) * 1024
    if hasattr(env, "sandbox"):
        if not hasattr(env.sandbox, "ram_tier"):
            setattr(env.sandbox, "ram_tier", int(ram_tier))
        if not hasattr(env.sandbox, "cpu_tier"):
            setattr(env.sandbox, "cpu_tier", int(cpu_tier))
        if not hasattr(env.sandbox, "lua_version"):
            setattr(env.sandbox, "lua_version", str(lua_version))
        if getattr(env.sandbox, "total_memory", None) == 2097152 and int(ram_tier) in RAM_TIER_KB:
            env.sandbox.total_memory = ram_bytes
            env.sandbox.free_memory = min(env.sandbox.free_memory, ram_bytes)

    return env


@pytest.fixture
def oc_env(request: pytest.FixtureRequest) -> Generator[OCEnvironment, None, None]:
    """Provide an isolated GTNH 2.9 OpenComputers simulation environment for each test."""
    jar_path = request.config.getoption("--oc-jar")
    jar_version = request.config.getoption("--oc-jar-version") or os.environ.get("OC_JAR_VERSION", "1.12.64-GTNH")
    lua_version = request.config.getoption("--oc-lua-version") or os.environ.get("OC_LUA_VERSION", "5.3")
    cpu_tier = request.config.getoption("--oc-cpu-tier") or int(os.environ.get("OC_CPU_TIER", "3"))
    ram_tier = request.config.getoption("--oc-ram-tier") or int(os.environ.get("OC_RAM_TIER", "6"))
    oc_config = request.config.getoption("--oc-config") or os.environ.get("OC_CONFIG_PATH")
    use_window = bool(request.config.getoption("--oc-window"))

    env = _create_configured_env(
        jar_path=jar_path,
        jar_version=str(jar_version),
        lua_version=str(lua_version),
        cpu_tier=int(cpu_tier),
        ram_tier=int(ram_tier),
        oc_config=oc_config,
    )

    window: OCPygameWindow | None = None
    if use_window:
        window = OCPygameWindow(env, title=f"OC Test - {request.node.name}")
        setattr(env, "window", window)
        window.render_frame()

    yield env

    if window is not None:
        window.render_frame()

    dag_dir = request.config.getoption("--oc-dag-dir")
    if dag_dir:
        safe_name = request.node.name.replace("[", "_").replace("]", "_").replace("/", "_")
        env.save_artifacts(Path(dag_dir), prefix=safe_name)

    if window is not None:
        window.close()

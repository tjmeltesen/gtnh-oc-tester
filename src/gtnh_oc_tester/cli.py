"""Unified CLI runner (`gtnh-oc-test`) for Python pytest suites, pure-Lua `*_spec.lua` suites, and Pygame viewer."""

from __future__ import annotations

import argparse
import inspect
import os
from pathlib import Path
import sys
from typing import Any, Dict, List

import pytest
from rich.console import Console
from rich.table import Table

from .lua_runner import LuaSpecRunner, LuaTestResult
from .pytest_plugin import RAM_TIER_KB, _create_configured_env
from .screen.window import OCPygameWindow


def discover_lua_specs(targets: List[str]) -> List[Path]:
    specs: List[Path] = []
    search_roots = [Path(t) for t in targets] if targets else [Path("tests")]
    for root in search_roots:
        if root.is_file() and root.name.endswith("_spec.lua"):
            specs.append(root)
        elif root.is_dir():
            specs.extend(sorted(root.rglob("*_spec.lua")))
    return specs


def _build_lua_runner(args: argparse.Namespace) -> LuaSpecRunner:
    sig = inspect.signature(LuaSpecRunner.__init__)
    params = sig.parameters
    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

    candidate_kwargs: Dict[str, Any] = {
        "jar_path": args.oc_jar,
        "dag_output_dir": args.dag_dir,
        "jar_version": args.jar_version,
        "lua_version": args.lua_version,
        "cpu_tier": args.cpu_tier,
        "ram_tier": args.ram_tier,
        "oc_config": args.oc_config,
        "config_path": args.oc_config,
    }
    filtered = {
        k: v
        for k, v in candidate_kwargs.items()
        if (k in ("jar_path", "dag_output_dir") or v is not None)
        and (accepts_var_kw or k in params)
    }
    return LuaSpecRunner(**filtered)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gtnh-oc-test",
        description="GTNH 2.9 OpenComputers Lua & Python Testing Framework CLI",
    )
    parser.add_argument(
        "targets",
        nargs="*",
        default=[],
        help="Test files or directories to run (defaults to `tests/`)",
    )
    parser.add_argument(
        "--oc-jar",
        dest="oc_jar",
        default=None,
        help="Path to OpenComputers GTNH .jar file",
    )
    parser.add_argument(
        "--jar-version",
        dest="jar_version",
        default="1.12.64-GTNH",
        help="Select OpenComputers GTNH JAR version (e.g. 1.12.64-GTNH or 1.12.62-GTNH, default: 1.12.64-GTNH)",
    )
    parser.add_argument(
        "--lua-version",
        dest="lua_version",
        default="5.3",
        choices=["5.2", "5.3"],
        help="Select CPU Lua architecture (5.3 or 5.2, default: 5.3)",
    )
    parser.add_argument(
        "--cpu-tier",
        dest="cpu_tier",
        type=int,
        default=3,
        choices=[1, 2, 3],
        help="Select CPU tier (1, 2, or 3, default: 3)",
    )
    parser.add_argument(
        "--ram-tier",
        dest="ram_tier",
        type=int,
        default=6,
        choices=[1, 2, 3, 4, 5, 6],
        help=f"Select RAM tier 1..6 ({', '.join(f'{k}={v}KB' for k, v in RAM_TIER_KB.items())}, default: 6)",
    )
    parser.add_argument(
        "--oc-config",
        dest="oc_config",
        default=None,
        help="Path to custom OpenComputers.cfg file",
    )
    parser.add_argument(
        "--window",
        dest="window",
        action="store_true",
        default=False,
        help="Open the interactive Pygame OpenComputers screen window",
    )
    parser.add_argument(
        "--dag-dir",
        dest="dag_dir",
        default=None,
        help="Directory to export execution DAGs and GPU screen snapshots",
    )
    parser.add_argument(
        "--lua-only",
        action="store_true",
        help="Run only pure-Lua `*_spec.lua` test suites",
    )
    parser.add_argument(
        "--py-only",
        action="store_true",
        help="Run only Python `pytest` test suites",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console()
    exit_code = 0

    os.environ["OC_JAR_VERSION"] = str(args.jar_version)
    os.environ["OC_LUA_VERSION"] = str(args.lua_version)
    os.environ["OC_CPU_TIER"] = str(args.cpu_tier)
    os.environ["OC_RAM_TIER"] = str(args.ram_tier)
    if args.oc_config:
        os.environ["OC_CONFIG_PATH"] = str(args.oc_config)

    if not args.lua_only:
        py_targets = [t for t in args.targets if not t.endswith(".lua")]
        pytest_args: List[str] = []
        if py_targets:
            pytest_args.extend(py_targets)
        elif not any(t.endswith(".lua") for t in args.targets):
            pytest_args.append("tests")

        if pytest_args:
            if args.oc_jar:
                pytest_args.extend(["--oc-jar", args.oc_jar])
            if args.jar_version:
                pytest_args.extend(["--oc-jar-version", str(args.jar_version)])
            if args.lua_version:
                pytest_args.extend(["--oc-lua-version", str(args.lua_version)])
            if args.cpu_tier:
                pytest_args.extend(["--oc-cpu-tier", str(args.cpu_tier)])
            if args.ram_tier:
                pytest_args.extend(["--oc-ram-tier", str(args.ram_tier)])
            if args.oc_config:
                pytest_args.extend(["--oc-config", str(args.oc_config)])
            if args.window:
                pytest_args.append("--oc-window")
            if args.dag_dir:
                pytest_args.extend(["--oc-dag-dir", args.dag_dir])
            console.rule(
                f"[bold cyan]Running Python pytest Suite (Lua {args.lua_version}, CPU T{args.cpu_tier}, RAM T{args.ram_tier})[/bold cyan]"
            )
            rc = pytest.main(pytest_args)
            if rc != 0:
                exit_code = int(rc)

    if not args.py_only:
        lua_specs = discover_lua_specs(args.targets)
        if lua_specs:
            console.rule(
                f"[bold magenta]Running Pure-Lua (*_spec.lua) Suite (Lua {args.lua_version}, JAR {args.jar_version})[/bold magenta]"
            )
            runner = _build_lua_runner(args)
            all_results: List[LuaTestResult] = []
            for spec_file in lua_specs:
                all_results.extend(runner.run_spec_file(spec_file))
                if args.window and runner.current_env is not None:
                    win = OCPygameWindow(
                        runner.current_env,
                        title=f"OC Lua Spec - {spec_file.name}",
                    )
                    win.render_frame()
                    win.close()

            table = Table(title="Pure-Lua Spec Results")
            table.add_column("File", style="cyan")
            table.add_column("Spec", style="white")
            table.add_column("Status", style="bold")
            for res in all_results:
                status = "[green]PASS[/green]" if res.passed else f"[red]FAIL[/red]\n{res.error}"
                if not res.passed:
                    exit_code = 1
                table.add_row(res.file_path.name, res.full_name, status)
            console.print(table)

        # Support running standalone non-spec `.lua` scripts with `--window`
        standalone_lua = [
            Path(t)
            for t in args.targets
            if t.endswith(".lua") and not t.endswith("_spec.lua") and Path(t).is_file()
        ]
        for script_path in standalone_lua:
            env = _create_configured_env(
                jar_path=args.oc_jar,
                jar_version=args.jar_version,
                lua_version=args.lua_version,
                cpu_tier=args.cpu_tier,
                ram_tier=args.ram_tier,
                oc_config=args.oc_config,
            )
            env.run_file(script_path)
            if args.window:
                win = OCPygameWindow(env, title=f"OC Viewer - {script_path.name}")
                win.run_loop(max_frames=1 if win.headless else None)
                win.close()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

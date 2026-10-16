"""Unified CLI runner (`gtnh-oc-test`) for Python pytest suites and pure-Lua `*_spec.lua` suites."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import List

import pytest
from rich.console import Console
from rich.table import Table

from .lua_runner import LuaSpecRunner, LuaTestResult


def discover_lua_specs(targets: List[str]) -> List[Path]:
    specs: List[Path] = []
    search_roots = [Path(t) for t in targets] if targets else [Path("tests")]
    for root in search_roots:
        if root.is_file() and root.name.endswith("_spec.lua"):
            specs.append(root)
        elif root.is_dir():
            specs.extend(sorted(root.rglob("*_spec.lua")))
    return specs


def main(argv: List[str] | None = None) -> int:
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
        help="Path to OpenComputers-1.12.62-GTNH.jar",
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

    args = parser.parse_args(argv)
    console = Console()
    exit_code = 0

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
            if args.dag_dir:
                pytest_args.extend(["--oc-dag-dir", args.dag_dir])
            console.rule("[bold cyan]Running Python pytest Suite[/bold cyan]")
            rc = pytest.main(pytest_args)
            if rc != 0:
                exit_code = int(rc)

    if not args.py_only:
        lua_specs = discover_lua_specs(args.targets)
        if lua_specs:
            console.rule("[bold magenta]Running Pure-Lua (*_spec.lua) Suite[/bold magenta]")
            runner = LuaSpecRunner(jar_path=args.oc_jar, dag_output_dir=args.dag_dir)
            all_results: List[LuaTestResult] = []
            for spec_file in lua_specs:
                all_results.extend(runner.run_spec_file(spec_file))

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

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

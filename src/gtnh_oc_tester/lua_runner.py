"""Pure-Lua (`*_spec.lua`) test runner with `mock_oc` bridge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .components.simulators import GTMachineSimulator, RedstoneSimulator
from .environment import OCEnvironment


@dataclass
class LuaTestResult:
    file_path: Path
    suite: str
    test: str
    full_name: str
    passed: bool
    error: str = ""


class _MockOCBridge:
    """Lua-callable `mock_oc` control library for configuring components and inspecting state inside `*_spec.lua`."""

    def __init__(self, runner: "LuaSpecRunner") -> None:
        self.runner = runner

    @property
    def env(self) -> OCEnvironment:
        assert self.runner.current_env is not None
        return self.runner.current_env

    def attach(self, component_type: str, address: Optional[str] = None, opts: Optional[Any] = None) -> str:
        py_opts = (
            self.env.sandbox.lua_to_python(opts)
            if opts is not None
            else {}
        )
        if not isinstance(py_opts, dict):
            py_opts = {}
        comp = self.env.attach(str(component_type), address=address, **py_opts)
        return comp.address

    def add_me_item(
        self,
        name: str,
        size: int = 1,
        label: Optional[str] = None,
        damage: int = 0,
    ) -> Any:
        item = self.env.me_network.add_item(
            name=str(name),
            size=int(size),
            label=str(label) if label else None,
            damage=int(damage or 0),
        )
        return self.env.sandbox.python_to_lua(item)

    def add_me_fluid(
        self,
        name: str,
        amount: int = 1000,
        label: Optional[str] = None,
    ) -> Any:
        fl = self.env.me_network.add_fluid(
            name=str(name),
            amount=int(amount),
            label=str(label) if label else None,
        )
        return self.env.sandbox.python_to_lua(fl)

    def add_me_craftable(
        self,
        name: str,
        recipe_type: str = "item",
        duration_ticks: int = 2,
        label: Optional[str] = None,
    ) -> bool:
        self.env.me_network.add_craftable(
            name=str(name),
            label=str(label) if label else None,
            recipe_type=str(recipe_type or "item"),
            duration_ticks=int(duration_ticks if duration_ticks is not None else 2),
        )
        return True

    def set_gt_machine(self, address: str, opts: Any) -> bool:
        comp = self.env.bus.get_component(str(address))
        if not isinstance(comp, GTMachineSimulator):
            return False
        py_opts = self.env.sandbox.lua_to_python(opts)
        if isinstance(py_opts, dict):
            if "stored_eu" in py_opts:
                comp.stored_eu = int(py_opts["stored_eu"])
            if "eu_capacity" in py_opts:
                comp.eu_capacity = int(py_opts["eu_capacity"])
            if "work_allowed" in py_opts:
                comp.work_allowed = bool(py_opts["work_allowed"])
            if "has_work" in py_opts:
                comp.has_work = bool(py_opts["has_work"])
            if "work_progress" in py_opts:
                comp.work_progress = int(py_opts["work_progress"])
            if "work_max_progress" in py_opts:
                comp.work_max_progress = int(py_opts["work_max_progress"])
            if "sensor_information" in py_opts:
                s_info = py_opts["sensor_information"]
                if isinstance(s_info, dict):
                    comp.sensor_information = [str( s_info[k] ) for k in sorted(s_info.keys())]
                elif isinstance(s_info, list):
                    comp.sensor_information = [str(x) for x in s_info]
        return True

    def set_inventory_slot(
        self,
        side: int,
        slot: int,
        name: str,
        size: int = 1,
        damage: int = 0,
        label: Optional[str] = None,
    ) -> Any:
        st = self.env.inventory_grid.set_stack(
            side=int(side),
            slot=int(slot),
            name=str(name),
            size=int(size),
            damage=int(damage or 0),
            label=str(label) if label else None,
        )
        return self.env.sandbox.python_to_lua(st)

    def set_tank_fluid(
        self,
        side: int,
        tank_index: int,
        name: str,
        amount: int,
        capacity: int = 16000,
    ) -> Any:
        tk = self.env.inventory_grid.set_tank(
            side=int(side),
            tank_index=int(tank_index),
            name=str(name),
            amount=int(amount),
            capacity=int(capacity or 16000),
        )
        return self.env.sandbox.python_to_lua(tk)

    def set_redstone_input(
        self,
        address: str,
        side: int,
        value: int,
        color: Optional[int] = None,
    ) -> bool:
        comp = self.env.bus.get_component(str(address))
        if isinstance(comp, RedstoneSimulator):
            comp.set_external_input(int(side), int(value), int(color) if color is not None else None)
            return True
        return False

    def push_event(self, name: str, *args: Any) -> bool:
        return self.env.push_event(str(name), *args)

    def advance_ticks(self, ticks: int = 1) -> int:
        self.env.advance_ticks(int(ticks))
        return self.env.scheduler.current_tick

    def screen_text(self) -> str:
        return self.env.screen.to_text()

    def call_count(self, component_type: str, method: Optional[str] = None) -> int:
        count = 0
        for rec in self.env.bus.call_log:
            if rec.component_type == str(component_type):
                if method is None or rec.method == str(method):
                    count += 1
        return count

    def dag_mermaid(self) -> str:
        return self.env.build_dag(collapse_loops=True).to_mermaid()


class LuaSpecRunner:
    """Executes pure-Lua `*_spec.lua` test files inside an OCEnvironment."""

    def __init__(
        self,
        jar_path: Optional[str | Path] = None,
        jar_version: str = "1.12.64-GTNH",
        lua_version: str = "5.3",
        cpu_tier: int = 3,
        ram_tier: int = 6,
        oc_config: Optional[Any] = None,
        dag_output_dir: Optional[str | Path] = None,
    ) -> None:
        self.jar_path = jar_path
        self.jar_version = jar_version
        self.lua_version = lua_version
        self.cpu_tier = cpu_tier
        self.ram_tier = ram_tier
        self.oc_config = oc_config
        self.dag_output_dir = Path(dag_output_dir) if dag_output_dir else None
        self.harness_path = Path(__file__).resolve().parent / "lua_harness" / "test_harness.lua"
        self.current_env: Optional[OCEnvironment] = None

    def run_spec_file(self, spec_path: str | Path) -> List[LuaTestResult]:
        path = Path(spec_path)
        env = OCEnvironment(
            jar_path=self.jar_path,
            jar_version=self.jar_version,
            lua_version=self.lua_version,
            cpu_tier=self.cpu_tier,
            ram_tier=self.ram_tier,
            oc_config=self.oc_config,
        )
        self.current_env = env

        harness_src = self.harness_path.read_text(encoding="utf-8")
        env.run_lua(harness_src, chunk_name="=test_harness.lua")

        bridge = _MockOCBridge(self)
        env.sandbox.lua.globals()["mock_oc"] = bridge
        env.sandbox.lua.eval('require("package").loaded')["mock_oc"] = bridge

        spec_src = path.read_text(encoding="utf-8")
        env.run_lua(spec_src, chunk_name=f"={path.name}")

        raw_results = env.run_lua("return __run_registered_specs()", chunk_name="=run_specs")
        py_results = env.sandbox.lua_to_python(raw_results)

        results: List[LuaTestResult] = []
        items = py_results if isinstance(py_results, list) else list(py_results.values())
        for item in items:
            results.append(
                LuaTestResult(
                    file_path=path,
                    suite=str(item.get("suite", "")),
                    test=str(item.get("test", "")),
                    full_name=str(item.get("full_name", "")),
                    passed=bool(item.get("passed", False)),
                    error=str(item.get("error", "")),
                )
            )

        if self.dag_output_dir:
            env.save_artifacts(self.dag_output_dir, prefix=path.stem)

        return results

"""High-level OCEnvironment orchestrating Sandbox, Component Bus, GPU Screen, and DAG Tracer."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .components.auto_mock import SchemaBackedComponent
from .components.bus import ComponentBus
from .components.simulators import (
    AE2NetworkComponent,
    DatabaseSimulator,
    GTMachineSimulator,
    MENetworkState,
    RedstoneSimulator,
    TransposerInventorySimulator,
    WorldInventoryGrid,
)
from .dag.dag_builder import ExecutionDAG
from .dag.tracer import ExecutionTracer
from .runtime.sandbox import OCLuaSandbox
from .runtime.scheduler import DeterministicScheduler
from .runtime.vfs import VirtualFileSystem
from .screen.gpu_buffer import GPUScreenEmulator
from .specs.jar_loader import OCJarLoader
from .specs.registry import SchemaRegistry, get_default_registry


class OCEnvironment:
    """Complete deterministic GTNH 2.9 OpenComputers simulation & testing environment."""

    def __init__(
        self,
        host: str = "computer",
        screen_width: int = 80,
        screen_height: int = 25,
        screen_tier: int = 3,
        jar_path: Optional[str | Path] = None,
        registry: Optional[SchemaRegistry] = None,
        trace_lua_functions: bool = True,
    ) -> None:
        self.host = host
        self.registry = registry or get_default_registry()
        self.jar_loader = OCJarLoader(jar_path=jar_path)
        self.screen = GPUScreenEmulator(
            width=screen_width,
            height=screen_height,
            tier=screen_tier,
            jar_loader=self.jar_loader,
        )
        self.sandbox = OCLuaSandbox(
            host=host,
            jar_loader=self.jar_loader,
            gpu_screen=self.screen,
        )
        self.scheduler: DeterministicScheduler = self.sandbox.scheduler
        self.vfs: VirtualFileSystem = self.sandbox.vfs

        self.bus = ComponentBus(
            host=host,
            registry=self.registry,
            scheduler=self.scheduler,
            sandbox=self.sandbox,
        )
        self.sandbox.component_bus = self.bus

        # Attach standard base OpenComputers components before binding component library
        self.screen_comp = self.bus.attach(
            "screen",
            address=self.screen.screen_address,
            slot=-1,
            primary=True,
        )
        self.gpu_comp = self.bus.attach(
            "gpu",
            address="g0000000-0000-4000-8000-000000000001",
            slot=0,
            primary=True,
        )
        self.keyboard_comp = self.bus.attach(
            "keyboard",
            address="k0000000-0000-4000-8000-000000000001",
            slot=-1,
            primary=True,
        )
        self.fs_comp = self.bus.attach(
            "filesystem",
            address=self.vfs.root_address,
            slot=1,
            primary=True,
        )
        self.eeprom_comp = self.bus.attach(
            "eeprom",
            address="e0000000-0000-4000-8000-000000000001",
            slot=-1,
            primary=True,
        )
        self.computer_comp = self.bus.attach(
            "computer",
            address=self.sandbox.computer_address,
            slot=-1,
            primary=True,
        )
        if host == "robot":
            self.bus.attach(
                "robot",
                address="r0000000-0000-4000-8000-000000000001",
                slot=-1,
                primary=True,
            )
        elif host == "tablet":
            self.bus.attach(
                "tablet",
                address="t0000000-0000-4000-8000-000000000001",
                slot=-1,
                primary=True,
            )

        # Clear initialization component_added signals from the test signal queue
        self.scheduler.signal_queue.clear()

        self.bus.build_lua_component_library(self.sandbox)

        self.tracer = ExecutionTracer(
            sandbox=self.sandbox,
            bus=self.bus,
            scheduler=self.scheduler,
            trace_lua_functions=trace_lua_functions,
        )
        self.tracer.attach()

    @property
    def me_network(self) -> MENetworkState:
        return self.bus.me_network

    @property
    def inventory_grid(self) -> WorldInventoryGrid:
        return self.bus.inventory_grid

    def attach(
        self,
        component_type: str,
        address: Optional[str] = None,
        slot: int = -1,
        variant: Optional[str] = None,
        primary: Optional[bool] = None,
        **kwargs: Any,
    ) -> SchemaBackedComponent:
        comp = self.bus.attach(
            component_type=component_type,
            address=address,
            slot=slot,
            variant=variant,
            primary=primary,
            **kwargs,
        )
        # Pop the automatic component_added signal unless user explicitly wants it
        if self.scheduler.signal_queue and self.scheduler.signal_queue[-1][0] == "component_added":
            self.scheduler.signal_queue.pop()
        return comp

    def attach_me_network(self, component_type: str = "me_interface", **kwargs: Any) -> AE2NetworkComponent:
        comp = self.attach(component_type, **kwargs)
        assert isinstance(comp, AE2NetworkComponent)
        return comp

    def attach_gt_machine(
        self,
        component_type: str = "gt_machine",
        address: Optional[str] = None,
        **kwargs: Any,
    ) -> GTMachineSimulator:
        comp = self.attach(component_type, address=address, **kwargs)
        assert isinstance(comp, GTMachineSimulator)
        return comp

    def attach_transposer(self, address: Optional[str] = None, **kwargs: Any) -> TransposerInventorySimulator:
        comp = self.attach("transposer", address=address, **kwargs)
        assert isinstance(comp, TransposerInventorySimulator)
        return comp

    def attach_redstone(self, address: Optional[str] = None, **kwargs: Any) -> RedstoneSimulator:
        comp = self.attach("redstone", address=address, **kwargs)
        assert isinstance(comp, RedstoneSimulator)
        return comp

    def attach_database(self, address: Optional[str] = None, **kwargs: Any) -> DatabaseSimulator:
        comp = self.attach("database", address=address, **kwargs)
        assert isinstance(comp, DatabaseSimulator)
        return comp

    def push_event(self, name: str, *args: Any) -> bool:
        return self.scheduler.push_signal(name, *args)

    def advance_ticks(self, ticks: int = 1) -> None:
        self.scheduler.advance_ticks(ticks)

    def run_lua(self, lua_code: str, chunk_name: str = "=script.lua") -> Any:
        return self.sandbox.execute(lua_code, chunk_name=chunk_name)

    def run_file(self, path: str | Path) -> Any:
        return self.sandbox.run_file(str(path))

    def build_dag(self, collapse_loops: bool = True) -> ExecutionDAG:
        return ExecutionDAG.from_tracer(self.tracer, collapse_loops=collapse_loops)

    def save_artifacts(
        self,
        output_dir: str | Path,
        prefix: str = "trace",
        render_png_screen: bool = True,
        render_dag_image: bool = True,
    ) -> Dict[str, Path]:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        dag = self.build_dag(collapse_loops=True)

        paths: Dict[str, Path] = {}
        mmd_path = out_dir / f"{prefix}.mmd"
        mmd_path.write_text(dag.to_mermaid(), encoding="utf-8")
        paths["mermaid"] = mmd_path

        dot_path = out_dir / f"{prefix}.dot"
        dot_path.write_text(dag.to_dot(), encoding="utf-8")
        paths["dot"] = dot_path

        html_path = out_dir / f"{prefix}_dag.html"
        html_path.write_text(
            dag.to_html(title=f"GTNH OC Execution DAG - {prefix}", screen_emulator=self.screen),
            encoding="utf-8",
        )
        paths["dag_html"] = html_path

        screen_html_path = out_dir / f"{prefix}_screen.html"
        screen_html_path.write_text(
            self.screen.to_html(title=f"OpenComputers Screen - {prefix}"),
            encoding="utf-8",
        )
        paths["screen_html"] = screen_html_path

        if render_png_screen:
            png_path = out_dir / f"{prefix}_screen.png"
            self.screen.to_png(png_path)
            paths["screen_png"] = png_path

        if render_dag_image:
            try:
                dag_png = dag.render_image(out_dir / f"{prefix}_dag", fmt="png")
                paths["dag_png"] = dag_png
            except Exception:
                pass

        return paths

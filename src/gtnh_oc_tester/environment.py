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
from .specs.oc_config import OCMachineConfig, load_oc_config
from .specs.registry import SchemaRegistry, get_default_registry


# Basic ASCII character to OpenComputers / LWJGL2 scancode lookup for send_key / send_text
_ASCII_TO_OC_KEYCODE: Dict[str, int] = {
    "\r": 0x1C,
    "\n": 0x1C,
    "\b": 0x0E,
    "\t": 0x0F,
    "\x1b": 0x01,
    " ": 0x39,
    "1": 0x02, "!": 0x02,
    "2": 0x03, "@": 0x03,
    "3": 0x04, "#": 0x04,
    "4": 0x05, "$": 0x05,
    "5": 0x06, "%": 0x06,
    "6": 0x07, "^": 0x07,
    "7": 0x08, "&": 0x08,
    "8": 0x09, "*": 0x09,
    "9": 0x0A, "(": 0x0A,
    "0": 0x0B, ")": 0x0B,
    "-": 0x0C, "_": 0x0C,
    "=": 0x0D, "+": 0x0D,
    "[": 0x1A, "{": 0x1A,
    "]": 0x1B, "}": 0x1B,
    ";": 0x27, ":": 0x27,
    "'": 0x28, '"': 0x28,
    "`": 0x29, "~": 0x29,
    "\\": 0x2B, "|": 0x2B,
    ",": 0x33, "<": 0x33,
    ".": 0x34, ">": 0x34,
    "/": 0x35, "?": 0x35,
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12, "f": 0x21,
    "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24, "k": 0x25, "l": 0x26,
    "m": 0x32, "n": 0x31, "o": 0x18, "p": 0x19, "q": 0x10, "r": 0x13,
    "s": 0x1F, "t": 0x14, "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D,
    "y": 0x15, "z": 0x2C,
}


class OCEnvironment:
    """Complete deterministic GTNH 2.9 OpenComputers simulation & testing environment."""

    def __init__(
        self,
        host: str = "computer",
        screen_width: int = 80,
        screen_height: int = 25,
        screen_tier: int = 3,
        jar_path: Optional[str | Path] = None,
        jar_version: str = "1.12.64-GTNH",
        lua_version: str = "5.2",
        architecture: Optional[str] = None,
        cpu_tier: int = 3,
        ram_tier: int = 6,
        oc_config: Optional[str | Path | OCMachineConfig] = None,
        config_path: Optional[str | Path] = None,
        enforce_call_budget: bool = True,
        timeout: Optional[float] = None,
        raise_on_event_error: bool = False,
        registry: Optional[SchemaRegistry] = None,
        trace_lua_functions: bool = True,
    ) -> None:
        self.host = host
        self.jar_version = str(jar_version or "1.12.64-GTNH")

        raw_arch = str(architecture or lua_version or "5.2").strip()
        if raw_arch in ("5.2", "Lua 5.2"):
            norm_arch = "Lua 5.2"
        elif raw_arch in ("5.3", "Lua 5.3"):
            norm_arch = "Lua 5.3"
        else:
            norm_arch = raw_arch

        if isinstance(oc_config, OCMachineConfig):
            self.config = oc_config
        else:
            cfg_source = oc_config if oc_config is not None else config_path
            self.config = load_oc_config(
                cfg_source,
                architecture=norm_arch if (architecture is not None or lua_version != "5.2" or cfg_source is None) else None,
                cpu_tier=int(cpu_tier),
                ram_tier=int(ram_tier),
            )

        effective_timeout = float(timeout) if timeout is not None else float(self.config.timeout)
        self.config.timeout = effective_timeout
        self.lua_version = "5.2" if self.config.architecture == "Lua 5.2" else "5.3"
        self.cpu_tier = self.config.cpu_tier
        self.ram_tier = self.config.ram_tier
        self.enforce_call_budget = bool(enforce_call_budget)
        self.raise_on_event_error = bool(raise_on_event_error)

        self.registry = registry or get_default_registry()
        self.jar_loader = OCJarLoader(jar_path=jar_path, jar_version=self.jar_version)
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
            architecture=self.config.architecture,
            ram_tier=self.config.ram_tier,
            cpu_tier=self.config.cpu_tier,
            allow_bytecode=self.config.allow_bytecode,
            allow_gc=self.config.allow_gc,
            timeout=effective_timeout,
            enforce_call_budget=self.enforce_call_budget,
            ram_scale_for_64bit=self.config.ram_scale_for_64bit,
            max_signal_queue_size=self.config.max_signal_queue_size,
            raise_on_event_error=self.raise_on_event_error,
        )
        self.scheduler: DeterministicScheduler = self.sandbox.scheduler
        self.scheduler.max_signal_queue_size = self.config.max_signal_queue_size
        self.vfs: VirtualFileSystem = self.sandbox.vfs

        self.bus = ComponentBus(
            host=host,
            registry=self.registry,
            scheduler=self.scheduler,
            sandbox=self.sandbox,
            config=self.config,
            enforce_call_budget=self.enforce_call_budget,
            vfs=self.vfs,
        )
        self.sandbox.component_bus = self.bus

        # Attach standard base OpenComputers components on the unified ComponentBus
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
            vfs=self.vfs,
            label="OpenOS",
        )
        self.tmp_fs_comp = self.bus.attach(
            "filesystem",
            address=self.vfs.tmp_address,
            slot=-1,
            primary=False,
            vfs=self.sandbox.machine_host.tmp_vfs,
            label="tmpfs",
        )
        self.eeprom_comp = self.bus.attach(
            "eeprom",
            address="e0000000-0000-4000-8000-000000000001",
            slot=-1,
            primary=True,
            data=self.vfs.root_address,
            max_code_size=self.config.eeprom_size,
            max_data_size=self.config.eeprom_data_size,
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

    @property
    def event_errors(self) -> list[str]:
        return self.scheduler.event_errors

    def read_event_log(self) -> str:
        """Read `/tmp/event.log` written by OpenOS `event.onError`."""
        tmp_log = self.sandbox.machine_host.tmp_vfs.read_file("/event.log")
        if tmp_log:
            return tmp_log
        return self.vfs.read_file("/tmp/event.log") or ""

    def mount_host_dir(
        self,
        host_dir: str | Path,
        vfs_dir: str = "/home",
        extensions: tuple[str, ...] = (
            ".lua",
            ".txt",
            ".cfg",
            ".conf",
            ".json",
            ".lon",
            ".md",
            ".yml",
            ".yaml",
            ".sh",
            ".rc",
            ".shrc",
        ),
    ) -> list[str]:
        """Copy text/Lua files from a host directory into the OpenOS VFS (default `/home`)."""
        raw_str = str(host_dir).strip().strip('"').strip("'")
        src_root = Path(raw_str)
        if not src_root.exists() and "\\" in raw_str and "/" not in raw_str:
            alt_root = Path(raw_str.replace("\\", "/"))
            if alt_root.exists():
                src_root = alt_root
        src_root = src_root.resolve()
        mounted: list[str] = []
        if src_root.is_file():
            target = f"{vfs_dir.rstrip('/')}/{src_root.name}"
            self.vfs.write_file(target, src_root.read_text(encoding="utf-8", errors="replace"))
            return [target]
        if not src_root.is_dir():
            return mounted
        self.vfs.make_directory(vfs_dir)
        for path in sorted(src_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(src_root)
            if any(
                (part.startswith(".") and part not in (".shrc",))
                or part in ("__pycache__", "node_modules", ".git", "venv", ".venv")
                for part in rel.parts
            ):
                continue
            if extensions and path.suffix.lower() not in extensions and path.name not in (".shrc", "LICENSE", "Makefile"):
                continue
            if path.stat().st_size > 256 * 1024:
                continue
            vfs_path = f"{vfs_dir.rstrip('/')}/{rel.as_posix()}"
            parent = "/".join(vfs_path.split("/")[:-1])
            if parent:
                self.vfs.make_directory(parent)
            try:
                self.vfs.write_file(vfs_path, path.read_text(encoding="utf-8", errors="replace"))
                mounted.append(vfs_path)
            except Exception:
                pass
        return mounted

    def start_interactive_shell(self, mount_home: Optional[str | Path] = None) -> None:
        """Boot OpenOS into its interactive `/bin/sh.lua` prompt for live keyboard/screen interaction."""
        if mount_home is not None:
            self.mount_host_dir(mount_home, vfs_dir="/home")
        self.sandbox.machine_host.start_interactive_shell()

    def step_interactive_tick(self, ticks: int = 1) -> bool:
        """Step the interactive OpenOS shell by `ticks` virtual ticks."""
        alive = True
        for _ in range(max(1, int(ticks))):
            alive = self.sandbox.machine_host.step_interactive_tick()
            if not alive:
                break
        return alive

    def send_key(
        self,
        char: str | int = 0,
        key_code: Optional[int] = None,
        ctrl: bool = False,
        alt: bool = False,
        shift: bool = False,
        player: str = "player",
    ) -> None:
        """Queue a `key_down` + `key_up` signal pair (with optional modifier wrapping) on the primary keyboard."""
        if isinstance(char, str):
            ch_code = ord(char[0]) if char else 0
            k_code = (
                int(key_code)
                if key_code is not None
                else _ASCII_TO_OC_KEYCODE.get(char[0].lower() if char else "", 0)
            )
        else:
            ch_code = int(char)
            if 1 <= ch_code <= 26 and key_code is None:
                ch_str = chr(ord("a") + ch_code - 1)
            else:
                ch_str = chr(ch_code) if 0 < ch_code < 128 else ""
            k_code = (
                int(key_code)
                if key_code is not None
                else _ASCII_TO_OC_KEYCODE.get(ch_str.lower(), 0)
            )
        if ctrl and 97 <= ch_code <= 122:
            ch_code = ch_code - 96
        elif ctrl and 65 <= ch_code <= 90:
            ch_code = ch_code - 64

        kb_addr = self.keyboard_comp.address
        p_name = str(player)
        if ctrl:
            self.scheduler.push_signal("key_down", kb_addr, 0, 0x1D, p_name)
        if alt:
            self.scheduler.push_signal("key_down", kb_addr, 0, 0x38, p_name)
        if shift:
            self.scheduler.push_signal("key_down", kb_addr, 0, 0x2A, p_name)

        self.scheduler.push_signal("key_down", kb_addr, ch_code, k_code, p_name)
        if ctrl and k_code == 0x2E:
            self.scheduler.push_signal("interrupted", self.scheduler.uptime())
        self.scheduler.push_signal("key_up", kb_addr, ch_code, k_code, p_name)

        if shift:
            self.scheduler.push_signal("key_up", kb_addr, 0, 0x2A, p_name)
        if alt:
            self.scheduler.push_signal("key_up", kb_addr, 0, 0x38, p_name)
        if ctrl:
            self.scheduler.push_signal("key_up", kb_addr, 0, 0x1D, p_name)

    def send_ctrl_c(self, step_ticks: int = 6, player: str = "player") -> str:
        """Send OpenComputers Ctrl+C (`^C`, keycode 0x2E, char 3) + `interrupted` signal."""
        self.send_key(3, key_code=0x2E, ctrl=True, player=player)
        if step_ticks > 0 and self.sandbox.machine_host._interactive_mode:
            self.step_interactive_tick(step_ticks)
        return self.screen.to_text()

    def send_ctrl_d(self, step_ticks: int = 6, player: str = "player") -> str:
        """Send OpenComputers Ctrl+D (`^D` EOF, keycode 0x20, char 4) with `lcontrol` held."""
        self.send_key(4, key_code=0x20, ctrl=True, player=player)
        if step_ticks > 0 and self.sandbox.machine_host._interactive_mode:
            self.step_interactive_tick(step_ticks)
        return self.screen.to_text()

    def send_ctrl_w(self, step_ticks: int = 4, player: str = "player") -> str:
        """Send OpenComputers Ctrl+W (delete previous word in `core/cursor.lua`)."""
        self.send_key(23, key_code=0x11, ctrl=True, player=player)
        if step_ticks > 0 and self.sandbox.machine_host._interactive_mode:
            self.step_interactive_tick(step_ticks)
        return self.screen.to_text()

    def send_ctrl_l(self, step_ticks: int = 6, player: str = "player") -> str:
        """Clear the interactive OpenOS terminal screen (Ctrl+L)."""
        self.send_key(12, key_code=0x26, ctrl=True, player=player)
        try:
            self.sandbox.lua.execute('require("term").clear()')
        except Exception:
            pass
        if step_ticks > 0 and self.sandbox.machine_host._interactive_mode:
            self.step_interactive_tick(step_ticks)
        return self.screen.to_text()

    def send_clipboard(self, text: str, player: str = "player") -> None:
        """Queue a `clipboard` paste signal on the primary keyboard."""
        self.scheduler.push_signal("clipboard", self.keyboard_comp.address, str(text), str(player))

    def send_touch(
        self,
        x: int,
        y: int,
        button: int = 0,
        player: str = "player",
        include_drop: bool = True,
    ) -> None:
        """Queue a `touch` (and optional `drop`) signal on the primary screen."""
        s_addr = self.screen.screen_address
        self.scheduler.push_signal("touch", s_addr, int(x), int(y), int(button), str(player))
        if include_drop:
            self.scheduler.push_signal("drop", s_addr, int(x), int(y), int(button), str(player))

    def send_text(
        self,
        text: str,
        press_enter: bool = True,
        step_ticks: int = 12,
        use_clipboard: bool = False,
        player: str = "player",
    ) -> str:
        """Type a command or string into the interactive OpenOS shell and step the machine."""
        if not self.sandbox.machine_host._interactive_mode:
            self.start_interactive_shell()
        if use_clipboard and text:
            self.send_clipboard(text, player=player)
            self.step_interactive_tick(2)
        else:
            for ch in str(text):
                if ch == "\n":
                    self.send_key("\r", key_code=0x1C, player=player)
                else:
                    self.send_key(ch, player=player)
                self.step_interactive_tick(1)
        if press_enter:
            self.send_key("\r", key_code=0x1C, player=player)
        if step_ticks > 0:
            self.step_interactive_tick(step_ticks)
        return self.screen.to_text()

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

"""Lupa-based OpenComputers Lua 5.2/5.3 Sandbox and real OpenOS Environment."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..specs.jar_loader import OCJarLoader
from .libs import ALL_28_OPENOS_LIBS
from .machine_host import CPU_CALL_BUDGETS, OCMachineHost, RAM_SIZES_KB, any_lua_type
from .scheduler import DeadlockError, DeterministicScheduler
from .vfs import VirtualFileSystem


class _SandboxLuaAdapter:
    """Adapter exposing `globals()`, `eval()`, `execute()`, `table()`, and memory APIs on `sandbox.lua`."""

    def __init__(self, host: OCMachineHost) -> None:
        self._host = host

    @property
    def raw_lua(self) -> Any:
        return self._host.lua

    def globals(self) -> Any:
        if self._host._sandbox_env is not None:
            return self._host._sandbox_env
        return self._host.lua.globals()

    def table(self, *args: Any, **kwargs: Any) -> Any:
        return self._host.lua.table(*args, **kwargs)

    def table_from(self, *args: Any, **kwargs: Any) -> Any:
        return self._host.lua.table_from(*args, **kwargs)

    def eval(self, lua_expr: str) -> Any:
        env = self.globals()
        loader = self._host.lua.globals()["load"]
        loaded = loader("return " + str(lua_expr), "=(eval)", "t", env)
        fn, err = (loaded[0], loaded[1] if len(loaded) > 1 else None) if isinstance(loaded, tuple) else (loaded, None)
        if fn is None:
            loaded = loader(str(lua_expr), "=(eval)", "t", env)
            fn, err = (loaded[0], loaded[1] if len(loaded) > 1 else None) if isinstance(loaded, tuple) else (loaded, None)
        if fn is None:
            raise RuntimeError(f"Lua eval syntax error: {err}")
        return fn()

    def execute(self, lua_code: str) -> Any:
        env = self.globals()
        loader = self._host.lua.globals()["load"]
        loaded = loader(str(lua_code), "=(execute)", "t", env)
        fn, err = (loaded[0], loaded[1] if len(loaded) > 1 else None) if isinstance(loaded, tuple) else (loaded, None)
        if fn is None:
            raise RuntimeError(f"Lua execute syntax error: {err}")
        return fn()

    def get_memory_used(self) -> int:
        return self._host.lua.get_memory_used()

    def get_max_memory(self) -> int:
        return self._host.lua.get_max_memory()

    def set_max_memory(self, max_bytes: int) -> None:
        self._host.lua.set_max_memory(max_bytes)


class OCLuaSandbox:
    """Isolated OpenComputers Lua 5.3 / 5.2 runtime booting real `machine.lua` -> `bios.lua` -> OpenOS."""

    def __init__(
        self,
        host: str = "computer",
        jar_loader: Optional[OCJarLoader] = None,
        component_bus: Optional[Any] = None,
        gpu_screen: Optional[Any] = None,
        architecture: str = "Lua 5.3",
        ram_tier: int = 6,
        cpu_tier: int = 3,
        allow_bytecode: bool = False,
        allow_gc: bool = False,
        timeout: float = 5.0,
        enforce_call_budget: bool = False,
    ) -> None:
        self.host = host
        self.jar_loader = jar_loader or OCJarLoader()
        self.scheduler = DeterministicScheduler()
        self.vfs = VirtualFileSystem(initial_files=self.jar_loader.list_openos_files())
        self.component_bus = component_bus
        self.gpu_screen = gpu_screen

        self.computer_address = "c0000000-0000-4000-8000-000000000001"
        self.energy = 10000.0
        self.max_energy = 10000.0
        self.beeps: List[Tuple[Any, float]] = []
        self.stdout_lines: List[str] = []
        self.stdin_queue: List[str] = []
        self.http_mock_responses: Dict[str, str] = {}
        self.is_shutdown = False
        self.reboot_requested = False

        self.machine_host = OCMachineHost(
            sandbox=self,
            architecture=architecture,
            ram_tier=ram_tier,
            cpu_tier=cpu_tier,
            allow_bytecode=allow_bytecode,
            allow_gc=allow_gc,
            timeout=timeout,
            enforce_call_budget=enforce_call_budget,
        )
        self.lua = _SandboxLuaAdapter(self.machine_host)
        self.machine_host.boot()
        self._install_fallbacks()

    @property
    def free_memory(self) -> int:
        return self.machine_host.free_memory()

    @property
    def total_memory(self) -> int:
        return self.machine_host.total_memory()

    def _install_fallbacks(self) -> None:
        """Ensure `require('internet')` and `require('robot')` work even when optional cards aren't attached."""
        env = self.lua.globals()
        self.machine_host.lua.globals()["__oc_http_mock"] = (
            lambda url, data=None, headers=None, method=None: self.http_mock_responses.get(str(url), "")
        )
        # Note: all 28 OpenOS libraries exist in `/lib/*.lua` and load from real OpenOS Lua files via `require`.
        # Ensure `bit32` is registered in `package.loaded["bit32"]` in the booted OpenOS `package` table.
        self.lua.execute(
            r"""
            do
              local pkg = require("package")
              if _G.bit32 and not pkg.loaded["bit32"] then
                pkg.loaded["bit32"] = _G.bit32
              end
              -- Re-remove any host bridge symbols from sandbox _G
              _G.python = nil
              _G.__oc_bridge = nil
              if _G.string then
                _G.string.dump = nil
              end
              if _G.io then
                _G.io.popen = nil
              end
            end
            """
        )

    def bind_component_library(self, lua_component_lib: Any = None) -> None:
        """Keep the real OpenOS `component` library (`machine.lua` + `boot/04_component.lua`)."""
        # Remove `__oc_comp_bridge` if `ComponentBus.build_lua_component_library` placed it in sandbox globals
        env = self.lua.globals()
        if env["__oc_comp_bridge"] is not None:
            env["__oc_comp_bridge"] = None

    def python_to_lua(self, value: Any) -> Any:
        """Recursively convert Python dicts/lists/tuples into Lua tables."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if any_lua_type(value) is not None:
            return value
        if hasattr(value, "__oc_lua_proxy__"):
            return value.__oc_lua_proxy__(self)
        if isinstance(value, (list, tuple)):
            tbl = self.lua.table()
            for idx, item in enumerate(value, start=1):
                tbl[idx] = self.python_to_lua(item)
            tbl["n"] = len(value)
            return tbl
        if isinstance(value, dict):
            tbl = self.lua.table()
            for k, v in value.items():
                tbl[self.python_to_lua(k)] = self.python_to_lua(v)
            return tbl
        return value

    def lua_to_python(self, value: Any) -> Any:
        """Recursively convert Lua tables into Python lists or dicts."""
        ltype = any_lua_type(value)
        if ltype == "table":
            items = list(value.items())
            if not items:
                return {}
            keys = [k for k, _ in items if k != "n"]
            if keys and all(isinstance(k, int) for k in keys):
                sorted_keys = sorted(keys)
                if sorted_keys == list(range(1, len(sorted_keys) + 1)):
                    return [self.lua_to_python(value[k]) for k in sorted_keys]
            return {
                self.lua_to_python(k): self.lua_to_python(v)
                for k, v in items
            }
        return value

    def execute(self, lua_code: str, chunk_name: str = "=script.lua") -> Any:
        return self.machine_host.execute_in_sandbox(lua_code, chunk_name=chunk_name)

    def run_file(self, vfs_or_host_path: str) -> Any:
        if self.vfs.exists(vfs_or_host_path):
            code = self.vfs.read_file(vfs_or_host_path)
            if code is None:
                raise FileNotFoundError(f"Cannot read VFS file: {vfs_or_host_path}")
            return self.execute(code, chunk_name=f"={vfs_or_host_path}")
        with open(vfs_or_host_path, "r", encoding="utf-8") as f:
            code = f.read()
        self.vfs.write_file("/home/script.lua", code)
        return self.execute(code, chunk_name=f"={vfs_or_host_path}")

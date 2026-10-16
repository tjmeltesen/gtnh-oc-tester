"""Lupa-based OpenComputers Lua 5.2/5.3 Sandbox and OpenOS Environment."""

from __future__ import annotations

import posixpath
from typing import Any, Callable, Dict, List, Optional, Tuple
import unicodedata

from lupa import LuaRuntime, lua_type

from ..specs.jar_loader import OCJarLoader
from .libs import ALL_28_OPENOS_LIBS, OPENOS_BOOTSTRAP_LUA
from .scheduler import DeterministicScheduler
from .vfs import VirtualFileSystem


def _char_width(ch: str) -> int:
    if not ch:
        return 0
    eaw = unicodedata.east_asian_width(ch[0])
    return 2 if eaw in ("W", "F") else 1


class _OCBridge:
    """Bridge exposed inside Lua as `__oc_bridge` for system calls."""

    def __init__(self, sandbox: "OCLuaSandbox") -> None:
        self.sandbox = sandbox

    # Unicode helpers
    def unicode_len(self, s: str) -> int:
        return len(s)

    def unicode_sub(self, s: str, i: int, j: Optional[int] = None) -> str:
        n = len(s)
        start = i - 1 if i > 0 else max(0, n + i)
        if j is None:
            return s[start:]
        end = j if j >= 0 else max(0, n + j + 1)
        return s[max(0, start) : max(0, end)]

    def unicode_lower(self, s: str) -> str:
        return s.lower()

    def unicode_upper(self, s: str) -> str:
        return s.upper()

    def unicode_reverse(self, s: str) -> str:
        return s[::-1]

    def unicode_char(self, *codes: int) -> str:
        return "".join(chr(int(c)) for c in codes)

    def unicode_wlen(self, s: str) -> int:
        return sum(_char_width(c) for c in s)

    def unicode_wtrunc(self, s: str, count: int) -> str:
        width = 0
        out: List[str] = []
        target = int(count)
        for ch in s:
            cw = _char_width(ch)
            if width + cw >= target:
                break
            out.append(ch)
            width += cw
        return "".join(out)

    def unicode_char_width(self, s: str) -> int:
        return _char_width(s[0]) if s else 0

    # Computer / Scheduler helpers
    def uptime(self) -> float:
        return self.sandbox.scheduler.uptime()

    def sleep(self, seconds: float = 0.05) -> None:
        self.sandbox.scheduler.sleep(seconds)

    def computer_address(self) -> str:
        return self.sandbox.computer_address

    def tmp_address(self) -> str:
        return self.sandbox.vfs.tmp_address

    def root_fs_address(self) -> str:
        return self.sandbox.vfs.root_address

    def free_memory(self) -> int:
        return self.sandbox.free_memory

    def total_memory(self) -> int:
        return self.sandbox.total_memory

    def energy(self) -> float:
        return self.sandbox.energy

    def max_energy(self) -> float:
        return self.sandbox.max_energy

    def is_robot(self) -> bool:
        return self.sandbox.host == "robot"

    def beep(self, freq: object = 440, dur: float = 0.1) -> bool:
        self.sandbox.beeps.append((freq, dur))
        return True

    def shutdown(self, reboot: bool = False) -> bool:
        self.sandbox.is_shutdown = True
        self.sandbox.reboot_requested = bool(reboot)
        return True

    def push_signal(self, name: str, *args: Any) -> bool:
        py_args = tuple(self.sandbox.lua_to_python(a) for a in args)
        return self.sandbox.scheduler.push_signal(name, *py_args)

    def pull_signal(self, timeout: Optional[float] = None, *filters: Any) -> Any:
        filter_name = str(filters[0]) if filters and filters[0] is not None else None
        filter_args = filters[1:] if len(filters) > 1 else ()
        result = self.sandbox.scheduler.pull_signal(timeout, filter_name, *filter_args)
        return self.sandbox.python_to_lua(list(result))

    def listen(self, name: str, callback: Callable[..., Any]) -> bool:
        return self.sandbox.scheduler.register_listener(name, callback)

    def ignore(self, name: str, callback: Callable[..., Any]) -> bool:
        return self.sandbox.scheduler.unregister_listener(name, callback)

    def timer(self, interval: float, callback: Callable[[], Any], times: float = 1) -> int:
        return self.sandbox.scheduler.register_timer(interval, callback, times)

    def cancel_timer(self, timer_id: int) -> bool:
        return self.sandbox.scheduler.cancel_timer(timer_id)

    # Filesystem helpers
    def fs_canonical(self, path: str) -> str:
        return self.sandbox.vfs.canonical(path)

    def fs_segments(self, path: str) -> Any:
        segs = self.sandbox.vfs.segments(path)
        return self.sandbox.python_to_lua(segs)

    def fs_concat(self, *parts: str) -> str:
        cleaned = [str(p) for p in parts if p is not None]
        if not cleaned:
            return "/"
        return self.sandbox.vfs.canonical(posixpath.join(*cleaned))

    def fs_path(self, path: str) -> str:
        c = self.sandbox.vfs.canonical(path)
        parent = posixpath.dirname(c)
        return parent if parent.endswith("/") else parent + "/"

    def fs_name(self, path: str) -> str:
        return posixpath.basename(self.sandbox.vfs.canonical(path).rstrip("/"))

    def fs_exists(self, path: str) -> bool:
        return self.sandbox.vfs.exists(path)

    def fs_is_directory(self, path: str) -> bool:
        return self.sandbox.vfs.is_directory(path)

    def fs_make_directory(self, path: str) -> bool:
        return self.sandbox.vfs.make_directory(path)

    def fs_size(self, path: str) -> int:
        return self.sandbox.vfs.size(path)

    def fs_last_modified(self, path: str) -> int:
        return self.sandbox.vfs.last_modified(path)

    def fs_remove(self, path: str) -> bool:
        return self.sandbox.vfs.remove(path)

    def fs_rename(self, old_path: str, new_path: str) -> bool:
        return self.sandbox.vfs.rename(old_path, new_path)

    def fs_copy(self, from_path: str, to_path: str) -> bool:
        return self.sandbox.vfs.copy(from_path, to_path)

    def fs_list(self, path: str) -> Any:
        return self.sandbox.python_to_lua(self.sandbox.vfs.list_dir(path))

    def fs_open(self, path: str, mode: str = "r") -> Any:
        handle, err = self.sandbox.vfs.open(path, mode)
        if handle is None:
            return self.sandbox.python_to_lua([None, err])
        lua_handle = self.sandbox.lua.eval(
            """
            function(py_h)
              local h = {}
              function h:read(fmt) return py_h.read(fmt) end
              function h:write(...) return py_h.write(...) end
              function h:seek(whence, offset) return py_h.seek(whence or "cur", offset or 0) end
              function h:lines() return py_h.lines() end
              function h:flush() return py_h.flush() end
              function h:close() return py_h.close() end
              return h
            end
            """
        )(handle)
        return self.sandbox.python_to_lua([lua_handle, None])

    def get_fs_proxy(self, path: str) -> Any:
        if self.sandbox.component_bus is not None:
            try:
                return self.sandbox.component_bus.get_primary("filesystem")
            except Exception:
                pass
        return self.sandbox.python_to_lua({"address": self.sandbox.vfs.root_address, "type": "filesystem"})

    def get_cwd(self) -> str:
        return self.sandbox.vfs.cwd

    def set_cwd(self, path: str) -> bool:
        canon = self.sandbox.vfs.canonical(path)
        if self.sandbox.vfs.is_directory(canon):
            self.sandbox.vfs.cwd = canon
            return True
        return False

    # Terminal / Screen helpers
    def term_clear(self) -> bool:
        if self.sandbox.gpu_screen is not None:
            self.sandbox.gpu_screen.term_clear()
        return True

    def term_clear_line(self) -> bool:
        if self.sandbox.gpu_screen is not None:
            self.sandbox.gpu_screen.term_clear_line()
        return True

    def term_get_cursor(self) -> Any:
        if self.sandbox.gpu_screen is not None:
            return self.sandbox.python_to_lua(list(self.sandbox.gpu_screen.get_cursor()))
        return self.sandbox.python_to_lua([1, 1])

    def term_set_cursor(self, col: int, row: int) -> None:
        if self.sandbox.gpu_screen is not None:
            self.sandbox.gpu_screen.set_cursor(int(col), int(row))

    def term_get_viewport(self) -> Any:
        if self.sandbox.gpu_screen is not None:
            w, h = self.sandbox.gpu_screen.get_resolution()
            return self.sandbox.python_to_lua([w, h, 0, 0, 1, 1])
        return self.sandbox.python_to_lua([80, 25, 0, 0, 1, 1])

    def term_write(self, text: str, wrap: bool = True) -> None:
        self.sandbox.stdout_lines.append(str(text))
        if self.sandbox.gpu_screen is not None:
            self.sandbox.gpu_screen.term_write(str(text), wrap=bool(wrap))

    def term_read(self) -> str:
        if self.sandbox.stdin_queue:
            return self.sandbox.stdin_queue.pop(0)
        return ""

    # Internet helper
    def http_request(
        self,
        url: str,
        data: Optional[str] = None,
        headers: Optional[Any] = None,
        method: Optional[str] = None,
    ) -> str:
        return self.sandbox.http_mock_responses.get(str(url), "")


class OCLuaSandbox:
    """Isolated OpenComputers Lua runtime with VFS, scheduler, and all 28 OpenOS libraries."""

    def __init__(
        self,
        host: str = "computer",
        jar_loader: Optional[OCJarLoader] = None,
        component_bus: Optional[Any] = None,
        gpu_screen: Optional[Any] = None,
    ) -> None:
        self.host = host
        self.jar_loader = jar_loader or OCJarLoader()
        self.scheduler = DeterministicScheduler()
        self.vfs = VirtualFileSystem(initial_files=self.jar_loader.list_openos_files())
        self.component_bus = component_bus
        self.gpu_screen = gpu_screen

        self.computer_address = "c0000000-0000-4000-8000-000000000001"
        self.free_memory = 1572864
        self.total_memory = 2097152
        self.energy = 10000.0
        self.max_energy = 10000.0
        self.beeps: List[Tuple[Any, float]] = []
        self.stdout_lines: List[str] = []
        self.stdin_queue: List[str] = []
        self.http_mock_responses: Dict[str, str] = {}
        self.is_shutdown = False
        self.reboot_requested = False

        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self._bridge = _OCBridge(self)
        self._setup_environment()

    def _setup_environment(self) -> None:
        g = self.lua.globals()
        g["__oc_bridge"] = self._bridge

        # Override print to write to term/stdout_lines
        def _lua_print(*args: Any) -> None:
            line = "\t".join("nil" if a is None else str(a) for a in args)
            self._bridge.term_write(line + "\n", True)

        g["print"] = _lua_print

        # Execute core OpenOS bootstrap
        self.lua.execute(OPENOS_BOOTSTRAP_LUA)

        # Ensure custom module searcher reads from VFS `/lib/<name>.lua` or `/home/<name>.lua`
        self.lua.execute(
            r"""
            package.loaded["package"] = package
            function package.delay(lib, file)
              local mt = {}
              function mt.__index(tbl, key)
                mt.__index = nil
                dofile(file)
                return tbl[key]
              end
              if lib.internal then
                setmetatable(lib.internal, mt)
              end
              setmetatable(lib, mt)
            end

            local vfs_searcher = function(modname)
              local rel = modname:gsub("%.", "/")
              local candidates = {
                "/lib/" .. rel .. ".lua",
                "/home/" .. rel .. ".lua",
                "/" .. rel .. ".lua",
              }
              for _, p in ipairs(candidates) do
                if __oc_bridge.fs_exists(p) and not __oc_bridge.fs_is_directory(p) then
                  local f = io.open(p, "r")
                  if f then
                    local src = f:read("*a")
                    f:close()
                    local fn, err = load(src, "=" .. p)
                    if fn then return fn end
                    return "\n\t" .. tostring(err)
                  end
                end
              end
              return "\n\tno file in VFS for '" .. tostring(modname) .. "'"
            end
            local searchers = package.searchers or package.loaders
            table.insert(searchers, 2, vfs_searcher)

            function loadfile(filename, mode, env)
              local f, err = io.open(filename, "r")
              if not f then return nil, err end
              local src = f:read("*a")
              f:close()
              if env then
                return load(src, "=" .. filename, mode or "bt", env)
              end
              return load(src, "=" .. filename, mode or "bt")
            end

            function dofile(filename)
              local fn, err = loadfile(filename)
              if not fn then error(err) end
              return fn()
            end
            """
        )

        # Load pure-Lua OpenOS libraries directly from OpenComputers-1.12.62-GTNH.jar assets
        native_libs = [
            "colors",
            "sides",
            "serialization",
            "transforms",
            "text",
            "vt100",
            "uuid",
            "note",
            "nbt",
        ]
        for lib_name in native_libs:
            code = self.jar_loader.read_asset_text(f"loot/openos/lib/{lib_name}.lua")
            if code:
                try:
                    mod = self.lua.execute(code)
                    if mod is not None:
                        g["package"]["loaded"][lib_name] = mod
                except Exception:
                    pass

    def bind_component_library(self, lua_component_lib: Any) -> None:
        g = self.lua.globals()
        g["component"] = lua_component_lib
        g["package"]["loaded"]["component"] = lua_component_lib

    def python_to_lua(self, value: Any) -> Any:
        """Recursively convert Python dicts/lists/tuples into Lua tables."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if lua_type(value) is not None:
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
        ltype = lua_type(value)
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
        loader = self.lua.globals()["load"]
        loaded = loader(lua_code, chunk_name)
        if isinstance(loaded, tuple):
            fn, err = loaded[0], loaded[1] if len(loaded) > 1 else "unknown error"
        else:
            fn, err = loaded, None
        if fn is None:
            raise RuntimeError(f"Lua syntax error in {chunk_name}: {err}")
        return fn()

    def run_file(self, vfs_or_host_path: str) -> Any:
        if self.vfs.exists(vfs_or_host_path):
            code = self.vfs.read_file(vfs_or_host_path) or ""
            return self.execute(code, chunk_name=f"={vfs_or_host_path}")
        with open(vfs_or_host_path, "r", encoding="utf-8") as f:
            code = f.read()
        self.vfs.write_file("/home/script.lua", code)
        return self.execute(code, chunk_name=f"={vfs_or_host_path}")

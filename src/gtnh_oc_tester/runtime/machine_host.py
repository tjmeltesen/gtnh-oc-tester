"""Real OpenComputers `machine.lua` -> `bios.lua` -> OpenOS boot host."""

from __future__ import annotations

import inspect
import math
from typing import Any, Callable, Dict, List, Optional, Tuple
import unicodedata

from lupa import lua_type as lua54_type
from lupa.lua52 import LuaRuntime as Lua52Runtime, lua_type as lua52_type
from lupa.lua53 import LuaRuntime as Lua53Runtime, lua_type as lua53_type

from ..specs.jar_loader import OCJarLoader
from .scheduler import DeadlockError, DeterministicScheduler
from .vfs import VirtualFileSystem


def any_lua_type(value: Any) -> Optional[str]:
    """Return the Lua type name of a Lupa object across Lua 5.3, 5.2, and 5.4 runtimes."""
    return lua53_type(value) or lua52_type(value) or lua54_type(value)


def _strict_lua_attribute_filter(obj: Any, attr_name: Any, is_setting: bool) -> Any:
    """Block Lua access to private/dunder Python attributes, attribute mutation, and raw function attributes."""
    name = str(attr_name)
    if is_setting or name.startswith("_"):
        raise AttributeError(f"Sandbox access denied to Python attribute {name!r}")
    if inspect.isfunction(obj) or inspect.ismethod(obj) or inspect.isbuiltin(obj):
        raise AttributeError(f"Sandbox access denied to Python callable attribute {name!r}")
    return attr_name


# OpenComputers default RAM tier sizes in KiB (1 = T1, 2 = T1.5, 3 = T2, 4 = T2.5, 5 = T3, 6 = T3.5)
RAM_SIZES_KB: Tuple[int, ...] = (192, 256, 384, 512, 768, 1024)
CPU_CALL_BUDGETS: Dict[int, float] = {1: 0.5, 2: 1.0, 3: 1.5}


def _char_width(ch: str) -> int:
    if not ch:
        return 0
    eaw = unicodedata.east_asian_width(ch[0])
    return 2 if eaw in ("W", "F") else 1


OPENOS_INIT_RUNNER_PATCH = r"""
do
  require("tty").window.nowrap = false
  local computer = require("computer")
  local component = require("component")
  local unicode = require("unicode")
  local event = require("event")
  local fs = require("filesystem")
  local shell = require("shell")
  local process = require("process")
  local package = require("package")

  -- Extend package.path so mounted /home projects (e.g. AE2MES & AE2-ES with src/ and lib/ subdirs) resolve cleanly
  package.path = package.path .. ";/home/?.lua;/home/?/init.lua;/home/src/?.lua;/home/src/?/init.lua;/home/lib/?.lua;/home/lib/?/init.lua;./src/?.lua;./lib/?.lua"

  -- Ensure process.findProcess falls back to the root init process if invoked from host eval
  local init_proc = process.info()
  local orig_findProcess = process.findProcess
  process.findProcess = function(co)
    local ok, p = pcall(orig_findProcess, co)
    if ok and p then
      return p
    end
    return init_proc
  end

  -- Trigger all package.delay lazy extensions while inside the init process coroutine
  local _ = event.timer
  _ = fs.isAutorunEnabled
  _ = shell.getShell
  _ = require("text").trim
  _ = require("buffer").freeMemory
  _ = require("vt100").parse
  _ = require("sh").expand
  _ = require("transforms").sub

  -- Route event.timer / event.listen callback errors to /tmp/event.log, stderr, and the host error tracker
  local orig_event_onError = event.onError
  event.onError = function(message)
    local msg_str = tostring(message)
    if orig_event_onError then
      pcall(orig_event_onError, msg_str)
    end
    if io.stderr then
      pcall(io.stderr.write, io.stderr, "[event.onError] " .. msg_str .. "\n")
    end
    if __oc_on_event_error then
      __oc_on_event_error(msg_str)
    end
  end

  _G.computer = computer
  _G.component = component
  _G.unicode = unicode
  fs.makeDirectory("/home")
  shell.setWorkingDirectory("/home")
  os.setenv("PWD", "/home")

  _G.runlevel = 1
  event.push("init")
  event.pull(0, "init")
  if __oc_initial_w and __oc_initial_h then
    local gpu_addr = component.list("gpu", true)()
    if gpu_addr then
      pcall(component.invoke, gpu_addr, "setResolution", __oc_initial_w, __oc_initial_h)
    end
  end
  require("term").clear()

  if rawget(_G, "__oc_interactive_shell") then
    while true do
      local sh_fn, sh_reason = require("shell").getShell()
      if not sh_fn then
        io.stderr:write((sh_reason ~= nil and tostring(sh_reason) or "cannot load shell") .. "\n")
        os.sleep(0.5)
      else
        local result, reason = xpcall(sh_fn, function(msg)
          if type(msg) == "table" and msg.reason == "terminated" then
            return nil
          end
          return tostring(msg) .. "\n" .. debug.traceback()
        end)
        if not result and reason then
          io.stderr:write(tostring(reason) .. "\n")
        end
      end
    end
  end

  while true do
    local sig = table.pack(__oc_raw_pull(0))
    if sig[1] == "__host_interactive_shell" then
      while true do
        local sh_fn, sh_reason = require("shell").getShell()
        if not sh_fn then
          io.stderr:write((sh_reason ~= nil and tostring(sh_reason) or "cannot load shell") .. "\n")
          os.sleep(0.5)
        else
          local result, reason = xpcall(sh_fn, function(msg)
            if type(msg) == "table" and msg.reason == "terminated" then
              return nil
            end
            return tostring(msg) .. "\n" .. debug.traceback()
          end)
          if not result and reason then
            io.stderr:write(tostring(reason) .. "\n")
          end
        end
      end
    elseif sig[1] == "__host_exec" then
      local code = sig[2]
      local chunk_name = sig[3] or "=script.lua"
      local fn, err = load(code, chunk_name, "t", _G)
      if not fn then
        __oc_record_result(false, "Lua syntax error in " .. tostring(chunk_name) .. ": " .. tostring(err))
      else
        local res = table.pack(xpcall(fn, debug.traceback))
        __oc_record_result(table.unpack(res, 1, res.n))
      end
    end
  end
end
"""


class OCMachineHost:
    """Hosts and drives OpenComputers' real `machine.lua`, `bios.lua`, and OpenOS inside Lupa Lua 5.2 / 5.3."""

    def __init__(
        self,
        sandbox: Any,
        architecture: str = "Lua 5.2",
        ram_tier: int = 6,
        cpu_tier: int = 3,
        allow_bytecode: bool = False,
        allow_gc: bool = False,
        timeout: float = 5.0,
        enforce_call_budget: bool = True,
        ram_scale_for_64bit: float = 1.8,
    ) -> None:
        self.sandbox = sandbox
        self.architecture = str(architecture or "Lua 5.2")
        if self.architecture not in ("Lua 5.3", "Lua 5.2"):
            raise ValueError(f"Unsupported Lua architecture: {self.architecture!r} (expected 'Lua 5.3' or 'Lua 5.2')")
        self.ram_tier = max(1, min(len(RAM_SIZES_KB), int(ram_tier)))
        self.cpu_tier = max(1, min(3, int(cpu_tier)))
        self.allow_bytecode = bool(allow_bytecode)
        self.allow_gc = bool(allow_gc)
        self.timeout = float(timeout)
        self.enforce_call_budget = bool(enforce_call_budget)
        self.ram_scale_for_64bit = max(1.0, float(ram_scale_for_64bit))

        self.total_memory_bytes: int = RAM_SIZES_KB[self.ram_tier - 1] * 1024
        self.call_budget_max: float = CPU_CALL_BUDGETS.get(self.cpu_tier, 1.5)
        self.call_budget_remaining: float = self.call_budget_max
        # Used only during initial calcHookInterval() bogomips calibration before baseline yield
        self.cpu_time_step_per_check: float = 0.01
        self._in_bogomips: bool = True

        self.boot_address: str = self.sandbox.vfs.root_address
        self.users_list: List[str] = ["player"]
        self.tmp_vfs = VirtualFileSystem(
            max_bytes=64 * 1024,
            read_only=False,
            label="tmpfs",
        )
        self.tmp_vfs.root_address = self.sandbox.vfs.tmp_address

        runtime_cls = Lua52Runtime if self.architecture == "Lua 5.2" else Lua53Runtime
        # Give VM overhead headroom for machine.lua + OpenOS boot, then tighten after boot against baseline
        self._vm_overhead_bytes: int = 4 * 1024 * 1024
        self.lua = runtime_cls(
            unpack_returned_tuples=True,
            register_eval=False,
            register_builtins=False,
            attribute_filter=_strict_lua_attribute_filter,
            max_memory=self.total_memory_bytes + self._vm_overhead_bytes,
        )
        self._baseline_memory: int = 0
        self._machine_co: Any = None
        self._sandbox_env: Any = None
        self._last_exec_result: Optional[Tuple[bool, Tuple[Any, ...]]] = None
        self._booted: bool = False
        self._in_sync_call: bool = False
        self._interactive_mode: bool = False
        self._interactive_wait_deadline: float = math.inf

    @property
    def scheduler(self) -> DeterministicScheduler:
        return self.sandbox.scheduler

    @property
    def vfs(self) -> VirtualFileSystem:
        return self.sandbox.vfs

    @property
    def jar_loader(self) -> OCJarLoader:
        return self.sandbox.jar_loader

    def free_memory(self) -> int:
        used_raw = max(0, self.lua.get_memory_used() - self._baseline_memory)
        used_scaled = int(used_raw / self.ram_scale_for_64bit)
        return max(0, self.total_memory_bytes - used_scaled)

    def total_memory(self) -> int:
        return self.total_memory_bytes

    def reset_call_budget(self) -> None:
        self.call_budget_remaining = self.call_budget_max

    def _populate_extra_assets(self) -> None:
        """Ensure `/init.lua`, `/lib/robot.lua`, and `/bin/go.lua` exist in root VFS for OpenOS."""
        init_src = self.jar_loader.read_asset_text("loot/openos/init.lua")
        if not init_src:
            raise RuntimeError("Missing OpenOS /init.lua in OpenComputers assets")
        # Patch /init.lua to capture raw computer.pullSignal and one-shot host hooks in local upvalues
        # before event.lua or any user script runs, so _G / _ENV never expose host callbacks.
        marker = "while true do\n  local result, reason = xpcall(require(\"shell\").getShell()"
        init_w = getattr(self.sandbox.gpu_screen, "initial_width", None)
        init_h = getattr(self.sandbox.gpu_screen, "initial_height", None)
        header = (
            "local __oc_raw_pull = computer.pullSignal\n"
            "local __oc_take_hooks = computer.__oc_take_host_hooks\n"
            "computer.__oc_take_host_hooks = nil\n"
            "local __oc_record_result, __oc_on_event_error = __oc_take_hooks()\n"
            "__oc_take_hooks = nil\n"
            f"local __oc_initial_w, __oc_initial_h = {int(init_w) if init_w else 'nil'}, {int(init_h) if init_h else 'nil'}\n"
        )
        patched_init = header + init_src.replace(
            marker,
            OPENOS_INIT_RUNNER_PATCH + "\n" + marker,
        )
        self.vfs.write_file("/init.lua", patched_init)

        robot_lib_src = self.jar_loader.read_asset_text("lua/component/robot/lib/robot.lua")
        if robot_lib_src and not self.vfs.exists("/lib/robot.lua"):
            self.vfs.write_file("/lib/robot.lua", robot_lib_src)
        robot_go_src = self.jar_loader.read_asset_text("lua/component/robot/bin/go.lua")
        if robot_go_src and not self.vfs.exists("/bin/go.lua"):
            self.vfs.write_file("/bin/go.lua", robot_go_src)

        internet_lib_src = self.jar_loader.read_asset_text("lua/component/internet/lib/internet.lua")
        if internet_lib_src and not self.vfs.exists("/lib/internet.lua"):
            self.vfs.write_file("/lib/internet.lua", internet_lib_src)

        data_bin_md5 = self.jar_loader.read_asset_text("lua/component/data/bin/md5sum.lua")
        if data_bin_md5 and not self.vfs.exists("/bin/md5sum.lua"):
            self.vfs.write_file("/bin/md5sum.lua", data_bin_md5)

    # -------------------------------------------------------------------------
    # Host-side component dispatch (for rootfs, tmpfs, eeprom, computer, screen, gpu, and ComponentBus)
    # -------------------------------------------------------------------------

    def _list_all_components(
        self,
        filter_str: Optional[str] = None,
        exact: Optional[bool] = None,
    ) -> Dict[str, str]:
        entries: Dict[str, str] = {
            self.vfs.root_address: "filesystem",
            self.vfs.tmp_address: "filesystem",
            self.sandbox.computer_address: "computer",
            "e0000000-0000-4000-8000-000000000001": "eeprom",
        }
        if self.sandbox.gpu_screen is not None:
            entries[self.sandbox.gpu_screen.screen_address] = "screen"
            entries["g0000000-0000-4000-8000-000000000001"] = "gpu"
            entries["k0000000-0000-4000-8000-000000000001"] = "keyboard"
        if self.sandbox.host == "robot":
            entries["r0000000-0000-4000-8000-000000000001"] = "robot"
        elif self.sandbox.host == "tablet":
            entries["t0000000-0000-4000-8000-000000000001"] = "tablet"

        if self.sandbox.component_bus is not None:
            for addr, comp in self.sandbox.component_bus.components.items():
                entries[addr] = comp.component_type

        if filter_str is None or filter_str == "":
            return entries
        is_exact = bool(exact) if exact is not None else True
        out: Dict[str, str] = {}
        for addr, ctype in entries.items():
            if is_exact:
                if ctype == filter_str:
                    out[addr] = ctype
            else:
                if str(filter_str) in ctype:
                    out[addr] = ctype
        if not out and self._booted and self.sandbox.component_bus is not None:
            out.update(self.sandbox.component_bus.list_matching(str(filter_str), is_exact))
        return out

    def _get_component_type(self, address: str) -> Optional[str]:
        all_c = self._list_all_components()
        addr = str(address)
        if addr in all_c:
            return all_c[addr]
        if self._booted and self.sandbox.component_bus is not None:
            comp = self.sandbox.component_bus.get_component(
                addr,
                auto_create=self.sandbox.component_bus.auto_mock_missing,
            )
            if comp is not None:
                return comp.component_type
        return None

    def _get_component_slot(self, address: str) -> int:
        if self.sandbox.component_bus is not None:
            comp = self.sandbox.component_bus.get_component(
                str(address),
                auto_create=bool(self._booted and self.sandbox.component_bus.auto_mock_missing),
            )
            if comp is not None:
                return comp.slot
        if str(address) == self.vfs.root_address:
            return 1
        return -1

    def _get_vfs_for_address(self, address: str) -> Optional[VirtualFileSystem]:
        if str(address) == self.vfs.root_address:
            return self.vfs
        if str(address) == self.vfs.tmp_address:
            return self.tmp_vfs
        if self.sandbox.component_bus is not None:
            comp = self.sandbox.component_bus.get_component(str(address))
            if comp is not None and hasattr(comp, "vfs") and isinstance(comp.vfs, VirtualFileSystem):
                return comp.vfs
        return None

    def _invoke_vfs(self, vfs_obj: VirtualFileSystem, method: str, *args: Any) -> Any:
        m = str(method)
        if m == "open":
            path = str(args[0]) if args else "/"
            mode = str(args[1]) if len(args) > 1 and args[1] is not None else "r"
            if (
                self._booted
                and self.sandbox.component_bus is not None
                and self.sandbox.component_bus.auto_mock_missing
                and path.endswith(".lua")
                and vfs_obj.exists(path)
            ):
                content = vfs_obj.read_file(path)
                if content:
                    self.sandbox.component_bus.scan_and_register_lua_declarations(content)
            hid, err = vfs_obj.open_handle(path, mode)
            if hid is None:
                return (None, err or str(path))
            return hid
        if m == "read":
            hid = int(args[0])
            count = args[1] if len(args) > 1 and args[1] is not None else math.inf
            return vfs_obj.read_handle(hid, count)
        if m == "write":
            hid = int(args[0])
            data = args[1] if len(args) > 1 else ""
            return vfs_obj.write_handle(hid, data)
        if m == "close":
            hid = int(args[0])
            vfs_obj.close_handle(hid)
            return None
        if m == "seek":
            hid = int(args[0])
            whence = str(args[1]) if len(args) > 1 and args[1] is not None else "cur"
            offset = int(args[2]) if len(args) > 2 and args[2] is not None else 0
            return vfs_obj.seek_handle(hid, whence, offset)
        if m == "makeDirectory":
            return vfs_obj.make_directory(str(args[0]) if args else "/")
        if m == "exists":
            return vfs_obj.exists(str(args[0]) if args else "/")
        if m == "isDirectory":
            return vfs_obj.is_directory(str(args[0]) if args else "/")
        if m == "rename":
            return vfs_obj.rename(str(args[0]), str(args[1]))
        if m == "copy":
            return vfs_obj.copy(str(args[0]), str(args[1]))
        if m == "remove":
            return vfs_obj.remove(str(args[0]) if args else "/")
        if m == "lastModified":
            return vfs_obj.last_modified(str(args[0]) if args else "/")
        if m == "spaceUsed":
            return vfs_obj.space_used()
        if m == "spaceTotal":
            return vfs_obj.space_total()
        if m == "isReadOnly":
            return vfs_obj.is_read_only()
        if m == "list":
            return vfs_obj.list_dir(str(args[0]) if args and args[0] is not None else "/")
        if m == "size":
            return vfs_obj.size(str(args[0]) if args else "/")
        if m == "getLabel":
            return vfs_obj.get_label()
        if m == "setLabel":
            return vfs_obj.set_label(str(args[0]) if args and args[0] is not None else None)
        raise AttributeError(f"filesystem component has no method {m!r}")

    def _invoke_builtin_eeprom(self, method: str, *args: Any) -> Any:
        m = str(method)
        if m == "get":
            return self.jar_loader.read_asset_text("lua/bios.lua") or ""
        if m == "getData":
            return self.boot_address
        if m == "setData":
            if args and args[0] is not None:
                self.boot_address = str(args[0])
            return None
        if m == "getLabel":
            return "LUA BIOS"
        if m == "setLabel":
            return str(args[0] if args else "LUA BIOS")
        if m == "getSize":
            return 4096
        if m == "getDataSize":
            return 256
        if m == "getChecksum":
            return "00000000"
        if m == "makeReadonly":
            return True
        return None

    def _invoke_builtin_computer(self, method: str, *args: Any) -> Any:
        m = str(method)
        if m == "beep":
            freq = args[0] if args and args[0] is not None else 440
            dur = float(args[1]) if len(args) > 1 and args[1] is not None else 0.1
            self.sandbox.beeps.append((freq, dur))
            return True
        if m == "isRunning":
            return not self.sandbox.is_shutdown
        if m == "start":
            self.sandbox.is_shutdown = False
            return True
        if m == "stop":
            self.sandbox.is_shutdown = True
            return True
        if m == "getDeviceInfo":
            return {}
        if m == "getProgramLocations":
            return []
        return True

    def _get_methods_table(self, address: str) -> Any:
        addr = str(address)
        vfs_obj = self._get_vfs_for_address(addr)
        if vfs_obj is not None:
            fs_methods = [
                "open",
                "read",
                "write",
                "close",
                "seek",
                "makeDirectory",
                "exists",
                "isDirectory",
                "rename",
                "copy",
                "remove",
                "lastModified",
                "spaceUsed",
                "spaceTotal",
                "isReadOnly",
                "list",
                "size",
                "getLabel",
                "setLabel",
            ]
            tbl = self.lua.table()
            for m in fs_methods:
                info = self.lua.table()
                info["direct"] = True
                info["getter"] = False
                info["setter"] = False
                tbl[m] = info
            return tbl

        if self.sandbox.component_bus is not None:
            comp = self.sandbox.component_bus.get_component(
                addr,
                auto_create=bool(self._booted and self.sandbox.component_bus.auto_mock_missing),
            )
            if comp is not None:
                tbl = self.lua.table()
                for m in sorted(comp.get_exposed_methods()):
                    info = self.lua.table()
                    info["direct"] = True
                    info["getter"] = False
                    info["setter"] = False
                    tbl[m] = info
                # Also expose dump_fields as getter entries so machine.lua proxy sets them up
                for fname in comp.extra_fields:
                    info = self.lua.table()
                    info["direct"] = True
                    info["getter"] = True
                    info["setter"] = False
                    tbl[fname] = info
                return tbl

        if addr == "e0000000-0000-4000-8000-000000000001":
            tbl = self.lua.table()
            for m in ("get", "set", "getLabel", "setLabel", "getSize", "getDataSize", "getData", "setData", "getChecksum", "makeReadonly"):
                info = self.lua.table()
                info["direct"] = True
                info["getter"] = False
                info["setter"] = False
                tbl[m] = info
            return tbl

        if addr == self.sandbox.computer_address:
            tbl = self.lua.table()
            for m in ("start", "stop", "isRunning", "beep", "getDeviceInfo", "getProgramLocations"):
                info = self.lua.table()
                info["direct"] = True
                info["getter"] = False
                info["setter"] = False
                tbl[m] = info
            return tbl

        if self.sandbox.gpu_screen is not None:
            if addr == self.sandbox.gpu_screen.screen_address:
                tbl = self.lua.table()
                for m in ("isOn", "turnOn", "turnOff", "getAspectRatio", "getKeyboards", "setPrecise", "isPrecise", "setTouchModeInverted", "isTouchModeInverted"):
                    info = self.lua.table()
                    info["direct"] = True
                    info["getter"] = False
                    info["setter"] = False
                    tbl[m] = info
                return tbl
            if addr == "g0000000-0000-4000-8000-000000000001":
                tbl = self.lua.table()
                for m in (
                    "bind", "getScreen", "getBackground", "setBackground", "getForeground", "setForeground",
                    "getPaletteColor", "setPaletteColor", "maxDepth", "getDepth", "setDepth",
                    "maxResolution", "getResolution", "setResolution", "getViewport", "setViewport",
                    "get", "set", "fill", "copy", "getActiveBuffer", "setActiveBuffer", "buffers",
                    "allocateBuffer", "freeBuffer", "freeAllBuffers", "totalMemory", "freeMemory",
                    "getBufferSize", "bitblt",
                ):
                    info = self.lua.table()
                    info["direct"] = True
                    info["getter"] = False
                    info["setter"] = False
                    tbl[m] = info
                return tbl
            if addr == "k0000000-0000-4000-8000-000000000001":
                return self.lua.table()

        return None

    def _host_component_invoke(self, address: str, method: str, *args: Any) -> Any:
        addr = str(address)
        m = str(method)

        enforce_budget = self.enforce_call_budget or bool(
            self.sandbox.component_bus is not None and self.sandbox.component_bus.enforce_call_budget
        )
        if enforce_budget and self._booted and not self._in_sync_call:
            direct = True
            cost = 0.1
            if self.sandbox.component_bus is not None and self.sandbox.component_bus.get_component(addr) is not None:
                minfo = self.sandbox.component_bus.get_method_info(addr, m)
                direct = bool(minfo["direct"])
                cost = float(minfo["cost"])
            if not direct or self.call_budget_remaining < cost:
                # Exhausted direct call budget or indirect method: return 0 values (nil)
                # so machine.lua yields a synchronous call wrapper to the next tick.
                if self.sandbox.component_bus is not None and direct:
                    self.sandbox.component_bus.budget_exhaustions += 1
                self.call_budget_remaining = self.call_budget_max
                return ()
            self.call_budget_remaining -= cost
            if self.sandbox.component_bus is not None:
                self.sandbox.component_bus.current_tick_budget_used += cost

        try:
            vfs_obj = self._get_vfs_for_address(addr)
            if vfs_obj is not None:
                if self.sandbox.component_bus is not None:
                    comp = self.sandbox.component_bus.get_component(addr)
                    if comp is not None and m in comp.mock_overrides:
                        res = comp.invoke(m, *args)
                        return self._pack_invoke_result(res)
                res = self._invoke_vfs(vfs_obj, m, *args)
                if self._booted and self.sandbox.component_bus is not None:
                    comp = self.sandbox.component_bus.get_component(addr)
                    if comp is not None:
                        from ..components.auto_mock import ComponentCallRecord

                        rec = ComponentCallRecord(
                            tick=self.scheduler.current_tick,
                            address=addr,
                            component_type="filesystem",
                            method=m,
                            args=args,
                            result=res,
                        )
                        comp.call_history.append(rec)
                        self.sandbox.component_bus.record_call(rec)
                return self._pack_invoke_result(res)

            # Check ComponentBus if attached (for non-generic or custom-overridden components)
            if self.sandbox.component_bus is not None:
                comp = self.sandbox.component_bus.get_component(addr)
                if comp is None and self._booted and self.sandbox.component_bus.auto_mock_missing:
                    comp = self.sandbox.component_bus.ensure_auto_mock(addr, method_name=m)
                if comp is not None:
                    # Handle built-in eeprom or computer if they are generic SchemaBackedComponent without custom overrides
                    if comp.component_type == "eeprom" and m not in comp.mock_overrides and not hasattr(comp, f"_impl_{m}"):
                        res = self._invoke_builtin_eeprom(m, *args)
                        return self._pack_invoke_result(res)
                    if comp.component_type == "computer" and m not in comp.mock_overrides and not hasattr(comp, f"_impl_{m}"):
                        res = self._invoke_builtin_computer(m, *args)
                        return self._pack_invoke_result(res)
                    if m in comp.extra_fields and m not in comp.get_exposed_methods():
                        return self._pack_invoke_result(comp.extra_fields[m])
                    res = comp.invoke(m, *args)
                    if comp.component_type == "eeprom" and m == "setData" and args and args[0] is not None:
                        self.boot_address = str(args[0])
                    # Record beep on sandbox if computer.beep was called
                    if comp.component_type == "computer" and m == "beep":
                        freq = args[0] if args and args[0] is not None else 440
                        dur = float(args[1]) if len(args) > 1 and args[1] is not None else 0.1
                        self.sandbox.beeps.append((freq, dur))
                    return self._pack_invoke_result(res)

            if addr == "e0000000-0000-4000-8000-000000000001":
                return self._pack_invoke_result(self._invoke_builtin_eeprom(m, *args))
            if addr == self.sandbox.computer_address:
                return self._pack_invoke_result(self._invoke_builtin_computer(m, *args))
            if self.sandbox.gpu_screen is not None:
                from ..screen.gpu_buffer import GPUComponent, ScreenComponent

                if addr == self.sandbox.gpu_screen.screen_address:
                    sc = ScreenComponent(self.sandbox.gpu_screen, address=addr, host=self.sandbox.host)
                    return self._pack_invoke_result(sc.invoke(m, *args))
                if addr == "g0000000-0000-4000-8000-000000000001":
                    gc = GPUComponent(self.sandbox.gpu_screen, address=addr, host=self.sandbox.host)
                    return self._pack_invoke_result(gc.invoke(m, *args))

            return (False, "no such component")
        except Exception as exc:
            return (False, str(exc))

    def _pack_invoke_result(self, res: Any) -> Tuple[Any, ...]:
        if isinstance(res, tuple):
            return (True, *[self.sandbox.python_to_lua(x) for x in res])
        return (True, self.sandbox.python_to_lua(res))

    def _host_component_doc(self, address: str, method: str) -> Optional[str]:
        if self.sandbox.component_bus is not None:
            comp = self.sandbox.component_bus.get_component(
                str(address),
                auto_create=bool(self._booted and self.sandbox.component_bus.auto_mock_missing),
            )
            if comp is not None:
                return comp.get_doc(str(method))
        return f"function() -- {method}"

    # -------------------------------------------------------------------------
    # Host tables for `machine.lua`
    # -------------------------------------------------------------------------

    def _install_host_globals(self) -> None:
        g = self.lua.globals()

        # 1. computer table
        comp_tbl = self.lua.table()
        comp_tbl["isRobot"] = lambda: self.sandbox.host == "robot"
        comp_tbl["address"] = lambda: self.sandbox.computer_address
        comp_tbl["tmpAddress"] = lambda: self.vfs.tmp_address
        comp_tbl["freeMemory"] = self.free_memory
        comp_tbl["totalMemory"] = self.total_memory
        comp_tbl["uptime"] = lambda: self.scheduler.uptime()

        def _real_time() -> float:
            if self._in_bogomips:
                return self.scheduler.advance_cpu_time(self.cpu_time_step_per_check)
            return self.scheduler.get_real_time()

        comp_tbl["realTime"] = _real_time
        comp_tbl["energy"] = lambda: float(self.sandbox.energy)
        comp_tbl["maxEnergy"] = lambda: float(self.sandbox.max_energy)
        comp_tbl["getBootAddress"] = lambda: self.boot_address

        def _set_boot_address(addr: Optional[str] = None) -> bool:
            self.boot_address = str(addr) if addr is not None else ""
            return True

        comp_tbl["setBootAddress"] = _set_boot_address
        comp_tbl["users"] = lambda: tuple(self.users_list)

        def _add_user(name: str) -> bool:
            s = str(name)
            if s not in self.users_list:
                self.users_list.append(s)
            return True

        def _remove_user(name: str) -> bool:
            s = str(name)
            if s in self.users_list:
                self.users_list.remove(s)
                return True
            return False

        comp_tbl["addUser"] = _add_user
        comp_tbl["removeUser"] = _remove_user

        def _push_signal(name: str, *args: Any) -> bool:
            py_args = tuple(self.sandbox.lua_to_python(a) for a in args)
            return self.scheduler.push_signal(str(name), *py_args)

        comp_tbl["pushSignal"] = _push_signal
        comp_tbl["getArchitectures"] = lambda: self.sandbox.python_to_lua(["Lua 5.3", "Lua 5.2"])
        comp_tbl["getArchitecture"] = lambda: self.architecture

        def _set_architecture(arch: str) -> bool:
            s = str(arch)
            if s in ("Lua 5.3", "Lua 5.2"):
                changed = s != self.architecture
                self.architecture = s
                return changed
            raise ValueError(f"unknown architecture {s!r}")

        comp_tbl["setArchitecture"] = _set_architecture
        g["computer"] = comp_tbl

        # 2. system table
        sys_tbl = self.lua.table()
        sys_tbl["allowBytecode"] = lambda: self.allow_bytecode
        sys_tbl["allowGC"] = lambda: self.allow_gc
        sys_tbl["timeout"] = lambda: self.timeout
        g["system"] = sys_tbl

        # 3. unicode table
        uni_tbl = self.lua.table()
        uni_tbl["char"] = lambda *codes: "".join(chr(int(c)) for c in codes)
        uni_tbl["len"] = lambda s: len(str(s or ""))
        uni_tbl["lower"] = lambda s: str(s or "").lower()
        uni_tbl["upper"] = lambda s: str(s or "").upper()
        uni_tbl["reverse"] = lambda s: str(s or "")[::-1]

        def _uni_sub(s: str, i: int, j: Optional[int] = None) -> str:
            st = str(s or "")
            n = len(st)
            idx_i = int(i)
            start = idx_i - 1 if idx_i > 0 else max(0, n + idx_i)
            if j is None:
                return st[max(0, start) :]
            idx_j = int(j)
            end = idx_j if idx_j >= 0 else max(0, n + idx_j + 1)
            return st[max(0, start) : max(0, end)]

        uni_tbl["sub"] = _uni_sub
        uni_tbl["charWidth"] = lambda s: _char_width(str(s or "")[0]) if s else 0
        uni_tbl["isWide"] = lambda s: (_char_width(str(s or "")[0]) > 1) if s else False
        uni_tbl["wlen"] = lambda s: sum(_char_width(c) for c in str(s or ""))

        def _uni_wtrunc(s: str, count: int) -> str:
            st = str(s or "")
            target = int(count)
            width = 0
            out: List[str] = []
            for ch in st:
                cw = _char_width(ch)
                if width + cw >= target:
                    break
                out.append(ch)
                width += cw
            return "".join(out)

        uni_tbl["wtrunc"] = _uni_wtrunc
        g["unicode"] = uni_tbl

        # 4. component table
        c_tbl = self.lua.table()

        def _c_list(filter_str: Optional[str] = None, exact: Optional[bool] = None) -> Any:
            matches = self._list_all_components(
                str(filter_str) if filter_str is not None else None,
                bool(exact) if exact is not None else (filter_str is not None),
            )
            return self.sandbox.python_to_lua(matches)

        c_tbl["list"] = _c_list
        c_tbl["type"] = lambda addr: self._get_component_type(str(addr))
        c_tbl["slot"] = lambda addr: self._get_component_slot(str(addr))
        c_tbl["methods"] = lambda addr: self._get_methods_table(str(addr))
        c_tbl["invoke"] = self._host_component_invoke
        c_tbl["doc"] = self._host_component_doc
        g["component"] = c_tbl

        # 5. userdata table
        u_tbl = self.lua.table()
        u_tbl["apply"] = lambda *a: (True, None)
        u_tbl["unapply"] = lambda *a: (True, None)
        u_tbl["call"] = lambda *a: (True, None)
        u_tbl["dispose"] = lambda *a: (True, None)
        u_tbl["methods"] = lambda *a: (True, self.lua.table())
        u_tbl["invoke"] = lambda *a: (True, None)
        u_tbl["doc"] = lambda *a: (True, "")
        u_tbl["save"] = lambda *a: (True, None)
        u_tbl["load"] = lambda *a: (True, None)
        g["userdata"] = u_tbl

    # -------------------------------------------------------------------------
    # Booting `machine.lua` -> `bios.lua` -> `/init.lua` -> `/boot/*.lua`
    # -------------------------------------------------------------------------

    def boot(self) -> None:
        """Boot real `machine.lua`, `bios.lua`, and all OpenOS `/boot/*.lua` scripts."""
        self._populate_extra_assets()
        self._install_host_globals()

        machine_src = self.jar_loader.read_asset_text("lua/machine.lua")
        if not machine_src:
            raise RuntimeError("Missing OpenComputers `lua/machine.lua` asset")

        # Patch `machine.lua` only to expose `sandbox` to the host, enforce WP2 (no string.dump),
        # and chain user-function call tracing into `checkDeadline` without weakening `checkDeadline`.
        machine_patched = (
            machine_src.replace(
                "dump = string.dump,",
                "dump = nil,",
            )
            .replace(
                "clock = os.clock,",
                "clock = function() return computer.uptime() end,",
            )
            .replace(
                "date = function(format, time)\n      return spcall(os.date, format, time)\n    end,",
                """date = function(format, time)
      if type(format) == "string" then
        format = format:gsub("%%F", "%%Y-%%m-%%d"):gsub("%%T", "%%H:%%M:%%S")
      end
      return spcall(os.date, format, time)
    end,""",
            )
            .replace(
                "local function checkDeadline()\n  if computer.realTime() > deadline then",
                """local _trace_ignored = {
  checkArg = true, pairs = true, ipairs = true, next = true,
  tostring = true, tonumber = true, type = true, select = true,
  unpack = true, pcall = true, xpcall = true, require = true,
  load = true, loadfile = true, dofile = true, setmetatable = true,
  getmetatable = true, rawget = true, rawset = true, error = true,
  assert = true, print = true,
}
local function checkDeadline(event)
  if event == "call" then
    if _G.__oc_trace_fn then
      local info = debug.getinfo(2, "nSl")
      if info and info.what == "Lua" then
        local name = info.name
        local src = info.source or ""
        if name and not _trace_ignored[name] and not name:match("^_") then
          if src:match("^=script") or src:match("^=/home/") or src:match("_spec%.lua") then
            _G.__oc_trace_fn(name, src:sub(2), info.linedefined or 0)
          end
        end
      end
    end
    return
  end
  if computer.realTime() > deadline then""",
            )
            .replace(
                'debug.sethook(co, checkDeadline, "", hookInterval)',
                'debug.sethook(co, checkDeadline, _G.__oc_trace_fn and "c" or "", hookInterval)',
            )
            .replace(
                "local function main()",
                "_G.__oc_machine_sandbox = sandbox\nlocal function main()",
            )
        )

        # In Lua 5.3, provide pure-Lua `bit32` inside `sandbox` if C bit32 wasn't built into Lua 5.3
        g = self.lua.globals()
        if g["bit32"] is None:
            self.lua.execute(
                r"""
                local bit32_lib = {}
                local MOD = 2^32
                local function to32(x)
                  return math.floor((tonumber(x) or 0) % MOD)
                end
                function bit32_lib.band(...)
                  local r = 0xFFFFFFFF
                  for i = 1, select("#", ...) do
                    r = (r & to32(select(i, ...))) & 0xFFFFFFFF
                  end
                  return r
                end
                function bit32_lib.bor(...)
                  local r = 0
                  for i = 1, select("#", ...) do
                    r = (r | to32(select(i, ...))) & 0xFFFFFFFF
                  end
                  return r
                end
                function bit32_lib.bxor(...)
                  local r = 0
                  for i = 1, select("#", ...) do
                    r = (r ~ to32(select(i, ...))) & 0xFFFFFFFF
                  end
                  return r
                end
                function bit32_lib.bnot(x)
                  return (~to32(x)) & 0xFFFFFFFF
                end
                function bit32_lib.lshift(x, disp)
                  x = to32(x)
                  disp = math.floor(tonumber(disp) or 0)
                  if disp < 0 then return bit32_lib.rshift(x, -disp) end
                  if disp >= 32 then return 0 end
                  return (x << disp) & 0xFFFFFFFF
                end
                function bit32_lib.rshift(x, disp)
                  x = to32(x)
                  disp = math.floor(tonumber(disp) or 0)
                  if disp < 0 then return bit32_lib.lshift(x, -disp) end
                  if disp >= 32 then return 0 end
                  return (x >> disp) & 0xFFFFFFFF
                end
                function bit32_lib.arshift(x, disp)
                  x = to32(x)
                  disp = math.floor(tonumber(disp) or 0)
                  if disp < 0 then return bit32_lib.lshift(x, -disp) end
                  if x < 0x80000000 then return bit32_lib.rshift(x, disp) end
                  if disp >= 32 then return 0xFFFFFFFF end
                  local shifted = x >> disp
                  local mask = (0xFFFFFFFF << (32 - disp)) & 0xFFFFFFFF
                  return (shifted | mask) & 0xFFFFFFFF
                end
                function bit32_lib.btest(...)
                  return bit32_lib.band(...) ~= 0
                end
                function bit32_lib.extract(n, field, width)
                  width = width or 1
                  return (to32(n) >> field) & ((1 << width) - 1)
                end
                function bit32_lib.replace(n, v, field, width)
                  width = width or 1
                  local mask = ((1 << width) - 1) << field
                  return ((to32(n) & (~mask)) | ((to32(v) << field) & mask)) & 0xFFFFFFFF
                end
                function bit32_lib.lrotate(x, disp)
                  disp = disp % 32
                  x = to32(x)
                  if disp == 0 then return x end
                  return ((x << disp) | (x >> (32 - disp))) & 0xFFFFFFFF
                end
                function bit32_lib.rrotate(x, disp)
                  return bit32_lib.lrotate(x, -disp)
                end
                _G.bit32 = bit32_lib
                """
            )

        loader = g["load"]
        loaded = loader(machine_patched, "=machine.lua")
        if isinstance(loaded, tuple):
            fn, err = loaded[0], loaded[1] if len(loaded) > 1 else "unknown error"
        else:
            fn, err = loaded, None
        if fn is None:
            raise RuntimeError(f"Failed to compile machine.lua: {err}")

        co_factory = self.lua.eval(
            """
            function(entry_fn)
              local co = coroutine.create(entry_fn)
              return {
                resume = function(...) return coroutine.resume(co, ...) end,
                status = function() return coroutine.status(co) end,
              }
            end
            """
        )
        self._machine_co = co_factory(fn)

        # First resume: runs `calcHookInterval()` and yields at the baseline yield before `bootstrap()`
        self._in_bogomips = True
        ok, res = self._resume_machine()
        self._in_bogomips = False
        if not ok:
            raise RuntimeError(f"machine.lua failed during initialization: {res}")

        # Record memory baseline right after machine.lua loads (before bios.lua / OpenOS boot)
        # so OpenOS kernel/boot libraries count against the RAM tier just like in-game OpenComputers.
        self.lua.execute('collectgarbage("collect")')
        self._baseline_memory = self.lua.get_memory_used()

        self._sandbox_env = g["__oc_machine_sandbox"]

        # Provide one-shot host hooks consumed into local upvalues at line 1 of /init.lua
        def _record_result(success: bool, *vals: Any) -> None:
            self._last_exec_result = (bool(success), vals)

        def _on_event_error(message: Any) -> None:
            msg_str = str(message)
            existing_tmp = self.tmp_vfs.read_file("/event.log") or ""
            self.tmp_vfs.write_file("/event.log", existing_tmp + msg_str + "\n")
            existing_root_tmp = self.vfs.read_file("/tmp/event.log") or ""
            self.vfs.write_file("/tmp/event.log", existing_root_tmp + msg_str + "\n")
            self.scheduler.record_event_error(msg_str)

        hooks_taken = False
        hook_wrapper = self.lua.eval(
            """
            function(rec_fn, err_fn)
              return function(...) return rec_fn(...) end, function(msg) return err_fn(msg) end
            end
            """
        )
        lua_rec_fn, lua_err_fn = hook_wrapper(_record_result, _on_event_error)

        def _take_host_hooks() -> Tuple[Any, Any]:
            nonlocal hooks_taken
            if hooks_taken:
                return (None, None)
            hooks_taken = True
            return (lua_rec_fn, lua_err_fn)

        self._sandbox_env["computer"]["__oc_take_host_hooks"] = _take_host_hooks
        # Enforce WP2 security inside sandbox_env: never place __oc_record_result or __oc_bridge in _G
        self._sandbox_env["python"] = None
        self._sandbox_env["__oc_bridge"] = None
        self._sandbox_env["__oc_record_result"] = None
        if self._sandbox_env["string"] is not None:
            self._sandbox_env["string"]["dump"] = None

        # Drive the coroutine through `bios.lua` -> `/init.lua` -> `/lib/core/boot.lua` -> `/boot/*.lua`
        # until `_G.runlevel == 1` and `/init.lua` reaches the `__oc_raw_pull(0)` runner loop.
        boot_steps = 0
        while boot_steps < 500:
            boot_steps += 1
            if self._sandbox_env["runlevel"] == 1 and not self.scheduler.signal_queue:
                # One final resume so `/init.lua` drains `"init"` and parks on `__oc_raw_pull(0)`
                self._step_machine_once()
                if self._sandbox_env["runlevel"] == 1 and not self.scheduler.signal_queue:
                    break
            self._step_machine_once()
        else:
            raise RuntimeError("OpenOS boot exceeded 500 yield steps without reaching runlevel 1")

        # Ensure __oc_take_host_hooks is removed from sandbox computer table
        self._sandbox_env["computer"]["__oc_take_host_hooks"] = None

        # Run a full Lua GC cycle after OpenOS boot and tighten the VM memory limit to the configured RAM tier
        # scaled by ramScaleFor64Bit (1.8 in GTNH OpenComputers.cfg) from the pre-OpenOS machine.lua baseline.
        self.lua.execute('collectgarbage("collect")')
        self.lua.set_max_memory(
            self._baseline_memory + int(self.total_memory_bytes * self.ram_scale_for_64bit)
        )

        # Pre-compile host-side component proxy factories (outside user RAM budget)
        # so component callbacks invoked inside child coroutines never re-enter `lua.eval()`.
        before_host_helpers = self.lua.get_memory_used()
        self.sandbox._proxy_factories = {
            "all_items": self.lua.eval(
                r"""
                function(items)
                  local idx = 0
                  return setmetatable(items, {
                    __call = function()
                      idx = idx + 1
                      return items[idx]
                    end
                  })
                end
                """
            ),
            "ae_job": self.lua.eval(
                r"""
                function(py_job)
                  local job = { type = "userdata" }
                  function job.isComputing() return py_job.is_computing() end
                  function job.hasFailed() return py_job.has_failed() end
                  function job.isCanceled() return py_job.is_canceled() end
                  function job.isDone() return py_job.is_done() end
                  function job.cancel() return py_job.cancel() end
                  return job
                end
                """
            ),
            "ae_cpu": self.lua.eval(
                r"""
                function(py_cpu, name, storage, coprocessors, sb)
                  local cpu = {
                    type = "userdata",
                    name = name,
                    storage = storage,
                    coprocessors = coprocessors,
                    busy = py_cpu.is_busy(),
                  }
                  function cpu.isBusy() return py_cpu.is_busy() end
                  function cpu.isActive() return py_cpu.is_active() end
                  function cpu.getStorage() return py_cpu.get_storage() end
                  function cpu.getCoprocessors() return py_cpu.get_coprocessors() end
                  function cpu.cancel()
                    local ok = py_cpu.cancel()
                    cpu.busy = py_cpu.is_busy()
                    return ok
                  end
                  function cpu.finalOutput() return py_cpu.final_output(sb) end
                  function cpu.activeItems() return py_cpu.active_items(sb) end
                  function cpu.pendingItems() return py_cpu.pending_items(sb) end
                  function cpu.storedItems() return py_cpu.stored_items(sb) end
                  return cpu
                end
                """
            ),
            "ae_craftable": self.lua.eval(
                r"""
                function(py_craftable, stack_tbl, sb)
                  local c = { type = "userdata" }
                  function c.getItemStack() return stack_tbl end
                  function c.request(amount, prioritizePower, cpuName)
                    return py_craftable.request_from_lua(amount or 1, prioritizePower, cpuName or "", sb)
                  end
                  return c
                end
                """
            ),
            "inv_stack_iter": self.lua.eval(
                r"""
                function(slots_tbl, count_val)
                  local idx = 0
                  local obj = {}
                  function obj.reset() idx = 0 end
                  function obj.count() return count_val end
                  function obj.getAll()
                    local all = {}
                    all[0] = slots_tbl[1] or {}
                    for i = 1, count_val do
                      all[i] = slots_tbl[i] or {}
                    end
                    return all
                  end
                  return setmetatable(obj, {
                    __call = function()
                      idx = idx + 1
                      if idx <= count_val then
                        return slots_tbl[idx] or {}
                      end
                      return nil
                    end
                  })
                end
                """
            ),
            "internet_handle": self.lua.eval(
                r"""
                function(py_handle, headers_tbl)
                  local h = { type = "userdata" }
                  function h.read(n) return py_handle.read(n) end
                  function h.write(data) return py_handle.write(data) end
                  function h.response() return py_handle.status_code, py_handle.status_message, headers_tbl end
                  function h.finishConnect() return py_handle.finishConnect() end
                  function h.close() py_handle.close() end
                  function h.id() return py_handle.id() end
                  return h
                end
                """
            ),
        }
        host_helper_delta = max(0, self.lua.get_memory_used() - before_host_helpers)
        self._baseline_memory += host_helper_delta
        self.lua.set_max_memory(
            self._baseline_memory + int(self.total_memory_bytes * self.ram_scale_for_64bit)
        )

        # Wrap `print` and `io.write` so `sandbox.stdout_lines` also captures printed lines
        self.lua.execute(
            r"""
            do
              local sb = _G.__oc_machine_sandbox
              local orig_print = sb.print
              sb.print = function(...)
                local parts = {}
                for i = 1, select("#", ...) do
                  local v = select(i, ...)
                  parts[i] = v == nil and "nil" or tostring(v)
                end
                if __oc_capture_stdout then
                  __oc_capture_stdout(table.concat(parts, "\t") .. "\n")
                end
                return orig_print(...)
              end
            end
            """
        )
        g["__oc_capture_stdout"] = lambda text: self.sandbox.stdout_lines.append(str(text))
        self._booted = True
        self.scheduler.current_tick = 0
        self.scheduler.sync_real_time()

    def _resume_machine(self, *args: Any) -> Tuple[bool, Any]:
        self.scheduler.sync_real_time()
        res = self._machine_co["resume"](*args)
        if isinstance(res, tuple):
            ok = bool(res[0])
            payload = res[1] if len(res) == 2 else res[1:]
            if (
                ok
                and self._machine_co["status"]() == "dead"
                and isinstance(payload, tuple)
                and len(payload) >= 2
                and payload[0] is False
            ):
                return False, payload[1]
            return ok, payload
        return bool(res), None

    def _step_machine_once(self) -> Tuple[bool, Any]:
        """Advance one yield/resume cycle of `machine.lua`."""
        if self._machine_co["status"]() == "dead":
            raise RuntimeError("OpenComputers machine coroutine is dead")

        if self.scheduler.signal_queue:
            sig_name, sig_args = self.scheduler.signal_queue.popleft()
            lua_args = [self.sandbox.python_to_lua(a) for a in sig_args]
            ok, yielded = self._resume_machine(sig_name, *lua_args)
        else:
            ok, yielded = self._resume_machine()

        if not ok:
            raise RuntimeError(f"OpenComputers machine error: {yielded}")

        # Handle what `machine.lua` yielded:
        # 1. A function closure: synchronous component call (when direct call budget was exhausted)
        # 2. A boolean: shutdown(reboot)
        # 3. A number (or nil): timeout in seconds for pullSignal
        while ok and any_lua_type(yielded) == "function":
            self.scheduler.advance_ticks(1)
            self.reset_call_budget()
            self._in_sync_call = True
            try:
                sync_results = yielded()
            finally:
                self._in_sync_call = False
            if isinstance(sync_results, tuple):
                ok, yielded = self._resume_machine(*sync_results)
            elif sync_results is not None:
                ok, yielded = self._resume_machine(sync_results)
            else:
                ok, yielded = self._resume_machine()
            if not ok:
                raise RuntimeError(f"OpenComputers machine error: {yielded}")

        if isinstance(yielded, bool):
            self.sandbox.is_shutdown = True
            self.sandbox.reboot_requested = bool(yielded)
            return ok, yielded

        return ok, yielded

    def execute_in_sandbox(self, lua_code: str, chunk_name: str = "=script.lua") -> Any:
        """Execute user Lua code inside the booted OpenOS coroutine so yields bubble through `machine.lua`."""
        if not self._booted:
            self.boot()

        if self.sandbox.component_bus is not None and self.sandbox.component_bus.auto_mock_missing:
            self.sandbox.component_bus.scan_and_register_lua_declarations(str(lua_code))

        self._last_exec_result = None
        self.reset_call_budget()

        co_resume = self._machine_co["resume"]
        co_status = self._machine_co["status"]

        # Resume the parked runner loop in `/init.lua` with `("__host_exec", lua_code, chunk_name)`
        ok, yielded = self._resume_machine("__host_exec", str(lua_code), str(chunk_name))

        if not ok:
            raise RuntimeError(f"OpenComputers machine error: {yielded}")

        while self._last_exec_result is None:
            if co_status() == "dead":
                raise RuntimeError(f"Machine halted before completing script (last yield: {yielded!r})")

            # 1. Synchronous component call closure yielded by machine.lua
            if any_lua_type(yielded) == "function":
                self.scheduler.advance_ticks(1)
                self.reset_call_budget()
                self._in_sync_call = True
                try:
                    sync_res = yielded()
                finally:
                    self._in_sync_call = False
                if isinstance(sync_res, tuple):
                    ok, yielded = self._resume_machine(*sync_res)
                elif sync_res is not None:
                    ok, yielded = self._resume_machine(sync_res)
                else:
                    ok, yielded = self._resume_machine()
                if not ok:
                    raise RuntimeError(f"OpenComputers machine error: {yielded}")
                continue

            # 2. Shutdown boolean yielded by computer.shutdown(reboot)
            if isinstance(yielded, bool):
                self.sandbox.is_shutdown = True
                self.sandbox.reboot_requested = bool(yielded)
                return yielded

            # 3. `computer.pullSignal(timeout)` yielded a timeout number (or nil/inf)
            timeout: Optional[float] = None
            if isinstance(yielded, (int, float)):
                timeout = float(yielded)

            sig = self.scheduler.pull_raw_signal(timeout)
            self.reset_call_budget()
            if sig:
                sig_name = sig[0]
                lua_args = [self.sandbox.python_to_lua(a) for a in sig[1:]]
                ok, yielded = self._resume_machine(sig_name, *lua_args)
            else:
                ok, yielded = self._resume_machine()

            if not ok:
                raise RuntimeError(f"OpenComputers machine error: {yielded}")

        success, vals = self._last_exec_result
        self._last_exec_result = None
        if not success:
            err_msg = str(vals[0]) if vals else "unknown Lua error"
            if "deadlock" in err_msg.lower():
                raise DeadlockError(err_msg)
            raise RuntimeError(err_msg)

        if not vals:
            return None
        if len(vals) == 1:
            return vals[0]
        return vals

    # -------------------------------------------------------------------------
    # Interactive OpenOS `/bin/sh.lua` shell & live event loop stepping
    # -------------------------------------------------------------------------

    def _drain_sync_calls(self, ok: bool, yielded: Any) -> Tuple[bool, Any]:
        """Execute any synchronous component call closures yielded by `machine.lua`."""
        while ok and any_lua_type(yielded) == "function":
            self.scheduler.advance_ticks(1)
            self.reset_call_budget()
            self._in_sync_call = True
            try:
                sync_res = yielded()
            finally:
                self._in_sync_call = False
            if isinstance(sync_res, tuple):
                ok, yielded = self._resume_machine(*sync_res)
            elif sync_res is not None:
                ok, yielded = self._resume_machine(sync_res)
            else:
                ok, yielded = self._resume_machine()
            if not ok:
                raise RuntimeError(f"OpenComputers machine error: {yielded}")
        return ok, yielded

    def _update_interactive_deadline(self, yielded: Any) -> None:
        if isinstance(yielded, bool):
            self.sandbox.is_shutdown = True
            self.sandbox.reboot_requested = bool(yielded)
            self._interactive_wait_deadline = math.inf
        elif isinstance(yielded, (int, float)):
            sec = max(0.0, float(yielded))
            self._interactive_wait_deadline = (
                math.inf if math.isinf(sec) else (self.scheduler.uptime() + sec)
            )
        else:
            self._interactive_wait_deadline = math.inf

    def start_interactive_shell(self) -> None:
        """Transition the booted OpenOS instance into the interactive `/bin/sh.lua` shell prompt."""
        if not self._booted:
            self.boot()
        if self._interactive_mode:
            return

        self._interactive_mode = True
        self.reset_call_budget()
        ok, yielded = self._resume_machine("__host_interactive_shell")
        if not ok:
            raise RuntimeError(f"OpenComputers interactive shell failed to start: {yielded}")
        ok, yielded = self._drain_sync_calls(ok, yielded)
        self._update_interactive_deadline(yielded)
        # Step a few ticks so sh.lua finishes printing the prompt and parks on term.read()
        for _ in range(5):
            if not self.scheduler.signal_queue and self._interactive_wait_deadline > self.scheduler.uptime():
                break
            self.step_interactive_tick()

    def step_interactive_tick(self, max_signal_burst: int = 32) -> bool:
        """Advance the interactive OpenOS machine by 1 virtual tick and process pending signals."""
        if not self._interactive_mode:
            self.start_interactive_shell()
        if self.sandbox.is_shutdown or self._machine_co["status"]() == "dead":
            return False

        self.reset_call_budget()
        processed = 0
        while processed < max_signal_burst:
            if self.sandbox.is_shutdown or self._machine_co["status"]() == "dead":
                return False
            if self.scheduler.signal_queue:
                sig_name, sig_args = self.scheduler.signal_queue.popleft()
                lua_args = [self.sandbox.python_to_lua(a) for a in sig_args]
                ok, yielded = self._resume_machine(sig_name, *lua_args)
                if not ok:
                    raise RuntimeError(f"OpenComputers machine error: {yielded}")
                ok, yielded = self._drain_sync_calls(ok, yielded)
                self._update_interactive_deadline(yielded)
                processed += 1
            elif self.scheduler.uptime() >= self._interactive_wait_deadline:
                ok, yielded = self._resume_machine()
                if not ok:
                    raise RuntimeError(f"OpenComputers machine error: {yielded}")
                ok, yielded = self._drain_sync_calls(ok, yielded)
                self._update_interactive_deadline(yielded)
                processed += 1
            else:
                break

        self.scheduler.advance_ticks(1)
        return not self.sandbox.is_shutdown

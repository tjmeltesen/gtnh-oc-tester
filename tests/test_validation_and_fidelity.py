"""Comprehensive 1:1 GTNH 2.9 OpenComputers Fidelity & Validation Regression Suite (WP1 - WP12)."""

from __future__ import annotations

import os
from pathlib import Path
import zipfile

import pytest

from gtnh_oc_tester import (
    DeadlockError,
    OCEnvironment,
    OCJarLoader,
    OCLuaSandbox,
    OCMachineConfig,
    OCPygameWindow,
    load_oc_config,
    validate_simulator_dumps,
)


# -----------------------------------------------------------------------------
# WP1: Pin Lua Version (Lua 5.3 default, Lua 5.2 selectable, no Lua 5.4)
# -----------------------------------------------------------------------------


def test_wp1_lua53_default_and_lua52_selectable() -> None:
    env53 = OCEnvironment(lua_version="5.3")
    ver53 = env53.run_lua("return _VERSION, (1 << 4), (64 >> 2), (7 // 2), (0x0F & 0x33)")
    assert ver53[0] == "Lua 5.3"
    assert ver53[1] == 16
    assert ver53[2] == 16
    assert ver53[3] == 3
    assert ver53[4] == 3

    # Verify Lua 5.4 `<const>` attribute syntax does NOT compile in Lua 5.3
    res_const = env53.run_lua('local fn, err = load("local x <const> = 1"); return fn == nil')
    assert res_const is True

    # Verify Lua 5.2 is selectable and reports _VERSION == "Lua 5.2"
    env52 = OCEnvironment(lua_version="5.2")
    ver52 = env52.run_lua("return _VERSION, require('computer').getArchitecture(), bit32.band(0xFF, 0x0F)")
    assert ver52[0] == "Lua 5.2"
    assert ver52[1] == "Lua 5.2"
    assert ver52[2] == 15

    # In Lua 5.2, native `<<` bitwise shift operator is a syntax error
    res_shift = env52.run_lua('local fn, err = load("return 1 << 4"); return fn == nil')
    assert res_shift is True


# -----------------------------------------------------------------------------
# WP2: Close Sandbox Security Hole (No host shell, no python, no bytecode, etc.)
# -----------------------------------------------------------------------------


def test_wp2_sandbox_security_isolation(tmp_path: Path) -> None:
    env = OCEnvironment()
    sentinel = tmp_path / "pwned_host_sentinel.txt"

    res = env.run_lua(
        f"""
        -- 1. python and __oc_bridge must be nil
        assert(_G.python == nil, "_G.python leaked into sandbox")
        assert(_G.__oc_bridge == nil, "_G.__oc_bridge leaked into sandbox")

        -- 2. io.popen and string.dump must be nil
        assert(io.popen == nil, "io.popen must be nil")
        assert(string.dump == nil, "string.dump must be nil")

        -- 3. debug must only expose getinfo, traceback, getlocal, getupvalue
        assert(type(debug.getinfo) == "function")
        assert(type(debug.traceback) == "function")
        assert(debug.sethook == nil, "debug.sethook must not be exposed to user scripts")
        assert(debug.getregistry == nil, "debug.getregistry must not be exposed")
        assert(debug.setlocal == nil, "debug.setlocal must not be exposed")
        assert(debug.setupvalue == nil, "debug.setupvalue must not be exposed")
        assert(debug.upvaluejoin == nil, "debug.upvaluejoin must not be exposed")

        -- 4. debug.getlocal and debug.getupvalue must only return name (not value)
        local function sample(alpha)
          local beta = alpha + 10
          local n, v = debug.getlocal(2, 1)
          return n, v, beta
        end
        local loc_name, loc_val = sample(42)
        assert(loc_name == "alpha")
        assert(loc_val == nil, "debug.getlocal must not leak local variable value")

        -- 5. Bytecode chunks (\\27Lua) must be rejected when allowBytecode is false
        local bc_fn, bc_err = load("\\27LuaP\\000\\001")
        assert(bc_fn == nil, "Bytecode loading should be rejected")

        -- 6. os.execute goes to OpenOS shell, NOT host /bin/sh
        os.execute("touch {sentinel.as_posix()}")
        return true
        """
    )
    assert res is True
    assert not sentinel.exists(), "os.execute executed on the host shell!"


# -----------------------------------------------------------------------------
# WP3: Boot Real Kernel (`machine.lua` -> `bios.lua` -> `/init.lua` -> `/boot/*.lua`)
# -----------------------------------------------------------------------------


def test_wp3_real_kernel_and_openos_boot() -> None:
    env = OCEnvironment()
    res = env.run_lua(
        r"""
        assert(_G._OSVERSION:match("^OpenOS"), "Expected real _OSVERSION from OpenOS boot")
        assert(_G.runlevel == 1, "Expected OpenOS runlevel 1 after boot")

        -- Verify real OpenOS thread library works with coroutine resumption
        local thread = require("thread")
        local log = {}
        local t = thread.create(function()
          table.insert(log, "t1_start")
          os.sleep(0.05)
          table.insert(log, "t1_end")
        end)
        table.insert(log, "main_wait")
        t:join()
        table.insert(log, "main_done")
        return _G._OSVERSION, table.concat(log, ",")
        """
    )
    assert str(res[0]).startswith("OpenOS")
    assert res[1] == "t1_start,main_wait,t1_end,main_done"


# -----------------------------------------------------------------------------
# WP4: Coroutine-Yielding Signal Queue, Real Timers, and Deadlock Detection
# -----------------------------------------------------------------------------


def test_wp4_signal_yielding_timers_and_deadlock() -> None:
    env = OCEnvironment()

    # 1. Real OpenOS event.timer fires during event.pull and returns a numeric timer ID
    res = env.run_lua(
        r"""
        local event = require("event")
        local fired = 0
        local tid = event.timer(0.05, function()
          fired = fired + 1
        end, 2)
        assert(type(tid) == "number", "event.timer must return a numeric timer ID")
        os.sleep(0.15)
        return tid, fired
        """
    )
    assert isinstance(res[0], (int, float))
    assert res[1] == 2

    # 2. Queued signal wakes no-timeout event.pull()
    env.push_event("modem_message", "m-local", "m-remote", 123, 0.0, "hello_gtnh")
    msg = env.run_lua(
        r"""
        local event = require("event")
        local name, loc, rem, port, dist, payload = event.pull("modem_message")
        return name, port, payload
        """
    )
    assert msg == ("modem_message", 123, "hello_gtnh")

    # 3. Unbounded event.pull() with no pending signals or timers raises DeadlockError
    env.scheduler.max_idle_ticks = 20
    with pytest.raises(DeadlockError, match="Infinite pullSignal"):
        env.run_lua('require("event").pull("never_arrives")')


# -----------------------------------------------------------------------------
# WP5: Enforce Game Limits (5.0s yield timeout, call budgets, RAM OOM, signal cap, EEPROM cap)
# -----------------------------------------------------------------------------


def test_wp5_too_long_without_yielding_timeout() -> None:
    env = OCEnvironment()
    with pytest.raises(RuntimeError, match="too long without yielding"):
        env.run_lua("while true do end")


def test_wp5_cpu_tier_call_budgets() -> None:
    # Tier 1 CPU has 0.5 call budget per tick; Tier 3 CPU has 1.5 call budget per tick
    env_t1 = OCEnvironment(cpu_tier=1, enforce_call_budget=True)
    env_t3 = OCEnvironment(cpu_tier=3, enforce_call_budget=True)
    assert env_t1.config.call_budget_per_tick == 0.5
    assert env_t3.config.call_budget_per_tick == 1.5

    env_t1.attach_gt_machine("gt_machine", address="gt-budget-1")
    env_t3.attach_gt_machine("gt_machine", address="gt-budget-3")

    t1_ticks = env_t1.run_lua(
        r"""
        local component = require("component")
        local gt = component.proxy(component.get("gt-budget-1"))
        local t0 = os.clock()
        for i = 1, 30 do
          gt.getEUStored()
        end
        return os.clock() - t0
        """
    )
    t3_ticks = env_t3.run_lua(
        r"""
        local component = require("component")
        local gt = component.proxy(component.get("gt-budget-3"))
        local t0 = os.clock()
        for i = 1, 30 do
          gt.getEUStored()
        end
        return os.clock() - t0
        """
    )
    # Tier 1 (budget 0.5 => 5 calls/tick) takes ~3x more ticks than Tier 3 (budget 1.5 => 15 calls/tick)
    assert t1_ticks > t3_ticks
    assert env_t1.bus.budget_exhaustions > env_t3.bus.budget_exhaustions


def test_wp5_ram_tier_memory_cap_oom() -> None:
    env_t1 = OCEnvironment(ram_tier=1)
    assert env_t1.sandbox.total_memory == 192 * 1024

    with pytest.raises(Exception, match="not enough memory|MemoryError"):
        env_t1.run_lua(
            r"""
            local big = {}
            for i = 1, 50000 do
              big[i] = string.rep("X", 1024)
            end
            """
        )


def test_wp5_signal_queue_cap_1024() -> None:
    env = OCEnvironment()
    assert env.scheduler.max_signal_queue_size == 1024

    for i in range(1024):
        assert env.push_event("test_sig", i) is True
    # 1025th signal must be dropped and return False
    assert env.push_event("test_sig", 1025) is False
    env.scheduler.signal_queue.clear()


def test_wp5_eeprom_size_limits_4096_and_256() -> None:
    env = OCEnvironment()
    res = env.run_lua(
        r"""
        local eeprom = require("component").eeprom
        assert(eeprom.getSize() == 4096)
        assert(eeprom.getDataSize() == 256)

        -- 4096 bytes succeeds
        eeprom.set(string.rep("A", 4096))
        assert(#eeprom.get() == 4096)

        -- 4097 bytes fails
        local ok_code, err_code = pcall(function()
          eeprom.set(string.rep("B", 4097))
        end)
        assert(not ok_code, "EEPROM > 4096 bytes must fail")

        -- 257 bytes of data fails
        local ok_data, err_data = pcall(function()
          eeprom.setData(string.rep("D", 257))
        end)
        assert(not ok_data, "EEPROM data > 256 bytes must fail")
        return true
        """
    )
    assert res is True


# -----------------------------------------------------------------------------
# WP6: Fail Loudly on Bad Jars or Broken Scripts (No silent pass)
# -----------------------------------------------------------------------------


def test_wp6_fail_loudly_on_invalid_jar(tmp_path: Path) -> None:
    missing_jar = tmp_path / "does_not_exist.jar"
    with pytest.raises(FileNotFoundError):
        OCJarLoader(jar_path=missing_jar)

    empty_jar = tmp_path / "empty_invalid.jar"
    with zipfile.ZipFile(empty_jar, "w") as zf:
        zf.writestr("README.txt", "not an opencomputers jar")

    with pytest.raises(RuntimeError, match="missing required asset"):
        OCJarLoader(jar_path=empty_jar)


# -----------------------------------------------------------------------------
# WP7: Configurable Jar (`1.12.64-GTNH` & `1.12.62-GTNH`) and `OpenComputers.cfg`
# -----------------------------------------------------------------------------


def test_wp7_multi_jar_versions_and_oc_config() -> None:
    # Both 1.12.64-GTNH and 1.12.62-GTNH JARs must load and boot OpenOS
    loader_64 = OCJarLoader(jar_version="1.12.64-GTNH")
    loader_62 = OCJarLoader(jar_version="1.12.62-GTNH")
    assert loader_64.jar_version == "1.12.64-GTNH"
    assert loader_62.jar_version == "1.12.62-GTNH"
    assert "tooLongWithoutYielding" in (loader_62.read_asset_text("lua/machine.lua") or "")

    # Default bundled GTNH OpenComputers.cfg + application.conf parsing
    cfg = load_oc_config()
    assert cfg.timeout == 5.0
    assert cfg.call_budgets == (0.5, 1.0, 1.5)
    assert cfg.ram_sizes_kb == (192, 256, 384, 512, 768, 1024)
    assert cfg.eeprom_size == 4096
    assert cfg.eeprom_data_size == 256
    assert cfg.max_signal_queue_size == 1024
    assert cfg.allow_bytecode is False
    assert cfg.allow_gc is False


# -----------------------------------------------------------------------------
# WP8: Validate All Simulators Against GTNH 2.9 Dumps
# -----------------------------------------------------------------------------


def test_wp8_validate_all_simulators_against_gtnh_dumps() -> None:
    report = validate_simulator_dumps()
    assert report["valid"] is True, f"Dump validation failed: {report}"
    assert report["checked_components"] >= 15
    assert report["checked_methods"] >= 200


# -----------------------------------------------------------------------------
# WP9: Unified ComponentBus for Vanilla OC + GTNH Components
# -----------------------------------------------------------------------------


def test_wp9_unified_oc_and_gtnh_component_bus() -> None:
    env = OCEnvironment()
    modem_a = env.attach("modem", address="m-node-a")
    modem_b = env.attach("modem", address="m-node-b")
    data_card = env.attach("data", address="d-card-1")
    drive = env.attach("drive", address="drv-1")
    sound = env.attach("sound", address="snd-1")
    inet = env.attach("internet", address="inet-1")
    me = env.attach_me_network("me_controller", address="me-ctrl-1")
    me.network.add_item("minecraft:diamond", 64, label="Diamond")

    res = env.run_lua(
        r"""
        local component = require("component")
        local event = require("event")

        -- 1. Both OC and GTNH components appear on the same component.list()
        local types = {}
        for addr, ctype in component.list() do
          types[ctype] = (types[ctype] or 0) + 1
        end
        assert(types["filesystem"] >= 2)
        assert(types["eeprom"] == 1)
        assert(types["computer"] == 1)
        assert(types["gpu"] == 1)
        assert(types["screen"] == 1)
        assert(types["keyboard"] == 1)
        assert(types["modem"] == 2)
        assert(types["data"] == 1)
        assert(types["drive"] == 1)
        assert(types["sound"] == 1)
        assert(types["internet"] == 1)
        assert(types["me_controller"] == 1)

        -- 2. Modem A broadcasts to Modem B on port 42
        local ma = component.proxy("m-node-a")
        local mb = component.proxy("m-node-b")
        assert(mb.open(42) == true)
        assert(mb.isOpen(42) == true)
        assert(ma.broadcast(42, "gtnh_packet", 99) == true)
        local ev, recv_addr, sender_addr, port, dist, p1, p2 = event.pull(0.5, "modem_message")
        assert(ev == "modem_message")
        assert(recv_addr == "m-node-b")
        assert(sender_addr == "m-node-a")
        assert(port == 42)
        assert(p1 == "gtnh_packet" and p2 == 99)

        -- 3. Data card crc32 / sha256 / base64 / deflate / inflate
        local dc = component.data
        local b64 = dc.encode64("GTNH-2.9")
        assert(dc.decode64(b64) == "GTNH-2.9")
        local compressed = dc.deflate("GTNH-2.9-OpenComputers")
        assert(dc.inflate(compressed) == "GTNH-2.9-OpenComputers")

        -- 4. Drive read/write sector & byte
        local drv = component.drive
        drv.writeSector(1, "SECTOR_ONE_DATA")
        assert(drv.readSector(1):sub(1, 15) == "SECTOR_ONE_DATA")

        -- 5. Sound card modes and channels
        local snd = component.sound
        assert(snd.channel_count == 8)
        assert(snd.modes.sine == 3)
        snd.open(1)
        snd.setWave(1, snd.modes.sine)
        assert(snd.process() == true)

        -- 6. ME Controller alongside vanilla OC components
        local items = component.me_controller.getItemsInNetwork()
        assert(#items == 1 and items[1].name == "minecraft:diamond" and items[1].size == 64)
        return true
        """
    )
    assert res is True


# -----------------------------------------------------------------------------
# WP10: Optional Pygame Interactive Screen Window (Headless SDL verification)
# -----------------------------------------------------------------------------


def test_wp10_pygame_window_rendering_and_input_signals() -> None:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    import pygame

    env = OCEnvironment(screen_width=80, screen_height=25, screen_tier=3)
    env.run_lua(
        r"""
        local gpu = require("component").gpu
        gpu.setResolution(80, 25)
        gpu.setBackground(0x002B36)
        gpu.setForeground(0x859900)
        gpu.fill(1, 1, 80, 25, " ")
        gpu.set(2, 2, "GTNH 2.9 Pygame Live Screen Viewer")
        """
    )

    win = OCPygameWindow(
        screen=env.screen,
        scheduler=env.scheduler,
        scale=1,
        headless=True,
    )
    try:
        surface = win.render_frame()
        assert surface.get_size() == (80 * 8, 25 * 16)
        # Pixel inside cell (1,1) background should match 0x002B36 -> (0, 43, 54)
        assert surface.get_at((0, 0))[:3] == (0x00, 0x2B, 0x36)

        # Inject key_down, key_up, touch, drag, drop, and scroll events through window handler
        win.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, unicode="a"))
        win.handle_event(pygame.event.Event(pygame.KEYUP, key=pygame.K_a, unicode="a"))
        win.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(16, 32), button=1))  # col 3, row 3 (1-based)
        win.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(24, 32), buttons=(1, 0, 0)))  # col 4, row 3
        win.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(24, 32), button=1))
        win.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, pos=(24, 32), y=1))

        signals = [env.scheduler.pull_signal(0) for _ in range(6)]
        assert signals[0][0] == "key_down" and signals[0][2] == ord("a") and signals[0][3] == 0x1E
        assert signals[1][0] == "key_up" and signals[1][2] == ord("a") and signals[1][3] == 0x1E
        assert signals[2][0] == "touch" and signals[2][2:5] == (3, 3, 0)
        assert signals[3][0] == "drag" and signals[3][2:5] == (4, 3, 0)
        assert signals[4][0] == "drop" and signals[4][2:5] == (4, 3, 0)
        assert signals[5][0] == "scroll" and signals[5][2:5] == (4, 3, 1)
    finally:
        win.close()

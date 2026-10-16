"""Tests for Phase 1 (Spec Ingestion, Dumps, LuaLS Stubs, JAR Loader) and Phase 2 (Sandbox, VFS, Scheduler, 28 Libs)."""

from __future__ import annotations

from gtnh_oc_tester import ALL_28_OPENOS_LIBS, OCEnvironment, OCJarLoader, get_default_registry


def test_schema_registry_counts_and_inheritance() -> None:
    reg = get_default_registry()
    assert len(reg.dumps) == 190
    assert len(reg.components) == 165
    assert len(reg.abstracts) == 19
    assert len(reg.libs) == 28
    assert len(reg.types) >= 55

    me_schema = reg.get_component_schema("me_interface", host="computer")
    assert "CommonNetworkAPI" in me_schema.parents_chain
    assert "EssentiaNetworkAPI" in me_schema.parents_chain
    assert "MEInterfaceAPI" in me_schema.parents_chain
    methods = me_schema.get_method_names()
    for expected in (
        "getItemsInNetwork",
        "getFluidInNetwork",
        "getEssentiaInNetwork",
        "getCraftables",
        "getCraftable",
        "setInterfaceConfiguration",
        "setItemEventSubscription",
    ):
        assert expected in methods

    # Verify fluid_interface has getFluidInterfaceConfiguration while me_interface does not
    fi_schema = reg.get_component_schema("fluid_interface", host="computer")
    assert "getFluidInterfaceConfiguration" in fi_schema.get_method_names()
    assert "getFluidInterfaceConfiguration" not in me_schema.get_method_names()


def test_host_specific_component_differences() -> None:
    reg = get_default_registry()
    # inventory_controller: adapter on computer (11 methods) vs robot (24 methods)
    ic_comp = reg.get_component_schema("inventory_controller", host="computer").get_method_names()
    ic_robot = reg.get_component_schema("inventory_controller", host="robot").get_method_names()
    assert "getAllStacks" in ic_comp
    assert "equip" not in ic_comp
    assert "equip" in ic_robot
    assert len(ic_comp) == 11
    assert len(ic_robot) == 24

    # robot component: external adapter (5 methods) vs internal robot (28 methods)
    rob_comp = reg.get_component_schema("robot", host="computer").get_method_names()
    rob_internal = reg.get_component_schema("robot", host="robot").get_method_names()
    assert "start" in rob_comp
    assert "move" not in rob_comp
    assert "move" in rob_internal
    assert "start" not in rob_internal

    # redstone in tablet: wireless + wake threshold only (7 methods), no sided getInput/setOutput
    rs_tablet = reg.get_component_schema("redstone", host="tablet").get_method_names()
    assert "getWirelessInput" in rs_tablet
    assert "getInput" not in rs_tablet


def test_jar_loader_assets_and_font_hex() -> None:
    jar = OCJarLoader()
    openos_files = jar.list_openos_files()
    assert "/lib/serialization.lua" in openos_files
    assert "/lib/colors.lua" in openos_files
    assert "/lib/sides.lua" in openos_files
    glyphs = jar.load_font_hex()
    assert len(glyphs) > 50000
    assert ord("A") in glyphs


def test_all_28_openos_libraries_and_vfs(oc_env: OCEnvironment) -> None:
    for lib_name in ALL_28_OPENOS_LIBS:
        mod = oc_env.run_lua(f'return require("{lib_name}")')
        assert mod is not None, f"Failed to require OpenOS library '{lib_name}'"

    res = oc_env.run_lua(
        """
        local fs = require("filesystem")
        local ser = require("serialization")
        local text = require("text")
        local unicode = require("unicode")
        local bit32 = require("bit32")

        fs.makeDirectory("/home/config")
        local f = io.open("/home/config/factory.cfg", "w")
        f:write(ser.serialize({ tier = "UV", eu_t = 524288, active = true }))
        f:close()

        local raw = io.open("/home/config/factory.cfg", "r"):read("*a")
        local cfg = ser.unserialize(raw)
        return cfg.tier, cfg.eu_t, text.trim("  GTNH 2.9  "), unicode.wlen("GTNH"), bit32.band(0xFF, 0x0F)
        """
    )
    assert res == ("UV", 524288, "GTNH 2.9", 4, 15)


def test_deterministic_scheduler_timers_and_listeners(oc_env: OCEnvironment) -> None:
    res = oc_env.run_lua(
        """
        local event = require("event")
        local count = 0
        local received_custom = nil

        event.listen("custom_alarm", function(_, zone, level)
          received_custom = zone .. ":" .. tostring(level)
        end)

        event.timer(0.1, function()
          count = count + 1
        end, 3)

        event.push("custom_alarm", "cleanroom", 5)
        os.sleep(0.5)
        return count, received_custom, computer.uptime()
        """
    )
    assert res == (3, "cleanroom:5", 0.5)

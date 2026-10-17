"""Tests for Phase 3: GTNH 2.9 Component Bus, 19 Abstracts, AE2/AE2FC, GregTech, Transposer, Redstone, Auto-Mock."""

from __future__ import annotations

from gtnh_oc_tester import OCEnvironment, get_default_registry


def test_all_165_components_attach_and_expose_docs(oc_env: OCEnvironment) -> None:
    reg = get_default_registry()
    all_types = reg.list_component_types()
    assert len(all_types) >= 165

    for ctype in all_types:
        comp = oc_env.attach(ctype)
        assert comp.address in oc_env.bus.components
        methods = comp.get_exposed_methods()
        if methods:
            first_method = sorted(methods)[0]
            doc = comp.get_doc(first_method)
            assert doc is not None and "function" in doc


def test_ae2_network_items_fluids_craftables_and_events(oc_env: OCEnvironment) -> None:
    oc_env.attach_me_network("me_controller")
    oc_env.attach_me_network("fluid_interface")
    oc_env.attach_me_network("level_maintainer")

    oc_env.me_network.add_item("gregtech:gt.metaitem.01", size=256, damage=11030, label="Stainless Steel Ingot")
    oc_env.me_network.add_fluid("molten.polytetrafluoroethylene", amount=1440, label="Molten PTFE")
    oc_env.me_network.add_essentia("instrumentum", amount=128)
    oc_env.me_network.add_craftable(
        "gregtech:gt.metaitem.01",
        damage=17306,
        label="Polyethylene Sheet",
        duration_ticks=4,
    )

    res = oc_env.run_lua(
        """
        local component = require("component")
        local event = require("event")
        local me = component.me_controller
        local fi = component.fluid_interface
        local lm = component.level_maintainer

        me.setItemEventSubscription(true)

        -- Verify allItems() userdata iterator
        local total_items = 0
        for item in me.allItems() do
          total_items = total_items + (item.size or 0)
        end

        -- Verify fluid & essentia queries
        local ptfe = fi.getFluidInNetwork("molten.polytetrafluoroethylene")
        local ess = me.getEssentiaInNetwork("instrumentum")

        -- Request crafting job via AECraftable userdata
        local recipe = me.getCraftable({ label = "Polyethylene Sheet" })
        local job = recipe.request(64, true, "CPU-1")
        local done_before = job.isDone()

        os.sleep(0.3) -- 6 ticks > 4 ticks duration
        local done_after = job.isDone()
        local crafted = me.getItemInNetwork({ label = "Polyethylene Sheet" })

        -- Level maintainer configuration
        lm.setSlot(1, 2048, 64)
        lm.setEnable(1, true)

        return total_items, ptfe[1].amount, ess[1].amount, done_before, done_after, crafted.size, lm.isEnable(1)
        """
    )
    assert res == (256, 1440, 128, False, True, 64, True)


def test_gregtech_machines_energy_and_parameters(oc_env: OCEnvironment) -> None:
    lcr = oc_env.attach_gt_machine(
        "gt_machine",
        machine_name="gt.blockmachines.multimachine.chemicalreactor",
        stored_eu=500000,
        eu_capacity=1000000,
        work_allowed=True,
        has_work=True,
        work_progress=10,
        work_max_progress=100,
    )
    batt = oc_env.attach_gt_machine("gt_batterybuffer")

    res = oc_env.run_lua(
        """
        local component = require("component")
        local gt = component.gt_machine
        local bb = component.gt_batterybuffer

        gt.setCircuitConfiguration(24)
        gt.setParameter(0, 42.5)
        os.sleep(0.25) -- 5 ticks progress (10 -> 15)
        local p_after = gt.getWorkProgress()
        gt.setWorkAllowed(false)

        return gt.getName(), gt.getCircuitConfiguration(), gt.getParameters()[0], p_after, gt.isWorkAllowed(), bb.getBatteryCharge(1)
        """
    )
    assert res == (
        "gt.blockmachines.multimachine.chemicalreactor",
        24,
        42.5,
        15,
        False,
        1000000,
    )
    assert not lcr.work_allowed
    assert batt.component_type == "gt_batterybuffer"


def test_transposer_inventory_tanks_and_stack_slot_iterator(oc_env: OCEnvironment) -> None:
    oc_env.attach_transposer()
    db = oc_env.attach_database()

    # Side 2 (north) has items and fluid; Side 3 (south) is empty destination
    oc_env.inventory_grid.set_stack(
        side=2,
        slot=1,
        name="gregtech:gt.metaitem.01",
        size=32,
        damage=2001,
        label="Crushed Bauxite Ore",
        ore_dict=["crushedBauxite"],
    )
    oc_env.inventory_grid.set_stack(
        side=2,
        slot=2,
        name="gregtech:gt.metaitem.01",
        size=16,
        damage=2002,
        label="Crushed Ilmenite Ore",
        ore_dict=["crushedIlmenite"],
    )
    oc_env.inventory_grid.set_tank(side=2, tank_index=1, name="sulfuricacid", amount=8000, capacity=16000)
    oc_env.inventory_grid.set_tank(side=3, tank_index=1, name=None, amount=0, capacity=16000)

    res = oc_env.run_lua(
        f"""
        local component = require("component")
        local sides = require("sides")
        local tp = component.transposer
        local db_addr = "{db.address}"

        local ss = tp.getAllStacks(sides.north)
        local count_slots = ss.count()
        local first_item = ss()
        local second_item = ss()
        ss.reset()
        local all_tbl = ss.getAll()

        -- Store slot 1 into database slot 1 and compare
        tp.store(sides.north, 1, db_addr, 1)
        local matches_db = tp.compareStackToDatabase(sides.north, 1, db_addr, 1)

        -- Transfer 12 items and 3000L sulfuric acid from north to south
        local moved_items = tp.transferItem(sides.north, sides.south, 12, 1, 1)
        local ok_fluid, moved_fluid = tp.transferFluid(sides.north, sides.south, 3000)

        return count_slots, first_item.label, second_item.label, all_tbl[1].size, matches_db, moved_items, ok_fluid, moved_fluid, tp.getTankLevel(sides.south, 1)
        """
    )
    assert res == (
        27,
        "Crushed Bauxite Ore",
        "Crushed Ilmenite Ore",
        32,
        True,
        12,
        True,
        3000,
        3000,
    )


def test_redstone_vanilla_bundled_and_wireless(oc_env: OCEnvironment) -> None:
    rs = oc_env.attach_redstone()
    rs.set_external_input(side=2, value=12)

    res = oc_env.run_lua(
        """
        local component = require("component")
        local sides = require("sides")
        local colors = require("colors")
        local event = require("event")
        local rs = component.redstone

        local ev_name, _, ev_side, old_v, new_v = event.pull(0.1, "redstone_changed")
        rs.setOutput(sides.south, 15)
        rs.setBundledOutput(sides.east, colors.lime, 255)
        rs.setWirelessFrequency(42)
        rs.setWirelessOutput(true)

        return ev_name, ev_side, new_v, rs.getOutput(sides.south), rs.getBundledOutput(sides.east, colors.lime), rs.getWirelessFrequency(), rs.getWirelessOutput()
        """
    )
    assert res == ("redstone_changed", 2, 12, 15, 255, 42, True)


def test_auto_mock_fluid_interface_me_interface_and_gt_machine_declarations(oc_env: OCEnvironment) -> None:
    """Verify that fluid_interface, me_interface, and gt_machine declarations are automatically mocked without manual attach calls."""
    res = oc_env.run_lua(
        """
        local component = require("component")

        -- 1. Explicit UUID declarations in script config table
        local CONFIG = {
            fluidInterfaceAddress = "f1000000-0000-4000-8000-000000000001",
            interfaceAddress = "b4b53e68-8262-40a4-9aaf-b1c9d9ca55a2",
            machineAddress = "e8b9066a-e6ff-4dae-b033-275fa283e38e",
            databaseAddress = "aebdc662-9cb1-4611-b360-0fcdd33d8aba",
        }

        -- Declared addresses are immediately present in component.list()
        local listed_types = {}
        for addr, ctype in component.list() do
            listed_types[addr] = ctype
        end
        assert(listed_types[CONFIG.fluidInterfaceAddress] == "fluid_interface")
        assert(listed_types[CONFIG.interfaceAddress] == "me_interface")
        assert(listed_types[CONFIG.machineAddress] == "gt_machine")
        assert(listed_types[CONFIG.databaseAddress] == "database")

        -- 2. Primary access & filtered component.list(ctype) auto-mocks on demand
        local fi = component.fluid_interface
        local mi = component.me_interface
        local gt = component.gt_machine

        local fluids = fi.getFluidsInNetwork()
        local items = mi.getItemsInNetwork()
        assert(type(fluids) == "table" and #fluids >= 1)
        assert(type(items) == "table" and #items >= 1)

        -- 3. Store item and fluid drop in database and configure both item and fluid interface slots
        local stored_item = mi.store({ name = items[1].name, damage = 0 }, CONFIG.databaseAddress, 1, 64)
        local stored_fluid = fi.store({ label = "drop of " .. fluids[1].label }, CONFIG.databaseAddress, 2)
        assert(stored_item == true)
        assert(stored_fluid == true)

        assert(mi.setInterfaceConfiguration(1, CONFIG.databaseAddress, 1, 64) == true)
        assert(fi.setFluidInterfaceConfiguration(1, CONFIG.databaseAddress, 2) == true)
        assert(mi.getInterfaceConfiguration(1).name == items[1].name)
        assert(fi.getFluidInterfaceConfiguration(1).name == fluids[1].name)

        -- 4. Call GT machine methods on the declared machineAddress without prior attach
        local sensor = component.invoke(CONFIG.machineAddress, "getSensorInformation")
        assert(type(sensor) == "table" and #sensor >= 1)
        assert(component.invoke(CONFIG.machineAddress, "isWorkAllowed") == true)

        return listed_types[CONFIG.fluidInterfaceAddress], listed_types[CONFIG.interfaceAddress], listed_types[CONFIG.machineAddress], items[1].name, fluids[1].name
        """
    )
    assert res == (
        "fluid_interface",
        "me_interface",
        "gt_machine",
        "minecraft:iron_ingot",
        "water",
    )


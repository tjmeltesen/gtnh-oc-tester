"""Tests for Phase 4 (GPU/Screen Emulator), Phase 5 (Execution Tracer & DAG), and End-to-End GTNH Workflows."""

from __future__ import annotations

from pathlib import Path

from gtnh_oc_tester import LuaSpecRunner, OCEnvironment


def test_gpu_screen_emulator_and_renderers(oc_env: OCEnvironment, tmp_path: Path) -> None:
    oc_env.run_lua(
        """
        local component = require("component")
        local term = require("term")
        local gpu = component.gpu

        gpu.setResolution(50, 12)
        gpu.setBackground(0x111827)
        gpu.setForeground(0x38BDF8)
        gpu.fill(1, 1, 50, 12, " ")

        gpu.setBackground(0x1E3A8A)
        gpu.setForeground(0xFFFFFF)
        gpu.fill(1, 1, 50, 1, " ")
        gpu.set(2, 1, "GTNH 2.9 Cleanroom & Petrochem Monitor")

        gpu.setBackground(0x111827)
        gpu.setForeground(0x34D399)
        gpu.set(3, 3, "Maintenance: OK (0 Problems)")
        gpu.setForeground(0xFBBF24)
        gpu.set(3, 5, "Ethylene Tank:    128,000 L / 256,000 L")
        gpu.set(3, 6, "Polyethylene:      64,000 L [CRAFTING]")

        -- Test off-screen buffer + bitblt
        local buf = gpu.allocateBuffer(20, 2)
        gpu.setActiveBuffer(buf)
        gpu.setBackground(0x065F46)
        gpu.setForeground(0xECFDF5)
        gpu.set(1, 1, "[LSC: 98.4% EU]")
        gpu.bitblt(0, 3, 9, 20, 1, buf, 1, 1)
        gpu.freeBuffer(buf)
        """
    )

    text_snap = oc_env.screen.to_text()
    assert "GTNH 2.9 Cleanroom & Petrochem Monitor" in text_snap
    assert "Maintenance: OK (0 Problems)" in text_snap
    assert "[LSC: 98.4% EU]" in text_snap

    ansi_snap = oc_env.screen.to_ansi()
    assert "\x1b[38;2;" in ansi_snap

    html_snap = oc_env.screen.to_html()
    assert "<div class=\"oc-screen\">" in html_snap

    png_path = oc_env.screen.to_png(tmp_path / "dashboard.png", scale=2)
    assert png_path.is_file()
    assert png_path.stat().st_size > 1000


def test_petrochem_autocraft_workflow_and_dag_loop_collapsing(
    oc_env: OCEnvironment, tmp_path: Path
) -> None:
    oc_env.attach_me_network("me_interface")
    lcr = oc_env.attach_gt_machine(
        "gt_machine",
        machine_name="multimachine.largechemicalreactor",
        stored_eu=2000000,
        eu_capacity=2000000,
        work_allowed=False,
        has_work=True,
        work_progress=0,
        work_max_progress=20,
    )
    rs = oc_env.attach_redstone()

    oc_env.me_network.add_fluid("ethylene", amount=400, label="Ethylene")
    oc_env.me_network.add_craftable(
        "ethylene",
        label="Ethylene",
        recipe_type="fluid",
        duration_ticks=6,
    )

    oc_env.run_lua(
        """
        local component = require("component")
        local sides = require("sides")
        local me = component.me_interface
        local lcr = component.gt_machine
        local rs = component.redstone

        local function check_and_refill_ethylene()
          local fl = me.getFluidInNetwork("ethylene")
          local current_amt = (fl and fl[1] and fl[1].amount) or 0
          if current_amt < 1000 then
            local recipe = me.getCraftable({ name = "ethylene" }, "fluid")
            local job = recipe.request(2000, true, "CPU-1")
            rs.setOutput(sides.north, 15)
            while not job.isDone() do
              os.sleep(0.1)
            end
            rs.setOutput(sides.north, 0)
            lcr.setWorkAllowed(true)
          end
        end

        check_and_refill_ethylene()
        """
    )

    assert lcr.work_allowed is True
    assert rs.outputs[2] == 0
    ethylene_after = oc_env.me_network.fluids[0]["amount"]
    assert ethylene_after == 2400

    dag = oc_env.build_dag(collapse_loops=True)
    mermaid = dag.to_mermaid()
    assert "Poll Loop" in mermaid or "Loop" in mermaid
    assert "AECraftable.request" in mermaid
    assert "gt_machine.setWorkAllowed(true)" in mermaid

    artifacts = oc_env.save_artifacts(tmp_path, prefix="petrochem_autocraft")
    assert artifacts["mermaid"].is_file()
    assert artifacts["dot"].is_file()
    assert artifacts["dag_html"].is_file()
    assert artifacts["screen_png"].is_file()


def test_pure_lua_spec_suites() -> None:
    runner = LuaSpecRunner()
    lua_dir = Path(__file__).resolve().parent / "lua"
    spec_files = sorted(lua_dir.glob("*_spec.lua"))
    assert len(spec_files) >= 2
    for sf in spec_files:
        results = runner.run_spec_file(sf)
        assert results, f"No specs found in {sf}"
        for r in results:
            assert r.passed, f"Lua spec failed: {r.full_name}\n{r.error}"

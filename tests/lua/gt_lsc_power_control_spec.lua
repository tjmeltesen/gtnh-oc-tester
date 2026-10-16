-- Pure-Lua Busted-style Spec: GregTech Lapotronic Supercapacitor (LSC) & Multiblock Control
local component = require("component")
local sides = require("sides")

describe("GTNH 2.9 LSC Power & Multiblock Hysteresis Controller", function()
  local lsc_addr
  local ebf_addr

  before_each(function()
    lsc_addr = mock_oc.attach("gt_machine", "11111111-1111-4000-8000-000000000001", {
      machine_name = "multimachine.supercapacitor",
      stored_eu = 1500000,
      eu_capacity = 10000000,
      work_allowed = true,
    })
    ebf_addr = mock_oc.attach("gt_machine", "22222222-2222-4000-8000-000000000002", {
      machine_name = "multimachine.blastfurnace",
      stored_eu = 500000,
      eu_capacity = 1000000,
      work_allowed = true,
      has_work = true,
    })
    mock_oc.attach("redstone")
  end)

  it("throttles EBF and turns on backup generator when LSC drops below 20%", function()
    local lsc = component.proxy(lsc_addr)
    local ebf = component.proxy(ebf_addr)
    local rs = component.redstone
    local gpu = component.gpu

    local ratio = lsc.getStoredEU() / lsc.getEUCapacity()
    if ratio < 0.20 then
      ebf.setWorkAllowed(false)
      rs.setOutput(sides.bottom, 15)
      gpu.set(1, 1, "ALERT: LOW EU - BACKUP GEN ON")
    end

    assert.is_false(ebf.isWorkAllowed())
    assert.equals(15, rs.getOutput(sides.bottom))
    assert.truthy(mock_oc.screen_text():find("ALERT: LOW EU", 1, true))
  end)

  it("re-enables EBF when LSC is charged above 85%", function()
    mock_oc.set_gt_machine(lsc_addr, { stored_eu = 9000000 })
    local lsc = component.proxy(lsc_addr)
    local ebf = component.proxy(ebf_addr)
    local rs = component.redstone

    local ratio = lsc.getStoredEU() / lsc.getEUCapacity()
    if ratio > 0.85 then
      ebf.setWorkAllowed(true)
      rs.setOutput(sides.bottom, 0)
    end

    assert.is_true(ebf.isWorkAllowed())
    assert.equals(0, rs.getOutput(sides.bottom))
  end)
end)

-- Pure-Lua Busted-style Spec: AE2 & AE2FC Auto-Crafting and Fluid Stocking
local component = require("component")
local sides = require("sides")

describe("GTNH 2.9 AE2 & AE2FC Stocking Controller", function()
  before_each(function()
    mock_oc.attach("me_interface")
    mock_oc.attach("fluid_interface")
    mock_oc.attach("redstone")
    mock_oc.add_me_item("gregtech:gt.metaitem.01", 120, "Polytetrafluoroethylene Bar", 11473)
    mock_oc.add_me_fluid("molten.epoxid", 500, "Molten Epoxid")
    mock_oc.add_me_craftable("molten.epoxid", "fluid", 4, "Molten Epoxid")
  end)

  it("triggers an AE2 crafting job when fluid stock falls below threshold", function()
    local me = component.me_interface
    local fi = component.fluid_interface
    local rs = component.redstone

    local fluids = fi.getFluidInNetwork("molten.epoxid")
    assert.equals(500, fluids[1].amount)

    local craftable = me.getCraftable({ name = "molten.epoxid" }, "fluid")
    assert.is_not_nil(craftable)

    local job = craftable.request(4000, true, "CPU-1")
    rs.setOutput(sides.east, 15)
    assert.is_false(job.isDone())

    while not job.isDone() do
      os.sleep(0.1)
    end
    rs.setOutput(sides.east, 0)

    local updated = fi.getFluidInNetwork("molten.epoxid")
    assert.equals(4500, updated[1].amount)
    assert.equals(0, rs.getOutput(sides.east))
  end)
end)

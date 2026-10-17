"""Stateful simulator for Transposer, Inventory Controller, Tank Controller, Database, and StackSlot userdata."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from ..auto_mock import SchemaBackedComponent


class StackSlotUserdata:
    """Emulates OpenComputers `ItemStackArrayValue` (`StackSlot`) returned by `getAllStacks(side)`."""

    def __init__(self, slots: List[Optional[Dict[str, Any]]]) -> None:
        self.slots = [dict(s) if s is not None else {} for s in slots]
        self.index = 0

    def reset(self) -> None:
        self.index = 0

    def count(self) -> int:
        return len(self.slots)

    def get_all(self) -> Dict[int, Dict[str, Any]]:
        # Provide both 0-based and 1-based keys for compatibility with all OC/GTNH scripts
        result: Dict[int, Dict[str, Any]] = {}
        for idx, stack in enumerate(self.slots):
            result[idx] = dict(stack) if stack else {}
            result[idx + 1] = dict(stack) if stack else {}
        return result

    def next_stack(self) -> Optional[Dict[str, Any]]:
        if self.index >= len(self.slots):
            return None
        val = self.slots[self.index]
        self.index += 1
        return dict(val) if val is not None else {}

    def __oc_lua_proxy__(self, sandbox: Any) -> Any:
        lua_slots = sandbox.python_to_lua([dict(s) if s else {} for s in self.slots])
        factory = getattr(sandbox, "_proxy_factories", {}).get("inv_stack_iter")
        if factory is None:
            factory = sandbox.lua.eval(
                """
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
            )
        return factory(lua_slots, len(self.slots))


@dataclass
class SideInventoryState:
    name: str = "tile.chest"
    size: int = 27
    slots: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    tanks: List[Dict[str, Any]] = field(
        default_factory=lambda: [{"name": None, "label": None, "amount": 0, "capacity": 16000}]
    )


class WorldInventoryGrid:
    """Shared world-side inventories and fluid tanks across transposer, inventory_controller, and tank_controller."""

    def __init__(self) -> None:
        self.sides: Dict[int, SideInventoryState] = {
            side: SideInventoryState(name=f"inventory_side_{side}", size=27)
            for side in range(6)
        }
        self.robot_slots: Dict[int, Dict[str, Any]] = {}
        self.robot_size: int = 16
        self.robot_selected_slot: int = 1
        self.robot_equipped: Optional[Dict[str, Any]] = None
        self.robot_tanks: List[Dict[str, Any]] = [
            {"name": None, "label": None, "amount": 0, "capacity": 16000}
        ]

    def get_side(self, side: int) -> SideInventoryState:
        return self.sides.setdefault(int(side), SideInventoryState())

    def set_stack(
        self,
        side: int,
        slot: int,
        name: str,
        size: int = 1,
        damage: int = 0,
        label: Optional[str] = None,
        max_size: int = 64,
        ore_dict: Optional[List[str]] = None,
        nbt: Optional[str] = None,
    ) -> Dict[str, Any]:
        inv = self.get_side(int(side))
        stack = {
            "name": name,
            "label": label or name.split(":")[-1].replace("_", " ").title(),
            "size": int(size),
            "maxSize": int(max_size),
            "damage": int(damage),
            "maxDamage": 0,
            "hasTag": bool(nbt),
        }
        if ore_dict:
            stack["oreNames"] = list(ore_dict)
        if nbt:
            stack["nbt"] = nbt
        inv.slots[int(slot)] = stack
        return stack

    def set_tank(
        self,
        side: int,
        tank_index: int = 1,
        name: Optional[str] = None,
        amount: int = 0,
        capacity: int = 16000,
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        inv = self.get_side(int(side))
        idx = max(1, int(tank_index)) - 1
        while len(inv.tanks) <= idx:
            inv.tanks.append({"name": None, "label": None, "amount": 0, "capacity": 16000})
        tank = {
            "name": name,
            "label": label or (name.replace("_", " ").title() if name else None),
            "amount": int(amount),
            "capacity": int(capacity),
        }
        inv.tanks[idx] = tank
        return tank


class DatabaseSimulator(SchemaBackedComponent):
    """Emulates OpenComputers `database` upgrade component."""

    def __init__(
        self,
        component_type: str = "database",
        address: Optional[str] = None,
        slot: int = -1,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
    ) -> None:
        super().__init__(
            component_type=component_type,
            address=address,
            slot=slot,
            host=host,
            variant=variant,
            registry=registry,
            bus=bus,
        )
        self.entries: Dict[int, Dict[str, Any]] = {}

    def _impl_get(self, slot: int) -> Optional[Dict[str, Any]]:
        item = self.entries.get(int(slot))
        return dict(item) if item else None

    def _impl_set(
        self,
        slot: int,
        item_id: str,
        damage: int = 0,
        nbt: Optional[str] = None,
    ) -> Tuple[bool, None]:
        self.entries[int(slot)] = {
            "name": str(item_id),
            "label": str(item_id).split(":")[-1].replace("_", " ").title(),
            "damage": int(damage or 0),
            "size": 1,
            "maxSize": 64,
            "hasTag": bool(nbt),
            "nbt": nbt,
        }
        return (True, None)

    def _impl_clear(self, slot: int) -> bool:
        return self.entries.pop(int(slot), None) is not None

    def _impl_computeHash(self, slot: int) -> Optional[str]:
        entry = self.entries.get(int(slot))
        if not entry:
            return None
        raw = f"{entry.get('name')}:{entry.get('damage', 0)}:{entry.get('nbt', '')}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _impl_indexOf(self, hash_val: str) -> int:
        for s in sorted(self.entries):
            if self._impl_computeHash(s) == str(hash_val):
                return s
        return -1

    def _impl_copy(self, from_slot: int, to_slot: int, db_address: Optional[str] = None) -> bool:
        src = self.entries.get(int(from_slot))
        target_db = self
        if db_address and self.bus:
            other = self.bus.get_component(db_address)
            if isinstance(other, DatabaseSimulator):
                target_db = other
        overwritten = int(to_slot) in target_db.entries
        if src:
            target_db.entries[int(to_slot)] = dict(src)
        else:
            target_db.entries.pop(int(to_slot), None)
        return overwritten

    def _impl_clone(self, db_address: str) -> int:
        if not self.bus:
            return 0
        other = self.bus.get_component(db_address)
        if not isinstance(other, DatabaseSimulator):
            return 0
        count = 0
        for s, item in self.entries.items():
            if s in other.entries:
                count += 1
            other.entries[s] = dict(item)
        return count


class TransposerInventorySimulator(SchemaBackedComponent):
    """Emulates `transposer`, `inventory_controller`, and `tank_controller` sharing a WorldInventoryGrid."""

    def __init__(
        self,
        component_type: str = "transposer",
        address: Optional[str] = None,
        slot: int = -1,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
        grid: Optional[WorldInventoryGrid] = None,
    ) -> None:
        super().__init__(
            component_type=component_type,
            address=address,
            slot=slot,
            host=host,
            variant=variant,
            registry=registry,
            bus=bus,
        )
        self.grid: WorldInventoryGrid = grid or (
            bus.inventory_grid if bus is not None else WorldInventoryGrid()
        )
        self.fluid_transfer_rate = 1000

    # Inventory methods
    def _impl_getInventoryName(self, side: int) -> str:
        return self.grid.get_side(int(side)).name

    def _impl_getInventorySize(self, side: int) -> int:
        return int(self.grid.get_side(int(side)).size)

    def _impl_getStackInSlot(self, side: int, slot: int) -> Optional[Dict[str, Any]]:
        s = self.grid.get_side(int(side)).slots.get(int(slot))
        return dict(s) if s and s.get("size", 0) > 0 else None

    def _impl_getSlotStackSize(self, side: int, slot: int) -> int:
        s = self._impl_getStackInSlot(side, slot)
        return int(s["size"]) if s else 0

    def _impl_getSlotMaxStackSize(self, side: int, slot: int) -> int:
        s = self._impl_getStackInSlot(side, slot)
        return int(s.get("maxSize", 64)) if s else 64

    def _impl_getAllStacks(self, side: int) -> StackSlotUserdata:
        inv = self.grid.get_side(int(side))
        slots_list = [inv.slots.get(i) for i in range(1, inv.size + 1)]
        return StackSlotUserdata(slots_list)

    def _impl_setStackDisplayName(self, side: int, slot: int, label: str) -> bool:
        inv = self.grid.get_side(int(side))
        if int(slot) in inv.slots:
            inv.slots[int(slot)]["label"] = str(label)
            return True
        return False

    def _impl_compareStacks(
        self,
        side: int,
        slot_a: int,
        slot_b: int,
        check_nbt: bool = False,
    ) -> bool:
        sa = self._impl_getStackInSlot(side, slot_a)
        sb = self._impl_getStackInSlot(side, slot_b)
        if not sa or not sb:
            return False
        if sa.get("name") != sb.get("name") or sa.get("damage", 0) != sb.get("damage", 0):
            return False
        if check_nbt and sa.get("nbt") != sb.get("nbt"):
            return False
        return True

    def _impl_areStacksEquivalent(self, side: int, slot_a: int, slot_b: int) -> bool:
        if self._impl_compareStacks(side, slot_a, slot_b, False):
            return True
        sa = self._impl_getStackInSlot(side, slot_a)
        sb = self._impl_getStackInSlot(side, slot_b)
        if not sa or not sb:
            return False
        ores_a = set(sa.get("oreNames", []))
        ores_b = set(sb.get("oreNames", []))
        return bool(ores_a and (ores_a & ores_b))

    def _impl_store(self, side: int, slot: int, db_address: str, db_slot: int) -> bool:
        stack = self._impl_getStackInSlot(side, slot)
        if not stack or not self.bus:
            return False
        db = self.bus.get_component(db_address)
        if isinstance(db, DatabaseSimulator):
            db.entries[int(db_slot)] = dict(stack)
            return True
        return False

    def _impl_compareStackToDatabase(
        self,
        side: int,
        slot: int,
        db_address: str,
        db_slot: int,
        check_nbt: bool = False,
    ) -> bool:
        stack = self._impl_getStackInSlot(side, slot)
        if not stack or not self.bus:
            return False
        db = self.bus.get_component(db_address)
        if not isinstance(db, DatabaseSimulator):
            return False
        db_item = db.entries.get(int(db_slot))
        if not db_item:
            return False
        if stack.get("name") != db_item.get("name") or stack.get("damage", 0) != db_item.get("damage", 0):
            return False
        if check_nbt and stack.get("nbt") != db_item.get("nbt"):
            return False
        return True

    def _impl_transferItem(
        self,
        source_side: int,
        sink_side: int,
        count: int = 64,
        source_slot: Optional[int] = None,
        sink_slot: Optional[int] = None,
    ) -> int:
        src_inv = self.grid.get_side(int(source_side))
        dst_inv = self.grid.get_side(int(sink_side))
        max_move = int(count) if count is not None else 64

        src_slots = [int(source_slot)] if source_slot is not None else sorted(src_inv.slots.keys())
        for s_slot in src_slots:
            s_stack = src_inv.slots.get(s_slot)
            if not s_stack or s_stack.get("size", 0) <= 0:
                continue
            move_amt = min(max_move, int(s_stack["size"]))
            target_slots = (
                [int(sink_slot)]
                if sink_slot is not None
                else list(range(1, dst_inv.size + 1))
            )
            for d_slot in target_slots:
                d_stack = dst_inv.slots.get(d_slot)
                if d_stack is None or d_stack.get("size", 0) == 0:
                    moved = dict(s_stack)
                    moved["size"] = move_amt
                    dst_inv.slots[d_slot] = moved
                    s_stack["size"] -= move_amt
                    if s_stack["size"] <= 0:
                        src_inv.slots.pop(s_slot, None)
                    return move_amt
                if (
                    d_stack.get("name") == s_stack.get("name")
                    and d_stack.get("damage", 0) == s_stack.get("damage", 0)
                ):
                    space = int(d_stack.get("maxSize", 64)) - int(d_stack["size"])
                    if space > 0:
                        actual = min(move_amt, space)
                        d_stack["size"] += actual
                        s_stack["size"] -= actual
                        if s_stack["size"] <= 0:
                            src_inv.slots.pop(s_slot, None)
                        return actual
        return 0

    def _impl_swap(
        self,
        source_side: int,
        sink_side: int,
        source_slot: int,
        sink_slot: int,
        safe: bool = False,
    ) -> bool:
        src_inv = self.grid.get_side(int(source_side))
        dst_inv = self.grid.get_side(int(sink_side))
        sa = src_inv.slots.get(int(source_slot))
        sb = dst_inv.slots.get(int(sink_slot))
        if safe and (not sa or not sb):
            return False
        if sa:
            dst_inv.slots[int(sink_slot)] = sa
        else:
            dst_inv.slots.pop(int(sink_slot), None)
        if sb:
            src_inv.slots[int(source_slot)] = sb
        else:
            src_inv.slots.pop(int(source_slot), None)
        return True

    # Tank / Fluid methods
    def _impl_getTankCount(self, side: int) -> int:
        return len(self.grid.get_side(int(side)).tanks)

    def _impl_getTankLevel(self, side: int, tank: int = 1) -> int:
        tanks = self.grid.get_side(int(side)).tanks
        idx = max(1, int(tank or 1)) - 1
        if 0 <= idx < len(tanks):
            return int(tanks[idx].get("amount", 0))
        return 0

    def _impl_getTankCapacity(self, side: int, tank: int = 1) -> int:
        tanks = self.grid.get_side(int(side)).tanks
        idx = max(1, int(tank or 1)) - 1
        if 0 <= idx < len(tanks):
            return int(tanks[idx].get("capacity", 16000))
        return 0

    def _impl_getFluidInTank(self, side: int, tank: Optional[int] = None) -> Any:
        tanks = self.grid.get_side(int(side)).tanks
        if tank is None:
            return [dict(t) for t in tanks]
        idx = max(1, int(tank)) - 1
        if 0 <= idx < len(tanks):
            return dict(tanks[idx])
        return {"amount": 0, "capacity": 16000}

    def _impl_transferFluid(
        self,
        source_side: int,
        sink_side: int,
        count: int = 1000,
        source_tank: int = 1,
    ) -> Tuple[bool, int]:
        src_tanks = self.grid.get_side(int(source_side)).tanks
        dst_tanks = self.grid.get_side(int(sink_side)).tanks
        s_idx = max(1, int(source_tank or 1)) - 1
        if s_idx >= len(src_tanks) or not dst_tanks:
            return (False, 0)
        src = src_tanks[s_idx]
        dst = dst_tanks[0]
        if not src.get("name") or src.get("amount", 0) <= 0:
            return (False, 0)
        if dst.get("name") and dst.get("amount", 0) > 0 and dst.get("name") != src.get("name"):
            return (False, 0)
        req = int(count) if count is not None else 1000
        space = int(dst.get("capacity", 16000)) - int(dst.get("amount", 0))
        moved = min(req, int(src["amount"]), max(0, space))
        if moved <= 0:
            return (False, 0)
        dst["name"] = src["name"]
        dst["label"] = src.get("label") or src["name"]
        dst["amount"] = int(dst.get("amount", 0)) + moved
        src["amount"] = int(src["amount"]) - moved
        if src["amount"] <= 0:
            src["name"] = None
            src["label"] = None
        return (True, moved)

    def _impl_getFluidTransferRate(self) -> int:
        return int(self.fluid_transfer_rate)

    # Robot-specific inventory_controller & tank_controller methods
    def _impl_getStackInInternalSlot(self, slot: Optional[int] = None) -> Optional[Dict[str, Any]]:
        s = int(slot) if slot is not None else self.grid.robot_selected_slot
        item = self.grid.robot_slots.get(s)
        return dict(item) if item and item.get("size", 0) > 0 else None

    def _impl_equip(self) -> bool:
        s = self.grid.robot_selected_slot
        cur = self.grid.robot_slots.get(s)
        self.grid.robot_slots[s] = self.grid.robot_equipped  # type: ignore[assignment]
        if self.grid.robot_slots[s] is None:
            self.grid.robot_slots.pop(s, None)
        self.grid.robot_equipped = cur
        return True

    def _impl_dropIntoSlot(
        self,
        facing: int,
        slot: int,
        count: int = 64,
        from_side: Optional[int] = None,
    ) -> bool:
        s = self.grid.robot_selected_slot
        item = self.grid.robot_slots.get(s)
        if not item or item.get("size", 0) <= 0:
            return False
        move = min(int(count or 64), int(item["size"]))
        inv = self.grid.get_side(int(facing))
        moved = dict(item)
        moved["size"] = move
        inv.slots[int(slot)] = moved
        item["size"] -= move
        if item["size"] <= 0:
            self.grid.robot_slots.pop(s, None)
        return True

    def _impl_suckFromSlot(
        self,
        facing: int,
        slot: int,
        count: int = 64,
        from_side: Optional[int] = None,
    ) -> bool:
        inv = self.grid.get_side(int(facing))
        item = inv.slots.get(int(slot))
        if not item or item.get("size", 0) <= 0:
            return False
        move = min(int(count or 64), int(item["size"]))
        s = self.grid.robot_selected_slot
        moved = dict(item)
        moved["size"] = move
        self.grid.robot_slots[s] = moved
        item["size"] -= move
        if item["size"] <= 0:
            inv.slots.pop(int(slot), None)
        return True

    def _impl_getFluidInInternalTank(self, slot: int = 1) -> Optional[Dict[str, Any]]:
        idx = max(1, int(slot or 1)) - 1
        if 0 <= idx < len(self.grid.robot_tanks):
            return dict(self.grid.robot_tanks[idx])
        return None

    # Container fluid & additional robot inventory/tank controller methods
    def _impl_getContainerCapacityInSlot(self, side: int, slot: int) -> int:
        stack = self._impl_getStackInSlot(side, slot)
        if not stack:
            return 0
        fluid = stack.get("fluid") if isinstance(stack.get("fluid"), dict) else {}
        return int(fluid.get("capacity", stack.get("capacity", 1000)))

    def _impl_getContainerLevelInSlot(self, side: int, slot: int) -> int:
        stack = self._impl_getStackInSlot(side, slot)
        if not stack:
            return 0
        fluid = stack.get("fluid") if isinstance(stack.get("fluid"), dict) else {}
        return int(fluid.get("amount", stack.get("amount", 0)))

    def _impl_getFluidInContainerInSlot(self, side: int, slot: int) -> Optional[Dict[str, Any]]:
        stack = self._impl_getStackInSlot(side, slot)
        if not stack:
            return None
        if isinstance(stack.get("fluid"), dict):
            return dict(stack["fluid"])
        return {"name": None, "label": None, "amount": 0, "capacity": 1000}

    def _impl_transferFluidBetweenContainers(
        self,
        source_side: int,
        source_slot: int,
        sink_side: int,
        sink_slot: int,
        count: int = 1000,
        *args: Any,
    ) -> Tuple[bool, int]:
        moved = int(count) if count is not None else 1000
        return (True, moved)

    def _impl_transferFluidFromContainerToTank(
        self,
        inventory_side: int,
        inventory_slot: int,
        tank_side: int,
        count: int = 1000,
        *args: Any,
    ) -> Tuple[bool, int]:
        moved = int(count) if count is not None else 1000
        return (True, moved)

    def _impl_transferFluidFromTankToContainer(
        self,
        tank_side: int,
        inventory_side: int,
        inventory_slot: int,
        count: int = 1000,
        *args: Any,
    ) -> Tuple[bool, int]:
        moved = int(count) if count is not None else 1000
        return (True, moved)

    def _impl_compareToDatabase(
        self,
        slot: int,
        db_address: str,
        db_slot: int,
        check_nbt: bool = False,
    ) -> bool:
        stack = self._impl_getStackInInternalSlot(slot)
        if not stack or not self.bus:
            return False
        db = self.bus.get_component(db_address)
        if not isinstance(db, DatabaseSimulator):
            return False
        db_item = db.entries.get(int(db_slot))
        if not db_item:
            return False
        if stack.get("name") != db_item.get("name") or stack.get("damage", 0) != db_item.get("damage", 0):
            return False
        if check_nbt and stack.get("nbt") != db_item.get("nbt"):
            return False
        return True

    def _impl_storeInternal(self, slot: int, db_address: str, db_slot: int) -> bool:
        stack = self._impl_getStackInInternalSlot(slot)
        if not stack or not self.bus:
            return False
        db = self.bus.get_component(db_address)
        if isinstance(db, DatabaseSimulator):
            db.entries[int(db_slot)] = dict(stack)
            return True
        return False

    def _impl_isEquivalentTo(self, other_slot: int) -> bool:
        sa = self._impl_getStackInInternalSlot(self.grid.robot_selected_slot)
        sb = self._impl_getStackInInternalSlot(int(other_slot))
        if not sa or not sb:
            return False
        if sa.get("name") == sb.get("name") and sa.get("damage", 0) == sb.get("damage", 0):
            return True
        ores_a = set(sa.get("oreNames", []))
        ores_b = set(sb.get("oreNames", []))
        return bool(ores_a and (ores_a & ores_b))

    def _impl_getItemInventorySize(self, slot: int) -> int:
        stack = self._impl_getStackInInternalSlot(slot)
        return int(stack.get("inventorySize", 0)) if stack else 0

    def _impl_dropIntoItemInventory(self, inventory_slot: int, slot: int, count: int = 64) -> int:
        return int(count or 0)

    def _impl_suckFromItemInventory(self, inventory_slot: int, slot: int, count: int = 64) -> int:
        return int(count or 0)

    def _impl_getUpgradeContainerTier(self, slot: int) -> int:
        return 3

    def _impl_getUpgradeContainerType(self, slot: int) -> str:
        return "None"

    def _impl_installUpgrade(self, slot: int = 1) -> bool:
        return True

    def _impl_drain(self, amount: int = 1000) -> bool:
        return True

    def _impl_fill(self, amount: int = 1000) -> bool:
        return True

    def _impl_getFluidInTankInSlot(self, slot: Optional[int] = None) -> Optional[Dict[str, Any]]:
        stack = self._impl_getStackInInternalSlot(slot)
        if stack and isinstance(stack.get("fluid"), dict):
            return dict(stack["fluid"])
        return {"name": None, "label": None, "amount": 0, "capacity": 1000}

    def _impl_getTankCapacityInSlot(self, slot: Optional[int] = None) -> int:
        fluid = self._impl_getFluidInTankInSlot(slot)
        return int(fluid.get("capacity", 1000)) if fluid else 0

    def _impl_getTankLevelInSlot(self, slot: Optional[int] = None) -> int:
        fluid = self._impl_getFluidInTankInSlot(slot)
        return int(fluid.get("amount", 0)) if fluid else 0

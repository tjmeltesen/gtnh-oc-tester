"""Component Bus managing attached GTNH 2.9 components, proxies, and Lua `component` library."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..specs.oc_config import OCMachineConfig
from ..specs.registry import SchemaRegistry, get_default_registry
from .auto_mock import ComponentCallRecord, SchemaBackedComponent
from .oc_components import (
    ComputerComponent,
    DataCardComponent,
    DriveComponent,
    EEPROMComponent,
    FilesystemComponent,
    InternetComponent,
    KeyboardComponent,
    ModemComponent,
    SoundCardComponent,
)
from .simulators.ae2 import AE2NetworkComponent, MENetworkState
from .simulators.gregtech import GTMachineSimulator
from .simulators.inventory import (
    DatabaseSimulator,
    TransposerInventorySimulator,
    WorldInventoryGrid,
)
from .simulators.redstone import RedstoneSimulator


AE2_COMPONENT_TYPES = {
    "me_controller",
    "me_interface",
    "fluid_interface",
    "upgrade_me",
    "level_maintainer",
    "oc_pattern_editor",
    "me_exportbus",
    "me_importbus",
    "me_storagebus",
    "fluid_exportbus",
    "fluid_importbus",
    "fluid_storagebus",
    "essentia_exportbus",
    "essentia_importbus",
    "essentia_storagebus",
}

GT_COMPONENT_TYPES = {
    "gt_machine",
    "gt_batterybuffer",
    "gt_energycontainer",
    "bec_storage",
    "bec_diode",
    "bec_io_node",
}

INVENTORY_COMPONENT_TYPES = {
    "transposer",
    "inventory_controller",
    "tank_controller",
}

OC_VANILLA_COMPONENT_CLASSES = {
    "filesystem": FilesystemComponent,
    "eeprom": EEPROMComponent,
    "computer": ComputerComponent,
    "keyboard": KeyboardComponent,
    "modem": ModemComponent,
    "internet": InternetComponent,
    "data": DataCardComponent,
    "drive": DriveComponent,
    "sound": SoundCardComponent,
}

# Known indirect (world/server-thread synchronous) methods in OpenComputers
INDIRECT_METHODS_BY_TYPE: Dict[str, set[str]] = {
    "transposer": {
        "transferItem",
        "transferFluid",
        "swap",
        "setStackDisplayName",
        "transferFluidBetweenContainers",
        "transferFluidFromContainerToTank",
        "transferFluidFromTankToContainer",
    },
    "inventory_controller": {
        "equip",
        "dropIntoSlot",
        "suckFromSlot",
        "dropIntoItemInventory",
        "suckFromItemInventory",
        "installUpgrade",
        "setStackDisplayName",
    },
    "tank_controller": {
        "drain",
        "fill",
    },
    "filesystem": {
        "makeDirectory",
        "remove",
        "rename",
        "setLabel",
    },
    "eeprom": {
        "set",
        "setData",
        "setLabel",
        "makeReadonly",
    },
    "drive": {
        "setLabel",
    },
}

# Known direct call limits (cost = 1.0 / limit) in OpenComputers
DIRECT_CALL_LIMITS: Dict[Tuple[str, str], float] = {
    ("gpu", "copy"): 25.0,
    ("gpu", "fill"): 50.0,
    ("gpu", "set"): 100.0,
    ("gpu", "get"): 50.0,
    ("gpu", "setBackground"): 100.0,
    ("gpu", "setForeground"): 100.0,
    ("gpu", "bitblt"): 2.0,
    ("filesystem", "read"): 15.0,
    ("filesystem", "seek"): 15.0,
    ("filesystem", "write"): 5.0,
    ("filesystem", "open"): 4.0,
    ("filesystem", "exists"): 20.0,
    ("filesystem", "isDirectory"): 20.0,
    ("filesystem", "size"): 20.0,
    ("filesystem", "lastModified"): 20.0,
    ("filesystem", "list"): 5.0,
}


class ComponentBus:
    """Central bus connecting emulated GTNH 2.9 components to the OpenComputers Lua sandbox."""

    def __init__(
        self,
        host: str = "computer",
        registry: Optional[SchemaRegistry] = None,
        scheduler: Optional[Any] = None,
        sandbox: Optional[Any] = None,
        config: Optional[OCMachineConfig] = None,
        call_budget_limit: Optional[float] = None,
        enforce_call_budget: bool = False,
        vfs: Optional[Any] = None,
    ) -> None:
        self.host = host
        self.registry = registry or get_default_registry()
        self.scheduler = scheduler
        self.sandbox = sandbox
        self.vfs = vfs
        self.config = config or OCMachineConfig()

        self.call_budget_limit: float = (
            float(call_budget_limit)
            if call_budget_limit is not None
            else float(self.config.call_budget_per_tick)
        )
        self.current_tick_budget_used: float = 0.0
        self.enforce_call_budget: bool = bool(enforce_call_budget)
        self.budget_exhaustions: int = 0

        self.components: Dict[str, SchemaBackedComponent] = {}
        self.primaries: Dict[str, str] = {}
        self.call_log: List[ComponentCallRecord] = []
        self.call_listeners: List[Callable[[ComponentCallRecord], None]] = []

        self.me_network = MENetworkState(bus=self)
        self.inventory_grid = WorldInventoryGrid()

        if self.scheduler is not None:
            self.scheduler.add_tick_hook(self._on_tick)

    def _on_tick(self, current_tick: int) -> None:
        self.current_tick_budget_used = 0.0
        self.me_network.on_tick(current_tick)
        for comp in list(self.components.values()):
            if hasattr(comp, "on_tick"):
                comp.on_tick(current_tick)  # type: ignore[attr-defined]

    def reset_call_budget(self) -> None:
        """Reset the accumulated direct-call budget for the current tick."""
        self.current_tick_budget_used = 0.0

    def get_method_info(self, address: str, method: str) -> Dict[str, Any]:
        """Return OpenComputers callback metadata `{"direct": bool, "getter": bool, "setter": bool, "cost": float}`."""
        comp = self.get_component(str(address))
        if comp is None:
            raise KeyError(f"no such component: {address}")

        mname = str(method)
        ctype = comp.component_type
        doc = comp.get_doc(mname) or ""

        is_field = mname in comp.extra_fields or mname in comp.schema.dump_fields
        getter = bool(is_field)
        setter = bool(is_field and mname == "fsnode")

        # Parse explicit `direct:true/false` and `limit:N` if present in dump doc or method metadata
        direct = True
        cost: Optional[float] = None

        m_direct = re.search(r"\bdirect\s*[:=]\s*(true|false)\b", doc, flags=re.IGNORECASE)
        if m_direct:
            direct = m_direct.group(1).lower() == "true"
        elif mname in INDIRECT_METHODS_BY_TYPE.get(ctype, set()):
            direct = False

        m_limit = re.search(r"\blimit\s*[:=]\s*([-+]?\d*\.?\d+)\b", doc, flags=re.IGNORECASE)
        if m_limit:
            lim = float(m_limit.group(1))
            cost = (1.0 / lim) if lim > 0 else 0.1
        elif (ctype, mname) in DIRECT_CALL_LIMITS:
            lim = DIRECT_CALL_LIMITS[(ctype, mname)]
            cost = (1.0 / lim) if lim > 0 else 0.1

        if not direct:
            cost = 1.0
        elif cost is None:
            cost = 0.1

        return {
            "direct": bool(direct),
            "getter": bool(getter),
            "setter": bool(setter),
            "cost": float(cost),
        }

    def consume_call_budget(
        self,
        address: str,
        method: str,
        advance_tick_on_exhaustion: bool = False,
    ) -> bool:
        """Consume call budget for `(address, method)`.

        Returns `True` if the call fits within the current tick's budget and can execute
        immediately as a direct call, or `False` if the call budget for this tick is
        exhausted (or the method is indirect), signaling that `machine.lua` should yield
        and execute on the next tick.
        """
        info = self.get_method_info(address, method)
        if not info["direct"]:
            if self.enforce_call_budget and advance_tick_on_exhaustion and self.scheduler is not None:
                self.scheduler.step_ticks(1)
            return not self.enforce_call_budget

        cost = float(info["cost"])
        if self.enforce_call_budget and (self.current_tick_budget_used + cost > self.call_budget_limit):
            self.budget_exhaustions += 1
            if advance_tick_on_exhaustion and self.scheduler is not None:
                self.scheduler.step_ticks(1)
                self.current_tick_budget_used = cost
            return False

        self.current_tick_budget_used += cost
        return True

    def record_call(self, record: ComponentCallRecord) -> None:
        self.call_log.append(record)
        for listener in self.call_listeners:
            listener(record)

    def attach(
        self,
        component_type: str,
        address: Optional[str] = None,
        slot: int = -1,
        variant: Optional[str] = None,
        primary: Optional[bool] = None,
        component_instance: Optional[SchemaBackedComponent] = None,
        **kwargs: Any,
    ) -> SchemaBackedComponent:
        """Create and attach a GTNH 2.9 component to the bus."""
        if component_instance is not None:
            comp = component_instance
            comp.bus = self
        elif component_type in AE2_COMPONENT_TYPES:
            comp = AE2NetworkComponent(
                component_type=component_type,
                address=address,
                slot=slot,
                host=self.host,
                variant=variant,
                registry=self.registry,
                bus=self,
                network=self.me_network,
            )
        elif component_type in GT_COMPONENT_TYPES:
            comp = GTMachineSimulator(
                component_type=component_type,
                address=address,
                slot=slot,
                host=self.host,
                variant=variant,
                registry=self.registry,
                bus=self,
                **kwargs,
            )
        elif component_type in INVENTORY_COMPONENT_TYPES:
            comp = TransposerInventorySimulator(
                component_type=component_type,
                address=address,
                slot=slot,
                host=self.host,
                variant=variant,
                registry=self.registry,
                bus=self,
                grid=self.inventory_grid,
            )
        elif component_type == "database":
            comp = DatabaseSimulator(
                component_type="database",
                address=address,
                slot=slot,
                host=self.host,
                variant=variant,
                registry=self.registry,
                bus=self,
            )
        elif component_type == "redstone":
            comp = RedstoneSimulator(
                component_type="redstone",
                address=address,
                slot=slot,
                host=self.host,
                variant=variant,
                registry=self.registry,
                bus=self,
            )
        elif component_type == "gpu" and self.sandbox is not None and self.sandbox.gpu_screen is not None:
            from ..screen.gpu_buffer import GPUComponent

            comp = GPUComponent(
                emulator=self.sandbox.gpu_screen,
                address=address,
                slot=slot,
                host=self.host,
                registry=self.registry,
                bus=self,
            )
        elif component_type == "gpu":
            from ..screen.gpu_buffer import GPUComponent, GPUScreenEmulator

            comp = GPUComponent(
                emulator=GPUScreenEmulator(),
                address=address,
                slot=slot,
                host=self.host,
                registry=self.registry,
                bus=self,
            )
        elif component_type == "screen" and self.sandbox is not None and self.sandbox.gpu_screen is not None:
            from ..screen.gpu_buffer import ScreenComponent

            comp = ScreenComponent(
                emulator=self.sandbox.gpu_screen,
                address=address,
                slot=slot,
                host=self.host,
                registry=self.registry,
                bus=self,
            )
        elif component_type == "screen":
            from ..screen.gpu_buffer import GPUScreenEmulator, ScreenComponent

            comp = ScreenComponent(
                emulator=GPUScreenEmulator(),
                address=address,
                slot=slot,
                host=self.host,
                registry=self.registry,
                bus=self,
            )
        elif component_type in OC_VANILLA_COMPONENT_CLASSES:
            oc_cls = OC_VANILLA_COMPONENT_CLASSES[component_type]
            if component_type == "filesystem" and "vfs" not in kwargs:
                default_vfs = self.vfs or (
                    getattr(self.sandbox, "vfs", None) if self.sandbox is not None else None
                )
                if default_vfs is not None:
                    kwargs = dict(kwargs, vfs=default_vfs)
            comp = oc_cls(
                component_type=component_type,
                address=address,
                slot=slot,
                host=self.host,
                variant=variant,
                registry=self.registry,
                bus=self,
                **kwargs,
            )
        else:
            comp = SchemaBackedComponent(
                component_type=component_type,
                address=address,
                slot=slot,
                host=self.host,
                variant=variant,
                registry=self.registry,
                bus=self,
            )

        self.components[comp.address] = comp
        ctype = comp.component_type
        if primary is True or ctype not in self.primaries:
            self.primaries[ctype] = comp.address
        if self.scheduler is not None:
            self.scheduler.push_signal("component_added", comp.address, ctype)
        return comp

    def detach(self, address: str) -> bool:
        comp = self.components.pop(address, None)
        if comp is None:
            return False
        ctype = comp.component_type
        if self.primaries.get(ctype) == address:
            self.primaries.pop(ctype, None)
            for addr, other in self.components.items():
                if other.component_type == ctype:
                    self.primaries[ctype] = addr
                    break
        if self.scheduler is not None:
            self.scheduler.push_signal("component_removed", address, ctype)
        return True

    def get_component(self, address_or_prefix: str, component_type: Optional[str] = None) -> Optional[SchemaBackedComponent]:
        if address_or_prefix in self.components:
            comp = self.components[address_or_prefix]
            if component_type is None or comp.component_type == component_type:
                return comp
        for addr, comp in self.components.items():
            if addr.startswith(str(address_or_prefix)):
                if component_type is None or comp.component_type == component_type:
                    return comp
        return None

    def get_primary_component(self, component_type: str) -> Optional[SchemaBackedComponent]:
        addr = self.primaries.get(component_type)
        if addr and addr in self.components:
            return self.components[addr]
        for comp in self.components.values():
            if comp.component_type == component_type:
                self.primaries[component_type] = comp.address
                return comp
        return None

    def list_matching(self, filter_str: Optional[str] = None, exact: Optional[bool] = None) -> Dict[str, str]:
        if filter_str is None or filter_str == "":
            return {addr: c.component_type for addr, c in self.components.items()}
        is_exact = bool(exact) if exact is not None else False
        out: Dict[str, str] = {}
        for addr, c in self.components.items():
            if is_exact:
                if c.component_type == filter_str:
                    out[addr] = c.component_type
            else:
                if filter_str in c.component_type:
                    out[addr] = c.component_type
        return out

    def validate_simulator_dumps(
        self,
        component_types: Optional[Tuple[str, ...]] = None,
        hosts: Tuple[str, ...] = ("computer", "robot", "tablet"),
        require_explicit_impl: bool = False,
    ) -> Dict[str, Any]:
        """Validate simulator components against GTNH 2.9 dump method names and docstrings."""
        from ..specs.registry import (
            DEFAULT_VALIDATED_SIMULATOR_TYPES,
            validate_simulator_dumps as _validate_dumps,
        )

        return _validate_dumps(
            registry=self.registry,
            component_types=component_types or DEFAULT_VALIDATED_SIMULATOR_TYPES,
            hosts=hosts,
            require_explicit_impl=require_explicit_impl,
        )

    def build_lua_component_library(self, sandbox: Any) -> Any:
        """Create the Lua `component` library table and bind it into `sandbox`."""
        self.sandbox = sandbox
        proxy_cache: Dict[str, Any] = {}

        def _invoke_packed(address: str, method: str, *args: Any) -> Any:
            comp = self.get_component(str(address))
            if comp is None:
                raise RuntimeError(f"no such component: {address}")
            self.consume_call_budget(comp.address, str(method), advance_tick_on_exhaustion=True)
            res = comp.invoke(str(method), *args)
            if isinstance(res, tuple):
                return sandbox.python_to_lua([True, *[sandbox.python_to_lua(x) for x in res]])
            return sandbox.python_to_lua([True, sandbox.python_to_lua(res)])

        def _make_proxy(address: str) -> Any:
            comp = self.get_component(str(address))
            if comp is None:
                return None
            if comp.address in proxy_cache:
                return proxy_cache[comp.address]

            method_names = sandbox.python_to_lua(sorted(comp.get_exposed_methods()))
            extra_fields = sandbox.python_to_lua(comp.extra_fields)
            proxy_builder = sandbox.lua.eval(
                r"""
                function(addr, ctype, cslot, methods_list, extra_tbl, invoke_fn)
                  local p = {
                    address = addr,
                    type = ctype,
                    slot = cslot,
                  }
                  for k, v in pairs(extra_tbl or {}) do
                    p[k] = v
                  end
                  for _, mname in ipairs(methods_list) do
                    local fn_table = {}
                    setmetatable(fn_table, {
                      __call = function(_, ...)
                        local first = select(1, ...)
                        local packed
                        if first == p then
                          packed = invoke_fn(addr, mname, select(2, ...))
                        else
                          packed = invoke_fn(addr, mname, ...)
                        end
                        return table.unpack(packed, 2, packed.n or #packed)
                      end,
                      __tostring = function()
                        return __oc_comp_bridge.doc(addr, mname) or ("function()")
                      end
                    })
                    p[mname] = fn_table
                  end
                  return p
                end
                """
            )
            proxy = proxy_builder(
                comp.address,
                comp.component_type,
                comp.slot,
                method_names,
                extra_fields,
                _invoke_packed,
            )
            proxy_cache[comp.address] = proxy
            return proxy

        class _CompBridge:
            def list_entries(self_, filter_str: Optional[str] = None, exact: Optional[bool] = None) -> Any:
                matches = self.list_matching(
                    str(filter_str) if filter_str is not None else None,
                    bool(exact) if exact is not None else (filter_str is not None and exact is None and False),
                )
                return sandbox.python_to_lua(matches)

            def proxy(self_, address: str) -> Any:
                return _make_proxy(str(address))

            def invoke(self_, address: str, method: str, *args: Any) -> Any:
                return _invoke_packed(str(address), str(method), *args)

            def doc(self_, address: str, method: str) -> Optional[str]:
                comp = self.get_component(str(address))
                if comp is None:
                    return None
                return comp.get_doc(str(method))

            def methods(self_, address: str) -> Any:
                comp = self.get_component(str(address))
                if comp is None:
                    return None
                return sandbox.python_to_lua(
                    {m: self.get_method_info(comp.address, m)["direct"] for m in comp.get_exposed_methods()}
                )

            def ctype(self_, address: str) -> Optional[str]:
                comp = self.get_component(str(address))
                return comp.component_type if comp else None

            def slot(self_, address: str) -> Optional[int]:
                comp = self.get_component(str(address))
                return comp.slot if comp else None

            def get_addr(self_, prefix: str, ctype: Optional[str] = None) -> Optional[str]:
                comp = self.get_component(str(prefix), str(ctype) if ctype else None)
                return comp.address if comp else None

            def is_available(self_, ctype: str) -> bool:
                return self.get_primary_component(str(ctype)) is not None

            def get_primary(self_, ctype: str) -> Any:
                comp = self.get_primary_component(str(ctype))
                if comp is None:
                    raise RuntimeError(f"no primary '{ctype}' available")
                return _make_proxy(comp.address)

            def set_primary(self_, ctype: str, address: str) -> bool:
                comp = self.get_component(str(address), str(ctype))
                if comp is not None:
                    self.primaries[str(ctype)] = comp.address
                    return True
                return False

        sandbox.lua.globals()["__oc_comp_bridge"] = _CompBridge()
        comp_lib = sandbox.lua.eval(
            r"""
            (function()
              local comp = {}
              function comp.list(filter, exact)
                if filter ~= nil and exact == nil then
                  exact = false
                end
                local tbl = __oc_comp_bridge.list_entries(filter, exact)
                local keys = {}
                for k in pairs(tbl) do
                  table.insert(keys, k)
                end
                table.sort(keys)
                local idx = 0
                return setmetatable(tbl, {
                  __call = function()
                    idx = idx + 1
                    local k = keys[idx]
                    if k ~= nil then
                      return k, tbl[k]
                    end
                    return nil
                  end
                })
              end
              function comp.proxy(address)
                checkArg(1, address, "string")
                local p = __oc_comp_bridge.proxy(address)
                if not p then return nil, "no such component" end
                return p
              end
              function comp.invoke(address, method, ...)
                checkArg(1, address, "string")
                checkArg(2, method, "string")
                local packed = __oc_comp_bridge.invoke(address, method, ...)
                return table.unpack(packed, 2, packed.n or #packed)
              end
              function comp.doc(address, method)
                checkArg(1, address, "string")
                checkArg(2, method, "string")
                return __oc_comp_bridge.doc(address, method)
              end
              function comp.methods(address)
                checkArg(1, address, "string")
                return __oc_comp_bridge.methods(address)
              end
              function comp.type(address)
                checkArg(1, address, "string")
                return __oc_comp_bridge.ctype(address)
              end
              function comp.slot(address)
                checkArg(1, address, "string")
                return __oc_comp_bridge.slot(address)
              end
              function comp.get(address, componentType)
                checkArg(1, address, "string")
                checkArg(2, componentType, "string", "nil")
                local full = __oc_comp_bridge.get_addr(address, componentType)
                if not full then return nil, "no such component" end
                return full
              end
              function comp.isAvailable(componentType)
                checkArg(1, componentType, "string")
                return __oc_comp_bridge.is_available(componentType)
              end
              function comp.getPrimary(componentType)
                checkArg(1, componentType, "string")
                return __oc_comp_bridge.get_primary(componentType)
              end
              function comp.setPrimary(componentType, address)
                checkArg(1, componentType, "string")
                checkArg(2, address, "string")
                return __oc_comp_bridge.set_primary(componentType, address)
              end
              setmetatable(comp, {
                __index = function(_, key)
                  if type(key) == "string" then
                    return comp.getPrimary(key)
                  end
                  return nil
                end
              })
              return comp
            end)()
            """
        )
        sandbox.bind_component_library(comp_lib)
        return comp_lib

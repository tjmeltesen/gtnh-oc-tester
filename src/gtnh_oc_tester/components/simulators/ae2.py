"""High-fidelity stateful simulator for Applied Energistics 2 (AE2) & AE2 Fluid Craft (AE2FC)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..auto_mock import ComponentCallRecord, SchemaBackedComponent


def _lua_to_py(value: Any, bus: Optional[Any] = None) -> Any:
    """Recursively convert any Lupa Lua table (Lua 5.2/5.3/5.4) into Python lists or dicts."""
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, (list, tuple)):
        return [_lua_to_py(v, bus) for v in value]
    if isinstance(value, dict):
        return {_lua_to_py(k, bus): _lua_to_py(v, bus) for k, v in value.items()}
    if hasattr(value, "items") and callable(getattr(value, "items", None)):
        try:
            items = list(value.items())
            if not items:
                return {}
            keys = [k for k, _ in items if k != "n"]
            if keys and all(isinstance(k, int) for k in keys):
                sorted_keys = sorted(keys)
                if sorted_keys == list(range(1, len(sorted_keys) + 1)):
                    return [_lua_to_py(value[k], bus) for k in sorted_keys]
            return {
                _lua_to_py(k, bus): _lua_to_py(v, bus)
                for k, v in items
            }
        except Exception:
            pass
    if bus and getattr(bus, "sandbox", None):
        return bus.sandbox.lua_to_python(value)
    return value


@dataclass
class AECraftingJobState:
    job_id: int
    item_or_fluid: Dict[str, Any]
    amount: int
    cpu_name: str
    prioritize_power: bool
    start_tick: int
    duration_ticks: int = 4
    canceled: bool = False
    failed: bool = False
    completed: bool = False
    network: Optional["MENetworkState"] = None

    def is_computing(self) -> bool:
        if self.canceled or self.failed or self.completed:
            return False
        if self.network and self.network.bus and self.network.bus.scheduler:
            return self.network.bus.scheduler.current_tick < self.start_tick + 1
        return False

    def has_failed(self) -> bool:
        return self.failed

    def is_canceled(self) -> bool:
        return self.canceled

    def is_done(self) -> bool:
        done = False
        if self.canceled or self.failed:
            done = False
        elif self.completed:
            done = True
        elif self.network and self.network.bus and self.network.bus.scheduler:
            if self.network.bus.scheduler.current_tick >= self.start_tick + self.duration_ticks:
                self.network._complete_job(self)
                done = True
        if self.network and self.network.bus is not None:
            rec = ComponentCallRecord(
                tick=self.network.bus.scheduler.current_tick if self.network.bus.scheduler else 0,
                address="userdata:ae_crafting_job",
                component_type="AECraftingJob",
                method="isDone",
                args=(),
                result=done,
                state_mutation="job completed" if done else None,
            )
            self.network.bus.call_log.append(rec)
            for listener in self.network.bus.call_listeners:
                listener(rec)
        return done

    def cancel(self) -> bool:
        if not self.completed:
            self.canceled = True
            if self.network is not None:
                for cpu in self.network.cpus:
                    if cpu.get("name") == self.cpu_name:
                        cpu["busy"] = False
            return True
        return False

    def __oc_lua_proxy__(self, sandbox: Any) -> Any:
        factory = sandbox.lua.eval(
            """
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
        )
        return factory(self)


class AECpuProxy:
    """Stateful GTNH 2.9 AE2 crafting CPU userdata (`getCpus()[i].cpu`)."""

    def __init__(self, network: "MENetworkState", cpu_dict: Dict[str, Any]) -> None:
        self.network = network
        self.cpu_dict = cpu_dict

    def _active_job(self) -> Optional[AECraftingJobState]:
        cname = self.cpu_dict.get("name", "")
        for job in reversed(self.network.active_jobs):
            if (
                job.cpu_name == cname
                and not job.completed
                and not job.canceled
                and not job.failed
            ):
                return job
        return None

    def is_busy(self) -> bool:
        if self._active_job() is not None:
            return True
        return bool(self.cpu_dict.get("busy", False))

    def is_active(self) -> bool:
        return self.is_busy() or bool(self.cpu_dict.get("active", True))

    def get_storage(self) -> int:
        return int(self.cpu_dict.get("storage", 65536))

    def get_coprocessors(self) -> int:
        return int(self.cpu_dict.get("coprocessors", 0))

    def cancel(self) -> bool:
        job = self._active_job()
        self.cpu_dict["busy"] = False
        if job is not None:
            return job.cancel()
        return True

    def final_output(self, sandbox: Any = None) -> Any:
        job = self._active_job()
        if job is None:
            return None
        out = dict(job.item_or_fluid)
        out["size"] = int(job.amount)
        target_sb = sandbox or (self.network.bus.sandbox if self.network.bus else None)
        return target_sb.python_to_lua(out) if target_sb else out

    def active_items(self, sandbox: Any = None) -> Any:
        job = self._active_job()
        items: List[Dict[str, Any]] = []
        if job is not None:
            out = dict(job.item_or_fluid)
            out["size"] = int(job.amount)
            items.append(out)
        target_sb = sandbox or (self.network.bus.sandbox if self.network.bus else None)
        return target_sb.python_to_lua(items) if target_sb else items

    def pending_items(self, sandbox: Any = None) -> Any:
        job = self._active_job()
        items: List[Dict[str, Any]] = []
        if job is not None:
            for rec in self.network.craftables:
                if rec.output.get("name") == job.item_or_fluid.get("name"):
                    for inp in rec.inputs:
                        entry = dict(inp)
                        entry["size"] = int(entry.get("size", 1)) * int(job.amount)
                        items.append(entry)
                    break
        target_sb = sandbox or (self.network.bus.sandbox if self.network.bus else None)
        return target_sb.python_to_lua(items) if target_sb else items

    def stored_items(self, sandbox: Any = None) -> Any:
        stored = list(self.cpu_dict.get("stored_items", []))
        target_sb = sandbox or (self.network.bus.sandbox if self.network.bus else None)
        return target_sb.python_to_lua(stored) if target_sb else stored

    def __oc_lua_proxy__(self, sandbox: Any) -> Any:
        factory = sandbox.lua.eval(
            """
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
              function cpu. getCoprocessors() return py_cpu.get_coprocessors() end
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
            """.replace("cpu. getCoprocessors", "cpu.getCoprocessors")
        )
        return factory(
            self,
            str(self.cpu_dict.get("name", "")),
            int(self.cpu_dict.get("storage", 65536)),
            int(self.cpu_dict.get("coprocessors", 0)),
            sandbox,
        )


@dataclass
class AECraftableRecipe:
    output: Dict[str, Any]
    recipe_type: str = "item"  # "item" or "fluid"
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    duration_ticks: int = 2
    will_fail: bool = False
    network: Optional["MENetworkState"] = None

    def get_item_stack(self) -> Dict[str, Any]:
        stack = dict(self.output)
        stack.setdefault("isCraftable", True)
        return stack

    def request(
        self,
        amount: int = 1,
        prioritize_power: bool = True,
        cpu_name: str = "",
    ) -> AECraftingJobState:
        assert self.network is not None
        return self.network.spawn_crafting_job(
            recipe=self,
            amount=int(amount) if amount is not None else 1,
            prioritize_power=bool(prioritize_power) if prioritize_power is not None else True,
            cpu_name=str(cpu_name or ""),
        )

    def __oc_lua_proxy__(self, sandbox: Any) -> Any:
        factory = sandbox.lua.eval(
            """
            function(py_craftable, stack_tbl, sb)
              local c = { type = "userdata" }
              function c.getItemStack() return stack_tbl end
              function c.request(amount, prioritizePower, cpuName)
                return py_craftable.request_from_lua(amount or 1, prioritizePower, cpuName or "", sb)
              end
              return c
            end
            """
        )
        return factory(self, sandbox.python_to_lua(self.get_item_stack()), sandbox)

    def request_from_lua(
        self,
        amount: int = 1,
        prioritize_power: Optional[bool] = True,
        cpu_name: str = "",
        sandbox: Any = None,
    ) -> Any:
        job = self.request(amount, bool(prioritize_power), str(cpu_name or ""))
        target_sb = sandbox or (
            self.network.bus.sandbox if (self.network and self.network.bus) else None
        )
        if target_sb is not None:
            return job.__oc_lua_proxy__(target_sb)
        return job


class MENetworkState:
    """Shared Applied Energistics 2 + AE2FC + Thaumic Energistics network state."""

    def __init__(self, bus: Optional[Any] = None) -> None:
        self.bus = bus
        self.items: List[Dict[str, Any]] = []
        self.fluids: List[Dict[str, Any]] = []
        self.essentia: List[Dict[str, Any]] = []
        self.craftables: List[AECraftableRecipe] = []
        self.cpus: List[Dict[str, Any]] = [
            {"name": "CPU-1", "storage": 65536, "coprocessors": 4, "busy": False},
            {"name": "CPU-2", "storage": 262144, "coprocessors": 16, "busy": False},
        ]
        self.active_jobs: List[AECraftingJobState] = []
        self._next_job_id = 1

        self.avg_power_injection = 2048.0
        self.avg_power_usage = 512.0
        self.idle_power_usage = 64.0
        self.stored_power = 1600000.0
        self.max_stored_power = 1600000.0

        self.item_event_sub = False
        self.fluid_event_sub = False
        self.essentia_event_sub = False

        self.interface_configs: Dict[int, Optional[Dict[str, Any]]] = {}
        self.fluid_interface_configs: Dict[Tuple[Optional[int], int], Optional[Dict[str, Any]]] = {}
        self.patterns: Dict[int, Dict[str, Any]] = {}

    def add_item(
        self,
        name: str,
        size: int = 1,
        label: Optional[str] = None,
        damage: int = 0,
        max_size: int = 64,
        is_craftable: bool = False,
        nbt: Optional[str] = None,
        item_id: int = 1,
    ) -> Dict[str, Any]:
        for existing in self.items:
            if existing.get("name") == name and existing.get("damage", 0) == damage:
                old_size = existing["size"]
                existing["size"] = max(0, old_size + int(size))
                if is_craftable:
                    existing["isCraftable"] = True
                self._notify_item_changed(existing, old_size, existing["size"])
                return existing
        entry = {
            "name": name,
            "label": label or name.split(":")[-1].replace("_", " ").title(),
            "size": int(size),
            "maxSize": int(max_size),
            "damage": int(damage),
            "maxDamage": 0,
            "hasTag": bool(nbt),
            "isCraftable": bool(is_craftable),
            "id": int(item_id),
        }
        if nbt:
            entry["nbt"] = nbt
        self.items.append(entry)
        self._notify_item_changed(entry, 0, entry["size"])
        return entry

    def set_item_count(self, name: str, size: int, damage: int = 0) -> Dict[str, Any]:
        for existing in self.items:
            if existing.get("name") == name and existing.get("damage", 0) == damage:
                old = existing["size"]
                existing["size"] = int(size)
                self._notify_item_changed(existing, old, existing["size"])
                return existing
        return self.add_item(name=name, size=size, damage=damage)

    def add_fluid(
        self,
        name: str,
        amount: int = 1000,
        label: Optional[str] = None,
        is_craftable: bool = False,
    ) -> Dict[str, Any]:
        for existing in self.fluids:
            if existing.get("name") == name:
                old_amt = existing["amount"]
                existing["amount"] = max(0, old_amt + int(amount))
                if is_craftable:
                    existing["isCraftable"] = True
                self._notify_fluid_changed(existing, old_amt, existing["amount"])
                return existing
        entry = {
            "name": name,
            "label": label or name.replace("_", " ").title(),
            "amount": int(amount),
            "hasTag": False,
            "isCraftable": bool(is_craftable),
        }
        self.fluids.append(entry)
        self._notify_fluid_changed(entry, 0, entry["amount"])
        return entry

    def set_fluid_amount(self, name: str, amount: int, label: Optional[str] = None) -> Dict[str, Any]:
        for existing in self.fluids:
            if existing.get("name") == name:
                old = existing["amount"]
                existing["amount"] = int(amount)
                self._notify_fluid_changed(existing, old, existing["amount"])
                return existing
        return self.add_fluid(name=name, amount=amount, label=label)

    def add_essentia(self, aspect: str, amount: int = 64, label: Optional[str] = None) -> Dict[str, Any]:
        for existing in self.essentia:
            if existing.get("aspect") == aspect or existing.get("name") == aspect:
                old = existing["amount"]
                existing["amount"] = max(0, old + int(amount))
                self._notify_essentia_changed(existing, old, existing["amount"])
                return existing
        entry = {
            "name": f"gaseous{aspect}essentia",
            "label": label or f"{aspect.title()} Essentia",
            "aspect": aspect.lower(),
            "amount": int(amount),
            "isCraftable": False,
        }
        self.essentia.append(entry)
        self._notify_essentia_changed(entry, 0, entry["amount"])
        return entry

    def add_craftable(
        self,
        name: str,
        label: Optional[str] = None,
        damage: int = 0,
        recipe_type: str = "item",
        duration_ticks: int = 2,
        will_fail: bool = False,
        inputs: Optional[List[Dict[str, Any]]] = None,
    ) -> AECraftableRecipe:
        output = {
            "name": name,
            "label": label or name.split(":")[-1].replace("_", " ").title(),
            "damage": int(damage),
            "size": 1,
            "maxSize": 64,
            "hasTag": False,
            "isCraftable": True,
        }
        recipe = AECraftableRecipe(
            output=output,
            recipe_type=recipe_type,
            inputs=inputs or [],
            duration_ticks=duration_ticks,
            will_fail=will_fail,
            network=self,
        )
        self.craftables.append(recipe)
        # Ensure item or fluid is marked craftable in network
        if recipe_type == "fluid":
            self.add_fluid(name=name, amount=0, label=output["label"], is_craftable=True)
        else:
            self.add_item(name=name, size=0, label=output["label"], damage=damage, is_craftable=True)
        return recipe

    def spawn_crafting_job(
        self,
        recipe: AECraftableRecipe,
        amount: int,
        prioritize_power: bool = True,
        cpu_name: str = "",
    ) -> AECraftingJobState:
        tick = self.bus.scheduler.current_tick if self.bus and self.bus.scheduler else 0
        chosen_cpu = cpu_name
        if not chosen_cpu:
            for cpu in self.cpus:
                if not cpu.get("busy"):
                    chosen_cpu = cpu["name"]
                    cpu["busy"] = True
                    break
            else:
                chosen_cpu = self.cpus[0]["name"] if self.cpus else "CPU-1"
        else:
            for cpu in self.cpus:
                if cpu["name"] == chosen_cpu:
                    cpu["busy"] = True

        job = AECraftingJobState(
            job_id=self._next_job_id,
            item_or_fluid=dict(recipe.output),
            amount=int(amount),
            cpu_name=chosen_cpu,
            prioritize_power=prioritize_power,
            start_tick=tick,
            duration_ticks=max(0, int(recipe.duration_ticks)),
            failed=recipe.will_fail,
            completed=(recipe.duration_ticks <= 0 and not recipe.will_fail),
            network=self,
        )
        self._next_job_id += 1
        self.active_jobs.append(job)

        if self.bus is not None:
            self.bus.record_call(
                ComponentCallRecord(
                    tick=tick,
                    address="ae2_craftable",
                    component_type="AECraftable",
                    method="request",
                    args=(amount, prioritize_power, chosen_cpu),
                    result=f"AECraftingJob#{job.job_id}({recipe.output['name']} x{amount})",
                    state_mutation=f"AECraftable.request({recipe.output['name']} x{amount} on {chosen_cpu})",
                )
            )

        if job.completed:
            self._complete_job(job)
        return job

    def _complete_job(self, job: AECraftingJobState) -> None:
        if job.canceled or job.failed:
            return
        if not job.completed:
            job.completed = True
        if getattr(job, "_reward_applied", False):
            return
        setattr(job, "_reward_applied", True)

        for cpu in self.cpus:
            if cpu["name"] == job.cpu_name:
                cpu["busy"] = False

        name = job.item_or_fluid.get("name", "")
        # Update fluid or item in network
        is_fluid = any(f.get("name") == name for f in self.fluids) and not any(
            i.get("name") == name for i in self.items if i.get("size", 0) > 0
        )
        if is_fluid:
            self.add_fluid(name=name, amount=job.amount, label=job.item_or_fluid.get("label"), is_craftable=True)
        else:
            self.add_item(
                name=name,
                size=job.amount,
                label=job.item_or_fluid.get("label"),
                damage=job.item_or_fluid.get("damage", 0),
                is_craftable=True,
            )

    def on_tick(self, current_tick: int) -> None:
        for job in list(self.active_jobs):
            if not job.completed and not job.canceled and not job.failed:
                if current_tick >= job.start_tick + job.duration_ticks:
                    self._complete_job(job)

    def _notify_item_changed(self, item: Dict[str, Any], old_size: int, new_size: int) -> None:
        if self.item_event_sub and self.bus and self.bus.scheduler and old_size != new_size:
            self.bus.scheduler.push_signal(
                "network_item_changed",
                dict(item),
                int(new_size - old_size),
            )

    def _notify_fluid_changed(self, fluid: Dict[str, Any], old_amt: int, new_amt: int) -> None:
        if self.fluid_event_sub and self.bus and self.bus.scheduler and old_amt != new_amt:
            self.bus.scheduler.push_signal(
                "network_fluid_changed",
                dict(fluid),
                int(new_amt - old_amt),
            )

    def _notify_essentia_changed(self, ess: Dict[str, Any], old_amt: int, new_amt: int) -> None:
        if self.essentia_event_sub and self.bus and self.bus.scheduler and old_amt != new_amt:
            self.bus.scheduler.push_signal(
                "network_essentia_changed",
                dict(ess),
                int(new_amt - old_amt),
            )


def _match_filter(entry: Dict[str, Any], flt: Optional[Dict[str, Any]]) -> bool:
    if not flt:
        return True
    for k, v in flt.items():
        if k == "n":
            continue
        if entry.get(k) != v:
            return False
    return True


class AE2NetworkComponent(SchemaBackedComponent):
    """Stateful component implementing CommonNetworkAPI, EssentiaNetworkAPI, MEInterfaceAPI, and AE2FC extensions."""

    def __init__(
        self,
        component_type: str = "me_interface",
        address: Optional[str] = None,
        slot: int = -1,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
        network: Optional[MENetworkState] = None,
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
        self.network: MENetworkState = network or (
            bus.me_network if bus is not None else MENetworkState()
        )
        self.maintainer_slots: Dict[int, Dict[str, Any]] = {}

    # CommonNetworkAPI
    def _impl_allItems(self) -> Any:
        items_snapshot = [dict(i) for i in self.network.items]
        if self.bus and self.bus.sandbox:
            sb = self.bus.sandbox
            lua_tbl = sb.python_to_lua(items_snapshot)
            return sb.lua.eval(
                """
                function(items)
                  local idx = 0
                  return function()
                    idx = idx + 1
                    return items[idx]
                  end
                end
                """
            )(lua_tbl)
        idx = 0

        def _py_iter() -> Optional[Dict[str, Any]]:
            nonlocal idx
            if idx < len(items_snapshot):
                val = items_snapshot[idx]
                idx += 1
                return val
            return None

        return _py_iter

    def _impl_getItemsInNetwork(self, filter_tbl: Optional[Any] = None) -> List[Dict[str, Any]]:
        flt = _lua_to_py(filter_tbl, self.bus) if filter_tbl is not None else None
        if not isinstance(flt, dict):
            flt = None
        return [dict(item) for item in self.network.items if _match_filter(item, flt)]

    def _impl_getItemsInNetworkById(self, ids_tbl: Any) -> List[Dict[str, Any]]:
        ids = _lua_to_py(ids_tbl, self.bus)
        id_set = set(ids.values() if isinstance(ids, dict) else (ids or []))
        return [dict(item) for item in self.network.items if item.get("id") in id_set]

    def _impl_getItemInNetwork(self, name_or_detail: Any, damage: Optional[int] = None, nbt: Optional[str] = None) -> Optional[Dict[str, Any]]:
        arg = _lua_to_py(name_or_detail, self.bus)
        if isinstance(arg, dict):
            for item in self.network.items:
                if _match_filter(item, arg):
                    return dict(item)
            return None
        for item in self.network.items:
            if item.get("name") == arg or item.get("id") == arg:
                if damage is None or item.get("damage", 0) == int(damage):
                    return dict(item)
        return None

    def _impl_getFluidsInNetwork(self) -> List[Dict[str, Any]]:
        return [dict(f) for f in self.network.fluids]

    def _impl_getFluidInNetwork(self, name_or_detail: Optional[Any] = None) -> Any:
        if name_or_detail is None:
            return [dict(f) for f in self.network.fluids]
        arg = _lua_to_py(name_or_detail, self.bus)
        if isinstance(arg, dict):
            return [dict(f) for f in self.network.fluids if _match_filter(f, arg)]
        matches = [dict(f) for f in self.network.fluids if f.get("name") == str(arg) or f.get("label") == str(arg)]
        return matches

    def _impl_getEssentiaInNetwork(self, aspect_or_detail: Optional[Any] = None) -> List[Dict[str, Any]]:
        if aspect_or_detail is None:
            return [dict(e) for e in self.network.essentia]
        arg = _lua_to_py(aspect_or_detail, self.bus)
        if isinstance(arg, dict):
            return [dict(e) for e in self.network.essentia if _match_filter(e, arg)]
        return [
            dict(e)
            for e in self.network.essentia
            if e.get("aspect") == str(arg).lower() or e.get("name") == str(arg)
        ]

    def _impl_getCpus(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for c in self.network.cpus:
            cpu_proxy = AECpuProxy(self.network, c)
            is_busy = cpu_proxy.is_busy()
            c["busy"] = is_busy
            out.append(
                {
                    "name": c["name"],
                    "storage": c["storage"],
                    "coprocessors": c["coprocessors"],
                    "busy": is_busy,
                    "cpu": cpu_proxy,
                }
            )
        return out

    def _impl_getCraftables(self, filter_tbl: Optional[Any] = None) -> List[Any]:
        flt = _lua_to_py(filter_tbl, self.bus) if filter_tbl is not None else None
        if not isinstance(flt, dict):
            flt = None
        return [c for c in self.network.craftables if _match_filter(c.output, flt)]

    def _impl_getCraftable(self, detail: Optional[Any] = None, recipe_type: Optional[str] = None) -> Optional[Any]:
        flt = _lua_to_py(detail, self.bus) if detail is not None else None
        if isinstance(flt, str):
            flt = {"name": flt}
        elif not isinstance(flt, dict):
            flt = None
        for c in self.network.craftables:
            if recipe_type and c.recipe_type != recipe_type:
                continue
            if _match_filter(c.output, flt):
                return c
        return None

    def _impl_getAvgPowerInjection(self) -> float:
        return float(self.network.avg_power_injection)

    def _impl_getAvgPowerUsage(self) -> float:
        return float(self.network.avg_power_usage)

    def _impl_getIdlePowerUsage(self) -> float:
        return float(self.network.idle_power_usage)

    def _impl_getStoredPower(self) -> float:
        return float(self.network.stored_power)

    def _impl_getMaxStoredPower(self) -> float:
        return float(self.network.max_stored_power)

    def _impl_setItemEventSubscription(self, enabled: bool) -> None:
        self.network.item_event_sub = bool(enabled)

    def _impl_isItemEventSubscription(self) -> bool:
        return bool(self.network.item_event_sub)

    def _impl_setFluidEventSubscription(self, enabled: bool) -> None:
        self.network.fluid_event_sub = bool(enabled)

    def _impl_isFluidEventSubscription(self) -> bool:
        return bool(self.network.fluid_event_sub)

    def _impl_setEssentiaEventSubscription(self, enabled: bool) -> None:
        self.network.essentia_event_sub = bool(enabled)

    def _impl_isEssentiaEventSubscription(self) -> bool:
        return bool(self.network.essentia_event_sub)

    def _impl_store(
        self,
        filter_tbl: Any,
        db_address: str,
        start_slot: int = 1,
        count: Optional[int] = None,
    ) -> bool:
        items = self._impl_getItemsInNetwork(filter_tbl)
        if self.bus:
            db = self.bus.get_component(db_address)
            if db is not None and hasattr(db, "entries"):
                slot = int(start_slot or 1)
                limit = int(count) if count is not None else len(items)
                for item in items[:limit]:
                    db.entries[slot] = dict(item)
                    slot += 1
        return True

    # MEInterfaceAPI & FluidInterface & PatternEditor
    def _impl_getInterfaceConfiguration(self, slot: int = 1) -> Optional[Dict[str, Any]]:
        return self.network.interface_configs.get(int(slot or 1))

    def _impl_setInterfaceConfiguration(self, *args: Any) -> bool:
        if not args:
            self.network.interface_configs[1] = None
            return True
        if isinstance(args[0], int) and len(args) == 1:
            self.network.interface_configs[int(args[0])] = None
            return True
        if isinstance(args[0], str):
            slot, db_addr, db_idx = 1, args[0], int(args[1])
            size = int(args[2]) if len(args) > 2 and args[2] is not None else 1
        else:
            slot = int(args[0])
            db_addr = str(args[1])
            db_idx = int(args[2])
            size = int(args[3]) if len(args) > 3 and args[3] is not None else 1
        entry = {"name": "minecraft:stone", "size": size, "database": db_addr, "entry": db_idx}
        if self.bus:
            db = self.bus.get_component(db_addr)
            if db is not None and hasattr(db, "entries") and db_idx in db.entries:
                entry = dict(db.entries[db_idx])
                entry["size"] = size
        self.network.interface_configs[slot] = entry
        return True

    def _impl_getFluidInterfaceConfiguration(self, arg1: int = 1, arg2: Optional[int] = None) -> Optional[Dict[str, Any]]:
        key = (None, int(arg1)) if arg2 is None else (int(arg1), int(arg2))
        return self.network.fluid_interface_configs.get(key)

    def _impl_setFluidInterfaceConfiguration(self, arg1: int = 1, arg2: Optional[Any] = None, arg3: Optional[Any] = None) -> bool:
        if arg3 is not None or (isinstance(arg2, int) and arg3 is None):
            key = (int(arg1), int(arg2))
            detail = _lua_to_py(arg3, self.bus) if arg3 is not None else None
        else:
            key = (None, int(arg1))
            detail = _lua_to_py(arg2, self.bus) if arg2 is not None else None
        self.network.fluid_interface_configs[key] = dict(detail) if isinstance(detail, dict) else None
        return True

    def _impl_getInterfacePattern(self, slot: int = 1) -> Dict[str, Any]:
        return self.network.patterns.setdefault(
            int(slot or 1),
            {"inputs": {}, "outputs": {}},
        )

    def _impl_setInterfacePatternInput(self, slot: int, index: int, *args: Any) -> bool:
        pat = self._impl_getInterfacePattern(int(slot))
        pat["inputs"][int(index)] = _lua_to_py(args[0], self.bus) if args else args
        return True

    def _impl_setInterfacePatternOutput(self, slot: int, index: int, *args: Any) -> bool:
        pat = self._impl_getInterfacePattern(int(slot))
        pat["outputs"][int(index)] = _lua_to_py(args[0], self.bus) if args else args
        return True

    def _impl_clearInterfacePatternInput(self, slot: int, index: int) -> bool:
        pat = self._impl_getInterfacePattern(int(slot))
        pat["inputs"].pop(int(index), None)
        return True

    def _impl_clearInterfacePatternOutput(self, slot: int, index: int) -> bool:
        pat = self._impl_getInterfacePattern(int(slot))
        pat["outputs"].pop(int(index), None)
        return True

    def _impl_storeInterfacePatternInput(
        self, slot: int, index: int, db_address: str, entry: int
    ) -> bool:
        pat = self._impl_getInterfacePattern(int(slot))
        val = pat["inputs"].get(int(index))
        if self.bus and val is not None:
            db = self.bus.get_component(db_address)
            if db is not None and hasattr(db, "entries"):
                db.entries[int(entry)] = dict(val) if isinstance(val, dict) else {"name": str(val), "size": 1}
        return True

    def _impl_storeInterfacePatternOutput(
        self, slot: int, index: int, db_address: str, entry: int
    ) -> bool:
        pat = self._impl_getInterfacePattern(int(slot))
        val = pat["outputs"].get(int(index))
        if self.bus and val is not None:
            db = self.bus.get_component(db_address)
            if db is not None and hasattr(db, "entries"):
                db.entries[int(entry)] = dict(val) if isinstance(val, dict) else {"name": str(val), "size": 1}
        return True

    # Level Maintainer methods
    def _impl_setSlot(self, slot: int, *args: Any) -> bool:
        s = int(slot)
        cur = self.maintainer_slots.setdefault(
            s,
            {"name": "minecraft:iron_ingot", "quantity": 1000, "batch": 64, "isEnable": True, "isDone": True},
        )
        if len(args) >= 4:
            cur["dbAddress"] = str(args[0])
            cur["dbIndex"] = int(args[1])
            cur["quantity"] = int(args[2])
            cur["batch"] = int(args[3])
        elif len(args) >= 2:
            cur["quantity"] = int(args[0])
            cur["batch"] = int(args[1])
        return True

    def _impl_getSlot(self, slot: int) -> Optional[Dict[str, Any]]:
        return self.maintainer_slots.get(int(slot))

    def _impl_active(self) -> bool:
        return True

    def _impl_isDone(self, slot: int) -> bool:
        info = self.maintainer_slots.get(int(slot))
        return bool(info.get("isDone", True)) if info else True

    def _impl_isEnable(self, slot: int) -> bool:
        info = self.maintainer_slots.get(int(slot))
        return bool(info.get("isEnable", True)) if info else False

    def _impl_setEnable(self, slot: int, value: bool) -> bool:
        info = self.maintainer_slots.setdefault(
            int(slot),
            {"name": "minecraft:iron_ingot", "quantity": 1000, "batch": 64, "isEnable": True, "isDone": True},
        )
        info["isEnable"] = bool(value)
        return True

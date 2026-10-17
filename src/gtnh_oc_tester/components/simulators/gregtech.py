"""High-fidelity stateful simulator for GregTech machines, battery buffers, energy containers, and LSC."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..auto_mock import SchemaBackedComponent


class GTMachineSimulator(SchemaBackedComponent):
    """Emulates `gt_machine`, `gt_batterybuffer`, `gt_energycontainer`, and Bartworks `bec_*`."""

    def __init__(
        self,
        component_type: str = "gt_machine",
        address: Optional[str] = None,
        slot: int = -1,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
        machine_name: str = "gt.blockmachines.multimachine.chemicalreactor",
        stored_eu: int = 1000000,
        eu_capacity: int = 10000000,
        work_allowed: bool = True,
        has_work: bool = False,
        work_progress: int = 0,
        work_max_progress: int = 200,
        eu_input_avg: float = 2048.0,
        eu_output_avg: float = 0.0,
        passive_loss_per_tick: int = 0,
        recipe_eu_per_tick: int = 0,
        maintenance_problems: int = 0,
        efficiency: float = 100.0,
        wireless_mode: bool = False,
        wireless_eu: int = 0,
        simulate_eu_dynamics: bool = False,
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
        self.machine_name = machine_name
        self.owner_name = "Player"
        self.coordinates = (0, 64, 0)
        self.stored_eu = int(stored_eu)
        self.eu_capacity = int(eu_capacity)
        self.eu_input_avg = float(eu_input_avg)
        self.eu_output_avg = float(eu_output_avg)
        self.passive_loss_per_tick = int(passive_loss_per_tick)
        self.recipe_eu_per_tick = int(recipe_eu_per_tick)
        self.maintenance_problems = int(maintenance_problems)
        self.efficiency = float(efficiency)
        self.wireless_mode = bool(wireless_mode)
        self.wireless_eu = int(wireless_eu)
        self.simulate_eu_dynamics = bool(simulate_eu_dynamics)
        self.completed_recipes: int = 0
        self.input_voltage = 8192
        self.output_voltage = 0
        self.output_amperage = 1
        self.stored_steam = 0
        self.steam_capacity = 0

        self.work_allowed = bool(work_allowed)
        self.has_work = bool(has_work)
        self.work_progress = int(work_progress)
        self.work_max_progress = int(work_max_progress)
        self.circuit_config = -1

        self._custom_sensor_information: Optional[List[str]] = None
        self.parameters: Dict[Any, float] = {i: 0.0 for i in range(20)}
        self.battery_charges: Dict[int, Tuple[int, int]] = {
            1: (1000000, 1000000),
            2: (1000000, 1000000),
            3: (1000000, 1000000),
            4: (1000000, 1000000),
        }

    @property
    def is_lsc(self) -> bool:
        lower = self.machine_name.lower()
        return "supercapacitor" in lower or "lapotronic" in lower or "lsc" in lower

    @property
    def sensor_information(self) -> List[str]:
        if self._custom_sensor_information is not None:
            return list(self._custom_sensor_information)
        if self.is_lsc:
            return [
                "Operational Data:",
                f"EU Stored: {self.stored_eu:,} EU",
                f"EU Capacity: {self.eu_capacity:,} EU",
                f"Total Capacity: {self.eu_capacity:,} EU",
                f"Passive Loss: {self.passive_loss_per_tick:,} EU/t",
                f"EU In: {int(self.eu_input_avg):,} EU/t",
                f"EU Out: {int(self.eu_output_avg):,} EU/t",
                f"Avg EU In: {int(self.eu_input_avg):,} (last 5 seconds)",
                f"Avg EU Out: {int(self.eu_output_avg):,} (last 5 seconds)",
                f"Maintenance Status: {'Working Perfectly' if self.maintenance_problems == 0 else f'{self.maintenance_problems} Problems'}",
                f"Wireless Mode: {'Enabled' if self.wireless_mode else 'Disabled'}",
                f"Total Wireless EU: {self.wireless_eu:,} EU",
            ]
        return [
            f"Progress: {self.work_progress // 20} s / {self.work_max_progress // 20} s",
            f"Stored Energy: {self.stored_eu:,} EU / {self.eu_capacity:,} EU",
            f"Problems: §c{self.maintenance_problems}§r Efficiency: §a{self.efficiency:.2f}%§r",
            f"Probably uses: {self.recipe_eu_per_tick:,} EU/t",
            f"EU In: {int(self.eu_input_avg):,} EU/t | EU Out: {int(self.eu_output_avg):,} EU/t",
        ]

    @sensor_information.setter
    def sensor_information(self, value: Optional[List[str]]) -> None:
        self._custom_sensor_information = [str(x) for x in value] if value is not None else None

    def on_tick(self, current_tick: int) -> None:
        if self.is_lsc or self.simulate_eu_dynamics or self.passive_loss_per_tick > 0:
            net_delta = int(round(self.eu_input_avg - self.eu_output_avg)) - self.passive_loss_per_tick
            if self.work_allowed and self.has_work and self.recipe_eu_per_tick > 0:
                net_delta -= self.recipe_eu_per_tick
            self.stored_eu = max(0, min(self.eu_capacity, self.stored_eu + net_delta))
            if self.wireless_mode and net_delta > 0 and self.stored_eu >= self.eu_capacity:
                self.wireless_eu += net_delta

        if self.work_allowed and self.has_work and self.work_max_progress > 0:
            if self.recipe_eu_per_tick > 0 and self.stored_eu <= 0 and self.eu_input_avg < self.recipe_eu_per_tick:
                # Insufficient power to advance recipe progress
                return
            self.work_progress += 1
            if self.work_progress >= self.work_max_progress:
                self.work_progress = 0
                self.completed_recipes += 1

    # BaseGregTechEnergy
    def _impl_getAverageElectricInput(self) -> float:
        return float(self.eu_input_avg)

    def _impl_getAverageElectricOutput(self) -> float:
        return float(self.eu_output_avg)

    def _impl_getEUCapacity(self) -> int:
        return int(self.eu_capacity)

    def _impl_getEUCapacityString(self) -> str:
        return str(self.eu_capacity)

    def _impl_getInputVoltage(self) -> int:
        return int(self.input_voltage)

    def _impl_getOutputAmperage(self) -> int:
        return int(self.output_amperage)

    def _impl_getOutputVoltage(self) -> int:
        return int(self.output_voltage)

    def _impl_getSteamCapacity(self) -> int:
        return int(self.steam_capacity)

    def _impl_getStoredEU(self) -> int:
        return int(self.stored_eu)

    def _impl_getStoredEUString(self) -> str:
        return str(self.stored_eu)

    def _impl_getStoredSteam(self) -> int:
        return int(self.stored_steam)

    # BaseGregTechMachine
    def _impl_getCoordinates(self) -> Tuple[int, int, int]:
        return self.coordinates

    def _impl_getEUInputAverage(self) -> float:
        return float(self.eu_input_avg)

    def _impl_getEUMaxStored(self) -> int:
        return int(self.eu_capacity)

    def _impl_getEUOutputAverage(self) -> float:
        return float(self.eu_output_avg)

    def _impl_getEUStored(self) -> int:
        return int(self.stored_eu)

    def _impl_getName(self) -> str:
        return str(self.machine_name)

    def _impl_getOwnerName(self) -> str:
        return str(self.owner_name)

    def _impl_getParameters(self) -> Dict[Any, float]:
        return dict(self.parameters)

    def _impl_setParameter(self, key: Any, val: Any, val2: Optional[Any] = None) -> bool:
        if val2 is not None:
            # Hatch/parameter index pair (hatch, param, value)
            self.parameters[f"{int(key)}:{int(val)}"] = float(val2)
            self.parameters[int(key)] = float(val2)
        else:
            k = int(key) if isinstance(key, (int, float)) else str(key)
            self.parameters[k] = float(val)
        return True

    def _impl_getSensorInformation(self) -> List[str]:
        return list(self.sensor_information)

    def _impl_getSteamMaxStored(self) -> int:
        return int(self.steam_capacity)

    def _impl_getSteamStored(self) -> int:
        return int(self.stored_steam)

    def _impl_getWorkMaxProgress(self) -> int:
        return int(self.work_max_progress)

    def _impl_getWorkProgress(self) -> int:
        return int(self.work_progress)

    def _impl_hasWork(self) -> bool:
        return bool(self.has_work)

    def _impl_isMachineActive(self) -> bool:
        return bool(self.work_allowed and self.has_work)

    def _impl_isWorkAllowed(self) -> bool:
        return bool(self.work_allowed)

    def _impl_setWorkAllowed(self, work: bool) -> None:
        self.work_allowed = bool(work)

    # gt_machine specific
    def _impl_getCircuitConfiguration(self) -> int:
        return int(self.circuit_config)

    def _impl_setCircuitConfiguration(self, config: int) -> Tuple[bool, None]:
        self.circuit_config = int(config)
        return (True, None)

    # gt_batterybuffer specific
    def _impl_getBatteryCharge(self, slot: int) -> int:
        charge, _max_c = self.battery_charges.get(int(slot), (0, 0))
        return int(charge)

    def _impl_getMaxBatteryCharge(self, slot: int) -> int:
        _charge, max_c = self.battery_charges.get(int(slot), (0, 0))
        return int(max_c)

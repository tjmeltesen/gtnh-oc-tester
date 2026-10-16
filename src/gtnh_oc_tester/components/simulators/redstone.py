"""Stateful simulator for OpenComputers Redstone (vanilla, bundled, comparator, and wireless)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..auto_mock import SchemaBackedComponent
from .ae2 import _lua_to_py


class RedstoneSimulator(SchemaBackedComponent):
    """Emulates vanilla, bundled, comparator, and wireless redstone I/O."""

    def __init__(
        self,
        component_type: str = "redstone",
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
        self.inputs: Dict[int, int] = {s: 0 for s in range(6)}
        self.outputs: Dict[int, int] = {s: 0 for s in range(6)}
        self.bundled_inputs: Dict[int, Dict[int, int]] = {
            s: {c: 0 for c in range(16)} for s in range(6)
        }
        self.bundled_outputs: Dict[int, Dict[int, int]] = {
            s: {c: 0 for c in range(16)} for s in range(6)
        }
        self.comparator_inputs: Dict[int, int] = {s: 0 for s in range(6)}
        self.wireless_frequency: int = 0
        self.wireless_input: int = 0
        self.wireless_output: bool = False
        self.wake_threshold: int = 0

    def set_external_input(self, side: int, value: int, color: Optional[int] = None) -> None:
        """Set external redstone input from tests and fire `redstone_changed` event."""
        s = int(side)
        new_val = int(value)
        if color is not None:
            c = int(color)
            old_val = self.bundled_inputs[s].get(c, 0)
            self.bundled_inputs[s][c] = new_val
            if old_val != new_val and self.bus and self.bus.scheduler:
                self.bus.scheduler.push_signal(
                    "redstone_changed", self.address, s, old_val, new_val, c
                )
        else:
            old_val = self.inputs.get(s, 0)
            self.inputs[s] = new_val
            if old_val != new_val and self.bus and self.bus.scheduler:
                self.bus.scheduler.push_signal(
                    "redstone_changed", self.address, s, old_val, new_val
                )

    def _impl_getInput(self, side: Optional[int] = None) -> Any:
        if side is None:
            return dict(self.inputs)
        return int(self.inputs.get(int(side), 0))

    def _impl_getOutput(self, side: Optional[int] = None) -> Any:
        if side is None:
            return dict(self.outputs)
        return int(self.outputs.get(int(side), 0))

    def _impl_setOutput(self, side_or_table: Any, value: Optional[int] = None) -> Any:
        arg = _lua_to_py(side_or_table, self.bus) if value is None else side_or_table
        if isinstance(arg, dict):
            old_all = dict(self.outputs)
            for s, v in arg.items():
                if isinstance(s, int) and 0 <= s <= 5:
                    self.outputs[s] = int(v)
            return old_all
        s = int(arg)
        old_val = self.outputs.get(s, 0)
        self.outputs[s] = int(value or 0)
        return old_val

    def _impl_getBundledInput(
        self, side: Optional[int] = None, color: Optional[int] = None
    ) -> Any:
        if side is None:
            return {s: dict(cmap) for s, cmap in self.bundled_inputs.items()}
        s = int(side)
        if color is None:
            return dict(self.bundled_inputs.get(s, {}))
        return int(self.bundled_inputs.get(s, {}).get(int(color), 0))

    def _impl_getBundledOutput(
        self, side: Optional[int] = None, color: Optional[int] = None
    ) -> Any:
        if side is None:
            return {s: dict(cmap) for s, cmap in self.bundled_outputs.items()}
        s = int(side)
        if color is None:
            return dict(self.bundled_outputs.get(s, {}))
        return int(self.bundled_outputs.get(s, {}).get(int(color), 0))

    def _impl_setBundledOutput(
        self,
        side_or_table: Any,
        color_or_table: Optional[Any] = None,
        value: Optional[int] = None,
    ) -> Any:
        if value is not None:
            s = int(side_or_table)
            c = int(color_or_table)
            old_val = self.bundled_outputs[s].get(c, 0)
            self.bundled_outputs[s][c] = int(value)
            return old_val
        s_arg = _lua_to_py(side_or_table, self.bus)
        if isinstance(s_arg, dict):
            old_all = {s: dict(cmap) for s, cmap in self.bundled_outputs.items()}
            for s, cmap in s_arg.items():
                if isinstance(s, int) and isinstance(cmap, dict):
                    for c, v in cmap.items():
                        if isinstance(c, int):
                            self.bundled_outputs[s][c] = int(v)
            return old_all
        s = int(s_arg)
        c_arg = _lua_to_py(color_or_table, self.bus)
        old_side = dict(self.bundled_outputs.get(s, {}))
        if isinstance(c_arg, dict):
            for c, v in c_arg.items():
                if isinstance(c, int):
                    self.bundled_outputs[s][c] = int(v)
        return old_side

    def _impl_getComparatorInput(self, side: int) -> int:
        return int(self.comparator_inputs.get(int(side), 0))

    def _impl_getWirelessInput(self) -> int:
        return int(self.wireless_input)

    def _impl_getWirelessOutput(self) -> bool:
        return bool(self.wireless_output)

    def _impl_setWirelessOutput(self, value: bool) -> bool:
        old = self.wireless_output
        self.wireless_output = bool(value)
        return old

    def _impl_getWirelessFrequency(self) -> int:
        return int(self.wireless_frequency)

    def _impl_setWirelessFrequency(self, frequency: int) -> int:
        old = self.wireless_frequency
        self.wireless_frequency = int(frequency)
        return old

    def _impl_getWakeThreshold(self) -> int:
        return int(self.wake_threshold)

    def _impl_setWakeThreshold(self, threshold: int) -> int:
        old = self.wake_threshold
        self.wake_threshold = int(threshold)
        return old

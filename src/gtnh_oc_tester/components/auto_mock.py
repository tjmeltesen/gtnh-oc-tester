"""Schema-backed auto-mock component base for all 165 GTNH 2.9 components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import uuid

from ..specs.registry import ResolvedComponentSchema, SchemaRegistry, get_default_registry
from .abstracts import DriverAbstractMixin


@dataclass
class ComponentCallRecord:
    tick: int
    address: str
    component_type: str
    method: str
    args: Tuple[Any, ...]
    result: Any
    state_mutation: Optional[str] = None


class SchemaBackedComponent(DriverAbstractMixin):
    """Base emulated component backed by GTNH 2.9 dumps, LuaLS stubs, and driver abstracts."""

    def __init__(
        self,
        component_type: str,
        address: Optional[str] = None,
        slot: int = -1,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[SchemaRegistry] = None,
        bus: Optional[Any] = None,
    ) -> None:
        self.component_type = component_type
        self.address = address or str(uuid.uuid4())
        self.slot = int(slot)
        self.host = host
        self.variant = variant
        self.registry = registry or get_default_registry()
        self.bus = bus
        self.schema: ResolvedComponentSchema = self.registry.get_component_schema(
            component_type, host=host, variant=variant
        )
        self.state: Dict[str, Any] = {}
        self.init_abstract_state()
        self.mock_overrides: Dict[str, Any] = {}
        self.call_history: List[ComponentCallRecord] = []

        # Populate table fields exposed on proxy (e.g. sound.modes, sound.channel_count)
        self.extra_fields: Dict[str, Any] = {}
        for fname in self.schema.dump_fields:
            if fname == "modes":
                self.extra_fields[fname] = {"noise": 1, "square": 2, "sine": 3, "triangle": 4, "sawtooth": 5}
            elif fname == "channel_count":
                self.extra_fields[fname] = 8
            else:
                self.extra_fields[fname] = {}

    def mock_method(self, method_name: str, return_value_or_fn: Any) -> "SchemaBackedComponent":
        """Override or script a specific method's return value or callback."""
        self.mock_overrides[method_name] = return_value_or_fn
        return self

    def get_exposed_methods(self) -> Set[str]:
        names = set(self.schema.get_method_names())
        names.update(self.mock_overrides.keys())
        return names

    def get_doc(self, method_name: str) -> Optional[str]:
        return self.schema.get_doc(method_name)

    def invoke(self, method_name: str, *args: Any) -> Any:
        exposed = self.get_exposed_methods()
        if method_name not in exposed and not hasattr(self, method_name):
            raise AttributeError(
                f"Component '{self.component_type}' ({self.address}) on host '{self.host}' "
                f"has no method '{method_name}'"
            )

        mutation_note: Optional[str] = None
        if method_name in self.mock_overrides:
            override = self.mock_overrides[method_name]
            result = override(*args) if callable(override) else override
        elif hasattr(self, f"_impl_{method_name}"):
            result = getattr(self, f"_impl_{method_name}")(*args)
            mutation_note = self._describe_mutation(method_name, args, result)
        elif hasattr(self, method_name) and method_name in exposed:
            result = getattr(self, method_name)(*args)
            mutation_note = self._describe_mutation(method_name, args, result)
        else:
            result = self._default_return(method_name, args)

        tick = self.bus.scheduler.current_tick if self.bus and self.bus.scheduler else 0
        rec = ComponentCallRecord(
            tick=tick,
            address=self.address,
            component_type=self.component_type,
            method=method_name,
            args=args,
            result=result,
            state_mutation=mutation_note,
        )
        self.call_history.append(rec)
        if self.bus is not None:
            self.bus.record_call(rec)
        return result

    def _describe_mutation(self, method_name: str, args: Tuple[Any, ...], result: Any) -> Optional[str]:
        if method_name.startswith(("set", "clear", "transfer", "swap", "request", "store", "export", "import", "bind", "fill", "copy")):
            args_fmt = ", ".join(repr(a) for a in args[:3])
            return f"{self.component_type}.{method_name}({args_fmt})"
        return None

    def _default_return(self, method_name: str, args: Tuple[Any, ...]) -> Any:
        # Check stub overloads first
        if method_name in self.schema.methods:
            mspec = self.schema.methods[method_name]
            if mspec.overloads and mspec.overloads[0].returns:
                rets = [
                    self.registry.default_return_for_type(r.type_str)
                    for r in mspec.overloads[0].returns
                ]
                return rets[0] if len(rets) == 1 else tuple(rets)
        # Check dump overloads
        if method_name in self.schema.dump_methods:
            dspec = self.schema.dump_methods[method_name]
            if dspec.overloads and dspec.overloads[0].returns:
                rets = [
                    self.registry.default_return_for_type(r)
                    for r in dspec.overloads[0].returns
                ]
                return rets[0] if len(rets) == 1 else tuple(rets)
        return True

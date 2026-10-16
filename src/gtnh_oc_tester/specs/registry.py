"""Unified Schema Registry combining GTNH 2.9 proxy dumps and LuaLS type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .dump_parser import DumpMethodSpec, DumpSpec, load_all_dumps
from .stub_parser import (
    StubClassSpec,
    StubFieldSpec,
    StubMethodSpec,
    load_all_stubs,
)


@dataclass
class ResolvedComponentSchema:
    component_type: str
    host: str
    class_spec: Optional[StubClassSpec]
    parents_chain: List[str] = field(default_factory=list)
    methods: Dict[str, StubMethodSpec] = field(default_factory=dict)
    dump_methods: Dict[str, DumpMethodSpec] = field(default_factory=dict)
    fields: Dict[str, StubFieldSpec] = field(default_factory=dict)
    dump_fields: Dict[str, str] = field(default_factory=dict)

    def get_method_names(self, strict_host_dump: bool = False) -> Set[str]:
        if strict_host_dump and self.dump_methods:
            return set(self.dump_methods.keys())
        return set(self.methods.keys()) | set(self.dump_methods.keys())

    def get_doc(self, method_name: str) -> Optional[str]:
        if method_name in self.dump_methods:
            return self.dump_methods[method_name].raw_doc
        if method_name in self.methods:
            mspec = self.methods[method_name]
            if mspec.overloads:
                ov = mspec.overloads[0]
                args_str = ", ".join(
                    f"[{p.name}:{p.type_str}]" if p.optional else f"{p.name}:{p.type_str}"
                    for p in ov.params
                )
                ret_str = (
                    ":" + ", ".join(r.type_str for r in ov.returns)
                    if ov.returns
                    else ""
                )
                desc = f" -- {ov.description.splitlines()[0]}" if ov.description else ""
                return f"function({args_str}){ret_str}{desc}"
            return f"function() -- {mspec.description}"
        return None


class SchemaRegistry:
    """Central registry of all 165 GTNH 2.9 components, 19 abstracts, 190 dumps, 28 libs, and 55 userdata types."""

    def __init__(self, docs_root: Optional[Path] = None) -> None:
        if docs_root is None:
            docs_root = Path(__file__).resolve().parent / "data" / "gtnh_docs"
        self.docs_root = docs_root
        self.dumps: Dict[Tuple[str, str], DumpSpec] = load_all_dumps(
            self.docs_root / "dumps"
        )
        stubs = load_all_stubs(self.docs_root / "lua")
        self.components: Dict[str, StubClassSpec] = stubs["components"]
        self.abstracts: Dict[str, StubClassSpec] = stubs["abstracts"]
        self.libs: Dict[str, StubClassSpec] = stubs["libs"]
        self.types: Dict[str, StubClassSpec] = stubs["types"]

        # Map component_type -> StubClassSpec
        self.component_by_type: Dict[str, StubClassSpec] = {}
        for cls_name, cspec in self.components.items():
            ctype = cspec.component_type or cls_name
            self.component_by_type[ctype] = cspec
            self.component_by_type[cls_name] = cspec
            self.component_by_type[ctype.lower()] = cspec

        # Index dumps by (host, component_type)
        self.dumps_by_host_type: Dict[Tuple[str, str], List[DumpSpec]] = {}
        for (host, _dump_name), dspec in self.dumps.items():
            key = (host, dspec.component_type)
            self.dumps_by_host_type.setdefault(key, []).append(dspec)
            key_lower = (host, dspec.component_type.lower())
            if key_lower != key:
                self.dumps_by_host_type.setdefault(key_lower, []).append(dspec)

    def list_component_types(self) -> List[str]:
        types: Set[str] = set()
        for cspec in self.components.values():
            types.add(cspec.component_type or cspec.name)
        for dspec in self.dumps.values():
            types.add(dspec.component_type)
        return sorted(types)

    def resolve_parents(self, class_name: str) -> List[StubClassSpec]:
        """Return MRO-ordered list of StubClassSpec (from base abstract to derived class)."""
        visited: Set[str] = set()
        order: List[StubClassSpec] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            cls = (
                self.components.get(name)
                or self.abstracts.get(name)
                or self.types.get(name)
                or self.component_by_type.get(name)
            )
            if cls is None:
                return
            for parent in cls.parents:
                visit(parent)
            order.append(cls)

        visit(class_name)
        return order

    def get_component_schema(
        self,
        component_type: str,
        host: str = "computer",
        variant: Optional[str] = None,
    ) -> ResolvedComponentSchema:
        """Resolve full component schema for the given component_type and host."""
        cspec = self.component_by_type.get(component_type) or self.component_by_type.get(
            component_type.lower()
        )
        mro = self.resolve_parents(cspec.name) if cspec else []
        methods: Dict[str, StubMethodSpec] = {}
        fields: Dict[str, StubFieldSpec] = {}
        parents_chain = [c.name for c in mro]

        for cls in mro:
            fields.update(cls.fields)
            for mname, mspec in cls.methods.items():
                methods[mname] = mspec

        # Find matching dump(s)
        dump_specs: List[DumpSpec] = []
        if variant and (host, variant) in self.dumps:
            dump_specs = [self.dumps[(host, variant)]]
        elif (host, component_type) in self.dumps_by_host_type:
            dump_specs = self.dumps_by_host_type[(host, component_type)]
        elif (host, component_type.lower()) in self.dumps_by_host_type:
            dump_specs = self.dumps_by_host_type[(host, component_type.lower())]
        else:
            # Fallback to any host dump if the requested host didn't dump this block directly
            for (h, ctype), dlist in self.dumps_by_host_type.items():
                if ctype.lower() == component_type.lower():
                    dump_specs.extend(dlist)

        dump_methods: Dict[str, DumpMethodSpec] = {}
        dump_fields: Dict[str, str] = {}
        for dspec in dump_specs:
            dump_fields.update(dspec.fields)
            # Keep first dump variant as primary, or merge methods across variants if no explicit variant requested
            for mname, dmethod in dspec.methods.items():
                if mname not in dump_methods:
                    dump_methods[mname] = dmethod

        # Filter host-incompatible stub and dump methods based on context notes and host
        filtered_methods: Dict[str, StubMethodSpec] = {}
        excluded_for_host: Set[str] = set()
        for mname, mspec in methods.items():
            notes_text = " ".join(mspec.context_notes).lower()
            if host != "robot" and "robot only" in notes_text:
                excluded_for_host.add(mname)
                continue
            if host == "robot" and "adapter only" in notes_text:
                excluded_for_host.add(mname)
                continue
            if host == "tablet" and "placed hosts only" in notes_text:
                excluded_for_host.add(mname)
                continue
            if host in ("robot", "tablet") and "screen block only" in notes_text:
                excluded_for_host.add(mname)
                continue
            filtered_methods[mname] = mspec
        methods = filtered_methods

        for ex_name in excluded_for_host:
            dump_methods.pop(ex_name, None)

        return ResolvedComponentSchema(
            component_type=cspec.component_type if cspec and cspec.component_type else component_type,
            host=host,
            class_spec=cspec,
            parents_chain=parents_chain,
            methods=methods,
            dump_methods=dump_methods,
            fields=fields,
            dump_fields=dump_fields,
        )

    def default_return_for_type(self, type_str: str) -> Any:
        """Synthesize a sensible default Python/Lua value for a LuaLS return type annotation."""
        primary = type_str.split("|")[0].strip()
        if primary in ("boolean", "bool", "true"):
            return True
        if primary == "false":
            return False
        if primary in ("number", "integer", "int", "float", "double", "long"):
            return 0
        if primary in ("string", "address"):
            return ""
        if primary.startswith('"') and primary.endswith('"'):
            return primary.strip('"')
        if primary.endswith("[]") or primary.startswith("table") or primary == "array":
            return {}
        if primary in ("nil", "void", "none"):
            return None
        if primary in self.types:
            return {}
        return None


_DEFAULT_REGISTRY: Optional[SchemaRegistry] = None


def get_default_registry() -> SchemaRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = SchemaRegistry()
    return _DEFAULT_REGISTRY

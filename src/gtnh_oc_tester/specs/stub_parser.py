"""Parser for LuaLS `---@meta` stubs in GTNH-OC-Lua-Documentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Dict, List, Optional


@dataclass
class StubParamSpec:
    name: str
    type_str: str
    optional: bool = False
    description: str = ""


@dataclass
class StubReturnSpec:
    type_str: str
    name: str = ""
    description: str = ""


@dataclass
class StubOverloadSpec:
    params: List[StubParamSpec] = field(default_factory=list)
    returns: List[StubReturnSpec] = field(default_factory=list)
    description: str = ""
    context_notes: List[str] = field(default_factory=list)


@dataclass
class StubMethodSpec:
    name: str
    overloads: List[StubOverloadSpec] = field(default_factory=list)

    @property
    def description(self) -> str:
        for ov in self.overloads:
            if ov.description:
                return ov.description
        return ""

    @property
    def context_notes(self) -> List[str]:
        notes: List[str] = []
        for ov in self.overloads:
            for n in ov.context_notes:
                if n not in notes:
                    notes.append(n)
        return notes


@dataclass
class StubFieldSpec:
    name: str
    type_str: str
    description: str = ""


@dataclass
class StubClassSpec:
    name: str
    parents: List[str] = field(default_factory=list)
    component_type: Optional[str] = None
    description: str = ""
    fields: Dict[str, StubFieldSpec] = field(default_factory=dict)
    methods: Dict[str, StubMethodSpec] = field(default_factory=dict)
    call_overload: Optional[str] = None
    source_path: Optional[Path] = None
    category: str = "component"  # component, abstract, lib, type


def parse_stub_file(path: Path, category: str = "component") -> Dict[str, StubClassSpec]:
    """Parse a LuaLS stub file into one or more StubClassSpec objects."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    classes: Dict[str, StubClassSpec] = {}
    current_class: Optional[StubClassSpec] = None
    local_var_to_class: Dict[str, StubClassSpec] = {}

    doc_lines: List[str] = []
    params: List[StubParamSpec] = []
    returns: List[StubReturnSpec] = []
    overloads_ann: List[str] = []

    def reset_block() -> None:
        nonlocal doc_lines, params, returns, overloads_ann
        doc_lines = []
        params = []
        returns = []
        overloads_ann = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("---@meta") or line.startswith("---@alias"):
            if not line:
                # Empty line outside a comment block resets unattached comments
                pass
            continue

        if line.startswith("---@class"):
            m = re.match(r"^---@class\s+([A-Za-z0-9_]+)(?:\s*:\s*(.+))?$", line)
            if m:
                cls_name = m.group(1).strip()
                parents_raw = m.group(2)
                parents = (
                    [p.strip() for p in parents_raw.split(",") if p.strip()]
                    if parents_raw
                    else []
                )
                desc = "\n".join(doc_lines).strip()
                current_class = StubClassSpec(
                    name=cls_name,
                    parents=parents,
                    description=desc,
                    source_path=path,
                    category=category,
                )
                classes[cls_name] = current_class
                reset_block()
            continue

        if line.startswith("---@field"):
            m = re.match(r"^---@field\s+([A-Za-z0-9_]+)\s+([^\s#]+)(?:\s*#?\s*(.*))?$", line)
            if m and current_class is not None:
                fname = m.group(1)
                ftyp = m.group(2)
                fdesc = (m.group(3) or "").strip()
                if fname == "type" and ftyp.startswith('"') and ftyp.endswith('"'):
                    current_class.component_type = ftyp.strip('"')
                current_class.fields[fname] = StubFieldSpec(
                    name=fname, type_str=ftyp, description=fdesc
                )
            continue

        if line.startswith("---@overload"):
            ov = line[len("---@overload") :].strip()
            if current_class is not None and not doc_lines and not params:
                current_class.call_overload = ov
            else:
                overloads_ann.append(ov)
            continue

        if line.startswith("---@param"):
            m = re.match(
                r"^---@param\s+([A-Za-z0-9_.]+)(\?)?\s+([^\s#]+)(?:\s*#?\s*(.*))?$",
                line,
            )
            if m:
                pname = m.group(1)
                popt = bool(m.group(2)) or ("nil" in m.group(3))
                ptyp = m.group(3)
                pdesc = (m.group(4) or "").strip()
                params.append(
                    StubParamSpec(
                        name=pname,
                        type_str=ptyp,
                        optional=popt,
                        description=pdesc,
                    )
                )
            continue

        if line.startswith("---@return"):
            rest = line[len("---@return") :].strip()
            # Handle multiple comma-separated returns or single return with comment
            comment = ""
            if "#" in rest:
                rest, comment = rest.split("#", 1)
                rest = rest.strip()
                comment = comment.strip()
            parts = [p.strip() for p in rest.split(",") if p.strip()]
            for part in parts:
                tokens = part.split()
                rtyp = tokens[0] if tokens else "any"
                rname = tokens[1] if len(tokens) > 1 else ""
                returns.append(
                    StubReturnSpec(type_str=rtyp, name=rname, description=comment)
                )
            continue

        if line.startswith("---"):
            text = line[3:].strip()
            doc_lines.append(text)
            continue

        if line.startswith("--"):
            continue

        m_local = re.match(r"^local\s+([A-Za-z0-9_]+)\s*=\s*\{", line)
        if m_local and current_class is not None:
            local_var_to_class[m_local.group(1)] = current_class
            reset_block()
            continue

        m_func = re.match(
            r"^function\s+(?:([A-Za-z0-9_]+)[.:])?([A-Za-z0-9_]+)\s*\(([^)]*)\)",
            line,
        )
        if m_func:
            holder = m_func.group(1)
            mname = m_func.group(2)
            raw_args = [a.strip() for a in m_func.group(3).split(",") if a.strip()]
            target_cls = (
                local_var_to_class.get(holder, current_class)
                if holder
                else current_class
            )
            if target_cls is None:
                target_cls = StubClassSpec(
                    name=path.stem.replace("-", "_"),
                    source_path=path,
                    category=category,
                )
                classes[target_cls.name] = target_cls
                current_class = target_cls

            if not params and raw_args:
                for arg_name in raw_args:
                    params.append(
                        StubParamSpec(name=arg_name, type_str="any", optional=True)
                    )

            context_notes: List[str] = []
            clean_doc: List[str] = []
            for dl in doc_lines:
                if dl.startswith("**") and "**" in dl[2:]:
                    context_notes.append(dl)
                else:
                    clean_doc.append(dl)

            overload = StubOverloadSpec(
                params=list(params),
                returns=list(returns),
                description="\n".join(clean_doc).strip(),
                context_notes=context_notes,
            )
            if mname not in target_cls.methods:
                target_cls.methods[mname] = StubMethodSpec(name=mname, overloads=[])
            target_cls.methods[mname].overloads.append(overload)
            reset_block()
            continue

    return classes


def load_all_stubs(lua_root: Path) -> Dict[str, Dict[str, StubClassSpec]]:
    """Load all LuaLS stubs across components, abstracts, libs, and type-definitions."""
    result: Dict[str, Dict[str, StubClassSpec]] = {
        "components": {},
        "abstracts": {},
        "libs": {},
        "types": {},
    }
    if not lua_root.exists():
        return result

    comp_dir = lua_root / "components"
    if comp_dir.exists():
        for p in sorted(comp_dir.glob("*.lua")):
            result["components"].update(parse_stub_file(p, category="component"))

    abs_dir = lua_root / "components" / "abstracts"
    if abs_dir.exists():
        for p in sorted(abs_dir.glob("*.lua")):
            result["abstracts"].update(parse_stub_file(p, category="abstract"))

    libs_dir = lua_root / "libs"
    if libs_dir.exists():
        for p in sorted(libs_dir.glob("*.lua")):
            parsed = parse_stub_file(p, category="lib")
            lib_name = p.stem
            if parsed:
                first_cls = next(iter(parsed.values()))
                result["libs"][lib_name] = first_cls

    types_dir = lua_root / "type-definitions"
    if types_dir.exists():
        for p in sorted(types_dir.rglob("*.lua")):
            result["types"].update(parse_stub_file(p, category="type"))

    return result

"""Parser for GTNH 2.9 in-game OpenComputers component proxy dumps."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple


TYPEMAP = {
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "bool": "boolean",
    "table": "table",
    "userdata": "userdata",
    "address": "string",
    "nil": "nil",
    "int": "integer",
    "integer": "integer",
    "array": "table",
    "float": "number",
    "double": "number",
    "long": "integer",
    "byte": "integer",
    "short": "integer",
}


@dataclass
class DumpParamSpec:
    name: str
    type_str: str
    optional: bool = False


@dataclass
class DumpOverloadSpec:
    params: List[DumpParamSpec] = field(default_factory=list)
    returns: List[str] = field(default_factory=list)


@dataclass
class DumpMethodSpec:
    name: str
    raw_doc: str
    description: str
    overloads: List[DumpOverloadSpec] = field(default_factory=list)
    is_field: bool = False


@dataclass
class DumpSpec:
    host: str
    dump_name: str
    component_type: str
    address: str
    slot: str
    methods: Dict[str, DumpMethodSpec] = field(default_factory=dict)
    fields: Dict[str, str] = field(default_factory=dict)


def parse_doc_signature(name: str, doc: str) -> DumpMethodSpec:
    """Parse an OpenComputers @Callback doc string into structured overloads."""
    desc = ""
    for sep in (" -- ", "; ", " – "):
        if sep in doc:
            head, desc = doc.split(sep, 1)
            break
    else:
        head = doc

    overloads: List[DumpOverloadSpec] = []
    for part in re.split(r"\s+OR\s+(?=function)", head):
        part = part.strip()
        if not part.startswith("function"):
            return DumpMethodSpec(
                name=name,
                raw_doc=doc,
                description=doc,
                overloads=[],
                is_field=True,
            )
        rest = part[len("function") :].lstrip()
        if not rest.startswith("("):
            overloads.append(DumpOverloadSpec(params=[], returns=[]))
            continue

        depth = 0
        end: Optional[int] = None
        for i, ch in enumerate(rest):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is None:
            overloads.append(DumpOverloadSpec(params=[], returns=[]))
            continue

        argstr = rest[1:end]
        ret = rest[end + 1 :].lstrip().lstrip(":").strip()
        params: List[DumpParamSpec] = []
        seen_bracket = False
        for raw in argstr.split(","):
            token = raw.strip()
            if "[" in token:
                seen_bracket = True
            token = token.replace("[", "").replace("]", "").strip()
            if not token:
                continue
            head_, sep_, tail_ = token.partition(":")
            if head_.strip().lower() in ("optional", "opt") and sep_:
                seen_bracket = True
                head_, sep_, tail_ = tail_.partition(":")
            pname = head_.strip()
            ptyp = tail_.split("=")[0].strip() if sep_ else ""
            if pname.lower() in TYPEMAP and ptyp.lower() not in TYPEMAP:
                pname, ptyp = ptyp, pname
            pname = pname.split("(")[0].strip().strip(".")
            ptyp = ptyp or "any"
            alt_types: List[str] = []
            for t in re.split(r"\s+OR\s+|\|", ptyp):
                t = t.strip()
                if not t:
                    continue
                if ":" in t:
                    t = t.split(":")[-1].strip()
                t = TYPEMAP.get(t.lower(), t)
                if t not in alt_types:
                    alt_types.append(t)
            ptyp = "|".join(alt_types) if alt_types else "any"
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", pname):
                pname = f"arg{len(params) + 1}"
            params.append(DumpParamSpec(name=pname, type_str=ptyp, optional=seen_bracket))

        alternatives: List[List[str]] = []
        for alt in re.split(r"\s+or\s+", ret) if ret else []:
            alt = alt.strip()
            if alt.startswith("(") and alt.endswith(")"):
                alt = alt[1:-1]
            tuple_ = [t.strip() for t in alt.split(",") if t.strip()]
            if tuple_:
                alternatives.append(tuple_)

        rets: List[str] = []
        max_len = max((len(a) for a in alternatives), default=0)
        for pos in range(max_len):
            types: List[str] = []
            for alt in alternatives:
                t = alt[pos] if pos < len(alt) else "nil"
                t = TYPEMAP.get(t.lower(), t)
                if t not in types:
                    types.append(t)
            rets.append("|".join(types))
        overloads.append(DumpOverloadSpec(params=params, returns=rets))

    return DumpMethodSpec(
        name=name,
        raw_doc=doc,
        description=desc.strip(),
        overloads=overloads,
        is_field=False,
    )


def parse_dump_file(path: Path, host: Optional[str] = None) -> DumpSpec:
    """Parse a single `dumps/<host>/<name>.txt` file."""
    src = path.read_text(encoding="utf-8", errors="replace")
    resolved_host = host or path.parent.name
    dump_name = path.stem

    raw_entries: Dict[str, str] = {}
    for m in re.finditer(r'\["([A-Za-z0-9_]+)"\]\s*=\s*"((?:[^"\\]|\\.)*)"', src):
        key = m.group(1)
        val = m.group(2).replace('\\"', '"').replace("\\\\", "\\")
        raw_entries[key] = val

    comp_type = raw_entries.get("type", re.sub(r"-\d+$", "", dump_name))
    address = raw_entries.get("address", "00000000-0000-0000-0000-000000000000")
    slot = raw_entries.get("slot", "-1")

    methods: Dict[str, DumpMethodSpec] = {}
    fields: Dict[str, str] = {}
    for k, v in raw_entries.items():
        if k in ("type", "address", "slot"):
            continue
        parsed = parse_doc_signature(k, v)
        if parsed.is_field:
            fields[k] = v
        else:
            methods[k] = parsed

    return DumpSpec(
        host=resolved_host,
        dump_name=dump_name,
        component_type=comp_type,
        address=address,
        slot=slot,
        methods=methods,
        fields=fields,
    )


def load_all_dumps(dumps_root: Path) -> Dict[Tuple[str, str], DumpSpec]:
    """Load all dumps under `dumps/{computer,robot,tablet}/*.txt`."""
    results: Dict[Tuple[str, str], DumpSpec] = {}
    if not dumps_root.exists():
        return results
    for host_dir in sorted(dumps_root.iterdir()):
        if not host_dir.is_dir():
            continue
        host = host_dir.name
        for txt_path in sorted(host_dir.glob("*.txt")):
            spec = parse_dump_file(txt_path, host=host)
            results[(host, spec.dump_name)] = spec
    return results

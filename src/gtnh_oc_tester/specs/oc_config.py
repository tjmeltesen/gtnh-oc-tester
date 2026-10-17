"""OpenComputers GTNH 2.9 machine and component configuration model."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union


BUNDLED_CFG_PATH = Path(__file__).parent / "data" / "oc_assets" / "OpenComputers.cfg"
BUNDLED_APP_CONF_PATH = Path(__file__).parent / "data" / "oc_assets" / "application.conf"


@dataclass
class OCMachineConfig:
    """Locked GTNH 2.9 OpenComputers configuration and hardware tier parameters."""

    architecture: str = "Lua 5.2"
    default_lua53: bool = False
    enable_lua53: bool = True
    enable_lua54: bool = False
    timeout: float = 5.0
    call_budgets: Tuple[float, float, float] = (0.5, 1.0, 1.5)
    ram_sizes_kb: Tuple[int, int, int, int, int, int] = (192, 256, 384, 512, 768, 1024)
    ram_scale_for_64bit: float = 1.8
    max_signal_queue_size: int = 1024
    eeprom_size: int = 4096
    eeprom_data_size: int = 256
    vram_sizes: Tuple[int, int, int] = (1, 2, 3)
    screen_resolutions_by_tier: Tuple[Tuple[int, int], ...] = ((50, 16), (80, 25), (160, 50))
    allow_bytecode: bool = False
    allow_gc: bool = False
    cpu_tier: int = 3
    ram_tier: int = 6

    def __post_init__(self) -> None:
        if self.architecture not in ("Lua 5.3", "Lua 5.2"):
            raise ValueError(f"Invalid architecture: {self.architecture!r}. Expected 'Lua 5.3' or 'Lua 5.2'.")
        if not (1 <= int(self.cpu_tier) <= len(self.call_budgets)):
            raise ValueError(f"Invalid cpu_tier: {self.cpu_tier}. Must be 1..{len(self.call_budgets)}.")
        if not (1 <= int(self.ram_tier) <= len(self.ram_sizes_kb)):
            raise ValueError(f"Invalid ram_tier: {self.ram_tier}. Must be 1..{len(self.ram_sizes_kb)}.")

    @property
    def call_budget_per_tick(self) -> float:
        """Return the per-tick direct component call budget for the configured CPU tier."""
        return float(self.call_budgets[self.cpu_tier - 1])

    @property
    def ram_bytes(self) -> int:
        """Return the total RAM in bytes for the configured RAM tier."""
        return int(self.ram_sizes_kb[self.ram_tier - 1] * 1024)


def _strip_hocon_comments(text: str) -> str:
    lines: List[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        # Remove inline unquoted # or // comments
        in_quotes = False
        out_chars: List[str] = []
        i = 0
        while i < len(raw_line):
            ch = raw_line[i]
            if ch == '"' and (i == 0 or raw_line[i - 1] != "\\"):
                in_quotes = not in_quotes
                out_chars.append(ch)
            elif not in_quotes and ch == "#":
                break
            elif not in_quotes and ch == "/" and i + 1 < len(raw_line) and raw_line[i + 1] == "/":
                break
            else:
                out_chars.append(ch)
            i += 1
        lines.append("".join(out_chars))
    return "\n".join(lines)


def _parse_bool(val: str) -> bool:
    return val.strip().lower() in ("true", "1", "yes", "on")


def _parse_number_list(raw_body: str, as_int: bool = False) -> Tuple[Any, ...]:
    tokens = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw_body)
    if as_int:
        return tuple(int(float(t)) for t in tokens)
    return tuple(float(t) for t in tokens)


def _parse_hocon_config_text(text: str) -> Dict[str, Any]:
    cleaned = _strip_hocon_comments(text)
    parsed: Dict[str, Any] = {}

    scalar_patterns = {
        "timeout": (r"\btimeout\s*[:=]\s*([-+]?\d*\.?\d+)", float),
        "ram_scale_for_64bit": (r"\bramScaleFor64Bit\s*[:=]\s*([-+]?\d*\.?\d+)", float),
        "max_signal_queue_size": (r"\bmaxSignalQueueSize\s*[:=]\s*(\d+)", int),
        "eeprom_size": (r"\beepromSize\s*[:=]\s*(\d+)", int),
        "eeprom_data_size": (r"\beepromDataSize\s*[:=]\s*(\d+)", int),
        "allow_bytecode": (r"\ballowBytecode\s*[:=]\s*(true|false)", _parse_bool),
        "allow_gc": (r"\ballowGC\s*[:=]\s*(true|false)", _parse_bool),
        "default_lua53": (r"\bdefaultLua53\s*[:=]\s*(true|false)", _parse_bool),
        "enable_lua53": (r"\benableLua53\s*[:=]\s*(true|false)", _parse_bool),
        "enable_lua54": (r"\benableLua54\s*[:=]\s*(true|false)", _parse_bool),
    }

    for field_name, (pattern, caster) in scalar_patterns.items():
        m = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if m:
            parsed[field_name] = caster(m.group(1))

    m_budgets = re.search(r"\bcallBudgets\s*[:=]\s*\[([^\]]*)\]", cleaned, flags=re.DOTALL)
    if m_budgets:
        vals = _parse_number_list(m_budgets.group(1), as_int=False)
        if len(vals) >= 3:
            parsed["call_budgets"] = (float(vals[0]), float(vals[1]), float(vals[2]))

    m_ram = re.search(r"\bramSizes\s*[:=]\s*\[([^\]]*)\]", cleaned, flags=re.DOTALL)
    if m_ram:
        vals = _parse_number_list(m_ram.group(1), as_int=True)
        if len(vals) >= 6:
            parsed["ram_sizes_kb"] = (
                int(vals[0]),
                int(vals[1]),
                int(vals[2]),
                int(vals[3]),
                int(vals[4]),
                int(vals[5]),
            )

    m_vram = re.search(r"\bvramSizes\s*[:=]\s*\[([^\]]*)\]", cleaned, flags=re.DOTALL)
    if m_vram:
        vals = _parse_number_list(m_vram.group(1), as_int=True)
        if len(vals) >= 3:
            parsed["vram_sizes"] = (int(vals[0]), int(vals[1]), int(vals[2]))

    return parsed


def load_oc_config(path: Optional[Union[str, Path]] = None, **overrides: Any) -> OCMachineConfig:
    """Load an `OCMachineConfig` from `OpenComputers.cfg` or `application.conf`.

    Respects the parsed `defaultLua53` (`false` in GTNH `OpenComputers.cfg`, giving
    `"Lua 5.2"` by default) and `maxSignalQueueSize` (`1024` in `OpenComputers.cfg`,
    `256` in `application.conf`, or any value from a custom config file).
    """
    values: Dict[str, Any] = {}

    if path is not None:
        cfg_path = Path(path)
        if not cfg_path.exists():
            raise FileNotFoundError(f"OpenComputers config file not found: {cfg_path}")
        raw_text = cfg_path.read_text(encoding="utf-8", errors="replace")
        values.update(_parse_hocon_config_text(raw_text))
    else:
        if BUNDLED_APP_CONF_PATH.exists():
            values.update(
                _parse_hocon_config_text(
                    BUNDLED_APP_CONF_PATH.read_text(encoding="utf-8", errors="replace")
                )
            )
        if BUNDLED_CFG_PATH.exists():
            values.update(
                _parse_hocon_config_text(
                    BUNDLED_CFG_PATH.read_text(encoding="utf-8", errors="replace")
                )
            )

    if "default_lua53" in values and overrides.get("architecture") is None and "architecture" not in values:
        values["architecture"] = "Lua 5.3" if values["default_lua53"] else "Lua 5.2"

    valid_fields = {f.name for f in fields(OCMachineConfig)}
    for k, v in overrides.items():
        if k not in valid_fields:
            raise TypeError(f"Unknown OCMachineConfig parameter: {k!r}")
        if v is not None:
            values[k] = v

    return OCMachineConfig(**values)

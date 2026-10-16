"""Multi-level Execution Tracer (Lua debug.sethook + Component Bus + Event Queue interceptors)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from ..components.auto_mock import ComponentCallRecord


def _short_repr(val: Any, max_len: int = 48) -> str:
    if val is None:
        return "nil"
    if isinstance(val, bool):
        return "true" if val else "false"
    if hasattr(val, "items") and not isinstance(val, (dict, str, bytes)):
        try:
            d = {k: v for k, v in val.items()}
            val = d
        except Exception:
            pass
    s = repr(val)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


@dataclass
class TraceEvent:
    seq: int
    tick: int
    kind: str  # "boot", "lua_call", "component_call", "event_wait"
    title: str
    detail: str = ""
    component_type: Optional[str] = None
    method: Optional[str] = None
    args_str: str = ""
    result_str: str = ""
    state_mutation: Optional[str] = None
    signature_key: Tuple[str, ...] = field(default_factory=tuple)


class ExecutionTracer:
    """Captures Lua function calls, component proxy calls, and event/signal wakeups."""

    def __init__(
        self,
        sandbox: Optional[Any] = None,
        bus: Optional[Any] = None,
        scheduler: Optional[Any] = None,
        trace_lua_functions: bool = True,
    ) -> None:
        self.sandbox = sandbox
        self.bus = bus
        self.scheduler = scheduler
        self.trace_lua_functions = trace_lua_functions
        self.events: List[TraceEvent] = []
        self._seq = 0
        self._attached = False

    def attach(self, script_name: str = "main.lua") -> None:
        if self._attached:
            return
        self._attached = True
        self._record(
            kind="boot",
            title=f"Boot Sandbox ({script_name})",
            detail="Initialize OpenComputers _ENV and component bus",
            signature_key=("boot", script_name),
        )
        if self.bus is not None:
            self.bus.call_listeners.append(self._on_component_call)
        if self.scheduler is not None:
            self.scheduler.on_signal_Wait.append(self._on_signal_wait)
        if self.trace_lua_functions and self.sandbox is not None:
            self._install_lua_hook()

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _current_tick(self) -> int:
        if self.scheduler is not None:
            return self.scheduler.current_tick
        return 0

    def _record(
        self,
        kind: str,
        title: str,
        detail: str = "",
        component_type: Optional[str] = None,
        method: Optional[str] = None,
        args_str: str = "",
        result_str: str = "",
        state_mutation: Optional[str] = None,
        signature_key: Tuple[str, ...] = (),
    ) -> TraceEvent:
        ev = TraceEvent(
            seq=self._next_seq(),
            tick=self._current_tick(),
            kind=kind,
            title=title,
            detail=detail,
            component_type=component_type,
            method=method,
            args_str=args_str,
            result_str=result_str,
            state_mutation=state_mutation,
            signature_key=signature_key or (kind, title),
        )
        self.events.append(ev)
        return ev

    def record_user_function(self, func_name: str, source: str, line: int) -> None:
        self._record(
            kind="lua_call",
            title=f"fn {func_name}()",
            detail=f"{source}:{line}",
            signature_key=("lua_call", func_name),
        )

    def _install_lua_hook(self) -> None:
        if self.sandbox is None:
            return
        self.sandbox.lua.globals()["__oc_trace_fn"] = self.record_user_function
        self.sandbox.lua.execute(
            r"""
            if debug and debug.sethook then
              local _ignored = {
                checkArg = true, pairs = true, ipairs = true, next = true,
                tostring = true, tonumber = true, type = true, select = true,
                unpack = true, pcall = true, xpcall = true, require = true,
                load = true, loadfile = true, dofile = true, setmetatable = true,
                getmetatable = true, rawget = true, rawset = true, error = true,
                assert = true, print = true,
              }
              debug.sethook(function(event)
                if event ~= "call" then return end
                local info = debug.getinfo(2, "nSl")
                if not info or info.what ~= "Lua" then return end
                local name = info.name
                local src = info.source or ""
                if name and not _ignored[name] and not name:match("^_") then
                  if src:match("^=script") or src:match("^=/home/") or src:match("_spec%.lua") then
                    __oc_trace_fn(name, src:sub(2), info.linedefined or 0)
                  end
                end
              end, "c")
            end
            """
        )

    def _on_component_call(self, rec: ComponentCallRecord) -> None:
        # Avoid cluttering trace with internal per-cell GPU draws unless explicitly desired
        if rec.component_type == "gpu" and rec.method in (
            "get",
            "set",
            "fill",
            "copy",
            "setBackground",
            "setForeground",
            "getBackground",
            "getForeground",
            "setPaletteColor",
            "getPaletteColor",
        ):
            return
        args_fmt = ", ".join(_short_repr(a, 28) for a in rec.args)
        res_fmt = _short_repr(rec.result, 36)
        title = f"{rec.component_type}.{rec.method}({args_fmt})"
        detail = f"-> {res_fmt}"
        self._record(
            kind="component_call",
            title=title,
            detail=detail,
            component_type=rec.component_type,
            method=rec.method,
            args_str=args_fmt,
            result_str=res_fmt,
            state_mutation=rec.state_mutation,
            signature_key=("component_call", rec.component_type, rec.method, args_fmt),
        )

    def _on_signal_wait(
        self,
        filter_name: Optional[str],
        timeout: Optional[float],
        matched: Optional[Tuple[str, Tuple[Any, ...]]],
    ) -> None:
        if filter_name == "os.sleep":
            self._record(
                kind="event_wait",
                title=f"os.sleep({timeout}s)",
                detail=f"advance virtual clock ({timeout}s)",
                signature_key=("event_wait", "os.sleep", str(timeout)),
            )
            return
        flt_label = f"'{filter_name}'" if filter_name else "*"
        if matched is not None:
            sig_name, sig_args = matched
            detail = f"woke on '{sig_name}' ({', '.join(_short_repr(a, 20) for a in sig_args[:2])})"
        else:
            detail = f"timeout ({timeout}s)"
        self._record(
            kind="event_wait",
            title=f"event.pull({flt_label})",
            detail=detail,
            signature_key=("event_wait", filter_name or "*"),
        )

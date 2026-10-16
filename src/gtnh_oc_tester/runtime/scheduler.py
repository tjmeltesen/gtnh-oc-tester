"""Deterministic virtual tick clock and event/signal queue for OpenComputers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple


@dataclass
class ScheduledTimer:
    timer_id: int
    interval_ticks: int
    next_tick: int
    callback: Callable[[], Any]
    remaining_times: float  # math.inf for repeating


class DeterministicScheduler:
    """Virtual 20-TPS clock, signal queue, and event listener/timer dispatcher."""

    TICKS_PER_SECOND = 20

    def __init__(self) -> None:
        self.current_tick: int = 0
        self.signal_queue: Deque[Tuple[str, Tuple[Any, ...]]] = deque()
        self.listeners: Dict[str, List[Callable[..., Any]]] = {}
        self.timers: Dict[int, ScheduledTimer] = {}
        self._next_timer_id: int = 1
        self.tick_hooks: List[Callable[[int], None]] = []
        self.on_signal_Wait: List[Callable[[Optional[str], Optional[float], Optional[Tuple[str, Tuple[Any, ...]]]], None]] = []

    def uptime(self) -> float:
        return round(self.current_tick / self.TICKS_PER_SECOND, 4)

    def add_tick_hook(self, fn: Callable[[int], None]) -> None:
        if fn not in self.tick_hooks:
            self.tick_hooks.append(fn)

    def push_signal(self, name: str, *args: Any) -> bool:
        self.signal_queue.append((str(name), tuple(args)))
        return True

    def register_listener(self, event_name: str, callback: Callable[..., Any]) -> bool:
        lst = self.listeners.setdefault(str(event_name), [])
        if callback in lst:
            return False
        lst.append(callback)
        return True

    def unregister_listener(self, event_name: str, callback: Callable[..., Any]) -> bool:
        lst = self.listeners.get(str(event_name), [])
        if callback in lst:
            lst.remove(callback)
            return True
        return False

    def register_timer(
        self,
        interval_seconds: float,
        callback: Callable[[], Any],
        times: float = 1,
    ) -> int:
        interval_ticks = max(1, int(round(float(interval_seconds) * self.TICKS_PER_SECOND)))
        tid = self._next_timer_id
        self._next_timer_id += 1
        rem = math.inf if times == math.inf or times < 0 else max(1, int(times))
        self.timers[tid] = ScheduledTimer(
            timer_id=tid,
            interval_ticks=interval_ticks,
            next_tick=self.current_tick + interval_ticks,
            callback=callback,
            remaining_times=rem,
        )
        return tid

    def cancel_timer(self, timer_id: int) -> bool:
        return self.timers.pop(int(timer_id), None) is not None

    def advance_ticks(self, ticks: int = 1) -> None:
        steps = max(0, int(ticks))
        for _ in range(steps):
            self.current_tick += 1
            for hook in list(self.tick_hooks):
                hook(self.current_tick)
            self._fire_due_timers()

    def _fire_due_timers(self) -> None:
        due_ids = [
            tid
            for tid, t in sorted(self.timers.items())
            if t.next_tick <= self.current_tick
        ]
        for tid in due_ids:
            timer = self.timers.get(tid)
            if timer is None:
                continue
            try:
                res = timer.callback()
            except Exception:
                res = False
            if res is False:
                self.timers.pop(tid, None)
                continue
            if timer.remaining_times != math.inf:
                timer.remaining_times -= 1
                if timer.remaining_times <= 0:
                    self.timers.pop(tid, None)
                    continue
            timer.next_tick = self.current_tick + timer.interval_ticks

    def _dispatch_listeners(self, sig_name: str, sig_args: Tuple[Any, ...]) -> None:
        for cb in list(self.listeners.get(sig_name, [])):
            try:
                res = cb(sig_name, *sig_args)
                if res is False:
                    self.unregister_listener(sig_name, cb)
            except Exception:
                pass

    def sleep(self, seconds: float = 0.05) -> None:
        ticks = max(1, int(round(max(0.0, float(seconds)) * self.TICKS_PER_SECOND)))
        self.advance_ticks(ticks)
        for cb in self.on_signal_Wait:
            cb("os.sleep", seconds, None)
        # Process any pending signals for listeners
        while self.signal_queue:
            sig_name, sig_args = self.signal_queue.popleft()
            self._dispatch_listeners(sig_name, sig_args)

    def pull_signal(
        self,
        timeout: Optional[float] = None,
        filter_name: Optional[str] = None,
        *filter_args: Any,
    ) -> Tuple[Any, ...]:
        """Pull a signal matching filter_name and filter_args, advancing virtual time up to timeout."""
        max_ticks = (
            max(1, int(round(float(timeout) * self.TICKS_PER_SECOND)))
            if timeout is not None and timeout != math.inf
            else 20  # Default bounded virtual ticks if no signal is queued in headless test
        )

        def _matches(sig_name: str, sig_args: Tuple[Any, ...]) -> bool:
            if filter_name is not None and sig_name != filter_name:
                return False
            for idx, expected in enumerate(filter_args):
                if expected is not None:
                    if idx >= len(sig_args) or sig_args[idx] != expected:
                        return False
            return True

        elapsed = 0
        while True:
            while self.signal_queue:
                sig_name, sig_args = self.signal_queue.popleft()
                self._dispatch_listeners(sig_name, sig_args)
                if _matches(sig_name, sig_args):
                    for hook in self.on_signal_Wait:
                        hook(filter_name, timeout, (sig_name, sig_args))
                    return (sig_name, *sig_args)

            if elapsed >= max_ticks:
                if filter_name == "timer":
                    # Synthesize timer wakeup event after advancing timeout ticks
                    synthetic = ("timer", self._next_timer_id)
                    for hook in self.on_signal_Wait:
                        hook(filter_name, timeout, ("timer", (self._next_timer_id,)))
                    return synthetic
                for hook in self.on_signal_Wait:
                    hook(filter_name, timeout, None)
                return (None,)

            self.advance_ticks(1)
            elapsed += 1

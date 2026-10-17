"""Interactive live OpenOS shell & screen modes (Pygame Window, Web UI, and Terminal ANSI TUI)."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .environment import OCEnvironment
from .screen.renderers import render_screen_ansi, render_screen_html


INTERACTIVE_WEB_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>GTNH OpenComputers Interactive Terminal</title>
<style>
  :root {
    --bg: #0b0f19;
    --panel: #111827;
    --border: #334155;
    --accent: #38bdf8;
    --green: #22c55e;
    --danger: #ef4444;
    --text: #e2e8f0;
    --muted: #94a3b8;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    padding: 0;
    width: 100vw;
    height: 100vh;
    max-width: 100vw;
    max-height: 100vh;
    overflow: hidden;
    background: var(--bg);
    color: var(--text);
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  }
  .app-shell {
    display: flex;
    flex-direction: column;
    width: 100vw;
    height: 100vh;
    max-width: 100vw;
    max-height: 100vh;
    padding: 10px 14px;
    gap: 10px;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  h1 { margin: 0; font-size: 16px; color: var(--accent); }
  .badges { display: flex; gap: 6px; flex-wrap: wrap; font-size: 11px; }
  .badge {
    background: #1e293b;
    border: 1px solid var(--border);
    padding: 3px 9px;
    border-radius: 999px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 310px;
    gap: 12px;
    flex: 1 1 auto;
    min-height: 0;
    overflow: hidden;
  }
  @media (max-width: 980px) {
    .layout {
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: minmax(0, 1fr) auto;
    }
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }
  .screen-viewport {
    flex: 1 1 auto;
    min-width: 0;
    min-height: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #05070c;
    border: 2px solid #475569;
    border-radius: 6px;
    padding: 6px;
    overflow: hidden;
    cursor: crosshair;
    user-select: none;
    outline: none;
  }
  .screen-viewport:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.35);
  }
  #oc-screen {
    margin: 0;
    background: #000000;
    font-family: "JetBrains Mono", "Fira Code", "Cascadia Mono", Consolas, "Courier New", monospace;
    font-size: clamp(8px, 1.05vw, 14px);
    line-height: 1.15;
    letter-spacing: 0;
    white-space: pre;
    transform-origin: center center;
  }
  .toolbar {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: 8px;
    flex-shrink: 0;
  }
  .cmd-bar {
    display: flex;
    gap: 6px;
    margin-top: 8px;
    flex-shrink: 0;
  }
  input[type="text"], textarea {
    width: 100%;
    background: #0f172a;
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 9px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12px;
  }
  button {
    background: #0284c7;
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 11px;
    cursor: pointer;
    white-space: nowrap;
  }
  button:hover { background: #0369a1; }
  button.secondary { background: #334155; }
  button.secondary:hover { background: #475569; }
  button.danger { background: #dc2626; }
  button.danger:hover { background: #b91c1c; }
  .hint { color: var(--muted); font-size: 11px; margin-top: 6px; flex-shrink: 0; }
  h2 { margin: 0 0 6px 0; font-size: 13px; color: var(--accent); flex-shrink: 0; }
  .comp-list {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11px;
    flex: 1 1 auto;
    min-height: 60px;
    overflow-y: auto;
    margin-bottom: 10px;
    border: 1px solid #1e293b;
    border-radius: 6px;
    padding: 4px;
  }
  .comp-item {
    padding: 3px 5px;
    border-bottom: 1px solid #1e293b;
    display: flex;
    justify-content: space-between;
  }
</style>
</head>
<body>
<div class="app-shell">
  <header>
    <div>
      <h1>GTNH 2.9 OpenComputers — Live Interactive Screen &amp; OpenOS Shell</h1>
    </div>
    <div class="badges">
      <span class="badge" id="st-arch">Lua 5.2</span>
      <span class="badge" id="st-uptime">Uptime: 0.00s (Tick 0)</span>
      <span class="badge" id="st-ram">RAM: -- / -- KB</span>
      <span class="badge" id="st-res">80x25</span>
    </div>
  </header>

  <div class="layout">
    <div class="card">
      <div class="screen-viewport" id="screen-focus" tabindex="0" title="Click to focus and type directly into OpenOS (Ctrl+C, Ctrl+D, Ctrl+V, Arrows, Tab all supported)">
        <div id="oc-screen">Booting OpenOS...</div>
      </div>

      <div class="toolbar">
        <button type="button" class="danger" id="btn-ctrlc" title="Send Ctrl+C + interrupted signal">Ctrl+C (Interrupt)</button>
        <button type="button" class="secondary" id="btn-ctrld" title="Send Ctrl+D (EOF)">Ctrl+D (EOF)</button>
        <button type="button" class="secondary" id="btn-ctrlw" title="Send Ctrl+W (Delete word)">Ctrl+W (Del Word)</button>
        <button type="button" class="secondary" id="btn-tab" title="Send Tab (Autocomplete)">Tab (Complete)</button>
        <button type="button" class="secondary" id="btn-up" title="Previous command in history">▲ Up</button>
        <button type="button" class="secondary" id="btn-down" title="Next command in history">▼ Down</button>
        <button type="button" class="secondary" id="btn-paste" title="Paste clipboard into OpenOS">Paste Clipboard</button>
        <button type="button" class="secondary" id="btn-clear" title="Clear terminal (Ctrl+L)">Ctrl+L (Clear)</button>
        <button type="button" class="secondary" id="btn-reboot" title="Restart interactive shell">Reboot Shell</button>
      </div>

      <form class="cmd-bar" id="cmd-form">
        <input type="text" id="cmd-input" placeholder="Type an OpenOS command (e.g. ls /home, lua, scripts/manual/test_me_snapshot.lua) and press Enter..." autocomplete="off" />
        <button type="submit">Send Command</button>
      </form>
      <div class="hint">
        Click the black monitor to type directly into OpenOS. Supports <b>Ctrl+C</b> (Interrupt), <b>Ctrl+D</b> (EOF), <b>Ctrl+V</b> (Paste), <b>Ctrl+L</b> (Clear), <b>Ctrl+W</b>, <b>Tab</b>, and <b>Arrow keys</b>.
      </div>
    </div>

    <div class="card">
      <h2>Attached GTNH Components</h2>
      <div class="comp-list" id="comp-list"></div>

      <h2>Quick Attach Component</h2>
      <div class="cmd-bar" style="margin-top: 0; margin-bottom: 10px;">
        <input type="text" id="attach-type" placeholder="e.g. me_controller, gt_machine, transposer" value="me_controller" />
        <button type="button" id="btn-attach">Attach</button>
      </div>

      <h2>Recent Component Calls</h2>
      <div class="comp-list" id="call-log" style="margin-bottom: 0;"></div>
    </div>
  </div>
</div>

<script>
const screenEl = document.getElementById("oc-screen");
const screenFocus = document.getElementById("screen-focus");
const cmdForm = document.getElementById("cmd-form");
const cmdInput = document.getElementById("cmd-input");

let currentCols = 80;
let currentRows = 25;

// Complete browser KeyboardEvent.key / code to OpenComputers LWJGL2 scancode map
const KEY_TO_LWJGL = {
  "Escape": 0x01, "1": 0x02, "!": 0x02, "2": 0x03, "@": 0x03, "3": 0x04, "#": 0x04,
  "4": 0x05, "$": 0x05, "5": 0x06, "%": 0x06, "6": 0x07, "^": 0x07, "7": 0x08, "&": 0x08,
  "8": 0x09, "*": 0x09, "9": 0x0A, "(": 0x0A, "0": 0x0B, ")": 0x0B, "-": 0x0C, "_": 0x0C,
  "=": 0x0D, "+": 0x0D, "Backspace": 0x0E, "Tab": 0x0F,
  "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14, "y": 0x15, "u": 0x16, "i": 0x17,
  "o": 0x18, "p": 0x19, "[": 0x1A, "{": 0x1A, "]": 0x1B, "}": 0x1B, "Enter": 0x1C,
  "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22, "h": 0x23, "j": 0x24, "k": 0x25,
  "l": 0x26, ";": 0x27, ":": 0x27, "'": 0x28, "\"": 0x28, "`": 0x29, "~": 0x29,
  "\\": 0x2B, "|": 0x2B, "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30, "n": 0x31,
  "m": 0x32, ",": 0x33, "<": 0x33, ".": 0x34, ">": 0x34, "/": 0x35, "?": 0x35, " ": 0x39,
  "F1": 0x3B, "F2": 0x3C, "F3": 0x3D, "F4": 0x3E, "F5": 0x3F, "F6": 0x40,
  "F7": 0x41, "F8": 0x42, "F9": 0x43, "F10": 0x44, "F11": 0x57, "F12": 0x58,
  "Home": 0xC7, "ArrowUp": 0xC8, "PageUp": 0xC9, "ArrowLeft": 0xCB,
  "ArrowRight": 0xCD, "End": 0xCF, "ArrowDown": 0xD0, "PageDown": 0xD1,
  "Insert": 0xD2, "Delete": 0xD3
};

function fitScreenToViewport() {
  if (!screenFocus || !screenEl) return;
  screenEl.style.transform = "scale(1)";
  const availW = Math.max(100, screenFocus.clientWidth - 16);
  const availH = Math.max(80, screenFocus.clientHeight - 16);
  const naturalW = Math.max(1, screenEl.scrollWidth);
  const naturalH = Math.max(1, screenEl.scrollHeight);
  const scale = Math.min(1.0, availW / naturalW, availH / naturalH);
  screenEl.style.transform = `scale(${scale.toFixed(4)})`;
}

window.addEventListener("resize", fitScreenToViewport);

async function postJson(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  return await res.json();
}

function updateUI(state) {
  if (!state) return;
  currentCols = state.width || 80;
  currentRows = state.height || 25;
  screenEl.innerHTML = state.screen_rows_html;
  document.getElementById("st-arch").textContent = state.architecture + " (" + state.jar_version + ")";
  document.getElementById("st-uptime").textContent = `Uptime: ${state.uptime.toFixed(2)}s (Tick ${state.tick})`;
  document.getElementById("st-ram").textContent = `Free RAM: ${(state.free_memory / 1024).toFixed(1)} / ${(state.total_memory / 1024).toFixed(0)} KB`;
  document.getElementById("st-res").textContent = `${currentCols}x${currentRows}`;

  const compList = document.getElementById("comp-list");
  compList.innerHTML = (state.components || []).map(c =>
    `<div class="comp-item"><span><b>${c.type}</b></span><span style="color:#94a3b8">${c.address.slice(0, 13)}…</span></div>`
  ).join("");

  const callLog = document.getElementById("call-log");
  callLog.innerHTML = (state.recent_calls || []).map(c =>
    `<div class="comp-item"><span>[T${c.tick}] ${c.type}.${c.method}</span></div>`
  ).join("");

  fitScreenToViewport();
}

async function pollState() {
  try {
    const res = await fetch("/api/state");
    const data = await res.json();
    updateUI(data);
  } catch (e) {}
}

cmdForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = cmdInput.value;
  cmdInput.value = "";
  const state = await postJson("/api/input", {action: "text", text: text, press_enter: true});
  updateUI(state);
});

// Support Ctrl+C, Ctrl+D, Ctrl+L inside the command input box too
cmdInput.addEventListener("keydown", async (e) => {
  if (e.ctrlKey && e.key.toLowerCase() === "c" && cmdInput.selectionStart === cmdInput.selectionEnd) {
    e.preventDefault();
    const state = await postJson("/api/input", {action: "interrupt"});
    updateUI(state);
  } else if (e.ctrlKey && e.key.toLowerCase() === "d") {
    e.preventDefault();
    const state = await postJson("/api/input", {action: "eof"});
    updateUI(state);
  } else if (e.ctrlKey && e.key.toLowerCase() === "l") {
    e.preventDefault();
    const state = await postJson("/api/input", {action: "clear"});
    updateUI(state);
  }
});

document.getElementById("btn-ctrlc").addEventListener("click", async () => {
  const state = await postJson("/api/input", {action: "interrupt"});
  updateUI(state);
  screenFocus.focus();
});

document.getElementById("btn-ctrld").addEventListener("click", async () => {
  const state = await postJson("/api/input", {action: "eof"});
  updateUI(state);
  screenFocus.focus();
});

document.getElementById("btn-ctrlw").addEventListener("click", async () => {
  const state = await postJson("/api/input", {action: "key", char: 23, key_code: 0x11, ctrl: true});
  updateUI(state);
  screenFocus.focus();
});

document.getElementById("btn-tab").addEventListener("click", async () => {
  const state = await postJson("/api/input", {action: "key", char: 9, key_code: 0x0F});
  updateUI(state);
  screenFocus.focus();
});

document.getElementById("btn-up").addEventListener("click", async () => {
  const state = await postJson("/api/input", {action: "key", char: 0, key_code: 0xC8});
  updateUI(state);
  screenFocus.focus();
});

document.getElementById("btn-down").addEventListener("click", async () => {
  const state = await postJson("/api/input", {action: "key", char: 0, key_code: 0xD0});
  updateUI(state);
  screenFocus.focus();
});

document.getElementById("btn-paste").addEventListener("click", async () => {
  let pasted = "";
  try {
    if (navigator.clipboard && navigator.clipboard.readText) {
      pasted = await navigator.clipboard.readText();
    }
  } catch (err) {}
  if (!pasted) {
    pasted = window.prompt("Paste text to send as OpenComputers 'clipboard' signal:", "") || "";
  }
  if (pasted) {
    const state = await postJson("/api/input", {action: "clipboard", text: pasted});
    updateUI(state);
  }
  screenFocus.focus();
});

document.getElementById("btn-clear").addEventListener("click", async () => {
  const state = await postJson("/api/input", {action: "clear"});
  updateUI(state);
  screenFocus.focus();
});

document.getElementById("btn-reboot").addEventListener("click", async () => {
  const state = await postJson("/api/input", {action: "reboot"});
  updateUI(state);
  screenFocus.focus();
});

document.getElementById("btn-attach").addEventListener("click", async () => {
  const ctype = document.getElementById("attach-type").value.trim();
  if (!ctype) return;
  const state = await postJson("/api/input", {action: "attach", component_type: ctype});
  updateUI(state);
});

screenFocus.addEventListener("keydown", async (e) => {
  if (e.key === "Control" || e.key === "Shift" || e.key === "Alt" || e.key === "Meta") {
    return;
  }
  const lower = e.key.length === 1 ? e.key.toLowerCase() : e.key;

  // Let browser native paste fire the `paste` event on Ctrl+V
  if ((e.ctrlKey || e.metaKey) && lower === "v") {
    return;
  }

  e.preventDefault();
  e.stopPropagation();

  if (e.ctrlKey && lower === "c") {
    const state = await postJson("/api/input", {action: "interrupt"});
    updateUI(state);
    return;
  }
  if (e.ctrlKey && lower === "d") {
    const state = await postJson("/api/input", {action: "eof"});
    updateUI(state);
    return;
  }
  if (e.ctrlKey && lower === "l") {
    const state = await postJson("/api/input", {action: "clear"});
    updateUI(state);
    return;
  }

  let ch = 0;
  let kc = KEY_TO_LWJGL[e.key] || KEY_TO_LWJGL[lower] || 0;

  if (e.key === "Enter") { ch = 13; kc = 0x1C; }
  else if (e.key === "Backspace") { ch = 8; kc = 0x0E; }
  else if (e.key === "Tab") { ch = 9; kc = 0x0F; }
  else if (e.key === "Escape") { ch = 27; kc = 0x01; }
  else if (e.key === "Delete") { ch = 127; kc = 0xD3; }
  else if (e.ctrlKey && lower.length === 1 && lower >= "a" && lower <= "z") {
    ch = lower.charCodeAt(0) - 96;
  } else if (e.key.length === 1) {
    ch = e.key.charCodeAt(0);
  } else if (kc === 0) {
    return;
  }

  const state = await postJson("/api/input", {
    action: "key",
    char: ch,
    key_code: kc,
    ctrl: Boolean(e.ctrlKey),
    alt: Boolean(e.altKey),
    shift: Boolean(e.shiftKey),
  });
  updateUI(state);
});

screenFocus.addEventListener("paste", async (e) => {
  e.preventDefault();
  const pasted = (e.clipboardData || window.clipboardData).getData("text");
  if (pasted) {
    const state = await postJson("/api/input", {action: "clipboard", text: pasted});
    updateUI(state);
  }
});

screenEl.addEventListener("mousedown", async (e) => {
  screenFocus.focus();
  const rect = screenEl.getBoundingClientRect();
  const x = Math.max(1, Math.min(currentCols, Math.floor(((e.clientX - rect.left) / Math.max(1, rect.width)) * currentCols) + 1));
  const y = Math.max(1, Math.min(currentRows, Math.floor(((e.clientY - rect.top) / Math.max(1, rect.height)) * currentRows) + 1));
  const btn = e.button === 2 ? 1 : 0;
  const state = await postJson("/api/input", {action: "touch", x, y, button: btn});
  updateUI(state);
});

screenEl.addEventListener("contextmenu", (e) => e.preventDefault());

setInterval(pollState, 150);
pollState();
window.addEventListener("load", () => screenFocus.focus());
</script>
</body>
</html>
"""


def _render_screen_rows_html(env: OCEnvironment) -> str:
    """Render the GPU screen cells into HTML spans for the live web monitor."""
    import html as html_lib

    buf = env.screen.screen_page
    lines: List[str] = []
    for y in range(buf.height):
        row_parts: List[str] = []
        run_fg: Optional[int] = None
        run_bg: Optional[int] = None
        run_chars: List[str] = []
        for x in range(buf.width):
            cell = buf.cells[y][x]
            if cell.fg != run_fg or cell.bg != run_bg:
                if run_chars:
                    escaped = html_lib.escape("".join(run_chars))
                    row_parts.append(
                        f'<span style="color:#{run_fg:06X};background-color:#{run_bg:06X}">{escaped}</span>'
                    )
                run_fg = cell.fg
                run_bg = cell.bg
                run_chars = [cell.char]
            else:
                run_chars.append(cell.char)
        if run_chars and run_fg is not None and run_bg is not None:
            escaped = html_lib.escape("".join(run_chars))
            row_parts.append(
                f'<span style="color:#{run_fg:06X};background-color:#{run_bg:06X}">{escaped}</span>'
            )
        lines.append("".join(row_parts))
    return "\n".join(lines)


class OCInteractiveWebServer:
    """Thread-safe HTTP server exposing the live OpenComputers screen and OpenOS shell."""

    def __init__(
        self,
        env: OCEnvironment,
        host: str = "127.0.0.1",
        port: int = 8080,
    ) -> None:
        self.env = env
        self.host = host
        self.port = int(port)
        self._lock = threading.Lock()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

        if not self.env.sandbox.machine_host._interactive_mode:
            self.env.start_interactive_shell()

    def get_state_dict(self) -> Dict[str, Any]:
        with self._lock:
            self.env.step_interactive_tick(1)
            comps = [
                {"address": addr, "type": comp.component_type}
                for addr, comp in sorted(self.env.bus.components.items(), key=lambda kv: kv[1].component_type)
            ]
            recent_calls = [
                {"tick": r.tick, "type": r.component_type, "method": r.method}
                for r in self.env.bus.call_log[-15:]
            ]
            return {
                "architecture": self.env.config.architecture,
                "jar_version": self.env.jar_version,
                "uptime": self.env.scheduler.uptime(),
                "tick": self.env.scheduler.current_tick,
                "free_memory": self.env.sandbox.free_memory,
                "total_memory": self.env.sandbox.total_memory,
                "width": self.env.screen.width,
                "height": self.env.screen.height,
                "screen_text": self.env.screen.to_text(),
                "screen_rows_html": _render_screen_rows_html(self.env),
                "components": comps,
                "recent_calls": recent_calls,
            }

    def handle_input(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        action = str(payload.get("action", "text"))
        with self._lock:
            if action == "text":
                text = str(payload.get("text", ""))
                press_enter = bool(payload.get("press_enter", True))
                self.env.send_text(text, press_enter=press_enter, step_ticks=12)
            elif action == "key":
                ch = int(payload.get("char", 0))
                kc = payload.get("key_code")
                ctrl = bool(payload.get("ctrl", False))
                alt = bool(payload.get("alt", False))
                shift = bool(payload.get("shift", False))
                self.env.send_key(
                    ch,
                    key_code=int(kc) if kc is not None else None,
                    ctrl=ctrl,
                    alt=alt,
                    shift=shift,
                )
                self.env.step_interactive_tick(6)
            elif action == "clipboard":
                self.env.send_clipboard(str(payload.get("text", "")))
                self.env.step_interactive_tick(6)
            elif action == "touch":
                x = int(payload.get("x", 1))
                y = int(payload.get("y", 1))
                btn = int(payload.get("button", 0))
                self.env.send_touch(x, y, button=btn)
                self.env.step_interactive_tick(4)
            elif action == "interrupt":
                self.env.send_ctrl_c(step_ticks=8)
            elif action == "eof":
                self.env.send_ctrl_d(step_ticks=8)
            elif action == "clear":
                self.env.send_ctrl_l(step_ticks=6)
            elif action == "reboot":
                self.env.send_ctrl_c(step_ticks=4)
                self.env.send_ctrl_d(step_ticks=6)
                self.env.send_text("clear", press_enter=True, step_ticks=8)
            elif action == "attach":
                ctype = str(payload.get("component_type", "me_controller"))
                self.env.attach(ctype)
                self.env.step_interactive_tick(2)
        return self.get_state_dict()

    def start_background(self) -> str:
        parent = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/api/state":
                    body = json.dumps(parent.get_state_dict()).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                body = INTERACTIVE_WEB_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/api/input":
                    length = int(self.headers.get("Content-Length", "0"))
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    payload = json.loads(raw.decode("utf-8"))
                    state = parent.handle_input(payload)
                    body = json.dumps(state).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self.port = int(self._httpd.server_address[1])
        self._running = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return f"http://{self.host}:{self.port}"

    def stop(self) -> None:
        self._running = False
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def run_terminal_tui(env: OCEnvironment, initial_commands: Optional[List[str]] = None) -> int:
    """Run an interactive ANSI terminal session connected to the booted OpenOS `/bin/sh.lua` shell."""
    if not env.sandbox.machine_host._interactive_mode:
        env.start_interactive_shell()

    for cmd in initial_commands or []:
        env.send_text(cmd, press_enter=True, step_ticks=15)

    while not env.sandbox.is_shutdown:
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.write(render_screen_ansi(env.screen, include_border=True) + "\n")
        sys.stdout.write(
            f"[OpenOS {env.config.architecture} | {env.screen.width}x{env.screen.height} | "
            f"Tick {env.scheduler.current_tick} | Free RAM {env.sandbox.free_memory // 1024}KB]\n"
            "Command (':c' = Ctrl+C, ':d' = Ctrl+D, ':q' = Quit): "
        )
        sys.stdout.flush()
        try:
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            env.send_ctrl_c(step_ticks=8)
            continue
        if not line:
            break
        stripped = line.rstrip("\r\n")
        if stripped in (":q", ":quit", ":exit"):
            break
        if stripped in (":c", ":ctrlc", "^C", "\x03"):
            env.send_ctrl_c(step_ticks=8)
            continue
        if stripped in (":d", ":ctrld", "^D", "\x04"):
            env.send_ctrl_d(step_ticks=8)
            continue
        env.send_text(stripped, press_enter=True, step_ticks=15)
    return 0


def launch_interactive_session(
    env: OCEnvironment,
    mode: str = "auto",
    mount_home: Optional[str | Path] = None,
    web_host: str = "127.0.0.1",
    web_port: int = 8080,
    initial_commands: Optional[List[str]] = None,
    max_frames: Optional[int] = None,
    scale: int = 2,
) -> int:
    """Start the interactive OpenOS shell in Window (`pygame`), Web (`http`), or Terminal (`tui`) mode."""
    env.start_interactive_shell(mount_home=mount_home)
    for cmd in initial_commands or []:
        env.send_text(cmd, press_enter=True, step_ticks=15)

    chosen = mode
    if chosen == "auto":
        has_display = bool(
            os.environ.get("DISPLAY")
            or os.environ.get("WAYLAND_DISPLAY")
            or sys.platform in ("darwin", "win32")
        )
        chosen = "window" if has_display else "terminal"

    if chosen == "web":
        srv = OCInteractiveWebServer(env, host=web_host, port=web_port)
        url = srv.start_background()
        print(f"GTNH OpenComputers Interactive Web Terminal running at: {url}")
        print("Press Ctrl+C to stop.")
        try:
            frames = 0
            while not env.sandbox.is_shutdown:
                if max_frames is not None and frames >= max_frames:
                    break
                time.sleep(0.05)
                frames += 1
        except KeyboardInterrupt:
            pass
        finally:
            srv.stop()
        return 0

    if chosen == "terminal" or chosen == "tui":
        return run_terminal_tui(env)

    # Desktop Pygame window mode
    from .screen.window import OCPygameWindow

    win = OCPygameWindow(
        env,
        scale=scale,
        title=f"GTNH OpenComputers Interactive Shell ({env.config.architecture})",
    )
    try:
        win.run_loop(fps=20, max_frames=max_frames)
    finally:
        win.close()
    return 0


def _parse_resolution(res_str: str) -> Tuple[int, int]:
    parts = res_str.lower().replace(",", "x").split("x")
    if len(parts) == 2:
        try:
            return (max(10, min(160, int(parts[0]))), max(5, min(50, int(parts[1]))))
        except ValueError:
            pass
    return (80, 25)


def main_shell(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for `gtnh-oc-shell`."""
    parser = argparse.ArgumentParser(
        prog="gtnh-oc-shell",
        description="Interactive GTNH 2.9 OpenComputers Screen & OpenOS Shell Emulator",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "window", "web", "terminal"],
        default="auto",
        help="Display mode: 'window' (Pygame), 'web' (Browser HTTP UI), or 'terminal' (ANSI TUI)",
    )
    parser.add_argument("--web", action="store_true", help="Launch interactive Browser Web UI at http://127.0.0.1:8080")
    parser.add_argument("--terminal", "--tui", dest="terminal", action="store_true", help="Launch interactive ANSI TUI in terminal")
    parser.add_argument("--window", action="store_true", help="Launch interactive Pygame desktop window")
    parser.add_argument("--host-addr", default="127.0.0.1", help="Bind address for --web mode (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port for --web mode (default: 8080)")
    parser.add_argument("--mount-home", default=None, help="Host directory or script file to mount into OpenOS /home")
    parser.add_argument("--lua-version", default="5.2", choices=["5.2", "5.3"], help="Lua architecture (default: 5.2)")
    parser.add_argument("--jar-version", default="1.12.64-GTNH", help="OpenComputers GTNH JAR version")
    parser.add_argument("--cpu-tier", type=int, default=3, choices=[1, 2, 3], help="CPU tier (1..3)")
    parser.add_argument("--ram-tier", type=int, default=6, choices=[1, 2, 3, 4, 5, 6], help="RAM tier (1..6)")
    parser.add_argument(
        "--resolution",
        default="80x25",
        help="Initial screen resolution WxH (default: 80x25; max Tier 3: 160x50)",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=2,
        help="Pixel scale factor for --window mode (default: 2; auto-fits within monitor)",
    )
    parser.add_argument("--attach", action="append", default=[], help="Attach GTNH component(s), e.g. --attach me_controller --attach gt_machine")
    parser.add_argument("-c", "--command", action="append", default=[], help="Initial shell command(s) to type on boot")

    args = parser.parse_args(argv)
    mode = args.mode
    if args.web:
        mode = "web"
    elif args.terminal:
        mode = "terminal"
    elif args.window:
        mode = "window"

    res_w, res_h = _parse_resolution(args.resolution)
    env = OCEnvironment(
        screen_width=res_w,
        screen_height=res_h,
        jar_version=args.jar_version,
        lua_version=args.lua_version,
        cpu_tier=args.cpu_tier,
        ram_tier=args.ram_tier,
    )
    for ctype in args.attach:
        env.attach(ctype)

    return launch_interactive_session(
        env=env,
        mode=mode,
        mount_home=args.mount_home,
        web_host=args.host_addr,
        web_port=args.port,
        initial_commands=args.command,
        scale=args.scale,
    )


if __name__ == "__main__":
    sys.exit(main_shell())

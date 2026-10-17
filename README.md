# GTNH 2.9 OpenComputers Lua Testing Framework (`gtnh-oc-tester`)

A deterministic Python and Pure-Lua testing, simulation, GPU screen emulation, interactive OpenOS shell (`gtnh-oc-shell`), and execution-DAG visualization framework for **GregTech: New Horizons (GTNH 2.9)** OpenComputers scripts.

## Installation

```bash
# Base headless installation (Lupa 2.8+, Pillow, Graphviz, pytest)
pip install "gtnh-oc-tester @ git+https://github.com/tjmeltesen/gtnh-oc-tester.git"

# With optional desktop Pygame screen viewer ([window] extra)
pip install "gtnh-oc-tester[window] @ git+https://github.com/tjmeltesen/gtnh-oc-tester.git"

# Editable local install for contributors
pip install -e ".[window]"
```

## Live Interactive OpenOS Screen & Shell (`gtnh-oc-shell`)

You can boot a live OpenComputers machine (`machine.lua` -> `bios.lua` -> OpenOS `/init.lua` -> `/bin/sh.lua`) to see the running OpenComputers screen, type shell commands (`ls`, `lua`, `edit`, `/home/myscript.lua`), paste via clipboard, and click/touch the screen in real time:

```bash
# 1. Desktop Pygame Window (default when DISPLAY is available)
gtnh-oc-shell --window --mount-home ./my_oc_scripts --attach me_controller --attach gt_machine

# 2. Browser / Web UI at http://127.0.0.1:8080 (works locally or in headless Cloud VMs)
gtnh-oc-shell --web --port 8080 --mount-home ./my_oc_scripts

# 3. Terminal 24-bit ANSI TUI directly in your console
gtnh-oc-shell --terminal --mount-home ./my_oc_scripts

# Or via gtnh-oc-test:
gtnh-oc-test --interactive --mount-home ./my_oc_scripts
```

## Features

- **1:1 GTNH 2.9 OpenComputers Kernel & Boot Chain**:
  - Executes the authentic OpenComputers boot sequence (`machine.lua` kernel sandbox + `bios.lua` EEPROM bootstrap + OpenOS `/init.lua` and all 28 OpenOS libraries) extracted from `OpenComputers-1.12.64-GTNH.jar` / `OpenComputers-1.12.62-GTNH.jar`.
  - Defaults to **Lua 5.2** (matching GTNH `OpenComputers.cfg` where `defaultLua53=false` and `forceLuaJ=false`) with **Lua 5.3** selectable (`--lua-version 5.2` or `--lua-version 5.3`) via `lupa>=2.8` multi-runtime bindings (`lupa.lua52` / `lupa.lua53`).
  - Hardened `LuaRuntime(register_eval=False, register_builtins=False, attribute_filter=...)` sandbox with zero host callables or bridges exposed in `_G` or `_ENV`.
- **Authentic OpenComputers Hardware Limits**:
  - **5.0s Wall-Clock Yield Timeout**: Enforces non-yielding CPU execution limits (`too long without yielding`) calibrated against `time.perf_counter()` elapsed wall-clock time (`timeout=5.0`s from `OpenComputers.cfg`), allowing legitimate heavy pure-Lua loops under 5.0s while halting infinite loops.
  - **CPU Call Budgets & Tiers (Enabled by Default)**: Enforces Tier 1 (`0.5/tick`), Tier 2 (`1.0/tick`), and Tier 3 (`1.5/tick`) direct/indirect component call budgets per tick with synchronous call yields (opt out via `enforce_call_budget=False` or `--no-call-budget`).
  - **RAM Tiers (1..6) with OpenOS Kernel Accounting**: Counts OpenOS kernel and `/boot/*.lua` memory footprint against the configured RAM tier (`192`, `256`, `384`, `512`, `768`, `1024` KB via `--ram-tier 1..6`), scaled by `ramScaleFor64Bit=1.8` from `OpenComputers.cfg`.
  - **Configurable Signal Queue & 4096B EEPROM**: Bounded signal queue read from `OCMachineConfig` (`1024` in GTNH `OpenComputers.cfg`, `256` in upstream `application.conf`) and 4096-byte EEPROM code + 256-byte data storage (`component.eeprom`).
  - **Timer & Listener Error Surfacing**: Hooks `event.onError` so errors inside `event.timer` and `event.listen` callbacks are written to `/tmp/event.log`, emitted to `stderr`, and recorded in `env.event_errors` (with optional `raise_on_event_error=True`).

## Component Support Matrix (Stateful Simulators vs. Schema-Backed Auto-Mocks)

All **165 GTNH 2.9 component types** (across `computer`, `robot`, and `tablet` hosts) are available on `ComponentBus` and validated against the 190 in-game proxy dumps:

| Category | Component Types | Simulation Level | Stateful Capabilities |
| :--- | :--- | :--- | :--- |
| **Vanilla OpenComputers** | `filesystem`, `eeprom`, `computer`, `gpu`, `screen`, `keyboard`, `modem`, `internet`, `data`, `drive`, `sound` | **Full Stateful Simulator** | Real VFS handles/quotas, 4096B/256B EEPROM, 1/4/8-bit GPU + VRAM pages + `bitblt`, virtual modem packet routing on ports, zlib/hash/base64 `data` card, raw sector `drive`, 8-channel `sound` card. |
| **Applied Energistics 2 & AE2FC** | `me_controller`, `me_interface`, `fluid_interface`, `upgrade_me`, `level_maintainer`, `oc_pattern_editor`, `me_exportbus`, `me_importbus`, `me_storagebus`, `fluid_*`, `essentia_*` | **Full Stateful Simulator** | Shared `MENetworkState` items/fluids/essentia, `allItems()` iterator, `getCraftables()` + `AECraftable.request()`, `AECraftingJob` lifecycle, `getCpus()` with `AECpu` userdata (`isBusy()`, `isActive()`, `finalOutput()`, `activeItems()`, `pendingItems()`, `storedItems()`, `cancel()`), interface slot/pattern storage, `network_*_changed` signals. |
| **GregTech 5u, Multiblocks & LSC** | `gt_machine`, `gt_batterybuffer`, `gt_energycontainer`, `bec_storage`, `bec_diode`, `bec_io_node` | **Full Stateful Simulator** | Live EU/steam storage, input/output averages, Lapotronic Supercapacitor (`LSC`) passive loss & wireless EU, dynamic `getSensorInformation()`, multiblock recipe progress & power consumption, circuit configuration,hatch parameters, battery slot charges. |
| **Inventories, Tanks & Database** | `transposer`, `inventory_controller`, `tank_controller`, `database` | **Full Stateful Simulator** | 6-sided `WorldInventoryGrid` item slots & fluid tanks, conservation of mass on `transferItem` / `transferFluid` / `swap`, callable `StackSlot` (`ItemStackArrayValue`) iterator userdata, 81-slot `database` hashes. |
| **Redstone** | `redstone` | **Full Stateful Simulator** | 6-sided vanilla (0..15), 16-color bundled (`colors.*`), comparator, and wireless redstone with `redstone_changed` signals. |
| **All Other GTNH 2.9 Components (130+ types)** | `reactor_chamber`, `blood_altar`, `thaumonomicon`, `computronics` (`chat_box`, `radar`, `tape_drive`, `camera`, `colorful_lamp`), `hologram`, `geolyzer`, `navigation`, `tractor_beam`, etc. | **Schema-Backed Auto-Mock** | Exact method tables, docstrings, `direct`/`limit` call budgets, and type-safe default returns synthesized from GTNH 2.9 in-game dumps; customizable via `.mock_method(name, fn)` and `.set_return(name, val)`. |

## Note on `os.clock()` vs. In-Game CPU Time

In `gtnh-oc-tester`, `os.clock()` inside the Lua sandbox is mapped to `computer.uptime()` (deterministic virtual server uptime advancing at `0.05`s per 20-TPS tick). In-game OpenComputers maps `os.clock()` to cumulative CPU thread execution time, whereas `computer.uptime()` tracks world ticks. Mapping `os.clock()` to virtual uptime ensures deterministic, reproducible timing assertions across CI runners regardless of host CPU speed, while the `"too long without yielding"` watchdog uses real wall-clock elapsed time (`time.perf_counter()`) per un-yielded coroutine slice.

## Quick Start

```bash
# Run full Python + Pure-Lua test suites (defaults to Lua 5.2) and export DAGs + screen snapshots
gtnh-oc-test --dag-dir ./artifacts

# Run with Lua 5.3, interactive Pygame viewer, and specific hardware tiers
gtnh-oc-test --window --lua-version 5.3 --jar-version 1.12.64-GTNH --cpu-tier 3 --ram-tier 6

# Opt out of per-tick component call budget if benchmarking raw throughput
gtnh-oc-test --no-call-budget

# Run via pytest directly with OpenComputers flags
pytest --oc-lua-version 5.2 --oc-window --oc-dag-dir ./artifacts
```

# GTNH 2.9 OpenComputers Lua Testing Framework (`gtnh-oc-tester`)

A deterministic Python and Pure-Lua testing, simulation, GPU screen emulation, interactive Pygame viewer, and execution-DAG visualization framework for **GregTech: New Horizons (GTNH 2.9)** OpenComputers scripts.

## Features

- **1:1 GTNH 2.9 OpenComputers Kernel & Boot Chain**:
  - Executes the authentic OpenComputers boot sequence (`machine.lua` kernel sandbox + `bios.lua` EEPROM bootstrap + OpenOS `/init.lua` and all 28 OpenOS libraries) extracted from `OpenComputers-1.12.64-GTNH.jar` / `OpenComputers-1.12.62-GTNH.jar`.
  - Supports both **Lua 5.3** and **Lua 5.2** CPU architectures (`--lua-version 5.3` or `--lua-version 5.2`) via `lupa` multi-runtime bindings (`lupa.lua53` / `lupa.lua52`).
- **Authentic OpenComputers Hardware Limits**:
  - **5.0s Yield Timeout**: Enforces non-yielding CPU execution limits (`too long without yielding`) configurable via `OpenComputers.cfg` (`--oc-config`).
  - **CPU Call Budgets & Tiers**: Emulates Tier 1 (`--cpu-tier 1`), Tier 2 (`--cpu-tier 2`), and Tier 3 (`--cpu-tier 3`) direct/indirect component call budgets per tick and synchronized call yields.
  - **RAM Tiers (1..6)**: Configurable memory limits across all 6 OpenComputers RAM levels (`192`, `256`, `384`, `512`, `768`, `1024` KB via `--ram-tier 1..6`).
  - **1024 Signal Queue & 4096B EEPROM**: Bounded 1024-entry event/signal queue (`computer.pushSignal` / `computer.pullSignal`) and hardware-accurate 4096-byte EEPROM code + 256-byte data storage (`component.eeprom`).
- **Unified OC + GTNH 2.9 Component Bus**:
  - Bundles all **190 in-game component proxy dumps** (`computer`, `robot`, `tablet`), **165 component definitions**, **19 driver abstracts**, **28 OpenOS libraries**, and **55 userdata types** from [`Navatusein/GTNH-OC-Lua-Documentation`](https://github.com/Navatusein/GTNH-OC-Lua-Documentation) alongside native OpenComputers component drivers (`filesystem`, `eeprom`, `gpu`, `screen`, `keyboard`, `computer`, `internet`, `data`, `modem`, `tunnel`, `redstone`, `robot`, `transposer`, `Inventory`, `Tank`, ` geolyzer`, `database`).
  - **AE2 & AE2FC**: Shared ME network across `me_controller`, `me_interface`, `fluid_interface`, `upgrade_me`, `level_maintainer`, and `oc_pattern_editor` with `allItems()`, `AECraftable.request()`, `AECraftingJob` lifecycle tracking, and `network_*_changed` events.
  - **GregTech Machines & LSC**: Stateful `gt_machine`, `gt_batterybuffer`, `gt_energycontainer`, and Bartworks `bec_*` with EU/steam storage, work progress, sensor info strings, circuit configuration, and multiblock parameters.
  - **Inventories, Tanks & Transposer**: World-grid inventory/tank slots shared across `transposer`, `inventory_controller`, `tank_controller`, and `database`, returning callable `StackSlot` (`ItemStackArrayValue`) userdata iterators (`getAll()`, `count()`, `reset()`, `__call`).
  - **Redstone**: Vanilla, bundled (`colors.*`), comparator, and wireless redstone with `redstone_changed` events.
- **GPU & Screen 2D Buffer Emulator + Interactive Pygame Window (`--window`)**:
  - Supports Tier 1 (`50x16`, 1-bit), Tier 2 (`80x25`, 4-bit 16-color palette), and Tier 3 (`160x50`, 8-bit 256-color palette with 16 user-settable + 240 fixed cube colors), dynamic `gpu.setResolution(w, h)` resizing, and offscreen VRAM buffers (`allocateBuffer`, `bitblt`).
  - **`OCPygameWindow` (`--window` / `--oc-window`)**: Live in-process Pygame viewer rendering `8x16` narrow and `16x16` wide `font.hex` glyphs with full keyboard (`key_down`, `key_up` via LWJGL2 keycodes) and mouse/touch (`touch`, `drag`, `drop`, `scroll`) signal injection, plus headless (`SDL_VIDEODRIVER=dummy`) support for CI and `pytest`.
  - Exports snapshots to plain text, ANSI, HTML, and pixel-accurate `font.hex` PNG images.
- **Execution Tracer & Visual DAG Generator**:
  - Captures Lua function calls (`debug.sethook`), component proxy invocations, state mutations, and `event.pull` wakeups.
  - Automatically collapses polling loops and exports to **Mermaid**, **Graphviz DOT / PNG / SVG**, and an **Interactive HTML Trace & DAG Viewer**.

## Quick Start

```bash
pip install -e .

# Run full Python + Pure-Lua test suites and export DAGs + screen snapshots
gtnh-oc-test --dag-dir ./artifacts

# Run with interactive Pygame viewer, Lua 5.2 or 5.3, and specific hardware tiers
gtnh-oc-test --window --lua-version 5.3 --jar-version 1.12.64-GTNH --cpu-tier 3 --ram-tier 6

# Run via pytest directly with OpenComputers flags
pytest --oc-lua-version 5.2 --oc-window --oc-dag-dir ./artifacts
```

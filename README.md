# GTNH 2.9 OpenComputers Lua Testing Framework (`gtnh-oc-tester`)

A deterministic Python and Pure-Lua testing, simulation, GPU screen emulation, and execution-DAG visualization framework for **GregTech: New Horizons (GTNH 2.9)** OpenComputers scripts.

## Features

- **Verified GTNH 2.9 Specification Registry**:
  - Bundles all **190 in-game component proxy dumps** (`computer`, `robot`, `tablet`), **165 component definitions**, **19 driver abstracts**, **28 OpenOS libraries**, and **55 userdata types** from [`Navatusein/GTNH-OC-Lua-Documentation`](https://github.com/Navatusein/GTNH-OC-Lua-Documentation).
  - Supports loading `OpenComputers-1.12.62-GTNH.jar` via `--oc-jar` or `OC_JAR_PATH` (with bundled OpenOS and `font.hex` assets included out of the box).
- **Isolated `lupa` OpenComputers Sandbox**:
  - Deterministic 20-TPS virtual tick clock (`computer.uptime()`, `os.sleep()`, `event.pull()`, `event.timer()`).
  - In-memory Virtual Filesystem (`filesystem`, `io`, `loadfile`, `dofile`) and all 28 OpenOS libraries.
- **High-Fidelity Stateful GTNH Simulators**:
  - **AE2 & AE2FC**: Shared ME network across `me_controller`, `me_interface`, `fluid_interface`, `upgrade_me`, `level_maintainer`, and `oc_pattern_editor` with `allItems()`, `AECraftable.request()`, `AECraftingJob` lifecycle tracking, and `network_*_changed` events.
  - **GregTech Machines & LSC**: Stateful `gt_machine`, `gt_batterybuffer`, `gt_energycontainer`, and Bartworks `bec_*` with EU/steam storage, work progress, sensor info strings, circuit configuration, and multiblock parameters.
  - **Inventories, Tanks & Transposer**: World-grid inventory/tank slots shared across `transposer`, `inventory_controller`, `tank_controller`, and `database`, returning callable `StackSlot` (`ItemStackArrayValue`) userdata iterators (`getAll()`, `count()`, `reset()`, `__call`).
  - **Redstone**: Vanilla, bundled (`colors.*`), comparator, and wireless redstone with `redstone_changed` events.
  - **Schema-Backed Auto-Mock**: All 165 GTNH 2.9 components work out of the box with host-accurate method sets and `component.doc` strings.
- **GPU & Screen 2D Buffer Emulator**:
  - Supports Tier 1/2/3 resolutions, 24-bit RGB and 16-color palettes, offscreen VRAM buffers (`allocateBuffer`, `bitblt`), and exports to plain text, ANSI, HTML, and pixel-accurate `font.hex` PNG images.
- **Execution Tracer & Visual DAG Generator**:
  - Captures Lua function calls (`debug.sethook`), component proxy invocations, state mutations, and `event.pull` wakeups.
  - Automatically collapses polling loops and exports to **Mermaid**, **Graphviz DOT / PNG / SVG**, and an **Interactive HTML Trace & DAG Viewer**.

## Quick Start

```bash
pip install -e .
gtnh-oc-test --dag-dir ./artifacts
```

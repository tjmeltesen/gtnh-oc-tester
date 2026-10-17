"""Stateful 2D GPU & Screen Buffer Emulator for OpenComputers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import unicodedata

from ..components.auto_mock import SchemaBackedComponent


DEFAULT_PALETTE: Dict[int, int] = {
    0: 0xFFFFFF,
    1: 0xFFCC33,
    2: 0xCC66CC,
    3: 0x6699FF,
    4: 0xFFFF33,
    5: 0x33CC33,
    6: 0xFF6699,
    7: 0x333333,
    8: 0xCCCCCC,
    9: 0x336699,
    10: 0x9933CC,
    11: 0x333399,
    12: 0x663300,
    13: 0x336600,
    14: 0xFF3333,
    15: 0x000000,
}

TIER_SPECS: Dict[int, Tuple[int, int, int]] = {
    1: (50, 16, 1),
    2: (80, 25, 4),
    3: (160, 50, 8),
}


def _char_display_width(ch: str) -> int:
    if not ch:
        return 1
    eaw = unicodedata.east_asian_width(ch[0])
    return 2 if eaw in ("W", "F") else 1


@dataclass
class ScreenCell:
    char: str = " "
    fg: int = 0xFFFFFF
    bg: int = 0x000000
    fg_palette: Optional[int] = None
    bg_palette: Optional[int] = None

    def clone(self) -> "ScreenCell":
        return ScreenCell(
            char=self.char,
            fg=self.fg,
            bg=self.bg,
            fg_palette=self.fg_palette,
            bg_palette=self.bg_palette,
        )


class PageBuffer:
    """Single 2D character/color page (0 = bound screen, >=1 = offscreen VRAM buffer)."""

    def __init__(self, width: int, height: int) -> None:
        self.width = int(width)
        self.height = int(height)
        self.cells: List[List[ScreenCell]] = [
            [ScreenCell() for _ in range(self.width)] for _ in range(self.height)
        ]

    def resize(self, width: int, height: int) -> bool:
        new_w, new_h = int(width), int(height)
        if new_w == self.width and new_h == self.height:
            return False
        new_cells = [[ScreenCell() for _ in range(new_w)] for _ in range(new_h)]
        for y in range(min(self.height, new_h)):
            for x in range(min(self.width, new_w)):
                new_cells[y][x] = self.cells[y][x].clone()
        self.width = new_w
        self.height = new_h
        self.cells = new_cells
        return True

    def get_cell(self, x: int, y: int) -> ScreenCell:
        if 1 <= x <= self.width and 1 <= y <= self.height:
            return self.cells[y - 1][x - 1]
        return ScreenCell()

    def set_cell(
        self,
        x: int,
        y: int,
        char: str,
        fg: int,
        bg: int,
        fg_pal: Optional[int] = None,
        bg_pal: Optional[int] = None,
    ) -> None:
        if 1 <= x <= self.width and 1 <= y <= self.height:
            self.cells[y - 1][x - 1] = ScreenCell(
                char=char[0] if char else " ",
                fg=int(fg) & 0xFFFFFF,
                bg=int(bg) & 0xFFFFFF,
                fg_palette=fg_pal,
                bg_palette=bg_pal,
            )


class GPUScreenEmulator:
    """Emulates OpenComputers GPU + Screen state, VRAM buffers, and `term` output."""

    def __init__(
        self,
        width: int = 80,
        height: int = 25,
        tier: int = 3,
        jar_loader: Optional[Any] = None,
    ) -> None:
        max_w, max_h, max_d = TIER_SPECS.get(int(tier), (160, 50, 8))
        self.tier = int(tier)
        self.max_width = max(int(width), max_w)
        self.max_height = max(int(height), max_h)
        self.max_depth = max_d
        self.depth = max_d
        self.jar_loader = jar_loader

        self.screen_address = "s0000000-0000-4000-8000-000000000001"
        self.palette: Dict[int, int] = dict(DEFAULT_PALETTE)
        self.fg_color: int = 0xFFFFFF
        self.fg_palette: Optional[int] = None
        self.bg_color: int = 0x000000
        self.bg_palette: Optional[int] = None

        self.initial_width = int(width)
        self.initial_height = int(height)
        self.pages: Dict[int, PageBuffer] = {
            0: PageBuffer(int(width), int(height))
        }
        self.active_buffer: int = 0
        self._next_buffer_id: int = 1
        self.total_vram: int = 160 * 50 * 4

        self.viewport_width = int(width)
        self.viewport_height = int(height)
        self.cursor_x: int = 1
        self.cursor_y: int = 1
        self.screen_on: bool = True
        self.precise_mode: bool = False
        self.touch_inverted: bool = False

    @property
    def screen_page(self) -> PageBuffer:
        return self.pages[0]

    @property
    def current_page(self) -> PageBuffer:
        return self.pages.get(self.active_buffer, self.pages[0])

    @property
    def width(self) -> int:
        return self.screen_page.width

    @property
    def height(self) -> int:
        return self.screen_page.height

    def get_resolution(self) -> Tuple[int, int]:
        p = self.current_page
        return (p.width, p.height)

    def set_resolution(self, width: int, height: int) -> bool:
        w = max(1, min(int(width), self.max_width))
        h = max(1, min(int(height), self.max_height))
        changed = self.screen_page.resize(w, h)
        self.viewport_width = w
        self.viewport_height = h
        self.cursor_x = min(self.cursor_x, w)
        self.cursor_y = min(self.cursor_y, h)
        return changed

    def get_cursor(self) -> Tuple[int, int]:
        return (self.cursor_x, self.cursor_y)

    def set_cursor(self, col: int, row: int) -> None:
        self.cursor_x = max(1, int(col))
        self.cursor_y = max(1, int(row))

    def term_clear(self) -> None:
        p = self.screen_page
        self.gpu_fill(1, 1, p.width, p.height, " ")
        self.cursor_x = 1
        self.cursor_y = 1

    def term_clear_line(self) -> None:
        p = self.screen_page
        self.gpu_fill(1, self.cursor_y, p.width, 1, " ")
        self.cursor_x = 1

    def _scroll_up(self, lines: int = 1) -> None:
        p = self.screen_page
        for _ in range(lines):
            p.cells.pop(0)
            p.cells.append(
                [
                    ScreenCell(
                        char=" ",
                        fg=self.fg_color,
                        bg=self.bg_color,
                        fg_palette=self.fg_palette,
                        bg_palette=self.bg_palette,
                    )
                    for _ in range(p.width)
                ]
            )

    def term_write(self, text: str, wrap: bool = True) -> None:
        p = self.screen_page
        for ch in str(text):
            if ch == "\n":
                self.cursor_x = 1
                self.cursor_y += 1
                if self.cursor_y > p.height:
                    self._scroll_up(self.cursor_y - p.height)
                    self.cursor_y = p.height
            elif ch == "\r":
                self.cursor_x = 1
            elif ch == "\t":
                spaces = 4 - ((self.cursor_x - 1) % 4)
                for _ in range(spaces):
                    self.term_write(" ", wrap=wrap)
            else:
                if self.cursor_x > p.width:
                    if wrap:
                        self.cursor_x = 1
                        self.cursor_y += 1
                        if self.cursor_y > p.height:
                            self._scroll_up(1)
                            self.cursor_y = p.height
                    else:
                        continue
                p.set_cell(
                    self.cursor_x,
                    self.cursor_y,
                    ch,
                    self.fg_color,
                    self.bg_color,
                    self.fg_palette,
                    self.bg_palette,
                )
                self.cursor_x += 1

    # GPU operations
    def gpu_set_background(
        self, color: int, is_palette: bool = False
    ) -> Tuple[int, Optional[int]]:
        old_color, old_pal = self.bg_color, self.bg_palette
        if is_palette:
            idx = int(color)
            self.bg_palette = idx
            self.bg_color = self.palette.get(idx, 0x000000)
        else:
            self.bg_palette = None
            self.bg_color = int(color) & 0xFFFFFF
        return (old_color, old_pal)

    def gpu_set_foreground(
        self, color: int, is_palette: bool = False
    ) -> Tuple[int, Optional[int]]:
        old_color, old_pal = self.fg_color, self.fg_palette
        if is_palette:
            idx = int(color)
            self.fg_palette = idx
            self.fg_color = self.palette.get(idx, 0xFFFFFF)
        else:
            self.fg_palette = None
            self.fg_color = int(color) & 0xFFFFFF
        return (old_color, old_pal)

    def gpu_get(self, x: int, y: int) -> Tuple[str, int, int, Optional[int], Optional[int]]:
        cell = self.current_page.get_cell(int(x), int(y))
        return (cell.char, cell.fg, cell.bg, cell.fg_palette, cell.bg_palette)

    def gpu_set(self, x: int, y: int, value: str, vertical: bool = False) -> bool:
        p = self.current_page
        cx, cy = int(x), int(y)
        s = str(value)
        if vertical:
            for i, ch in enumerate(s):
                p.set_cell(
                    cx,
                    cy + i,
                    ch,
                    self.fg_color,
                    self.bg_color,
                    self.fg_palette,
                    self.bg_palette,
                )
        else:
            offset = 0
            for ch in s:
                p.set_cell(
                    cx + offset,
                    cy,
                    ch,
                    self.fg_color,
                    self.bg_color,
                    self.fg_palette,
                    self.bg_palette,
                )
                w = _char_display_width(ch)
                if w == 2 and cx + offset + 1 <= p.width:
                    p.set_cell(
                        cx + offset + 1,
                        cy,
                        " ",
                        self.fg_color,
                        self.bg_color,
                        self.fg_palette,
                        self.bg_palette,
                    )
                offset += 1
        return True

    def gpu_fill(self, x: int, y: int, width: int, height: int, char: str) -> bool:
        p = self.current_page
        fill_ch = str(char)[0] if str(char) else " "
        x0, y0, w, h = int(x), int(y), int(width), int(height)
        for ry in range(y0, y0 + h):
            for rx in range(x0, x0 + w):
                p.set_cell(
                    rx,
                    ry,
                    fill_ch,
                    self.fg_color,
                    self.bg_color,
                    self.fg_palette,
                    self.bg_palette,
                )
        return True

    def gpu_copy(self, x: int, y: int, width: int, height: int, tx: int, ty: int) -> bool:
        p = self.current_page
        x0, y0, w, h, dx, dy = int(x), int(y), int(width), int(height), int(tx), int(ty)
        snapshot: List[List[ScreenCell]] = []
        for ry in range(y0, y0 + h):
            row_snap: List[ScreenCell] = []
            for rx in range(x0, x0 + w):
                row_snap.append(p.get_cell(rx, ry).clone())
            snapshot.append(row_snap)

        for iy in range(h):
            for ix in range(w):
                dst_x = x0 + dx + ix
                dst_y = y0 + dy + iy
                if 1 <= dst_x <= p.width and 1 <= dst_y <= p.height:
                    p.cells[dst_y - 1][dst_x - 1] = snapshot[iy][ix]
        return True

    def allocate_buffer(self, width: Optional[int] = None, height: Optional[int] = None) -> int:
        w = int(width) if width is not None else self.max_width
        h = int(height) if height is not None else self.max_height
        bid = self._next_buffer_id
        self._next_buffer_id += 1
        self.pages[bid] = PageBuffer(w, h)
        return bid

    def free_buffer(self, index: Optional[int] = None) -> bool:
        target = int(index) if index is not None else self.active_buffer
        if target == 0 or target not in self.pages:
            return False
        del self.pages[target]
        if self.active_buffer == target:
            self.active_buffer = 0
        return True

    def free_all_buffers(self) -> None:
        for k in list(self.pages.keys()):
            if k != 0:
                del self.pages[k]
        self.active_buffer = 0

    def bitblt(
        self,
        dst: int = 0,
        dst_x: int = 1,
        dst_y: int = 1,
        width: Optional[int] = None,
        height: Optional[int] = None,
        src: Optional[int] = None,
        src_x: int = 1,
        src_y: int = 1,
    ) -> bool:
        dst_idx = int(dst) if dst is not None else 0
        src_idx = int(src) if src is not None else self.active_buffer
        dst_page = self.pages.get(dst_idx)
        src_page = self.pages.get(src_idx)
        if dst_page is None or src_page is None:
            return False
        dx = int(dst_x) if dst_x is not None else 1
        dy = int(dst_y) if dst_y is not None else 1
        sx = int(src_x) if src_x is not None else 1
        sy = int(src_y) if src_y is not None else 1
        w = int(width) if width is not None else src_page.width
        h = int(height) if height is not None else src_page.height

        snapshot: List[List[ScreenCell]] = []
        for iy in range(h):
            row: List[ScreenCell] = []
            for ix in range(w):
                row.append(src_page.get_cell(sx + ix, sy + iy).clone())
            snapshot.append(row)

        for iy in range(h):
            for ix in range(w):
                tx = dx + ix
                ty = dy + iy
                if 1 <= tx <= dst_page.width and 1 <= ty <= dst_page.height:
                    dst_page.cells[ty - 1][tx - 1] = snapshot[iy][ix]
        return True

    # Convenience rendering methods
    def to_text(self, strip_trailing: bool = True) -> str:
        from .renderers import render_screen_text

        return render_screen_text(self, strip_trailing=strip_trailing)

    def to_ansi(self) -> str:
        from .renderers import render_screen_ansi

        return render_screen_ansi(self)

    def to_html(self, title: str = "OpenComputers Screen") -> str:
        from .renderers import render_screen_html

        return render_screen_html(self, title=title)

    def to_png(self, output_path: str | Path, scale: int = 2) -> Path:
        from .renderers import render_screen_png

        return render_screen_png(self, output_path=output_path, jar_loader=self.jar_loader, scale=scale)


class GPUComponent(SchemaBackedComponent):
    """Emulates `gpu` component bound to a `GPUScreenEmulator`."""

    def __init__(
        self,
        emulator: GPUScreenEmulator,
        address: Optional[str] = None,
        slot: int = 0,
        host: str = "computer",
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
    ) -> None:
        super().__init__(
            component_type="gpu",
            address=address,
            slot=slot,
            host=host,
            registry=registry,
            bus=bus,
        )
        self.emulator = emulator

    def _impl_bind(self, address: str, reset: bool = True) -> Tuple[bool, None]:
        self.emulator.screen_address = str(address)
        if reset:
            self.emulator.set_resolution(self.emulator.width, self.emulator.height)
        return (True, None)

    def _impl_getScreen(self) -> str:
        return self.emulator.screen_address

    def _impl_getBackground(self) -> Tuple[int, bool]:
        if self.emulator.bg_palette is not None:
            return (self.emulator.bg_palette, True)
        return (self.emulator.bg_color, False)

    def _impl_setBackground(self, color: int, is_palette: bool = False) -> Tuple[int, Optional[int]]:
        return self.emulator.gpu_set_background(int(color), bool(is_palette))

    def _impl_getForeground(self) -> Tuple[int, bool]:
        if self.emulator.fg_palette is not None:
            return (self.emulator.fg_palette, True)
        return (self.emulator.fg_color, False)

    def _impl_setForeground(self, color: int, is_palette: bool = False) -> Tuple[int, Optional[int]]:
        return self.emulator.gpu_set_foreground(int(color), bool(is_palette))

    def _impl_getPaletteColor(self, index: int) -> int:
        return self.emulator.palette.get(int(index), 0x000000)

    def _impl_setPaletteColor(self, index: int, value: int) -> int:
        idx = int(index)
        old = self.emulator.palette.get(idx, 0x000000)
        self.emulator.palette[idx] = int(value) & 0xFFFFFF
        return old

    def _impl_maxDepth(self) -> int:
        return self.emulator.max_depth

    def _impl_getDepth(self) -> int:
        return self.emulator.depth

    def _impl_setDepth(self, bit: int) -> str:
        names = {1: "OneBit", 4: "FourBit", 8: "EightBit"}
        old_name = names.get(self.emulator.depth, "EightBit")
        self.emulator.depth = int(bit)
        return old_name

    def _impl_maxResolution(self) -> Tuple[int, int]:
        return (self.emulator.max_width, self.emulator.max_height)

    def _impl_getResolution(self) -> Tuple[int, int]:
        return self.emulator.get_resolution()

    def _impl_setResolution(self, width: int, height: int) -> bool:
        return self.emulator.set_resolution(int(width), int(height))

    def _impl_getViewport(self) -> Tuple[int, int]:
        return (self.emulator.viewport_width, self.emulator.viewport_height)

    def _impl_setViewport(self, width: int, height: int) -> bool:
        w, h = int(width), int(height)
        changed = (w != self.emulator.viewport_width) or (h != self.emulator.viewport_height)
        self.emulator.viewport_width = w
        self.emulator.viewport_height = h
        return changed

    def _impl_get(self, x: int, y: int) -> Tuple[str, int, int, Optional[int], Optional[int]]:
        return self.emulator.gpu_get(int(x), int(y))

    def _impl_set(self, x: int, y: int, value: str, vertical: bool = False) -> bool:
        return self.emulator.gpu_set(int(x), int(y), str(value), bool(vertical))

    def _impl_fill(self, x: int, y: int, width: int, height: int, char: str) -> bool:
        return self.emulator.gpu_fill(int(x), int(y), int(width), int(height), str(char))

    def _impl_copy(self, x: int, y: int, width: int, height: int, tx: int, ty: int) -> bool:
        return self.emulator.gpu_copy(int(x), int(y), int(width), int(height), int(tx), int(ty))

    def _impl_getActiveBuffer(self) -> int:
        return self.emulator.active_buffer

    def _impl_setActiveBuffer(self, index: int) -> Optional[int]:
        idx = int(index)
        if idx in self.emulator.pages:
            old = self.emulator.active_buffer
            self.emulator.active_buffer = idx
            return old
        return None

    def _impl_buffers(self) -> List[int]:
        return sorted(k for k in self.emulator.pages if k != 0)

    def _impl_allocateBuffer(self, width: Optional[int] = None, height: Optional[int] = None) -> int:
        return self.emulator.allocate_buffer(width, height)

    def _impl_freeBuffer(self, index: Optional[int] = None) -> bool:
        return self.emulator.free_buffer(index)

    def _impl_freeAllBuffers(self) -> None:
        self.emulator.free_all_buffers()

    def _impl_totalMemory(self) -> int:
        return self.emulator.total_vram

    def _impl_freeMemory(self) -> int:
        used = sum(p.width * p.height for k, p in self.emulator.pages.items() if k != 0)
        return max(0, self.emulator.total_vram - used)

    def _impl_getBufferSize(self, index: Optional[int] = None) -> Tuple[int, int]:
        idx = int(index) if index is not None else self.emulator.active_buffer
        p = self.emulator.pages.get(idx, self.emulator.screen_page)
        return (p.width, p.height)

    def _impl_bitblt(
        self,
        dst: int = 0,
        dst_x: int = 1,
        dst_y: int = 1,
        width: Optional[int] = None,
        height: Optional[int] = None,
        src: Optional[int] = None,
        src_x: int = 1,
        src_y: int = 1,
    ) -> bool:
        return self.emulator.bitblt(dst, dst_x, dst_y, width, height, src, src_x, src_y)


class ScreenComponent(SchemaBackedComponent):
    """Emulates `screen` component bound to a `GPUScreenEmulator`."""

    def __init__(
        self,
        emulator: GPUScreenEmulator,
        address: Optional[str] = None,
        slot: int = -1,
        host: str = "computer",
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
    ) -> None:
        super().__init__(
            component_type="screen",
            address=address or emulator.screen_address,
            slot=slot,
            host=host,
            registry=registry,
            bus=bus,
        )
        self.emulator = emulator
        self.emulator.screen_address = self.address

    def _impl_isOn(self) -> bool:
        return self.emulator.screen_on

    def _impl_turnOn(self) -> Tuple[bool, bool]:
        was = self.emulator.screen_on
        self.emulator.screen_on = True
        return (not was, True)

    def _impl_turnOff(self) -> Tuple[bool, bool]:
        was = self.emulator.screen_on
        self.emulator.screen_on = False
        return (was, False)

    def _impl_getAspectRatio(self) -> Tuple[int, int]:
        return (1, 1)

    def _impl_getKeyboards(self) -> List[str]:
        if self.bus:
            return [
                addr
                for addr, c in self.bus.components.items()
                if c.component_type == "keyboard"
            ]
        return ["k0000000-0000-4000-8000-000000000001"]

    def _impl_setPrecise(self, enabled: bool) -> bool:
        old = self.emulator.precise_mode
        self.emulator.precise_mode = bool(enabled)
        return old

    def _impl_isPrecise(self) -> bool:
        return self.emulator.precise_mode

    def _impl_setTouchModeInverted(self, enabled: bool) -> bool:
        old = self.emulator.touch_inverted
        self.emulator.touch_inverted = bool(enabled)
        return old

    def _impl_isTouchModeInverted(self) -> bool:
        return self.emulator.touch_inverted

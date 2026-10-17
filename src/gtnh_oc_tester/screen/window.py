"""Interactive and headless Pygame window viewer for OpenComputers GPU & Screen emulation."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import pygame
except ImportError:  # pragma: no cover - optional [window] extra
    pygame = None  # type: ignore[assignment]

from ..specs.jar_loader import OCJarLoader
from .gpu_buffer import DEFAULT_PALETTE, GPUScreenEmulator, ScreenCell
from .renderers import FontHexRenderer


def _build_pygame_to_oc_keycode() -> Dict[int, int]:
    """Build complete mapping of Pygame `K_*` constants to OpenComputers / LWJGL2 key codes."""
    if pygame is None:
        return {}
    mapping: Dict[int, int] = {
        pygame.K_ESCAPE: 0x01,
        pygame.K_1: 0x02,
        pygame.K_2: 0x03,
        pygame.K_3: 0x04,
        pygame.K_4: 0x05,
        pygame.K_5: 0x06,
        pygame.K_6: 0x07,
        pygame.K_7: 0x08,
        pygame.K_8: 0x09,
        pygame.K_9: 0x0A,
        pygame.K_0: 0x0B,
        pygame.K_MINUS: 0x0C,
        pygame.K_EQUALS: 0x0D,
        pygame.K_BACKSPACE: 0x0E,
        pygame.K_TAB: 0x0F,
        pygame.K_q: 0x10,
        pygame.K_w: 0x11,
        pygame.K_e: 0x12,
        pygame.K_r: 0x13,
        pygame.K_t: 0x14,
        pygame.K_y: 0x15,
        pygame.K_u: 0x16,
        pygame.K_i: 0x17,
        pygame.K_o: 0x18,
        pygame.K_p: 0x19,
        pygame.K_LEFTBRACKET: 0x1A,
        pygame.K_RIGHTBRACKET: 0x1B,
        pygame.K_RETURN: 0x1C,
        pygame.K_LCTRL: 0x1D,
        pygame.K_a: 0x1E,
        pygame.K_s: 0x1F,
        pygame.K_d: 0x20,
        pygame.K_f: 0x21,
        pygame.K_g: 0x22,
        pygame.K_h: 0x23,
        pygame.K_j: 0x24,
        pygame.K_k: 0x25,
        pygame.K_l: 0x26,
        pygame.K_SEMICOLON: 0x27,
        pygame.K_QUOTE: 0x28,
        pygame.K_BACKQUOTE: 0x29,
        pygame.K_LSHIFT: 0x2A,
        pygame.K_BACKSLASH: 0x2B,
        pygame.K_z: 0x2C,
        pygame.K_x: 0x2D,
        pygame.K_c: 0x2E,
        pygame.K_v: 0x2F,
        pygame.K_b: 0x30,
        pygame.K_n: 0x31,
        pygame.K_m: 0x32,
        pygame.K_COMMA: 0x33,
        pygame.K_PERIOD: 0x34,
        pygame.K_SLASH: 0x35,
        pygame.K_RSHIFT: 0x36,
        pygame.K_KP_MULTIPLY: 0x37,
        pygame.K_LALT: 0x38,
        pygame.K_SPACE: 0x39,
        pygame.K_CAPSLOCK: 0x3A,
        pygame.K_F1: 0x3B,
        pygame.K_F2: 0x3C,
        pygame.K_F3: 0x3D,
        pygame.K_F4: 0x3E,
        pygame.K_F5: 0x3F,
        pygame.K_F6: 0x40,
        pygame.K_F7: 0x41,
        pygame.K_F8: 0x42,
        pygame.K_F9: 0x43,
        pygame.K_F10: 0x44,
        pygame.K_NUMLOCK: 0x45,
        pygame.K_KP_MINUS: 0x4A,
        pygame.K_KP_PLUS: 0x4E,
        pygame.K_KP_PERIOD: 0x53,
        pygame.K_F11: 0x57,
        pygame.K_F12: 0x58,
        pygame.K_F13: 0x64,
        pygame.K_F14: 0x65,
        pygame.K_F15: 0x66,
        pygame.K_KP_EQUALS: 0x8D,
        pygame.K_CARET: 0x90,
        pygame.K_AT: 0x91,
        pygame.K_COLON: 0x92,
        pygame.K_UNDERSCORE: 0x93,
        pygame.K_KP_ENTER: 0x9C,
        pygame.K_RCTRL: 0x9D,
        pygame.K_KP_DIVIDE: 0xB5,
        pygame.K_RALT: 0xB8,
        pygame.K_PAUSE: 0xC5,
        pygame.K_HOME: 0xC7,
        pygame.K_UP: 0xC8,
        pygame.K_PAGEUP: 0xC9,
        pygame.K_LEFT: 0xCB,
        pygame.K_RIGHT: 0xCD,
        pygame.K_END: 0xCF,
        pygame.K_DOWN: 0xD0,
        pygame.K_PAGEDOWN: 0xD1,
        pygame.K_INSERT: 0xD2,
        pygame.K_DELETE: 0xD3,
    }
    optional_keys = {
        "K_SCROLLLOCK": 0x46,
        "K_SCROLLOCK": 0x46,
        "K_KP0": 0x52,
        "K_KP_0": 0x52,
        "K_KP1": 0x4F,
        "K_KP_1": 0x4F,
        "K_KP2": 0x50,
        "K_KP_2": 0x50,
        "K_KP3": 0x51,
        "K_KP_3": 0x51,
        "K_KP4": 0x4B,
        "K_KP_4": 0x4B,
        "K_KP5": 0x4C,
        "K_KP_5": 0x4C,
        "K_KP6": 0x4D,
        "K_KP_6": 0x4D,
        "K_KP7": 0x47,
        "K_KP_7": 0x47,
        "K_KP8": 0x48,
        "K_KP_8": 0x48,
        "K_KP9": 0x49,
        "K_KP_9": 0x49,
    }
    for attr, code in optional_keys.items():
        if hasattr(pygame, attr):
            mapping[int(getattr(pygame, attr))] = code
    return mapping


PYGAME_TO_OC_KEYCODE: Dict[int, int] = _build_pygame_to_oc_keycode()

_SHIFTED_ASCII: Dict[int, str] = (
    {
        pygame.K_1: "!",
        pygame.K_2: "@",
        pygame.K_3: "#",
        pygame.K_4: "$",
        pygame.K_5: "%",
        pygame.K_6: "^",
        pygame.K_7: "&",
        pygame.K_8: "*",
        pygame.K_9: "(",
        pygame.K_0: ")",
        pygame.K_MINUS: "_",
        pygame.K_EQUALS: "+",
        pygame.K_LEFTBRACKET: "{",
        pygame.K_RIGHTBRACKET: "}",
        pygame.K_BACKSLASH: "|",
        pygame.K_SEMICOLON: ":",
        pygame.K_QUOTE: '"',
        pygame.K_BACKQUOTE: "~",
        pygame.K_COMMA: "<",
        pygame.K_PERIOD: ">",
        pygame.K_SLASH: "?",
    }
    if pygame is not None
    else {}
)

_CONTROL_CHAR_CODES: Dict[int, int] = (
    {
        pygame.K_RETURN: 13,
        pygame.K_KP_ENTER: 13,
        pygame.K_BACKSPACE: 8,
        pygame.K_TAB: 9,
        pygame.K_ESCAPE: 27,
        pygame.K_DELETE: 127,
        pygame.K_SPACE: 32,
    }
    if pygame is not None
    else {}
)


def _build_oc_240_fixed_palette() -> Tuple[int, ...]:
    """OpenComputers 8-bit 240-color fixed RGB cube (6 red x 8 green x 5 blue)."""
    reds = (0x00, 0x33, 0x66, 0x99, 0xCC, 0xFF)
    greens = (0x00, 0x24, 0x49, 0x6D, 0x92, 0xB6, 0xDB, 0xFF)
    blues = (0x00, 0x40, 0x80, 0xC0, 0xFF)
    colors: List[int] = []
    for r in reds:
        for g in greens:
            for b in blues:
                colors.append((r << 16) | (g << 8) | b)
    return tuple(colors)


OC_240_FIXED_PALETTE: Tuple[int, ...] = _build_oc_240_fixed_palette()


def _int_to_rgb(color: int) -> Tuple[int, int, int]:
    c = int(color) & 0xFFFFFF
    return ((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)


def _event_char_code(event: pygame.event.Event) -> int:
    """Resolve OpenComputers integer character code from a Pygame key event."""
    key = int(getattr(event, "key", 0))
    mod = int(getattr(event, "mod", 0))
    ctrl = bool(mod & getattr(pygame, "KMOD_CTRL", 0))

    if ctrl and pygame.K_a <= key <= pygame.K_z:
        return key - pygame.K_a + 1

    uni = getattr(event, "unicode", "")
    if isinstance(uni, str) and len(uni) > 0:
        return ord(uni[0])

    if key in _CONTROL_CHAR_CODES:
        return _CONTROL_CHAR_CODES[key]

    shift = bool(mod & (pygame.KMOD_SHIFT | getattr(pygame, "KMOD_CAPS", 0)))
    if pygame.K_a <= key <= pygame.K_z:
        ch = chr(key)
        return ord(ch.upper() if shift else ch)
    if shift and key in _SHIFTED_ASCII:
        return ord(_SHIFTED_ASCII[key])
    if 0x20 <= key <= 0x7E:
        return key
    return 0


def _read_system_clipboard() -> str:
    """Best-effort cross-platform clipboard read for Ctrl+V in the Pygame window."""
    if pygame is not None and hasattr(pygame, "scrap"):
        try:
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            raw = pygame.scrap.get(pygame.SCRAP_TEXT)
            if raw:
                return raw.decode("utf-8", errors="ignore").rstrip("\x00")
        except Exception:
            pass
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        if text:
            return str(text)
    except Exception:
        pass
    return ""


def _translate_mouse_button(pg_button: int) -> Optional[int]:
    """Translate Pygame mouse button to OpenComputers button (0=left, 1=right)."""
    if pg_button in (0, 1):
        return 0
    if pg_button in (2, 3):
        return 1
    return None


class OCPygameWindow:
    """Pygame viewer and input event bridge for `GPUScreenEmulator` using `font.hex`."""

    CELL_WIDTH = 8
    CELL_HEIGHT = 16

    def __init__(
        self,
        screen: Optional[Any] = None,
        *,
        env: Optional[Any] = None,
        emulator: Optional[GPUScreenEmulator] = None,
        scheduler: Optional[Any] = None,
        jar_loader: Optional[OCJarLoader] = None,
        scale: int = 2,
        auto_fit: Optional[bool] = None,
        resizable: bool = True,
        max_desktop_fraction: float = 0.82,
        headless: bool = False,
        player_name: str = "player",
        keyboard_address: Optional[str] = None,
        screen_address: Optional[str] = None,
        touch_enabled: Optional[bool] = None,
        title: str = "GTNH OpenComputers Screen",
    ) -> None:
        if screen is not None and hasattr(screen, "screen") and hasattr(screen, "scheduler"):
            env = screen
            screen = env.screen

        self.env = env
        resolved_screen = screen or emulator or (env.screen if env is not None else None)
        if resolved_screen is None:
            resolved_screen = GPUScreenEmulator()
        self.screen: GPUScreenEmulator = resolved_screen

        self.scheduler = scheduler or (env.scheduler if env is not None else None)
        self.jar_loader = (
            jar_loader
            or self.screen.jar_loader
            or (env.jar_loader if env is not None else None)
            or OCJarLoader()
        )
        self.font_renderer = FontHexRenderer(jar_loader=self.jar_loader)
        self.scale = max(1, int(scale))
        self.resizable = bool(resizable)
        self.max_desktop_fraction = max(0.3, min(0.98, float(max_desktop_fraction)))
        self.player_name = str(player_name)
        self.title = str(title)
        self._explicit_keyboard_address = keyboard_address
        self._explicit_screen_address = screen_address
        self._explicit_touch_enabled = touch_enabled

        no_display = (
            sys.platform.startswith("linux")
            and not os.environ.get("DISPLAY")
            and not os.environ.get("WAYLAND_DISPLAY")
        )
        self.headless = bool(headless or no_display)
        self.auto_fit = (not self.headless) if auto_fit is None else bool(auto_fit)
        if self.headless:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

        if pygame is None:
            raise ImportError(
                "pygame is required for OCPygameWindow; install with `pip install 'gtnh-oc-tester[window]'`"
            )
        if not pygame.get_init():
            pygame.init()
        if not pygame.display.get_init():
            pygame.display.init()

        self._desktop_size: Tuple[int, int] = self._detect_desktop_size()
        self._surface_size: Tuple[int, int] = (0, 0)
        self._logical_size: Tuple[int, int] = (0, 0)
        self._user_resized_size: Optional[Tuple[int, int]] = None
        self._zoom_factor: float = 1.0
        self._viewport_rect: Tuple[int, int, int, int] = (0, 0, 1, 1)
        self._display_surface: Optional[pygame.Surface] = None
        self._logical_surface: Optional[pygame.Surface] = None
        self._glyph_cache: Dict[Tuple[int, int, int, int, int], pygame.Surface] = {}
        self._pressed_mouse_button: Optional[int] = None
        self._clock = pygame.time.Clock()
        self._ensure_display_surface()

    def _detect_desktop_size(self) -> Tuple[int, int]:
        """Detect the host monitor pixel size before opening the Pygame window."""
        try:
            info = pygame.display.Info()
            w = int(getattr(info, "current_w", 0) or 0)
            h = int(getattr(info, "current_h", 0) or 0)
            if w >= 640 and h >= 480:
                return (w, h)
        except Exception:
            pass
        return (1920, 1080)

    @property
    def cell_pixel_width(self) -> int:
        return self.CELL_WIDTH * self.scale

    @property
    def cell_pixel_height(self) -> int:
        return self.CELL_HEIGHT * self.scale

    @property
    def keyboard_address(self) -> str:
        if self._explicit_keyboard_address:
            return self._explicit_keyboard_address
        if self.env is not None and hasattr(self.env, "keyboard_comp"):
            return str(self.env.keyboard_comp.address)
        return "k0000000-0000-4000-8000-000000000001"

    @property
    def screen_address(self) -> str:
        if self._explicit_screen_address:
            return self._explicit_screen_address
        return str(self.screen.screen_address)

    @property
    def touch_enabled(self) -> bool:
        if self._explicit_touch_enabled is not None:
            return bool(self._explicit_touch_enabled)
        return int(self.screen.max_depth) > 1

    def get_full_palette_color(self, palette_index: int) -> int:
        """Resolve an 8-bit palette index (0..15 user palette, 16..255 fixed 240-color cube)."""
        idx = int(palette_index) & 0xFF
        if idx < 16:
            return int(self.screen.palette.get(idx, DEFAULT_PALETTE.get(idx, 0x000000))) & 0xFFFFFF
        return OC_240_FIXED_PALETTE[idx - 16]

    def resolve_cell_colors(self, cell: ScreenCell) -> Tuple[int, int]:
        """Resolve effective (fg, bg) 24-bit RGB ints respecting screen depth (1-bit, 4-bit, 8-bit) and palette."""
        depth = int(self.screen.depth)
        fg = int(cell.fg) & 0xFFFFFF
        bg = int(cell.bg) & 0xFFFFFF

        if cell.fg_palette is not None:
            fg = self.get_full_palette_color(cell.fg_palette)
        if cell.bg_palette is not None:
            bg = self.get_full_palette_color(cell.bg_palette)

        if depth == 1:
            mono_on = int(self.screen.palette.get(0, 0xFFFFFF)) & 0xFFFFFF
            fg = mono_on if fg != 0x000000 else 0x000000
            bg = mono_on if bg != 0x000000 else 0x000000
        elif depth == 4 and cell.fg_palette is not None:
            fg = int(self.screen.palette.get(int(cell.fg_palette) & 0xF, fg)) & 0xFFFFFF
        if depth == 4 and cell.bg_palette is not None:
            bg = int(self.screen.palette.get(int(cell.bg_palette) & 0xF, bg)) & 0xFFFFFF

        return (fg, bg)

    def _compute_target_window_size(self, logical_w: int, logical_h: int) -> Tuple[int, int]:
        if self._user_resized_size is not None:
            return self._user_resized_size
        scaled_w = max(160, int(round(logical_w * self._zoom_factor)))
        scaled_h = max(100, int(round(logical_h * self._zoom_factor)))
        if not self.auto_fit:
            return (scaled_w, scaled_h)
        desk_w, desk_h = self._desktop_size
        max_w = max(320, int(desk_w * self.max_desktop_fraction))
        max_h = max(240, int(desk_h * self.max_desktop_fraction))
        if scaled_w <= max_w and scaled_h <= max_h:
            return (scaled_w, scaled_h)
        fit_ratio = min(max_w / max(1, scaled_w), max_h / max(1, scaled_h))
        return (
            max(160, int(round(scaled_w * fit_ratio))),
            max(100, int(round(scaled_h * fit_ratio))),
        )

    def _ensure_display_surface(self) -> pygame.Surface:
        page = self.screen.screen_page
        logical_w = max(1, page.width) * self.cell_pixel_width
        logical_h = max(1, page.height) * self.cell_pixel_height
        logical_size = (logical_w, logical_h)

        if self._logical_surface is None or self._logical_size != logical_size:
            if self._logical_size != (0, 0) and self._logical_size != logical_size:
                # Reset manual window size when OpenOS changes GPU resolution (e.g. 160x50 -> 80x25)
                self._user_resized_size = None
            self._logical_size = logical_size
            self._logical_surface = pygame.Surface(logical_size)

        target_size = self._compute_target_window_size(logical_w, logical_h)
        if self._display_surface is None or self._surface_size != target_size:
            self._surface_size = target_size
            flags = pygame.RESIZABLE if (self.resizable and not self.headless) else 0
            self._display_surface = pygame.display.set_mode(target_size, flags)
            pygame.display.set_caption(
                f"{self.title} [{page.width}x{page.height} {self.screen.depth}-bit | Ctrl+C Interrupt | Ctrl+V Paste | Ctrl+-/= Zoom]"
            )
        return self._display_surface

    def set_zoom(self, zoom_factor: float) -> None:
        """Adjust window zoom factor and resize the display window accordingly."""
        self._zoom_factor = max(0.25, min(4.0, float(zoom_factor)))
        self._user_resized_size = None
        self._ensure_display_surface()

    def _get_glyph_surface(
        self,
        cp: int,
        fg_color: int,
        bg_color: int,
        cells_span: int,
    ) -> pygame.Surface:
        key = (cp, fg_color, bg_color, self.scale, cells_span)
        cached = self._glyph_cache.get(key)
        if cached is not None:
            return cached

        glyph = self.font_renderer.get_glyph(cp)
        base_w = self.CELL_WIDTH * cells_span
        base_h = self.CELL_HEIGHT
        surf = pygame.Surface((base_w, base_h))
        fg_rgb = _int_to_rgb(fg_color)
        bg_rgb = _int_to_rgb(bg_color)
        surf.fill(bg_rgb)

        if cp != 32 and glyph:
            if len(glyph) == 32:
                for gy in range(base_h):
                    hi = glyph[gy * 2] if gy * 2 < len(glyph) else 0
                    lo = glyph[gy * 2 + 1] if gy * 2 + 1 < len(glyph) else 0
                    word = (hi << 8) | lo
                    for gx in range(min(16, base_w)):
                        if (word >> (15 - gx)) & 1:
                            surf.set_at((gx, gy), fg_rgb)
            else:
                for gy in range(base_h):
                    row_bits = glyph[gy] if gy < len(glyph) else 0
                    for gx in range(min(8, base_w)):
                        if (row_bits >> (7 - gx)) & 1:
                            surf.set_at((gx, gy), fg_rgb)

        if self.scale > 1:
            surf = pygame.transform.scale(
                surf,
                (base_w * self.scale, base_h * self.scale),
            )

        if len(self._glyph_cache) > 8192:
            self._glyph_cache.clear()
        self._glyph_cache[key] = surf
        return surf

    def render_frame(self) -> pygame.Surface:
        """Render the active screen buffer (`page 0`) onto the Pygame window surface."""
        display_surface = self._ensure_display_surface()
        assert self._logical_surface is not None
        logical_surface = self._logical_surface
        page = self.screen.screen_page

        if not self.screen.screen_on:
            logical_surface.fill((0, 0, 0))
            display_surface.fill((0, 0, 0))
            self._viewport_rect = (0, 0, self._surface_size[0], self._surface_size[1])
            pygame.display.flip()
            return display_surface

        cell_w = self.cell_pixel_width
        cell_h = self.cell_pixel_height

        for ry in range(page.height):
            row = page.cells[ry]
            py = ry * cell_h
            skip_next = False
            for rx in range(page.width):
                if skip_next:
                    skip_next = False
                    continue
                cell = row[rx]
                px = rx * cell_w
                cp = ord(cell.char[0]) if cell.char else 32
                fg_color, bg_color = self.resolve_cell_colors(cell)
                is_wide = self.font_renderer.is_wide_glyph(cp)
                if is_wide and (rx + 1 < page.width):
                    cells_span = 2
                    if row[rx + 1].char in (" ", ""):
                        skip_next = True
                else:
                    cells_span = 1

                tile = self._get_glyph_surface(cp, fg_color, bg_color, cells_span)
                logical_surface.blit(tile, (px, py))

        win_w, win_h = self._surface_size
        log_w, log_h = self._logical_size
        if (win_w, win_h) == (log_w, log_h):
            display_surface.blit(logical_surface, (0, 0))
            self._viewport_rect = (0, 0, log_w, log_h)
        else:
            display_surface.fill((12, 15, 22))
            scale_ratio = min(win_w / max(1, log_w), win_h / max(1, log_h))
            vp_w = max(1, int(round(log_w * scale_ratio)))
            vp_h = max(1, int(round(log_h * scale_ratio)))
            vp_x = (win_w - vp_w) // 2
            vp_y = (win_h - vp_h) // 2
            self._viewport_rect = (vp_x, vp_y, vp_w, vp_h)
            try:
                scaled = pygame.transform.smoothscale(logical_surface, (vp_w, vp_h))
            except Exception:
                scaled = pygame.transform.scale(logical_surface, (vp_w, vp_h))
            display_surface.blit(scaled, (vp_x, vp_y))

        pygame.display.flip()
        return display_surface

    def _emit_signal(self, name: str, *args: Any) -> None:
        if self.env is not None and hasattr(self.env, "push_event"):
            self.env.push_event(name, *args)
        elif self.scheduler is not None and hasattr(self.scheduler, "push_signal"):
            self.scheduler.push_signal(name, *args)

    def pixel_to_cell(self, px: int, py: int) -> Tuple[int | float, int | float]:
        """Convert window pixel coordinates `(px, py)` to 1-indexed OpenComputers screen cell coordinates."""
        page = self.screen.screen_page
        vp_x, vp_y, vp_w, vp_h = self._viewport_rect
        if vp_w <= 1 or vp_h <= 1:
            vp_x, vp_y = 0, 0
            vp_w = max(1, page.width * self.cell_pixel_width)
            vp_h = max(1, page.height * self.cell_pixel_height)

        rel_x = max(0.0, min(float(vp_w) - 0.001, float(px - vp_x)))
        rel_y = max(0.0, min(float(vp_h) - 0.001, float(py - vp_y)))
        norm_x = rel_x / float(vp_w)
        norm_y = rel_y / float(vp_h)

        if self.screen.precise_mode:
            cx = max(1.0, min(float(page.width), norm_x * float(page.width) + 1.0))
            cy = max(1.0, min(float(page.height), norm_y * float(page.height) + 1.0))
            return (round(cx, 3), round(cy, 3))
        cx_i = max(1, min(page.width, int(norm_x * page.width) + 1))
        cy_i = max(1, min(page.height, int(norm_y * page.height) + 1))
        return (cx_i, cy_i)

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Translate a single Pygame event into OpenComputers signals; returns False on `pygame.QUIT`."""
        if event.type == pygame.QUIT:
            return False

        if hasattr(pygame, "VIDEORESIZE") and event.type == pygame.VIDEORESIZE:
            new_w = max(160, int(getattr(event, "w", self._surface_size[0])))
            new_h = max(100, int(getattr(event, "h", self._surface_size[1])))
            self._user_resized_size = (new_w, new_h)
            self._ensure_display_surface()
            return True

        if event.type == pygame.KEYDOWN:
            key = int(getattr(event, "key", 0))
            mod = int(getattr(event, "mod", 0))
            ctrl = bool(mod & getattr(pygame, "KMOD_CTRL", 0))

            # Window zoom hotkeys: Ctrl+- (zoom out), Ctrl+= / Ctrl++ (zoom in), Ctrl+0 (reset fit)
            if ctrl and key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.set_zoom(self._zoom_factor * 0.85)
                return True
            if ctrl and key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                self.set_zoom(self._zoom_factor * 1.15)
                return True
            if ctrl and key == pygame.K_0:
                self.set_zoom(1.0)
                return True

            # Ctrl+V: emit OpenComputers `clipboard` signal if clipboard text is available
            if ctrl and key == pygame.K_v:
                pasted = _read_system_clipboard()
                if pasted:
                    self._emit_signal("clipboard", self.keyboard_address, pasted, self.player_name)
                    return True

            oc_keycode = PYGAME_TO_OC_KEYCODE.get(key, 0)
            char_code = _event_char_code(event)
            self._emit_signal(
                "key_down",
                self.keyboard_address,
                char_code,
                oc_keycode,
                self.player_name,
            )
            # In OpenOS, Ctrl+C (or Ctrl+Alt+C) also triggers `interrupted`
            if ctrl and key == pygame.K_c:
                uptime = self.scheduler.uptime() if self.scheduler and hasattr(self.scheduler, "uptime") else 0.0
                self._emit_signal("interrupted", uptime)
            return True

        if event.type == pygame.KEYUP:
            key = int(getattr(event, "key", 0))
            oc_keycode = PYGAME_TO_OC_KEYCODE.get(key, 0)
            char_code = _event_char_code(event)
            self._emit_signal(
                "key_up",
                self.keyboard_address,
                char_code,
                oc_keycode,
                self.player_name,
            )
            return True

        if not self.touch_enabled:
            return True

        if event.type == pygame.MOUSEBUTTONDOWN:
            raw_btn = int(getattr(event, "button", 1))
            oc_btn = _translate_mouse_button(raw_btn)
            if oc_btn is not None:
                pos = getattr(event, "pos", (0, 0))
                cell_x, cell_y = self.pixel_to_cell(int(pos[0]), int(pos[1]))
                self._pressed_mouse_button = oc_btn
                self._emit_signal(
                    "touch",
                    self.screen_address,
                    cell_x,
                    cell_y,
                    oc_btn,
                    self.player_name,
                )
            return True

        if event.type == pygame.MOUSEMOTION:
            oc_btn = self._pressed_mouse_button
            if oc_btn is None:
                buttons = getattr(event, "buttons", ())
                if isinstance(buttons, (tuple, list)) and len(buttons) >= 1:
                    if buttons[0]:
                        oc_btn = 0
                    elif len(buttons) >= 3 and buttons[2]:
                        oc_btn = 1
                    elif len(buttons) >= 2 and buttons[1]:
                        oc_btn = 1
            if oc_btn is not None:
                pos = getattr(event, "pos", (0, 0))
                cell_x, cell_y = self.pixel_to_cell(int(pos[0]), int(pos[1]))
                self._emit_signal(
                    "drag",
                    self.screen_address,
                    cell_x,
                    cell_y,
                    oc_btn,
                    self.player_name,
                )
            return True

        if event.type == pygame.MOUSEBUTTONUP:
            raw_btn = int(getattr(event, "button", 1))
            oc_btn = _translate_mouse_button(raw_btn)
            if oc_btn is None:
                oc_btn = self._pressed_mouse_button
            self._pressed_mouse_button = None
            if oc_btn is not None:
                pos = getattr(event, "pos", (0, 0))
                cell_x, cell_y = self.pixel_to_cell(int(pos[0]), int(pos[1]))
                self._emit_signal(
                    "drop",
                    self.screen_address,
                    cell_x,
                    cell_y,
                    oc_btn,
                    self.player_name,
                )
            return True

        if event.type == pygame.MOUSEWHEEL:
            pos = getattr(event, "pos", None)
            if pos is None:
                try:
                    pos = pygame.mouse.get_pos()
                except Exception:
                    pos = (0, 0)
            cell_x, cell_y = self.pixel_to_cell(int(pos[0]), int(pos[1]))
            direction = int(getattr(event, "y", 0))
            if direction == 0:
                direction = 1
            self._emit_signal(
                "scroll",
                self.screen_address,
                cell_x,
                cell_y,
                direction,
                self.player_name,
            )
            return True

        return True

    def pump_events(
        self,
        events: Optional[Iterable[pygame.event.Event]] = None,
    ) -> bool:
        """Process queued Pygame events and emit OpenComputers signals; returns False on `pygame.QUIT`."""
        event_list = list(events) if events is not None else pygame.event.get()
        for ev in event_list:
            if not self.handle_event(ev):
                return False
        return True

    def save_screenshot(self, path: str | Path) -> Path:
        """Render the current frame and save it as an image file."""
        surface = self.render_frame()
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(surface, str(out))
        return out

    def run_loop(
        self,
        step_callback: Optional[Callable[[], Any]] = None,
        fps: int = 20,
        max_frames: Optional[int] = None,
    ) -> int:
        """Run the interactive or bounded frame loop at `fps` (default 20 TPS)."""
        frames = 0
        while True:
            if max_frames is not None and frames >= int(max_frames):
                break
            if not self.pump_events():
                break
            if step_callback is not None:
                res = step_callback()
                if res is False:
                    break
            elif (
                self.env is not None
                and hasattr(self.env, "step_interactive_tick")
                and getattr(getattr(getattr(self.env, "sandbox", None), "machine_host", None), "_interactive_mode", False)
            ):
                if not self.env.step_interactive_tick():
                    break
            elif self.env is not None and hasattr(self.env, "advance_ticks"):
                self.env.advance_ticks(1)
            elif self.scheduler is not None and hasattr(self.scheduler, "advance_ticks"):
                self.scheduler.advance_ticks(1)

            self.render_frame()
            frames += 1

            if self.env is not None and getattr(getattr(self.env, "sandbox", None), "is_shutdown", False):
                break
            if fps and fps > 0 and not self.headless:
                self._clock.tick(int(fps))
        return frames

    def close(self) -> None:
        """Close the Pygame display surface."""
        try:
            if pygame.display.get_init():
                pygame.display.quit()
        except Exception:
            pass
        self._display_surface = None
        self._surface_size = (0, 0)

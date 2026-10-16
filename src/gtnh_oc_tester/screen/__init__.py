"""GPU & Screen 2D buffer emulator, Pygame window viewer, and text/ANSI/HTML/PNG snapshot exporters."""

from .gpu_buffer import (
    DEFAULT_PALETTE,
    GPUComponent,
    GPUScreenEmulator,
    PageBuffer,
    ScreenCell,
    ScreenComponent,
    TIER_SPECS,
)
from .renderers import (
    FontHexRenderer,
    render_screen_ansi,
    render_screen_html,
    render_screen_png,
    render_screen_text,
)
from .window import (
    OC_240_FIXED_PALETTE,
    OCPygameWindow,
    PYGAME_TO_OC_KEYCODE,
)

__all__ = [
    "DEFAULT_PALETTE",
    "FontHexRenderer",
    "GPUComponent",
    "GPUScreenEmulator",
    "OC_240_FIXED_PALETTE",
    "OCPygameWindow",
    "PYGAME_TO_OC_KEYCODE",
    "PageBuffer",
    "ScreenCell",
    "ScreenComponent",
    "TIER_SPECS",
    "render_screen_ansi",
    "render_screen_html",
    "render_screen_png",
    "render_screen_text",
]

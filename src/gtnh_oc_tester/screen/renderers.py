"""Exporters for GPUScreenEmulator: Plain text, ANSI terminal, HTML/CSS, and pixel-accurate `font.hex` PNG."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from ..specs.jar_loader import OCJarLoader
from .gpu_buffer import GPUScreenEmulator


def _int_to_rgb(color: int) -> Tuple[int, int, int]:
    c = int(color) & 0xFFFFFF
    return ((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)


def render_screen_text(emulator: GPUScreenEmulator, strip_trailing: bool = True) -> str:
    page = emulator.screen_page
    lines: List[str] = []
    for row in page.cells:
        line = "".join(cell.char for cell in row)
        if strip_trailing:
            line = line.rstrip()
        lines.append(line)
    if strip_trailing:
        while lines and not lines[-1]:
            lines.pop()
    return "\n".join(lines)


def render_screen_ansi(emulator: GPUScreenEmulator) -> str:
    page = emulator.screen_page
    out_lines: List[str] = []
    for row in page.cells:
        parts: List[str] = []
        last_fg: Optional[int] = None
        last_bg: Optional[int] = None
        for cell in row:
            if cell.fg != last_fg or cell.bg != last_bg:
                fr, fg_c, fb = _int_to_rgb(cell.fg)
                br, bg_c, bb = _int_to_rgb(cell.bg)
                parts.append(f"\x1b[38;2;{fr};{fg_c};{fb}m\x1b[48;2;{br};{bg_c};{bb}m")
                last_fg = cell.fg
                last_bg = cell.bg
            parts.append(cell.char)
        parts.append("\x1b[0m")
        out_lines.append("".join(parts))
    return "\n".join(out_lines)


def render_screen_html(
    emulator: GPUScreenEmulator,
    title: str = "OpenComputers Screen",
) -> str:
    page = emulator.screen_page
    rows_html: List[str] = []
    for row in page.cells:
        spans: List[str] = []
        cur_fg: Optional[int] = None
        cur_bg: Optional[int] = None
        buf: List[str] = []

        def flush_span() -> None:
            if not buf:
                return
            txt = html.escape("".join(buf))
            fg_hex = f"#{(cur_fg or 0) & 0xFFFFFF:06x}"
            bg_hex = f"#{(cur_bg or 0) & 0xFFFFFF:06x}"
            spans.append(f'<span style="color:{fg_hex};background:{bg_hex}">{txt}</span>')
            buf.clear()

        for cell in row:
            if cell.fg != cur_fg or cell.bg != cur_bg:
                flush_span()
                cur_fg = cell.fg
                cur_bg = cell.bg
            buf.append(cell.char)
        flush_span()
        rows_html.append("<div>" + "".join(spans) + "</div>")

    body_content = "\n".join(rows_html)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{html.escape(title)}</title>
<style>
  body {{
    background: #111318;
    color: #e5e7eb;
    font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 24px;
    margin: 0;
  }}
  .oc-bezel {{
    background: #232730;
    border: 4px solid #3b4252;
    border-radius: 8px;
    padding: 14px;
    box-shadow: 0 12px 32px rgba(0,0,0,0.65);
  }}
  .oc-header {{
    font-size: 12px;
    color: #9ca3af;
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
  }}
  .oc-screen {{
    background: #000000;
    font-size: 14px;
    line-height: 16px;
    letter-spacing: 0px;
    white-space: pre;
    border: 2px solid #0f1116;
  }}
</style>
</head>
<body>
  <div class="oc-bezel">
    <div class="oc-header">
      <span>{html.escape(title)}</span>
      <span>{page.width}x{page.height} ({emulator.depth}-bit)</span>
    </div>
    <div class="oc-screen">
{body_content}
    </div>
  </div>
</body>
</html>
"""


def render_screen_png(
    emulator: GPUScreenEmulator,
    output_path: str | Path,
    jar_loader: Optional[OCJarLoader] = None,
    scale: int = 2,
) -> Path:
    """Render the GPU screen buffer to a pixel-accurate PNG using OpenComputers `font.hex`."""
    loader = jar_loader or OCJarLoader()
    glyphs: Dict[int, bytes] = loader.load_font_hex()
    page = emulator.screen_page

    char_w = 8
    char_h = 16
    bezel = 12
    screen_px_w = page.width * char_w
    screen_px_h = page.height * char_h
    img_w = screen_px_w + bezel * 2
    img_h = screen_px_h + bezel * 2

    img = Image.new("RGB", (img_w, img_h), (28, 32, 40))
    draw = ImageDraw.Draw(img)
    # Outer and inner monitor frame
    draw.rectangle([0, 0, img_w - 1, img_h - 1], outline=(62, 70, 86), width=2)
    draw.rectangle(
        [bezel - 2, bezel - 2, bezel + screen_px_w + 1, bezel + screen_px_h + 1],
        outline=(14, 16, 22),
        fill=(0, 0, 0),
        width=2,
    )

    pixels = img.load()
    assert pixels is not None

    for ry in range(page.height):
        row = page.cells[ry]
        py_base = bezel + ry * char_h
        for rx in range(page.width):
            cell = row[rx]
            px_base = bezel + rx * char_w
            fg_rgb = _int_to_rgb(cell.fg)
            bg_rgb = _int_to_rgb(cell.bg)
            cp = ord(cell.char[0]) if cell.char else 32
            glyph = glyphs.get(cp) or glyphs.get(32)

            if not glyph or (cp == 32 and cell.bg == 0x000000):
                if cell.bg != 0x000000:
                    for gy in range(char_h):
                        for gx in range(char_w):
                            pixels[px_base + gx, py_base + gy] = bg_rgb
                continue

            bytes_per_row = 2 if len(glyph) == 32 else 1
            for gy in range(char_h):
                if bytes_per_row == 1:
                    row_bits = glyph[gy] if gy < len(glyph) else 0
                    for gx in range(char_w):
                        bit_on = (row_bits >> (7 - gx)) & 1
                        pixels[px_base + gx, py_base + gy] = fg_rgb if bit_on else bg_rgb
                else:
                    hi = glyph[gy * 2] if gy * 2 < len(glyph) else 0
                    lo = glyph[gy * 2 + 1] if gy * 2 + 1 < len(glyph) else 0
                    word = (hi << 8) | lo
                    for gx in range(char_w):
                        # Sample 8 columns across the 16-bit glyph or left 8 bits
                        bit_on = ((word >> (15 - gx * 2)) & 1) or ((word >> (14 - gx * 2)) & 1)
                        pixels[px_base + gx, py_base + gy] = fg_rgb if bit_on else bg_rgb

    if scale > 1:
        img = img.resize((img_w * int(scale), img_h * int(scale)), Image.Resampling.NEAREST)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, format="PNG")
    return out

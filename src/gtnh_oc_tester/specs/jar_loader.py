"""Loader and extractor for OpenComputers-1.12.62-GTNH.jar and bundled OpenOS/font.hex assets."""

from __future__ import annotations

import os
from pathlib import Path
import urllib.request
import zipfile
from typing import Dict, List, Optional


DEFAULT_OC_JAR_URL = (
    "https://github.com/GTNewHorizons/OpenComputers/releases/download/"
    "1.12.62-GTNH/OpenComputers-1.12.62-GTNH.jar"
)
DEFAULT_JAR_FILENAME = "OpenComputers-1.12.62-GTNH.jar"


class OCJarLoader:
    """Provides OpenOS standard libraries, boot scripts, and font.hex from OpenComputers-1.12.62-GTNH.jar."""

    def __init__(
        self,
        jar_path: Optional[str | Path] = None,
        auto_download: bool = False,
    ) -> None:
        self.bundled_dir = Path(__file__).resolve().parent / "data" / "oc_assets"
        self.cache_dir = Path.home() / ".cache" / "gtnh-oc-tester"
        self.jar_path: Optional[Path] = self._resolve_jar_path(jar_path, auto_download)
        self._font_cache: Optional[Dict[int, bytes]] = None

    def _resolve_jar_path(
        self,
        explicit_path: Optional[str | Path],
        auto_download: bool,
    ) -> Optional[Path]:
        candidates: List[Path] = []
        if explicit_path:
            candidates.append(Path(str(explicit_path)))
            # Handle Windows paths passed on Linux/WSL if file exists in cache/downloads
            win_str = str(explicit_path).replace("\\", "/")
            if "/" in win_str:
                candidates.append(self.cache_dir / win_str.rsplit("/", 1)[-1])

        env_path = os.environ.get("OC_JAR_PATH")
        if env_path:
            candidates.append(Path(env_path))

        candidates.extend(
            [
                self.cache_dir / DEFAULT_JAR_FILENAME,
                Path("/tmp/oc-jar") / DEFAULT_JAR_FILENAME,
                Path.home() / "Downloads" / DEFAULT_JAR_FILENAME,
            ]
        )

        for cand in candidates:
            try:
                if cand.is_file():
                    return cand
            except OSError:
                continue

        if auto_download:
            return self.download_jar()
        return None

    def download_jar(self, url: str = DEFAULT_OC_JAR_URL) -> Optional[Path]:
        """Download OpenComputers-1.12.62-GTNH.jar into the user cache directory."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            target = self.cache_dir / DEFAULT_JAR_FILENAME
            if not target.exists():
                urllib.request.urlretrieve(url, target)
            self.jar_path = target
            return target
        except Exception:
            return None

    def read_asset_bytes(self, relative_path: str) -> Optional[bytes]:
        """Read an asset under `assets/opencomputers/<relative_path>` from JAR or bundled data."""
        clean_rel = relative_path.lstrip("/")
        if clean_rel.startswith("assets/opencomputers/"):
            clean_rel = clean_rel[len("assets/opencomputers/") :]

        if self.jar_path and self.jar_path.is_file():
            jar_entry = f"assets/opencomputers/{clean_rel}"
            try:
                with zipfile.ZipFile(self.jar_path, "r") as zf:
                    if jar_entry in zf.namelist():
                        return zf.read(jar_entry)
            except Exception:
                pass

        bundled_file = self.bundled_dir / clean_rel
        if bundled_file.is_file():
            return bundled_file.read_bytes()
        return None

    def read_asset_text(self, relative_path: str) -> Optional[str]:
        data = self.read_asset_bytes(relative_path)
        if data is None:
            return None
        return data.decode("utf-8", errors="replace")

    def list_openos_files(self) -> Dict[str, bytes]:
        """Return all files under `loot/openos/` mapped by their OpenOS VFS path (e.g. `/lib/event.lua`)."""
        files: Dict[str, bytes] = {}
        prefix = "assets/opencomputers/loot/openos/"
        if self.jar_path and self.jar_path.is_file():
            try:
                with zipfile.ZipFile(self.jar_path, "r") as zf:
                    for name in zf.namelist():
                        if name.startswith(prefix) and not name.endswith("/"):
                            vfs_path = "/" + name[len(prefix) :]
                            files[vfs_path] = zf.read(name)
                if files:
                    return files
            except Exception:
                pass

        openos_dir = self.bundled_dir / "loot" / "openos"
        if openos_dir.is_dir():
            for file_path in sorted(openos_dir.rglob("*")):
                if file_path.is_file():
                    rel = file_path.relative_to(openos_dir).as_posix()
                    files["/" + rel] = file_path.read_bytes()
        return files

    def load_font_hex(self) -> Dict[int, bytes]:
        """Parse OpenComputers `font.hex` into `{codepoint: glyph_bytes}` (8x16 or 16x16 bitmap rows)."""
        if self._font_cache is not None:
            return self._font_cache

        glyphs: Dict[int, bytes] = {}
        raw = self.read_asset_text("font.hex")
        if raw:
            for line in raw.splitlines():
                line = line.strip()
                if not line or ":" not in line:
                    continue
                cp_hex, bitmap_hex = line.split(":", 1)
                try:
                    cp = int(cp_hex, 16)
                    glyphs[cp] = bytes.fromhex(bitmap_hex.strip())
                except ValueError:
                    continue
        self._font_cache = glyphs
        return glyphs

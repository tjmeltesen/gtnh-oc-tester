"""Loader and extractor for OpenComputers-{version}.jar and bundled OpenOS/font.hex assets."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional
import urllib.request
import zipfile


logger = logging.getLogger(__name__)

SUPPORTED_JAR_VERSIONS = ("1.12.64-GTNH", "1.12.62-GTNH")
DEFAULT_JAR_VERSION = "1.12.64-GTNH"
DEFAULT_OC_JAR_URL = (
    f"https://github.com/GTNewHorizons/OpenComputers/releases/download/"
    f"{DEFAULT_JAR_VERSION}/OpenComputers-{DEFAULT_JAR_VERSION}.jar"
)
DEFAULT_JAR_FILENAME = f"OpenComputers-{DEFAULT_JAR_VERSION}.jar"


def _jar_filename(version: str) -> str:
    return f"OpenComputers-{version}.jar"


def _jar_url(version: str) -> str:
    return (
        f"https://github.com/GTNewHorizons/OpenComputers/releases/download/"
        f"{version}/{_jar_filename(version)}"
    )


class OCJarLoader:
    """Provides OpenOS standard libraries, boot scripts, machine.lua, bios.lua, and font.hex from OpenComputers JAR."""

    def __init__(
        self,
        jar_path: Optional[str | Path] = None,
        auto_download: bool = False,
        jar_version: Optional[str] = None,
    ) -> None:
        self.bundled_dir = Path(__file__).resolve().parent / "data" / "oc_assets"
        self.cache_dir = Path.home() / ".cache" / "gtnh-oc-tester"
        resolved_version = jar_version or os.environ.get("OC_JAR_VERSION") or DEFAULT_JAR_VERSION
        self.jar_version: str = str(resolved_version)
        self.jar_path: Optional[Path] = self._resolve_jar_path(jar_path, auto_download)
        self._font_cache: Optional[Dict[int, bytes]] = None

    @staticmethod
    def _validate_jar_file(path: Path) -> None:
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"OpenComputers JAR file does not exist: {path}")
        if not zipfile.is_zipfile(path):
            raise zipfile.BadZipFile(f"OpenComputers JAR is not a valid ZIP/JAR archive: {path}")
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            required = "assets/opencomputers/lua/machine.lua"
            if required not in names:
                raise RuntimeError(
                    f"OpenComputers JAR {path} is missing required asset {required!r}"
                )

    def _resolve_jar_path(
        self,
        explicit_path: Optional[str | Path],
        auto_download: bool,
    ) -> Optional[Path]:
        if explicit_path is not None:
            raw_str = str(explicit_path)
            cand = Path(raw_str)
            if not cand.is_file():
                # Check cache fallback only if a Windows path was passed on Linux
                win_str = raw_str.replace("\\", "/")
                if "\\" in raw_str and "/" in win_str:
                    alt = self.cache_dir / win_str.rsplit("/", 1)[-1]
                    if alt.is_file():
                        cand = alt
            try:
                self._validate_jar_file(cand)
                return cand
            except Exception as exc:
                logger.error("Failed to load explicitly requested OpenComputers JAR %s: %s", explicit_path, exc)
                raise

        candidates: List[Path] = []
        env_path = os.environ.get("OC_JAR_PATH")
        if env_path:
            candidates.append(Path(env_path))

        # First look for the requested jar_version, then fallback to any supported cached version
        version_order = [self.jar_version] + [
            v for v in SUPPORTED_JAR_VERSIONS if v != self.jar_version
        ]
        for ver in version_order:
            fname = _jar_filename(ver)
            candidates.extend(
                [
                    self.cache_dir / fname,
                    Path("/tmp/oc-jar") / fname,
                    Path.home() / "Downloads" / fname,
                ]
            )

        for cand in candidates:
            try:
                if cand.is_file() and zipfile.is_zipfile(cand):
                    return cand
            except OSError as exc:
                logger.debug("Skipping candidate JAR %s: %s", cand, exc)
                continue

        if auto_download:
            return self.download_jar(_jar_url(self.jar_version), version=self.jar_version)
        return None

    def download_jar(
        self,
        url: Optional[str] = None,
        version: Optional[str] = None,
    ) -> Optional[Path]:
        """Download OpenComputers-{version}.jar into the user cache directory."""
        ver = version or self.jar_version
        target_url = url or _jar_url(ver)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            target = self.cache_dir / _jar_filename(ver)
            if not target.exists():
                urllib.request.urlretrieve(target_url, target)
            self._validate_jar_file(target)
            self.jar_path = target
            return target
        except Exception as exc:
            logger.warning("Failed to download OpenComputers JAR from %s: %s", target_url, exc)
            return None

    def read_asset_bytes(self, relative_path: str) -> Optional[bytes]:
        """Read a root-level or `assets/opencomputers/<relative_path>` entry from JAR or bundled data."""
        raw_rel = relative_path.lstrip("/")
        clean_rel = raw_rel
        if clean_rel.startswith("assets/opencomputers/"):
            clean_rel = clean_rel[len("assets/opencomputers/") :]

        if self.jar_path and self.jar_path.is_file():
            try:
                with zipfile.ZipFile(self.jar_path, "r") as zf:
                    names = set(zf.namelist())
                    for entry in (f"assets/opencomputers/{clean_rel}", raw_rel, clean_rel):
                        if entry in names:
                            return zf.read(entry)
            except Exception as exc:
                logger.warning("Error reading asset %r from %s: %s", relative_path, self.jar_path, exc)

        for candidate_rel in (clean_rel, raw_rel):
            bundled_file = self.bundled_dir / candidate_rel
            if bundled_file.is_file():
                return bundled_file.read_bytes()
        return None

    def read_asset_text(self, relative_path: str) -> Optional[str]:
        data = self.read_asset_bytes(relative_path)
        if data is None:
            return None
        return data.decode("utf-8", errors="replace")

    read_bytes = read_asset_bytes
    read_text = read_asset_text

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
            except Exception as exc:
                logger.warning("Error listing OpenOS files from %s: %s", self.jar_path, exc)

        openos_dir = self.bundled_dir / "loot" / "openos"
        if openos_dir.is_dir():
            for file_path in sorted(openos_dir.rglob("*")):
                if file_path.is_file():
                    rel = file_path.relative_to(openos_dir).as_posix()
                    files["/" + rel] = file_path.read_bytes()
        return files

    extract_openos_files = list_openos_files

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

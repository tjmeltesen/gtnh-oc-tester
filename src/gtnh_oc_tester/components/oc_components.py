"""Vanilla OpenComputers component implementations for GTNH 2.9 (`filesystem`, `eeprom`, `computer`, `keyboard`, `modem`, `internet`, `data`, `drive`, `sound`)."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union
import uuid
import zlib

from .auto_mock import SchemaBackedComponent
from .simulators.ae2 import _lua_to_py

if TYPE_CHECKING:
    from ..runtime.vfs import VFSFileHandle, VirtualFileSystem


BUNDLED_BIOS_PATH = Path(__file__).resolve().parent.parent / "specs" / "data" / "oc_assets" / "lua" / "bios.lua"


def _load_default_bios_bytes() -> bytes:
    if BUNDLED_BIOS_PATH.is_file():
        return BUNDLED_BIOS_PATH.read_bytes()
    return b'error("no bios.lua found")'


def _create_default_vfs() -> "VirtualFileSystem":
    try:
        from ..runtime.vfs import VirtualFileSystem as _VFS

        return _VFS()
    except Exception:
        import importlib.util
        import sys

        vfs_path = Path(__file__).resolve().parent.parent / "runtime" / "vfs.py"
        spec = importlib.util.spec_from_file_location("gtnh_oc_tester_vfs_fallback", vfs_path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod.VirtualFileSystem()


class FilesystemComponent(SchemaBackedComponent):
    """Emulates an OpenComputers `filesystem` component backed by a `VirtualFileSystem`."""

    def __init__(
        self,
        component_type: str = "filesystem",
        address: Optional[str] = None,
        slot: int = -1,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
        vfs: Optional["VirtualFileSystem"] = None,
        label: str = "OpenOS",
        readonly: bool = False,
        space_total: int = 4 * 1024 * 1024,
        mount_prefix: str = "/",
    ) -> None:
        super().__init__(
            component_type=component_type,
            address=address,
            slot=slot,
            host=host,
            variant=variant,
            registry=registry,
            bus=bus,
        )
        if vfs is not None:
            self.vfs: VirtualFileSystem = vfs
        else:
            self.vfs = _create_default_vfs()
        self.label: Optional[str] = label
        self.readonly: bool = bool(readonly)
        self.space_total: int = int(space_total)
        self.mount_prefix: str = "/" + mount_prefix.strip("/") if mount_prefix.strip("/") else "/"
        self._handles: Dict[int, VFSFileHandle] = {}
        self._next_handle_id: int = 1
        self.extra_fields["fsnode"] = {}

    def get_exposed_methods(self) -> Set[str]:
        names = super().get_exposed_methods()
        names.add("copy")
        return names

    def get_doc(self, method_name: str) -> Optional[str]:
        doc = super().get_doc(method_name)
        if doc is None and method_name == "copy":
            return "function(from:string, to:string):boolean -- Copies an object from the first specified absolute path in the file system to the second."
        return doc

    def _norm_path(self, path: Any) -> str:
        rel = str(path or "").replace("\\", "/").lstrip("/")
        if self.mount_prefix == "/":
            return "/" + rel if rel else "/"
        return f"{self.mount_prefix}/{rel}" if rel else self.mount_prefix

    def _resolve_handle(self, handle: Any) -> Optional["VFSFileHandle"]:
        if hasattr(handle, "read") and hasattr(handle, "closed"):
            return None if handle.closed else handle
        try:
            hid = int(handle)
        except (TypeError, ValueError):
            return None
        h = self._handles.get(hid)
        if h is None or h.closed:
            return None
        return h

    def open(self, path: str, mode: str = "r") -> Any:
        m = str(mode or "r")
        if self.readonly and any(ch in m for ch in ("w", "a", "+")):
            return (None, "filesystem is readonly")
        norm = self._norm_path(path)
        handle, err = self.vfs.open(norm, m)
        if handle is None:
            return (None, err or str(path))
        hid = self._next_handle_id
        self._next_handle_id += 1
        self._handles[hid] = handle
        return hid

    _impl_open = open

    def read(self, handle: Any, count: float = math.inf) -> Optional[str]:
        h = self._resolve_handle(handle)
        if h is None:
            raise ValueError("bad file descriptor")
        try:
            if count is None or math.isinf(float(count)) or float(count) >= 0x7FFFFFFF:
                read_len = max(1, len(h._buffer) - h.pos)
            else:
                read_len = max(0, int(count))
        except (TypeError, ValueError, OverflowError):
            read_len = max(1, len(h._buffer) - h.pos)
        if h.pos >= len(h._buffer):
            return None
        return h.read(read_len)

    _impl_read = read

    def write(self, handle: Any, value: str) -> bool:
        if self.readonly:
            return False
        h = self._resolve_handle(handle)
        if h is None:
            raise ValueError("bad file descriptor")
        return h.write(value)

    _impl_write = write

    def close(self, handle: Any) -> None:
        if hasattr(handle, "close") and callable(handle.close):
            handle.close()
            return
        try:
            hid = int(handle)
        except (TypeError, ValueError):
            return
        h = self._handles.pop(hid, None)
        if h is not None:
            h.close()

    _impl_close = close

    def seek(self, handle: Any, whence: str = "cur", offset: int = 0) -> int:
        h = self._resolve_handle(handle)
        if h is None:
            raise ValueError("bad file descriptor")
        return h.seek(str(whence or "cur"), int(offset or 0))

    _impl_seek = seek

    def makeDirectory(self, path: str) -> bool:
        if self.readonly:
            return False
        return self.vfs.make_directory(self._norm_path(path))

    _impl_makeDirectory = makeDirectory

    def exists(self, path: str) -> bool:
        return self.vfs.exists(self._norm_path(path))

    _impl_exists = exists

    def isDirectory(self, path: str) -> bool:
        return self.vfs.is_directory(self._norm_path(path))

    _impl_isDirectory = isDirectory

    def rename(self, from_path: str, to_path: str) -> bool:
        if self.readonly:
            return False
        return self.vfs.rename(self._norm_path(from_path), self._norm_path(to_path))

    _impl_rename = rename

    def copy(self, from_path: str, to_path: str) -> bool:
        if self.readonly:
            return False
        return self.vfs.copy(self._norm_path(from_path), self._norm_path(to_path))

    _impl_copy = copy

    def remove(self, path: str) -> bool:
        if self.readonly:
            return False
        return self.vfs.remove(self._norm_path(path))

    _impl_remove = remove

    def lastModified(self, path: str) -> int:
        return int(self.vfs.last_modified(self._norm_path(path)))

    _impl_lastModified = lastModified

    def _compute_node_bytes(self, node: Any) -> int:
        if node is None:
            return 0
        if not node.is_dir:
            return len(node.content)
        return sum(self._compute_node_bytes(child) for child in node.children.values())

    def spaceUsed(self) -> int:
        root_node = self.vfs._get_node(self.mount_prefix)
        return self._compute_node_bytes(root_node)

    _impl_spaceUsed = spaceUsed

    def spaceTotal(self) -> int:
        return int(self.space_total)

    _impl_spaceTotal = spaceTotal

    def isReadOnly(self) -> bool:
        return bool(self.readonly)

    _impl_isReadOnly = isReadOnly

    def list(self, path: str = "/") -> List[str]:
        return list(self.vfs.list_dir(self._norm_path(path)))

    _impl_list = list

    def size(self, path: str) -> int:
        return int(self.vfs.size(self._norm_path(path)))

    _impl_size = size

    def getLabel(self) -> Optional[str]:
        return self.label

    _impl_getLabel = getLabel

    def setLabel(self, value: Optional[str]) -> Optional[str]:
        if self.readonly:
            raise ValueError("filesystem is read-only")
        if value is None:
            self.label = None
        else:
            self.label = str(value)[:32]
        return self.label

    _impl_setLabel = setLabel


class EEPROMComponent(SchemaBackedComponent):
    """Emulates an OpenComputers `eeprom` component."""

    def __init__(
        self,
        component_type: str = "eeprom",
        address: Optional[str] = None,
        slot: int = 9,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
        code: Optional[Union[bytes, str]] = None,
        data: Union[bytes, str] = b"",
        label: str = "LUA BIOS",
        readonly: bool = False,
        max_code_size: int = 4096,
        max_data_size: int = 256,
    ) -> None:
        super().__init__(
            component_type=component_type,
            address=address,
            slot=slot,
            host=host,
            variant=variant,
            registry=registry,
            bus=bus,
        )
        if code is None:
            self.code: bytes = _load_default_bios_bytes()
        elif isinstance(code, str):
            self.code = code.encode("utf-8")
        else:
            self.code = bytes(code)

        if isinstance(data, str):
            self.data: bytes = data.encode("utf-8")
        else:
            self.data = bytes(data)

        self.label: str = str(label)
        self.readonly: bool = bool(readonly)
        self.max_code_size: int = int(max_code_size)
        self.max_data_size: int = int(max_data_size)

    def get(self) -> str:
        return self.code.decode("utf-8", errors="replace")

    _impl_get = get

    def set(self, code: Optional[Union[str, bytes]] = "") -> Any:
        if self.readonly:
            return (None, "storage is readonly")
        if code is None:
            raw = b""
        elif isinstance(code, bytes):
            raw = code
        else:
            raw = str(code).encode("utf-8")
        if len(raw) > self.max_code_size:
            raise ValueError("not enough memory")
        self.code = raw
        return None

    _impl_set = set

    def getLabel(self) -> str:
        return self.label

    _impl_getLabel = getLabel

    def setLabel(self, data: Optional[str] = "") -> Any:
        if self.readonly:
            return (None, "storage is readonly")
        self.label = str(data or "EEPROM")[:24]
        return self.label

    _impl_setLabel = setLabel

    def getSize(self) -> int:
        return int(self.max_code_size)

    _impl_getSize = getSize

    def getDataSize(self) -> int:
        return int(self.max_data_size)

    _impl_getDataSize = getDataSize

    def getData(self) -> str:
        return self.data.decode("utf-8", errors="replace")

    _impl_getData = getData

    def setData(self, data: Optional[Union[str, bytes]] = "") -> Any:
        if data is None:
            raw = b""
        elif isinstance(data, bytes):
            raw = data
        else:
            raw = str(data).encode("utf-8")
        if len(raw) > self.max_data_size:
            raise ValueError("not enough memory")
        self.data = raw
        return None

    _impl_setData = setData

    def getChecksum(self) -> str:
        crc = zlib.crc32(self.code) & 0xFFFFFFFF
        return f"{crc:08x}"

    _impl_getChecksum = getChecksum

    def makeReadonly(self, checksum: str) -> Any:
        if str(checksum) != self.getChecksum():
            return (None, "incorrect checksum")
        self.readonly = True
        return True

    _impl_makeReadonly = makeReadonly


class ComputerComponent(SchemaBackedComponent):
    """Emulates an OpenComputers `computer` component."""

    def __init__(
        self,
        component_type: str = "computer",
        address: Optional[str] = None,
        slot: int = -1,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
        running: bool = True,
    ) -> None:
        super().__init__(
            component_type=component_type,
            address=address,
            slot=slot,
            host=host,
            variant=variant,
            registry=registry,
            bus=bus,
        )
        self.running: bool = bool(running)
        self.beeps: List[Tuple[Any, float]] = []
        self.device_info: Dict[str, Dict[str, str]] = {}
        self.program_locations: Dict[str, str] = {
            "edit": "openos",
            "ls": "openos",
            "mkdir": "openos",
            "cp": "openos",
            "mv": "openos",
            "rm": "openos",
            "cat": "openos",
            "sh": "openos",
            "lua": "openos",
            "reboot": "openos",
            "shutdown": "openos",
        }

    def start(self) -> bool:
        if self.running:
            return False
        self.running = True
        return True

    _impl_start = start

    def stop(self) -> bool:
        if not self.running:
            return False
        self.running = False
        return True

    _impl_stop = stop

    def isRunning(self) -> bool:
        return bool(self.running)

    _impl_isRunning = isRunning

    def beep(self, frequency: Union[int, float, str] = 440, duration: float = 0.1) -> bool:
        self.beeps.append((frequency, float(duration if duration is not None else 0.1)))
        return True

    _impl_beep = beep

    def getDeviceInfo(self) -> Dict[str, Dict[str, str]]:
        if self.device_info:
            return dict(self.device_info)
        info: Dict[str, Dict[str, str]] = {}
        if self.bus is not None:
            for addr, comp in self.bus.components.items():
                info[addr] = {
                    "class": "generic",
                    "description": comp.component_type,
                    "vendor": "MightyPirates GmbH & Co. KG",
                    "product": comp.component_type,
                }
        return info

    _impl_getDeviceInfo = getDeviceInfo

    def getProgramLocations(self) -> List[List[str]]:
        return [[prog, disk] for prog, disk in sorted(self.program_locations.items())]

    _impl_getProgramLocations = getProgramLocations


class KeyboardComponent(SchemaBackedComponent):
    """Emulates an OpenComputers `keyboard` component attachable to a screen."""

    def __init__(
        self,
        component_type: str = "keyboard",
        address: Optional[str] = None,
        slot: int = -1,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
        screen_address: Optional[str] = None,
    ) -> None:
        super().__init__(
            component_type=component_type,
            address=address,
            slot=slot,
            host=host,
            variant=variant,
            registry=registry,
            bus=bus,
        )
        self.screen_address: Optional[str] = screen_address


class ModemComponent(SchemaBackedComponent):
    """Emulates a stateful OpenComputers wired/wireless `modem` component."""

    def __init__(
        self,
        component_type: str = "modem",
        address: Optional[str] = None,
        slot: int = 1,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
        wireless: bool = True,
        wired: bool = True,
        max_packet_size: int = 8192,
        max_strength: float = 400.0,
    ) -> None:
        super().__init__(
            component_type=component_type,
            address=address,
            slot=slot,
            host=host,
            variant=variant,
            registry=registry,
            bus=bus,
        )
        self.wireless: bool = bool(wireless)
        self.wired: bool = bool(wired)
        self.max_packet_size: int = int(max_packet_size)
        self.max_strength: float = float(max_strength)
        self.strength: float = float(max_strength)
        self.open_ports: Set[int] = set()
        self.wake_message: Optional[str] = None
        self.wake_fuzzy: bool = False
        self.sent_messages: List[Tuple[Optional[str], int, Tuple[Any, ...]]] = []

    def get_exposed_methods(self) -> Set[str]:
        names = super().get_exposed_methods()
        names.update({"getStrength", "setStrength"})
        return names

    def open(self, port: int) -> bool:
        p = int(port)
        if p < 1 or p > 65535:
            raise ValueError("invalid port number")
        if p in self.open_ports:
            return False
        self.open_ports.add(p)
        return True

    _impl_open = open

    def close(self, port: Optional[int] = None) -> bool:
        if port is None:
            if not self.open_ports:
                return False
            self.open_ports.clear()
            return True
        p = int(port)
        if p in self.open_ports:
            self.open_ports.remove(p)
            return True
        return False

    _impl_close = close

    def isOpen(self, port: int) -> bool:
        return int(port) in self.open_ports

    _impl_isOpen = isOpen

    def isWireless(self) -> bool:
        return bool(self.wireless)

    _impl_isWireless = isWireless

    def isWired(self) -> bool:
        return bool(self.wired)

    _impl_isWired = isWired

    def maxPacketSize(self) -> int:
        return int(self.max_packet_size)

    _impl_maxPacketSize = maxPacketSize

    def getStrength(self) -> float:
        return float(self.strength)

    _impl_getStrength = getStrength

    def setStrength(self, strength: float) -> float:
        self.strength = max(0.0, min(self.max_strength, float(strength)))
        return float(self.strength)

    _impl_setStrength = setStrength

    def getWakeMessage(self) -> Tuple[Optional[str], bool]:
        return (self.wake_message, self.wake_fuzzy)

    _impl_getWakeMessage = getWakeMessage

    def setWakeMessage(self, message: Optional[str] = None, fuzzy: bool = False) -> Optional[str]:
        old = self.wake_message
        self.wake_message = str(message) if message is not None else None
        self.wake_fuzzy = bool(fuzzy)
        return old

    _impl_setWakeMessage = setWakeMessage

    def generateUUID(self) -> str:
        self.address = str(uuid.uuid4())
        return self.address

    _impl_generateUUID = generateUUID

    def _deliver(self, target_address: Optional[str], port: int, payload: Tuple[Any, ...]) -> bool:
        p = int(port)
        self.sent_messages.append((target_address, p, payload))
        if self.bus is not None:
            for addr, comp in self.bus.components.items():
                if isinstance(comp, ModemComponent) and addr != self.address:
                    if target_address is not None and addr != target_address:
                        continue
                    if p in comp.open_ports and self.bus.scheduler is not None:
                        self.bus.scheduler.push_signal(
                            "modem_message", addr, self.address, p, 0.0, *payload
                        )
        return True

    def send(self, address: str, port: int, *data: Any) -> bool:
        return self._deliver(str(address), int(port), data)

    _impl_send = send

    def broadcast(self, port: int, *data: Any) -> bool:
        return self._deliver(None, int(port), data)

    _impl_broadcast = broadcast


@dataclass
class MockInternetHandle:
    """Userdata handle returned by `internet.request` or `internet.connect`."""

    url_or_address: str
    response_chunks: List[str] = field(default_factory=lambda: ["OK"])
    status_code: int = 200
    status_message: str = "OK"
    headers: Dict[str, List[str]] = field(default_factory=lambda: {"Content-Type": ["text/plain"]})
    closed: bool = False
    _idx: int = 0

    def read(self, count: Optional[int] = None) -> Optional[str]:
        if self.closed or self._idx >= len(self.response_chunks):
            return None
        chunk = self.response_chunks[self._idx]
        self._idx += 1
        return chunk

    def write(self, data: str) -> int:
        if self.closed:
            return 0
        return len(str(data))

    def response(self) -> Tuple[int, str, Dict[str, List[str]]]:
        return (self.status_code, self.status_message, dict(self.headers))

    def finishConnect(self) -> bool:
        return not self.closed

    def close(self) -> None:
        self.closed = True

    def id(self) -> str:
        return self.url_or_address

    def __oc_lua_proxy__(self, sandbox: Any) -> Any:
        factory = sandbox.lua.eval(
            """
            function(py_handle, headers_tbl)
              local h = { type = "userdata" }
              function h.read(n) return py_handle.read(n) end
              function h.write(data) return py_handle.write(data) end
              function h.response() return py_handle.status_code, py_handle.status_message, headers_tbl end
              function h.finishConnect() return py_handle.finishConnect() end
              function h.close() py_handle.close() end
              function h.id() return py_handle.id() end
              return h
            end
            """
        )
        return factory(self, sandbox.python_to_lua(self.headers))


class InternetComponent(SchemaBackedComponent):
    """Emulates a stateful mock OpenComputers `internet` card component."""

    def __init__(
        self,
        component_type: str = "internet",
        address: Optional[str] = None,
        slot: int = 0,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
        http_enabled: bool = True,
        tcp_enabled: bool = True,
    ) -> None:
        super().__init__(
            component_type=component_type,
            address=address,
            slot=slot,
            host=host,
            variant=variant,
            registry=registry,
            bus=bus,
        )
        self.http_enabled: bool = bool(http_enabled)
        self.tcp_enabled: bool = bool(tcp_enabled)
        self.canned_responses: Dict[str, List[str]] = {}
        self.requests_log: List[Tuple[str, Optional[str], Optional[Dict[str, Any]], Optional[str]]] = []
        self.connections_log: List[Tuple[str, Optional[int]]] = []

    def isHttpEnabled(self) -> bool:
        return bool(self.http_enabled)

    _impl_isHttpEnabled = isHttpEnabled

    def isTcpEnabled(self) -> bool:
        return bool(self.tcp_enabled)

    _impl_isTcpEnabled = isTcpEnabled

    def connect(self, address: str, port: Optional[int] = None) -> MockInternetHandle:
        if not self.tcp_enabled:
            raise RuntimeError("tcp connections are unavailable")
        target = f"{address}:{port}" if port is not None else str(address)
        self.connections_log.append((str(address), int(port) if port is not None else None))
        return MockInternetHandle(url_or_address=target, response_chunks=self.canned_responses.get(target, [""]))

    _impl_connect = connect

    def request(
        self,
        url: str,
        post_data: Optional[str] = None,
        headers: Optional[Any] = None,
        method: Optional[str] = None,
    ) -> MockInternetHandle:
        if not self.http_enabled:
            raise RuntimeError("http requests are unavailable")
        hdrs = _lua_to_py(headers, self.bus) if headers is not None else None
        self.requests_log.append((str(url), post_data, hdrs if isinstance(hdrs, dict) else None, method))
        chunks = list(self.canned_responses.get(str(url), ["OK"]))
        return MockInternetHandle(url_or_address=str(url), response_chunks=chunks)

    _impl_request = request


class DataCardComponent(SchemaBackedComponent):
    """Emulates an OpenComputers `data` card component (T1/T2/T3)."""

    def __init__(
        self,
        component_type: str = "data",
        address: Optional[str] = None,
        slot: int = 1,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
        limit: int = 1048576,
    ) -> None:
        super().__init__(
            component_type=component_type,
            address=address,
            slot=slot,
            host=host,
            variant=variant,
            registry=registry,
            bus=bus,
        )
        self.limit: int = int(limit)

    @staticmethod
    def _to_bytes(val: Any) -> bytes:
        if isinstance(val, bytes):
            return val
        return str(val or "").encode("latin-1", errors="replace")

    @staticmethod
    def _from_bytes(raw: bytes) -> str:
        return raw.decode("latin-1")

    def getLimit(self) -> int:
        return int(self.limit)

    _impl_getLimit = getLimit

    def crc32(self, data: Any) -> str:
        crc = zlib.crc32(self._to_bytes(data)) & 0xFFFFFFFF
        return self._from_bytes(crc.to_bytes(4, "big"))

    _impl_crc32 = crc32

    def encode64(self, data: Any) -> str:
        return base64.b64encode(self._to_bytes(data)).decode("ascii")

    _impl_encode64 = encode64

    def decode64(self, data: Any) -> str:
        return self._from_bytes(base64.b64decode(self._to_bytes(data)))

    _impl_decode64 = decode64

    def md5(self, data: Any = "", hmac_key: Optional[Any] = None) -> str:
        raw = self._to_bytes(data)
        if hmac_key is not None:
            digest = hmac.new(self._to_bytes(hmac_key), raw, hashlib.md5).digest()
        else:
            digest = hashlib.md5(raw).digest()
        return self._from_bytes(digest)

    _impl_md5 = md5

    def sha256(self, data: Any = "", hmac_key: Optional[Any] = None) -> str:
        raw = self._to_bytes(data)
        if hmac_key is not None:
            digest = hmac.new(self._to_bytes(hmac_key), raw, hashlib.sha256).digest()
        else:
            digest = hashlib.sha256(raw).digest()
        return self._from_bytes(digest)

    _impl_sha256 = sha256

    def deflate(self, data: Any) -> str:
        return self._from_bytes(zlib.compress(self._to_bytes(data)))

    _impl_deflate = deflate

    def inflate(self, data: Any) -> str:
        return self._from_bytes(zlib.decompress(self._to_bytes(data)))

    _impl_inflate = inflate

    def random(self, length: int) -> str:
        n = max(0, min(self.limit, int(length)))
        return self._from_bytes(os.urandom(n))

    _impl_random = random

    def encrypt(self, data: Any, key: Any, iv: Any) -> str:
        raw = self._to_bytes(data)
        key_bytes = hashlib.sha256(self._to_bytes(key) + self._to_bytes(iv)).digest()
        out = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(raw))
        return self._from_bytes(out)

    _impl_encrypt = encrypt

    def decrypt(self, data: Any, key: Any, iv: Any) -> str:
        return self.encrypt(data, key, iv)

    _impl_decrypt = decrypt


class DriveComponent(SchemaBackedComponent):
    """Emulates an OpenComputers unmanaged `drive` component."""

    def __init__(
        self,
        component_type: str = "drive",
        address: Optional[str] = None,
        slot: int = 6,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
        capacity: int = 1048576,
        sector_size: int = 512,
        platter_count: int = 2,
        label: str = "drive",
    ) -> None:
        super().__init__(
            component_type=component_type,
            address=address,
            slot=slot,
            host=host,
            variant=variant,
            registry=registry,
            bus=bus,
        )
        self.capacity: int = int(capacity)
        self.sector_size: int = int(sector_size)
        self.platter_count: int = int(platter_count)
        self.label: str = str(label)
        self._storage: bytearray = bytearray(self.capacity)

    def getCapacity(self) -> int:
        return int(self.capacity)

    _impl_getCapacity = getCapacity

    def getSectorSize(self) -> int:
        return int(self.sector_size)

    _impl_getSectorSize = getSectorSize

    def getPlatterCount(self) -> int:
        return int(self.platter_count)

    _impl_getPlatterCount = getPlatterCount

    def getLabel(self) -> str:
        return self.label

    _impl_getLabel = getLabel

    def setLabel(self, value: Optional[str] = "") -> str:
        self.label = str(value or "")[:32]
        return self.label

    _impl_setLabel = setLabel

    def readByte(self, offset: int) -> int:
        idx = int(offset) - 1
        if idx < 0 or idx >= len(self._storage):
            raise ValueError("offset out of bounds")
        b = self._storage[idx]
        return b - 256 if b >= 128 else b

    _impl_readByte = readByte

    def writeByte(self, offset: int, value: int) -> None:
        idx = int(offset) - 1
        if idx < 0 or idx >= len(self._storage):
            raise ValueError("offset out of bounds")
        self._storage[idx] = int(value) & 0xFF

    _impl_writeByte = writeByte

    def readSector(self, sector: int) -> str:
        s = int(sector) - 1
        start = s * self.sector_size
        end = start + self.sector_size
        if start < 0 or end > len(self._storage):
            raise ValueError("sector out of bounds")
        return bytes(self._storage[start:end]).decode("latin-1")

    _impl_readSector = readSector

    def writeSector(self, sector: int, value: Union[str, bytes]) -> None:
        s = int(sector) - 1
        start = s * self.sector_size
        end = start + self.sector_size
        if start < 0 or end > len(self._storage):
            raise ValueError("sector out of bounds")
        raw = value if isinstance(value, bytes) else str(value).encode("latin-1", errors="replace")
        padded = (raw[: self.sector_size]).ljust(self.sector_size, b"\x00")
        self._storage[start:end] = padded

    _impl_writeSector = writeSector


class SoundCardComponent(SchemaBackedComponent):
    """Emulates an OpenComputers `sound` card component."""

    def __init__(
        self,
        component_type: str = "sound",
        address: Optional[str] = None,
        slot: int = 1,
        host: str = "computer",
        variant: Optional[str] = None,
        registry: Optional[Any] = None,
        bus: Optional[Any] = None,
    ) -> None:
        super().__init__(
            component_type=component_type,
            address=address,
            slot=slot,
            host=host,
            variant=variant,
            registry=registry,
            bus=bus,
        )
        self.total_volume: float = 1.0
        self.queue: List[Tuple[str, Tuple[Any, ...]]] = []

    def clear(self) -> None:
        self.queue.clear()

    _impl_clear = clear

    def open(self, channel: int) -> None:
        self.queue.append(("open", (int(channel),)))

    _impl_open = open

    def close(self, channel: int) -> None:
        self.queue.append(("close", (int(channel),)))

    _impl_close = close

    def delay(self, duration: int) -> None:
        self.queue.append(("delay", (int(duration),)))

    _impl_delay = delay

    def process(self) -> bool:
        self.queue.clear()
        return True

    _impl_process = process

    def resetAM(self, channel: int) -> None:
        self.queue.append(("resetAM", (int(channel),)))

    _impl_resetAM = resetAM

    def resetEnvelope(self, channel: int) -> None:
        self.queue.append(("resetEnvelope", (int(channel),)))

    _impl_resetEnvelope = resetEnvelope

    def resetFM(self, channel: int) -> None:
        self.queue.append(("resetFM", (int(channel),)))

    _impl_resetFM = resetFM

    def setADSR(
        self,
        channel: int,
        attack: int,
        decay: int,
        attenuation: float,
        release: int,
    ) -> None:
        self.queue.append(
            ("setADSR", (int(channel), int(attack), int(decay), float(attenuation), int(release)))
        )

    _impl_setADSR = setADSR

    def setAM(self, channel: int, mod_index: int) -> None:
        self.queue.append(("setAM", (int(channel), int(mod_index))))

    _impl_setAM = setAM

    def setFM(self, channel: int, mod_index: int, intensity: float) -> None:
        self.queue.append(("setFM", (int(channel), int(mod_index), float(intensity))))

    _impl_setFM = setFM

    def setFrequency(self, channel: int, frequency: float) -> None:
        self.queue.append(("setFrequency", (int(channel), float(frequency))))

    _impl_setFrequency = setFrequency

    def setLFSR(self, channel: int, initial: int, mask: int) -> None:
        self.queue.append(("setLFSR", (int(channel), int(initial), int(mask))))

    _impl_setLFSR = setLFSR

    def setTotalVolume(self, volume: float) -> None:
        self.total_volume = max(0.0, min(1.0, float(volume)))

    _impl_setTotalVolume = setTotalVolume

    def setVolume(self, channel: int, volume: float) -> None:
        self.queue.append(("setVolume", (int(channel), float(volume))))

    _impl_setVolume = setVolume

    def setWave(self, channel: int, wave_type: int) -> None:
        self.queue.append(("setWave", (int(channel), int(wave_type))))

    _impl_setWave = setWave

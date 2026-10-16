"""In-memory Virtual Filesystem (VFS) emulating OpenComputers / OpenOS filesystem and io."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import posixpath
import time
from typing import Dict, List, Optional, Tuple


@dataclass
class VFSNode:
    is_dir: bool
    content: bytes = b""
    last_modified: int = field(default_factory=lambda: int(time.time() * 1000))
    children: Dict[str, "VFSNode"] = field(default_factory=dict)


class VFSFileHandle:
    """File handle supporting both OpenOS `filesystem` component handles and Lua `io.open` semantics."""

    def __init__(self, vfs: "VirtualFileSystem", path: str, mode: str) -> None:
        self.vfs = vfs
        self.path = vfs.canonical(path)
        self.mode = str(mode or "r")
        self.closed = False
        self.pos = 0
        if vfs.read_only and any(ch in self.mode for ch in ("w", "a", "+")):
            raise PermissionError(f"filesystem is readonly: {self.path}")
        node = vfs._get_node(self.path)
        if "w" in self.mode:
            if node is not None and node.is_dir:
                raise IsADirectoryError(f"Is a directory: {self.path}")
            self._buffer = bytearray()
            if not self.vfs._write_bytes(self.path, b""):
                raise OSError(f"cannot open file for writing: {self.path}")
        elif "a" in self.mode:
            if node is not None and node.is_dir:
                raise IsADirectoryError(f"Is a directory: {self.path}")
            existing = node.content if node and not node.is_dir else b""
            self._buffer = bytearray(existing)
            self.pos = len(self._buffer)
            if node is None:
                if not self.vfs._write_bytes(self.path, b""):
                    raise OSError(f"cannot open file for appending: {self.path}")
        else:
            if node is None or node.is_dir:
                raise FileNotFoundError(f"file not found: {self.path}")
            self._buffer = bytearray(node.content)

    def read(self, fmt_or_count: object = "*a") -> Optional[str]:
        if self.closed:
            return None
        if isinstance(fmt_or_count, (int, float)):
            try:
                if math.isinf(float(fmt_or_count)) or float(fmt_or_count) >= len(self._buffer):
                    count = max(1, len(self._buffer) - self.pos)
                else:
                    count = int(fmt_or_count)
            except (ValueError, OverflowError):
                count = max(1, len(self._buffer) - self.pos)
            if count <= 0:
                return "" if self.pos < len(self._buffer) else None
            if self.pos >= len(self._buffer):
                return None
            chunk = self._buffer[self.pos : self.pos + count]
            self.pos += len(chunk)
            return chunk.decode("utf-8", errors="replace")

        fmt = str(fmt_or_count) if fmt_or_count is not None else "*l"
        if fmt.startswith("*"):
            fmt = fmt[1:]
        if fmt.startswith("a"):
            if self.pos >= len(self._buffer):
                return ""
            chunk = self._buffer[self.pos :]
            self.pos = len(self._buffer)
            return chunk.decode("utf-8", errors="replace")
        if fmt.startswith("l") or fmt.startswith("L"):
            if self.pos >= len(self._buffer):
                return None
            nl_idx = self._buffer.find(b"\n", self.pos)
            if nl_idx == -1:
                chunk = self._buffer[self.pos :]
                self.pos = len(self._buffer)
                return chunk.decode("utf-8", errors="replace")
            end_idx = nl_idx + 1 if fmt.startswith("L") else nl_idx
            chunk = self._buffer[self.pos : end_idx]
            self.pos = nl_idx + 1
            return chunk.decode("utf-8", errors="replace").rstrip("\r")
        return None

    def write(self, *values: object) -> bool:
        if self.closed or self.vfs.read_only or (
            "w" not in self.mode and "a" not in self.mode and "+" not in self.mode
        ):
            return False
        new_buf = bytearray(self._buffer)
        pos = self.pos
        for val in values:
            data = val if isinstance(val, bytes) else str(val).encode("utf-8")
            if pos == len(new_buf):
                new_buf.extend(data)
            elif pos > len(new_buf):
                new_buf.extend(b"\x00" * (pos - len(new_buf)))
                new_buf.extend(data)
            else:
                new_buf[pos : pos + len(data)] = data
            pos += len(data)
        if not self.vfs._write_bytes(self.path, bytes(new_buf)):
            return False
        self._buffer = new_buf
        self.pos = pos
        return True

    def seek(self, whence: str = "cur", offset: int = 0) -> int:
        if whence == "set":
            self.pos = max(0, int(offset))
        elif whence == "end":
            self.pos = max(0, len(self._buffer) + int(offset))
        else:
            self.pos = max(0, self.pos + int(offset))
        return self.pos

    def lines(self):
        def _iter():
            return self.read("*l")

        return _iter

    def flush(self) -> bool:
        if not self.closed and ("w" in self.mode or "a" in self.mode or "+" in self.mode):
            return self.vfs._write_bytes(self.path, bytes(self._buffer))
        return True

    def close(self) -> bool:
        if not self.closed:
            self.flush()
            self.closed = True
        return True


class VirtualFileSystem:
    """In-memory hierarchical virtual filesystem for OpenComputers sandboxes."""

    def __init__(
        self,
        initial_files: Optional[Dict[str, bytes | str]] = None,
        max_bytes: int = 4 * 1024 * 1024,
        read_only: bool = False,
        label: Optional[str] = "OpenOS",
    ) -> None:
        self.root = VFSNode(is_dir=True)
        self.root_address = "f8d0e1a2-1111-4000-8000-000000000001"
        self.tmp_address = "f8d0e1a2-2222-4000-8000-000000000002"
        self.cwd = "/home"
        self.max_bytes: int = int(max_bytes)
        self.read_only: bool = bool(read_only)
        self.label: Optional[str] = label
        self._handles: Dict[int, VFSFileHandle] = {}
        self._next_handle_id: int = 1

        self.make_directory("/home")
        self.make_directory("/tmp")
        self.make_directory("/lib")
        self.make_directory("/bin")
        self.make_directory("/etc")
        self.make_directory("/boot")
        self.make_directory("/usr")

        if initial_files:
            was_ro = self.read_only
            self.read_only = False
            for path, content in initial_files.items():
                self.write_file(path, content)
            self.read_only = was_ro

    def canonical(self, path: str) -> str:
        """Normalize a VFS path relative to VFS root `/` (matching OC filesystem component semantics)."""
        s = str(path or "/").replace("\\", "/")
        if not s.startswith("/"):
            s = "/" + s
        norm = posixpath.normpath(s)
        return "/" if norm in (".", "//") else norm

    def segments(self, path: str) -> List[str]:
        canon = self.canonical(path)
        return [seg for seg in canon.split("/") if seg]

    def _get_node(self, path: str) -> Optional[VFSNode]:
        segs = self.segments(path)
        cur = self.root
        for seg in segs:
            if not cur.is_dir or seg not in cur.children:
                return None
            cur = cur.children[seg]
        return cur

    def _compute_node_bytes(self, node: Optional[VFSNode]) -> int:
        if node is None:
            return 0
        if not node.is_dir:
            return len(node.content)
        return sum(self._compute_node_bytes(child) for child in node.children.values())

    def space_used(self) -> int:
        return self._compute_node_bytes(self.root)

    def space_total(self) -> int:
        return int(self.max_bytes)

    def is_read_only(self) -> bool:
        return bool(self.read_only)

    def get_label(self) -> Optional[str]:
        return self.label

    def set_label(self, value: Optional[str]) -> Optional[str]:
        if self.read_only:
            raise PermissionError("filesystem is read-only")
        if value is None:
            self.label = None
        else:
            self.label = str(value)[:32]
        return self.label

    def exists(self, path: str) -> bool:
        return self._get_node(path) is not None

    def is_directory(self, path: str) -> bool:
        node = self._get_node(path)
        return bool(node and node.is_dir)

    def make_directory(self, path: str) -> bool:
        if self.read_only:
            return False
        segs = self.segments(path)
        cur = self.root
        created = False
        for seg in segs:
            if seg not in cur.children:
                cur.children[seg] = VFSNode(is_dir=True)
                created = True
            cur = cur.children[seg]
            if not cur.is_dir:
                return False
        return created or True

    def _write_bytes(self, path: str, data: bytes) -> bool:
        if self.read_only:
            return False
        segs = self.segments(path)
        if not segs:
            return False
        parent_path = "/" + "/".join(segs[:-1])
        self.make_directory(parent_path)
        parent = self._get_node(parent_path)
        if parent is None or not parent.is_dir:
            return False
        existing = parent.children.get(segs[-1])
        if existing is not None and existing.is_dir:
            return False
        old_len = len(existing.content) if existing is not None else 0
        if self.max_bytes > 0 and (self.space_used() - old_len + len(data)) > self.max_bytes:
            return False
        parent.children[segs[-1]] = VFSNode(is_dir=False, content=data)
        return True

    def write_file(self, path: str, content: bytes | str) -> bool:
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        return self._write_bytes(path, raw)

    def read_file(self, path: str) -> Optional[str]:
        node = self._get_node(path)
        if node is None or node.is_dir:
            return None
        return node.content.decode("utf-8", errors="replace")

    def size(self, path: str) -> int:
        node = self._get_node(path)
        if node is None or node.is_dir:
            return 0
        return len(node.content)

    def last_modified(self, path: str) -> int:
        node = self._get_node(path)
        return node.last_modified if node else 0

    def list_dir(self, path: str = "/") -> List[str]:
        node = self._get_node(path)
        if node is None or not node.is_dir:
            return []
        entries: List[str] = []
        for name, child in sorted(node.children.items()):
            entries.append(f"{name}/" if child.is_dir else name)
        return entries

    def remove(self, path: str) -> bool:
        if self.read_only:
            return False
        segs = self.segments(path)
        if not segs:
            return False
        parent_path = "/" + "/".join(segs[:-1])
        parent = self._get_node(parent_path)
        if parent is None or not parent.is_dir or segs[-1] not in parent.children:
            return False
        del parent.children[segs[-1]]
        return True

    def rename(self, old_path: str, new_path: str) -> bool:
        if self.read_only:
            return False
        node = self._get_node(old_path)
        if node is None:
            return False
        segs_new = self.segments(new_path)
        if not segs_new:
            return False
        parent_new = "/" + "/".join(segs_new[:-1])
        self.make_directory(parent_new)
        pnode = self._get_node(parent_new)
        if pnode is None or not pnode.is_dir:
            return False
        pnode.children[segs_new[-1]] = node
        self.remove(old_path)
        return True

    def copy(self, from_path: str, to_path: str) -> bool:
        if self.read_only:
            return False
        node = self._get_node(from_path)
        if node is None or node.is_dir:
            return False
        return self._write_bytes(to_path, bytes(node.content))

    def open(self, path: str, mode: str = "r") -> Tuple[Optional[VFSFileHandle], Optional[str]]:
        try:
            handle = VFSFileHandle(self, path, mode)
            return handle, None
        except Exception as exc:
            return None, str(exc)

    # Integer handle API for OpenComputers `filesystem` component invocations
    def open_handle(self, path: str, mode: str = "r") -> Tuple[Optional[int], Optional[str]]:
        handle, err = self.open(path, mode)
        if handle is None:
            return None, err
        hid = self._next_handle_id
        self._next_handle_id += 1
        self._handles[hid] = handle
        return hid, None

    def read_handle(self, hid: int, count: float = math.inf) -> Optional[str]:
        h = self._handles.get(int(hid))
        if h is None or h.closed:
            raise ValueError("bad file descriptor")
        return h.read(count)

    def write_handle(self, hid: int, data: str | bytes) -> bool:
        h = self._handles.get(int(hid))
        if h is None or h.closed:
            raise ValueError("bad file descriptor")
        return h.write(data)

    def seek_handle(self, hid: int, whence: str = "cur", offset: int = 0) -> int:
        h = self._handles.get(int(hid))
        if h is None or h.closed:
            raise ValueError("bad file descriptor")
        return h.seek(whence, offset)

    def close_handle(self, hid: int) -> bool:
        h = self._handles.pop(int(hid), None)
        if h is None:
            return False
        return h.close()

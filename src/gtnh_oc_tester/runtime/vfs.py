"""In-memory Virtual Filesystem (VFS) emulating OpenComputers / OpenOS filesystem and io."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    """File handle supporting both OpenOS `filesystem.open` and Lua `io.open` semantics."""

    def __init__(self, vfs: "VirtualFileSystem", path: str, mode: str) -> None:
        self.vfs = vfs
        self.path = vfs.canonical(path)
        self.mode = mode
        self.closed = False
        self.pos = 0
        node = vfs._get_node(self.path)
        if "w" in mode:
            self._buffer = bytearray()
            self.vfs._write_bytes(self.path, b"")
        elif "a" in mode:
            existing = node.content if node and not node.is_dir else b""
            self._buffer = bytearray(existing)
            self.pos = len(self._buffer)
            if node is None:
                self.vfs._write_bytes(self.path, b"")
        else:
            if node is None or node.is_dir:
                raise FileNotFoundError(f"File not found: {self.path}")
            self._buffer = bytearray(node.content)

    def read(self, fmt_or_count: object = "*a") -> Optional[str]:
        if self.closed:
            return None
        if isinstance(fmt_or_count, (int, float)):
            count = int(fmt_or_count)
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
        if self.closed or ("w" not in self.mode and "a" not in self.mode and "+" not in self.mode):
            return False
        for val in values:
            data = str(val).encode("utf-8")
            if self.pos == len(self._buffer):
                self._buffer.extend(data)
            else:
                self._buffer[self.pos : self.pos + len(data)] = data
            self.pos += len(data)
        self.vfs._write_bytes(self.path, bytes(self._buffer))
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
            self.vfs._write_bytes(self.path, bytes(self._buffer))
        return True

    def close(self) -> bool:
        if not self.closed:
            self.flush()
            self.closed = True
        return True


class VirtualFileSystem:
    """In-memory hierarchical virtual filesystem for OpenComputers sandboxes."""

    def __init__(self, initial_files: Optional[Dict[str, bytes | str]] = None) -> None:
        self.root = VFSNode(is_dir=True)
        self.root_address = "f8d0e1a2-1111-4000-8000-000000000001"
        self.tmp_address = "f8d0e1a2-2222-4000-8000-000000000002"
        self.cwd = "/home"
        self.make_directory("/home")
        self.make_directory("/tmp")
        self.make_directory("/lib")
        self.make_directory("/bin")
        self.make_directory("/etc")

        if initial_files:
            for path, content in initial_files.items():
                self.write_file(path, content)

    def canonical(self, path: str) -> str:
        s = str(path or "/").replace("\\", "/")
        if not s.startswith("/"):
            s = posixpath.join(self.cwd, s)
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

    def exists(self, path: str) -> bool:
        return self._get_node(path) is not None

    def is_directory(self, path: str) -> bool:
        node = self._get_node(path)
        return bool(node and node.is_dir)

    def make_directory(self, path: str) -> bool:
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
        segs = self.segments(path)
        if not segs:
            return False
        parent_path = "/" + "/".join(segs[:-1])
        self.make_directory(parent_path)
        parent = self._get_node(parent_path)
        if parent is None or not parent.is_dir:
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

    def list_dir(self, path: str) -> List[str]:
        node = self._get_node(path)
        if node is None or not node.is_dir:
            return []
        entries: List[str] = []
        for name, child in sorted(node.children.items()):
            entries.append(f"{name}/" if child.is_dir else name)
        return entries

    def remove(self, path: str) -> bool:
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

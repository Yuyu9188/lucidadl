"""Small helpers: filename sanitizing, metadata bits, dedup state."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from typing import Any, Dict, List, Optional

# Windows-forbidden filename chars + control chars.
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize(name: str, fallback: str = "untitled") -> str:
    name = (name or "").strip()
    name = _INVALID.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if name.upper() in {"CON", "PRN", "AUX", "NUL"} or re.match(r"^(COM|LPT)\d$", name.upper()):
        name = "_" + name
    return name[:180] or fallback


def sanitize_filename(fname: str, fallback: str = "download") -> str:
    """Sanitize a real on-disk filename WITHOUT truncating its extension."""
    root, ext = os.path.splitext(fname or "")
    ext = ext[:12]  # guard against absurd 'extensions'
    stem = sanitize(root, fallback)
    budget = max(1, 180 - len(ext))
    return (stem[:budget] or fallback) + ext


def artists_str(artists: Optional[List[Dict[str, Any]]]) -> str:
    names = [a.get("name", "") for a in (artists or []) if a.get("name")]
    return ", ".join(names) or "Unknown Artist"


def year_of(rfc3339: Optional[str]) -> Optional[str]:
    if not rfc3339:
        return None
    m = re.match(r"(\d{4})", str(rfc3339))
    return m.group(1) if m else None


def _path_exists(path: str) -> bool:
    """os.path.exists with Windows extended-length prefix (utils can't import api)."""
    if not path:
        return False
    try:
        if os.name == "nt":
            ap = os.path.abspath(path)
            if not ap.startswith("\\\\?\\"):
                ap = "\\\\?\\" + ap
            return os.path.exists(ap)
        return os.path.exists(path)
    except OSError:
        return False


class State:
    """Remembers which track URLs were already downloaded, *and where the file landed*,
    so a re-run skips an item only while its file still exists on disk. Delete the file
    → it is re-downloaded. Legacy state (no recorded path) is treated as 'done'."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.done: Dict[str, str] = {}   # url -> final file path ("" = unknown/legacy)
        self._inflight = set()
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f).get("done", [])
                if isinstance(raw, dict):
                    self.done = {str(k): str(v or "") for k, v in raw.items()}
                else:  # legacy: a plain list of URLs, no paths
                    self.done = {str(k): "" for k in raw}
            except Exception as e:
                # The file EXISTS but is unreadable: don't silently drop the whole dedup
                # history (the next add() would overwrite it). Back it up and warn.
                self.done = {}
                bak = path + ".bad"
                try:
                    os.replace(path, bak)
                except OSError:
                    bak = path
                sys.stderr.write(
                    f"⚠ dedup state unreadable ({path}: {e}) — backed up to {bak} then "
                    f"reset; duplicates are possible this run.\n")

    def has(self, key: str) -> bool:
        """True if this URL counts as already-downloaded. A recorded path that no
        longer exists on disk does NOT count (the user deleted it → re-download)."""
        if key not in self.done:
            return False
        p = self.done[key]
        return _path_exists(p) if p else True

    def reserve(self, key: str) -> bool:
        """Atomically claim a key (asyncio single-thread: no await inside).
        Returns False if already downloaded (and present) or currently in flight."""
        if key in self._inflight or self.has(key):
            return False
        self._inflight.add(key)
        return True

    def release(self, key: str) -> None:
        self._inflight.discard(key)

    def add(self, key: str, path: str = "") -> None:
        with self._lock:
            self.done[key] = path or self.done.get(key) or ""
            self._inflight.discard(key)
            tmp = self.path + f".{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"done": self.done}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

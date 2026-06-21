"""Small helpers: filename sanitizing, metadata bits, dedup state."""

from __future__ import annotations

import json
import os
import re
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


class State:
    """Remembers which item URLs were already downloaded (skip on re-run)."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.done = set()
        self._inflight = set()
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.done = set(json.load(f).get("done", []))
            except Exception:
                self.done = set()

    def has(self, key: str) -> bool:
        return key in self.done

    def reserve(self, key: str) -> bool:
        """Atomically claim a key (asyncio single-thread: no await inside).
        Returns False if already downloaded or currently in flight."""
        if key in self.done or key in self._inflight:
            return False
        self._inflight.add(key)
        return True

    def release(self, key: str) -> None:
        self._inflight.discard(key)

    def add(self, key: str) -> None:
        with self._lock:
            self.done.add(key)
            self._inflight.discard(key)
            tmp = self.path + f".{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"done": sorted(self.done)}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

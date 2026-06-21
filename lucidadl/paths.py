"""Filesystem locations.

App data that must persist across runs and is independent of where you launch the
tool — the Cloudflare cookie, the browser profile, the dedup state — lives in a
per-user data directory. Working files you expect next to you — downloads, watchlist
inputs, logs — live in the current working directory.

Override the data directory with the LUCIDADL_HOME environment variable.
"""

from __future__ import annotations

import os
from pathlib import Path

APP = "lucidadl"


def _data_dir() -> Path:
    env = os.environ.get("LUCIDADL_HOME")
    if env:
        d = Path(env)
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        d = Path(base) / APP
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        d = Path(base) / APP
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


DATA_DIR = _data_dir()
PROFILE_DIR = str(DATA_DIR / "profile")        # persistent browser profile
CLEARANCE_PATH = str(DATA_DIR / "clearance.json")  # cached cf_clearance + UA
STATE_PATH = str(DATA_DIR / "state.json")      # dedup (downloaded item URLs)


def cwd(name: str) -> str:
    """A path in the current working directory (downloads, inputs, logs)."""
    return os.path.join(os.getcwd(), name)

"""Download progress rendering.

A `Reporter` decouples the download core from how progress is shown. `TextReporter`
reproduces the classic line-by-line log (and is what non-interactive / piped runs use).
`RichReporter` draws one live progress bar per concurrent download. Both mirror every
text event to the run-log file, so the log on disk is identical regardless of rendering.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional


class Reporter:
    """No-op base; also the interface the downloader calls."""

    def log(self, msg: object = "") -> None: ...
    def start(self, key: str, label: str) -> None: ...
    def status(self, key: str, msg: str) -> None: ...
    def progress(self, key: str, downloaded: int, total: Optional[int]) -> None: ...
    def finish(self, key: str, ok: bool, line: str) -> None: ...
    def close(self) -> None: ...


def _tofile(logfile, s: str) -> None:
    if logfile is None:
        return
    try:
        logfile.write(s + "\n")
        logfile.flush()
    except Exception:
        pass


class TextReporter(Reporter):
    """Classic behaviour: print every event as a line (console + log file)."""

    def __init__(self, echo: Callable[[str], None] = print, logfile=None):
        self._echo = echo
        self._logfile = logfile
        self._last_status: dict = {}

    def log(self, msg: object = "") -> None:
        s = str(msg)
        try:
            self._echo(s)
        except Exception:
            pass
        _tofile(self._logfile, s)

    def start(self, key: str, label: str) -> None:
        self.log(f"  ▶ {label}")

    def status(self, key: str, msg: str) -> None:
        if msg and msg != self._last_status.get(key):
            self._last_status[key] = msg
            self.log(f"    … {msg}")

    def progress(self, key: str, downloaded: int, total: Optional[int]) -> None:
        pass  # bytes are shown only in the rich renderer

    def finish(self, key: str, ok: bool, line: str) -> None:
        self._last_status.pop(key, None)
        self.log(line)

    def close(self) -> None:
        pass


class RichReporter(Reporter):
    """One live progress bar per concurrent download (rich)."""

    def __init__(self, logfile=None):
        from rich.console import Console
        from rich.progress import (Progress, SpinnerColumn, BarColumn, TextColumn,
                                    DownloadColumn, TransferSpeedColumn, TaskProgressColumn)
        self._console = Console()
        self._logfile = logfile
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=self._console, transient=False, expand=True,
        )
        self._tasks: dict = {}
        self._labels: dict = {}
        self._started = False

    def _ensure(self) -> None:
        if not self._started:
            self._progress.start()
            self._started = True

    def log(self, msg: object = "") -> None:
        s = str(msg)
        try:
            self._console.print(s, markup=False, highlight=False)
        except Exception:
            pass
        _tofile(self._logfile, s)

    def start(self, key: str, label: str) -> None:
        self._ensure()
        self._labels[key] = label
        try:
            self._tasks[key] = self._progress.add_task(label, total=None)
        except Exception:
            pass
        _tofile(self._logfile, f"  ▶ {label}")

    def status(self, key: str, msg: str) -> None:
        tid = self._tasks.get(key)
        if tid is not None and msg:
            try:
                self._progress.update(tid, description=f"{self._labels.get(key, '')} · {msg}")
            except Exception:
                pass

    def progress(self, key: str, downloaded: int, total: Optional[int]) -> None:
        tid = self._tasks.get(key)
        if tid is None:
            return
        try:
            task = self._progress.tasks[self._progress.task_ids.index(tid)]
            if total and task.total is None:
                self._progress.update(tid, total=total,
                                      description=self._labels.get(key, ""))
            self._progress.update(tid, completed=downloaded)
        except Exception:
            pass

    def finish(self, key: str, ok: bool, line: str) -> None:
        tid = self._tasks.pop(key, None)
        if tid is not None:
            try:
                self._progress.remove_task(tid)
            except Exception:
                pass
        self._labels.pop(key, None)
        try:
            self._console.print(line, markup=False, highlight=False,
                                style="green" if ok else "red")
        except Exception:
            pass
        _tofile(self._logfile, line)

    def close(self) -> None:
        if self._started:
            try:
                self._progress.stop()
            except Exception:
                pass
            self._started = False


def make_reporter(echo: Callable[[str], None] = print, logfile=None,
                  rich_ok: Optional[bool] = None) -> Reporter:
    """Rich bars when attached to an interactive terminal and rich is importable;
    otherwise the plain text reporter (pipes, redirects, dumb terminals, CI)."""
    if rich_ok is None:
        rich_ok = bool(getattr(sys.stdout, "isatty", lambda: False)())
    if rich_ok:
        try:
            return RichReporter(logfile=logfile)
        except Exception:
            pass
    return TextReporter(echo=echo, logfile=logfile)

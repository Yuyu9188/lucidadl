"""Interactive terminal menu (`lucida ui`).

A small, dependency-light front-end over the existing async runners. Each menu action
gathers a couple of inputs with questionary, then dispatches to the very same code the
plain commands use (so behaviour is identical, just easier to drive). Download progress
is rendered by the rich reporter in :mod:`lucidadl.progress`.
"""

from __future__ import annotations

import asyncio
import os
import sys

from . import paths, transcode

_TO_NONE = "(none — keep the source format)"
_SERVICES = ["qobuz", "amazon"]
# actions whose output is worth reading before the menu redraws (we pause after them)
_PAUSE_AFTER = {"track", "album", "playlist", "search", "watchlist", "retry"}


def _isatty(stream) -> bool:
    # stdin/stdout can be None under pythonw / detached GUI contexts
    return bool(getattr(stream, "isatty", lambda: False)())


def _onoff(b: bool) -> str:
    return "yes" if b else "no"


# --- persisted settings -----------------------------------------------------

def _settings() -> dict:
    cfg = paths.load_config()
    return {
        "jobs": int(cfg.get("jobs", 3) or 3),
        "service": cfg.get("service") if cfg.get("service") in _SERVICES else "qobuz",
        "to": cfg.get("to") or None,
        "bitrate": cfg.get("bitrate") or None,
        "force": bool(cfg.get("force", False)),
        "keep_orig": bool(cfg.get("keep_orig", False)),
    }


def _save_settings(s: dict) -> None:
    cfg = paths.load_config()
    for k in ("jobs", "service", "to", "bitrate", "force", "keep_orig"):
        cfg[k] = s[k]
    paths.save_config(cfg)


def _to_label(s: dict) -> str:
    if s["to"] and s["bitrate"]:
        return f"{s['to']} @ {s['bitrate']}"
    return s["to"] or "original format (no transcoding)"


def _opts_line(s: dict) -> str:
    bits = [f"{s['jobs']} concurrent downloads", s["service"], _to_label(s)]
    if s["force"]:
        bits.append("force")
    if s["keep_orig"]:
        bits.append("keep FLAC")
    return "  ·  ".join(bits)


# --- small input helpers ----------------------------------------------------

def _ask_text(questionary, message: str, instruction: str = "") -> str:
    """Text prompt that collapses cancel/empty/whitespace into '' (caller returns)."""
    v = questionary.text(message, instruction=instruction).ask()
    return (v or "").strip()


def _open_path(path: str, console) -> None:
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: F821 (Windows only)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        console.print(f"[green]Opened: {path}[/]")
    except Exception as e:
        console.print(f"[yellow]Could not open {path}: {e}[/]")


def _append_line(path: str, line: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def _remove_entries(path: str, entries) -> None:
    """Delete only the given entry lines, PRESERVING comments and blank lines (the
    watchlist files ship with a documented header we must not wipe)."""
    targets = set(entries)
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.readlines()
    except OSError:
        return
    kept = [ln for ln in raw if ln.strip() not in targets]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(kept)


# --- main loop --------------------------------------------------------------

def run() -> None:
    if not (_isatty(sys.stdin) and _isatty(sys.stdout)):
        print("`lucida ui` needs an interactive terminal. "
              "Use the direct commands instead (e.g. lucida track \"…\").")
        return
    try:
        import questionary
        from questionary import Choice
        from rich.console import Console
    except Exception as e:  # pragma: no cover
        print(f"UI unavailable ({e}). Install: pip install rich questionary")
        return

    console = Console()
    from . import cli  # deferred: cli imports tui for the command

    console.print("[dim]Esc cancels a field · Ctrl-C interrupts a download.[/]")
    while True:
        s = _settings()
        console.print(f"\n[bold cyan]lucidadl[/]  ·  [dim]{_opts_line(s)}[/]\n"
                      f"[dim]{paths.default_music_dir()}[/]")

        menu = [
            Choice("🎵  Download a track", "track"),
            Choice("💿  Download an album", "album"),
            Choice("🅰️   Import an Apple Music playlist", "playlist"),
            Choice("🔎  Interactive search", "search"),
            Choice("📜  Watchlists (tracks / albums)", "watchlist"),
        ]
        failed = cli._read_lines(paths.FAILED_PATH)
        if failed:
            menu.append(Choice(f"🔁  Retry failures ({len(failed)})", "retry"))
        menu += [
            Choice("⚙   Settings", "settings"),
            Choice("🛡   Prepare access (Cloudflare)", "setup"),
            Choice("📂  Open the music folder", "openfolder"),
            Choice("📄  View the log", "log"),
            Choice("🚪  Quit", "quit"),
        ]
        action = questionary.select("What would you like to do?", choices=menu,
                                    qmark="►", instruction="(↑/↓, Enter)").ask()

        if action in (None, "quit"):
            console.print("See you soon.")
            return
        ran = False
        try:
            ran = _dispatch(action, s, console, cli, questionary)
        except KeyboardInterrupt:
            console.print("[yellow]Interrupted.[/]")
            ran = True
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")
            ran = True
        if ran and action in _PAUSE_AFTER:
            try:
                questionary.text("Enter to return to the menu…").ask()
            except Exception:
                pass


def _dispatch(action, s, console, cli, questionary) -> bool:
    """Returns True if an action actually ran (worth pausing on), False if cancelled."""
    out = paths.default_music_dir()

    def _warn_browser():
        if not os.path.exists(paths.CLEARANCE_PATH):
            console.print("[dim]A browser may open briefly to get past "
                          "Cloudflare — that's normal.[/]")

    def go(items, kind, dedup, collection=None):
        _warn_browser()
        asyncio.run(cli._run(items, kind, s["service"], None, "original", out,
                             hidden=False, jobs=s["jobs"], dedup=dedup, organize_on=True,
                             to_fmt=s["to"], bitrate=s["bitrate"], keep_orig=s["keep_orig"],
                             collection=collection, force=s["force"]))

    if action == "track":
        q = _ask_text(questionary, "Track or URL:",
                      "(e.g. Daft Punk - Around the World ; empty = back)")
        if not q:
            return False
        go([q], "track", dedup=False)
        return True

    if action == "album":
        q = _ask_text(questionary, "Album or URL:",
                      "(e.g. Daft Punk - Discovery ; empty = back)")
        if not q:
            return False
        go([q], "album", dedup=False)
        return True

    if action == "playlist":
        url = _ask_text(questionary, "Apple Music playlist URL:", "(empty = back)")
        if not url:
            return False
        dry = questionary.confirm("Just list (without downloading)?", default=False).ask()
        if dry is None:  # cancel must NOT fall through to a full download
            return False
        _warn_browser()
        asyncio.run(cli._playlist(url, dry, s["service"], None, "original", out,
                                  hidden=False, jobs=s["jobs"], organize_on=True,
                                  to_fmt=s["to"], bitrate=s["bitrate"],
                                  keep_orig=s["keep_orig"], force=s["force"]))
        return True

    if action == "search":
        return _search_action(s, console, cli, questionary, go)

    if action == "watchlist":
        return _watchlist_action(s, console, cli, questionary, go)

    if action == "retry":
        items = cli._read_lines(paths.FAILED_PATH)
        if not items:
            console.print("[yellow]No failures to retry.[/]")
            return False
        go(items, "track", dedup=False)
        return True

    if action == "settings":
        _settings_menu(s, console, questionary)
        return False

    if action == "setup":
        _warn_browser()
        asyncio.run(cli._setup())
        return False

    if action == "openfolder":
        _open_path(paths.default_music_dir(), console)
        return False

    if action == "log":
        if os.path.exists(paths.LOG_PATH):
            _open_path(paths.LOG_PATH, console)
        else:
            console.print("[yellow]No log yet.[/]")
        return False

    return False


def _search_action(s, console, cli, questionary, go) -> bool:
    from questionary import Choice
    q = _ask_text(questionary, "Search:", "(empty = back)")
    if not q:
        return False
    if not os.path.exists(paths.CLEARANCE_PATH):
        console.print("[dim]A browser may open briefly to get past "
                      "Cloudflare — that's normal.[/]")
    try:
        entries = asyncio.run(cli._search_entries(q, s["service"]))
    except Exception as e:
        console.print(f"[red]Search failed: {e} (try \"Prepare access\").[/]")
        return True
    if not entries:
        console.print("[yellow]No results.[/]")
        return True
    choices = []
    for kind, it in entries:
        tag = "💿" if kind == "album" else "🎵"
        alb = f"  [{it.get('album')}]" if it.get("album") else ""
        choices.append(Choice(f"{tag} {it.get('title', '?')} — {it.get('artist', '?')}{alb}",
                              (kind, it)))
    choices.append(Choice("← Cancel", None))
    pick = questionary.select("Result to download:", choices=choices).ask()
    if not pick:
        return False
    kind, item = pick
    go([item["url"]], kind, dedup=False)
    return True


def _watchlist_action(s, console, cli, questionary, go) -> bool:
    from questionary import Choice
    which = questionary.select("Which list?", choices=[
        Choice("Tracks  (tracks.txt)", "tracks"),
        Choice("Albums  (albums.txt)", "albums"),
        Choice("← Back", None),
    ]).ask()
    if not which:
        return False
    kind = "track" if which == "tracks" else "album"
    f = os.path.join(cli.INPUTS, f"{which}.txt")
    lines = cli._read_lines(f)
    op = questionary.select(f"{which}.txt — {len(lines)} item(s):", choices=[
        Choice("⬇   Download all", "dl"),
        Choice("👁   View the list", "view"),
        Choice("➕  Add", "add"),
        Choice("🗑   Remove", "del"),
        Choice("← Back", None),
    ]).ask()
    if not op:
        return False

    if op == "view":
        if lines:
            for line in lines:
                console.print(f"  • {line}")
        else:
            console.print("[yellow](empty list)[/]")
        return True

    if op == "add":
        added = 0
        while True:
            it = _ask_text(questionary, "Add (artist - track/album, or URL ; empty = done):")
            if not it:
                break
            _append_line(f, it)
            added += 1
            console.print(f"[green]+ {it}[/]")
        if added:
            console.print(f"[green]{added} added to {which}.txt.[/]")
        return added > 0

    if op == "del":
        if not lines:
            console.print("[yellow](empty list)[/]")
            return False
        rm = questionary.checkbox("Check (Space) the items to remove:",
                                  choices=lines).ask()
        if rm:
            _remove_entries(f, rm)  # preserves comments / blank lines
            console.print(f"[green]{len(rm)} removed.[/]")
        return bool(rm)

    # op == "dl"
    if not lines:
        console.print(f"[yellow]{which}.txt is empty — add some items first.[/]")
        return False
    go(lines, kind, dedup=True)
    return True


# --- settings : scroll a list, edit ONE row, ← Back to leave ----------------

def _settings_menu(s, console, questionary) -> None:
    from questionary import Choice
    while True:
        choice = questionary.select(
            "Settings — choose an item to change:",
            choices=[
                Choice(f"Parallel downloads: {s['jobs']}", "jobs"),
                Choice(f"Service: {s['service']}", "service"),
                Choice(f"Transcoding: {_to_label(s)}", "to"),
                Choice(f"Keep the original FLAC: {_onoff(s['keep_orig'])}", "keep"),
                Choice(f"Force re-download: {_onoff(s['force'])}", "force"),
                Choice(f"Music folder: {paths.default_music_dir()}", "music"),
                Choice("← Back", "back"),
            ],
            qmark="⚙", instruction="(↑/↓, Enter ; Esc = back)",
        ).ask()
        if choice in (None, "back"):
            return
        _edit_setting(choice, s, console, questionary)


def _edit_setting(key, s, console, questionary) -> None:
    if key == "jobs":
        v = questionary.text("Parallel downloads (1–20):", default=str(s["jobs"]),
                             validate=lambda x: x.isdigit() and 1 <= int(x) <= 20).ask()
        if not v:
            return
        s["jobs"] = int(v)
        _save_settings(s)
    elif key == "service":
        v = questionary.select("Service:",
                               default=s["service"] if s["service"] in _SERVICES else "qobuz",
                               choices=_SERVICES).ask()
        if not v:
            return
        s["service"] = v
        _save_settings(s)
    elif key == "to":
        cur = s["to"] if s["to"] in transcode.CHOICES else _TO_NONE
        to = questionary.select("Local transcoding (ffmpeg):", default=cur,
                                choices=[_TO_NONE] + list(transcode.CHOICES)).ask()
        if to is None:
            return
        s["to"] = None if to == _TO_NONE else to
        if s["to"]:
            br = questionary.text("Bitrate (e.g. 320k, 256k, 192k ; empty = default):",
                                  default=s["bitrate"] or "").ask()
            s["bitrate"] = (br or "").strip() or None
        else:
            s["bitrate"] = None
        _save_settings(s)
    elif key == "keep":
        v = questionary.confirm("Keep the original FLAC next to the transcoded file?",
                                default=s["keep_orig"]).ask()
        if v is None:
            return
        s["keep_orig"] = bool(v)
        _save_settings(s)
    elif key == "force":
        v = questionary.confirm("Force re-download (ignore dedup)?",
                                default=s["force"]).ask()
        if v is None:
            return
        s["force"] = bool(v)
        _save_settings(s)
    elif key == "music":
        m = questionary.text("Music folder:", default=paths.default_music_dir()).ask()
        if not m or not m.strip():
            return
        paths.set_music_dir(m.strip())
        try:
            os.makedirs(paths.default_music_dir(), exist_ok=True)
        except Exception:
            pass
    console.print("[green]✓ Saved.[/]")

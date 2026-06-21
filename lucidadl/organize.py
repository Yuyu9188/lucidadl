"""Post-download organization: place files into <music_root>/<Artist>/<Album>/
using embedded tags, and auto-extract album zips into the same structure."""

from __future__ import annotations

import os
import shutil
import zipfile
from typing import Dict, List

from . import utils
from .api import _long

AUDIO_EXT = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".alac", ".aiff", ".aif"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def read_tags(path: str) -> Dict[str, str]:
    """Best-effort read of artist/albumartist/album from embedded tags."""
    try:
        import mutagen
        f = mutagen.File(_long(path), easy=True)
        if not f:
            return {}

        def first(key: str) -> str:
            v = f.get(key)
            if isinstance(v, list):
                return str(v[0]) if v else ""
            return str(v) if v else ""

        return {
            "artist": first("artist"),
            "albumartist": first("albumartist"),
            "album": first("album"),
            "title": first("title"),
        }
    except Exception:
        return {}


def album_dir(music_root: str, tags: Dict[str, str]) -> str:
    artist = tags.get("albumartist") or tags.get("artist") or "Unknown Artist"
    album = tags.get("album") or "Unknown Album"
    return os.path.join(music_root, utils.sanitize(artist), utils.sanitize(album))


def _move_into(src: str, dest_dir: str) -> str:
    os.makedirs(_long(dest_dir), exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(src))
    root, ext = os.path.splitext(dest)
    i = 1
    while os.path.exists(_long(dest)):
        dest = f"{root} ({i}){ext}"
        i += 1
    shutil.move(_long(src), _long(dest))
    return dest


def place_file(path: str, music_root: str) -> str:
    """Move a single audio file into <music_root>/<Artist>/<Album>/."""
    return _move_into(path, album_dir(music_root, read_tags(path)))


def process_download(path: str, music_root: str) -> List[str]:
    """Organize a finished download (single audio file or an album .zip).
    Returns the final file paths. Removes the source zip after extraction."""
    if path.lower().endswith(".zip"):
        return _extract_and_place(path, music_root)
    return [place_file(path, music_root)]


def _extract_and_place(zip_path: str, music_root: str) -> List[str]:
    tmp = zip_path + ".extract"
    placed: List[str] = []
    covers: List[str] = []
    try:
        with zipfile.ZipFile(_long(zip_path)) as z:
            z.extractall(_long(tmp))
        for root, _dirs, files in os.walk(tmp):
            for fn in files:
                fp = os.path.join(root, fn)
                ext = os.path.splitext(fn)[1].lower()
                if ext in AUDIO_EXT:
                    placed.append(place_file(fp, music_root))
                elif ext in IMAGE_EXT:
                    covers.append(fp)
        # drop cover art into the album folder of the first placed track
        if placed and covers:
            target = os.path.dirname(placed[0])
            dst = os.path.join(target, "cover" + os.path.splitext(covers[0])[1].lower())
            if not os.path.exists(_long(dst)):
                try:
                    shutil.copyfile(_long(covers[0]), _long(dst))
                except OSError:
                    pass
    finally:
        shutil.rmtree(_long(tmp), ignore_errors=True)
        try:
            os.remove(_long(zip_path))
        except OSError:
            pass
    return placed

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

# Top-level grouping under the music root: albums/tracks live under Artistes/<Artist>/…,
# playlists live under Playlists/<Playlist name>/ — so the two never mix.
ARTISTS_DIR = "Artistes"
PLAYLISTS_DIR = "Playlists"

try:  # mutagen is a hard dep; a missing/broken install must be VISIBLE, not silent
    import mutagen as _mutagen
except Exception:  # pragma: no cover
    _mutagen = None


def mutagen_available() -> bool:
    """False if mutagen can't be imported — tag-based organization is then impossible
    and every file would land in Unknown Artist/Album. Callers warn the user."""
    return _mutagen is not None


def read_tags(path: str) -> Dict[str, str]:
    """Best-effort read of artist/albumartist/album from embedded tags. Returns {} if
    mutagen is unavailable or the file's tags can't be read (caller falls back to
    API-supplied metadata, then to Unknown)."""
    if _mutagen is None:
        return {}
    try:
        f = _mutagen.File(_long(path), easy=True)
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


def album_dir(music_root: str, tags: Dict[str, str], meta: Dict[str, str] = None) -> str:
    """<music_root>/<Artist>/<Album>/. Embedded `tags` win; API-derived `meta` only
    fills a BLANK folder-artist or folder-album (so a file that already organizes
    correctly by its embedded artist is never relocated by meta), then 'Unknown'."""
    tags = tags or {}
    meta = meta or {}
    artist = (tags.get("albumartist") or tags.get("artist")
              or meta.get("albumartist") or meta.get("artist") or "Unknown Artist")
    album = tags.get("album") or meta.get("album") or "Unknown Album"
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


def place_file(path: str, music_root: str, collection: str = None,
               meta: Dict[str, str] = None) -> str:
    """Move a single audio file into <music_root>/<Artist>/<Album>/, or, when a
    `collection` (e.g. a playlist name) is given, into <music_root>/<collection>/.
    `meta` (API-derived artist/album) is a fallback used only when embedded tags
    are missing; `collection` takes priority over both. Playlists go under
    <music_root>/Playlists/<collection>/, everything else under
    <music_root>/Artistes/<Artist>/<Album>/."""
    if collection:
        dest_dir = os.path.join(music_root, PLAYLISTS_DIR, utils.sanitize(collection))
    else:
        dest_dir = album_dir(os.path.join(music_root, ARTISTS_DIR), read_tags(path), meta)
    return _move_into(path, dest_dir)


def process_download(path: str, music_root: str, collection: str = None,
                     meta: Dict[str, str] = None) -> List[str]:
    """Organize a finished download (single audio file or an album .zip).
    Returns the final file paths. Removes the source zip after extraction."""
    if path.lower().endswith(".zip"):
        return _extract_and_place(path, music_root, collection, meta)
    return [place_file(path, music_root, collection, meta)]


def _extract_and_place(zip_path: str, music_root: str, collection: str = None,
                       meta: Dict[str, str] = None) -> List[str]:
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
                    placed.append(place_file(fp, music_root, collection, meta))
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

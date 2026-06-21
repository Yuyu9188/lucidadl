"""Local audio transcoding via ffmpeg (bundled by imageio-ffmpeg).

Download the original (FLAC) from lucida, then convert here to the chosen
format/bitrate — full codec + bitrate control, tags and cover art preserved."""

from __future__ import annotations

import os
import re
import subprocess
from typing import List, Optional

# target format -> output extension
EXT = {
    "mp3": ".mp3", "aac": ".m4a", "m4a": ".m4a", "opus": ".opus",
    "ogg": ".ogg", "vorbis": ".ogg", "flac": ".flac", "wav": ".wav",
}
CHOICES = ["mp3", "aac", "m4a", "opus", "ogg", "flac", "wav"]


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def available() -> bool:
    try:
        r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-version"],
                           capture_output=True, text=True)
        return r.returncode == 0
    except Exception:
        return False


def norm_bitrate(b: Optional[str]) -> Optional[str]:
    """A bare number means kbps: '192' -> '192k'. Avoids ffmpeg reading it as bits/s."""
    if not b:
        return None
    b = str(b).strip().lower()
    if re.fullmatch(r"\d+", b):
        return b + "k"
    return b


def build_cmd(ff: str, src: str, dst: str, fmt: str, bitrate: Optional[str]) -> List[str]:
    fmt = fmt.lower()
    bitrate = norm_bitrate(bitrate)
    base = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-map_metadata", "0"]
    if fmt == "mp3":
        enc = ["-map", "0:a", "-map", "0:v?", "-c:v", "copy", "-id3v2_version", "3",
               "-c:a", "libmp3lame", "-b:a", bitrate or "320k"]
    elif fmt in ("aac", "m4a"):
        enc = ["-map", "0:a", "-map", "0:v?", "-c:v", "copy", "-disposition:v", "attached_pic",
               "-c:a", "aac", "-b:a", bitrate or "256k"]
    elif fmt == "opus":
        enc = ["-map", "0:a", "-c:a", "libopus", "-b:a", bitrate or "192k"]
    elif fmt in ("ogg", "vorbis"):
        enc = ["-map", "0:a", "-c:a", "libvorbis"] + (
            ["-b:a", bitrate] if bitrate else ["-q:a", "6"])
    elif fmt == "flac":
        enc = ["-map", "0:a", "-map", "0:v?", "-c:v", "copy", "-c:a", "flac"]
    elif fmt == "wav":
        enc = ["-map", "0:a", "-c:a", "pcm_s16le"]
    else:
        raise ValueError(f"format de transcodage inconnu: {fmt}")
    return base + enc + [dst]


def transcode(src: str, fmt: str, bitrate: Optional[str] = None,
              keep_original: bool = False, log=print) -> str:
    """Transcode `src` to `fmt`; return the new path (or `src` unchanged if already
    that format). On ffmpeg failure raises RuntimeError (caller keeps the original)."""
    fmt = (fmt or "").lower()
    ext = EXT.get(fmt)
    if not ext:
        raise ValueError(f"format inconnu: {fmt}")
    root, src_ext = os.path.splitext(src)
    if src_ext.lower() == ext.lower():
        return src  # already in the target format — nothing to do
    dst = root + ext
    cmd = build_cmd(ffmpeg_exe(), src, dst, fmt, bitrate)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        try:
            if os.path.exists(dst):
                os.remove(dst)
        except OSError:
            pass
        raise RuntimeError((r.stderr or "ffmpeg error").strip().splitlines()[-1][:300]
                           if (r.stderr or "").strip() else "ffmpeg error")
    if not keep_original:
        try:
            os.remove(src)
        except OSError:
            pass
    return dst

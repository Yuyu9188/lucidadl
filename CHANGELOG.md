# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-27

First public release.

### Added
- **Fast parallel downloads** over HTTP (`-j/--jobs`) — the Cloudflare challenge is
  solved once in a real browser (`setup`), the `cf_clearance` cookie is cached, and
  everything else runs over `httpx`, so no browser stays open.
- **Search or URL** for `track` / `album` (singular, ad-hoc) and `tracks` / `albums`
  (watchlists with dedup), plus automatic **service fallback** (Qobuz → Amazon).
- **Albums downloaded track-by-track** in parallel.
- **Local transcoding** with bundled ffmpeg (`--to`, `--bitrate`); tags and cover art
  preserved. `-F/--format` requests a server-side format from lucida.
- **Tag-based organization** into `Artists/<Artist>/<Album>/`, with an API-metadata
  fallback when a file has no embedded tags. Playlists go under `Playlists/<name>/`.
- **Apple Music playlist import** (`playlist`) — the tracklist is scraped headless, with
  a visible-window fallback, then each track is downloaded via Qobuz.
- **Interactive menu** (`lucida ui`, or bare `lucida`) and **live progress bars** (one
  per parallel download).
- **Interactive search** (`search`), **retry** of failures (`retry`), and a `config`
  command for the fixed music directory.
- **Existence-aware dedup**: an item is skipped only while its file still exists; delete
  it and it is re-downloaded. `--force` ignores the dedup memory.
- **Fixed, configurable download directory** (`~/Downloads/music` by default;
  `lucida config --music`, or the `LUCIDADL_MUSIC` env var).

[Unreleased]: https://github.com/Jude-A/lucidadl/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Jude-A/lucidadl/releases/tag/v0.1.0

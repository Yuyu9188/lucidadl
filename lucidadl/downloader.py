"""Async orchestration over the FAST HTTP path (no browser).

Phase 1 (resolve): each line -> item URL (search via httpx, with service fallback for
free-text queries), then ONE httpx GET of the item page -> token + every track.
Phase 2 (download): per track, httpx POST /api/load + poll + stream the file from the
Cloudflare-free <server>.lucida.to. Failed items are collected for an easy retry."""

from __future__ import annotations

import asyncio
import os
from typing import Dict, List, Optional, Tuple

from . import matching, organize, transcode, utils
from .api import LucidaClient, LucidaError, FALLBACK_SERVICES, normalize_service, _long


async def _resolve_url(client: LucidaClient, line: str, service: str, kind: str,
                       log, strict: bool = False) -> Optional[str]:
    line = line.strip()
    if line.lower().startswith("http"):
        return line
    services = [service]
    if not strict:
        for s in FALLBACK_SERVICES:
            if normalize_service(s) != normalize_service(service):
                services.append(s)
    bucket = "albums" if kind == "album" else "tracks"
    for i, svc in enumerate(services):
        res = await client.search(line, svc)
        items = res.get(bucket) or []
        if not items and kind == "album":
            items = res.get("tracks") or []
        if items:
            url = matching.pick_best(line, items)
            chosen = next((it for it in items if it.get("url") == url), {})
            tag = f" [repli {svc}]" if i else ""
            log(f"  ↳ choisi: «{chosen.get('title', '?')}» — {chosen.get('artist', '?')}{tag} "
                f"(parmi {len(items)} résultats)")
            return url
    return None


def _dest_dir(out: str, organize_on: bool) -> str:
    return os.path.join(out, ".incoming") if organize_on else os.path.join(out, "Music")


def _filesize_mb(path: Optional[str]) -> float:
    try:
        return os.path.getsize(_long(path)) / 1_048_576 if path else 0.0
    except OSError:
        return 0.0


async def _resolve_targets(client, line, kind, service, country, strict, log
                           ) -> Optional[List[Dict]]:
    url = await _resolve_url(client, line, service, kind, log, strict)
    if not url:
        return None
    pd = await client.fetch_page_data(url, country)        # ONE httpx GET
    info = pd.get("info", {}) or {}
    expiry = pd.get("tokenExpiry")
    is_album = info.get("type") == "album"
    targets = []
    for t in client.tracks_from_pd(pd):
        if t.get("producers", "x") is None or not t.get("url"):  # unavailable
            continue
        targets.append({"url": t["url"], "label": t.get("title") or line,
                        "csrf": t.get("csrf"), "csrfFallback": t.get("csrfFallback"),
                        "expiry": expiry})
    if not targets:
        return None
    if is_album:
        log(f"  ⤷ album «{line}» → {len(targets)} pistes")
    return targets


async def _download_target(client, state, target, country, out, dedup, organize_on,
                           tx, log, totals, failed, lock) -> None:
    url, label = target["url"], target["label"]
    reserved = False
    if dedup and not state.reserve(url):
        log(f"  ⏭ déjà téléchargé / en cours, ignoré: {label}")
        async with lock:
            totals["skip"] += 1
        return
    reserved = dedup
    log(f"  ▶ {label}")
    track = {"url": url, "csrf": target["csrf"], "csrfFallback": target.get("csrfFallback")}
    path, last_err = None, None
    for attempt in range(2):
        try:
            handoff, server = await client.start_download(track, target["expiry"], country)
            path = await client.run_job(handoff, server, _dest_dir(out, organize_on),
                                        utils.sanitize(label), title=label)
            break
        except Exception as e:
            last_err = e
            if attempt == 0:
                log(f"  … {label}: {e} — nouvelle tentative")
                await asyncio.sleep(3)
    if path is None:
        if reserved:
            state.release(url)
        log(f"  ✗ {label}: {last_err}")
        async with lock:
            totals["fail"] += 1
            failed.append(url)  # a track URL: `retry` can re-download it directly
        return

    finals = [path]
    if organize_on:
        try:
            finals = await asyncio.to_thread(organize.process_download, path, out) or [path]
        except Exception as e:
            log(f"  ⚠ rangement échoué ({os.path.basename(path)}): {e}")
    if tx and tx.get("fmt"):
        converted = []
        for fp in finals:
            try:
                converted.append(await asyncio.to_thread(
                    transcode.transcode, fp, tx["fmt"], tx.get("bitrate"),
                    tx.get("keep", False), log))
            except Exception as e:
                log(f"  ⚠ transcode échoué ({os.path.basename(fp)}): {e}")
                converted.append(fp)
        finals = converted

    async with lock:
        totals["ok"] += 1
    shown = os.path.relpath(finals[0], out) if finals else os.path.basename(path)
    extra = f" (+{len(finals) - 1})" if len(finals) > 1 else ""
    log(f"  ✓ {shown}{extra}  ({_filesize_mb(finals[0]):.1f} Mo)")
    try:
        state.add(url)
    except Exception as e:
        log(f"  ⚠ état non sauvegardé ({url}): {e}")


async def run_batch(client: LucidaClient, state: utils.State, items: List[str],
                    kind: str, service: str, country: Optional[str], out: str,
                    jobs: int, dedup: bool, organize_on: bool = True,
                    tx: Optional[Dict] = None, strict: bool = False, log=print
                    ) -> Tuple[Dict[str, int], List[str]]:
    totals = {"ok": 0, "skip": 0, "fail": 0}
    failed: List[str] = []
    sem = asyncio.Semaphore(max(1, jobs))
    lock = asyncio.Lock()

    # Phase 1 — resolve + expand into a flat track list (one httpx GET per item).
    targets: List[Dict] = []

    async def resolve_worker(line: str) -> None:
        async with sem:
            try:
                tg = await _resolve_targets(client, line, kind, service, country, strict, log)
            except Exception as e:
                log(f"  ✗ résolution «{line}»: {e}")
                async with lock:
                    totals["fail"] += 1
                    failed.append(line)
                return
            if tg is None:
                log(f"  ⃠ introuvable, ignoré: {line}")
                async with lock:
                    totals["skip"] += 1
                    failed.append(line)  # so `retry` can re-search it later
                return
            async with lock:
                targets.extend(tg)

    await asyncio.gather(*(resolve_worker(line) for line in items), return_exceptions=True)
    if not targets:
        return totals, failed
    log(f"→ {len(targets)} piste(s) à télécharger ({jobs} en parallèle)…")

    # Phase 2 — download every track concurrently over httpx (no browser).
    async def dl_worker(target: Dict) -> None:
        async with sem:
            try:
                await _download_target(client, state, target, country, out, dedup,
                                       organize_on, tx, log, totals, failed, lock)
            except Exception as e:
                log(f"  ✗ {target.get('label')}: {e}")
                async with lock:
                    totals["fail"] += 1
                    failed.append(target.get("url") or target.get("label"))

    await asyncio.gather(*(dl_worker(t) for t in targets), return_exceptions=True)
    return totals, failed

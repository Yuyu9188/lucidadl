"""Command-line interface for lucidadl (async download core)."""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from typing import List, Optional

import click

from . import api, paths, transcode, utils
from .api import LucidaClient, default_country, normalize_service, DOWNSCALE_CHOICES, LUCIDA
from .downloader import run_batch
from .session import (lucida_context, ensure_cleared, get_page, BrowserClosed,
                      acquire_clearance, load_clearance)

# App data (persistent, install-independent) in the user data dir; working files in cwd.
STATE_PATH = paths.STATE_PATH
DEFAULT_OUT = paths.cwd("downloads")
INPUTS = paths.cwd("inputs")
LOG_PATH = paths.cwd("run.log")
FAILED_PATH = paths.cwd("failed.txt")


def _write_failed(items) -> None:
    try:
        with open(FAILED_PATH, "w", encoding="utf-8") as f:
            f.write("# Items en échec — relance avec : lucidadl retry\n")
            f.write("\n".join(items) + "\n")
    except Exception:
        pass

_CLOSED_HINT = (
    "Le navigateur s'est fermé tout seul. Essaie : (1) relancer ; (2) ferme les "
    "fenêtres Chrome ; (3) pour forcer ton vrai Chrome : $env:LUCIDA_CHANNEL='chrome'."
)


def _read_lines(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def _service_opts(f):
    f = click.option("-s", "--service", default="qobuz",
                     help="Service source (qobuz par défaut, amazon).")(f)
    f = click.option("--country", default=None, help="Code pays (def: US pour qobuz).")(f)
    f = click.option("-F", "--format", "downscale", default="original",
                     type=click.Choice(DOWNSCALE_CHOICES),
                     help="Format demandé à lucida (conversion côté serveur, sans contrôle "
                          "du bitrate). Pour format + bitrate précis, préfère --to.")(f)
    f = click.option("-o", "--out", default=DEFAULT_OUT, help="Dossier de sortie.")(f)
    f = click.option("--organize/--flat", "organize_on", default=True,
                     help="Rangement par tags en Artiste/Album/ (défaut) ; "
                          "--flat = tout dans downloads/Music/.")(f)
    f = click.option("-j", "--jobs", default=3, type=click.IntRange(1, 20),
                     help="Téléchargements en parallèle (1–20, def 3).")(f)
    f = click.option("--to", "to_fmt", default=None, type=click.Choice(transcode.CHOICES),
                     help="Transcodage local ffmpeg (recommandé) : télécharge en FLAC puis "
                          "convertit vers ce format. Bitrate réglable via --bitrate.")(f)
    f = click.option("--bitrate", default=None,
                     help="Bitrate pour --to (ex: 320k, 256k, 192k).")(f)
    f = click.option("--keep-original", "keep_orig", is_flag=True,
                     help="Garder le FLAC d'origine à côté du fichier transcodé.")(f)
    f = click.option("--hidden/--visible", "hidden", default=False,
                     help="--hidden = fenêtre hors-écran si un passage Cloudflare est requis "
                          "(sinon aucun navigateur ne s'ouvre). Défaut: visible.")(f)
    return f


@click.group()
@click.version_option(message="lucidadl %(version)s")
def cli():
    """Téléchargeur lucida.to en HTTP parallèle (navigateur requis seulement pour Cloudflare)."""


# --- shared async runners ---------------------------------------------------

async def _run(items: List[str], kind: str, service: str, country: Optional[str],
               downscale: str, out: str, hidden: bool, jobs: int, dedup: bool,
               organize_on: bool = True, to_fmt: Optional[str] = None,
               bitrate: Optional[str] = None, keep_orig: bool = False) -> None:
    if not items:
        click.secho("Rien à télécharger.", fg="yellow")
        return
    cc = country or default_country(service)
    # When transcoding locally, pull the best source (FLAC) from lucida.
    tx = None
    if to_fmt:
        downscale = "original"
        tx = {"fmt": to_fmt, "bitrate": bitrate, "keep": keep_orig}
        if not transcode.available():
            click.secho("⚠ ffmpeg introuvable — installe-le (pip install imageio-ffmpeg) "
                        "ou enlève --to.", fg="red")
            return
    os.makedirs(out, exist_ok=True)
    state = utils.State(STATE_PATH)
    logf = open(LOG_PATH, "w", encoding="utf-8")

    def log(msg: object = "") -> None:
        s = str(msg)
        click.echo(s)
        try:
            logf.write(s + "\n")
            logf.flush()
        except Exception:
            pass

    log(f"# lucidadl — kind={kind} service={service} country={cc!r} "
        f"format={downscale} jobs={jobs} dedup={dedup} "
        f"transcode={to_fmt or '-'}{('@'+bitrate) if (to_fmt and bitrate) else ''}")
    try:
        # Get a Cloudflare cookie: reuse the saved one (no browser at all), else open
        # the browser briefly to solve it. Downloads then run over httpx (RAM-light).
        cf, ua = load_clearance()
        if not (cf and ua):
            log("Pas de cookie Cloudflare — ouverture brève du navigateur…")
            try:
                cf, ua = await acquire_clearance(hidden=hidden)
            except BrowserClosed:
                log(_CLOSED_HINT)
                return
            except Exception as e:
                log(f"Cloudflare non franchi: {e}. Lance `setup`.")
                return

        async def _acquire():
            return await acquire_clearance(hidden=hidden)

        client = LucidaClient(cf, ua, acquire=_acquire, country=cc, downscale=downscale,
                              metadata=True, jobs=jobs, log=log)
        await client.start_http()
        log(f"Téléchargement de {len(items)} élément(s) — {jobs} en parallèle (sans navigateur)…")
        try:
            totals, failed = await run_batch(client, state, items, kind, service, cc, out,
                                             jobs, dedup, organize_on, tx, log=log)
        finally:
            await client.aclose()
        log(f"\nTerminé — OK:{totals['ok']}  ignorés:{totals['skip']}  échecs:{totals['fail']}")
        if failed:
            _write_failed(failed)
            log(f"  → {len(failed)} échec(s) écrits dans failed.txt "
                f"(relance : run.cmd retry)")
    except Exception as e:
        log(f"ERREUR FATALE: {e}")
        log(traceback.format_exc())
    finally:
        try:
            logf.close()
        except Exception:
            pass
    click.secho("→ Journal écrit dans run.log", fg="cyan")


# --- ad-hoc (singulier) : args, sans dédup ---------------------------------

@cli.command("track")
@click.argument("items", nargs=-1, required=True)
@_service_opts
def track_cmd(items, service, country, downscale, out, organize_on, jobs, to_fmt,
              bitrate, keep_orig, hidden):
    """Un/des titre(s) maintenant : track "artiste - titre" (ou URL). Force le DL."""
    asyncio.run(_run(list(items), "track", service, country, downscale, out,
                     hidden, jobs, dedup=False, organize_on=organize_on,
                     to_fmt=to_fmt, bitrate=bitrate, keep_orig=keep_orig))


@cli.command("album")
@click.argument("items", nargs=-1, required=True)
@_service_opts
def album_cmd(items, service, country, downscale, out, organize_on, jobs,
              to_fmt, bitrate, keep_orig, hidden):
    """Un/des album(s) maintenant : album "artiste - album" (ou URL), déroulé piste par piste."""
    asyncio.run(_run(list(items), "album", service, country, downscale, out,
                     hidden, jobs, dedup=False, organize_on=organize_on,
                     to_fmt=to_fmt, bitrate=bitrate, keep_orig=keep_orig))


# --- watchlist (pluriel) : fichier, avec dédup -----------------------------

@cli.command("tracks")
@click.option("-f", "--file", "file", default=os.path.join(INPUTS, "tracks.txt"),
              help="Fichier de titres/URLs, un par ligne (def: inputs/tracks.txt).")
@_service_opts
def tracks_cmd(file, service, country, downscale, out, organize_on, jobs, to_fmt,
               bitrate, keep_orig, hidden):
    """Watchlist titres : télécharge inputs/tracks.txt (dédup activée)."""
    asyncio.run(_run(_read_lines(file), "track", service, country, downscale, out,
                     hidden, jobs, dedup=True, organize_on=organize_on,
                     to_fmt=to_fmt, bitrate=bitrate, keep_orig=keep_orig))


@cli.command("albums")
@click.option("-f", "--file", "file", default=os.path.join(INPUTS, "albums.txt"),
              help="Fichier d'albums/URLs, un par ligne (def: inputs/albums.txt).")
@_service_opts
def albums_cmd(file, service, country, downscale, out, organize_on, jobs,
               to_fmt, bitrate, keep_orig, hidden):
    """Watchlist albums : télécharge inputs/albums.txt (dédup activée)."""
    asyncio.run(_run(_read_lines(file), "album", service, country, downscale, out,
                     hidden, jobs, dedup=True, organize_on=organize_on,
                     to_fmt=to_fmt, bitrate=bitrate, keep_orig=keep_orig))


@cli.command("retry")
@_service_opts
def retry_cmd(service, country, downscale, out, organize_on, jobs, to_fmt,
              bitrate, keep_orig, hidden):
    """Relance les items en échec du dernier run (failed.txt)."""
    items = _read_lines(FAILED_PATH)
    if not items:
        click.secho("Aucun échec à relancer (failed.txt est vide).", fg="yellow")
        return
    asyncio.run(_run(items, "track", service, country, downscale, out,
                     hidden, jobs, dedup=True, organize_on=organize_on,
                     to_fmt=to_fmt, bitrate=bitrate, keep_orig=keep_orig))


# --- interactive search ----------------------------------------------------

async def _search(query, service, country, downscale, out, organize_on, jobs,
                  to_fmt, bitrate, keep_orig, hidden):
    cc = country or default_country(service)
    cf, ua = load_clearance()
    if not (cf and ua):
        try:
            cf, ua = await acquire_clearance(hidden=hidden)
        except Exception as e:
            click.secho(f"Cloudflare: {e}. Lance `setup`.", fg="red")
            return
    client = LucidaClient(cf, ua, acquire=lambda: acquire_clearance(hidden=hidden),
                          country=cc, downscale=downscale, log=click.echo)
    await client.start_http()
    try:
        res = await client.search(query, service)
    finally:
        await client.aclose()

    entries = []
    albums, tracks = res.get("albums") or [], res.get("tracks") or []
    if albums:
        click.secho("\nAlbums :", fg="cyan")
        for it in albums[:15]:
            entries.append(("album", it))
            click.echo(f"  {len(entries):>2}. {it.get('title', '?')} — {it.get('artist', '?')}")
    if tracks:
        click.secho("\nTitres :", fg="cyan")
        for it in tracks[:15]:
            entries.append(("track", it))
            alb = f"  [{it.get('album', '')}]" if it.get("album") else ""
            click.echo(f"  {len(entries):>2}. {it.get('title', '?')} — {it.get('artist', '?')}{alb}")
    if not entries:
        click.secho("Aucun résultat.", fg="yellow")
        return

    try:
        sel = (await asyncio.to_thread(input, "\nNuméro à télécharger (Entrée = annuler) : ")).strip()
    except EOFError:
        sel = ""
    if not sel.isdigit() or not (1 <= int(sel) <= len(entries)):
        click.echo("Annulé.")
        return
    kind, item = entries[int(sel) - 1]
    await _run([item["url"]], kind, service, country, downscale, out, hidden, jobs,
               dedup=False, organize_on=organize_on, to_fmt=to_fmt, bitrate=bitrate,
               keep_orig=keep_orig)


@cli.command("search")
@click.argument("query", nargs=-1, required=True)
@_service_opts
def search_cmd(query, service, country, downscale, out, organize_on, jobs,
               to_fmt, bitrate, keep_orig, hidden):
    """Recherche interactive : liste les résultats, télécharge celui que tu choisis."""
    asyncio.run(_search(" ".join(query), service, country, downscale, out, organize_on,
                        jobs, to_fmt, bitrate, keep_orig, hidden))


# --- playlist import (Apple Music / Spotify / Deezer / Tidal) --------------

async def _playlist(url, dry_run, service, country, downscale, out, hidden,
                    jobs, organize_on=True, to_fmt=None, bitrate=None, keep_orig=False):
    cc = country or default_country(service)
    click.echo("Lecture de la playlist (navigateur)…")
    tracks = []
    try:
        async with lucida_context(hidden=hidden) as ctx:  # browser only for the source page
            page = await get_page(ctx)
            tracks = await api.playlist_tracklist(page, url, click.echo)
    except BrowserClosed:
        click.secho(_CLOSED_HINT, fg="red")
        return
    except Exception as e:
        click.secho(f"✗ extraction playlist: {e}", fg="red")
        return

    if not tracks:
        click.secho("Aucun titre extrait (un <source>_debug.html a pu être écrit).", fg="red")
        return

    click.secho(f"\n{len(tracks)} titres trouvés :", fg="green")
    for t in tracks:
        click.echo(f"  - {t['artist']} - {t['title']}")
    items = [f"{t['artist']} - {t['title']}" for t in tracks]
    try:
        os.makedirs(INPUTS, exist_ok=True)
        with open(os.path.join(INPUTS, "playlist.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(items) + "\n")
        click.echo("(liste écrite dans inputs/playlist.txt)")
    except Exception:
        pass

    if dry_run:
        click.secho("--dry-run : pas de téléchargement.", fg="yellow")
        return
    click.secho(f"\nTéléchargement de {len(items)} titres via {service} ({jobs} en //)…", fg="cyan")
    await _run(items, "track", service, country, downscale, out, hidden, jobs,
               dedup=True, organize_on=organize_on, to_fmt=to_fmt, bitrate=bitrate,
               keep_orig=keep_orig)


@cli.command("playlist")
@click.argument("url")
@click.option("--dry-run", is_flag=True, help="Lister les titres sans télécharger.")
@_service_opts
def playlist_cmd(url, dry_run, service, country, downscale, out, organize_on, jobs,
                 to_fmt, bitrate, keep_orig, hidden):
    """Importe une playlist Apple Music (lien public) → télécharge chaque titre via lucida.
    (Spotify/Deezer/Tidal codés mais désactivés pour l'instant.)"""
    asyncio.run(_playlist(url, dry_run, service, country, downscale, out, hidden,
                          jobs, organize_on, to_fmt=to_fmt, bitrate=bitrate, keep_orig=keep_orig))


# --- setup / doctor / debug -------------------------------------------------

async def _setup():
    click.echo("Ouverture du navigateur… (résous un éventuel captcha)")
    try:
        await acquire_clearance(hidden=False)  # clears CF and SAVES the cookie to disk
    except BrowserClosed:
        click.secho(_CLOSED_HINT, fg="red")
        return
    except Exception as e:
        click.secho(f"⚠ {e} — réessaie `setup`.", fg="yellow")
        return
    click.secho("✓ Cloudflare passé, cookie mémorisé (les téléchargements n'ouvriront "
                "plus de navigateur tant qu'il est valide).", fg="green")


@cli.command()
def setup():
    """Ouvre le navigateur une fois pour passer Cloudflare et mémoriser le cookie."""
    asyncio.run(_setup())


async def _doctor():
    click.echo(f"Python      : {sys.version.split()[0]}")
    try:
        import playwright  # noqa
        click.echo("Playwright  : installé")
    except Exception as e:
        click.secho(f"Playwright  : MANQUANT ({e})", fg="red")
    click.echo(f"Profil      : {os.path.join(ROOT, '.userdata', 'profile')}")
    click.echo(f"Sortie      : {DEFAULT_OUT}")
    click.echo("Test navigateur + Cloudflare…")
    try:
        async with lucida_context(headless=False) as ctx:
            ok = await ensure_cleared(ctx, timeout=120)
            click.secho("✓ lucida.to joignable" if ok else "⚠ Cloudflare non franchi",
                        fg="green" if ok else "yellow")
    except Exception as e:
        click.secho(f"✗ Échec lancement navigateur: {e}", fg="red")


@cli.command()
def doctor():
    """Diagnostique l'environnement et la joignabilité de lucida.to."""
    asyncio.run(_doctor())


async def _debug(query, service, country, item, headless):
    from urllib.parse import urlencode

    svc = normalize_service(service)
    cc = country or default_country(svc)
    q = " ".join(query) or "red hot chili peppers"
    if item:
        target, tag = f"{LUCIDA}/?{urlencode({'url': item, 'country': cc})}", "item"
    else:
        target = f"{LUCIDA}/search?{urlencode({'service': svc, 'country': cc, 'query': q})}"
        tag = "search"

    async with lucida_context(headless=headless, downloads_dir=DEFAULT_OUT) as ctx:
        try:
            if not await ensure_cleared(ctx, timeout=180):
                click.secho("Cloudflare non franchi.", fg="red")
                return
        except BrowserClosed:
            click.secho(_CLOSED_HINT, fg="red")
            return
        page = await get_page(ctx)
        click.echo(f"Navigation: {target}")
        try:
            await page.goto(target, wait_until="networkidle", timeout=60_000)
        except Exception as e:
            click.echo(f"goto: {e}")
        await page.wait_for_timeout(4000)
        html = await page.content()
        with open(os.path.join(ROOT, f"{tag}_debug.html"), "w", encoding="utf-8") as f:
            f.write(html)
        try:
            await page.screenshot(path=os.path.join(ROOT, f"{tag}_debug.png"), full_page=True)
        except Exception:
            pass
        click.echo(f"  HTML {len(html)} octets -> {tag}_debug.html (+ .png)")
        for m in ('const data = [', 'songs-list-row', 'button.download-button',
                  'download-button'):
            click.echo(f"  marqueur {m!r}: {'OUI' if m in html else 'non'}")
        click.secho("Fenêtre laissée OUVERTE. Entrée pour fermer.", fg="yellow")
        try:
            await asyncio.to_thread(input)
        except Exception:
            pass


@cli.command("debug")
@click.argument("query", nargs=-1)
@click.option("-s", "--service", default="qobuz", help="Service à diagnostiquer (def: qobuz).")
@click.option("--country", default=None, help="Code pays (def: US pour qobuz).")
@click.option("--item", default=None, help="Charger cette URL d'item au lieu d'une recherche.")
@click.option("--headless", is_flag=True, help="(dev) forcer le headless, normalement bloqué par CF.")
def debug_cmd(query, service, country, item, headless):
    """(dev) Diagnostic : ouvre une page, capture HTML + screenshot, garde la fenêtre ouverte."""
    asyncio.run(_debug(query, service, country, item, headless))


if __name__ == "__main__":
    cli()

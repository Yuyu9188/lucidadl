"""Pick the best search result for a query instead of blindly taking the first.

Search results often rank remixes / karaoke / tribute / "renditions" versions above
the real track, so we score each candidate on title+artist match and penalise
unwanted variants (unless the query explicitly asked for them)."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

# Whole-word markers of an unwanted variant.
_BAD_TOKENS = {
    "remix", "mix", "karaoke", "cover", "covers", "instrumental", "nightcore",
    "acoustic", "rendition", "renditions", "tribute", "lullaby", "parody",
    "workout", "reverb", "slowed", "sped", "8d", "acapella", "acappella",
}
# Multi-word markers.
_BAD_PHRASES = (
    "sped up", "made famous", "originally performed", "in the style of",
    "made popular", "8d audio", "piano version", "string quartet", "tribute to",
)


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", " ", (s or "").lower())


def _tokens(s: str) -> set:
    return set(_norm(s).split())


def _split_query(q: str):
    if " - " in q:
        a, t = q.split(" - ", 1)
        return a.strip(), t.strip()
    return "", q.strip()


def score(query: str, item: Dict[str, str]) -> float:
    artist_q, title_q = _split_query(query)
    q_tokens = _tokens(query)
    title = item.get("title", "")
    artist = item.get("artist", "")
    ctx = item.get("context") or title
    t_tokens = _tokens(title)
    a_tokens = _tokens(artist)                            # explicit artist field (h2)
    c_tokens = _tokens(ctx) | a_tokens

    s = 0.0
    tq = _tokens(title_q)
    if tq:
        s += 3.0 * len(tq & t_tokens) / len(tq)          # title word overlap
    if _norm(title_q) and _norm(title_q) in _norm(title):
        s += 2.0                                          # exact-ish title
    aq = _tokens(artist_q)
    if aq:
        # Prefer the explicit artist field; fall back to the row context.
        artist_hits = len(aq & a_tokens) / len(aq) if a_tokens else 0.0
        ctx_hits = len(aq & c_tokens) / len(aq)
        s += 3.0 * artist_hits + 1.0 * ctx_hits           # artist match (weighted)
        if a_tokens and not (aq & a_tokens):
            s -= 2.0                                       # wrong artist → strong penalty

    blob_tokens = t_tokens | c_tokens
    for b in _BAD_TOKENS:
        if b in blob_tokens and b not in q_tokens:
            s -= 1.5
    blob = _norm(title) + " " + _norm(ctx)
    nq = _norm(query)
    for ph in _BAD_PHRASES:
        if ph in blob and ph not in nq:
            s -= 1.5

    if title_q:
        s -= 0.01 * abs(len(title) - len(title_q))        # prefer closest length
    return s


def pick_best(query: str, items: List[Dict[str, str]]) -> Optional[str]:
    """Return the URL of the best-scoring candidate (ties → earliest result)."""
    if not items:
        return None
    best_i, best_s = 0, None
    for i, it in enumerate(items):
        sc = score(query, it)
        if best_s is None or sc > best_s:
            best_s, best_i = sc, i
    return items[best_i].get("url")

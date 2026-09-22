"""Album-name fuzzy matcher — used by all run modes to filter text-search candidates."""

from __future__ import annotations

import difflib
import unicodedata


def _normalize(text: str) -> str:
    """Lowercase, strip, NFC-normalize unicode."""
    return unicodedata.normalize("NFC", text.strip().casefold())


def _token_sort(text: str) -> str:
    """Split into words, sort, rejoin — handles transposed word ordering."""
    return " ".join(sorted(text.split()))


def album_name_matches(
    query_album: str,
    candidate_title: str,
    threshold: float = 0.85,
) -> float:
    """Return match score (0.0–1.0) between *query_album* and *candidate_title*.

    Strategy (short-circuits on exact match):
    1. Case-insensitive exact match (NFC-normalized) → 1.0
    2. Case-insensitive substring match (one contains the other) → 0.95
    3. Token-sorted comparison → 0.90
    4. Levenshtein ratio via ``difflib.SequenceMatcher`` → ratio
    5. Below threshold → 0.0
    """
    if not query_album and not candidate_title:
        return 1.0
    if not query_album or not candidate_title:
        return 0.0

    q = _normalize(query_album)
    c = _normalize(candidate_title)

    # 1 — exact match
    if q == c:
        return 1.0

    # 2 — substring match
    if q in c or c in q:
        return 0.95

    # 3 — token-sorted match
    if _token_sort(q) == _token_sort(c):
        return 0.90

    # 4 — Levenshtein ratio
    ratio = difflib.SequenceMatcher(None, q, c).ratio()
    return ratio if ratio >= threshold else 0.0

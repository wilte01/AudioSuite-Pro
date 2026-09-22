"""Candidate filtering and ranking — applied by every API module before selection."""

from __future__ import annotations

from collections.abc import Callable

from .matcher import album_name_matches
from .ranker import RankedCandidate, get_image_dimensions, rank_by_area

_FILTER_LOG_FORMAT = (
    '    {status} "{title}" {width:>4}×{height:<4}  → match: {match_str}  {result}'
)


def _log_candidate(
    log: Callable[[str], None],
    title: str,
    width: int,
    height: int,
    match_score: float,
    passed: bool,
    reason: str,
) -> None:
    score_str = f"{match_score:.3f}" if match_score >= 0 else "n/a"
    status = "✓" if passed else "✗"
    result = "passed" if passed else reason
    log(
        _FILTER_LOG_FORMAT.format(
            status=status,
            title=title,
            width=width,
            height=height,
            match_str=score_str,
            result=result,
        )
    )


def filter_and_rank(
    raw_items: list[dict[str, str]],
    *,
    query_album: str,
    source_name: str,
    is_trusted_source: bool,
    min_dimension: int = 500,
    match_threshold: float = 0.85,
    log: Callable[[str], None],
) -> list[RankedCandidate]:
    """Process raw API results into filtered, ranked candidates.

    Steps for *all* sources:
    1. Resolve image dimensions for each candidate.
    2. Reject candidates below *min_dimension* on either axis.
    3. For untrusted sources (Deezer/iTunes): run album-name fuzzy match;
       reject candidates below *match_threshold*.
    4. For trusted sources (Fanart.tv): skip name filtering; match_score = 1.0.
    5. Sort survivors by area descending.
    6. Log audit of every candidate.

    Returns empty list if no candidates pass all guardrails.
    """
    if not raw_items:
        log(f"  → {source_name}: no raw candidates returned")
        return []

    log(f"  → {source_name}: {len(raw_items)} raw candidate(s)")

    passed: list[RankedCandidate] = []

    for i, item in enumerate(raw_items):
        url = item.get("url", "")
        title = item.get("title", "")
        if not url:
            _log_candidate(log, title or "(no title)", 0, 0, -1.0, False, "no URL")
            continue

        dims = get_image_dimensions(url)
        if dims is None:
            _log_candidate(log, title, 0, 0, -1.0, False, "unreadable dimensions")
            continue

        w, h = dims

        if w < min_dimension or h < min_dimension:
            _log_candidate(
                log,
                title,
                w,
                h,
                -1.0,
                False,
                f"below min dimension ({min_dimension}px)",
            )
            continue

        if is_trusted_source:
            match_score = 1.0
            _log_candidate(log, title, w, h, match_score, True, "passed")
            score = float(w * h)
            passed.append(
                RankedCandidate(
                    index=i,
                    url=url,
                    title=title,
                    width=w,
                    height=h,
                    score=score,
                    match_score=match_score,
                )
            )
        else:
            match_score = album_name_matches(query_album, title, match_threshold)
            if match_score <= 0.0:
                _log_candidate(
                    log,
                    title,
                    w,
                    h,
                    match_score,
                    False,
                    f"album name mismatch (<{match_threshold})",
                )
                continue
            _log_candidate(log, title, w, h, match_score, True, "passed")
            score = float(w * h)
            passed.append(
                RankedCandidate(
                    index=i,
                    url=url,
                    title=title,
                    width=w,
                    height=h,
                    score=score,
                    match_score=match_score,
                )
            )

    ranked = rank_by_area(passed)
    log(f"    Ranked: {len(ranked)} candidate(s) passed guardrails")
    return ranked

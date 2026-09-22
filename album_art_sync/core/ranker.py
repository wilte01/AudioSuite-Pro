"""Image dimension detection, resolution-based ranking, and candidate type."""

from __future__ import annotations

import struct
from dataclasses import dataclass

import requests

from ..config.settings import CONFIG


@dataclass(frozen=True)
class RankedCandidate:
    """A candidate that has passed all guardrails and been quality-ranked."""

    index: int
    url: str
    title: str
    width: int
    height: int
    score: float
    match_score: float


_JPEG_SOI = b"\xff\xd8"
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _read_chunk(url: str, offset: int = 0, size: int = 2048) -> bytes | None:
    """Fetch a byte range of an image URL via Range header."""
    headers = {"Range": f"bytes={offset}-{offset + size - 1}"}
    try:
        # Bandit B113 only accepts a literal timeout value; the real (non-None,
        # config-driven) timeout is present here, so the static detector cannot
        # see it and is silenced explicitly.
        resp = requests.get(  # nosec B113
            url, headers=headers, timeout=CONFIG["REQUEST_TIMEOUT"], stream=True
        )
        resp.raise_for_status()
        return resp.content
    except requests.RequestException:
        return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Parse JPEG dimensions from image header (first ~2 KB)."""
    if not data.startswith(_JPEG_SOI):
        return None
    pos = 2
    while pos < len(data) - 1:
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == 0xC0 or marker == 0xC2:
            if pos + 9 < len(data):
                height = struct.unpack_from(">H", data, pos + 5)[0]
                width = struct.unpack_from(">H", data, pos + 7)[0]
                return width, height
            return None
        seg_len = struct.unpack_from(">H", data, pos + 2)[0]
        pos += 2 + seg_len
    return None


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Parse PNG dimensions from IHDR chunk (bytes 16–24)."""
    if not data.startswith(_PNG_SIG):
        return None
    if len(data) < 24:
        return None
    width = struct.unpack_from(">I", data, 16)[0]
    height = struct.unpack_from(">I", data, 20)[0]
    return width, height


def get_image_dimensions(url: str) -> tuple[int, int] | None:
    """Return (width, height) of an image URL by reading its header.

    Uses a ranged GET to minimise transfer: ~2 KB for JPEG,
    ~100 bytes for PNG.  Returns None on any failure.
    """
    chunk = _read_chunk(url, 0, 100)
    if chunk is None:
        return None
    if chunk.startswith(_PNG_SIG):
        return _png_dimensions(chunk)
    if chunk.startswith(_JPEG_SOI):
        full = _read_chunk(url, 0, 2048)
        if full is None:
            return None
        return _jpeg_dimensions(full)
    return None


def rank_by_area(candidates: list[RankedCandidate]) -> list[RankedCandidate]:
    """Sort candidates by match score descending, then pixel area descending.

    When all candidates have the same resolution (common with 1000×1000
    artwork from Deezer/iTunes), match_score breaks the tie so the best
    album-name match is ranked first.
    """
    return sorted(
        candidates,
        key=lambda c: (c.match_score, c.score),
        reverse=True,
    )

"""
sidecar.py — local `.lrc` sidecar lyric provider.

Reads a ``.lrc`` file sitting next to the audio file (same stem, ``.lrc``
extension).  No network access, no licence issue — the file is already on
the user's disk.

The provider overrides :meth:`search` with an additional keyword-only
``file_path`` parameter carrying the audio file's full path.  When
*file_path* is ``None`` (the caller did not supply one) the provider
returns ``None`` — it cannot locate a sidecar without knowing the audio
file's position on disk.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from audio_suite_shared.lrc_handler import (
    LrcDocument,
    LrcParseError,
    generate_lrc,
    parse_lrc,
)

from .base import LyricProvider, LyricResult

logger = logging.getLogger(__name__)

_TIMESTAMPS_ONLY = re.compile(r"\[[^\]]*\]")


def _strip_timestamps(lrc_text: str) -> str:
    """Remove ``[mm:ss.xx]`` timestamps from *lrc_text*, returning plain lyrics.

    Args:
        lrc_text: LRC-formatted synced lyric text.

    Returns:
        Plain-text lyrics with timestamps removed and leading/trailing
        whitespace stripped from each line.
    """
    plain_lines: list[str] = []
    for line in lrc_text.splitlines():
        stripped = _TIMESTAMPS_ONLY.sub("", line).strip()
        if stripped:
            plain_lines.append(stripped)
    return "\n".join(plain_lines)


class SidecarProvider(LyricProvider):
    """Reads lyrics from a local ``.lrc`` sidecar file.

    The sidecar is located by replacing the audio file's extension with
    ``.lrc``.  For example, ``track01.mp3`` → ``track01.lrc`` in the same
    directory.
    """

    name = "sidecar"

    def search(
        self,
        artist: str,
        title: str,
        *,
        timeout: float = 10.0,
        file_path: str | None = None,
    ) -> LyricResult | None:
        """Look up lyrics from a local ``.lrc`` sidecar.

        Args:
            artist: Artist name read from the file's tags (unused by this
                provider — the sidecar is resolved by file path, not by
                metadata).
            title: Track title read from the file's tags (unused).
            timeout: Per-request timeout in seconds (unused — no I/O
                blocking beyond the local read).
            file_path: Full path to the audio file.  The provider derives
                the sidecar path by replacing the extension with ``.lrc``.

        Returns:
            A :class:`LyricResult` with synced and/or plain lyrics when
            a valid ``.lrc`` sidecar exists, or ``None`` when no sidecar
            is found or *file_path* is not supplied.
        """
        if file_path is None:
            logger.debug("sidecar: no file_path supplied — skipping")
            return None

        sidecar = Path(file_path).with_suffix(".lrc")
        if not sidecar.is_file():
            logger.debug("sidecar: no .lrc file at %s", sidecar)
            return None

        try:
            raw_text = sidecar.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("sidecar: could not read %s: %s", sidecar, exc)
            return None

        try:
            document: LrcDocument = parse_lrc(raw_text)
        except LrcParseError as exc:
            logger.warning("sidecar: malformed .lrc at %s: %s", sidecar, exc)
            return None

        if not document.lines:
            logger.debug("sidecar: .lrc at %s has no lyric lines", sidecar)
            return None

        synced_text: str | None = None
        plain_text: str | None = None

        # Re-generate the LRC text from the parsed document so the output
        # is canonical (timestamps normalised, meta tags stripped).
        synced_text = generate_lrc(
            [(line.timestamp_ms, line.text) for line in document.lines],
            metadata=None,  # do not re-emit meta tags into the tag
        )

        plain_text = _strip_timestamps(synced_text)
        if not plain_text:
            plain_text = None

        meta_artist = document.metadata.artist
        meta_title = document.metadata.title

        logger.debug("sidecar: found %d lines in %s", len(document.lines), sidecar)

        return LyricResult(
            provider_name=self.name,
            synced_lyrics=synced_text,
            plain_lyrics=plain_text,
            track_name=meta_title,
            artist_name=meta_artist,
        )

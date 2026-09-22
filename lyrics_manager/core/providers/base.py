"""
base.py — Lyric provider protocol and shared data containers.

Defines :class:`LyricResult` (a provider's answer for one track) and the
:class:`LyricProvider` abstract base class every lyric source implements.
The separation of ``search`` from the registry keeps the fetch pipeline
(files → tags → lookup → embed) provider-agnostic.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

from audio_suite_shared.exceptions import AudioSuiteError


class LyricProviderError(AudioSuiteError):
    """Raised when a lyric provider cannot complete a lookup.

    Distinct from "no match found": transport failures, timeouts, and
    malformed responses surface as this error so the processor can report
    them as per-file errors instead of silently skipping.
    """


@dataclass(frozen=True)
class LyricResult:
    """Lyric content resolved for a single track.

    Attributes:
        provider_name: Identifier of the provider that produced the result.
        synced_lyrics: LRC-formatted synced lyrics, or None if the source
            only has plain text (or none at all).
        plain_lyrics: Unsynced (plain text) lyrics, or None if the source
            has no text for the track.
        track_name: Title as returned by the source (may differ from the
            file tag, e.g. case/punctuation normalisation).
        artist_name: Artist as returned by the source.
    """

    provider_name: str
    synced_lyrics: str | None = None
    plain_lyrics: str | None = None
    track_name: str | None = None
    artist_name: str | None = None

    @property
    def has_lyrics(self) -> bool:
        """Whether the result carries any lyric content."""
        return self.synced_lyrics is not None or self.plain_lyrics is not None


class LyricProvider(abc.ABC):
    """Abstract base class for lyric sources.

    Implementations are stateless between calls: every :meth:`search`
    performs a fresh lookup so the processor can share one instance across
    worker threads safely.
    """

    name: str = ""

    @abc.abstractmethod
    def search(
        self,
        artist: str,
        title: str,
        *,
        timeout: float = 10.0,
    ) -> LyricResult | None:
        """Look up lyrics for a track.

        Args:
            artist: Artist name read from the file's tags.
            title: Track title read from the file's tags.
            timeout: Per-request timeout in seconds.

        Returns:
            A :class:`LyricResult` when the source has lyric text for the
            track, or None when the source reports no match.

        Raises:
            LyricProviderError: On transport failure, timeout, or a
                response the provider cannot interpret.
        """

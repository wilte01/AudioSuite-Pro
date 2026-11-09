"""Build a :class:`FingerprintRecord` from one file on disk.

All the format knowledge this tool needs lives here, and each part is borrowed
rather than re-implemented:

* the fingerprint comes from ``audio_fingerprinter.core.fingerprinter`` — the one
  fpcalc resolution path in the tree (explicit path, ``FPCALC``, PATH, then the
  committed ``fpcalc.exe``) — asked for ``-raw`` so the sub-fingerprints are
  comparable words instead of AcoustID's compressed payload;
* the stream properties come from ``mutagen``, which reads them uniformly for
  every container the suite supports without decoding the audio;
* ``lossless`` comes from the shared extension table, and the tags come from the
  shared :func:`audio_suite_shared.tag_helper_reader.read_artist_title` reader,
  which already returns ``("Unknown", "Unknown")`` rather than raising.

Changed in 2.6.0: adds ``build_properties_record``, the same measured record
without the fpcalc fingerprint, so an exact-only run never calls the
fingerprint calculator (F-E9).

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import logging
import os

import mutagen

from audio_fingerprinter.core.fingerprinter import generate_fingerprint
from audio_suite_shared.audio_formats import is_lossless_extension
from audio_suite_shared.tag_helper_reader import read_artist_title

from .fingerprint_distance import decode_words
from .models import FingerprintRecord

logger = logging.getLogger(__name__)

#: What the shared tag reader returns when a file has no readable artist/title.
_UNKNOWN = "Unknown"


def _stream_properties(path: str, duration: float, size: int) -> tuple[int, int, float]:
    """Return ``(sample_rate, channels, bitrate_kbps)`` for *path*.

    A container mutagen cannot describe is not an error: the record keeps zeros,
    which simply ranks it below a copy whose properties are known.

    Args:
        path: Audio file path.
        duration: Duration in seconds, from fpcalc.
        size: File size in bytes, used as the bitrate fallback.

    Returns:
        The three measured properties.
    """
    sample_rate = 0
    channels = 0
    bitrate_kbps = 0.0
    try:
        audio = mutagen.File(path)
        info = getattr(audio, "info", None)
        if info is not None:
            sample_rate = int(getattr(info, "sample_rate", 0) or 0)
            channels = int(getattr(info, "channels", 0) or 0)
            bitrate_kbps = float(getattr(info, "bitrate", 0) or 0) / 1000.0
    # Changed in 2.4.1: BLE001 triage (WP-7 of
    # PLAN_2026-11-03_2.4.1_stop_the_drift.md, D-31).
    except (mutagen.MutagenError, OSError, ValueError) as exc:
        logger.debug("mutagen could not read stream info for %s: %s", path, exc)
    if bitrate_kbps <= 0.0 and duration > 0:
        bitrate_kbps = (size * 8.0) / duration / 1000.0
    return sample_rate, channels, bitrate_kbps


def _clean_tag(value: str) -> str:
    """Return *value* with the shared reader's ``Unknown`` sentinel removed.

    Args:
        value: A tag string from the shared reader.

    Returns:
        The tag, or an empty string when it was absent.
    """
    return "" if value == _UNKNOWN else value


def _measured_duration(path: str) -> float:
    """Return the file's declared duration in seconds, or ``0.0``.

    An exact-only run still needs a duration for the keeper rule (a truncated
    copy must lose to a complete one) and for the report, but it must not pay
    for a fingerprint to learn it.  Mutagen already reads the container's own
    header for every other property, so it answers this too.

    Args:
        path: Audio file path.

    Returns:
        The duration in seconds, or ``0.0`` when the container does not say.
    """
    try:
        audio = mutagen.File(path)
        info = getattr(audio, "info", None)
        return float(getattr(info, "length", 0) or 0)
    except (mutagen.MutagenError, OSError, ValueError) as exc:
        logger.debug("mutagen could not read the duration of %s: %s", path, exc)
        return 0.0


def build_properties_record(path: str, mtime: float, size: int) -> FingerprintRecord:
    """Collect everything a keeper decision needs except the fingerprint.

    Args:
        path: Audio file path.
        mtime: The file's ``st_mtime``, stored as half the freshness stamp.
        size: The file's ``st_size``.

    Returns:
        A record whose ``words`` are empty — it is never clustered by
        fingerprint, only hashed and grouped by :mod:`duplicate_finder.core.exact`.
    """
    duration = _measured_duration(path)
    sample_rate, channels, bitrate_kbps = _stream_properties(path, duration, size)
    artist, title = read_artist_title(path)
    return FingerprintRecord(
        path=os.path.normpath(path),
        duration=duration,
        words=(),
        size=int(size),
        mtime=float(mtime),
        sample_rate=sample_rate,
        channels=channels,
        bitrate_kbps=bitrate_kbps,
        lossless=is_lossless_extension(path),
        artist=_clean_tag(artist),
        title=_clean_tag(title),
    )


def build_record(path: str, mtime: float, size: int) -> FingerprintRecord:
    """Fingerprint *path* and collect the properties a keeper is chosen by.

    Args:
        path: Audio file path.
        mtime: The file's ``st_mtime``, stored as half the freshness stamp.
        size: The file's ``st_size``.

    Returns:
        The record.

    Raises:
        FingerprintToolError: If fpcalc cannot produce a fingerprint — the
            caller counts that as a skipped file rather than a fatal error.
        FingerprintFormatError: If fpcalc's output is not a word array.
    """
    fingerprint = generate_fingerprint(path, raw=True)
    words = decode_words(fingerprint.fingerprint)
    sample_rate, channels, bitrate_kbps = _stream_properties(
        path, fingerprint.duration, size
    )
    artist, title = read_artist_title(path)
    return FingerprintRecord(
        path=os.path.normpath(path),
        duration=float(fingerprint.duration),
        words=words,
        size=int(size),
        mtime=float(mtime),
        sample_rate=sample_rate,
        channels=channels,
        bitrate_kbps=bitrate_kbps,
        lossless=is_lossless_extension(path),
        artist=_clean_tag(artist),
        title=_clean_tag(title),
    )

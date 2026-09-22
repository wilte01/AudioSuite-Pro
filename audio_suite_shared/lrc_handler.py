"""
lrc_handler.py — Parse, generate and validate LRC (synced lyrics) files.

Part of audio_suite_shared. Provides a pure-text LRC layer: timestamped lyric
lines of the form ``[mm:ss.xx]text`` plus optional ``[ti:]``/``[ar:]``/
``[al:]``/``[by:]``/``[offset:]`` meta tags.

The embedding of LRC text into audio tag containers (ID3 SYLT frames for MP3,
Vorbis ``SYNCEDLYRICS`` comments for FLAC/OGG, ...) lives in the tag helpers
(``tag_helper_base`` / ``tag_helper_reader`` / ``tag_helper_writer``); this
module has no audio or mutagen imports.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .exceptions import AudioSuiteError

_TIMESTAMP_RE = re.compile(r"^(\d{1,3}):([0-5]\d)(?:\.(\d{1,2}))?$")
_HMS_TIMESTAMP_RE = re.compile(r"^(\d{1,3}):([0-5]\d):([0-5]\d)(?:\.(\d{1,2}))?$")
_TOKEN_RE = re.compile(r"^\[([^\]]*)\]")
_META_RE = re.compile(r"^([A-Za-z]+):(.*)$")
_OFFSET_RE = re.compile(r"^[+-]?\d+$")

# Meta keys stored on LrcMetadata. Any other ``[key:value]`` token (e.g. the
# common ``[re:...]`` / ``[ve:...]`` editor tags) is recognised and ignored.
_META_KEY_TO_ATTR: dict[str, str] = {
    "ti": "title",
    "ar": "artist",
    "al": "album",
    "by": "creator",
}


class LrcParseError(AudioSuiteError):
    """Raised when LRC text cannot be parsed (bad timestamp, no timestamp)."""


@dataclass(frozen=True)
class LrcLine:
    """One synced lyric line.

    Attributes:
        timestamp_ms: Start time of the lyric, in milliseconds.
        text: Lyric text without the leading timestamp.
    """

    timestamp_ms: int
    text: str


@dataclass(frozen=True)
class LrcMetadata:
    """Optional LRC file meta tags.

    Attributes:
        title: ``[ti:...]`` value, or None.
        artist: ``[ar:...]`` value, or None.
        album: ``[al:...]`` value, or None.
        creator: ``[by:...]`` value, or None.
        offset_ms: ``[offset:+/-N]`` value in milliseconds, 0 when absent.
    """

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    creator: str | None = None
    offset_ms: int = 0


@dataclass(frozen=True)
class LrcDocument:
    """A fully parsed LRC document.

    Attributes:
        metadata: Parsed meta tags (all optional).
        lines: Lyric lines in the order they appeared in the source text.
    """

    metadata: LrcMetadata
    lines: tuple[LrcLine, ...]


def _parse_timestamp_token(token: str) -> int | None:
    """Convert a ``[mm:ss(.xx)]`` or ``[hh:mm:ss(.xx)]`` timestamp to ms.

    The fractional part after the seconds is interpreted as hundredths of a
    second (the LRC spec): ``.5`` is 0.05 s (50 ms), ``.50`` is 0.50 s.

    Args:
        token: Timestamp body without the surrounding brackets.

    Returns:
        Milliseconds since track start, or None if *token* is not a valid
        LRC timestamp.
    """
    match = _HMS_TIMESTAMP_RE.match(token)
    if match:
        hours, minutes, seconds, fraction = match.groups()
    else:
        match = _TIMESTAMP_RE.match(token)
        if not match:
            return None
        hours, minutes, seconds, fraction = (None, *match.groups())
    ms = (int(minutes) * 60 + int(seconds)) * 1000
    if hours is not None:
        ms += int(hours) * 3_600_000
    if fraction:
        ms += int(fraction) * 10
    return ms


def format_timestamp(ms: int) -> str:
    """Format a millisecond timestamp as ``mm:ss.xx``.

    Minutes are not folded into hours: a 62-minute timestamp renders as
    ``62:03.00``, matching extended-minute LRC files.

    Args:
        ms: Milliseconds since track start. Must be non-negative.

    Returns:
        Formatted timestamp string.

    Raises:
        ValueError: If *ms* is negative.
    """
    if ms < 0:
        raise ValueError(f"timestamp cannot be negative: {ms}")
    minutes, remainder = divmod(ms, 60_000)
    seconds, rest = divmod(remainder, 1000)
    centiseconds = rest // 10
    return f"{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def parse_lrc(text: str) -> LrcDocument:
    """Parse LRC-format text into an :class:`LrcDocument`.

    Each lyric line is ``[mm:ss(.xx)]`` (or ``[hh:mm:ss(.xx)]``) optionally
    repeated, followed by the lyric text. A line with several timestamps
    produces one :class:`LrcLine` per timestamp. A line with no timestamp and
    no text (blank) is ignored; a non-blank line without a timestamp is an
    error. Unknown ``[key:value]`` meta tags and timestamp-only lines are
    ignored; ``[offset:]`` must be an integer and ``[ti:]``/``[ar:]``/
    ``[al:]``/``[by:]`` are stored on the returned metadata.

    Args:
        text: Raw LRC file contents (UTF-8). A leading BOM and CRLF line
            endings are tolerated.

    Returns:
        The parsed document. Lines preserve source order (timestamps are
        *not* sorted); use :func:`timestamps_ordered` to check ordering.

    Raises:
        LrcParseError: If a non-blank line carries text without any
            timestamp, or an ``[offset:]`` tag is not an integer.
    """
    meta_values: dict[str, str | None] = {
        attr: None for attr in _META_KEY_TO_ATTR.values()
    }
    lines: list[LrcLine] = []
    offset: int | None = None

    for line_number, raw_line in enumerate(text.lstrip("\ufeff").splitlines(), start=1):
        content = raw_line
        timestamps: list[int] = []
        while content.startswith("["):
            token_match = _TOKEN_RE.match(content)
            if not token_match:
                break
            token = token_match.group(1)
            body = content[token_match.end() :]
            ts = _parse_timestamp_token(token)
            if ts is not None:
                timestamps.append(ts)
            else:
                meta = _META_RE.match(token)
                if meta:
                    key, value = meta.group(1).lower(), meta.group(2)
                    if key == "offset":
                        if not _OFFSET_RE.match(value.strip()):
                            raise LrcParseError(
                                f"line {line_number}: invalid [offset:] value '{token}'"
                            )
                        offset = int(value.strip())
                    elif key in _META_KEY_TO_ATTR:
                        meta_values[_META_KEY_TO_ATTR[key]] = value
            content = body

        text_part = content.strip()
        if not text_part:
            continue
        if not timestamps:
            raise LrcParseError(
                f"line {line_number}: lyric text without a timestamp: '{text_part}'"
            )
        for ts in timestamps:
            lines.append(LrcLine(timestamp_ms=ts, text=text_part))

    return LrcDocument(
        metadata=LrcMetadata(
            title=meta_values.get("title"),
            artist=meta_values.get("artist"),
            album=meta_values.get("album"),
            creator=meta_values.get("creator"),
            offset_ms=offset if offset is not None else 0,
        ),
        lines=tuple(lines),
    )


def generate_lrc(
    lines: Iterable[tuple[int, str]],
    metadata: LrcMetadata | None = None,
) -> str:
    """Generate LRC text from timestamped lyric lines.

    Optional meta tags are emitted first (``[ti:]``/``[ar:]``/``[al:]``/
    ``[by:]`` followed by ``[offset:]`` when non-zero), then one
    ``[mm:ss.xx]text`` line per lyric.

    Args:
        lines: Iterable of ``(timestamp_ms, text)`` pairs in the desired
            output order.
        metadata: Optional meta tags to emit, or None.

    Returns:
        The LRC text (no trailing newline). Timestamp order is preserved as
        given; callers needing monotonic timestamps can use
        :func:`timestamps_ordered` to check first.
    """
    chunks: list[str] = []
    if metadata is not None:
        for key, value in (
            ("ti", metadata.title),
            ("ar", metadata.artist),
            ("al", metadata.album),
            ("by", metadata.creator),
        ):
            if value is not None:
                chunks.append(f"[{key}:{value}]")
        if metadata.offset_ms:
            chunks.append(f"[offset:{metadata.offset_ms:+d}]")
    for timestamp_ms, text in lines:
        chunks.append(f"[{format_timestamp(timestamp_ms)}]{text}")
    return "\n".join(chunks)


def timestamps_ordered(document: LrcDocument) -> bool:
    """Return True if all lyric timestamps are in non-decreasing order.

    Args:
        document: Parsed :class:`LrcDocument`.

    Returns:
        True when the timestamp of every line is >= the previous line's
        timestamp (empty and single-line documents are ordered).
    """
    previous: int | None = None
    for line in document.lines:
        if previous is not None and line.timestamp_ms < previous:
            return False
        previous = line.timestamp_ms
    return True

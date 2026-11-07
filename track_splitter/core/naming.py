"""naming.py — render an output filename from a pattern.

The pattern is a pure function of the track and its album tags, so the naming
surface is testable without a window or a file.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E4).
"""

from __future__ import annotations

import string

from audio_suite_shared.exceptions import AudioConfigValueError
from audio_suite_shared.security.input_validator import InputValidator

#: Fields a pattern may name.  ``{track:02d}`` is the usual spelling; the
#: number is passed as an int so any format spec that takes one works.
_PATTERN_FIELDS: frozenset[str] = frozenset({"track", "title", "album", "artist"})

#: Longest stem a pattern may produce.  The illegal characters themselves are
#: declared once, in ``InputValidator``, so this tool and the CUE splitter
#: cannot drift apart on what a legal filename is.
_MAX_STEM = 120


def _check_pattern(pattern: str) -> None:
    """Reject a pattern naming an unknown field or using a positional one.

    Raises:
        AudioConfigValueError: The pattern is empty, uses ``{}``, or names a
            field outside :data:`_PATTERN_FIELDS`.
    """
    if not pattern.strip():
        raise AudioConfigValueError("The naming pattern must not be empty.")
    for _literal, field_name, _spec, _conv in string.Formatter().parse(pattern):
        if field_name is None:
            continue
        if field_name == "" or field_name.isdigit():
            raise AudioConfigValueError(
                "The naming pattern needs named fields "
                f"({', '.join(sorted(_PATTERN_FIELDS))}), not positional ones.",
                context={"pattern": pattern},
            )
        root = field_name.split(".")[0].split("[")[0]
        if root not in _PATTERN_FIELDS:
            allowed = ", ".join(sorted(_PATTERN_FIELDS))
            raise AudioConfigValueError(
                f"Unknown naming field {{{root}}} in {pattern!r}; use {allowed}.",
                context={"pattern": pattern, "field": root},
            )


def safe_stem(name: str) -> str:
    """Return *name* usable as a filename stem on every supported platform.

    Args:
        name: The rendered name.

    Returns:
        The name with illegal characters replaced, whitespace collapsed and
        trailing dots or spaces removed.  An empty result becomes ``track``.
    """
    return InputValidator.sanitize_filename(
        name, fallback="track", max_length=_MAX_STEM
    )


def render_name(
    pattern: str,
    *,
    number: int,
    title: str,
    extension: str,
    album: str = "",
    artist: str = "",
) -> str:
    """Render one output filename from *pattern*.

    Args:
        pattern: A pattern such as ``"{track:02d} - {title}"``.
        number: 1-based track number.
        title: The track's title.
        extension: The output extension, with its leading dot.
        album: Album title from the source's tags (may be empty).
        artist: Album artist from the source's tags (may be empty).

    Returns:
        The filename, sanitised and carrying *extension*.

    Raises:
        AudioConfigValueError: The pattern names a field that does not exist.
    """
    _check_pattern(pattern)
    rendered = pattern.format(track=number, title=title, album=album, artist=artist)
    suffix = extension if extension.startswith(".") else f".{extension}"
    return f"{safe_stem(rendered)}{suffix.lower()}"

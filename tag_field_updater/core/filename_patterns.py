"""filename_patterns.py — Parse a filename into tag fields (F-01).

A library whose only metadata is in its filenames cannot be cleaned without a
spreadsheet.  This module is the *source* half of the fix: an ordered list of
patterns, tried in order, each capturing named fields from a filename.

The dialect is deliberately tiny — ``%field%`` placeholders separated by
literal text::

    %artist% - %title%            Artist - Title.flac
    %track%. %artist% - %title%   05. Artist - Title.flac
    %disc%-%track% %artist% - %title%   1-05 Artist - Title.flac

Rules that keep a wrong split from looking like a success:

* **The extension is not part of the match.** ``Artist - Title.flac`` is parsed
  as ``Artist - Title``; a title containing a dot is not truncated.
* **Numeric fields match digits only.** ``track``, ``disc`` and ``year`` are
  typed as numbers, which is what stops ``05 - Artist - Title`` from parsing as
  ``disc="05", track="-"`` under a space-separated disc/track pattern: a
  separator is not a number, so that pattern fails and the track-prefixed one
  gets its turn.
* **Only the last placeholder is greedy.** Earlier ones match as little as
  possible, so ``AC - DC - Song`` under ``%artist% - %title%`` yields
  ``artist="AC", title="DC - Song"`` — the first separator wins, which is the
  only split that keeps the whole remainder in the final field.
* **A placeholder must match at least one character**, so ``Artist - `` is a
  non-match rather than an empty title.
* **Patterns are ordered, and order is the disambiguator.** ``05 - Artist -
  Title`` under ``%artist% - %title%`` would call the track number the artist,
  so a library of numbered files lists its track-prefixed patterns first.
  :data:`DEFAULT_PATTERNS` is ordered that way.
* **An ambiguous pattern is rejected, not guessed.** Two adjacent placeholders
  (``%artist%%title%``), an unknown name, or a repeated name raise
  :class:`PatternError`, because each would produce a split the user did not
  describe.  The CLI validates the whole list before it runs, so a typo is an
  error message rather than a library of plausible wrong tags.

Changed in 2.2.0: new — the filename source of functional backlog F-01.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from audio_suite_shared.tag_helper import EDITABLE_FIELDS

#: Fields a pattern may capture: ``audio_suite_shared``'s editable tag fields,
#: taken from that set rather than copied, so every capture has a writer in
#: every supported format and a new editable field needs no second edit here.
PLACEHOLDERS: tuple[str, ...] = EDITABLE_FIELDS

_PLACEHOLDER_RE = re.compile(r"%([a-z_]+)%")

#: Fields that are numbers, matched as digits only.  A text match here would
#: swallow the separator (``track="-"``), which is the mis-parse class this
#: module exists to prevent.
NUMERIC_PLACEHOLDERS: frozenset[str] = frozenset({"track", "disc", "year"})

#: Patterns tried, in order, when the caller names none.  The bare
#: ``%artist% - %title%`` form is last on purpose: it matches a numbered
#: filename by calling the number the artist, so every prefixed form above it
#: must have its chance first.
DEFAULT_PATTERNS: tuple[str, ...] = (
    "%disc%-%track% %artist% - %title%",
    "%disc%-%track%. %artist% - %title%",
    "%disc% %track% %artist% - %title%",
    "%track%. %artist% - %title%",
    "%track% - %artist% - %title%",
    "%track% %artist% - %title%",
    "%artist% - %title%",
)


class PatternError(ValueError):
    """A filename pattern that cannot be used as written."""


@dataclass(frozen=True)
class ParsedFilename:
    """The outcome of matching one filename against the pattern list.

    Attributes:
        fields: Captured field values, in the order the pattern names them.
            Values are stripped; a field that would be blank is not present
            because the pattern could not have matched with it blank.
        pattern: The pattern that matched, so a dry run can show *why* a file
            parsed the way it did.
    """

    fields: dict[str, str]
    pattern: str


def validate_pattern(pattern: str) -> None:
    """Check that *pattern* is usable, raising :class:`PatternError` if not.

    Args:
        pattern: A candidate pattern.

    Raises:
        PatternError: If the pattern is empty, names no placeholder, names an
            unknown placeholder, repeats one, or places two adjacently (an
            ambiguous split).
    """
    if not pattern or not pattern.strip():
        raise PatternError("a filename pattern cannot be empty")

    names = _PLACEHOLDER_RE.findall(pattern)
    if not names:
        raise PatternError(
            f"pattern {pattern!r} names no field; expected at least one of "
            f"{', '.join('%' + name + '%' for name in PLACEHOLDERS)}"
        )

    unknown = [name for name in names if name not in PLACEHOLDERS]
    if unknown:
        raise PatternError(
            f"pattern {pattern!r} uses unknown field(s) "
            f"{', '.join(unknown)}; expected "
            f"{', '.join('%' + name + '%' for name in PLACEHOLDERS)}"
        )

    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise PatternError(
            f"pattern {pattern!r} repeats field(s) {', '.join(repeated)}; "
            "a repeated field has no single value to write"
        )

    # ``%artist%%title%`` would let the first field match a single character
    # and the rest become the second field: a split nobody described.
    for left, right in zip(names, names[1:], strict=False):
        if f"%{left}%%{right}%" in pattern:
            raise PatternError(
                f"pattern {pattern!r} puts %{left}% directly against %{right}% "
                "with no separator; the split would be ambiguous"
            )

    # Literal text must not contain an unclosed '%', which is almost always a
    # typo (``%artst%`` is caught above, ``50% %title%`` is not).
    leftover = _PLACEHOLDER_RE.sub("", pattern)
    if "%" in leftover:
        raise PatternError(
            f"pattern {pattern!r} has a '%' outside a placeholder; write a "
            "field as %name%"
        )


@lru_cache(maxsize=128)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile *pattern* into an anchored regular expression.

    The final placeholder is greedy and every earlier one is lazy, so the
    literal text after a placeholder decides where the value ends and the whole
    remainder stays with the last field.

    Args:
        pattern: A pattern validated by :func:`validate_pattern`.

    Returns:
        A compiled pattern that :meth:`re.Pattern.fullmatch` applies to a
        filename without its extension.

    Raises:
        PatternError: If the pattern is invalid.
    """
    validate_pattern(pattern)

    names = _PLACEHOLDER_RE.findall(pattern)
    last = names[-1]
    parts: list[str] = []
    cursor = 0
    for match in _PLACEHOLDER_RE.finditer(pattern):
        parts.append(re.escape(pattern[cursor : match.start()]))
        name = match.group(1)
        if name in NUMERIC_PLACEHOLDERS:
            group = f"(?P<{name}>\\d+)"
        elif name == last:
            group = f"(?P<{name}>.+)"
        else:
            group = f"(?P<{name}>.+?)"
        parts.append(group)
        cursor = match.end()
    parts.append(re.escape(pattern[cursor:]))
    return re.compile("".join(parts), re.UNICODE)


def validate_patterns(patterns: Sequence[str]) -> tuple[str, ...]:
    """Return *patterns* unchanged after validating each one.

    Args:
        patterns: Candidate patterns, in the order they will be tried.

    Returns:
        The same patterns as a tuple.

    Raises:
        PatternError: If any pattern is invalid.  The whole list is checked so
            a bad later pattern is reported before the run starts, not after
            it has already tagged files with the earlier ones.
    """
    for pattern in patterns:
        validate_pattern(pattern)
    return tuple(patterns)


def parse_filename(
    filename: str | os.PathLike[str], patterns: Sequence[str] | None = None
) -> ParsedFilename | None:
    """Parse one filename against *patterns*, first match wins.

    Args:
        filename: A path or bare filename.  Only its final component is
            matched, without its extension.
        patterns: Patterns to try in order; None uses
            :data:`DEFAULT_PATTERNS`.

    Returns:
        The captured fields and the pattern that matched, or None when no
        pattern matches — which callers report as a skip rather than guessing.

    Raises:
        PatternError: If a pattern is invalid.
    """
    stem = os.path.splitext(os.path.basename(os.fspath(filename)))[0]
    for pattern in DEFAULT_PATTERNS if patterns is None else patterns:
        match = compile_pattern(pattern).fullmatch(stem)
        if match is None:
            continue
        fields = {
            name: value.strip()
            for name, value in match.groupdict().items()
            if value is not None and value.strip()
        }
        return ParsedFilename(fields=fields, pattern=pattern)
    return None

"""Tests for the filename pattern parser (F-01).

The failure mode this source must not have is a **silent mis-parse**: a wrong
split writes plausible wrong tags, and afterwards the file looks tagged.  So
the table below is as much about the filenames that must *not* split the way a
naive rule would as about the ones that must.

* Ordering is what disambiguates a leading track number from an artist, and the
  default list is asserted to place the prefixed forms first.
* Numeric fields are typed as digits, so ``05 - Artist - Title`` cannot parse
  as ``disc="05", track="-"``.
* The first separator wins, so ``AC - DC - Song`` keeps ``DC - Song`` whole.
* An ambiguous pattern is rejected at validation time, not guessed at.

Changed in 2.2.0: new — F-01.
"""

from __future__ import annotations

import pytest

from audio_suite_shared.tag_helper import EDITABLE_FIELDS
from tag_field_updater.core.filename_patterns import (
    DEFAULT_PATTERNS,
    PLACEHOLDERS,
    PatternError,
    compile_pattern,
    parse_filename,
    validate_pattern,
    validate_patterns,
)

#: ``(filename, patterns or None, expected fields or None)``.  ``None`` for the
#: patterns means the defaults, which is what a run with no ``--pattern`` uses.
PARSE_TABLE: list[tuple[str, list[str] | None, dict[str, str] | None]] = [
    (
        "Artist - Title.flac",
        None,
        {"artist": "Artist", "title": "Title"},
    ),
    (
        "05. Artist - Title.mp3",
        None,
        {"track": "05", "artist": "Artist", "title": "Title"},
    ),
    # The negative that made the numeric field necessary: with a text-typed
    # track, the space-separated disc/track pattern swallowed the dash.
    (
        "05 - Artist - Title.mp3",
        None,
        {"track": "05", "artist": "Artist", "title": "Title"},
    ),
    (
        "05 Artist - Title.mp3",
        None,
        {"track": "05", "artist": "Artist", "title": "Title"},
    ),
    (
        "1-05 Artist - Title.flac",
        None,
        {"disc": "1", "track": "05", "artist": "Artist", "title": "Title"},
    ),
    (
        "1-05. Artist - Title.flac",
        None,
        {"disc": "1", "track": "05", "artist": "Artist", "title": "Title"},
    ),
    # Only the first separator separates: the rest of the name stays a title.
    (
        "AC - DC - Song.flac",
        None,
        {"artist": "AC", "title": "DC - Song"},
    ),
    (
        "01. AC - DC - Song.flac",
        None,
        {"track": "01", "artist": "AC", "title": "DC - Song"},
    ),
    # The extension is not part of the match, even when the title has a dot.
    (
        "Artist - Title.flac",
        ["%artist% - %title%"],
        {"artist": "Artist", "title": "Title"},
    ),
    (
        "Artist - Pt. 2.mp3",
        ["%artist% - %title%"],
        {"artist": "Artist", "title": "Pt. 2"},
    ),
    (
        "NoSeparator.flac",
        None,
        None,
    ),
    (
        "",
        None,
        None,
    ),
    (
        "Artist - Title 1999.flac",
        None,
        {"artist": "Artist", "title": "Title 1999"},
    ),
    (
        "Artist - Title 1999.flac",
        ["%artist% - %title% %year%"],
        {"artist": "Artist", "title": "Title", "year": "1999"},
    ),
    # A numeric field will not match a word, so a pattern that starts with one
    # simply does not apply.
    (
        "Unknown - Artist - Title.flac",
        ["%track% - %artist% - %title%"],
        None,
    ),
    # Surrounding whitespace is trimmed rather than written into the tag.
    (
        "  Artist   -   Title .flac",
        ["%artist% - %title%"],
        {"artist": "Artist", "title": "Title"},
    ),
    (
        "08_bassline.flac",
        ["%track%_%title%"],
        {"track": "08", "title": "bassline"},
    ),
]


@pytest.mark.parametrize(("filename", "patterns", "expected"), PARSE_TABLE)
def test_parse_table(
    filename: str, patterns: list[str] | None, expected: dict[str, str] | None
) -> None:
    parsed = parse_filename(filename, patterns)
    assert (parsed.fields if parsed else None) == expected


class TestParseContract:
    def test_placeholders_are_the_writable_fields(self) -> None:
        """Every capturable field must have a writer — one source of truth."""
        assert PLACEHOLDERS == EDITABLE_FIELDS

    def test_a_match_reports_the_pattern_that_matched(self) -> None:
        parsed = parse_filename("05. Artist - Title.mp3")
        assert parsed is not None
        assert parsed.pattern == "%track%. %artist% - %title%"

    def test_default_order_puts_prefixed_forms_before_the_bare_one(self) -> None:
        """The bare form would call a track number the artist."""
        assert DEFAULT_PATTERNS[-1] == "%artist% - %title%"
        assert all("%track%" in pattern for pattern in DEFAULT_PATTERNS[:-1])

    def test_the_first_matching_pattern_wins(self) -> None:
        parsed = parse_filename(
            "Artist - Title.flac",
            ["%track% %title%", "%artist% - %title%"],
        )
        assert parsed is not None
        assert parsed.pattern == "%artist% - %title%"
        assert parsed.fields == {"artist": "Artist", "title": "Title"}

    def test_a_named_path_is_matched_by_its_last_component(self) -> None:
        parsed = parse_filename("D:/Music/Album/Artist - Title.flac")
        assert parsed is not None
        assert parsed.fields == {"artist": "Artist", "title": "Title"}


class TestValidation:
    @pytest.mark.parametrize(
        "pattern",
        [
            "",
            "   ",
            "Artist - Title",
            "%artst% - %title%",
            "%artist% %artist%",
            "%artist%%title%",
            "50% %title%",
        ],
    )
    def test_invalid_patterns_are_refused(self, pattern: str) -> None:
        with pytest.raises(PatternError):
            validate_pattern(pattern)

    @pytest.mark.parametrize(
        "pattern",
        [
            "%artist% - %title%",
            "%disc%-%track% %artist% - %title%",
            "%track%_%title%",
            "%artist%",
            "%year%-%title%",
        ],
    )
    def test_valid_patterns_are_accepted(self, pattern: str) -> None:
        validate_pattern(pattern)
        assert compile_pattern(pattern) is not None

    def test_the_whole_list_is_checked_before_anything_runs(self) -> None:
        with pytest.raises(PatternError, match="artst"):
            validate_patterns(["%artist% - %title%", "%artst%"])

    def test_the_error_names_the_field_it_does_not_accept(self) -> None:
        with pytest.raises(PatternError, match="%artst%"):
            validate_pattern("%artst% - %title%")

    def test_the_adjacent_placeholder_error_explains_the_ambiguity(self) -> None:
        with pytest.raises(PatternError, match="ambiguous"):
            validate_pattern("%artist%%title%")

    def test_compiling_an_invalid_pattern_raises(self) -> None:
        with pytest.raises(PatternError):
            compile_pattern("no fields here")

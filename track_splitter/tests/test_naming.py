"""Tests for the output-filename pattern.

Changed in 2.5.0: new module (F-E4).
"""

from __future__ import annotations

import pytest

from audio_suite_shared.exceptions import AudioConfigValueError
from track_splitter.core.naming import render_name, safe_stem


class TestRenderName:
    def test_default_pattern_numbers_the_track(self) -> None:
        name = render_name(
            "{track:02d} - {title}", number=3, title="Take 3", extension=".flac"
        )
        assert name == "03 - Take 3.flac"

    def test_album_and_artist_are_available(self) -> None:
        name = render_name(
            "{artist}/{album} {track}",
            number=2,
            title="t",
            extension=".wav",
            album="Live",
            artist="Band",
        )
        assert name == "Band_Live 2.wav"

    def test_a_leading_dot_extension_is_not_doubled(self) -> None:
        assert render_name("{track}", number=1, title="t", extension="mp3") == "1.mp3"

    @pytest.mark.parametrize(
        "pattern",
        ["{track:02d} {unknowable}", "{}", "{0}", "   "],
    )
    def test_an_unusable_pattern_is_refused(self, pattern: str) -> None:
        with pytest.raises(AudioConfigValueError):
            render_name(pattern, number=1, title="t", extension=".flac")


class TestSafeStem:
    def test_illegal_characters_are_replaced(self) -> None:
        assert safe_stem('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"

    def test_a_comma_and_an_apostrophe_survive(self) -> None:
        """A legal title keeps its punctuation; only illegal characters go."""
        name = render_name(
            "{track:02d} - {title}",
            number=3,
            title="Johnny, Don't Do It",
            extension="mp3",
        )

        assert name == "03 - Johnny, Don't Do It.mp3"

    def test_whitespace_is_collapsed_and_trimmed(self) -> None:
        assert safe_stem("  a    b  ") == "a b"

    def test_trailing_dots_and_spaces_are_removed(self) -> None:
        assert safe_stem("name. . ") == "name"

    def test_an_empty_name_falls_back(self) -> None:
        assert safe_stem("   ") == "track"

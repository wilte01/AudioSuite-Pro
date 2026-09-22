"""
Tests for genre_sync.core.genre_resolver and genre_sync.core.log_builder
Gap G-06: resolve_genre(), GenreResolution, build_log_lines()
"""

from genre_sync.core.genre_resolver import GenreResolution, _has_value, resolve_genre
from genre_sync.core.log_builder import build_log_lines

# ── GenreResolution dataclass ─────────────────────────────────────────────────


class TestGenreResolution:
    def test_has_required_slots(self):
        r = GenreResolution("Pop", "TITLE GENRE", "Title", "resolved")
        assert r.selected_genre == "Pop"
        assert r.selection_reason == "TITLE GENRE"
        assert r.derived_value == "Title"
        assert r.status == "resolved"

    def test_no_genre_result(self):
        r = GenreResolution(None, None, None, "no_genre")
        assert r.selected_genre is None
        assert r.status == "no_genre"


# ── resolve_genre — Rule 1: TitleGenre wins ───────────────────────────────────


class TestResolveGenreTitlePriority:
    def test_title_genre_wins_over_everything(self):
        result = resolve_genre(
            title_genre="Classical",
            artist_genre="Rock",
            album_genre="Jazz",
            album_artist_genre="Blues",
            album_artist="Various Artists",
        )
        assert result.selected_genre == "Classical"
        assert result.selection_reason == "TITLE GENRE"
        assert result.derived_value == "Title"
        assert result.status == "resolved"

    def test_title_genre_wins_when_others_absent(self):
        result = resolve_genre("Ambient", None, None, None, None)
        assert result.selected_genre == "Ambient"
        assert result.status == "resolved"

    def test_empty_title_genre_not_treated_as_present(self):
        result = resolve_genre(
            title_genre="",
            artist_genre=None,
            album_genre="Jazz",
            album_artist_genre=None,
            album_artist=None,
        )
        assert result.selected_genre == "Jazz"

    def test_whitespace_only_title_genre_not_treated_as_present(self):
        result = resolve_genre(
            title_genre="   ",
            artist_genre=None,
            album_genre="Jazz",
            album_artist_genre=None,
            album_artist=None,
        )
        assert result.selected_genre == "Jazz"
        assert result.selection_reason == "ALBUM GENRE"

    def test_none_title_genre_falls_through(self):
        result = resolve_genre(None, None, "Blues", None, None)
        assert result.selected_genre == "Blues"

    def test_non_breaking_space_title_genre_treated_as_absent(self):
        result = resolve_genre("\u00a0", None, "Jazz", None, None)
        assert result.selected_genre == "Jazz"
        assert result.selection_reason == "ALBUM GENRE"

    def test_zero_width_space_title_genre_treated_as_absent(self):
        result = resolve_genre("\u200b", None, "Jazz", None, None)
        assert result.selected_genre == "Jazz"

    def test_ideographic_space_title_genre_treated_as_absent(self):
        result = resolve_genre("\u3000", None, "Jazz", None, None)
        assert result.selected_genre == "Jazz"

    def test_bom_title_genre_treated_as_absent(self):
        result = resolve_genre("\ufeff", None, "Jazz", None, None)
        assert result.selected_genre == "Jazz"

    def test_mixed_unicode_whitespace_title_genre_treated_as_absent(self):
        result = resolve_genre("\u00a0\u200b\u3000\ufeff", None, "Jazz", None, None)
        assert result.selected_genre == "Jazz"


# ── resolve_genre — Rule 2a: Various Artists ──────────────────────────────────


class TestResolveGenreVariousArtists:
    VA = "Various Artists"

    def test_artist_genre_preferred_over_album_genre_for_va(self):
        result = resolve_genre(None, "Rock", "Jazz", None, self.VA)
        assert result.selected_genre == "Rock"
        assert result.selection_reason == "ARTIST GENRE (VA)"
        assert result.derived_value == "Artist"

    def test_album_genre_fallback_when_no_artist_genre_for_va(self):
        result = resolve_genre(None, None, "Jazz", None, self.VA)
        assert result.selected_genre == "Jazz"
        assert result.selection_reason == "ALBUM GENRE (VA)"
        assert result.derived_value == "Album"

    def test_no_genre_when_all_absent_for_va(self):
        result = resolve_genre(None, None, None, None, self.VA)
        assert result.status == "no_genre"
        assert result.selected_genre is None

    def test_va_case_insensitive(self):
        result = resolve_genre(None, "Funk", None, None, "various artists")
        assert result.selected_genre == "Funk"

    def test_va_with_leading_trailing_spaces(self):
        result = resolve_genre(None, "Soul", None, None, "  Various Artists  ")
        assert result.selected_genre == "Soul"

    def test_album_artist_genre_not_used_for_va(self):
        # album_artist_genre should be bypassed for VA
        result = resolve_genre(None, None, None, "Country", self.VA)
        assert result.status == "no_genre"

    def test_whitespace_only_artist_genre_falls_back_to_album_genre_for_va(self):
        result = resolve_genre(None, "   ", "Jazz", None, self.VA)
        assert result.selected_genre == "Jazz"
        assert result.selection_reason == "ALBUM GENRE (VA)"

    def test_whitespace_only_album_genre_treated_as_no_genre_for_va(self):
        result = resolve_genre(None, None, "\t\n ", None, self.VA)
        assert result.status == "no_genre"
        assert result.selected_genre is None


# ── resolve_genre — Rule 2b: Regular album ────────────────────────────────────


class TestResolveGenreRegularAlbum:
    def test_album_genre_preferred_over_album_artist_genre(self):
        result = resolve_genre(None, "Rock", "Jazz", "Blues", "The Beatles")
        assert result.selected_genre == "Jazz"
        assert result.selection_reason == "ALBUM GENRE"
        assert result.derived_value == "Album"

    def test_album_artist_genre_fallback_when_no_album_genre(self):
        result = resolve_genre(None, "Rock", None, "Blues", "The Beatles")
        assert result.selected_genre == "Blues"
        assert result.selection_reason == "ALBUM ARTIST GENRE"
        assert result.derived_value == "Album Artist"

    def test_no_genre_when_all_absent_for_regular(self):
        result = resolve_genre(None, None, None, None, "The Beatles")
        assert result.status == "no_genre"

    def test_artist_genre_not_preferred_for_regular_album(self):
        # artist_genre should be ignored; album_genre should win
        result = resolve_genre(None, "Funk", "Jazz", None, "Miles Davis")
        assert result.selected_genre == "Jazz"

    def test_none_album_artist_treated_as_regular(self):
        result = resolve_genre(None, None, "Pop", None, None)
        assert result.selected_genre == "Pop"
        assert result.selection_reason == "ALBUM GENRE"

    def test_empty_album_artist_treated_as_regular(self):
        result = resolve_genre(None, None, "Classical", None, "")
        assert result.selected_genre == "Classical"

    def test_whitespace_only_album_genre_falls_back_to_album_artist_genre(self):
        result = resolve_genre(None, None, "  ", "Blues", "The Beatles")
        assert result.selected_genre == "Blues"
        assert result.selection_reason == "ALBUM ARTIST GENRE"

    def test_whitespace_only_album_artist_genre_treated_as_no_genre(self):
        result = resolve_genre(None, None, None, " \t ", "The Beatles")
        assert result.status == "no_genre"
        assert result.selected_genre is None


# ── resolve_genre — no_genre path ────────────────────────────────────────────


class TestResolveGenreNoGenre:
    def test_all_none_inputs_returns_no_genre(self):
        result = resolve_genre(None, None, None, None, None)
        assert result.status == "no_genre"
        assert result.selected_genre is None
        assert result.selection_reason is None
        assert result.derived_value is None

    def test_returns_genre_resolution_instance(self):
        result = resolve_genre(None, None, None, None, None)
        assert isinstance(result, GenreResolution)


# ── _has_value (private helper) ──────────────────────────────────────────────


class TestHasValue:
    def test_none_returns_false(self):
        assert _has_value(None) is False

    def test_empty_string_returns_false(self):
        assert _has_value("") is False

    def test_whitespace_only_returns_false(self):
        assert _has_value("   ") is False

    def test_tab_and_newline_returns_false(self):
        assert _has_value("\t\n\r") is False

    def test_non_breaking_space_returns_false(self):
        assert _has_value("\u00a0") is False

    def test_zero_width_space_returns_false(self):
        assert _has_value("\u200b") is False

    def test_ideographic_space_returns_false(self):
        assert _has_value("\u3000") is False

    def test_bom_returns_false(self):
        assert _has_value("\ufeff") is False

    def test_mixed_unicode_whitespace_returns_false(self):
        assert _has_value("\u00a0\u200b\u3000\ufeff") is False

    def test_visible_string_returns_true(self):
        assert _has_value("Rock") is True

    def test_visible_with_unicode_whitespace_returns_true(self):
        assert _has_value("Rock\u00a0") is True

    def test_number_string_returns_true(self):
        assert _has_value("123") is True


# ── build_log_lines ───────────────────────────────────────────────────────────


class TestBuildLogLines:
    def _base_kwargs(self, **overrides):
        defaults = dict(
            is_dry_run=False,
            total=10,
            updated_count=7,
            skipped_count=2,
            no_genre_count=1,
            error_count=0,
            duration_secs=65.0,
            log_updated=[],
            log_skipped=[],
            log_no_genre=[],
            log_errors=[],
        )
        defaults.update(overrides)
        return defaults

    def test_returns_list_of_strings(self):
        lines = build_log_lines(**self._base_kwargs())
        assert isinstance(lines, list)
        assert all(isinstance(line, str) for line in lines)

    def test_header_present(self):
        lines = build_log_lines(**self._base_kwargs())
        combined = "".join(lines)
        assert "GENRE SYNC REPORT" in combined

    def test_live_mode_label(self):
        lines = build_log_lines(**self._base_kwargs(is_dry_run=False))
        combined = "".join(lines)
        assert "LIVE UPDATE" in combined

    def test_dry_run_mode_label(self):
        lines = build_log_lines(**self._base_kwargs(is_dry_run=True))
        combined = "".join(lines)
        assert "DRY RUN" in combined

    def test_dry_run_uses_would_update_label(self):
        lines = build_log_lines(
            **self._base_kwargs(
                is_dry_run=True,
                updated_count=3,
                log_updated=["file1.mp3\n", "file2.mp3\n", "file3.mp3\n"],
            )
        )
        combined = "".join(lines)
        assert "WOULD UPDATE" in combined

    def test_live_uses_updated_label(self):
        lines = build_log_lines(
            **self._base_kwargs(
                log_updated=["file1.mp3\n"],
            )
        )
        combined = "".join(lines)
        assert "UPDATED" in combined

    def test_summary_section_present(self):
        lines = build_log_lines(**self._base_kwargs())
        combined = "".join(lines)
        assert "SUMMARY" in combined

    def test_summary_contains_total(self):
        lines = build_log_lines(**self._base_kwargs(total=42))
        combined = "".join(lines)
        assert "42" in combined

    def test_time_formatted_mm_ss(self):
        lines = build_log_lines(**self._base_kwargs(duration_secs=65.0))
        combined = "".join(lines)
        assert "01:05" in combined

    def test_time_zero_seconds(self):
        lines = build_log_lines(**self._base_kwargs(duration_secs=0.0))
        combined = "".join(lines)
        assert "00:00" in combined

    def test_time_exactly_one_minute(self):
        lines = build_log_lines(**self._base_kwargs(duration_secs=60.0))
        combined = "".join(lines)
        assert "01:00" in combined

    def test_updated_section_present_when_nonempty(self):
        lines = build_log_lines(
            **self._base_kwargs(
                log_updated=["file1.mp3\n"],
            )
        )
        combined = "".join(lines)
        assert "file1.mp3" in combined

    def test_skipped_section_present_when_nonempty(self):
        lines = build_log_lines(
            **self._base_kwargs(
                log_skipped=["skip.mp3\n"],
            )
        )
        combined = "".join(lines)
        assert "SKIPPED" in combined
        assert "skip.mp3" in combined

    def test_no_genre_section_present_when_nonempty(self):
        lines = build_log_lines(
            **self._base_kwargs(
                log_no_genre=["nogenre.mp3\n"],
            )
        )
        combined = "".join(lines)
        assert "NO GENRE" in combined

    def test_errors_section_present_when_nonempty(self):
        lines = build_log_lines(
            **self._base_kwargs(
                log_errors=["bad.mp3\n"],
            )
        )
        combined = "".join(lines)
        assert "ERRORS" in combined

    def test_empty_sections_not_in_output(self):
        lines = build_log_lines(
            **self._base_kwargs(
                log_updated=[],
                log_skipped=[],
                log_no_genre=[],
                log_errors=[],
            )
        )
        combined = "".join(lines)
        assert "UPDATED" not in combined
        assert "SKIPPED" not in combined

    def test_counts_in_section_headers(self):
        lines = build_log_lines(
            **self._base_kwargs(
                log_updated=["a.mp3\n", "b.mp3\n"],
                updated_count=2,
            )
        )
        combined = "".join(lines)
        assert "2" in combined

    def test_all_counters_appear_in_summary(self):
        lines = build_log_lines(
            **self._base_kwargs(
                total=10,
                updated_count=7,
                skipped_count=2,
                no_genre_count=1,
                error_count=0,
            )
        )
        combined = "".join(lines)
        assert "10" in combined
        assert "7" in combined
        assert "2" in combined
        assert "1" in combined

    def test_section_order_is_header_updated_skipped_nogenre_errors_summary(self):
        lines = build_log_lines(
            **self._base_kwargs(
                log_updated=["a.mp3\n"],
                log_skipped=["b.mp3\n"],
                log_no_genre=["c.mp3\n"],
                log_errors=["d.mp3\n"],
            )
        )
        joined = "".join(lines)
        header_pos = joined.index("GENRE SYNC REPORT")
        updated_pos = joined.index("UPDATED")
        skipped_pos = joined.index("SKIPPED")
        nogenre_pos = joined.index("NO GENRE")
        errors_pos = joined.index("ERRORS")
        summary_pos = joined.index("SUMMARY")
        assert (
            header_pos
            < updated_pos
            < skipped_pos
            < nogenre_pos
            < errors_pos
            < summary_pos
        )

    def test_dry_run_is_dry_run_not_live(self):
        lines = build_log_lines(**self._base_kwargs(is_dry_run=True))
        combined = "".join(lines)
        assert "DRY RUN" in combined
        assert "LIVE UPDATE" not in combined

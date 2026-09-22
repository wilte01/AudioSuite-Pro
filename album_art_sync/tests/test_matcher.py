"""Tests for album_art_sync.core.matcher — album_name_matches()."""

from __future__ import annotations

from album_art_sync.core.matcher import album_name_matches


class TestAlbumNameMatches:
    """Covers all five matching strategies plus edge cases."""

    def test_exact_match_case_insensitive(self) -> None:
        assert album_name_matches("Abbey Road", "abbey road") == 1.0

    def test_exact_match_unicode_normalized(self) -> None:
        assert album_name_matches("Café", "Cafe\u0301") == 1.0

    def test_exact_match_whitespace_stripped(self) -> None:
        assert album_name_matches("  Abbey Road  ", "abbey road") == 1.0

    def test_substring_match_query_in_candidate(self) -> None:
        assert album_name_matches("Abbey Road", "Abbey Road (Remastered)") == 0.95

    def test_substring_match_candidate_in_query(self) -> None:
        assert album_name_matches("The Dark Side of the Moon", "Dark Side") == 0.95

    def test_token_sorted_match(self) -> None:
        assert album_name_matches("Greatest Hits", "Hits Greatest") == 0.90

    def test_token_sorted_with_extra(self) -> None:
        assert album_name_matches("Greatest Hits", "Greatest Hits (2003)") == 0.95

    def test_levenshtein_above_threshold(self) -> None:
        score = album_name_matches("Abbey Road", "Abbey Roade", threshold=0.85)
        assert score >= 0.85
        assert score < 1.0

    def test_levenshtein_at_threshold(self) -> None:
        score = album_name_matches("Thriller", "Thrillr", threshold=0.80)
        assert score > 0.0

    def test_below_threshold_returns_zero(self) -> None:
        assert album_name_matches("Abbey Road", "Yesterday") == 0.0

    def test_completely_different_returns_zero(self) -> None:
        assert album_name_matches("Thriller", "Kind of Blue") == 0.0

    def test_both_empty_returns_one(self) -> None:
        assert album_name_matches("", "") == 1.0

    def test_query_empty_candidate_not(self) -> None:
        assert album_name_matches("", "Something") == 0.0

    def test_candidate_empty_query_not(self) -> None:
        assert album_name_matches("Something", "") == 0.0

    def test_special_characters_handled(self) -> None:
        assert album_name_matches("Hötel Cäliförnia", "Hötel Cäliförnia") == 1.0

    def test_substring_with_parentheses(self) -> None:
        assert album_name_matches("Rumours", "Rumours (2001 Remaster)") == 0.95

    def test_levenshtein_below_threshold(self) -> None:
        score = album_name_matches("Back in Black", "Back in White", threshold=0.85)
        assert score == 0.0


class TestAlbumNameMatchesCustomThreshold:
    """Lower/higher thresholds affect which fuzzy matches pass."""

    def test_lower_threshold_passes_more(self) -> None:
        score = album_name_matches("Kind of Blue", "Kind of Glue", threshold=0.70)
        assert score > 0.0

    def test_higher_threshold_rejects_more(self) -> None:
        assert album_name_matches("Kind of Blue", "Kind of Glue", threshold=0.95) == 0.0

    def test_threshold_of_one_requires_exact(self) -> None:
        assert album_name_matches("Abbey Road", "abbey road", threshold=1.0) == 1.0
        assert album_name_matches("Abbey Road", "Kind of Glue", threshold=1.0) == 0.0

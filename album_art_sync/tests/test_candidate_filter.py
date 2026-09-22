"""Tests for album_art_sync.core.candidate_filter — filter_and_rank()."""

from __future__ import annotations

import unittest.mock as mock

import pytest

from album_art_sync.core.candidate_filter import filter_and_rank
from album_art_sync.core.ranker import RankedCandidate


@pytest.fixture
def log() -> mock.Mock:
    return mock.Mock()


def _make_ranked(
    index: int,
    url: str = "",
    title: str = "",
    width: int = 600,
    height: int = 600,
    score: float = 360000.0,
    match_score: float = 1.0,
) -> RankedCandidate:
    return RankedCandidate(index, url, title, width, height, score, match_score)


class TestFilterAndRankTrustedSource:
    """Fanart.tv path — is_trusted_source=True, no name filtering."""

    RAW_ITEMS = [
        {"url": "https://example.com/a.jpg", "title": "Cover A"},
        {"url": "https://example.com/b.jpg", "title": "Cover B"},
        {"url": "https://example.com/c.jpg", "title": "Cover C"},
    ]

    def test_trusted_all_pass_ranked_by_area(self, log: mock.Mock) -> None:
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            side_effect=[(1000, 1000), (800, 600), (500, 500)],
        ):
            result = filter_and_rank(
                self.RAW_ITEMS,
                query_album="Album",
                source_name="Fanart.tv",
                is_trusted_source=True,
                log=log,
            )
        assert len(result) == 3
        # Sorted by area descending
        assert result[0].width == 1000
        assert result[1].width == 800
        assert result[2].width == 500
        # All have match_score = 1.0 (trusted source)
        assert all(r.match_score == 1.0 for r in result)

    def test_trusted_rejects_below_min_dimension(self, log: mock.Mock) -> None:
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            return_value=(200, 200),
        ):
            result = filter_and_rank(
                self.RAW_ITEMS,
                query_album="Album",
                source_name="Fanart.tv",
                is_trusted_source=True,
                min_dimension=500,
                log=log,
            )
        assert len(result) == 0

    def test_trusted_unreadable_dimensions_skipped(self, log: mock.Mock) -> None:
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            side_effect=[None, (800, 600), None],
        ):
            result = filter_and_rank(
                self.RAW_ITEMS,
                query_album="Album",
                source_name="Fanart.tv",
                is_trusted_source=True,
                log=log,
            )
        assert len(result) == 1
        assert result[0].width == 800

    def test_trusted_no_url_skipped(self, log: mock.Mock) -> None:
        items = [{"url": "", "title": "No URL"}]
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            return_value=(600, 600),
        ):
            result = filter_and_rank(
                items,
                query_album="Album",
                source_name="Fanart.tv",
                is_trusted_source=True,
                log=log,
            )
        assert len(result) == 0

    def test_trusted_empty_input(self, log: mock.Mock) -> None:
        result = filter_and_rank(
            [],
            query_album="Album",
            source_name="Fanart.tv",
            is_trusted_source=True,
            log=log,
        )
        assert result == []


class TestFilterAndRankUntrustedSource:
    """Deezer/iTunes path — is_trusted_source=False, name filtering applied."""

    RAW_ITEMS = [
        {"url": "https://example.com/exact.jpg", "title": "Dark Side of the Moon"},
        {
            "url": "https://example.com/remaster.jpg",
            "title": "Dark Side of the Moon (2011 Remaster)",
        },
        {"url": "https://example.com/wrong.jpg", "title": "The Wall"},
    ]

    def test_exact_name_match_passes(self, log: mock.Mock) -> None:
        with (
            mock.patch(
                "album_art_sync.core.candidate_filter.get_image_dimensions",
                return_value=(600, 600),
            ),
        ):
            result = filter_and_rank(
                [self.RAW_ITEMS[0]],
                query_album="Dark Side of the Moon",
                source_name="Deezer",
                is_trusted_source=False,
                log=log,
            )
        assert len(result) == 1
        assert result[0].match_score == 1.0

    def test_remaster_substring_match_passes(self, log: mock.Mock) -> None:
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            return_value=(600, 600),
        ):
            result = filter_and_rank(
                [self.RAW_ITEMS[1]],
                query_album="Dark Side of the Moon",
                source_name="Deezer",
                is_trusted_source=False,
                log=log,
            )
        assert len(result) == 1
        assert result[0].match_score == 0.95

    def test_wrong_album_rejected(self, log: mock.Mock) -> None:
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            return_value=(600, 600),
        ):
            result = filter_and_rank(
                [self.RAW_ITEMS[2]],
                query_album="Dark Side of the Moon",
                source_name="Deezer",
                is_trusted_source=False,
                log=log,
            )
        assert len(result) == 0

    def test_mixed_candidates_only_survivors_returned(self, log: mock.Mock) -> None:
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            return_value=(600, 600),
        ):
            result = filter_and_rank(
                self.RAW_ITEMS,
                query_album="Dark Side of the Moon",
                source_name="Deezer",
                is_trusted_source=False,
                log=log,
            )
        # Only the first two pass name matching
        assert len(result) == 2
        assert "The Wall" not in [r.title for r in result]

    def test_all_rejected_returns_empty(self, log: mock.Mock) -> None:
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            return_value=(600, 600),
        ):
            result = filter_and_rank(
                self.RAW_ITEMS,
                query_album="Completely Different Album",
                source_name="Deezer",
                is_trusted_source=False,
                log=log,
            )
        assert len(result) == 0

    def test_lower_threshold_passes_more(self, log: mock.Mock) -> None:
        items = [
            {
                "url": "https://example.com/near.jpg",
                "title": "Dark Side of the Moon (Deluxe)",
            },
        ]
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            return_value=(600, 600),
        ):
            # At default 0.85 this substring match should pass (substring → 0.95)
            result = filter_and_rank(
                items,
                query_album="Dark Side of the Moon",
                source_name="Deezer",
                is_trusted_source=False,
                match_threshold=0.90,
                log=log,
            )
        assert len(result) == 1

    def test_quality_ranking_among_survivors(self, log: mock.Mock) -> None:
        items = [
            {"url": "https://example.com/small.jpg", "title": "Dark Side of the Moon"},
            {"url": "https://example.com/large.jpg", "title": "Dark Side of the Moon"},
        ]
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            side_effect=[(500, 500), (1200, 1200)],
        ):
            result = filter_and_rank(
                items,
                query_album="Dark Side of the Moon",
                source_name="Deezer",
                is_trusted_source=False,
                log=log,
            )
        assert len(result) == 2
        assert result[0].width == 1200  # highest resolution first

    def test_match_score_ties_ranked_by_area(self, log: mock.Mock) -> None:
        """When match_score differs, higher match_score wins even if same size."""
        items = [
            {
                "url": "https://example.com/remaster.jpg",
                "title": "10cc (2024 Remaster)",
            },
            {"url": "https://example.com/exact.jpg", "title": "10cc"},
        ]
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            return_value=(1000, 1000),
        ):
            result = filter_and_rank(
                items,
                query_album="10cc",
                source_name="Deezer",
                is_trusted_source=False,
                log=log,
            )
        assert len(result) == 2
        # Exact match (1.0) should be ranked first, ahead of substring match (0.95)
        assert result[0].title == "10cc"
        assert result[0].match_score == 1.0
        assert result[1].title == "10cc (2024 Remaster)"
        assert result[1].match_score == 0.95

    def test_dimension_below_min_rejected_before_name_match(
        self, log: mock.Mock
    ) -> None:
        with mock.patch(
            "album_art_sync.core.candidate_filter.get_image_dimensions",
            return_value=(100, 100),
        ):
            result = filter_and_rank(
                self.RAW_ITEMS,
                query_album="Dark Side of the Moon",
                source_name="Deezer",
                is_trusted_source=False,
                min_dimension=500,
                log=log,
            )
        assert len(result) == 0

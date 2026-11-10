"""Tests for library_stats.ui.charts — Tk-free figure builders.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md D38/D40).

Changed in 2.6.0: the summary figure carries an Artwork Coverage panel, so the
axis order and the trend's index move.
"""

from __future__ import annotations

import pytest

from library_stats.core.completeness import (
    UNKNOWN_ALBUM,
    AlbumCompleteness,
    CompletenessReport,
    TagCompleteness,
)
from library_stats.core.file_processor import StatsReport
from library_stats.ui.charts import build_heatmap_figure, build_summary_figure

# ── Helpers ──────────────────────────────────────────────────────────────────


def _stats() -> StatsReport:
    return StatsReport(
        scan_path="/music",
        total_files=4,
        genre_distribution={"House": 3, "Jazz": 1},
        bpm_distribution={"120\u2013139": 2, "140\u2013159": 1, "Unknown": 1},
        key_distribution={"Cm": 2, "G": 1},
        year_distribution={"1990s": 1, "2000s": 2, "Unknown": 1},
    )


def _album(name: str, total: int, missing: dict[str, int]) -> AlbumCompleteness:
    return AlbumCompleteness(album=name, total_files=total, missing=missing)


def _report(albums: tuple[AlbumCompleteness, ...]) -> CompletenessReport:
    return CompletenessReport(
        directory="/music",
        total_files=sum(a.total_files for a in albums),
        tag_results={
            "title": TagCompleteness(
                field="title", total=2, present=2, missing=0, pct_complete=100.0
            )
        },
        overall_pct=50.0,
        album_results=albums,
    )


# ── Summary figure ───────────────────────────────────────────────────────────


class TestSummaryFigure:
    def test_panels_and_data(self) -> None:
        fig = build_summary_figure(_stats())
        assert [ax.get_title() for ax in fig.axes] == [
            "Top Genres",
            "BPM Distribution",
            "Top Keys",
            "Year Distribution",
            "Artwork Coverage",
            "Completeness Trend",
        ]
        # Two genres, one wedge each.
        assert len(fig.axes[0].patches) == 2
        # Two measured BPM buckets, one file each (Unknown draws nothing).
        heights = [p.get_height() for p in fig.axes[1].patches]
        assert sum(heights) == 3
        # Two keys, two bars.
        assert len(fig.axes[2].patches) == 2
        # Two decades; the Unknown bucket is dropped from the chart only.
        assert len(fig.axes[3].patches) == 2

    def test_unknown_and_other_buckets(self) -> None:
        report = StatsReport(
            scan_path="/music",
            genre_distribution={"A": 5, "B": 1, "C": 1},
            year_distribution={"Unknown": 3},
        )
        fig = build_summary_figure(report)
        # 12 genres collapse to "Other"; here 3 genres stay separate, so no
        # synthetic wedge is invented.
        labels = [t.get_text() for t in fig.axes[0].texts]
        assert "Other" not in labels
        assert len(fig.axes[3].patches) == 0

    def test_trend_uses_history_oldest_first(self) -> None:
        history = [
            {"recorded_at": "2026-10-01 09:00:00", "overall_pct": 10.0},
            {"recorded_at": "2026-10-02 09:00:00", "overall_pct": 55.0},
            {"recorded_at": "2026-10-03 09:00:00", "overall_pct": 90.0},
        ]
        fig = build_summary_figure(_stats(), history)
        trend = fig.axes[5]
        assert len(trend.lines) == 1
        assert list(trend.lines[0].get_ydata()) == [10.0, 55.0, 90.0]
        assert [t.get_text() for t in trend.get_xticklabels()] == [
            "2026-10-01",
            "2026-10-02",
            "2026-10-03",
        ]
        assert trend.get_ylim() == (0.0, 100.0)

    def test_trend_without_history_explains_itself(self) -> None:
        fig = build_summary_figure(_stats())
        trend = fig.axes[5]
        assert len(trend.lines) == 0
        assert any("No history" in t.get_text() for t in trend.texts)


class TestArtworkPanel:
    """Changed in 2.6.0: the Artwork Coverage panel."""

    def test_bars_count_files_with_and_without_artwork(self) -> None:
        report = StatsReport(
            scan_path="/music",
            total_files=10,
            missing_data={"no_art": 4},
        )

        fig = build_summary_figure(report)

        artwork = fig.axes[4]
        assert artwork.get_title() == "Artwork Coverage"
        # One bar for "Without", one for "With artwork": 4 and 6 files.
        assert [patch.get_width() for patch in artwork.patches] == [4.0, 6.0]
        assert any("60% have artwork" in t.get_text() for t in artwork.texts)

    def test_a_fully_covered_library_reads_one_hundred_percent(self) -> None:
        report = StatsReport(scan_path="/music", total_files=5)

        fig = build_summary_figure(report)

        artwork = fig.axes[4]
        assert [patch.get_width() for patch in artwork.patches] == [0.0, 5.0]
        assert any("100% have artwork" in t.get_text() for t in artwork.texts)

    def test_the_panel_is_exposed_and_advertises_the_list(self) -> None:
        """Changed in 2.6.0: the GUI clicks this axis to open the album list."""
        report = StatsReport(
            scan_path="/music",
            total_files=10,
            missing_data={"no_art": 4},
        )

        fig = build_summary_figure(report)

        assert getattr(fig, "artwork_axes") is fig.axes[4]
        assert "click to list the albums missing covers" in (fig.axes[4].get_xlabel())

    def test_a_fully_covered_library_does_not_advertise_the_list(self) -> None:
        fig = build_summary_figure(StatsReport(scan_path="/music", total_files=5))

        assert fig.axes[4].get_xlabel() == "files"

    def test_an_empty_scan_explains_itself(self) -> None:
        fig = build_summary_figure(StatsReport(scan_path=""))

        artwork = fig.axes[4]
        assert len(artwork.patches) == 0
        assert any("Scan a library" in t.get_text() for t in artwork.texts)


# ── Heatmap figure ───────────────────────────────────────────────────────────


class TestHeatmapFigure:
    def test_matrix_shape_and_scale(self) -> None:
        fig = build_heatmap_figure(
            _report(
                (
                    _album("A \u2014 One", 2, {"title": 1}),
                    _album("B \u2014 Two", 4, {"title": 4}),
                )
            )
        )
        ax = fig.axes[0]
        assert len(ax.images) == 1
        matrix = ax.images[0].get_array()
        assert matrix.shape == (2, 12)
        assert ax.images[0].get_clim() == (0.0, 100.0)
        # 50 % (1 of 2) and 100 % (4 of 4) missing title cells respectively.
        assert matrix[0][0] == 50.0
        assert matrix[1][0] == 100.0
        assert [t.get_text() for t in ax.get_yticklabels()] == [
            "A \u2014 One",
            "B \u2014 Two",
        ]

    def test_cells_are_annotated_for_small_albums(self) -> None:
        fig = build_heatmap_figure(_report((_album("A \u2014 One", 4, {"title": 1}),)))
        values = [t.get_text() for t in fig.axes[0].texts]
        assert "25" in values
        assert "0" in values

    def test_large_album_counts_skip_annotations(self) -> None:
        albums = tuple(_album(f"A \u2014 {i}", 10, {"title": i}) for i in range(13))
        fig = build_heatmap_figure(_report(albums))
        assert len(fig.axes[0].texts) == 0

    def test_max_albums_caps_the_rows(self) -> None:
        albums = tuple(_album(f"A \u2014 {i}", 2, {}) for i in range(30))
        fig = build_heatmap_figure(_report(albums), max_albums=5)
        assert fig.axes[0].images[0].get_array().shape == (5, 12)

    def test_empty_report_explains_itself(self) -> None:
        fig = build_heatmap_figure(_report(()))
        ax = fig.axes[0]
        assert len(ax.images) == 0
        assert any("No albums" in t.get_text() for t in ax.texts)

    def test_unknown_album_label_is_kept(self) -> None:
        fig = build_heatmap_figure(_report((_album(UNKNOWN_ALBUM, 2, {}),)))
        assert fig.axes[0].get_yticklabels()[0].get_text() == UNKNOWN_ALBUM

    def test_long_album_labels_are_truncated(self) -> None:
        long_name = "Artist \u2014 " + "x" * 60
        fig = build_heatmap_figure(_report((_album(long_name, 2, {}),)))
        label = fig.axes[0].get_yticklabels()[0].get_text()
        assert label.endswith("\u2026")
        assert len(label) <= 35

    @pytest.mark.parametrize("total", (0,))
    def test_album_with_no_files_has_zero_cells(self, total: int) -> None:
        fig = build_heatmap_figure(_report((_album("A \u2014 Empty", total, {}),)))
        assert fig.axes[0].images[0].get_array()[0][0] == 0.0

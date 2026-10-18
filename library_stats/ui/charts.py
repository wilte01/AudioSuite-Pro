"""charts.py — Tk-free matplotlib figure builders for Library Statistics.

Every figure is built from data alone, so the charts can be tested without a
Tk root: the GUI only owns the canvas it embeds.  Keeping the builders here
also keeps ``app.py`` from growing a second, untestable copy of each plot.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md D38) — the four
summary panels moved out of ``app._update_charts``, and the completeness
heatmap (missing tags by album) plus the completeness trend chart were added.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from matplotlib.figure import Figure

from library_stats.core.completeness import TAG_FIELDS, CompletenessReport

_CHART_BG = "#fafafa"

#: Ordered BPM buckets, matching ``library_stats.library_cache._bpm_bin``.
_BPM_ORDER = (
    "<60",
    "60\u201379",
    "80\u201399",
    "100\u2013119",
    "120\u2013139",
    "140\u2013159",
    "160\u2013179",
    "180+",
)


def _short_date(recorded_at: Any) -> str:
    """Return a compact date label from a SQLite ``datetime('now')`` string."""
    text = str(recorded_at or "")
    return text[:10] or "?"


def _add_trend_panel(
    fig: Figure,
    position: Any,
    history: Sequence[dict[str, Any]] | None,
) -> Any:
    """Draw the completeness trend (oldest first) into *position*."""
    ax = fig.add_subplot(*position)
    points = list(history or [])
    if points:
        labels = [_short_date(p.get("recorded_at")) for p in points]
        values = [float(p.get("overall_pct", 0.0)) for p in points]
        ax.plot(
            range(len(values)),
            values,
            marker="o",
            color="#6366f1",
            linewidth=1.5,
            markersize=4,
        )
        ax.set_xticks(range(len(values)))
        ax.set_xticklabels(labels, rotation=45, fontsize=7)
        ax.set_ylim(0, 100)
        ax.set_ylabel("complete %", fontsize=7)
        ax.tick_params(axis="y", labelsize=7)
    else:
        ax.text(
            0.5,
            0.5,
            "No history yet\n(snapshots accumulate per scan)",
            ha="center",
            va="center",
            fontsize=8,
            color="#6b7280",
            transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
    ax.set_title("Completeness Trend", fontsize=10, fontweight="bold")
    return ax


def build_summary_figure(
    report: Any,
    history: Sequence[dict[str, Any]] | None = None,
) -> Figure:
    """Build the Charts-tab figure: four distributions plus the trend.

    Args:
        report: A populated ``StatsReport``.
        history: Completeness snapshots, oldest first (``LibraryCache
            .completeness_history``).  ``None``/empty draws an explanatory
            panel instead of an empty axis.

    Returns:
        A ``Figure`` the caller embeds in a canvas.
    """
    fig = Figure(figsize=(10, 7), dpi=100, facecolor=_CHART_BG)

    # Genre pie chart
    ax1 = fig.add_subplot(2, 3, 1)
    genres = dict(sorted(report.genre_distribution.items(), key=lambda x: -x[1])[:10])
    total_others = sum(report.genre_distribution.values()) - sum(genres.values())
    if total_others > 0:
        genres["Other"] = total_others
    if genres:
        ax1.pie(
            list(genres.values()),
            labels=list(genres.keys()),
            autopct="%1.0f%%",
            startangle=90,
            textprops={"fontsize": 7},
        )
    ax1.set_title("Top Genres", fontsize=10, fontweight="bold")

    # BPM histogram
    ax2 = fig.add_subplot(2, 3, 2)
    bpm_vals = [report.bpm_distribution.get(b, 0) for b in _BPM_ORDER]
    ax2.bar(_BPM_ORDER, bpm_vals, color="#6366f1", edgecolor="white")
    ax2.set_title("BPM Distribution", fontsize=10, fontweight="bold")
    ax2.tick_params(axis="x", rotation=30, labelsize=7)
    ax2.tick_params(axis="y", labelsize=7)

    # Key distribution
    ax3 = fig.add_subplot(2, 3, 3)
    keys = dict(sorted(report.key_distribution.items(), key=lambda x: -x[1])[:15])
    if keys:
        ax3.barh(
            list(keys.keys()),
            list(keys.values()),
            color="#a855f7",
            edgecolor="white",
        )
    ax3.set_title("Top Keys", fontsize=10, fontweight="bold")
    ax3.tick_params(axis="y", labelsize=7)
    ax3.tick_params(axis="x", labelsize=7)

    # Year distribution
    ax4 = fig.add_subplot(2, 3, 4)
    years = dict(report.year_distribution)
    years.pop("Unknown", None)
    if years:
        sorted_years = sorted(years.items(), key=lambda x: x[0])
        labels_y = [y[0] for y in sorted_years]
        vals_y = [y[1] for y in sorted_years]
        ax4.bar(labels_y, vals_y, color="#22c55e", edgecolor="white")
    ax4.set_title("Year Distribution", fontsize=10, fontweight="bold")
    ax4.tick_params(axis="x", rotation=45, labelsize=7)
    ax4.tick_params(axis="y", labelsize=7)

    # Completeness trend spans the rest of the second row.
    _add_trend_panel(fig, (2, 3, (5, 6)), history)

    fig.tight_layout(pad=3)
    return fig


def build_heatmap_figure(
    report: CompletenessReport,
    max_albums: int = 20,
) -> Figure:
    """Build the missing-tags-by-album heatmap for the Completeness tab.

    Rows are the worst albums first (``CompletenessReport.album_results`` is
    already ordered by completeness), columns are the tracked tag fields, and
    each cell is the percentage of that album's files missing the field.

    Args:
        report: A populated completeness report.
        max_albums: Rows to show; the worst *max_albums* albums.

    Returns:
        A ``Figure`` the caller embeds in a canvas.
    """
    fig = Figure(figsize=(9, 4.2), dpi=100, facecolor=_CHART_BG)
    ax = fig.add_subplot(1, 1, 1)
    albums = list(report.album_results)[: max(1, int(max_albums))]

    title = "Missing Tags by Album (% of each album's files)"
    ax.set_title(title, fontsize=10, fontweight="bold")

    if not albums:
        ax.text(
            0.5,
            0.5,
            "No albums to display",
            ha="center",
            va="center",
            fontsize=9,
            color="#6b7280",
            transform=ax.transAxes,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        return fig

    matrix = [
        [album.pct_missing(tag_field) for tag_field in TAG_FIELDS] for album in albums
    ]
    image = ax.imshow(matrix, aspect="auto", cmap="Reds", vmin=0.0, vmax=100.0)
    ax.set_xticks(range(len(TAG_FIELDS)))
    ax.set_xticklabels(
        [TAG_FIELDS[i].replace("_", " ").title() for i in range(len(TAG_FIELDS))],
        rotation=40,
        ha="right",
        fontsize=7,
    )
    ax.set_yticks(range(len(albums)))
    ax.set_yticklabels(
        [
            (album.album[:34] + "\u2026") if len(album.album) > 34 else album.album
            for album in albums
        ],
        fontsize=7,
    )
    # A 0-100 legend keeps every dashboard's colours comparable.
    fig.colorbar(image, ax=ax, fraction=0.03, pad=0.02).ax.tick_params(labelsize=7)

    if len(albums) <= 12:
        for row, album_row in enumerate(matrix):
            for col, value in enumerate(album_row):
                ax.text(
                    col,
                    row,
                    f"{value:.0f}",
                    ha="center",
                    va="center",
                    fontsize=6,
                    color="white" if value >= 60 else "#374151",
                )

    fig.tight_layout(pad=1.5)
    return fig

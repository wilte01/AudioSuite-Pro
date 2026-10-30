"""Tests for the playlist/HTML/CSV export surface and the Camelot mapping.

* The Camelot table is a pure-function table test over **every** key
  ``key_engine`` can emit, both spellings, the three enharmonic pairs, the two
  text forms, and the two "no key" answers.
* The M3U, HTML and CSV checks read the artefact the export actually wrote and
  assert its bytes/rows — an export that reports success while writing the
  wrong order, the host's path separator or an unescaped filename is the
  failure mode this module exists to prevent.

Fixtures are real encoded files tagged through mutagen, so the columns under
test come from the same reader path the dashboard uses.

Changed in 2.2.0: new — F-05/F-06.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from mutagen.flac import FLAC
from pydub import AudioSegment

from library_stats.core.file_processor import StatsReport, export_csv
from library_stats.core.playlist_export import (
    DEFAULT_EXPORT_COLUMNS,
    EXPORT_COLUMNS,
    ExportRow,
    camelot_for_key,
    collect_export_rows,
    export_html,
    export_m3u,
    resolve_columns,
)

#: Every key the detector emits: 12 major spellings, then 12 minor.
DETECTOR_KEYS: list[tuple[str, str]] = [
    ("C", "8B"),
    ("C#", "3B"),
    ("D", "10B"),
    ("Eb", "5B"),
    ("E", "12B"),
    ("F", "7B"),
    ("F#", "2B"),
    ("G", "9B"),
    ("Ab", "4B"),
    ("A", "11B"),
    ("Bb", "6B"),
    ("B", "1B"),
    ("Cm", "5A"),
    ("C#m", "12A"),
    ("Dm", "7A"),
    ("Ebm", "2A"),
    ("Em", "9A"),
    ("Fm", "4A"),
    ("F#m", "11A"),
    ("Gm", "6A"),
    ("G#m", "1A"),
    ("Am", "8A"),
    ("Bbm", "3A"),
    ("Bm", "10A"),
]


def _make_flac(path: Path, **tags: str) -> Path:
    """Write a real 2-second FLAC carrying *tags*.

    Raises the encoder's own error when the host cannot encode FLAC; callers
    turn that into an attributable skip.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    AudioSegment.silent(duration=2000).export(str(path), format="flac")
    audio = FLAC(str(path))
    if audio.tags is None:
        audio.add_tags()
    for key, value in tags.items():
        audio[key] = [value]
    audio.save()
    return path


def _build(path: Path, **tags: str) -> Path:
    """Build the fixture, skipping with a reason if FLAC cannot be encoded."""
    try:
        return _make_flac(path, **tags)
    except Exception as exc:  # pragma: no cover - host without the encoder
        pytest.skip(f"this host cannot encode FLAC ({type(exc).__name__})")


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """A two-album library whose files are written out of track order."""
    root = tmp_path / "music"
    # Deliberately not in track order, and album names chosen so album-first
    # ordering is distinguishable from walk order.
    _build(
        root / "beta" / "03 third.flac",
        artist="Beta Artist",
        album="Beta Album",
        albumartist="Beta Artist",
        title="Third Song",
        tracknumber="3",
        initialkey="Am",
        bpm="128",
    )
    _build(
        root / "beta" / "01 first.flac",
        artist="Beta Artist",
        album="Beta Album",
        albumartist="Beta Artist",
        title="First Song",
        tracknumber="1",
        initialkey="C",
        bpm="120",
    )
    _build(
        root / "alpha" / "02 second.flac",
        artist="Alpha Artist",
        album="Alpha Album",
        albumartist="Alpha Artist",
        title="Second Song",
        tracknumber="2",
        initialkey="Ebm",
        bpm="100",
    )
    return root


# ── Camelot mapping ─────────────────────────────────────────────────────────


class TestCamelotMapping:
    """The wheel is a pure table; every emitted spelling must land on it."""

    @pytest.mark.parametrize(("key", "code"), DETECTOR_KEYS)
    def test_every_detector_key_maps(self, key: str, code: str) -> None:
        assert camelot_for_key(key) == code

    @pytest.mark.parametrize(
        ("sharp", "flat"),
        [
            ("C#m", "Dbm"),
            ("D#", "Eb"),
            ("D#m", "Ebm"),
            ("F#", "Gb"),
            ("F#m", "Gbm"),
            ("G#", "Ab"),
            ("G#m", "Abm"),
            ("A#", "Bb"),
            ("A#m", "Bbm"),
        ],
    )
    def test_enharmonic_spellings_agree(self, sharp: str, flat: str) -> None:
        assert camelot_for_key(sharp) == camelot_for_key(flat)

    @pytest.mark.parametrize(
        ("text", "code"),
        [
            ("C major", "8B"),
            ("A minor", "8A"),
            ("Eb minor", "2A"),
            ("F# major", "2B"),
            ("Db major", "3B"),
        ],
    )
    def test_text_forms_map(self, text: str, code: str) -> None:
        assert camelot_for_key(text) == code

    @pytest.mark.parametrize("value", [None, "", "   ", "Unknown", "N/A", "H"])
    def test_unmapped_values_are_not_given_a_wheel_position(
        self, value: str | None
    ) -> None:
        """``UNKNOWN_KEY`` is a deliberate "no key" answer, not a wheel slot."""
        assert camelot_for_key(value) is None

    def test_all_twenty_four_positions_are_reachable(self) -> None:
        """Guard the guard: a table test over a short table proves nothing."""
        codes = {camelot_for_key(key) for key, _code in DETECTOR_KEYS}
        assert len(codes) == 24

    def test_an_already_camelot_value_survives_a_second_pass(self) -> None:
        assert camelot_for_key("8A") == "8A"
        assert camelot_for_key("11B") == "11B"


# ── Rows and columns ────────────────────────────────────────────────────────


class TestExportRows:
    def test_rows_come_back_in_album_then_track_order(self, library: Path) -> None:
        rows = collect_export_rows(str(library))
        assert [row.title for row in rows] == [
            "Second Song",
            "First Song",
            "Third Song",
        ]

    def test_rows_carry_the_tags_a_playlist_needs(self, library: Path) -> None:
        first = collect_export_rows(str(library))[1]
        assert first.artist == "Beta Artist"
        assert first.album == "Beta Album"
        assert first.track == "1"
        assert first.bpm == 120
        assert first.key == "C"
        assert first.camelot == "8B"
        assert first.duration_secs == pytest.approx(2.0, abs=0.2)

    def test_a_missing_scan_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            collect_export_rows(str(tmp_path / "nope"))


class TestColumnResolution:
    def test_default_is_the_playlist_subset(self) -> None:
        assert resolve_columns(None) == DEFAULT_EXPORT_COLUMNS

    def test_camelot_is_appended_once(self) -> None:
        once = resolve_columns(None, camelot=True)
        assert once[-1] == "camelot"
        assert resolve_columns(("path", "camelot"), camelot=True) == (
            "path",
            "camelot",
        )

    def test_a_misspelt_column_fails_instead_of_vanishing(self) -> None:
        with pytest.raises(ValueError, match="camelott"):
            resolve_columns(("path", "camelott"))

    def test_opt_in_columns_are_not_in_the_default_set(self) -> None:
        for column in ("camelot", "disc", "mood", "tempo_marking", "duration"):
            assert column in EXPORT_COLUMNS
            assert column not in DEFAULT_EXPORT_COLUMNS


# ── M3U ─────────────────────────────────────────────────────────────────────


class TestM3UExport:
    def _lines(self, path: Path) -> list[str]:
        return path.read_text(encoding="utf-8").splitlines()

    def test_header_paths_and_order(self, library: Path, tmp_path: Path) -> None:
        out = tmp_path / "list.m3u"
        count = export_m3u(str(library), str(out))

        lines = self._lines(out)
        assert count == 3
        assert lines[0] == "#EXTM3U"
        assert len(lines) == 1 + 3 * 2

        paths = [line for line in lines if not line.startswith("#")]
        assert len(paths) == 3
        assert [Path(p).name for p in paths] == [
            "02 second.flac",
            "01 first.flac",
            "03 third.flac",
        ]
        for entry in paths:
            assert Path(entry).is_absolute()
            # A player on POSIX rejects a backslash path, so the separator is
            # asserted deliberately rather than inherited from the host.
            assert "\\" not in entry

    def test_extinf_carries_seconds_and_a_display_name(
        self, library: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "list.m3u"
        export_m3u(str(library), str(out))

        lines = self._lines(out)
        extinf = [line for line in lines if line.startswith("#EXTINF:")]
        assert "#EXTINF:2,Alpha Artist - Second Song" in extinf
        assert "#EXTINF:2,Beta Artist - First Song" in extinf
        assert all(line.split(",")[1] for line in extinf)

    def test_an_untagged_file_still_gets_a_name_and_an_honest_duration(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "plain"
        _build(root / "Untagged Track.flac")

        out = tmp_path / "plain.m3u"
        export_m3u(str(root), str(out))

        lines = self._lines(out)
        assert lines[1] == "#EXTINF:2,Untagged Track"


# ── HTML ────────────────────────────────────────────────────────────────────


class TestHtmlExport:
    def test_page_is_self_contained_and_escaped(self, tmp_path: Path) -> None:
        root = tmp_path / "esc"
        _build(
            root / "X.flac",
            artist="A & B",
            album="Alb",
            title="<script>alert(1)</script>",
            tracknumber="1",
            initialkey="C",
        )

        out = tmp_path / "report.html"
        count = export_html(str(root), str(out), columns=("artist", "title", "camelot"))

        assert count == 1
        page = out.read_text(encoding="utf-8")
        assert page.startswith("<!DOCTYPE html>")
        assert '<meta charset="utf-8">' in page
        assert "<th>camelot</th>" in page
        assert "8B" in page
        # No external asset of any kind: the page must open from anywhere.
        assert "http://" not in page
        assert "https://" not in page
        assert "src=" not in page
        # The markup is escaped, so the tag is text rather than a script.
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
        assert "<script>alert(1)</script>" not in page
        # An ampersand in a real tag value is escaped too, not passed through.
        assert "A &amp; B" in page

    def test_non_ascii_survives_the_utf8_write(self, tmp_path: Path) -> None:
        root = tmp_path / "uni"
        _build(root / "U.flac", artist="Beyoncé", title="Déjà Vu", tracknumber="1")

        out = tmp_path / "unicode.html"
        export_html(str(root), str(out), columns=("artist", "title"))

        page = out.read_text(encoding="utf-8")
        assert "Beyoncé" in page
        assert "Déjà Vu" in page


# ── CSV (additive columns only) ─────────────────────────────────────────────


class TestCsvExport:
    LEGACY_COLUMNS = [
        "path",
        "format",
        "bpm",
        "key",
        "genre",
        "mood",
        "tempo_marking",
        "album_artist",
        "artist_album",
        "year",
    ]

    def test_default_columns_are_unchanged(self, library: Path, tmp_path: Path) -> None:
        """The existing export contract must not move: this is the regression lock."""
        out = tmp_path / "legacy.csv"
        export_csv(StatsReport(scan_path=str(library)), str(out))

        with open(out, newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle))
        assert header == self.LEGACY_COLUMNS

    def test_requested_columns_replace_the_set(
        self, library: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "columns.csv"
        export_csv(
            StatsReport(scan_path=str(library)),
            str(out),
            columns=("path", "title", "camelot"),
        )

        with open(out, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert list(rows[0]) == ["path", "title", "camelot"]
        assert [row["camelot"] for row in rows] == ["2A", "8B", "8A"]
        assert [row["title"] for row in rows] == [
            "Second Song",
            "First Song",
            "Third Song",
        ]

    def test_camelot_alone_appends_to_the_legacy_set(
        self, library: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "legacy_camelot.csv"
        export_csv(StatsReport(scan_path=str(library)), str(out), camelot=True)

        with open(out, newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle))
        assert header[: len(self.LEGACY_COLUMNS)] == self.LEGACY_COLUMNS
        assert header[-1] == "camelot"


class TestRowValues:
    def test_absent_values_render_as_empty_not_none(self) -> None:
        row = ExportRow(path="/music/a.flac", format=".flac")
        assert row.value("artist") == ""
        assert row.value("bpm") == ""
        assert row.value("duration") == ""
        assert row.value("camelot") == ""

    def test_display_name_falls_back_through_title_then_stem(self) -> None:
        assert ExportRow(path="/m/a.flac", format=".flac").display_name == "a"
        assert (
            ExportRow(path="/m/a.flac", format=".flac", artist="X").display_name == "X"
        )
        assert (
            ExportRow(path="/m/a.flac", format=".flac", title="T").display_name == "T"
        )

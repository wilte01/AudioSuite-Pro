"""Tests for library_stats.cli — stats command completeness reporting.

Changed in 1.3.0: covers the completeness trend (recording, --trend output,
--history-limit, --no-history) and keeps the CLI's cache in the test's temp
directory, since a plain --completeness run now records a snapshot.

Changed in 1.4.0: the command patches the tag-handler factory, so the real
single-pass ``_read_file_tags`` read stays in the loop, replacing the
per-reader patches of the old eight-read fan-out (PLAN D55).
Changed in 2.2.0: ``TestExportSurface`` covers ``--export {m3u,csv,html}``,
its column set, the Camelot column and the refusals (columns on a playlist, an
empty column list), all against real tagged files (F-05/F-06).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from library_stats.cli import _completeness_status, _echo_completeness
from library_stats.core.completeness import (
    TAG_FIELDS,
    CompletenessReport,
    TagCompleteness,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _sample_report(directory: str) -> CompletenessReport:
    """Build a deterministic 50%-complete report across every tag field."""
    return CompletenessReport(
        directory=directory,
        total_files=2,
        tag_results={
            tag_field: TagCompleteness(
                field=tag_field,
                total=2,
                present=1,
                missing=1,
                pct_complete=50.0,
                missing_files=tuple(
                    [str(Path(directory) / f"{tag_field}_missing.mp3")]
                ),
            )
            for tag_field in TAG_FIELDS
        },
        overall_pct=50.0,
        duration_secs=0.5,
    )


def _report_with_pct(directory: str, pct: float) -> CompletenessReport:
    """Build a report whose per-field percentages are *pct*.

    The snapshot de-duplicator compares the per-field percentages, so a trend
    fixture has to vary them (a report differing only in ``overall_pct`` is
    not a distinct scan).
    """
    return CompletenessReport(
        directory=directory,
        total_files=2,
        tag_results={
            tag_field: TagCompleteness(
                field=tag_field,
                total=2,
                present=1,
                missing=1,
                pct_complete=pct,
            )
            for tag_field in TAG_FIELDS
        },
        overall_pct=pct,
        duration_secs=0.5,
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ── _completeness_status ───────────────────────────────────────────────────────


class TestCompletenessStatus:
    @pytest.mark.parametrize(
        ("pct", "expected"),
        [
            (100.0, "complete"),
            (80.1, "complete"),
            (80.0, "partial"),
            (50.0, "partial"),
            (49.9, "needs work"),
            (0.0, "needs work"),
        ],
    )
    def test_status_thresholds(self, pct: float, expected: str) -> None:
        assert _completeness_status(pct) == expected


# ── _echo_completeness ─────────────────────────────────────────────────────────


class TestEchoCompleteness:
    def test_table_lists_every_tag_field(self, capsys: pytest.CaptureFixture) -> None:
        _echo_completeness(_sample_report("/music"))
        captured = capsys.readouterr().out
        assert "Tag Completeness" in captured
        for tag_field in TAG_FIELDS:
            assert _sample_report("/music").tag_results[tag_field].label in captured
        assert "50.0%" in captured
        assert "Overall" in captured

    def test_detail_lists_missing_files(self, capsys: pytest.CaptureFixture) -> None:
        _echo_completeness(_sample_report("/music"), "bpm")
        captured = capsys.readouterr().out
        assert "Files missing BPM (1)" in captured
        assert "bpm_missing.mp3" in captured

    def test_needs_work_status_shown(self, capsys: pytest.CaptureFixture) -> None:
        report = CompletenessReport(
            directory="/music",
            total_files=1,
            tag_results={
                tag_field: TagCompleteness(
                    field=tag_field,
                    total=1,
                    present=0,
                    missing=1,
                    pct_complete=0.0,
                    missing_files=tuple(),
                )
                for tag_field in TAG_FIELDS
            },
            overall_pct=0.0,
        )
        _echo_completeness(report)
        assert "needs work" in capsys.readouterr().out


# ── stats command integration ──────────────────────────────────────────────────


class TestStatsCompletenessCommand:
    @staticmethod
    @pytest.fixture
    def music_dir(tmp_path: Path) -> str:
        (tmp_path / "a.mp3").write_bytes(b"fake")
        (tmp_path / "b.flac").write_bytes(b"fake")
        return str(tmp_path)

    @staticmethod
    def _cache_path(music_dir: str) -> Path:
        return Path(music_dir) / "cli_cache.db"

    def _invoke(
        self,
        runner: CliRunner,
        music_dir: str,
        *args: str,
        cache_factory: object = None,
    ):
        from audio_suite_shared.cli_app import cli
        from library_stats.library_cache import LibraryCache

        # ``_read_file_tags`` loads one handler per file, so stub the factory
        # rather than the (removed) module-level reader functions.
        handler = MagicMock()
        raw = MagicMock()
        raw.get.return_value = None
        handler.get_raw_tags.return_value = raw
        for reader in (
            "read_artist_album",
            "read_album_artist",
            "read_bpm",
            "read_key",
            "read_genre",
            "read_mood",
            "read_tempo_marking",
        ):
            getattr(handler, reader).return_value = None
        # A plain --completeness run now records a trend snapshot, so the CLI
        # creates the cache even without --incremental: keep it in the test's
        # temp directory instead of the user's real ~/.audiosuite cache.
        cache_path = str(self._cache_path(music_dir))
        factory = cache_factory or (lambda: LibraryCache(cache_path))
        with (
            patch(
                "library_stats.core.file_processor.TagHandlerFactory.get_handler",
                lambda path: handler,
            ),
            patch("library_stats.cli.LibraryCache", factory),
        ):
            return runner.invoke(cli, ["stats", music_dir, *args])

    def test_json_completeness_key_present(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        import json

        result = self._invoke(runner, music_dir, "--json", "--completeness")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert "completeness" in payload
        assert payload["completeness"]["total_files"] == 2
        assert set(payload["completeness"]["tag_results"]) == set(TAG_FIELDS)

    def test_detail_without_completeness_implies_it(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        import json

        result = self._invoke(runner, music_dir, "--json", "--detail", "bpm")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert "completeness" in payload

    def test_invalid_detail_choice_rejected(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        result = self._invoke(runner, music_dir, "--json", "--detail", "banana")
        assert result.exit_code != 0
        assert "Invalid value" in result.output

    def test_trend_prints_recorded_snapshots(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        from library_stats.library_cache import LibraryCache

        cache = LibraryCache(str(self._cache_path(music_dir)))
        try:
            for pct in (40.0, 80.0):
                cache.record_completeness_snapshot(_report_with_pct(music_dir, pct))
        finally:
            cache.close()

        result = self._invoke(runner, music_dir, "--trend", "--no-history")
        assert result.exit_code == 0, result.output
        assert "Completeness Trend (last 2 scans)" in result.output
        assert "40.0% complete" in result.output
        assert "80.0% complete" in result.output

    def test_trend_limit_keeps_only_the_newest(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        from library_stats.library_cache import LibraryCache

        cache = LibraryCache(str(self._cache_path(music_dir)))
        try:
            for pct in (10.0, 20.0, 30.0, 40.0):
                cache.record_completeness_snapshot(_report_with_pct(music_dir, pct))
        finally:
            cache.close()

        result = self._invoke(
            runner, music_dir, "--trend", "--no-history", "--history-limit", "2"
        )
        assert result.exit_code == 0, result.output
        assert "Completeness Trend (last 2 scans)" in result.output
        assert "30.0% complete" in result.output
        assert "40.0% complete" in result.output
        assert "10.0% complete" not in result.output

    def test_trend_without_history_explains_itself(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        result = self._invoke(runner, music_dir, "--trend", "--no-history")
        assert result.exit_code == 0, result.output
        assert "no snapshots recorded yet" in result.output

    def test_completeness_records_a_snapshot(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        result = self._invoke(runner, music_dir, "--completeness", "--no-history")
        assert result.exit_code == 0, result.output

        result = self._invoke(runner, music_dir, "--completeness")
        assert result.exit_code == 0, result.output

        from library_stats.library_cache import LibraryCache

        cache = LibraryCache(str(self._cache_path(music_dir)))
        try:
            history = cache.completeness_history(music_dir)
        finally:
            cache.close()
        assert len(history) == 1
        assert history[0]["total_files"] == 2

    def test_no_history_writes_nothing(self, runner: CliRunner, music_dir: str) -> None:
        result = self._invoke(runner, music_dir, "--completeness", "--no-history")
        assert result.exit_code == 0, result.output
        assert not self._cache_path(music_dir).exists()

    def test_json_trend_key_present(self, runner: CliRunner, music_dir: str) -> None:
        import json

        result = self._invoke(runner, music_dir, "--json", "--trend")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        # This run recorded its own snapshot before reading the trend back.
        assert len(payload["trend"]) == 1
        assert "completeness" in payload

    def test_incremental_run_closes_the_cache_it_created(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        """The CLI owns its cache: it must be closed before the command ends."""
        from library_stats.library_cache import LibraryCache

        closed: list[LibraryCache] = []

        class _SpyCache(LibraryCache):
            def __init__(self) -> None:
                super().__init__(str(Path(music_dir) / "cli_cache.db"))

            def close(self) -> None:
                closed.append(self)
                super().close()

        result = self._invoke(
            runner, music_dir, "--incremental", cache_factory=_SpyCache
        )
        assert result.exit_code == 0, result.output
        assert len(closed) == 1, "the CLI-created cache was never closed"
        assert closed[0]._conn is None, "close() must drop the connection"


def _build_library(root: Path) -> None:
    """Write two real, tagged FLAC files under *root*.

    Skips (with a reason) on a host that cannot encode FLAC, rather than
    leaving a test that can only pass by asserting nothing.
    """
    from mutagen.flac import FLAC
    from pydub import AudioSegment

    root.mkdir(parents=True, exist_ok=True)
    specs = [
        ("track2.flac", {"title": "Two", "tracknumber": "2", "initialkey": "Am"}),
        ("track1.flac", {"title": "One", "tracknumber": "1", "initialkey": "C"}),
    ]
    for name, tags in specs:
        path = root / name
        try:
            AudioSegment.silent(duration=2000).export(str(path), format="flac")
        except Exception as exc:  # pragma: no cover - host without the encoder
            pytest.skip(f"this host cannot encode FLAC ({type(exc).__name__})")
        audio = FLAC(str(path))
        if audio.tags is None:
            audio.add_tags()
        audio["artist"] = ["Artist"]
        audio["album"] = ["Album"]
        for key, value in tags.items():
            audio[key] = [value]
        audio.save()


class TestExportSurface:
    """``--export {m3u,csv,html}``, its column set, and the Camelot column."""

    @pytest.fixture
    def library(self, tmp_path: Path) -> Path:
        root = tmp_path / "library"
        _build_library(root)
        return root

    def _invoke(self, runner: CliRunner, music_dir: Path, *args: str):
        from audio_suite_shared.cli_app import cli

        return runner.invoke(cli, ["stats", str(music_dir), *args])

    def test_m3u_export_writes_a_playlist_a_player_opens(
        self, runner: CliRunner, library: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "mix.m3u"
        result = self._invoke(
            runner, library, "--export", "m3u", "--export-path", str(out)
        )

        assert result.exit_code == 0, result.output
        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "#EXTM3U"
        assert [Path(line).name for line in lines if not line.startswith("#")] == [
            "track1.flac",
            "track2.flac",
        ]
        assert "Exported 2 file(s)" in result.output

    def test_html_export_defaults_beside_the_library(
        self, runner: CliRunner, library: Path
    ) -> None:
        result = self._invoke(runner, library, "--export", "html")

        assert result.exit_code == 0, result.output
        out = library / "library_library.html"
        assert out.exists(), result.output
        assert "<table>" in out.read_text(encoding="utf-8")

    def test_csv_export_honours_the_column_set(
        self, runner: CliRunner, library: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "cols.csv"
        result = self._invoke(
            runner,
            library,
            "--export",
            "csv",
            "--export-path",
            str(out),
            "--export-columns",
            "path,title,camelot",
        )

        assert result.exit_code == 0, result.output
        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "path,title,camelot"
        assert lines[1].endswith("One,8B")

    def test_camelot_applies_to_the_legacy_csv_export(
        self, runner: CliRunner, library: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "legacy.csv"
        result = self._invoke(runner, library, "--export-csv", str(out), "--camelot")

        assert result.exit_code == 0, result.output
        header = out.read_text(encoding="utf-8").splitlines()[0]
        assert header.startswith("path,format,bpm,key,genre,mood")
        assert header.endswith(",camelot")

    def test_export_works_alongside_json(
        self, runner: CliRunner, library: Path, tmp_path: Path
    ) -> None:
        import json

        out = tmp_path / "both.m3u"
        result = self._invoke(
            runner,
            library,
            "--json",
            "--export",
            "m3u",
            "--export-path",
            str(out),
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["total_files"] == 2
        assert out.exists()

    def test_columns_are_refused_for_a_playlist(
        self, runner: CliRunner, library: Path, tmp_path: Path
    ) -> None:
        """A flag that silently did nothing would be worse than an error."""
        out = tmp_path / "mix.m3u"
        result = self._invoke(
            runner,
            library,
            "--export",
            "m3u",
            "--export-path",
            str(out),
            "--export-columns",
            "bpm",
        )

        assert result.exit_code != 0
        assert "not to m3u" in result.output
        assert not out.exists()

    def test_empty_column_list_is_refused(
        self, runner: CliRunner, library: Path, tmp_path: Path
    ) -> None:
        result = self._invoke(
            runner,
            library,
            "--export",
            "csv",
            "--export-path",
            str(tmp_path / "x.csv"),
            "--export-columns",
            " , ,",
        )

        assert result.exit_code != 0
        assert "at least one column" in result.output

    def test_camelot_without_an_export_warns(
        self, runner: CliRunner, library: Path
    ) -> None:
        result = self._invoke(runner, library, "--camelot")

        assert result.exit_code == 0, result.output
        assert "--camelot applies to" in result.output


class TestStatsCommandErrorHandling:
    @staticmethod
    @pytest.fixture
    def music_dir(tmp_path: Path) -> str:
        (tmp_path / "a.mp3").write_bytes(b"fake")
        return str(tmp_path)

    def _invoke(self, runner: CliRunner, music_dir: str, *args: str):
        from audio_suite_shared.cli_app import cli

        return runner.invoke(cli, ["stats", music_dir, *args])

    def test_fatal_scan_oserror_reports_and_exits(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        with patch(
            "library_stats.library_stats.scan_directory",
            side_effect=OSError("unreadable directory"),
        ):
            result = self._invoke(runner, music_dir)
        assert result.exit_code == 1
        assert "FATAL" in result.output
        assert "unreadable directory" in result.output

    def test_csv_export_failure_reported_not_fatal(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        out = str(Path(music_dir).parent / "export.csv")
        with patch(
            "library_stats.library_stats.export_csv",
            side_effect=OSError("disk full"),
        ):
            result = self._invoke(runner, music_dir, "--export-csv", out)
        assert result.exit_code == 0
        assert "CSV exported to" not in result.output
        assert "CSV export failed" in result.output

"""
Tests for TagProcessor class.

Comprehensive test coverage for tag field processing logic, including all
five format processors, edge-case value transformations, and thread-stop
behaviour.

Changed in 2.1.0: adds the tag-processor extension-point host tests.
Changed in 2.1.4: locks the scan-level error tally - one corrupt file is one
error, not the two the CLI used to report (found while wiring the R-06 exit
contract, which reads the same count).
Changed in 2.2.1: covers ``run_scan``, the GUI's entry point (maintenance item
U4) - the payload the three callbacks receive, and the report lines a dry run
and a live run produce.

Changed in 2.4.2: the per-format mock suite is gone because the per-format
rules are.  ``TestFormatProcessors`` asserted what each ``process_*_file`` did to
a mocked mutagen object; that container work now belongs to
``audio_suite_shared.tag_field_engine`` and is tested against real files in
``audio_suite_shared/tests/test_tag_field_engine.py`` and
``test_transformation_rules.py``.  What remains here is this tool's own
contract: extension dispatch, skip/error accounting, the plugin seam and the
undo snapshot (plan WP-6, C-M2).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tag_field_updater.core.processor import (
    ProcessingResult,
    ProcessingStats,
    TagProcessor,
    _log_line,
    count_scanned_files,
    run_scan,
)

# ---------------------------------------------------------------------------
# ProcessingResult
# ---------------------------------------------------------------------------


class TestProcessingResult:
    """Tests for the frozen ProcessingResult dataclass."""

    def test_default_values(self) -> None:
        """Defaults: not updated, no tags, no error."""
        result = ProcessingResult(file_path=Path("/test/file.mp3"))
        assert result.file_path == Path("/test/file.mp3")
        assert result.updated is False
        assert result.tags_updated == ()
        assert result.error is None

    def test_custom_values(self) -> None:
        """Explicit construction stores all supplied values."""
        result = ProcessingResult(
            file_path=Path("/test/file.mp3"),
            updated=True,
            tags_updated=("TIT1", "TCON"),
            error=None,
        )
        assert result.updated is True
        assert result.tags_updated == ("TIT1", "TCON")

    def test_is_frozen(self) -> None:
        """ProcessingResult must be immutable (frozen=True)."""
        import dataclasses

        result = ProcessingResult(file_path=Path("/test/file.mp3"))
        assert dataclasses.fields(result)[0].name == "file_path"
        try:
            result.updated = True  # type: ignore[misc]
            raise AssertionError("Expected FrozenInstanceError was not raised")
        except dataclasses.FrozenInstanceError:
            pass


# ---------------------------------------------------------------------------
# ProcessingStats
# ---------------------------------------------------------------------------


class TestProcessingStats:
    """Tests for the mutable ProcessingStats accumulator dataclass."""

    def test_default_values(self) -> None:
        """All counters start at zero."""
        stats = ProcessingStats()
        assert stats.total_files == 0
        assert stats.processed_files == 0
        assert stats.updated_files == 0
        assert stats.error_files == 0
        assert stats.skipped_files == 0

    def test_mutation(self) -> None:
        """Stats can be incremented freely (not frozen)."""
        stats = ProcessingStats()
        stats.processed_files = 10
        stats.updated_files = 5
        stats.error_files = 1
        assert stats.processed_files == 10
        assert stats.updated_files == 5
        assert stats.error_files == 1


# ---------------------------------------------------------------------------
# TagProcessor initialisation
# ---------------------------------------------------------------------------


class TestTagProcessorInitialization:
    """Tests for TagProcessor construction and class-level constants."""

    def test_default_initialization(self) -> None:
        """Processor starts with zeroed stats and stop_flag=False."""
        processor = TagProcessor()
        assert processor.stats == ProcessingStats()
        assert processor.stop_flag is False

    def test_supported_extensions(self) -> None:
        """All expected extensions are present."""
        processor = TagProcessor()
        expected = (
            ".mp3",
            ".flac",
            ".mp4",
            ".m4a",
            ".ogg",
            ".opus",
            ".wav",
            ".aiff",
            ".aif",
            ".wma",
        )
        for ext in expected:
            assert ext in processor.SUPPORTED_EXTENSIONS

    def test_slash_fields_are_engine_rules(self) -> None:
        """The tool's field list is a subset of the engine's one table.

        The per-format key maps this replaced were a second copy of the
        container keys; the tool now names only the canonical fields it
        rewrites, and a field the engine cannot place fails in the engine's own
        table test rather than silently doing nothing here.
        """
        from audio_suite_shared.tag_field_engine import FIELD_RULES

        processor = TagProcessor()
        names = {rule.name for rule in FIELD_RULES}
        assert processor.SLASH_FIELDS, "the tool declares no fields"
        assert set(processor.SLASH_FIELDS) <= names, (
            f"unknown field(s): {sorted(set(processor.SLASH_FIELDS) - names)}"
        )

    def test_stop_flag_transitions(self) -> None:
        """stop() sets stop_flag to True."""
        processor = TagProcessor()
        assert processor.stop_flag is False
        processor.stop()
        assert processor.stop_flag is True


# ---------------------------------------------------------------------------
# should_update_value
# ---------------------------------------------------------------------------


class TestShouldUpdateValue:
    """Tests for the slash-detection predicate."""

    def test_bare_slash_returns_true(self) -> None:
        """Values with a bare '/' are flagged for update."""
        processor = TagProcessor()
        assert processor.should_update_value("Rock/Pop") is True
        assert processor.should_update_value("Electronic/Dance") is True

    def test_no_slash_returns_false(self) -> None:
        """Values without '/' are not flagged."""
        processor = TagProcessor()
        assert processor.should_update_value("Rock") is False
        assert processor.should_update_value("Jazz") is False

    def test_space_slash_space_still_contains_slash(self) -> None:
        """' / ' contains '/', so should_update_value returns True."""
        processor = TagProcessor()
        assert processor.should_update_value("Rock / Pop") is True

    def test_leading_slash(self) -> None:
        """Leading '/' is detected."""
        processor = TagProcessor()
        assert processor.should_update_value("/Rock") is True

    def test_trailing_slash(self) -> None:
        """Trailing '/' is detected."""
        processor = TagProcessor()
        assert processor.should_update_value("Rock/") is True

    def test_only_slash(self) -> None:
        """A bare '/' alone is detected."""
        processor = TagProcessor()
        assert processor.should_update_value("/") is True


# ---------------------------------------------------------------------------
# update_value
# ---------------------------------------------------------------------------


class TestUpdateValue:
    """Tests for the slash-replacement transformation."""

    def test_simple_slash_replacement(self) -> None:
        """Bare '/' becomes '; '."""
        processor = TagProcessor()
        assert processor.update_value("Rock/Pop") == "Rock; Pop"
        assert processor.update_value("A/B/C") == "A; B; C"

    def test_space_slash_space_preserved(self) -> None:
        """' / ' is preserved verbatim."""
        processor = TagProcessor()
        assert processor.update_value("Rock / Pop") == "Rock / Pop"

    def test_mixed_pattern(self) -> None:
        """Bare '/' within a ' / '-delimited segment is replaced."""
        processor = TagProcessor()
        assert processor.update_value("Rock/Pop / Jazz") == "Rock; Pop / Jazz"

    def test_complex_mixed_pattern(self) -> None:
        """Multiple segments each containing bare slashes are all replaced."""
        processor = TagProcessor()
        assert processor.update_value("A/B / C/D") == "A; B / C; D"

    def test_no_slash_unchanged(self) -> None:
        """Values without '/' are returned unchanged."""
        processor = TagProcessor()
        assert processor.update_value("Rock") == "Rock"
        assert processor.update_value("Pop Music") == "Pop Music"

    def test_leading_slash(self) -> None:
        """Leading '/' is replaced."""
        processor = TagProcessor()
        assert processor.update_value("/Rock") == "; Rock"

    def test_trailing_slash(self) -> None:
        """Trailing '/' is replaced."""
        processor = TagProcessor()
        assert processor.update_value("Rock/") == "Rock; "

    def test_only_slash(self) -> None:
        """A lone '/' becomes '; '."""
        processor = TagProcessor()
        assert processor.update_value("/") == "; "


# ---------------------------------------------------------------------------
# scan_directory
# ---------------------------------------------------------------------------


class TestScanDirectory:
    """Tests for recursive directory scanning."""

    def test_scan_empty_directory(self) -> None:
        """Empty directory produces no results and zero processed files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            processor = TagProcessor()
            results = processor.scan_directory(tmpdir)
            assert results == []
            assert processor.stats.processed_files == 0

    def test_scan_skips_non_audio_files(self) -> None:
        """Non-audio files increment skipped_files, not processed_files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "file.txt").write_text("text")
            Path(tmpdir, "file.jpg").write_bytes(b"image")

            processor = TagProcessor()
            processor.scan_directory(tmpdir)

            assert processor.stats.skipped_files == 2

    def test_stop_flag_halts_processing(self) -> None:
        """Calling stop() mid-scan causes the processor to abort early.

        scan_directory resets stop_flag at entry, so the flag must be set
        from within a progress callback to simulate a mid-scan stop request.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(10):
                Path(tmpdir, f"file_{i}.txt").write_text("x")  # non-audio; fast path

            processor = TagProcessor()
            calls: list[int] = []

            def stop_after_first(filename: str, stats: ProcessingStats) -> None:
                calls.append(stats.processed_files)
                if stats.processed_files >= 1:
                    processor.stop()

            processor.scan_directory(tmpdir, progress_callback=stop_after_first)

            # Stopped early: far fewer than 10 files processed
            assert processor.stats.processed_files < 10
            assert processor.stop_flag is True

    def test_progress_callback_invoked_per_file(self) -> None:
        """Progress callback is called once for each file visited."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "file.mp3").write_bytes(b"audio")

            processor = TagProcessor()
            mock_callback = MagicMock()

            processor.scan_directory(tmpdir, progress_callback=mock_callback)

            mock_callback.assert_called()

    def test_one_failed_file_is_counted_once(self) -> None:
        """One corrupt file is one error, not two.

        ``process_file`` counts its own failures; ``scan_directory`` counted the
        returned ``error`` flag a second time, so both the CLI summary and the
        JSON payload reported a doubled count - and the R-06 exit contract now
        reads that same number.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "broken.mp3").write_bytes(b"this is not an MPEG stream")
            processor = TagProcessor()
            results = processor.scan_directory(tmpdir)

        assert [result.error is not None for result in results] == [True]
        assert processor.stats.processed_files == 1
        assert processor.stats.error_files == 1

    def test_stats_reset_on_each_scan(self) -> None:
        """Stats are zeroed at the start of each scan_directory call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "file.txt").write_text("x")
            processor = TagProcessor()
            processor.scan_directory(tmpdir)
            assert processor.stats.skipped_files == 1

            # Second scan on empty dir must reset to zero
            with tempfile.TemporaryDirectory() as tmpdir2:
                processor.scan_directory(tmpdir2)
                assert processor.stats.skipped_files == 0

    def test_scan_subdirectories(self) -> None:
        """Files in subdirectories are found and processed via os.walk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir, "sub")
            subdir.mkdir()
            Path(subdir, "track.mp3").write_bytes(b"audio")
            Path(tmpdir, "root.mp3").write_bytes(b"audio")

            processor = TagProcessor()

            with patch(
                "tag_field_updater.core.processor.process_file",
                return_value=ProcessingResult(file_path=Path("unused")),
            ):
                results = processor.scan_directory(tmpdir)

            assert len(results) == 2
            assert processor.stats.processed_files == 2

    def test_scan_directory_walk_error_handled(self) -> None:
        """An exception from os.walk is caught and counted as an error."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.os.walk",
            side_effect=PermissionError("access denied"),
        ):
            results = processor.scan_directory("C:\\nonexistent")

        assert processor.stats.error_files == 1
        assert results == []


# ---------------------------------------------------------------------------
# process_file
# ---------------------------------------------------------------------------


class TestProcessFile:
    """Tests for the per-file dispatch logic."""

    def test_skip_unsupported_extension(self) -> None:
        """Unsupported extensions are counted as skipped, not errors."""
        processor = TagProcessor()
        result = processor.process_file(Path("/test/file.txt"))

        assert result.updated is False
        assert result.error is None
        assert processor.stats.skipped_files == 1

    def test_error_is_captured_not_raised(self) -> None:
        """An exception from the format processor populates result.error."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.process_file",
            side_effect=Exception("Read error"),
        ):
            result = processor.process_file(Path("/test/file.mp3"))

        assert result.error is not None
        assert processor.stats.error_files == 1

    def test_error_result_is_not_updated(self) -> None:
        """A file that errors must not be marked as updated."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.process_file",
            side_effect=Exception("boom"),
        ):
            result = processor.process_file(Path("/test/file.mp3"))

        assert result.updated is False

    @pytest.mark.parametrize(
        "name",
        [
            "file.mp3",
            "file.flac",
            "file.m4a",
            "file.mp4",
            "file.ogg",
            "file.opus",
            "file.wav",
            "file.aiff",
            "file.aif",
        ],
    )
    def test_every_supported_extension_reaches_the_one_rule(self, name: str) -> None:
        """Every supported extension reaches the same rule, exactly once.

        The eight per-format delegates are gone; a container that stopped
        reaching the rule would still be counted as processed, so this asserts
        the call as well as the count.
        """
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.process_file",
            return_value=ProcessingResult(file_path=Path("/test") / name),
        ) as mock_rule:
            processor.process_file(Path("/test") / name)

        mock_rule.assert_called_once()
        assert processor.stats.total_files == 1


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end workflow tests using mocked mutagen calls."""

    def test_complete_workflow_progress_tracking(self) -> None:
        """scan_directory calls the progress callback once per file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                Path(tmpdir, f"track_{i}.mp3").write_bytes(b"audio data")

            processor = TagProcessor()
            progress_calls: list[tuple[str, int]] = []

            def track_progress(filename: str, stats: ProcessingStats) -> None:
                progress_calls.append((filename, stats.processed_files))

            with patch(
                "tag_field_updater.core.processor.process_file",
                return_value=ProcessingResult(file_path=Path("unused")),
            ):
                processor.scan_directory(tmpdir, progress_callback=track_progress)

            assert len(progress_calls) == 3
            assert processor.stats.processed_files == 3

    def test_mixed_extensions_only_audio_processed(self) -> None:
        """Only supported audio extensions reach the format processor.

        The .jpg and .txt files are skipped at the extension check; the .mp3
        has no ID3 container, which the rule reports as a skip, so
        skipped_files == 3 and total_files counts only the mp3.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "track.mp3").write_bytes(b"audio")
            Path(tmpdir, "cover.jpg").write_bytes(b"image")
            Path(tmpdir, "info.txt").write_text("text")

            processor = TagProcessor()

            from tag_field_updater.core.transformation_rules import _SkipFile

            with patch(
                "tag_field_updater.core.processor.process_file",
                side_effect=_SkipFile("no ID3 tags found"),
            ):
                processor.scan_directory(tmpdir)

            assert processor.stats.total_files == 1  # mp3 only
            assert processor.stats.skipped_files == 3  # jpg + txt + mp3-no-tags


# ---------------------------------------------------------------------------
# Undo-batch recording (record side of undo feature)
# ---------------------------------------------------------------------------


class TestUndoBatchRecording:
    """The snapshot is recorded once, at the engine's write site."""

    @staticmethod
    def _slashed_mp3(directory: Path) -> Path:
        """Build a real MP3 whose genre carries a bare slash."""
        from mutagen.id3 import ID3, TCON
        from pydub import AudioSegment

        path = directory / "slashed.mp3"
        AudioSegment.silent(duration=200).export(str(path), format="mp3")
        tags = ID3(str(path))
        tags.add(TCON(encoding=3, text="Rock/Pop"))
        tags.save(str(path))
        return path

    def test_mp3_save_records_snapshot_into_active_batch(self, tmp_path: Path) -> None:
        """A live rule run inside a batch logs one snapshot for the file."""
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches
        from tag_field_updater.core.transformation_rules import process_file

        undo_db = tmp_path / "undo_log.db"
        path = self._slashed_mp3(tmp_path)

        with active_batch("tag_field_updater", "tag_edit", db_path=undo_db):
            result = process_file(path)

        assert result.updated is True
        batches = list_recent_batches(limit=10, db_path=undo_db)
        assert len(batches) == 1
        assert batches[0].tool_name == "tag_field_updater"
        assert batches[0].operation_type == "tag_edit"
        assert batches[0].record_count == 1

    def test_no_batch_records_nothing(self, tmp_path: Path) -> None:
        """Without an active batch the snapshot call is a no-op."""
        from audio_suite_shared.batch_undo import BatchUndoLog
        from tag_field_updater.core.transformation_rules import process_file

        undo_db = tmp_path / "undo_log.db"
        path = self._slashed_mp3(tmp_path)

        with BatchUndoLog(db_path=undo_db) as log:
            result = process_file(path)
            assert result.updated is True
            assert log.list_batches() == []


# ---------------------------------------------------------------------------
# Plugin tag processors (the ``tag_processor`` extension point)
# ---------------------------------------------------------------------------

_PLUGIN_MANIFEST = """\
[plugin]
id = "host_probe_plugin"
name = "Host Probe Plugin"
version = "1.0.0"
author = "tests"
description = "Exercises the tag-processor host"
api_version = 1

[[tag_processor]]
id = "stamp_genre"
name = "Stamp the genre"
entry_point = "host_probe_plugin.tags:apply"
"""

_PLUGIN_PROCESSOR = '''\
"""A tag processor that stamps one field, honouring the dry-run flag."""

from types import SimpleNamespace


def apply(path, dry_run, *, context):
    """Write ``genre`` unless this is a dry run."""
    context.write_tag(path, "genre", "Probed") if not dry_run else None
    return SimpleNamespace(changed=True, message="genre stamped")
'''


class TestPluginTagProcessors:
    """The host end of the plugin system's ``tag_processor`` extension point.

    The outcome is read back from disk with a fresh mutagen handle, so a
    processor that silently did not persist is a failure — not a mock's call
    count standing in for the file's contents.
    """

    @staticmethod
    def _install_plugin(tmp_path: Path, monkeypatch: object) -> Path:
        """Create a plugin root holding one enabled tag processor.

        Args:
            tmp_path: The test's scratch directory.
            monkeypatch: The pytest monkeypatch fixture.

        Returns:
            The plugin root, already pointed at by the environment override.
        """
        import sys

        from audio_suite_shared.plugin_system import loader, reset_plugins_for_tests

        # A module name is cached once imported, so a test that rewrites the
        # processor's source (the raising case) would otherwise keep running
        # the previous test's code.
        for name in [
            module
            for module in sys.modules
            if module == "host_probe_plugin" or module.startswith("host_probe_plugin.")
        ]:
            del sys.modules[name]

        root = tmp_path / "plugins"
        package = root / "host_probe_plugin"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "MANIFEST.toml").write_text(_PLUGIN_MANIFEST, encoding="utf-8")
        (package / "tags.py").write_text(_PLUGIN_PROCESSOR, encoding="utf-8")

        monkeypatch.setenv(loader.PLUGIN_DIR_ENV, str(root))  # type: ignore[attr-defined]
        # The enable map lives in the user's shared config; a test must not
        # depend on it (and must not write to it), so it is pinned here.
        monkeypatch.setattr(  # type: ignore[attr-defined]
            loader, "load_enabled_map", lambda: {"host_probe_plugin": True}
        )
        reset_plugins_for_tests()
        return root

    @staticmethod
    def _tagged_mp3(path: Path) -> Path:
        """Export a real MP3 carrying a genre tag."""
        from mutagen.id3 import TCON
        from mutagen.mp3 import MP3
        from pydub import AudioSegment

        AudioSegment.silent(duration=20).export(str(path), format="mp3")
        audio = MP3(str(path))
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TCON(encoding=3, text="Original"))
        audio.save()
        return path

    @staticmethod
    def _genre_on_disk(path: Path) -> str | None:
        """Read the genre back from the file, not from the processor."""
        from audio_suite_shared.tag_helper import read_genre

        return read_genre(str(path))

    def test_enabled_processor_writes_after_the_built_in_rules(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """A live run persists the processor's change and counts it."""
        from audio_suite_shared.plugin_system import reset_plugins_for_tests

        self._install_plugin(tmp_path, monkeypatch)
        try:
            library = tmp_path / "library"
            library.mkdir()
            track = self._tagged_mp3(library / "track.mp3")
            assert self._genre_on_disk(track) == "Original"

            processor = TagProcessor()
            processor.scan_directory(str(library), dry_run=False)

            assert self._genre_on_disk(track) == "Probed"
            assert processor.plugin_changes == 1
            assert processor.plugin_errors == 0
        finally:
            reset_plugins_for_tests()

    def test_dry_run_leaves_the_file_untouched(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """The dry-run flag reaches the processor, which writes nothing."""
        from audio_suite_shared.plugin_system import reset_plugins_for_tests

        self._install_plugin(tmp_path, monkeypatch)
        try:
            library = tmp_path / "library"
            library.mkdir()
            track = self._tagged_mp3(library / "track.mp3")
            before = track.read_bytes()

            processor = TagProcessor()
            processor.scan_directory(str(library), dry_run=True)

            assert track.read_bytes() == before
            assert self._genre_on_disk(track) == "Original"
        finally:
            reset_plugins_for_tests()

    def test_plugins_false_skips_every_processor(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """``plugins=False`` is the switch the CLI's --no-plugin-tags exposes."""
        from audio_suite_shared.plugin_system import reset_plugins_for_tests

        self._install_plugin(tmp_path, monkeypatch)
        try:
            library = tmp_path / "library"
            library.mkdir()
            track = self._tagged_mp3(library / "track.mp3")
            before = track.read_bytes()

            processor = TagProcessor(plugins=False)
            processor.scan_directory(str(library), dry_run=False)

            assert track.read_bytes() == before
            assert self._genre_on_disk(track) == "Original"
            assert processor.plugin_changes == 0
        finally:
            reset_plugins_for_tests()

    def test_a_raising_processor_is_counted_and_does_not_fail_the_file(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """A broken plugin costs its own processor, never the batch."""
        from audio_suite_shared.plugin_system import reset_plugins_for_tests

        self._install_plugin(tmp_path, monkeypatch)
        try:
            broken = tmp_path / "plugins" / "host_probe_plugin" / "tags.py"
            broken.write_text(
                "def apply(path, dry_run):\n    raise RuntimeError('boom')\n",
                encoding="utf-8",
            )
            library = tmp_path / "library"
            library.mkdir()
            track = self._tagged_mp3(library / "track.mp3")

            processor = TagProcessor()
            results = processor.scan_directory(str(library), dry_run=False)

            assert [result.error for result in results] == [None]
            assert self._genre_on_disk(track) == "Original"
            assert processor.plugin_errors == 1
            assert processor.plugin_changes == 0
            assert processor.stats.error_files == 0
        finally:
            reset_plugins_for_tests()


# ---------------------------------------------------------------------------
# run_scan - the GUI's entry point (maintenance item U4)
# ---------------------------------------------------------------------------


class TestCountScannedFiles:
    def test_it_counts_every_file_the_walk_visits(self, tmp_path: Path) -> None:
        """Regression (review of U1): the unit the scan's counter uses.

        ``processed_files`` is incremented for each file the walk visits, so a
        denominator counting only supported extensions read as complete while
        artwork and notes beside a few tracks were still unvisited.
        """
        for name in ("one.mp3", "two.flac", "cover.jpg", "notes.txt"):
            (tmp_path / name).write_bytes(b"")
        (tmp_path / "cd1").mkdir()
        (tmp_path / "cd1" / "three.mp3").write_bytes(b"")

        total = count_scanned_files(str(tmp_path))
        processor = TagProcessor()
        with patch(
            "tag_field_updater.core.processor.process_file",
            return_value=ProcessingResult(file_path=Path("unused")),
        ):
            processor.scan_directory(str(tmp_path))

        assert total == 5
        assert total == processor.stats.processed_files

    def test_an_unreadable_tree_leaves_zero(self) -> None:
        assert count_scanned_files(r"C:\definitely_not_a_directory_12345") == 0


class TestRunScan:
    def test_it_publishes_the_shared_payload(self, tmp_path: Path) -> None:
        """The three callbacks receive the fields every peer's handlers read."""
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        (tmp_path / "broken.mp3").write_bytes(b"not an MPEG stream")
        progress: list[dict[str, Any]] = []
        completed: list[dict[str, Any]] = []
        errors: list[str] = []

        run_scan(
            str(tmp_path),
            is_dry_run=True,
            on_progress=lambda **kw: progress.append(kw),
            on_complete=lambda **kw: completed.append(kw),
            on_error=errors.append,
        )

        assert len(progress) == 2
        assert set(progress[0]) == {
            "processed",
            "total",
            "skipped",
            "errors",
            "display_text",
            "updated",
        }
        assert [kw["total"] for kw in progress] == [2, 2]
        assert errors == []
        assert len(completed) == 1
        payload = completed[0]
        assert payload["total"] == 2
        assert payload["processed"] == 2
        assert payload["skipped"] == 1
        assert payload["errors"] == 1
        assert payload["updated"] == 0
        assert payload["audio_files"] == 1
        assert len(payload["log_entries"]) == 2
        assert payload["duration_secs"] >= 0

    def test_a_failed_sweep_reports_one_message(self, tmp_path: Path) -> None:
        """A fatal scan reaches ``on_error`` instead of raising at the caller."""
        engine = MagicMock()
        engine.scan_directory.side_effect = RuntimeError("boom")
        errors: list[str] = []

        run_scan(
            str(tmp_path),
            is_dry_run=True,
            on_progress=MagicMock(),
            on_complete=MagicMock(),
            on_error=errors.append,
            processor=engine,
        )

        # The neutral user-facing message, not the internal exception text:
        # the UI reports a message, the log carries the traceback.
        assert len(errors) == 1
        assert errors[0].strip()

    def test_it_uses_the_processor_it_is_given(self, tmp_path: Path) -> None:
        """The window's Stop button signals this instance, so it must be used."""
        engine = TagProcessor()
        run_scan(
            str(tmp_path),
            is_dry_run=True,
            on_progress=MagicMock(),
            on_complete=MagicMock(),
            on_error=MagicMock(),
            processor=engine,
        )

        assert engine.stats.processed_files == 0
        assert engine.stop_flag is False

    def test_the_run_is_recorded_as_one_undo_batch(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        from audio_suite_shared.batch_undo import list_recent_batches

        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        seen: list[Any] = []

        def _fake_scan(directory: str, **kwargs: Any) -> list[ProcessingResult]:
            seen.append(list_recent_batches())
            return []

        engine = TagProcessor()
        monkeypatch.setattr(engine, "scan_directory", _fake_scan)

        run_scan(
            str(tmp_path),
            is_dry_run=True,
            on_progress=MagicMock(),
            on_complete=MagicMock(),
            on_error=MagicMock(),
            processor=engine,
        )

        assert seen, "the scan never ran inside an undo batch"


class TestLogLine:
    """The run report's per-file lines."""

    def test_a_dry_run_says_would_update(self) -> None:
        result = ProcessingResult(
            file_path=Path("/music/a.mp3"),
            updated=True,
            tags_updated=("TXXX:ALBUMGENRE",),
        )

        assert _log_line(result, is_dry_run=True, filename_mode=False).startswith(
            "[WOULD UPDATE] a.mp3"
        )

    def test_a_live_run_says_updated(self) -> None:
        result = ProcessingResult(
            file_path=Path("/music/a.mp3"),
            updated=True,
            tags_updated=("TXXX:ALBUMGENRE",),
        )

        line = _log_line(result, is_dry_run=False, filename_mode=False)

        assert line.startswith("[UPDATED] a.mp3")
        assert "TXXX:ALBUMGENRE" in line

    def test_an_unsupported_file_is_a_skip(self) -> None:
        result = ProcessingResult(file_path=Path("/music/cover.jpg"))

        line = _log_line(result, is_dry_run=False, filename_mode=False)

        assert line.startswith("[SKIP]")
        assert "unsupported format" in line

    def test_a_filename_mode_no_match_is_named(self) -> None:
        result = ProcessingResult(file_path=Path("/music/a.mp3"), filename_pattern="")

        line = _log_line(result, is_dry_run=False, filename_mode=True)

        assert line.startswith("[NO MATCH] a.mp3")

    def test_an_error_carries_its_message(self) -> None:
        result = ProcessingResult(file_path=Path("/music/a.mp3"), error="bad header")

        line = _log_line(result, is_dry_run=False, filename_mode=False)

        assert line.startswith("[ERROR]")
        assert "bad header" in line

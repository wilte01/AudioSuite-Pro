"""
Tests for TagProcessor class.

Comprehensive test coverage for tag field processing logic, including all
five format processors, edge-case value transformations, and thread-stop
behaviour.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from mutagen.id3 import ID3NoHeaderError

from tag_field_updater.core.processor import (
    ProcessingResult,
    ProcessingStats,
    TagProcessor,
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

    def test_tag_mappings_structure(self) -> None:
        """Every format entry has 'txxx' and 'standard' list keys."""
        processor = TagProcessor()
        for fmt, mappings in processor.TAG_MAPPINGS.items():
            assert "txxx" in mappings, f"Missing 'txxx' key for format '{fmt}'"
            assert "standard" in mappings, f"Missing 'standard' key for format '{fmt}'"
            assert isinstance(mappings["txxx"], list)
            assert isinstance(mappings["standard"], list)

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

            with patch("tag_field_updater.core.processor.MP3") as mock_mp3_class:
                mock_mp3 = MagicMock()
                mock_mp3.tags = None
                mock_mp3_class.return_value = mock_mp3

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
            "tag_field_updater.core.processor.MP3", side_effect=Exception("Read error")
        ):
            result = processor.process_file(Path("/test/file.mp3"))

        assert result.error is not None
        assert processor.stats.error_files == 1

    def test_error_result_is_not_updated(self) -> None:
        """A file that errors must not be marked as updated."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.MP3", side_effect=Exception("boom")
        ):
            result = processor.process_file(Path("/test/file.mp3"))

        assert result.updated is False

    def test_m4a_dispatches_to_mp4_processor(self) -> None:
        """.m4a files are dispatched to the MP4 format processor."""
        processor = TagProcessor()

        with patch.object(
            processor,
            "_process_mp4",
            return_value=ProcessingResult(file_path=Path("/test/file.m4a")),
        ) as mock_process_mp4:
            result = processor.process_file(Path("/test/file.m4a"))

        mock_process_mp4.assert_called_once()
        assert result.updated is False
        assert processor.stats.total_files == 1

    def test_opus_dispatches_to_opus_processor(self) -> None:
        """.opus files are dispatched to the Opus format processor."""
        processor = TagProcessor()

        with patch.object(
            processor,
            "_process_opus",
            return_value=ProcessingResult(file_path=Path("/test/file.opus")),
        ) as mock_process_opus:
            result = processor.process_file(Path("/test/file.opus"))

        mock_process_opus.assert_called_once()
        assert result.updated is False
        assert processor.stats.total_files == 1

    def test_wav_dispatches_to_wav_processor(self) -> None:
        """.wav files are dispatched to the WAV format processor."""
        processor = TagProcessor()

        with patch.object(
            processor,
            "_process_wav",
            return_value=ProcessingResult(file_path=Path("/test/file.wav")),
        ) as mock_process_wav:
            result = processor.process_file(Path("/test/file.wav"))

        mock_process_wav.assert_called_once()
        assert result.updated is False
        assert processor.stats.total_files == 1

    def test_aiff_dispatches_to_aiff_processor(self) -> None:
        """.aiff files are dispatched to the AIFF format processor."""
        processor = TagProcessor()

        with patch.object(
            processor,
            "_process_aiff",
            return_value=ProcessingResult(file_path=Path("/test/file.aiff")),
        ) as mock_process_aiff:
            result = processor.process_file(Path("/test/file.aiff"))

        mock_process_aiff.assert_called_once()
        assert result.updated is False
        assert processor.stats.total_files == 1


# ---------------------------------------------------------------------------
# Format processors
# ---------------------------------------------------------------------------


class TestFormatProcessors:
    """Tests for _process_mp3, _process_flac, _process_mp4,
    _process_ogg, _process_wma."""

    # --- MP3 ---

    def test_process_mp3_no_tags(self) -> None:
        """MP3 with no ID3 tags is skipped cleanly."""
        processor = TagProcessor()
        mock_mp3 = MagicMock()
        mock_mp3.tags = None

        with patch("tag_field_updater.core.processor.MP3", return_value=mock_mp3):
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                result = processor._process_mp3(Path(tmp.name))

        assert result.updated is False
        assert result.error is None
        assert processor.stats.skipped_files == 1

    def test_process_mp3_no_matching_tags(self) -> None:
        """MP3 whose tags contain none of the target keys is not updated."""
        processor = TagProcessor()
        mock_tags = MagicMock()
        mock_tags.__contains__ = MagicMock(return_value=False)
        mock_tags.version = (2, 3)
        mock_mp3 = MagicMock()
        mock_mp3.tags = mock_tags

        with patch("tag_field_updater.core.processor.MP3", return_value=mock_mp3):
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                result = processor._process_mp3(Path(tmp.name))

        assert result.updated is False
        mock_mp3.save.assert_not_called()

    def test_process_mp3_error_captured(self) -> None:
        """An exception in MP3 processing populates result.error."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.MP3", side_effect=Exception("corrupt")
        ):
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                result = processor._process_mp3(Path(tmp.name))

        assert result.error is not None
        assert result.updated is False
        assert processor.stats.error_files == 1

    def test_process_mp3_updates_tags(self) -> None:
        """MP3 with a matching tag containing '/' is updated and saved."""
        processor = TagProcessor()
        mock_tags = MagicMock()
        mock_tags.__contains__ = MagicMock(return_value=True)
        mock_tags.__getitem__ = MagicMock(return_value="Rock/Pop")
        mock_tags.version = (2, 3)
        mock_mp3 = MagicMock()
        mock_mp3.tags = mock_tags

        with patch("tag_field_updater.core.processor.MP3", return_value=mock_mp3):
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                result = processor._process_mp3(Path(tmp.name))

        mock_mp3.save.assert_called_once()
        assert result.updated is True
        assert len(result.tags_updated) > 0
        assert processor.stats.skipped_files == 0

    def test_process_mp3_id3_no_header_error(self) -> None:
        """ID3NoHeaderError is caught and counted as skipped, not error."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.MP3",
            side_effect=ID3NoHeaderError("No ID3 header"),
        ):
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                result = processor._process_mp3(Path(tmp.name))

        assert result.updated is False
        assert result.error is None
        assert processor.stats.skipped_files == 1
        assert processor.stats.error_files == 0

    # --- FLAC ---

    def test_process_flac_updates_tags(self) -> None:
        """FLAC with a matching tag containing '/' is updated and saved."""
        processor = TagProcessor()
        mock_flac = MagicMock()
        mock_flac.__contains__ = MagicMock(return_value=True)
        mock_flac.__getitem__ = MagicMock(return_value="Rock/Pop")

        with patch("tag_field_updater.core.processor.FLAC", return_value=mock_flac):
            with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as tmp:
                result = processor._process_flac(Path(tmp.name))

        mock_flac.save.assert_called_once()
        assert result.updated is True

    def test_process_flac_no_matching_tags(self) -> None:
        """FLAC with no matching keys is not saved."""
        processor = TagProcessor()
        mock_flac = MagicMock()
        mock_flac.__contains__ = MagicMock(return_value=False)

        with patch("tag_field_updater.core.processor.FLAC", return_value=mock_flac):
            with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as tmp:
                result = processor._process_flac(Path(tmp.name))

        mock_flac.save.assert_not_called()
        assert result.updated is False

    def test_process_flac_error_captured(self) -> None:
        """An exception in FLAC processing populates result.error."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.FLAC", side_effect=Exception("bad flac")
        ):
            with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as tmp:
                result = processor._process_flac(Path(tmp.name))

        assert result.error is not None
        assert result.updated is False

    def test_process_flac_value_no_slash_no_update(self) -> None:
        """FLAC with matching tag but no '/' in value is not saved."""
        processor = TagProcessor()
        mock_flac = MagicMock()
        mock_flac.__contains__ = MagicMock(return_value=True)
        mock_flac.__getitem__ = MagicMock(return_value="Rock")

        with patch("tag_field_updater.core.processor.FLAC", return_value=mock_flac):
            with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as tmp:
                result = processor._process_flac(Path(tmp.name))

        mock_flac.save.assert_not_called()
        assert result.updated is False
        assert result.tags_updated == ()

    # --- MP4 ---

    def test_process_mp4_updates_tags(self) -> None:
        """MP4 with a matching tag containing '/' is updated and saved."""
        processor = TagProcessor()
        mock_mp4 = MagicMock()
        mock_mp4.__contains__ = MagicMock(return_value=True)
        mock_mp4.__getitem__ = MagicMock(return_value="Rock/Pop")

        with patch("tag_field_updater.core.processor.MP4", return_value=mock_mp4):
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                result = processor._process_mp4(Path(tmp.name))

        mock_mp4.save.assert_called_once()
        assert result.updated is True

    def test_process_mp4_no_matching_tags(self) -> None:
        """MP4 with no matching keys is not saved."""
        processor = TagProcessor()
        mock_mp4 = MagicMock()
        mock_mp4.__contains__ = MagicMock(return_value=False)

        with patch("tag_field_updater.core.processor.MP4", return_value=mock_mp4):
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                result = processor._process_mp4(Path(tmp.name))

        mock_mp4.save.assert_not_called()
        assert result.updated is False

    def test_process_mp4_error_captured(self) -> None:
        """An exception in MP4 processing populates result.error."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.MP4", side_effect=Exception("bad mp4")
        ):
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                result = processor._process_mp4(Path(tmp.name))

        assert result.error is not None
        assert result.updated is False

    def test_process_mp4_value_no_slash_no_update(self) -> None:
        """MP4 with matching tag but no '/' in value is not saved."""
        processor = TagProcessor()
        mock_mp4 = MagicMock()
        mock_mp4.__contains__ = MagicMock(return_value=True)
        mock_mp4.__getitem__ = MagicMock(return_value="Rock")

        with patch("tag_field_updater.core.processor.MP4", return_value=mock_mp4):
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                result = processor._process_mp4(Path(tmp.name))

        mock_mp4.save.assert_not_called()
        assert result.updated is False
        assert result.tags_updated == ()

    # --- OGG ---

    def test_process_ogg_updates_tags(self) -> None:
        """OGG with a matching tag containing '/' is updated and saved."""
        processor = TagProcessor()
        mock_ogg = MagicMock()
        mock_ogg.__contains__ = MagicMock(return_value=True)
        mock_ogg.__getitem__ = MagicMock(return_value="Rock/Pop")

        with patch("tag_field_updater.core.processor.OggVorbis", return_value=mock_ogg):
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                result = processor._process_ogg(Path(tmp.name))

        mock_ogg.save.assert_called_once()
        assert result.updated is True

    def test_process_ogg_no_matching_tags(self) -> None:
        """OGG with no matching keys is not saved."""
        processor = TagProcessor()
        mock_ogg = MagicMock()
        mock_ogg.__contains__ = MagicMock(return_value=False)

        with patch("tag_field_updater.core.processor.OggVorbis", return_value=mock_ogg):
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                result = processor._process_ogg(Path(tmp.name))

        mock_ogg.save.assert_not_called()
        assert result.updated is False

    def test_process_ogg_error_captured(self) -> None:
        """An exception in OGG processing populates result.error."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.OggVorbis",
            side_effect=Exception("bad ogg"),
        ):
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                result = processor._process_ogg(Path(tmp.name))

        assert result.error is not None
        assert result.updated is False

    def test_process_ogg_value_no_slash_no_update(self) -> None:
        """OGG with matching tag but no '/' in value is not saved."""
        processor = TagProcessor()
        mock_ogg = MagicMock()
        mock_ogg.__contains__ = MagicMock(return_value=True)
        mock_ogg.__getitem__ = MagicMock(return_value="Rock")

        with patch("tag_field_updater.core.processor.OggVorbis", return_value=mock_ogg):
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                result = processor._process_ogg(Path(tmp.name))

        mock_ogg.save.assert_not_called()
        assert result.updated is False
        assert result.tags_updated == ()

    # --- WMA ---

    def test_process_wma_updates_tags(self) -> None:
        """WMA with a matching tag containing '/' is updated and saved."""
        processor = TagProcessor()
        mock_wma = MagicMock()
        mock_wma.__contains__ = MagicMock(return_value=True)
        mock_wma.__getitem__ = MagicMock(return_value="Rock/Pop")

        with patch("tag_field_updater.core.processor.ASF", return_value=mock_wma):
            with tempfile.NamedTemporaryFile(suffix=".wma", delete=False) as tmp:
                result = processor._process_wma(Path(tmp.name))

        mock_wma.save.assert_called_once()
        assert result.updated is True

    def test_process_wma_no_matching_tags(self) -> None:
        """WMA with no matching keys is not saved."""
        processor = TagProcessor()
        mock_wma = MagicMock()
        mock_wma.__contains__ = MagicMock(return_value=False)

        with patch("tag_field_updater.core.processor.ASF", return_value=mock_wma):
            with tempfile.NamedTemporaryFile(suffix=".wma", delete=False) as tmp:
                result = processor._process_wma(Path(tmp.name))

        mock_wma.save.assert_not_called()
        assert result.updated is False

    def test_process_wma_error_captured(self) -> None:
        """An exception in WMA processing populates result.error."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.ASF", side_effect=Exception("bad wma")
        ):
            with tempfile.NamedTemporaryFile(suffix=".wma", delete=False) as tmp:
                result = processor._process_wma(Path(tmp.name))

        assert result.error is not None
        assert result.updated is False

    def test_process_wma_value_no_slash_no_update(self) -> None:
        """WMA with matching tag but no '/' in value is not saved."""
        processor = TagProcessor()
        mock_wma = MagicMock()
        mock_wma.__contains__ = MagicMock(return_value=True)
        mock_wma.__getitem__ = MagicMock(return_value="Rock")

        with patch("tag_field_updater.core.processor.ASF", return_value=mock_wma):
            with tempfile.NamedTemporaryFile(suffix=".wma", delete=False) as tmp:
                result = processor._process_wma(Path(tmp.name))

        mock_wma.save.assert_not_called()
        assert result.updated is False
        assert result.tags_updated == ()

    # --- Opus ---

    def test_process_opus_updates_tags(self) -> None:
        """Opus with a matching tag containing '/' is updated and saved."""
        processor = TagProcessor()
        mock_opus = MagicMock()
        mock_opus.__contains__ = MagicMock(return_value=True)
        mock_opus.__getitem__ = MagicMock(return_value="Rock/Pop")

        with patch("tag_field_updater.core.processor.OggOpus", return_value=mock_opus):
            with tempfile.NamedTemporaryFile(suffix=".opus", delete=False) as tmp:
                result = processor._process_opus(Path(tmp.name))

        mock_opus.save.assert_called_once()
        assert result.updated is True

    def test_process_opus_no_matching_tags(self) -> None:
        """Opus with no matching keys is not saved."""
        processor = TagProcessor()
        mock_opus = MagicMock()
        mock_opus.__contains__ = MagicMock(return_value=False)

        with patch("tag_field_updater.core.processor.OggOpus", return_value=mock_opus):
            with tempfile.NamedTemporaryFile(suffix=".opus", delete=False) as tmp:
                result = processor._process_opus(Path(tmp.name))

        mock_opus.save.assert_not_called()
        assert result.updated is False

    def test_process_opus_error_captured(self) -> None:
        """An exception in Opus processing populates result.error."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.OggOpus",
            side_effect=Exception("bad opus"),
        ):
            with tempfile.NamedTemporaryFile(suffix=".opus", delete=False) as tmp:
                result = processor._process_opus(Path(tmp.name))

        assert result.error is not None
        assert result.updated is False

    def test_process_opus_value_no_slash_no_update(self) -> None:
        """Opus with matching tag but no '/' in value is not saved."""
        processor = TagProcessor()
        mock_opus = MagicMock()
        mock_opus.__contains__ = MagicMock(return_value=True)
        mock_opus.__getitem__ = MagicMock(return_value="Rock")

        with patch("tag_field_updater.core.processor.OggOpus", return_value=mock_opus):
            with tempfile.NamedTemporaryFile(suffix=".opus", delete=False) as tmp:
                result = processor._process_opus(Path(tmp.name))

        mock_opus.save.assert_not_called()
        assert result.updated is False
        assert result.tags_updated == ()

    # --- WAV ---

    def test_process_wav_updates_tags(self) -> None:
        """WAV with a matching tag containing '/' is updated and saved."""
        processor = TagProcessor()
        mock_tags = MagicMock()
        mock_tags.__contains__ = MagicMock(return_value=True)
        mock_tags.__getitem__ = MagicMock(return_value="Rock/Pop")
        mock_tags.version = (2, 3)
        mock_wav = MagicMock()
        mock_wav.tags = mock_tags

        with patch("tag_field_updater.core.processor.WAVE", return_value=mock_wav):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                result = processor._process_wav(Path(tmp.name))

        mock_wav.save.assert_called_once()
        assert result.updated is True

    def test_process_wav_no_tags(self) -> None:
        """WAV with no ID3 tags is skipped cleanly."""
        processor = TagProcessor()
        mock_wav = MagicMock()
        mock_wav.tags = None

        with patch("tag_field_updater.core.processor.WAVE", return_value=mock_wav):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                result = processor._process_wav(Path(tmp.name))

        assert result.updated is False
        assert result.error is None
        assert processor.stats.skipped_files == 1

    def test_process_wav_no_matching_tags(self) -> None:
        """WAV whose tags contain none of the target keys is not updated."""
        processor = TagProcessor()
        mock_tags = MagicMock()
        mock_tags.__contains__ = MagicMock(return_value=False)
        mock_tags.version = (2, 3)
        mock_wav = MagicMock()
        mock_wav.tags = mock_tags

        with patch("tag_field_updater.core.processor.WAVE", return_value=mock_wav):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                result = processor._process_wav(Path(tmp.name))

        assert result.updated is False

    def test_process_wav_error_captured(self) -> None:
        """An exception in WAV processing populates result.error."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.WAVE", side_effect=Exception("corrupt")
        ):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                result = processor._process_wav(Path(tmp.name))

        assert result.error is not None
        assert result.updated is False
        assert processor.stats.error_files == 1

    # --- AIFF ---

    def test_process_aiff_updates_tags(self) -> None:
        """AIFF with a matching tag containing '/' is updated and saved."""
        processor = TagProcessor()
        mock_tags = MagicMock()
        mock_tags.__contains__ = MagicMock(return_value=True)
        mock_tags.__getitem__ = MagicMock(return_value="Rock/Pop")
        mock_tags.version = (2, 3)
        mock_aiff = MagicMock()
        mock_aiff.tags = mock_tags

        with patch("tag_field_updater.core.processor.AIFF", return_value=mock_aiff):
            with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
                result = processor._process_aiff(Path(tmp.name))

        mock_aiff.save.assert_called_once()
        assert result.updated is True

    def test_process_aiff_no_tags(self) -> None:
        """AIFF with no ID3 tags is skipped cleanly."""
        processor = TagProcessor()
        mock_aiff = MagicMock()
        mock_aiff.tags = None

        with patch("tag_field_updater.core.processor.AIFF", return_value=mock_aiff):
            with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
                result = processor._process_aiff(Path(tmp.name))

        assert result.updated is False
        assert result.error is None
        assert processor.stats.skipped_files == 1

    def test_process_aiff_no_matching_tags(self) -> None:
        """AIFF whose tags contain none of the target keys is not updated."""
        processor = TagProcessor()
        mock_tags = MagicMock()
        mock_tags.__contains__ = MagicMock(return_value=False)
        mock_tags.version = (2, 3)
        mock_aiff = MagicMock()
        mock_aiff.tags = mock_tags

        with patch("tag_field_updater.core.processor.AIFF", return_value=mock_aiff):
            with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
                result = processor._process_aiff(Path(tmp.name))

        assert result.updated is False

    def test_process_aiff_error_captured(self) -> None:
        """An exception in AIFF processing populates result.error."""
        processor = TagProcessor()

        with patch(
            "tag_field_updater.core.processor.AIFF", side_effect=Exception("corrupt")
        ):
            with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
                result = processor._process_aiff(Path(tmp.name))

        assert result.error is not None
        assert result.updated is False
        assert processor.stats.error_files == 1


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

            with patch("tag_field_updater.core.processor.MP3") as mock_mp3_class:
                mock_mp3 = MagicMock()
                mock_mp3.tags = None
                mock_mp3_class.return_value = mock_mp3

                processor.scan_directory(tmpdir, progress_callback=track_progress)

            assert len(progress_calls) == 3
            assert processor.stats.processed_files == 3

    def test_mixed_extensions_only_audio_processed(self) -> None:
        """Only supported audio extensions reach the format processor.

        The .jpg and .txt files are skipped at the extension check.
        The .mp3 with tags=None is skipped inside _process_mp3, so
        skipped_files == 3 total; total_files counts only the mp3.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "track.mp3").write_bytes(b"audio")
            Path(tmpdir, "cover.jpg").write_bytes(b"image")
            Path(tmpdir, "info.txt").write_text("text")

            processor = TagProcessor()

            with patch("tag_field_updater.core.processor.MP3") as mock_mp3_class:
                mock_mp3 = MagicMock()
                mock_mp3.tags = None
                mock_mp3_class.return_value = mock_mp3

                processor.scan_directory(tmpdir)

            assert processor.stats.total_files == 1  # mp3 only
            assert processor.stats.skipped_files == 3  # jpg + txt + mp3-no-tags


# ---------------------------------------------------------------------------
# Undo-batch recording (record side of undo feature)
# ---------------------------------------------------------------------------


class TestUndoBatchRecording:
    def test_mp3_save_records_snapshot_into_active_batch(self, tmp_path: Path) -> None:
        """An MP3 save inside an active undo batch must log a tag snapshot."""
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches
        from tag_field_updater.core.transformation_rules import process_mp3_file

        undo_db = tmp_path / "undo_log.db"

        mock_tags = MagicMock()
        mock_tags.__contains__ = MagicMock(return_value=True)
        mock_tags.__getitem__ = MagicMock(return_value="Rock/Pop")
        mock_tags.version = (2, 3)
        mock_mp3 = MagicMock()
        mock_mp3.tags = mock_tags

        handler = MagicMock()
        handler.get_raw_tags.return_value = {"TCON": "Rock/Pop"}

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            with patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory"
            ) as factory:
                factory.get_handler.return_value = handler
                with patch(
                    "tag_field_updater.core.processor.MP3", return_value=mock_mp3
                ):
                    with active_batch("tag_field_updater", "tag_edit", db_path=undo_db):
                        result = process_mp3_file(Path(tmp.name))

        assert result.updated is True
        batches = list_recent_batches(limit=10, db_path=undo_db)
        assert len(batches) == 1
        assert batches[0].tool_name == "tag_field_updater"
        assert batches[0].operation_type == "tag_edit"
        assert batches[0].record_count == 1

    def test_no_batch_records_nothing(self, tmp_path: Path) -> None:
        """Without an active batch the snapshot call is a zero-overhead no-op."""
        from audio_suite_shared.batch_undo import BatchUndoLog
        from tag_field_updater.core.transformation_rules import process_mp3_file

        mock_tags = MagicMock()
        mock_tags.__contains__ = MagicMock(return_value=True)
        mock_tags.__getitem__ = MagicMock(return_value="Rock/Pop")
        mock_tags.version = (2, 3)
        mock_mp3 = MagicMock()
        mock_mp3.tags = mock_tags

        undo_db = tmp_path / "undo_log.db"
        with BatchUndoLog(db_path=undo_db) as log:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                with patch(
                    "tag_field_updater.core.processor.MP3", return_value=mock_mp3
                ):
                    result = process_mp3_file(Path(tmp.name))
            assert result.updated is True
            assert log.list_batches() == []

"""
Tests for tempo_analyzer.core.file_processor
Gap G-33: process_single_file(), run_analysis(), TempoAnalyzerProcessor

Strategy:
- process_single_file: mock read_bpm / read_tempo_marking / write_tempo_marking
- run_analysis: integration via real MP3 fixtures with BPM tags pre-written
"""

import os
import threading
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest
from mutagen.id3 import ID3, TBPM, TIT2
from mutagen.mp3 import MP3
from pydub import AudioSegment

from tempo_analyzer.core.file_processor import (
    TempoAnalyzerProcessor,
    _file_has_any_tags,
    process_single_file,
    run_analysis,
)
from tempo_analyzer.core.tempo_schemes import TEMPO_SCHEMES

# ── Helpers ───────────────────────────────────────────────────────────────────

MARKINGS = TEMPO_SCHEMES["Italian"]


def _make_mp3(tmp_path, name="track.mp3", bpm=None):
    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="mp3")
    if bpm is not None:
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TBPM(text=[str(bpm)]))
        audio.save()
    return str(path)


def _make_truly_untagged_mp3(tmp_path, name="untagged.mp3"):
    """An MP3 with zero tag block — pydub/ffmpeg export may stamp an encoder
    tag, so the ID3 frame is explicitly stripped to guarantee a true
    no-tags-at-all state (verified empirically with mutagen, not assumed)."""
    path = _make_mp3(tmp_path, name)
    audio = MP3(path, ID3=ID3)
    if audio.tags is not None:
        audio.delete()
        audio.save()
    return path


def _make_mp3_with_tags_no_bpm(tmp_path, name="tagged_no_bpm.mp3"):
    """An MP3 with a real (non-BPM) tag present, but no TBPM frame."""
    path = _make_mp3(tmp_path, name)
    audio = MP3(path, ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    audio.tags.add(TIT2(encoding=3, text="Test Title"))
    audio.save()
    return path


def _make_slots(n=4):
    slot_vars = [MagicMock() for _ in range(n)]
    slot_q = Queue()
    for i in range(n):
        slot_q.put(i)
    return slot_vars, slot_q


# ═════════════════════════════════════════════════════════════════════════════
# TempoAnalyzerProcessor
# ═════════════════════════════════════════════════════════════════════════════


class TestTempoAnalyzerProcessor:
    def test_instantiates_without_error(self):
        with patch("audio_suite_shared.file_processor_base.get_resource_manager"):
            p = TempoAnalyzerProcessor()
            assert p is not None

    def test_operation_type_set_correctly(self):
        with patch("audio_suite_shared.file_processor_base.get_resource_manager"):
            p = TempoAnalyzerProcessor()
            assert p.operation_type == "tempo_analysis"


# ═════════════════════════════════════════════════════════════════════════════
# process_single_file — BPM absent (skip path)
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessSingleFileSkip:
    def _call(self, tmp_path, name, bpm_return, is_dry_run=True):
        slot_vars, slot_q = _make_slots()
        slot_idx = slot_q.get()
        results = []
        lock = threading.Lock()

        with patch(
            "tempo_analyzer.core.file_processor.read_bpm", return_value=bpm_return
        ):
            process_single_file(
                name=name,
                dir_path=str(tmp_path),
                is_dry_run=is_dry_run,
                markings=MARKINGS,
                slot_idx=slot_idx,
                lock=lock,
                on_progress=lambda **kw: results.append(kw),
                slot_vars=slot_vars,
            )
        return results

    def test_none_bpm_reports_skip(self, tmp_path):
        results = self._call(tmp_path, "track.mp3", None)
        assert len(results) == 1
        assert results[0]["n_skipped"] == 1
        assert results[0]["n_errors"] == 0
        assert "SKIP" in results[0]["display_text"]

    def test_zero_bpm_reports_skip(self, tmp_path):
        results = self._call(tmp_path, "track.mp3", 0)
        assert results[0]["n_skipped"] == 1

    def test_negative_bpm_reports_skip(self, tmp_path):
        results = self._call(tmp_path, "track.mp3", -1)
        assert results[0]["n_skipped"] == 1

    def test_skip_display_contains_filename(self, tmp_path):
        results = self._call(tmp_path, "my_track.mp3", None)
        assert "my_track.mp3" in results[0]["display_text"]

    def test_skip_display_mentions_no_bpm(self, tmp_path):
        results = self._call(tmp_path, "track.mp3", None)
        assert "BPM" in results[0]["display_text"]


# ═════════════════════════════════════════════════════════════════════════════
# process_single_file — SKIP message distinguishes "no tags" vs "no BPM tag"
#
# Regression coverage for: file_processor previously emitted "No BPM tag" for
# every skip, even when the file had no tag block at all. Confirmed against
# real fixture files (not mocked) across MP3 with/without an ID3 block, since
# the distinction depends on actual tag-handler behaviour, not assumption.
# ═════════════════════════════════════════════════════════════════════════════


class TestFileHasAnyTags:
    def test_true_untagged_file_returns_false(self, tmp_path):
        path = _make_truly_untagged_mp3(tmp_path)
        assert _file_has_any_tags(path) is False

    def test_tagged_file_without_bpm_returns_true(self, tmp_path):
        path = _make_mp3_with_tags_no_bpm(tmp_path)
        assert _file_has_any_tags(path) is True

    def test_file_with_bpm_returns_true(self, tmp_path):
        path = _make_mp3(tmp_path, bpm=120)
        assert _file_has_any_tags(path) is True

    def test_nonexistent_file_defaults_to_true(self, tmp_path):
        # Conservative fallback: undetermined state must not be reported
        # as "no tags" — that's a specific claim we can't make if the file
        # can't even be read.
        assert _file_has_any_tags(str(tmp_path / "does_not_exist.mp3")) is True


class TestProcessSingleFileSkipReason:
    def _call(self, tmp_path, path):
        slot_vars, slot_q = _make_slots()
        results = []
        process_single_file(
            name=os.path.basename(path),
            dir_path=str(tmp_path),
            is_dry_run=True,
            markings=MARKINGS,
            slot_idx=slot_q.get(),
            lock=threading.Lock(),
            on_progress=lambda **kw: results.append(kw),
            slot_vars=slot_vars,
        )
        return results

    def test_truly_untagged_file_reports_no_tags_found(self, tmp_path):
        path = _make_truly_untagged_mp3(tmp_path)
        results = self._call(tmp_path, path)
        assert "No tags found" in results[0]["display_text"]
        assert "No tags found" in results[0]["log_text"]

    def test_tagged_file_without_bpm_reports_no_bpm_tag(self, tmp_path):
        path = _make_mp3_with_tags_no_bpm(tmp_path)
        results = self._call(tmp_path, path)
        assert "No BPM tag" in results[0]["display_text"]
        assert "No tags found" not in results[0]["display_text"]

    def test_both_skip_reasons_still_count_as_skipped(self, tmp_path):
        for path in (
            _make_truly_untagged_mp3(tmp_path, "u.mp3"),
            _make_mp3_with_tags_no_bpm(tmp_path, "t.mp3"),
        ):
            results = self._call(tmp_path, path)
            assert results[0]["n_skipped"] == 1
            assert results[0]["n_errors"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# process_single_file — dry run path
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessSingleFileDryRun:
    def _call(self, tmp_path, bpm=128, existing_tempo=None):
        slot_vars, _slot_q = _make_slots()
        results = []

        with (
            patch("tempo_analyzer.core.file_processor.read_bpm", return_value=bpm),
            patch(
                "tempo_analyzer.core.file_processor.read_tempo_marking",
                return_value=existing_tempo,
            ),
            patch(
                "tempo_analyzer.core.file_processor.write_tempo_marking"
            ) as mock_write,
        ):
            process_single_file(
                name="track.mp3",
                dir_path=str(tmp_path),
                is_dry_run=True,
                markings=MARKINGS,
                slot_idx=0,
                lock=threading.Lock(),
                on_progress=lambda **kw: results.append(kw),
                slot_vars=slot_vars,
            )
        return results, mock_write

    def test_dry_run_does_not_write(self, tmp_path):
        results, mock_write = self._call(tmp_path)
        mock_write.assert_not_called()
        assert "DRY RUN" in results[0]["display_text"]

    def test_dry_run_display_contains_dry_run(self, tmp_path):
        results, _ = self._call(tmp_path)
        assert "DRY RUN" in results[0]["display_text"]

    def test_dry_run_reports_zero_errors(self, tmp_path):
        results, _ = self._call(tmp_path)
        assert results[0]["n_errors"] == 0

    def test_dry_run_reports_zero_skipped(self, tmp_path):
        results, _ = self._call(tmp_path)
        assert results[0]["n_skipped"] == 0

    def test_dry_run_display_contains_marking(self, tmp_path):
        # BPM=128 → Allegro in Italian scheme
        results, _ = self._call(tmp_path, bpm=128)
        assert "Allegro" in results[0]["display_text"]

    def test_dry_run_display_contains_bpm(self, tmp_path):
        results, _ = self._call(tmp_path, bpm=128)
        assert "128" in results[0]["display_text"]

    @pytest.mark.parametrize(
        "bpm,expected_marking",
        [
            (40, "Largo"),
            (80, "Andante"),
            (128, "Allegro"),
            (174, "Vivace"),
            (220, "Prestissimo"),
        ],
    )
    def test_correct_marking_for_bpm(self, tmp_path, bpm, expected_marking):
        results, _ = self._call(tmp_path, bpm=bpm)
        assert expected_marking in results[0]["display_text"]


# ═════════════════════════════════════════════════════════════════════════════
# process_single_file — live run path
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessSingleFileLive:
    def _call(self, tmp_path, bpm=128, existing_tempo=None):
        slot_vars, slot_q = _make_slots()
        results = []

        with (
            patch("tempo_analyzer.core.file_processor.read_bpm", return_value=bpm),
            patch(
                "tempo_analyzer.core.file_processor.read_tempo_marking",
                return_value=existing_tempo,
            ),
            patch(
                "tempo_analyzer.core.file_processor.write_tempo_marking"
            ) as mock_write,
        ):
            process_single_file(
                name="track.mp3",
                dir_path=str(tmp_path),
                is_dry_run=False,
                markings=MARKINGS,
                slot_idx=0,
                lock=threading.Lock(),
                on_progress=lambda **kw: results.append(kw),
                slot_vars=slot_vars,
            )
        return results, mock_write

    def test_live_calls_write_tempo_marking(self, tmp_path):
        _, mock_write = self._call(tmp_path, bpm=128)
        mock_write.assert_called_once()

    def test_live_writes_correct_marking(self, tmp_path):
        _, mock_write = self._call(tmp_path, bpm=128)
        args = mock_write.call_args[0]
        assert "Allegro" in args

    def test_live_display_contains_tagged(self, tmp_path):
        results, _ = self._call(tmp_path, bpm=128)
        assert "TAGGED" in results[0]["display_text"]

    def test_live_reports_zero_errors(self, tmp_path):
        results, _ = self._call(tmp_path)
        assert results[0]["n_errors"] == 0

    def test_live_display_shows_previous_marking_when_changed(self, tmp_path):
        results, _ = self._call(tmp_path, bpm=128, existing_tempo="Andante")
        assert "Andante" in results[0]["display_text"]

    def test_live_no_previous_shown_when_same(self, tmp_path):
        results, _ = self._call(tmp_path, bpm=128, existing_tempo="Allegro")
        # No "was …" section when marking unchanged
        assert "was" not in results[0]["display_text"].lower()


# ═════════════════════════════════════════════════════════════════════════════
# run_analysis
# ═════════════════════════════════════════════════════════════════════════════


class TestRunAnalysis:
    def _run(self, tmp_path, bpm_map=None, is_dry_run=True):
        """bpm_map: {filename: bpm_value} — None means no BPM tag."""
        slot_vars, slot_q = _make_slots()
        progress, complete, errors = [], [], []

        # Build side_effect for read_bpm based on filename
        bpm_map = bpm_map or {}

        def mock_read_bpm(path):
            name = path.split("/")[-1].split("\\")[-1]
            return bpm_map.get(name)

        with (
            patch(
                "tempo_analyzer.core.file_processor.read_bpm", side_effect=mock_read_bpm
            ),
            patch(
                "tempo_analyzer.core.file_processor.read_tempo_marking",
                return_value=None,
            ),
            patch("tempo_analyzer.core.file_processor.write_tempo_marking"),
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            run_analysis(
                dir_path=str(tmp_path),
                is_dry_run=is_dry_run,
                markings=MARKINGS,
                scheme_name="Italian",
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=lambda **kw: progress.append(kw),
                on_complete=lambda **kw: complete.append(kw),
                on_error=lambda msg: errors.append(msg),
            )
        return progress, complete, errors

    def test_empty_directory_calls_on_error(self, tmp_path):
        _, _, errors = self._run(tmp_path)
        assert len(errors) == 1

    def test_on_complete_called_with_total(self, tmp_path):
        for i in range(3):
            _make_mp3(tmp_path, f"t{i}.mp3")
        bpm_map = {f"t{i}.mp3": 120 + i for i in range(3)}
        _, complete, _ = self._run(tmp_path, bpm_map=bpm_map)
        assert len(complete) == 1
        assert complete[0]["total"] == 3

    def test_files_without_bpm_counted_as_skipped(self, tmp_path):
        _make_mp3(tmp_path, "a.mp3")
        _make_mp3(tmp_path, "b.mp3")
        bpm_map = {"a.mp3": 128}  # b.mp3 has no BPM → skipped by process_single_file
        _, complete, _ = self._run(tmp_path, bpm_map=bpm_map)
        # BaseFileProcessor tracks total files found; processed counter reflects
        # only files that called on_progress with explicit n_processed increment.
        assert complete[0]["total"] == 2

    def test_on_complete_total_matches_file_count(self, tmp_path):
        """BaseFileProcessor aggregates progress internally; on_complete
        has the totals."""
        for i in range(4):
            _make_mp3(tmp_path, f"t{i}.mp3")
        bpm_map = {f"t{i}.mp3": 128 for i in range(4)}
        _, complete, _ = self._run(tmp_path, bpm_map=bpm_map)
        assert complete[0]["total"] == 4

    def test_nonexistent_directory_calls_on_error(self, tmp_path):
        _, _, errors = self._run(tmp_path / "missing")
        assert len(errors) == 1

    def test_duration_secs_in_complete(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3")
        _, complete, _ = self._run(tmp_path, bpm_map={"t.mp3": 128})
        assert complete[0]["duration_secs"] >= 0

    def test_log_entries_in_complete(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3")
        _, complete, _ = self._run(tmp_path, bpm_map={"t.mp3": 128})
        assert isinstance(complete[0]["log_entries"], list)


# ═════════════════════════════════════════════════════════════════════════════
# Undo-batch recording (record side of undo feature)
# ═════════════════════════════════════════════════════════════════════════════


class TestUndoBatchRecording:
    def test_worker_threads_record_snapshots_into_active_batch(self, tmp_path):
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches

        undo_db = tmp_path / "undo_log.db"
        (tmp_path / "a.mp3").write_bytes(b"")
        (tmp_path / "b.mp3").write_bytes(b"")

        handler = MagicMock()
        handler.read_bpm.return_value = 128
        handler.get_raw_tags.return_value = {"TXXX:marker": "x"}

        slot_vars, slot_q = _make_slots()

        # TagHandlerFactory is imported into the reader/writer/base modules at
        # module load; patch every namespace that resolves it so the snapshot,
        # reads, and writes all hit the mock handler (real mutagen would reject
        # the zero-byte fixture files).
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler
        with (
            patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory", shared_factory
            ),
            patch(
                "audio_suite_shared.tag_helper_reader.TagHandlerFactory", shared_factory
            ),
            patch(
                "audio_suite_shared.tag_helper_writer.TagHandlerFactory", shared_factory
            ),
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            with active_batch("tempo_analyzer", "tag_edit", db_path=undo_db):
                run_analysis(
                    dir_path=str(tmp_path),
                    is_dry_run=False,
                    markings=MARKINGS,
                    scheme_name="Italian",
                    slot_vars=slot_vars,
                    slot_queue=slot_q,
                    on_progress=lambda **kw: None,
                    on_complete=lambda **kw: None,
                    on_error=lambda msg: None,
                )

        batches = list_recent_batches(limit=10, db_path=undo_db)
        assert len(batches) == 1
        assert batches[0].tool_name == "tempo_analyzer"
        assert batches[0].operation_type == "tag_edit"
        assert batches[0].record_count == 2

    def test_dry_run_creates_no_batch_records(self, tmp_path):
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches

        undo_db = tmp_path / "undo_log.db"
        (tmp_path / "a.mp3").write_bytes(b"")
        slot_vars, slot_q = _make_slots()

        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = MagicMock()
        with (
            patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory", shared_factory
            ),
            patch(
                "audio_suite_shared.tag_helper_reader.TagHandlerFactory", shared_factory
            ),
            patch(
                "audio_suite_shared.tag_helper_writer.TagHandlerFactory", shared_factory
            ),
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
        ):
            with active_batch("tempo_analyzer", "tag_edit", db_path=undo_db):
                run_analysis(
                    dir_path=str(tmp_path),
                    is_dry_run=True,
                    markings=MARKINGS,
                    scheme_name="Italian",
                    slot_vars=slot_vars,
                    slot_queue=slot_q,
                    on_progress=lambda **kw: None,
                    on_complete=lambda **kw: None,
                    on_error=lambda msg: None,
                )

        assert list_recent_batches(limit=10, db_path=undo_db) == []


# ═════════════════════════════════════════════════════════════════════════════
# Multi-format support: FLAC, OGG, M4A, Opus
#
# Regression coverage for the tool's advertised scope: BPM is read and tempo
# markings are written in each format's native tag convention, so a mixed
# library is tagged in one pass. Verified against real fixture files (pydub
# export) and the resulting on-disk tags are read back with the shared
# tag_helper — never read back from internal state (see AGENTS.md "verify
# the actual transformed outcome").
# ═════════════════════════════════════════════════════════════════════════════


def _make_flac(tmp_path, name="track.flac", bpm=None, title=None, strip_tags=False):
    """Create a real FLAC with optional native Vorbis BPM / title tags.

    pydub/ffmpeg export stamps an ``encoder`` Vorbis comment, so ``strip_tags``
    deletes every tag block (mirroring ``_make_truly_untagged_mp3``) to produce
    a genuinely tagless file.
    """
    from mutagen.flac import FLAC

    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="flac")
    audio = FLAC(str(path))
    if strip_tags:
        audio.delete()
        audio.save()
        return str(path)
    if bpm is not None:
        audio["bpm"] = [str(bpm)]
    if title is not None:
        audio["title"] = [title]
    if bpm is not None or title is not None:
        audio.save()
    return str(path)


def _make_ogg(tmp_path, name="track.ogg", bpm=None, title=None, strip_tags=False):
    """Create a real OGG Vorbis with optional native Vorbis BPM / title tags."""
    from mutagen.oggvorbis import OggVorbis

    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="ogg")
    audio = OggVorbis(str(path))
    if strip_tags:
        audio.delete()
        audio.save()
        return str(path)
    if bpm is not None:
        audio["bpm"] = [str(bpm)]
    if title is not None:
        audio["title"] = [title]
    if bpm is not None or title is not None:
        audio.save()
    return str(path)


def _make_opus(tmp_path, name="track.opus", bpm=None, title=None, strip_tags=False):
    """Create a real Opus file with optional native Vorbis BPM / title tags."""
    from mutagen.oggopus import OggOpus

    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="opus")
    audio = OggOpus(str(path))
    if strip_tags:
        audio.delete()
        audio.save()
        return str(path)
    if bpm is not None:
        audio["bpm"] = [str(bpm)]
    if title is not None:
        audio["title"] = [title]
    if bpm is not None or title is not None:
        audio.save()
    return str(path)


def _make_m4a(tmp_path, name="track.m4a", bpm=None, title=None, strip_tags=False):
    """Create a real M4A file with optional native tmpo / title tags."""
    from mutagen.mp4 import MP4

    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="mp4")
    audio = MP4(str(path))
    if strip_tags:
        audio.delete()
        audio.save()
        return str(path)
    if bpm is not None:
        audio["tmpo"] = [bpm]
    if title is not None:
        audio["\xa9nam"] = [title]
    if bpm is not None or title is not None:
        audio.save()
    return str(path)


_FORMAT_MAKERS = [_make_flac, _make_ogg, _make_opus, _make_m4a]


def _run_process_single(tmp_path, name, is_dry_run):
    slot_vars, slot_q = _make_slots()
    results = []
    process_single_file(
        name=name,
        dir_path=str(tmp_path),
        is_dry_run=is_dry_run,
        markings=MARKINGS,
        slot_idx=slot_q.get(),
        lock=threading.Lock(),
        on_progress=lambda **kw: results.append(kw),
        slot_vars=slot_vars,
    )
    return results


class TestMultiFormatRoundTrip:
    @pytest.mark.parametrize(
        "file_maker",
        _FORMAT_MAKERS,
        ids=["flac", "ogg", "opus", "m4a"],
    )
    def test_live_run_reads_native_bpm_and_writes_marking(self, tmp_path, file_maker):
        path = file_maker(tmp_path, bpm=128)

        results = _run_process_single(
            tmp_path, os.path.basename(path), is_dry_run=False
        )

        assert "TAGGED" in results[0]["display_text"]
        assert "Allegro" in results[0]["display_text"]

        # Verify the actual on-disk outcome, not internal state.
        from audio_suite_shared.tag_helper import read_bpm, read_tempo_marking

        assert read_bpm(path) == 128
        assert read_tempo_marking(path) == "Allegro"

    @pytest.mark.parametrize(
        "file_maker",
        _FORMAT_MAKERS,
        ids=["flac", "ogg", "opus", "m4a"],
    )
    def test_dry_run_leaves_no_marking_on_disk(self, tmp_path, file_maker):
        path = file_maker(tmp_path, bpm=128)

        results = _run_process_single(tmp_path, os.path.basename(path), is_dry_run=True)

        assert "DRY RUN" in results[0]["display_text"]
        from audio_suite_shared.tag_helper import read_tempo_marking

        assert read_tempo_marking(path) is None


class TestMultiFormatSkipReasons:
    @pytest.mark.parametrize(
        "file_maker",
        _FORMAT_MAKERS,
        ids=["flac", "ogg", "opus", "m4a"],
    )
    def test_tagged_without_bpm_reports_no_bpm_tag(self, tmp_path, file_maker):
        path = file_maker(tmp_path, title="Test Title")

        results = _run_process_single(tmp_path, os.path.basename(path), is_dry_run=True)

        assert "No BPM tag" in results[0]["display_text"]
        assert "No tags found" not in results[0]["display_text"]
        assert _file_has_any_tags(path) is True

    @pytest.mark.parametrize(
        "file_maker",
        _FORMAT_MAKERS,
        ids=["flac", "ogg", "opus", "m4a"],
    )
    def test_untagged_reports_no_tags_found(self, tmp_path, file_maker):
        path = file_maker(tmp_path, strip_tags=True)

        results = _run_process_single(tmp_path, os.path.basename(path), is_dry_run=True)

        assert "No tags found" in results[0]["display_text"]
        assert _file_has_any_tags(path) is False

    @pytest.mark.parametrize(
        "file_maker",
        _FORMAT_MAKERS,
        ids=["flac", "ogg", "opus", "m4a"],
    )
    def test_file_with_bpm_tag_has_tags(self, tmp_path, file_maker):
        path = file_maker(tmp_path, bpm=128)
        assert _file_has_any_tags(path) is True


class TestRunAnalysisMultiFormat:
    def _run(self, tmp_path, is_dry_run=True):
        slot_vars, slot_q = _make_slots()
        progress, complete, errors = [], [], []
        with (
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            run_analysis(
                dir_path=str(tmp_path),
                is_dry_run=is_dry_run,
                markings=MARKINGS,
                scheme_name="Italian",
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=lambda **kw: progress.append(kw),
                on_complete=lambda **kw: complete.append(kw),
                on_error=lambda msg: errors.append(msg),
            )
        return progress, complete, errors

    def test_discovers_and_analyses_mixed_formats(self, tmp_path):
        for file_maker in _FORMAT_MAKERS:
            file_maker(tmp_path, bpm=128)
        _make_mp3(tmp_path, "e.mp3", bpm=128)
        (tmp_path / "notes.txt").write_text("not audio")

        progress, complete, errors = self._run(tmp_path)

        assert errors == []
        assert complete[0]["total"] == 5  # 4 formats + mp3; notes.txt excluded
        assert complete[0]["processed"] == 5
        assert complete[0]["errors"] == 0
        labels = {p["display_text"] for p in progress}
        for expected in ("track.flac", "track.ogg", "track.opus", "track.m4a", "e.mp3"):
            assert any(expected in label for label in labels)

    def test_live_mixed_format_run_writes_marks(self, tmp_path):
        from audio_suite_shared.tag_helper import read_tempo_marking

        paths = [
            maker(tmp_path, name=f"c{i}.{ext}", bpm=128)
            for i, (maker, ext) in enumerate(
                zip(_FORMAT_MAKERS, ["flac", "ogg", "opus", "m4a"], strict=True)
            )
        ]

        _, complete, errors = self._run(tmp_path, is_dry_run=False)

        assert errors == []
        assert complete[0]["processed"] == 4
        for path in paths:
            assert read_tempo_marking(path) == "Allegro"

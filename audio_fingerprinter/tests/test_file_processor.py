"""Tests for audio_fingerprinter.core.file_processor."""

from __future__ import annotations

import threading
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from audio_fingerprinter.core.file_processor import (
    FingerprintProcessor,
    _fingerprint_worker,
    _FingerprintJob,
    _process_file,
    _result_display,
    _summarise_results,
    run_fingerprinting,
)
from audio_fingerprinter.core.models import (
    AcoustidRecording,
    FingerprintFileResult,
    FingerprintParams,
)
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS


def _make_job(**overrides: Any) -> MagicMock:
    """Create a mock _FingerprintJob with sane defaults."""
    job = MagicMock()
    job.fpcalc_path = "/usr/bin/fpcalc"
    job.params = FingerprintParams()
    job.api_key = "key"
    job.client = MagicMock()
    job.undo_batch = None
    for k, v in overrides.items():
        setattr(job, k, v)
    return job


def _make_recording(**kwargs: Any) -> AcoustidRecording:
    defaults = dict(
        acoustid_id="a1",
        recording_id="r1",
        title="Song",
        artist="Artist",
        score=0.9,
        duration=200,
    )
    defaults.update(kwargs)
    return AcoustidRecording(**defaults)


class TestProcessFile:
    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    def test_generate_failure_raises(self, mock_fp):
        mock_fp.side_effect = OSError("fpcalc missing")
        job = _make_job()
        with pytest.raises(OSError, match="fpcalc missing"):
            _process_file(job, "/path/track.mp3")

    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    def test_no_lookup_enabled(self, mock_fp):
        mock_fp.return_value = MagicMock(duration=60.0, fingerprint="ABC")
        params = FingerprintParams(lookup_enabled=False, is_dry_run=True)
        job = _make_job(params=params)
        result = _process_file(job, "/path/track.mp3")
        assert result.status == "LOOKUP SKIPPED"

    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    def test_no_client_returns_skipped(self, mock_fp):
        mock_fp.return_value = MagicMock(duration=60.0, fingerprint="ABC")
        job = _make_job(client=None, params=FingerprintParams(lookup_enabled=True))
        result = _process_file(job, "/path/track.mp3")
        assert result.status == "LOOKUP SKIPPED"

    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    def test_lookup_error(self, mock_fp):
        mock_fp.return_value = MagicMock(duration=60.0, fingerprint="ABC")
        mock_lookup = MagicMock(status="error", error="bad key")
        job = _make_job()
        job.client.lookup.return_value = mock_lookup
        result = _process_file(job, "/path/track.mp3")
        assert result.status == "ERROR"
        assert "bad key" in result.message

    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    def test_no_match(self, mock_fp):
        mock_fp.return_value = MagicMock(duration=60.0, fingerprint="ABC")
        mock_lookup = MagicMock(status="no results", recordings=(), best_match=None)
        job = _make_job()
        job.client.lookup.return_value = mock_lookup
        result = _process_file(job, "/path/track.mp3")
        assert result.status == "NO MATCH"

    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    def test_match_dry_run_no_tag_write(self, mock_fp):
        mock_fp.return_value = MagicMock(duration=60.0, fingerprint="ABC")
        rec = _make_recording()
        mock_lookup = MagicMock(status="ok", recordings=(rec,), best_match=rec)
        job = _make_job(
            params=FingerprintParams(
                lookup_enabled=True, write_tags=True, is_dry_run=True
            )
        )
        job.client.lookup.return_value = mock_lookup
        result = _process_file(job, "/path/track.mp3")
        assert result.status == "MATCHED"
        assert result.tag_written is False

    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    def test_match_live_writes_tags(self, mock_fp):
        mock_fp.return_value = MagicMock(duration=60.0, fingerprint="ABC")
        rec = _make_recording()
        mock_lookup = MagicMock(status="ok", recordings=(rec,), best_match=rec)
        job = _make_job(
            params=FingerprintParams(
                lookup_enabled=True, write_tags=True, is_dry_run=False
            )
        )
        job.client.lookup.return_value = mock_lookup
        with patch(
            "audio_fingerprinter.core.file_processor.write_acoustid_tags",
            return_value=(True, "OK"),
        ):
            result = _process_file(job, "/path/track.mp3")
        assert result.status == "TAGGED"
        assert result.tag_written is True

    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    def test_tag_write_failure(self, mock_fp):
        mock_fp.return_value = MagicMock(duration=60.0, fingerprint="ABC")
        rec = _make_recording()
        mock_lookup = MagicMock(status="ok", recordings=(rec,), best_match=rec)
        job = _make_job(
            params=FingerprintParams(
                lookup_enabled=True, write_tags=True, is_dry_run=False
            )
        )
        job.client.lookup.return_value = mock_lookup
        with patch(
            "audio_fingerprinter.core.file_processor.write_acoustid_tags",
            return_value=(False, "mutagen missing"),
        ):
            result = _process_file(job, "/path/track.mp3")
        assert result.status == "TAG WRITE FAILED"
        assert "mutagen" in result.message


class TestProcessFileTagTiebreak:
    """Near-tied AcoustID candidates are resolved using the file tags."""

    def _lookup(self, recordings):
        return MagicMock(status="ok", recordings=recordings, best_match=recordings[0])

    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    @patch("audio_fingerprinter.core.file_processor.read_artist_title")
    def test_prefers_tag_consistent_candidate(self, mock_tags, mock_fp):
        mock_fp.return_value = MagicMock(duration=218.0, fingerprint="ABC")
        mock_tags.return_value = ("10cc", "Johnny, Don't Do It")
        remix = _make_recording(
            acoustid_id="ac-remix",
            recording_id="mb-remix",
            title="Ich geh in Flammen auf",
            artist="Rosenstolz",
            score=0.984,
        )
        original = _make_recording(
            acoustid_id="ac-orig",
            recording_id="mb-orig",
            title="Johnny, Don't Do It",
            artist="10cc",
            score=0.947,
        )
        job = _make_job()
        job.client.lookup.return_value = self._lookup((remix, original))
        result = _process_file(job, "/path/track.mp3")
        assert result.status == "MATCHED"
        assert "Johnny, Don't Do It — 10cc" in result.message
        assert "matched file tags" in result.message
        assert "Rosenstolz" not in result.message
        assert result.acoustid_id == "ac-orig"

    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    @patch("audio_fingerprinter.core.file_processor.read_artist_title")
    def test_unresolved_ambiguity_flags_runner_up(self, mock_tags, mock_fp):
        mock_fp.return_value = MagicMock(duration=218.0, fingerprint="ABC")
        mock_tags.return_value = ("Unknown", "Unknown")
        top = _make_recording(
            acoustid_id="ac-top",
            recording_id="mb-top",
            title="Song A",
            score=0.98,
        )
        runner_up = _make_recording(
            acoustid_id="ac-run",
            recording_id="mb-run",
            title="Song B",
            score=0.96,
        )
        job = _make_job()
        job.client.lookup.return_value = self._lookup((top, runner_up))
        result = _process_file(job, "/path/track.mp3")
        assert result.status == "MATCHED"
        assert result.acoustid_id == "ac-top"
        assert "ambiguous — also Song B" in result.message
        assert "matched file tags" not in result.message

    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    @patch("audio_fingerprinter.core.file_processor.read_artist_title")
    def test_clearly_dominant_candidate_not_annotated(self, mock_tags, mock_fp):
        mock_fp.return_value = MagicMock(duration=60.0, fingerprint="ABC")
        mock_tags.return_value = ("10cc", "Dominant")
        top = _make_recording(
            recording_id="mb-top", title="Dominant", artist="10cc", score=0.98
        )
        runner_up = _make_recording(recording_id="mb-run", title="Other", score=0.55)
        job = _make_job()
        job.client.lookup.return_value = self._lookup((top, runner_up))
        result = _process_file(job, "/path/track.mp3")
        assert result.status == "MATCHED"
        assert result.message == "Dominant — 10cc (score 0.98)"
        assert "ambiguous" not in result.message


class TestSummariseResults:
    def test_empty(self):
        counts = _summarise_results([])
        assert counts["identified"] == 0
        assert counts["errors"] == 0

    def test_counts_statuses(self):
        results = [
            FingerprintFileResult(file_path="a", filename="a.mp3", status="TAGGED"),
            FingerprintFileResult(file_path="b", filename="b.mp3", status="MATCHED"),
            FingerprintFileResult(file_path="c", filename="c.mp3", status="NO MATCH"),
            FingerprintFileResult(file_path="d", filename="d.mp3", status="ERROR"),
            FingerprintFileResult(
                file_path="e", filename="e.mp3", status="LOOKUP SKIPPED"
            ),
            FingerprintFileResult(
                file_path="f", filename="f.mp3", status="TAG WRITE FAILED"
            ),
        ]
        counts = _summarise_results(results)
        assert counts["identified"] == 2
        assert counts["tagged"] == 1
        assert counts["no_match"] == 1
        assert counts["lookup_skipped"] == 1
        assert counts["errors"] == 2


class TestFingerprintProcessor:
    def test_inherits_base(self):
        from audio_suite_shared.file_processor_base import BaseFileProcessor

        proc = FingerprintProcessor()
        assert isinstance(proc, BaseFileProcessor)

    def test_operation_type(self):
        proc = FingerprintProcessor()
        assert proc.operation_type == "fingerprint"

    def test_worker_count_matches_suite_default(self):
        proc = FingerprintProcessor()
        assert proc.max_workers == DEFAULT_MAX_WORKERS


class TestResultDisplay:
    def test_error_line(self):
        result = FingerprintFileResult(
            file_path="x", filename="a.mp3", status="ERROR", message="boom"
        )
        assert _result_display(result) == "[ERROR] a.mp3: boom"

    def test_match_line_includes_message(self):
        result = FingerprintFileResult(
            file_path="x",
            filename="a.mp3",
            status="MATCHED",
            message="Song — Artist (score 0.90)",
        )
        assert _result_display(result) == "[MATCHED] a.mp3 — Song — Artist (score 0.90)"

    def test_plain_status_line(self):
        result = FingerprintFileResult(
            file_path="x", filename="a.mp3", status="NO MATCH"
        )
        assert _result_display(result) == "[NO MATCH] a.mp3"


class TestFingerprintWorker:
    def test_reports_display_text_and_releases_slot(self, tmp_path):
        target = tmp_path / "track.mp3"
        target.write_bytes(b"\x00")
        slot_q: Queue[int] = Queue()
        slot_q.put(0)
        results: list[FingerprintFileResult] = []
        completed = FingerprintFileResult(
            file_path=str(target),
            filename="track.mp3",
            status="LOOKUP SKIPPED",
        )
        job = _FingerprintJob(
            filename="track.mp3",
            folder_path=str(tmp_path),
            fpcalc_path="fpcalc",
            params=FingerprintParams(lookup_enabled=False),
            client=None,
            api_key="",
            slot_idx=0,
            on_slot_update=None,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=MagicMock(),
            results=results,
            undo_batch=None,
            processor=MagicMock(),
        )
        with patch(
            "audio_fingerprinter.core.file_processor._process_file",
            return_value=completed,
        ):
            _fingerprint_worker(job)
        assert job.on_progress.call_count == 1
        job.on_progress.assert_called_once_with(
            n_errors=0, display_text="[LOOKUP SKIPPED] track.mp3"
        )
        assert results == [completed]
        assert slot_q.qsize() == 1


class TestRunFingerprinting:
    def test_streams_display_text_and_releases_slots(
        self,
        fake_audio_dir,
        patched_resolve_fpcalc,
        patched_generate_fingerprint,
    ):
        progress = MagicMock()
        complete = MagicMock()
        error = MagicMock()
        slot_q: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            slot_q.put(i)
        run_fingerprinting(
            dir_path=str(fake_audio_dir),
            api_key="",
            params=FingerprintParams(lookup_enabled=False),
            slot_vars=[MagicMock() for _ in range(DEFAULT_MAX_WORKERS)],
            slot_queue=slot_q,
            on_progress=progress,
            on_complete=complete,
            on_error=error,
        )
        error.assert_not_called()
        complete.assert_called_once()
        texts = [c.kwargs.get("display_text") for c in progress.call_args_list]
        assert any(t and t.startswith("[LOOKUP SKIPPED]") for t in texts)
        assert slot_q.qsize() == DEFAULT_MAX_WORKERS

    def test_error_flags_an_error_in_log_entries(
        self,
        fake_audio_dir,
        patched_resolve_fpcalc,
        patched_generate_fingerprint,
    ):
        progress = MagicMock()
        complete = MagicMock()
        error = MagicMock()
        slot_q: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            slot_q.put(i)
        with patch(
            "audio_fingerprinter.core.file_processor._process_file",
            side_effect=OSError("decode failed"),
        ):
            run_fingerprinting(
                dir_path=str(fake_audio_dir),
                api_key="",
                params=FingerprintParams(lookup_enabled=False),
                slot_vars=[MagicMock() for _ in range(DEFAULT_MAX_WORKERS)],
                slot_queue=slot_q,
                on_progress=progress,
                on_complete=complete,
                on_error=error,
            )
        error.assert_not_called()
        texts = [c.kwargs.get("display_text") for c in progress.call_args_list]
        assert any(t and t.startswith("[ERROR]") for t in texts)

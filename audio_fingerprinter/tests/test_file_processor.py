"""Tests for audio_fingerprinter.core.file_processor.

Changed in 1.2.0: adds the MusicBrainz enrichment / ISRC real-outcome tests
(Sprint 2 Item 2.1) and the ISRC submission tests, including the lock that a
dry run's previewed XML is byte-identical to the live POST body
(Sprint 2 Item 2.3).
Changed in 1.4.0: the tag tie-break and album-mode tests patch the single handler load.
"""

from __future__ import annotations

import ast
import inspect
import os
import threading
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from audio_fingerprinter.core import file_processor as file_processor_module
from audio_fingerprinter.core.file_processor import (
    FingerprintProcessor,
    _commit_match_tags,
    _fingerprint_worker,
    _FingerprintJob,
    _process_file,
    _result_display,
    _run_isrc_submission,
    _summarise_results,
    collect_isrc_submissions,
    run_fingerprinting,
)
from audio_fingerprinter.core.models import (
    AcoustidRecording,
    Fingerprint,
    FingerprintFileResult,
    FingerprintParams,
    FingerprintStatus,
    LookupResult,
    ReleaseGroup,
)
from audio_fingerprinter.core.musicbrainz_client import (
    ISRCSubmitResult,
    MBAuth,
    MusicBrainzClient,
)
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.tag_helper import TagHandlerFactory as _TagHandlerFactory


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
    @patch("audio_fingerprinter.core.file_processor.TagHandlerFactory.get_handler")
    def test_prefers_tag_consistent_candidate(self, mock_handler, mock_fp):
        mock_fp.return_value = MagicMock(duration=218.0, fingerprint="ABC")
        mock_handler.return_value.read_artist_title.return_value = (
            "10cc",
            "Johnny, Don't Do It",
        )
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
    @patch("audio_fingerprinter.core.file_processor.TagHandlerFactory.get_handler")
    def test_unresolved_ambiguity_flags_runner_up(self, mock_handler, mock_fp):
        mock_fp.return_value = MagicMock(duration=218.0, fingerprint="ABC")
        mock_handler.return_value.read_artist_title.return_value = (
            "Unknown",
            "Unknown",
        )
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
    @patch("audio_fingerprinter.core.file_processor.TagHandlerFactory.get_handler")
    def test_clearly_dominant_candidate_not_annotated(self, mock_handler, mock_fp):
        mock_fp.return_value = MagicMock(duration=60.0, fingerprint="ABC")
        mock_handler.return_value.read_artist_title.return_value = ("10cc", "Dominant")
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
        assert counts["album_ambiguous"] == 0

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
            FingerprintFileResult(
                file_path="g", filename="g.mp3", status="ALBUM AMBIGUOUS"
            ),
        ]
        counts = _summarise_results(results)
        assert counts["identified"] == 2
        assert counts["tagged"] == 1
        assert counts["no_match"] == 1
        assert counts["lookup_skipped"] == 1
        assert counts["errors"] == 2
        assert counts["album_ambiguous"] == 1


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

    def test_album_ambiguous_line_includes_message(self):
        result = FingerprintFileResult(
            file_path="x",
            filename="a.mp3",
            status="ALBUM AMBIGUOUS",
            message="album ambiguous — A vs B; left untagged",
        )
        assert (
            _result_display(result)
            == "[ALBUM AMBIGUOUS] a.mp3 — album ambiguous — A vs B; left untagged"
        )


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


_ALBUM = ReleaseGroup("rg-album", "The Album")
_OTHER = ReleaseGroup("rg-other", "Other Album")


def _rg_rec(
    recording_id: str,
    score: float,
    groups: tuple[ReleaseGroup, ...],
    title: str = "Song",
    artist: str = "Artist",
) -> AcoustidRecording:
    return AcoustidRecording(
        acoustid_id=f"ac-{recording_id}",
        recording_id=recording_id,
        title=title,
        artist=artist,
        score=score,
        duration=60,
        release_groups=groups,
    )


def _patch_fingerprint_by_name():
    """Patch generate_fingerprint to a distinct Fingerprint per file."""
    return patch(
        "audio_fingerprinter.core.file_processor.generate_fingerprint",
        side_effect=lambda path, **_kw: Fingerprint(
            duration=60.0, fingerprint=f"fp-{os.path.basename(path)}"
        ),
    )


#: Captured before any test patches the class, so the album mode tests can
#: still read a real file's tags through the single-load path.
_REAL_GET_HANDLER = _TagHandlerFactory.get_handler


def _album_tag_factory(path: str) -> MagicMock:
    """A handler whose artist/title are blank but whose album tags are real."""
    handler = MagicMock(name="TagHandler")
    handler.read_artist_title.return_value = ("Unknown", "Unknown")
    try:
        real = _REAL_GET_HANDLER(path)
        handler.read_artist_album.return_value = real.read_artist_album()
        handler.read_custom_field.side_effect = real.read_custom_field
    except Exception:
        handler.read_artist_album.return_value = ("Unknown", "Unknown")
        handler.read_custom_field.return_value = None
    return handler


def _mock_client(responses_by_fp: dict[str, LookupResult]) -> MagicMock:
    """A client stub whose lookup_many answers by fingerprint string."""
    client = MagicMock(name="AcoustidClient")

    def _lookup_many(fps, on_progress=None):
        results = [responses_by_fp[fp.fingerprint] for fp in fps]
        if on_progress is not None:
            on_progress(len(fps), len(fps))
        return results

    client.lookup_many.side_effect = _lookup_many
    return client


def _run_album(
    folder,
    client: MagicMock,
    params: FingerprintParams,
    progress: MagicMock,
    complete: MagicMock,
    error: MagicMock,
):
    from contextlib import ExitStack

    slot_q: Queue[int] = Queue()
    for i in range(DEFAULT_MAX_WORKERS):
        slot_q.put(i)
    with ExitStack() as stack:
        for entered in [
            _patch_fingerprint_by_name(),
            patch(
                "audio_fingerprinter.core.file_processor.resolve_fpcalc",
                return_value="fpcalc",
            ),
            patch(
                "audio_fingerprinter.core.file_processor.TagHandlerFactory.get_handler",
                side_effect=_album_tag_factory,
            ),
        ] + [
            patch(
                "audio_fingerprinter.core.file_processor.AcoustidClient",
                return_value=client,
            ),
        ]:
            stack.enter_context(entered)
        run_fingerprinting(
            dir_path=str(folder),
            api_key="key",
            params=params,
            slot_vars=[MagicMock() for _ in range(DEFAULT_MAX_WORKERS)],
            slot_queue=slot_q,
            on_progress=progress,
            on_complete=complete,
            on_error=error,
        )


class TestProcessFileAlbumMode:
    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    def test_album_mode_defers_lookup_to_cluster_phase(self, mock_fp):
        mock_fp.return_value = MagicMock(duration=60.0, fingerprint="ABC")
        job = _make_job(params=FingerprintParams(album_mode=True))
        result = _process_file(job, "/path/track.mp3")
        assert result.status == "ANALYSED"
        assert "album matching" in result.message
        job.client.lookup.assert_not_called()

    @patch("audio_fingerprinter.core.file_processor.generate_fingerprint")
    def test_album_mode_without_key_still_skips_lookup(self, mock_fp):
        mock_fp.return_value = MagicMock(duration=60.0, fingerprint="ABC")
        job = _make_job(params=FingerprintParams(album_mode=True))
        job.api_key = ""
        result = _process_file(job, "/path/track.mp3")
        assert result.status == "LOOKUP SKIPPED"


class TestRunFingerprintingAlbumMode:
    """Album mode: fingerprint in workers, cluster after the batch."""

    def _album_dir(self, tmp_path, names):
        folder = tmp_path / "album"
        folder.mkdir()
        for name in names:
            (folder / name).write_bytes(b"\x00" * 100)
        return folder

    def _decided_responses(self) -> dict[str, LookupResult]:
        """Three album votes plus one remix-topped file the cluster
        pulls back to the album release group."""
        responses = {
            f"fp-{name}.mp3": LookupResult(
                status="ok",
                recordings=(_rg_rec(f"mb-{name}", 0.93, (_ALBUM,)),),
            )
            for name in ("a", "b", "c")
        }
        responses["fp-d.mp3"] = LookupResult(
            status="ok",
            recordings=(
                _rg_rec("mb-remix", 0.984, (_OTHER,), title="Remix"),
                _rg_rec(
                    "mb-orig",
                    0.947,
                    (_ALBUM,),
                    title="Original",
                    artist="10cc",
                ),
            ),
        )
        return responses

    def test_decided_cluster_dry_run_reports_and_defers_writes(self, tmp_path):
        folder = self._album_dir(tmp_path, ["a.mp3", "b.mp3", "c.mp3", "d.mp3"])
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        params = FingerprintParams(album_mode=True, write_tags=True, is_dry_run=True)
        with patch(
            "audio_fingerprinter.core.file_processor.write_acoustid_tags"
        ) as mock_write:
            _run_album(
                folder,
                _mock_client(self._decided_responses()),
                params,
                progress,
                complete,
                error,
            )
            mock_write.assert_not_called()

        error.assert_not_called()
        complete.assert_called_once()
        kwargs = complete.call_args.kwargs
        results = {os.path.basename(r.file_path): r for r in kwargs["results"]}
        assert set(results) == {"a.mp3", "b.mp3", "c.mp3", "d.mp3"}
        for name in ("a.mp3", "b.mp3", "c.mp3"):
            assert results[name].status == "MATCHED"
            assert results[name].tag_written is False
        # The remix-topped file is pulled to the album's candidate.
        pulled = results["d.mp3"]
        assert pulled.status == "MATCHED"
        assert pulled.acoustid_id == "ac-mb-orig"
        assert "album consensus The Album" in pulled.message
        assert "Remix" not in pulled.message
        # The per-album report line is present.
        assert any(
            line.startswith("[ALBUM]") and "decided — The Album" in line
            for line in kwargs["log_entries"]
        )
        assert kwargs["counts"]["identified"] == 4
        assert kwargs["counts"]["album_ambiguous"] == 0

    def test_ambiguous_album_leaves_files_untagged_with_runner_up(self, tmp_path):
        folder = self._album_dir(
            tmp_path, ["a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3", "f.mp3"]
        )
        responses = {
            f"fp-{name}.mp3": LookupResult(
                status="ok",
                recordings=(
                    _rg_rec(f"mb-{name}", 0.90, (_ALBUM if i < 3 else _OTHER,)),
                ),
            )
            for i, name in enumerate("abcdef")
        }
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        params = FingerprintParams(album_mode=True, write_tags=True, is_dry_run=False)
        with patch(
            "audio_fingerprinter.core.file_processor.write_acoustid_tags"
        ) as mock_write:
            _run_album(
                folder, _mock_client(responses), params, progress, complete, error
            )
            mock_write.assert_not_called()

        error.assert_not_called()
        kwargs = complete.call_args.kwargs
        assert all(r.status == "ALBUM AMBIGUOUS" for r in kwargs["results"])
        for result in kwargs["results"]:
            assert "album ambiguous — The Album vs Other Album" in result.message
            assert result.tag_written is False
        assert kwargs["counts"]["album_ambiguous"] == 6
        assert any(
            "ambiguous" in line and "left untagged" in line
            for line in kwargs["log_entries"]
            if line.startswith("[ALBUM]")
        )

    def test_below_minimum_falls_back_to_per_file_matching(self, tmp_path):
        folder = self._album_dir(tmp_path, ["a.mp3", "b.mp3"])
        responses = {
            f"fp-{name}.mp3": LookupResult(
                status="ok",
                recordings=(_rg_rec(f"mb-{name}", 0.9, (_ALBUM,)),),
            )
            for name in "ab"
        }
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        _run_album(
            folder,
            _mock_client(responses),
            FingerprintParams(album_mode=True, album_min=3),
            progress,
            complete,
            error,
        )
        error.assert_not_called()
        kwargs = complete.call_args.kwargs
        assert len(kwargs["results"]) == 2
        for result in kwargs["results"]:
            assert result.status == "MATCHED"
            assert "album consensus" not in result.message
            assert "(score 0.90)" in result.message
        assert any(
            "3-file minimum" in line
            for line in kwargs["log_entries"]
            if line.startswith("[ALBUM]")
        )

    def test_per_file_lookup_error_counts_as_error(self, tmp_path):
        folder = self._album_dir(tmp_path, ["a.mp3", "b.mp3", "c.mp3"])
        responses = {
            f"fp-{name}.mp3": LookupResult(
                status="ok",
                recordings=(_rg_rec(f"mb-{name}", 0.9, (_ALBUM,)),),
            )
            for name in "abc"
        }
        responses["fp-b.mp3"] = LookupResult(
            status="error", error="AcoustID returned HTTP 500."
        )
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        _run_album(
            folder,
            _mock_client(responses),
            FingerprintParams(album_mode=True),
            progress,
            complete,
            error,
        )
        error.assert_not_called()
        kwargs = complete.call_args.kwargs
        by_name = {os.path.basename(r.file_path): r for r in kwargs["results"]}
        assert by_name["b.mp3"].status == "ERROR"
        assert "HTTP 500" in by_name["b.mp3"].message
        # The other two files still form a below-minimum fallback... they
        # are only 2 votes, so both fall back to per-file matching.
        assert by_name["a.mp3"].status == "MATCHED"
        assert kwargs["errors"] == 1

    def test_auth_failure_aborts_run_with_on_error(self, tmp_path):
        folder = self._album_dir(tmp_path, ["a.mp3", "b.mp3"])
        client = MagicMock(name="AcoustidClient")
        from audio_fingerprinter.core.exceptions import AcoustidAuthError

        client.lookup_many.side_effect = AcoustidAuthError(
            "AcoustID rejected the application API key (HTTP 401)."
        )
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        _run_album(
            folder,
            client,
            FingerprintParams(album_mode=True),
            progress,
            complete,
            error,
        )
        error.assert_called_once()
        complete.assert_not_called()


class TestAlbumModeRealOutcome:
    """Decode-and-measure: real MP3 files, real tag writes, tags read
    back with mutagen — the decided cluster must actually write the
    cluster-chosen Acoustid Id per file, and a Dry Run must not."""

    @staticmethod
    def _make_album(tmp_path, names):
        from pydub import AudioSegment

        folder = tmp_path / "album"
        folder.mkdir()
        for name in names:
            AudioSegment.silent(duration=300).export(str(folder / name), format="mp3")
        return folder

    @staticmethod
    def _acoustid_tags(path) -> dict[str, str]:
        import mutagen

        audio = mutagen.File(str(path))
        assert audio is not None and audio.tags is not None
        return {str(tag.desc): str(tag) for tag in audio.tags.getall("TXXX")}

    def _responses(self, names) -> dict[str, LookupResult]:
        return {
            f"fp-{name}": LookupResult(
                status="ok",
                recordings=(_rg_rec(f"mb-{name}", 0.93, (_ALBUM,)),),
            )
            for name in names
        }

    def test_decided_cluster_writes_real_tags(self, tmp_path):
        names = ["a.mp3", "b.mp3", "c.mp3"]
        folder = self._make_album(tmp_path, names)
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        _run_album(
            folder,
            _mock_client(self._responses(names)),
            FingerprintParams(album_mode=True, write_tags=True, is_dry_run=False),
            progress,
            complete,
            error,
        )
        error.assert_not_called()
        kwargs = complete.call_args.kwargs
        assert kwargs["counts"]["tagged"] == 3
        for name in names:
            tags = self._acoustid_tags(folder / name)
            assert tags["Acoustid Id"] == f"ac-mb-{name}", (
                f"cluster-decided Acoustid Id missing on {name}"
            )
            assert tags["Acoustid Fingerprint"] == f"fp-{name}"

    def test_album_tag_tie_break_decides_and_writes_real_tags(self, tmp_path):
        """The measured 10cc failure shape, end to end: two clusters tie
        exactly, the files' real album tags name the correct one, and the
        run decides and writes tags instead of leaving the folder
        ambiguous."""
        import mutagen
        from mutagen.id3 import TALB

        from audio_fingerprinter.core.models import ReleaseGroup

        names = ["a.mp3", "b.mp3", "c.mp3"]
        folder = self._make_album(tmp_path, names)
        for name in names:
            audio = mutagen.File(str(folder / name))
            if audio.tags is None:
                audio.add_tags()
            audio.tags.add(TALB(encoding=3, text=["The Album"]))
            audio.save()

        tied = (
            ReleaseGroup("rg-album", "The Album"),
            ReleaseGroup("rg-other", "Other Album"),
        )
        responses = {
            f"fp-{name}": LookupResult(
                status="ok",
                recordings=(_rg_rec(f"mb-{name}", 0.9, tied),),
            )
            for name in names
        }
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        _run_album(
            folder,
            _mock_client(responses),
            FingerprintParams(album_mode=True, write_tags=True, is_dry_run=False),
            progress,
            complete,
            error,
        )
        error.assert_not_called()
        assert complete.call_args.kwargs["counts"]["tagged"] == 3
        log_text = "\n".join(complete.call_args.kwargs["log_entries"])
        assert "album-tag match among 2 clusters tied at 2.70" in log_text
        for name in names:
            tags = self._acoustid_tags(folder / name)
            assert tags["Acoustid Id"] == f"ac-mb-{name}", (
                f"tie-broken cluster did not tag {name}"
            )

    def test_dry_run_writes_no_tags(self, tmp_path):
        names = ["a.mp3", "b.mp3", "c.mp3"]
        folder = self._make_album(tmp_path, names)
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        _run_album(
            folder,
            _mock_client(self._responses(names)),
            FingerprintParams(album_mode=True, write_tags=True, is_dry_run=True),
            progress,
            complete,
            error,
        )
        error.assert_not_called()
        assert complete.call_args.kwargs["counts"]["tagged"] == 0
        for name in names:
            assert "Acoustid Id" not in self._acoustid_tags(folder / name)

    def test_ambiguous_album_writes_no_tags(self, tmp_path):
        names = [f"{ch}.mp3" for ch in "abcdef"]
        folder = self._make_album(tmp_path, names)
        responses = {
            f"fp-{name}": LookupResult(
                status="ok",
                recordings=(
                    _rg_rec(
                        f"mb-{name}",
                        0.90,
                        (_ALBUM if i < 3 else _OTHER,),
                    ),
                ),
            )
            for i, name in enumerate(names)
        }
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        _run_album(
            folder,
            _mock_client(responses),
            FingerprintParams(album_mode=True, write_tags=True, is_dry_run=False),
            progress,
            complete,
            error,
        )
        error.assert_not_called()
        assert complete.call_args.kwargs["counts"]["tagged"] == 0
        for name in names:
            assert "Acoustid Id" not in self._acoustid_tags(folder / name)


class TestMbidRealOutcome:
    """Decode-and-measure for E2: the opt-in MusicBrainz identifiers must
    actually appear on real files (read back through the shared reader),
    stay absent when off / dry-run / write-tags-off, and the album id must
    be omitted when the release is ambiguous."""

    TRACK_ID = "mb-rec"
    ARTIST_ID = "mb-art"
    ALBUM_ID = "mb-rel"

    @staticmethod
    def _make_track(tmp_path, name="t.mp3"):
        from pydub import AudioSegment

        AudioSegment.silent(duration=300).export(str(tmp_path / name), format="mp3")
        return tmp_path / name

    @staticmethod
    def _mbid_tags(path) -> dict[str, str]:
        from audio_suite_shared.tag_helper_reader import read_musicbrainz_ids

        return read_musicbrainz_ids(str(path))

    @staticmethod
    def _acoustid_written(path) -> bool:
        import mutagen

        audio = mutagen.File(str(path))
        assert audio is not None and audio.tags is not None
        return any(str(tag.desc) == "Acoustid Id" for tag in audio.tags.getall("TXXX"))

    def _recording(self, *release_ids: str) -> AcoustidRecording:
        from audio_fingerprinter.core.models import Release

        releases = tuple(
            Release(
                release_id=release_id,
                release_group_id=_ALBUM.release_group_id,
                release_group_title=_ALBUM.title,
                release_group_type="Album",
            )
            for release_id in release_ids
        )
        return AcoustidRecording(
            acoustid_id="a1",
            recording_id=self.TRACK_ID,
            title="Song",
            artist="Artist",
            artist_ids=(self.ARTIST_ID,),
            score=0.9,
            duration=60,
            release_groups=(_ALBUM,),
            releases=releases,
        )

    def _run_single_file(
        self, folder, recording: AcoustidRecording, **params_kwargs: Any
    ):
        client = MagicMock()
        client.lookup.return_value = LookupResult(status="ok", recordings=(recording,))
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        slot_q: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            slot_q.put(i)
        defaults: dict[str, Any] = {
            "lookup_enabled": True,
            "write_tags": True,
            "is_dry_run": False,
        }
        defaults.update(params_kwargs)
        with (
            _patch_fingerprint_by_name(),
            patch(
                "audio_fingerprinter.core.file_processor.resolve_fpcalc",
                return_value="fpcalc",
            ),
            patch(
                "audio_fingerprinter.core.file_processor.AcoustidClient",
                return_value=client,
            ),
        ):
            run_fingerprinting(
                dir_path=str(folder),
                api_key="key",
                params=FingerprintParams(**defaults),
                slot_vars=[MagicMock() for _ in range(DEFAULT_MAX_WORKERS)],
                slot_queue=slot_q,
                on_progress=progress,
                on_complete=complete,
                on_error=error,
            )
        return complete

    def test_opt_in_writes_real_mbid_tags(self, tmp_path):
        track = self._make_track(tmp_path)
        complete = self._run_single_file(
            tmp_path, self._recording("mb-rel"), write_mbids=True
        )
        assert complete.call_args.kwargs["counts"]["tagged"] == 1
        tags = self._mbid_tags(track)
        assert tags["MUSICBRAINZ_TRACKID"] == self.TRACK_ID
        assert tags["MUSICBRAINZ_ARTISTID"] == self.ARTIST_ID
        assert tags["MUSICBRAINZ_ALBUMID"] == self.ALBUM_ID

    def test_default_off_writes_no_mbid_tags(self, tmp_path):
        track = self._make_track(tmp_path)
        self._run_single_file(tmp_path, self._recording("mb-rel"))
        # The AcoustID tags were written; the MBIDs were not.
        assert self._acoustid_written(track)
        assert self._mbid_tags(track) == {}

    def test_write_mbids_requires_write_tags(self, tmp_path):
        track = self._make_track(tmp_path)
        client = MagicMock()
        client.lookup.return_value = LookupResult(
            status="ok", recordings=(self._recording("mb-rel"),)
        )
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        slot_q: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            slot_q.put(i)
        with (
            _patch_fingerprint_by_name(),
            patch(
                "audio_fingerprinter.core.file_processor.resolve_fpcalc",
                return_value="fpcalc",
            ),
            patch(
                "audio_fingerprinter.core.file_processor.AcoustidClient",
                return_value=client,
            ),
        ):
            run_fingerprinting(
                dir_path=str(tmp_path),
                api_key="key",
                params=FingerprintParams(
                    lookup_enabled=True,
                    write_tags=False,
                    write_mbids=True,
                    is_dry_run=False,
                ),
                slot_vars=[MagicMock() for _ in range(DEFAULT_MAX_WORKERS)],
                slot_queue=slot_q,
                on_progress=progress,
                on_complete=complete,
                on_error=error,
            )
        assert complete.call_args.kwargs["counts"]["tagged"] == 0
        assert self._mbid_tags(track) == {}

    def test_dry_run_writes_no_mbid_tags(self, tmp_path):
        track = self._make_track(tmp_path)
        self._run_single_file(
            tmp_path, self._recording("mb-rel"), write_mbids=True, is_dry_run=True
        )
        assert self._mbid_tags(track) == {}

    def test_ambiguous_release_omits_albumid_only(self, tmp_path):
        # Two indistinguishable releases: track and artist ids are written,
        # the album id is not (never-guess guarantee).
        track = self._make_track(tmp_path)
        self._run_single_file(
            tmp_path, self._recording("rel-a", "rel-b"), write_mbids=True
        )
        tags = self._mbid_tags(track)
        assert tags["MUSICBRAINZ_TRACKID"] == self.TRACK_ID
        assert tags["MUSICBRAINZ_ARTISTID"] == self.ARTIST_ID
        assert "MUSICBRAINZ_ALBUMID" not in tags

    def test_album_mode_opt_in_writes_real_mbid_tags(self, tmp_path):
        names = ["a.mp3", "b.mp3", "c.mp3"]
        folder = TestAlbumModeRealOutcome._make_album(tmp_path, names)
        responses = {
            f"fp-{name}": LookupResult(
                status="ok",
                recordings=(self._recording(f"rel-{name}"),),
            )
            for name in names
        }
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        _run_album(
            folder,
            _mock_client(responses),
            FingerprintParams(
                album_mode=True,
                write_tags=True,
                is_dry_run=False,
                write_mbids=True,
            ),
            progress,
            complete,
            error,
        )
        error.assert_not_called()
        assert complete.call_args.kwargs["counts"]["tagged"] == 3
        for name in names:
            tags = self._mbid_tags(folder / name)
            assert tags["MUSICBRAINZ_TRACKID"] == self.TRACK_ID
            assert tags["MUSICBRAINZ_ARTISTID"] == self.ARTIST_ID
            assert tags["MUSICBRAINZ_ALBUMID"] == f"rel-{name}"


def _processor_tree() -> ast.Module:
    """Parse the production module so the locks below read real source."""
    source = inspect.getsourcefile(file_processor_module)
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=source)


def _enum_members_used(tree: ast.Module) -> set[str]:
    """Every ``FingerprintStatus.<NAME>`` attribute referenced in the module."""
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "FingerprintStatus"
    }


class TestStatusEnumIsTheSingleSource:
    """E3: the status vocabulary lives in one enum, and the tag-write tail
    is written once."""

    def test_no_bare_status_literal_survives_in_the_processor(self):
        values = {member.value for member in FingerprintStatus}
        bare = [
            (node.lineno, node.value)
            for node in ast.walk(_processor_tree())
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in values
        ]
        assert bare == []

    def test_every_status_member_is_actually_produced(self):
        # Two-way lock: no member is dead, and no producer invents a status
        # outside the enum. A scan that matched nothing would pass the first
        # assertion above vacuously, hence the exact-set comparison.
        assert _enum_members_used(_processor_tree()) == {
            member.name for member in FingerprintStatus
        }

    def test_acoustid_tag_write_has_exactly_one_call_site(self):
        calls = [
            node
            for node in ast.walk(_processor_tree())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "write_acoustid_tags"
        ]
        assert len(calls) == 1

    def test_both_match_paths_share_the_extracted_write_helper(self):
        tree = _processor_tree()
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        for name in ("_process_file", "_finalize_album_file", "_commit_match_tags"):
            assert name in functions
        for caller in ("_process_file", "_finalize_album_file"):
            called = {
                node.func.id
                for node in ast.walk(functions[caller])
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            assert "_commit_match_tags" in called


class TestCommitMatchTags:
    """The shared write tail used by per-file and album matching."""

    @staticmethod
    def _matched() -> FingerprintFileResult:
        return FingerprintFileResult(
            file_path="/x/a.mp3",
            filename="a.mp3",
            duration=61.0,
            fingerprint="FP123",
            status=FingerprintStatus.MATCHED,
            message="Song (score 0.90)",
            acoustid_id="a1",
        )

    def test_success_reports_tagged_and_keeps_the_match_fields(self):
        matched = self._matched()
        recording = _make_recording()
        with patch(
            "audio_fingerprinter.core.file_processor.write_acoustid_tags",
            return_value=(True, "AcoustID tags written"),
        ) as mock_write:
            result = _commit_match_tags(
                matched, recording, FingerprintParams(), undo_batch="batch-1"
            )
        mock_write.assert_called_once_with("/x/a.mp3", "FP123", "a1")
        assert result.status == FingerprintStatus.TAGGED
        assert result.tag_written is True
        assert result.message == "Song (score 0.90)"
        assert result.acoustid_id == "a1"
        assert result.fingerprint == "FP123"
        assert result.duration == 61.0

    def test_failed_write_reports_tag_write_failed_with_the_writer_message(self):
        matched = self._matched()
        with patch(
            "audio_fingerprinter.core.file_processor.write_acoustid_tags",
            return_value=(False, "file is read-only"),
        ):
            result = _commit_match_tags(
                matched, _make_recording(), FingerprintParams(), undo_batch=None
            )
        assert result.status == FingerprintStatus.TAG_WRITE_FAILED
        assert result.tag_written is False
        assert result.message == "Song (score 0.90) — file is read-only"

    def test_mbid_note_is_appended_when_the_opt_in_is_on(self):
        matched = self._matched()
        params = FingerprintParams(write_mbids=True, mbid_region="GB")
        with (
            patch(
                "audio_fingerprinter.core.file_processor.write_acoustid_tags",
                return_value=(True, "written"),
            ),
            patch(
                "audio_fingerprinter.core.file_processor._write_mbids_for",
                return_value="MBID track id written",
            ) as mock_mbids,
        ):
            result = _commit_match_tags(matched, _make_recording(), params, None)
        mock_mbids.assert_called_once()
        assert result.status == FingerprintStatus.TAGGED
        assert result.message == "Song (score 0.90) — MBID track id written"

    def test_mbids_are_skipped_when_the_acoustid_write_failed(self):
        matched = self._matched()
        params = FingerprintParams(write_mbids=True)
        with (
            patch(
                "audio_fingerprinter.core.file_processor.write_acoustid_tags",
                return_value=(False, "boom"),
            ) as mock_write,
            patch(
                "audio_fingerprinter.core.file_processor._write_mbids_for",
                return_value="MBID track id written",
            ) as mock_mbids,
        ):
            result = _commit_match_tags(matched, _make_recording(), params, None)
        mock_write.assert_called_once()
        assert result.status == FingerprintStatus.TAG_WRITE_FAILED
        assert mock_mbids.call_count == 0

    def test_mbids_are_skipped_when_the_opt_in_is_off(self):
        matched = self._matched()
        with (
            patch(
                "audio_fingerprinter.core.file_processor.write_acoustid_tags",
                return_value=(True, "written"),
            ) as mock_write,
            patch(
                "audio_fingerprinter.core.file_processor._write_mbids_for",
                return_value="MBID track id written",
            ) as mock_mbids,
        ):
            result = _commit_match_tags(
                matched, _make_recording(), FingerprintParams(), None
            )
        mock_write.assert_called_once()
        assert result.status == FingerprintStatus.TAGGED
        assert mock_mbids.call_count == 0


class TestResultDisplayCoversEveryStatus:
    """Byte-identical display for every enum member."""

    def test_each_member_renders_its_own_value(self):
        for member in FingerprintStatus:
            result = FingerprintFileResult(
                file_path="/x/a.mp3", filename="a.mp3", status=member
            )
            line = _result_display(result)
            assert line.startswith(f"[{member.value}] a.mp3")
            assert "FingerprintStatus" not in line

    def test_analysed_status_keeps_the_bare_filename_form(self):
        result = FingerprintFileResult(
            file_path="/x/a.mp3",
            filename="a.mp3",
            status=FingerprintStatus.ANALYSED,
            message="Fingerprint ready for album matching.",
        )
        assert _result_display(result) == "[ANALYSED] a.mp3"


class TestIsrcEnrichmentRealOutcome:
    """Sprint 2 Item 2.1 end to end: the enrichment must reach the bytes.

    Every assertion reads the file back through mutagen, never the params
    object the run was handed, so a flag that is accepted but never threaded
    to the write site cannot pass.
    """

    REC_ID = "b0f1c1c8-3a4d-4c1b-9d1e-1a2b3c4d5e6f"
    ALT_ID = "c1d2e3f4-a5b6-4c7d-8e9f-0a1b2c3d4e5f"
    REL_ID = "d2e3f4a5-b6c7-4d8e-9f0a-1b2c3d4e5f60"
    ISRC = "GBAYE0601498"
    ALT_ISRC = "USRC17607839"

    @staticmethod
    def _make_track(tmp_path):
        from pydub import AudioSegment

        AudioSegment.silent(duration=300).export(str(tmp_path / "t.mp3"), format="mp3")
        return tmp_path / "t.mp3"

    @staticmethod
    def _tsrc(path) -> list[str]:
        """Return the ID3 TSRC values actually stored on disk."""
        import mutagen

        audio = mutagen.File(str(path))
        assert audio is not None and audio.tags is not None
        return [str(text) for frame in audio.tags.getall("TSRC") for text in frame.text]

    def _recording(self, recording_id: str = "") -> AcoustidRecording:
        from audio_fingerprinter.core.models import Release

        return AcoustidRecording(
            acoustid_id="a1",
            recording_id=recording_id or self.REC_ID,
            title="Song",
            artist="Artist",
            score=0.9,
            duration=60,
            releases=(
                Release(
                    release_id=self.REL_ID,
                    title="Sheet Music",
                    release_group_id=_ALBUM.release_group_id,
                    release_group_title=_ALBUM.title,
                    release_group_type="Album",
                ),
            ),
        )

    @classmethod
    def _mb_client(cls, recordings: dict[str, Any]):
        """Build a fake MusicBrainzClient keyed by recording MBID."""
        from audio_fingerprinter.core.models import MBReleaseFacts
        from audio_fingerprinter.core.musicbrainz_client import MBResult

        client = MagicMock()

        def _get_recording(recording_id: str):
            value = recordings.get(recording_id)
            if value is None:
                return MBResult(status="not found", reason="no such recording")
            if isinstance(value, MBResult):
                return value
            return MBResult(status="ok", value=value)

        client.get_recording.side_effect = _get_recording
        client.get_release.return_value = MBResult(
            status="ok",
            value=MBReleaseFacts(
                release_id=cls.REL_ID,
                title="Sheet Music",
                date="1974-03-01",
                countries=("GB",),
                labels=("UK Records",),
            ),
        )
        return client

    def _run(
        self,
        folder,
        recordings: list[AcoustidRecording],
        mb_client: MagicMock,
        **params_kwargs: Any,
    ):
        client = MagicMock()
        client.lookup.return_value = LookupResult(
            status="ok", recordings=tuple(recordings)
        )
        complete, error = MagicMock(), MagicMock()
        slot_q: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            slot_q.put(i)
        defaults: dict[str, Any] = {
            "lookup_enabled": True,
            "write_tags": True,
            "is_dry_run": False,
            "musicbrainz": True,
            "write_isrc": True,
        }
        defaults.update(params_kwargs)
        with (
            _patch_fingerprint_by_name(),
            patch(
                "audio_fingerprinter.core.file_processor.resolve_fpcalc",
                return_value="fpcalc",
            ),
            patch(
                "audio_fingerprinter.core.file_processor.AcoustidClient",
                return_value=client,
            ),
            patch(
                "audio_fingerprinter.core.file_processor.MusicBrainzClient",
                return_value=mb_client,
            ),
        ):
            run_fingerprinting(
                dir_path=str(folder),
                api_key="key",
                params=FingerprintParams(**defaults),
                slot_vars=[MagicMock() for _ in range(DEFAULT_MAX_WORKERS)],
                slot_queue=slot_q,
                on_progress=MagicMock(),
                on_complete=complete,
                on_error=error,
            )
        assert not error.called, error.call_args
        return complete

    def test_isrc_is_written_to_a_real_file(self, tmp_path):
        from audio_fingerprinter.core.models import MBRecording

        track = self._make_track(tmp_path)
        complete = self._run(
            tmp_path,
            [self._recording()],
            self._mb_client(
                {self.REC_ID: MBRecording(recording_id=self.REC_ID, isrcs=(self.ISRC,))}
            ),
        )

        assert complete.call_args.kwargs["counts"]["tagged"] == 1
        assert self._tsrc(track) == [self.ISRC]

    def test_dry_run_writes_no_isrc(self, tmp_path):
        from audio_fingerprinter.core.models import MBRecording

        track = self._make_track(tmp_path)
        self._run(
            tmp_path,
            [self._recording()],
            self._mb_client(
                {self.REC_ID: MBRecording(recording_id=self.REC_ID, isrcs=(self.ISRC,))}
            ),
            is_dry_run=True,
        )
        assert self._tsrc(track) == []

    def test_write_isrc_off_writes_nothing(self, tmp_path):
        from audio_fingerprinter.core.models import MBRecording

        track = self._make_track(tmp_path)
        self._run(
            tmp_path,
            [self._recording()],
            self._mb_client(
                {self.REC_ID: MBRecording(recording_id=self.REC_ID, isrcs=(self.ISRC,))}
            ),
            write_isrc=False,
        )
        assert self._tsrc(track) == []

    def test_musicbrainz_off_never_queries_the_service(self, tmp_path):
        track = self._make_track(tmp_path)
        client = self._mb_client({})
        self._run(tmp_path, [self._recording()], client, musicbrainz=False)
        client.get_recording.assert_not_called()
        assert self._tsrc(track) == []

    def test_lookup_failure_does_not_fail_the_file(self, tmp_path):
        from audio_fingerprinter.core.models import FingerprintStatus
        from audio_fingerprinter.core.musicbrainz_client import MBResult

        track = self._make_track(tmp_path)
        complete = self._run(
            tmp_path,
            [self._recording()],
            self._mb_client({self.REC_ID: MBResult(status="offline", reason="down")}),
        )

        results = complete.call_args.kwargs["results"]
        assert len(results) == 1
        # The AcoustID outcome still stands; only the enrichment is missing.
        assert results[0].status == FingerprintStatus.TAGGED
        assert results[0].mb is not None
        assert "down" in results[0].mb.note
        assert results[0].isrcs == ()
        assert self._tsrc(track) == []

    def test_release_facts_are_retrieved_for_the_selected_release(self, tmp_path):
        from audio_fingerprinter.core.models import MBRecording

        self._make_track(tmp_path)
        mb_client = self._mb_client(
            {self.REC_ID: MBRecording(recording_id=self.REC_ID, isrcs=(self.ISRC,))}
        )
        complete = self._run(tmp_path, [self._recording()], mb_client)

        result = complete.call_args.kwargs["results"][0]
        assert result.mb is not None
        assert result.mb.release is not None
        assert result.mb.release.date == "1974-03-01"
        assert result.mb.release.countries == ("GB",)
        mb_client.get_release.assert_called_once_with(self.REL_ID)

    def test_near_tie_resolved_by_musicbrainz_writes_its_isrc(self, tmp_path):
        """The MusicBrainz evidence, not the AcoustID rank, decides the write."""
        from audio_fingerprinter.core.models import MBRecording

        track = self._make_track(tmp_path)
        top = self._recording(self.REC_ID)
        runner_up = AcoustidRecording(
            acoustid_id="a2",
            recording_id=self.ALT_ID,
            title="Song",
            artist="Artist",
            score=0.94,
            duration=60,
            releases=top.releases,
        )
        # The rank-order pick has no ISRCs; only the runner-up has them.
        mb_client = self._mb_client(
            {
                self.REC_ID: MBRecording(recording_id=self.REC_ID),
                self.ALT_ID: MBRecording(
                    recording_id=self.ALT_ID, isrcs=(self.ALT_ISRC,)
                ),
            }
        )
        complete = self._run(tmp_path, [top, runner_up], mb_client)

        result = complete.call_args.kwargs["results"][0]
        assert result.mb is not None
        assert result.mb.resolved_ambiguity is True
        assert result.mb.recording_id == self.ALT_ID
        assert self._tsrc(track) == [self.ALT_ISRC]


# ── ISRC submission (Item 2.3) ────────────────────────────────────────────

_SUBMIT_REC = "b0f1c1c8-3a4d-4c1b-9d1e-1a2b3c4d5e6f"
_SUBMIT_OTHER = "c1d2e3f4-a5b6-4c7d-8e9f-0a1b2c3d4e5f"


def _submit_result(
    tmp_path: Any,
    name: str,
    *,
    recording_id: str = _SUBMIT_REC,
    registered: tuple[str, ...] = (),
) -> FingerprintFileResult:
    """A matched result whose file exists on disk (tags are patched)."""
    path = tmp_path / name
    path.write_bytes(b"")
    return FingerprintFileResult(
        file_path=str(path),
        filename=name,
        status=FingerprintStatus.MATCHED,
        recording_id=recording_id,
        isrcs=registered,
    )


def _patch_tagged(mapping: dict[str, tuple[str, ...]]):
    """Patch ``read_isrcs`` to answer by basename."""
    return patch(
        "audio_fingerprinter.core.file_processor.read_isrcs",
        side_effect=lambda path: mapping[os.path.basename(path)],
    )


class TestCollectIsrcSubmissions:
    """What a run offers MusicBrainz: the files' own codes, minus knowns."""

    def test_submits_the_files_tagged_isrcs(self, tmp_path):
        result = _submit_result(tmp_path, "a.mp3")
        with _patch_tagged({"a.mp3": ("USRC17607839",)}):
            submissions, notes = collect_isrc_submissions([result])
        assert len(submissions) == 1
        assert submissions[0].recording_id == _SUBMIT_REC
        assert submissions[0].isrcs == ("USRC17607839",)
        assert notes == ()

    def test_display_form_is_normalised(self, tmp_path):
        result = _submit_result(tmp_path, "a.mp3")
        with _patch_tagged({"a.mp3": ("us-rc1-76-07839",)}):
            submissions, _notes = collect_isrc_submissions([result])
        assert submissions[0].isrcs == ("USRC17607839",)

    def test_already_registered_codes_are_dropped_and_reported(self, tmp_path):
        result = _submit_result(tmp_path, "a.mp3", registered=("USRC17607839",))
        with _patch_tagged({"a.mp3": ("USRC17607839",)}):
            submissions, notes = collect_isrc_submissions([result])
        assert submissions == ()
        assert any("nothing new to submit" in note for note in notes)

    def test_invalid_code_is_reported_not_submitted(self, tmp_path):
        result = _submit_result(tmp_path, "a.mp3")
        with _patch_tagged({"a.mp3": ("NOPE",)}):
            submissions, notes = collect_isrc_submissions([result])
        assert submissions == ()
        assert any("[ISRC SKIPPED] a.mp3" in note for note in notes)
        assert any("not an ISRC" in note for note in notes)

    def test_two_files_on_one_recording_merge(self, tmp_path):
        first = _submit_result(tmp_path, "a.mp3")
        second = _submit_result(tmp_path, "b.mp3")
        with _patch_tagged(
            {
                "a.mp3": ("USRC17607839",),
                "b.mp3": ("USRC17607839", "GBUM72400001"),
            }
        ):
            submissions, _notes = collect_isrc_submissions([first, second])
        assert len(submissions) == 1
        assert submissions[0].isrcs == ("GBUM72400001", "USRC17607839")

    def test_file_without_a_recording_is_reported(self, tmp_path):
        result = _submit_result(tmp_path, "a.mp3", recording_id="")
        with _patch_tagged({"a.mp3": ("USRC17607839",)}):
            submissions, notes = collect_isrc_submissions([result])
        assert submissions == ()
        assert any("no MusicBrainz recording" in note for note in notes)

    def test_untagged_file_contributes_nothing(self, tmp_path):
        result = _submit_result(tmp_path, "a.mp3")
        with _patch_tagged({"a.mp3": ()}):
            submissions, notes = collect_isrc_submissions([result])
        assert submissions == ()
        assert notes == ()

    def test_unreadable_tags_are_reported(self, tmp_path):
        result = _submit_result(tmp_path, "a.mp3")
        with patch(
            "audio_fingerprinter.core.file_processor.read_isrcs",
            side_effect=OSError("locked"),
        ):
            submissions, notes = collect_isrc_submissions([result])
        assert submissions == ()
        assert any("could not read its ISRCs" in note for note in notes)


class TestRunIsrcSubmission:
    """Preview vs post, and the refusals that must not spend an edit."""

    def _client(self, result: ISRCSubmitResult) -> MagicMock:
        client = MagicMock(spec=MusicBrainzClient)
        client.submit_isrcs.return_value = result
        return client

    def test_dry_run_renders_the_payload_and_posts_nothing(self, tmp_path):
        result = _submit_result(tmp_path, "a.mp3")
        client = self._client(ISRCSubmitResult(status="ok"))
        with _patch_tagged({"a.mp3": ("USRC17607839",)}):
            payload, lines, display = _run_isrc_submission(
                [result], FingerprintParams(submit_isrc=True), client, None
            )
        client.submit_isrcs.assert_not_called()
        assert payload["mode"] == "preview"
        assert payload["status"] == "preview"
        assert payload["isrcs"] == 1
        assert payload["recordings"] == 1
        assert 'isrc id="USRC17607839"' in payload["xml"]
        # The payload keeps the exact wire bytes; the log writes one line per
        # entry, so the rendered document loses only its final newline.
        assert payload["xml"].rstrip("\n") in lines
        assert display.startswith("[ISRC PREVIEW]")

    def test_live_posts_and_reports_a_pending_edit(self, tmp_path):
        result = _submit_result(tmp_path, "a.mp3")
        client = self._client(
            ISRCSubmitResult(
                status="ok", recordings=1, isrcs=1, url="https://mb/recording"
            )
        )
        with _patch_tagged({"a.mp3": ("USRC17607839",)}):
            payload, lines, display = _run_isrc_submission(
                [result],
                FingerprintParams(submit_isrc=True, is_dry_run=False),
                client,
                MBAuth(token="tok"),
            )
        client.submit_isrcs.assert_called_once()
        assert payload["status"] == "ok"
        assert payload["mode"] == "live"
        assert any("[ISRC SUBMITTED]" in line for line in lines)
        assert any("7 days" in line for line in lines)
        assert display.startswith("[ISRC SUBMITTED]")

    def test_nothing_to_submit_makes_no_request(self, tmp_path):
        result = _submit_result(tmp_path, "a.mp3")
        client = self._client(ISRCSubmitResult(status="ok"))
        with _patch_tagged({"a.mp3": ()}):
            payload, _lines, display = _run_isrc_submission(
                [result],
                FingerprintParams(submit_isrc=True, is_dry_run=False),
                client,
                MBAuth(token="tok"),
            )
        client.submit_isrcs.assert_not_called()
        assert payload["status"] == "nothing to submit"
        assert payload["xml"] == ""
        assert "Nothing new to submit" in display


class TestIsrcSubmissionRealOutcome:
    """A real tagged file, a real client, and the byte-identical lock."""

    ISRC = "USRC17607839"

    @staticmethod
    def _make_track(folder) -> Any:
        from pydub import AudioSegment

        from audio_suite_shared.tag_helper_writer import write_isrc

        path = folder / "t.mp3"
        AudioSegment.silent(duration=300).export(str(path), format="mp3")
        write_isrc(str(path), [TestIsrcSubmissionRealOutcome.ISRC])
        return path

    @staticmethod
    def _recording_json(*, isrcs: tuple[str, ...] = ()) -> dict[str, Any]:
        return {
            "id": _SUBMIT_REC,
            "title": "Song",
            "length": 60000,
            "isrcs": list(isrcs),
            "artist-credit": [
                {"name": "Artist", "artist": {"id": "art", "name": "Artist"}}
            ],
            "releases": [],
        }

    @classmethod
    def _session(cls, *, isrcs: tuple[str, ...] = ()) -> MagicMock:
        session = MagicMock(spec=requests.Session)
        session.headers = MagicMock()
        get_resp = MagicMock(spec=requests.Response)
        get_resp.status_code = 200
        get_resp.json.return_value = cls._recording_json(isrcs=isrcs)
        session.get.return_value = get_resp
        post_resp = MagicMock(spec=requests.Response)
        post_resp.status_code = 200
        session.post.return_value = post_resp
        return session

    def _run(self, folder, *, dry_run: bool, auth: MBAuth | None, isrcs=()):
        session = self._session(isrcs=isrcs)
        mb_client = MusicBrainzClient(requests_per_second=1000.0, session=session)
        acoustid = MagicMock()
        acoustid.lookup.return_value = LookupResult(
            status="ok",
            recordings=(
                _make_recording(
                    acoustid_id="a1",
                    recording_id=_SUBMIT_REC,
                    title="Song",
                    artist="Artist",
                ),
            ),
        )
        progress, complete, error = MagicMock(), MagicMock(), MagicMock()
        slot_q: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            slot_q.put(i)
        with (
            _patch_fingerprint_by_name(),
            patch(
                "audio_fingerprinter.core.file_processor.resolve_fpcalc",
                return_value="fpcalc",
            ),
            patch(
                "audio_fingerprinter.core.file_processor.AcoustidClient",
                return_value=acoustid,
            ),
            patch(
                "audio_fingerprinter.core.file_processor.MusicBrainzClient",
                return_value=mb_client,
            ),
        ):
            run_fingerprinting(
                dir_path=str(folder),
                api_key="key",
                params=FingerprintParams(
                    musicbrainz=True,
                    submit_isrc=True,
                    is_dry_run=dry_run,
                ),
                slot_vars=[MagicMock() for _ in range(DEFAULT_MAX_WORKERS)],
                slot_queue=slot_q,
                on_progress=progress,
                on_complete=complete,
                on_error=error,
                mb_auth=auth,
            )
        return complete, session

    def test_dry_run_preview_is_exactly_what_live_posts(self, tmp_path):
        self._make_track(tmp_path)
        dry_complete, dry_session = self._run(tmp_path, dry_run=True, auth=None)
        dry_payload = dry_complete.call_args.kwargs["isrc_submission"]
        dry_session.post.assert_not_called()
        assert dry_payload["mode"] == "preview"
        assert self.ISRC in dry_payload["xml"]

        live_complete, live_session = self._run(
            tmp_path, dry_run=False, auth=MBAuth(token="tok")
        )
        posted = live_session.post.call_args.kwargs["data"].decode("utf-8")
        # The preview the user approved is byte-for-byte the request sent.
        assert posted == dry_payload["xml"]
        live_payload = live_complete.call_args.kwargs["isrc_submission"]
        assert live_payload["status"] == "ok"
        assert any(
            "[ISRC SUBMITTED]" in line
            for line in live_complete.call_args.kwargs["log_entries"]
        )

    def test_already_registered_isrc_is_not_resubmitted(self, tmp_path):
        self._make_track(tmp_path)
        complete, session = self._run(
            tmp_path, dry_run=False, auth=MBAuth(token="tok"), isrcs=(self.ISRC,)
        )
        session.post.assert_not_called()
        payload = complete.call_args.kwargs["isrc_submission"]
        assert payload["status"] == "nothing to submit"

    def test_missing_token_posts_nothing(self, tmp_path):
        self._make_track(tmp_path)
        complete, session = self._run(tmp_path, dry_run=False, auth=MBAuth())
        session.post.assert_not_called()
        payload = complete.call_args.kwargs["isrc_submission"]
        assert payload["status"] == "no auth"
        assert any(
            "NO AUTH" in line for line in complete.call_args.kwargs["log_entries"]
        )

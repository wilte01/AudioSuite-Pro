"""Tests for audio_fingerprinter.core.file_processor."""

from __future__ import annotations

import os
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
    Fingerprint,
    FingerprintFileResult,
    FingerprintParams,
    LookupResult,
    ReleaseGroup,
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
    patch_album_reader: bool = True,
):
    from contextlib import ExitStack

    slot_q: Queue[int] = Queue()
    for i in range(DEFAULT_MAX_WORKERS):
        slot_q.put(i)
    with ExitStack() as stack:
        for entered in (
            [
                _patch_fingerprint_by_name(),
                patch(
                    "audio_fingerprinter.core.file_processor.resolve_fpcalc",
                    return_value="fpcalc",
                ),
                patch(
                    "audio_fingerprinter.core.file_processor.read_artist_title",
                    return_value=("Unknown", "Unknown"),
                ),
            ]
            + (
                [
                    patch(
                        "audio_fingerprinter.core.file_processor.read_artist_album",
                        return_value=("Unknown", "Unknown"),
                    ),
                ]
                if patch_album_reader
                else []
            )
            + [
                patch(
                    "audio_fingerprinter.core.file_processor.AcoustidClient",
                    return_value=client,
                ),
            ]
        ):
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
            patch_album_reader=False,
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

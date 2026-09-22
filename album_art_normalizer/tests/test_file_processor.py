"""
tests/test_file_processor.py
Unit tests for album_art_normalizer/core/file_processor.py — the
BaseFileProcessor-backed orchestration layer.

_normalize_single_file branches are driven directly with the per-format
processors patched; run_normalization is exercised end-to-end against a
tmp directory (which also covers the shared run_parallel_processing path
in audio_suite_shared.file_processor_base).

Run with:
    pytest tests/test_file_processor.py -v
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from album_art_normalizer.core import file_processor as fp
from album_art_normalizer.core.art_processor import AudioTagReadError


class _FakeVar:
    """Minimal stand-in for a tk.StringVar."""

    def __init__(self) -> None:
        self._value = ""

    def set(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value


def _run_single(
    name: str,
    process_result: str | None = None,
    process_raises: Exception | None = None,
) -> tuple[list[dict], str]:
    """Call _normalize_single_file with patched per-format processors.

    Returns (on_progress kwargs calls, final slot-var text).
    """
    calls: list[dict] = []
    slot_vars = [_FakeVar()]

    proc_mock = MagicMock()
    if process_raises is not None:
        proc_mock.side_effect = process_raises
    else:
        proc_mock.return_value = process_result

    with (
        patch.object(fp, "process_mp3_artwork", proc_mock),
        patch.object(fp, "process_flac_artwork", proc_mock),
    ):
        fp._normalize_single_file(
            name=name,
            dir_path="/fake",
            target_size=(800, 800),
            slot_idx=0,
            lock=threading.Lock(),
            on_progress=lambda **kw: calls.append(kw),
            slot_vars=slot_vars,
        )
    return calls, slot_vars[0]._value


class TestNormalizeSingleFile:
    def test_resized_and_saved_reports_updated(self) -> None:
        calls, slot = _run_single(
            "song.mp3", process_result="resized to 800x800 and saved"
        )
        assert len(calls) == 1
        assert calls[0]["n_skipped"] == 0
        assert calls[0]["n_errors"] == 0
        assert calls[0]["display_text"].startswith("[UPDATED] song.mp3")
        assert slot.startswith("Processing: song.mp3")

    def test_unchanged_artwork_reports_skipped(self) -> None:
        calls, _ = _run_single("song.flac", process_result="already 800x800")
        assert calls[0]["n_skipped"] == 1
        assert calls[0]["display_text"].startswith("[SKIPPED] song.flac")

    def test_unsupported_format_reports_skipped(self) -> None:
        calls, _ = _run_single("song.txt", process_result="unused")
        assert calls[0]["n_skipped"] == 1
        assert "unsupported format" in calls[0]["display_text"]

    def test_handled_tag_error_reports_error(self) -> None:
        calls, _ = _run_single("song.mp3", process_raises=AudioTagReadError("bad tags"))
        assert calls[0]["n_errors"] == 1
        assert "bad tags" in calls[0]["display_text"]

    def test_handled_audio_suite_error_reports_error(self) -> None:
        from audio_suite_shared.exceptions import AudioIOError

        calls, _ = _run_single("song.mp3", process_raises=AudioIOError("io boom"))
        assert calls[0]["n_errors"] == 1
        assert "io boom" in calls[0]["display_text"]

    def test_unexpected_error_reports_generic_error(self) -> None:
        calls, _ = _run_single("song.mp3", process_raises=OSError("io boom"))
        assert calls[0]["n_errors"] == 1
        assert "unexpected error" in calls[0]["display_text"]

    def test_flac_file_routes_to_flac_processor(self) -> None:
        proc_mock = MagicMock(return_value="resized and saved")
        with (
            patch.object(fp, "process_mp3_artwork", MagicMock()),
            patch.object(fp, "process_flac_artwork", proc_mock),
        ):
            fp._normalize_single_file(
                name="song.flac",
                dir_path="/fake",
                target_size=(800, 800),
                slot_idx=0,
                lock=threading.Lock(),
                on_progress=lambda **kw: None,
            )
        proc_mock.assert_called_once_with(Path("/fake") / "song.flac", (800, 800))

    def test_ogg_file_routes_to_unified_processor(self) -> None:
        proc_mock = MagicMock(return_value="resized and saved")
        with patch.object(fp, "process_audio_artwork", proc_mock):
            fp._normalize_single_file(
                name="song.ogg",
                dir_path="/fake",
                target_size=(800, 800),
                slot_idx=0,
                lock=threading.Lock(),
                on_progress=lambda **kw: None,
            )
        proc_mock.assert_called_once_with(Path("/fake") / "song.ogg", (800, 800))

    def test_wav_file_routes_to_unified_processor(self) -> None:
        proc_mock = MagicMock(return_value="resized and saved")
        with patch.object(fp, "process_audio_artwork", proc_mock):
            fp._normalize_single_file(
                name="song.wav",
                dir_path="/fake",
                target_size=(800, 800),
                slot_idx=0,
                lock=threading.Lock(),
                on_progress=lambda **kw: None,
            )
        proc_mock.assert_called_once_with(Path("/fake") / "song.wav", (800, 800))

    def test_aiff_file_routes_to_unified_processor(self) -> None:
        proc_mock = MagicMock(return_value="resized and saved")
        with patch.object(fp, "process_audio_artwork", proc_mock):
            fp._normalize_single_file(
                name="song.aiff",
                dir_path="/fake",
                target_size=(800, 800),
                slot_idx=0,
                lock=threading.Lock(),
                on_progress=lambda **kw: None,
            )
        proc_mock.assert_called_once_with(Path("/fake") / "song.aiff", (800, 800))


class TestRunNormalization:
    def test_end_to_end_mixed_outcomes(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.flac").write_bytes(b"x")

        progress: list[dict] = []
        complete: dict[str, Any] = {}
        error_calls: list[str] = []

        mp3_mock = MagicMock(return_value="resized to 800x800 and saved")
        flac_mock = MagicMock(return_value="already 800x800")
        with (
            patch.object(fp, "process_mp3_artwork", mp3_mock),
            patch.object(fp, "process_flac_artwork", flac_mock),
        ):
            fp.run_normalization(
                dir_path=str(tmp_path),
                target_size=(800, 800),
                slot_vars=[_FakeVar() for _ in range(4)],
                on_progress=lambda **kw: progress.append(kw),
                on_complete=lambda **kw: complete.update(kw),
                on_error=error_calls.append,
            )

        assert error_calls == []
        assert complete["total"] == 2
        assert complete["processed"] == 2
        assert complete["skipped"] == 1
        assert complete["errors"] == 0
        assert len(complete["log_entries"]) == 2
        assert len(progress) == 2
        mp3_mock.assert_called_once()
        flac_mock.assert_called_once()

    def test_omitted_callbacks_default_to_noops(self, tmp_path: Path) -> None:
        """CLI callers may pass no callbacks; the pipeline must not raise."""
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        fp.run_normalization(
            dir_path=str(empty),
            target_size=(800, 800),
        )  # must not raise

    def test_processor_defaults(self) -> None:
        proc = fp.ArtNormalizerProcessor()
        assert proc.operation_type == "art_normalization"
        assert proc.max_workers == 4

    def test_processor_respects_custom_workers(self) -> None:
        assert fp.ArtNormalizerProcessor(max_workers=2).max_workers == 2


class TestUndoBatchRecording:
    """Undo-batch recording for album art runs (Phase 3d of the plan)."""

    def _jpeg_bytes(self) -> bytes:
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (80, 80), (10, 20, 30)).save(buf, format="JPEG")
        return buf.getvalue()

    def _fake_embed_process(self, path: Path, target: tuple[int, int]) -> str:
        from album_art_normalizer.core.art_processor import embed_artwork

        embed_artwork(str(path), self._jpeg_bytes())
        return "resized and saved"

    def test_live_run_records_embed_snapshots_under_active_batch(
        self, tmp_path: Path
    ) -> None:
        """A live run must record tag snapshots from worker threads into the
        active undo batch, joined via use_batch."""
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches

        undo_db = tmp_path / "undo_log.db"
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.flac").write_bytes(b"x")

        handler = MagicMock()
        handler.get_raw_tags.return_value = {"APIC": b"old"}
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler

        def _run() -> None:
            with active_batch("album_art_normalizer", "tag_edit", db_path=undo_db):
                fp.run_normalization(
                    dir_path=str(tmp_path),
                    target_size=(800, 800),
                    on_progress=lambda **kw: None,
                    on_complete=lambda **kw: None,
                    on_error=lambda msg: None,
                )

        with (
            patch.object(
                fp, "process_mp3_artwork", side_effect=self._fake_embed_process
            ),
            patch.object(
                fp, "process_flac_artwork", side_effect=self._fake_embed_process
            ),
            patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory", shared_factory
            ),
        ):
            _run()

        batches = list_recent_batches(limit=10, db_path=undo_db)
        assert len(batches) == 1
        assert batches[0].tool_name == "album_art_normalizer"
        assert batches[0].operation_type == "tag_edit"
        assert batches[0].record_count == 2

    def test_run_without_batch_records_nothing(self, tmp_path: Path) -> None:
        from audio_suite_shared.batch_undo import list_recent_batches

        undo_db = tmp_path / "undo_log.db"
        (tmp_path / "a.mp3").write_bytes(b"x")

        handler = MagicMock()
        handler.get_raw_tags.return_value = {"APIC": b"old"}
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler

        with (
            patch.object(
                fp, "process_mp3_artwork", side_effect=self._fake_embed_process
            ),
            patch.object(
                fp, "process_flac_artwork", side_effect=self._fake_embed_process
            ),
            patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory", shared_factory
            ),
        ):
            fp.run_normalization(
                dir_path=str(tmp_path),
                target_size=(800, 800),
                on_progress=lambda **kw: None,
                on_complete=lambda **kw: None,
                on_error=lambda msg: None,
            )

        assert list_recent_batches(limit=10, db_path=undo_db) == []

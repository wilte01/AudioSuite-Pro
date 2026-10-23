"""Tests for ``ml_denoiser.core.file_processor``.

Every assertion about a live run decodes the file that was actually written and
measures it; none of them read back the array the adapter had in memory.  The
model is replaced by a fake ``pyrnnoise`` that halves the signal, so the level
the file must carry is known in advance (-6 dBFS) and a silent no-op could not
pass.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
"""

from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from mutagen.id3 import TPE1
from mutagen.wave import WAVE
from pydub import AudioSegment
from pydub.generators import Sine

from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import AudioMissingDependencyError
from ml_denoiser.core import file_processor
from ml_denoiser.core.file_processor import run_ml_denoise
from ml_denoiser.core.models import FRAME_SIZE, DenoiseParams

SR = 44100


def _tone(path: Path, *, seconds: float = 0.5) -> Path:
    """Write a mono 440 Hz tone at -6 dBFS and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tone = Sine(440).to_audio_segment(duration=int(seconds * 1000), volume=-6)
    tone.set_channels(1).export(str(path), format="wav")
    return path


def _install_fake_rnnoise(
    monkeypatch: pytest.MonkeyPatch, *, gain: float = 0.5
) -> None:
    """Register a fake model that multiplies every sample by *gain*."""
    module = types.ModuleType("pyrnnoise")

    class _FakeRNNoise:
        def __init__(self, sample_rate: int) -> None:
            self.sample_rate = sample_rate

        def denoise_chunk(self, chunk: Any, partial: bool = False) -> Any:
            array = np.atleast_2d(np.asarray(chunk, dtype=np.int16))
            processed = np.rint(array.astype(np.float64) * gain).astype(np.int16)
            for start in range(0, processed.shape[1], FRAME_SIZE):
                yield (
                    np.zeros((array.shape[0], 1), dtype=np.float32),
                    processed[:, start : start + FRAME_SIZE],
                )

    module.RNNoise = _FakeRNNoise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyrnnoise", module)


def _slots() -> tuple[list[Any], Queue[int]]:
    """Return one worker slot per pool worker and a full index queue."""
    slots = [MagicMock() for _ in range(DEFAULT_MAX_WORKERS)]
    queue: Queue[int] = Queue()
    for index in range(DEFAULT_MAX_WORKERS):
        queue.put(index)
    return slots, queue


def _run(directory: Path, params: DenoiseParams) -> tuple[dict[str, Any], list[str]]:
    """Drive the real processor; return ``(completion, display lines)``."""
    completions: list[dict[str, Any]] = []
    display: list[str] = []

    def _on_complete(**kwargs: Any) -> None:
        completions.append(kwargs)

    def _on_progress(**kwargs: Any) -> None:
        display.append(kwargs["display_text"])

    errors: list[str] = []
    slots, queue = _slots()
    run_ml_denoise(
        str(directory),
        params,
        slots,
        queue,
        _on_progress,
        _on_complete,
        errors.append,
    )
    assert not errors, f"run reported a fatal error: {errors}"
    assert completions, "run never called on_complete"
    return completions[0], display


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_artist(path: Path, artist: str) -> None:
    wave = WAVE(str(path))
    if wave.tags is None:
        wave.add_tags()
    wave["TPE1"] = TPE1(encoding=3, text=[artist])
    wave.save()


def _read_artist(path: Path) -> str | None:
    wave = WAVE(str(path))
    tags = wave.tags
    if tags is None:
        return None
    frame = tags.get("TPE1")
    return str(frame) if frame is not None else None


class TestDryRun:
    """A dry run measures, reports, and writes nothing."""

    def test_bytes_and_mtime_are_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch)
        source = _tone(tmp_path / "tone.wav")
        digest = _sha256(source)
        mtime = source.stat().st_mtime_ns

        completion, display = _run(tmp_path, DenoiseParams(dry_run=True))

        # FOUND, not SKIP: the measurement ran, so this cannot pass because
        # nothing was detected.
        assert completion["succeeded"] == 1
        assert completion["skipped"] == 0
        assert display[0].startswith("[FOUND] tone.wav")
        assert "Attenuated" in display[0]
        assert _sha256(source) == digest
        assert source.stat().st_mtime_ns == mtime
        assert [p.name for p in tmp_path.iterdir()] == ["tone.wav"]

    def test_no_export_call_happens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The dry-run flag reaches the write site, not just the parameter list."""
        _install_fake_rnnoise(monkeypatch)
        _tone(tmp_path / "tone.wav")
        exported: list[str] = []
        real_export = AudioSegment.export

        def _tracking_export(self: AudioSegment, *args: Any, **kwargs: Any) -> Any:
            exported.append(str(args[0]) if args else "")
            return real_export(self, *args, **kwargs)

        monkeypatch.setattr(AudioSegment, "export", _tracking_export)

        _run(tmp_path, DenoiseParams(dry_run=True))

        assert exported == []


class TestLiveRun:
    """The rewritten file carries the model's level, its tags and its length."""

    def test_the_decoded_level_drops_by_the_measured_attenuation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch, gain=0.5)
        source = _tone(tmp_path / "tone.wav")
        before = AudioSegment.from_wav(str(source))
        _write_artist(source, "Original Artist")

        completion, display = _run(tmp_path, DenoiseParams())

        after = AudioSegment.from_wav(str(source))
        assert completion["succeeded"] == 1
        assert display[0].startswith("[FIXED] tone.wav")
        assert after.rms == pytest.approx(before.rms / 2, rel=0.02)
        assert len(after) == len(before)
        assert after.frame_rate == before.frame_rate
        assert after.channels == before.channels
        assert _read_artist(source) == "Original Artist"

    def test_a_file_the_model_leaves_alone_is_not_rewritten(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch, gain=1.0)
        source = _tone(tmp_path / "tone.wav")
        digest = _sha256(source)

        completion, display = _run(tmp_path, DenoiseParams())

        assert completion["skipped"] == 1
        assert completion["succeeded"] == 0
        assert display[0].startswith("[SKIP] tone.wav")
        assert _sha256(source) == digest

    def test_a_broken_file_is_counted_and_does_not_stop_the_batch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch)
        _tone(tmp_path / "good.wav")
        (tmp_path / "bad.wav").write_bytes(b"this is not a wav file")

        completion, display = _run(tmp_path, DenoiseParams())

        assert completion["total"] == 2
        assert completion["errors"] == 1
        assert completion["succeeded"] == 1
        assert any(line.startswith("[ERROR] bad.wav") for line in display)


class TestFatalCases:
    """Configuration and dependency failures stop the run before any file."""

    def test_missing_extra_raises_before_touching_a_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "pyrnnoise", None)
        source = _tone(tmp_path / "tone.wav")
        digest = _sha256(source)

        with pytest.raises(AudioMissingDependencyError):
            run_ml_denoise(
                str(tmp_path),
                DenoiseParams(),
                *_slots(),
                lambda **kw: None,
                lambda **kw: None,
                lambda msg: None,
            )

        assert _sha256(source) == digest

    def test_an_invalid_amount_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch)

        with pytest.raises(ValueError) as caught:
            run_ml_denoise(
                str(tmp_path),
                DenoiseParams(amount=0.0),
                *_slots(),
                lambda **kw: None,
                lambda **kw: None,
                lambda msg: None,
            )

        assert "amount" in str(caught.value).lower()

    def test_an_empty_directory_reports_a_fatal_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch)
        errors: list[str] = []

        run_ml_denoise(
            str(tmp_path),
            DenoiseParams(),
            *_slots(),
            lambda **kw: None,
            lambda **kw: None,
            errors.append,
        )

        assert errors
        assert "No supported audio files" in errors[0]


class TestUndo:
    """A live run is undoable byte for byte, audio and tags together."""

    def test_revert_restores_the_original_bytes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from audio_suite_shared.batch_undo import BatchUndoLog, active_batch

        _install_fake_rnnoise(monkeypatch)
        source = _tone(tmp_path / "tone.wav")
        _write_artist(source, "Original Artist")
        original_digest = _sha256(source)
        undo_db = tmp_path / "undo.db"

        with active_batch("ml_denoiser", "tag_edit", db_path=str(undo_db)):
            completion, _display = _run(tmp_path, DenoiseParams())
        assert completion["succeeded"] == 1

        with BatchUndoLog(db_path=str(undo_db)) as log:
            batches = log.list_batches(limit=10)
            assert len(batches) == 1
            records = log.get_batch_records(batches[0].batch_id)
            assert len(records) == 1
            assert records[0].file_path == str(source)
            assert records[0].operation == file_processor.TAG_OPERATION
            assert records[0].file_action == "overwrite"

        # The repair really changed the file, and kept its tags.
        assert _sha256(source) != original_digest
        assert _read_artist(source) == "Original Artist"

        with BatchUndoLog(db_path=str(undo_db)) as log:
            result = log.revert_batch(batches[0].batch_id)

        assert result.reverted == 1
        assert _sha256(source) == original_digest

"""Tests for ``stem_separator.core.file_processor``.

A stem separation is one of the suite's most expensive operations, so the
tests drive the real processor with the model seam patched and assert the files
that land on disk: how many, where, at what level, and that a dry run wrote
none of them.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
"""

from __future__ import annotations

import logging
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from pydub import AudioSegment

from audio_suite_shared.exceptions import (
    AudioFormatError,
    AudioMissingDependencyError,
)
from stem_separator.core import demucs_engine, file_processor
from stem_separator.core.models import (
    MIX_FILENAME,
    MODEL_SAMPLE_RATE,
    STEM_NAMES,
    SeparatedTrack,
    StemSeparationParams,
)

SR = MODEL_SAMPLE_RATE
SAMPLES = SR // 4


def _source(path: Path, seconds: float = 0.25) -> Path:
    """Write a short stereo WAV the processor can discover."""
    path.parent.mkdir(parents=True, exist_ok=True)
    AudioSegment.silent(duration=int(seconds * 1000), frame_rate=SR).export(
        str(path), format="wav"
    )
    return path


def _track(*, amplitude: float = 0.1) -> SeparatedTrack:
    """Return four distinguishable stems."""
    return SeparatedTrack(
        sample_rate=SR,
        stems={
            name: np.full((2, SAMPLES), amplitude * (index + 1), dtype=np.float32)
            for index, name in enumerate(STEM_NAMES)
        },
    )


def _run(
    directory: Path,
    params: StemSeparationParams,
    *,
    patch_model: bool = True,
    patch_require: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Drive the real processor and return completion, progress and errors.

    ``patch_require=False`` leaves ``require_demucs`` alone so a test can prove
    the dry-run path never needs it, or supply its own failing stand-in.
    """
    completions: list[dict[str, Any]] = []
    progress: list[dict[str, Any]] = []
    errors: list[str] = []

    slots = [MagicMock() for _ in range(file_processor.MAX_WORKERS)]
    queue: Queue[int] = Queue()
    for index in range(file_processor.MAX_WORKERS):
        queue.put(index)

    def _on_complete(**kwargs: Any) -> None:
        completions.append(kwargs)

    def _on_progress(**kwargs: Any) -> None:
        progress.append(kwargs)

    with pytest.MonkeyPatch.context() as patch:
        if patch_require:
            patch.setattr(demucs_engine, "require_demucs", lambda: None)
        if patch_model:
            patch.setattr(file_processor, "separate", lambda *_a, **_k: _track())
        file_processor.run_stem_separation(
            str(directory),
            params,
            slots,
            queue,
            _on_progress,
            _on_complete,
            errors.append,
        )

    return completions[0], progress, errors


class TestDryRun:
    """A dry run reports the plan and writes nothing."""

    def test_no_stem_folder_is_created(self, tmp_path: Path) -> None:
        _source(tmp_path / "song.wav")
        out = tmp_path / "out"

        completion, progress, _errors = _run(
            tmp_path,
            StemSeparationParams(output_dir=str(out), dry_run=True),
            patch_model=False,
            patch_require=False,
        )

        assert completion["total"] == 1
        assert completion["separated"] == 1
        assert completion["files_written"] == 0
        assert out.is_dir(), "the output root is created so the run can check it"
        assert not (out / "song").exists(), "a dry run created a stem folder"
        assert progress and "would write 4 stems" in progress[0]["display_text"]

    def test_dry_run_does_not_need_demucs(self, tmp_path: Path) -> None:
        """The report must work on a machine without the ML extra."""
        _source(tmp_path / "song.wav")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                demucs_engine,
                "require_demucs",
                lambda: pytest.fail("a dry run required the model"),
            )
            completion, _progress, _errors = _run(
                tmp_path,
                StemSeparationParams(output_dir=str(tmp_path / "out"), dry_run=True),
                patch_model=False,
                patch_require=False,
            )

        assert completion["separated"] == 1


class TestLiveRun:
    """The written stems are the model's output, at the declared level."""

    def test_every_selected_stem_and_the_mix_are_written(self, tmp_path: Path) -> None:
        _source(tmp_path / "song.wav")
        out = tmp_path / "out"

        completion, progress, errors = _run(
            tmp_path,
            StemSeparationParams(
                output_dir=str(out),
                device="cpu",
                write_mix=True,
            ),
        )

        folder = out / "song"
        for stem in STEM_NAMES:
            assert (folder / f"{stem}.wav").is_file(), stem
        assert (folder / MIX_FILENAME).is_file()
        assert completion["separated"] == 1
        assert completion["files_written"] == 5
        assert completion["device"] == "CPU"
        assert progress[0]["display_text"].startswith("[SEPARATED]")
        assert not errors

        vocals = AudioSegment.from_wav(str(folder / "vocals.wav"))
        assert vocals.frame_rate == SR
        assert len(vocals) == pytest.approx(SAMPLES / SR * 1000, abs=2)
        # 0.1 amplitude at 16-bit, decoded back: the level is the model's.
        assert vocals.rms == pytest.approx(0.1 * 32767, rel=0.01)

        mixed = AudioSegment.from_wav(str(folder / MIX_FILENAME))
        # 0.1 + 0.2 + 0.3 + 0.4 = 1.0, clipped at full scale.
        assert mixed.rms == pytest.approx(32767, rel=0.001)

    def test_a_subset_is_written_without_a_mix(self, tmp_path: Path) -> None:
        _source(tmp_path / "song.wav")
        out = tmp_path / "out"

        completion, _progress, _errors = _run(
            tmp_path,
            StemSeparationParams(
                output_dir=str(out),
                device="cpu",
                stems=("vocals", "bass"),
            ),
        )

        assert sorted(p.name for p in (out / "song").iterdir()) == [
            "bass.wav",
            "vocals.wav",
        ]
        assert completion["files_written"] == 2

    def test_two_sources_with_one_stem_name_do_not_overwrite(
        self, tmp_path: Path
    ) -> None:
        """song.wav and song.mp3 both target out/song; the second is skipped."""
        _source(tmp_path / "song.wav")
        (tmp_path / "song.mp3").write_bytes(b"")
        out = tmp_path / "out"

        completion, _progress, _errors = _run(
            tmp_path,
            StemSeparationParams(output_dir=str(out), device="cpu"),
        )

        assert completion["separated"] == 1
        assert completion["skipped"] == 1
        assert completion["processed"] == 2
        assert sorted(p.name for p in (out / "song").iterdir()) == [
            "bass.wav",
            "drums.wav",
            "other.wav",
            "vocals.wav",
        ]

    def test_a_failing_file_is_an_error_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        _source(tmp_path / "song.wav")
        out = tmp_path / "out"

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(demucs_engine, "require_demucs", lambda: None)
            patch.setattr(
                file_processor,
                "separate",
                MagicMock(side_effect=RuntimeError("model exploded")),
            )
            completion, progress, _errors = _run(
                tmp_path,
                StemSeparationParams(output_dir=str(out), device="cpu"),
                patch_model=False,
            )

        assert completion["errors"] == 1
        assert completion["separated"] == 0
        assert not (out / "song").exists()
        assert progress[0]["display_text"].startswith("[ERROR]")


class TestFatalCases:
    """Configuration and dependency failures stop the run before any file."""

    def test_missing_output_directory_is_refused(self, tmp_path: Path) -> None:
        _source(tmp_path / "song.wav")

        # The @handle_audio_errors decorator maps the ValueError to the suite's
        # format error, which is the type a caller (and the CLI) sees.
        with pytest.raises(AudioFormatError) as caught:
            _run(
                tmp_path,
                StemSeparationParams(output_dir="", dry_run=True),
                patch_model=False,
            )

        assert "output directory" in str(caught.value).lower()

    def test_missing_demucs_stops_a_live_run(self, tmp_path: Path) -> None:
        _source(tmp_path / "song.wav")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                demucs_engine,
                "require_demucs",
                MagicMock(side_effect=AudioMissingDependencyError("no demucs")),
            )
            with pytest.raises(AudioMissingDependencyError):
                _run(
                    tmp_path,
                    StemSeparationParams(
                        output_dir=str(tmp_path / "out"), device="cpu"
                    ),
                    patch_model=False,
                    patch_require=False,
                )

    def test_the_log_starts_with_the_run_line(self, tmp_path: Path) -> None:
        _source(tmp_path / "song.wav")

        completion, _progress, _errors = _run(
            tmp_path,
            StemSeparationParams(
                output_dir=str(tmp_path / "out"), device="cpu", dry_run=True
            ),
            patch_model=False,
        )

        first = completion["log_entries"][0]
        assert "Dry Run" in first
        assert "CPU" in first

    def test_the_run_logs_the_device_and_its_reason(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Item 6.3 asks the device status to be *logged*, and the reason is
        the half that makes a CPU fallback diagnosable.  ``device="cpu"`` keeps
        the assertion independent of whether torch is installed on the host."""
        _source(tmp_path / "song.wav")

        with caplog.at_level(logging.INFO, logger=file_processor.__name__):
            _run(
                tmp_path,
                StemSeparationParams(
                    output_dir=str(tmp_path / "out"), device="cpu", dry_run=True
                ),
                patch_model=False,
            )

        messages = [record.getMessage() for record in caplog.records]
        line = next(m for m in messages if "Stem separation device" in m)
        assert "CPU" in line
        assert "turned off" in line

    def test_an_empty_directory_completes_with_zeroes(self, tmp_path: Path) -> None:
        completion, _progress, errors = _run(
            tmp_path,
            StemSeparationParams(
                output_dir=str(tmp_path / "out"), device="cpu", dry_run=True
            ),
            patch_model=False,
        )

        assert completion["total"] == 0
        assert completion["processed"] == 0
        assert not errors

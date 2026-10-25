"""CLI contract for BPM Analyzer's JSON summary.

Changed in 1.4.0: the ``--json`` payload now carries top-level
``skipped_files`` and ``error_files`` lists so a script can tell a beatless
file from a corrupt one, and see the periodicity score or error type behind
each outcome.
Changed in 2.1.4: the JSON helper asserts the R-06 exit status.  A run that
reports a per-file error exits 1, so ``_invoke_json`` takes the expected count
and derives the status from it instead of always demanding 0 (PLAN D9).
"""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from click.testing import CliRunner

from audio_suite_shared.cli_app import cli
from bpm_analyzer.core.bpm_detector import MIN_ONSET_PERIODICITY


def _write_pcm_wav(path: Path, samples: np.ndarray, sr: int = 22050) -> Path:
    """Write 16-bit mono PCM (values clipped to +/-1)."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())
    return path


def _write_noise(path: Path, seconds: float = 8.0, seed: int = 99) -> Path:
    rng = np.random.default_rng(seed)
    return _write_pcm_wav(path, 0.3 * rng.standard_normal(int(22050 * seconds)))


def _write_clicks(path: Path, bpm: float = 120.0, seconds: float = 8.0) -> Path:
    sr = 22050
    n = int(sr * seconds)
    signal = np.zeros(n)
    click_len = max(4, int(0.004 * sr))
    decay = np.exp(-np.linspace(0.0, 8.0, click_len))
    carrier = np.sin(2 * np.pi * 1000.0 * np.arange(click_len) / sr)
    for start in (np.arange(int(bpm / 60.0 * seconds) + 1) / (bpm / 60.0) * sr).astype(
        int
    ):
        end = min(start + click_len, n)
        signal[start:end] += carrier[: end - start] * decay[: end - start]
    signal = 0.9 * signal / float(np.max(np.abs(signal)))
    return _write_pcm_wav(path, signal)


@pytest.fixture()
def mixed_dir(tmp_path: Path) -> Path:
    _write_noise(tmp_path / "noise.wav")
    _write_clicks(tmp_path / "beat.wav")
    return tmp_path


def _invoke_json(directory: Path, *, expect_errors: int = 0) -> dict[str, Any]:
    """Run the JSON path and return its payload.

    The exit status follows the error count the payload reports (R-06), so the
    expectation is a parameter: a clean run is 0, a run with per-file errors is
    1.  ``expect_errors`` is the count the caller already asserts, so the status
    and the count cannot disagree in one test.
    """
    result = CliRunner().invoke(
        cli,
        ["bpm", str(directory), "--dry", "--json", "--duration", "8"],
    )
    expected_status = 1 if expect_errors else 0
    assert result.exit_code == expected_status, result.output
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


class TestBpmJsonSkippedFiles:
    def test_skip_record_has_filename_reason_and_score(self, mixed_dir: Path) -> None:
        """The record is structured, top-level, and carries the real score."""
        payload = _invoke_json(mixed_dir)

        assert payload["processed"] == 2
        assert payload["skipped"] == 1
        assert payload["errors"] == 0
        assert payload["error_files"] == []
        assert "extra" not in payload
        records: list[dict[str, Any]] = payload["skipped_files"]
        assert isinstance(records, list)
        assert [record["filename"] for record in records] == ["noise.wav"]

        record = records[0]
        assert "No tempo detected" in record["reason"]
        score = record["onset_periodicity"]
        assert isinstance(score, float)
        assert 0.0 <= score < MIN_ONSET_PERIODICITY

    def test_clean_run_still_has_an_empty_list(self, tmp_path: Path) -> None:
        """Scripts can rely on the key existing even when nothing was skipped."""
        _write_clicks(tmp_path / "beat.wav")
        payload = _invoke_json(tmp_path)

        assert payload["skipped"] == 0
        assert payload["skipped_files"] == []
        assert payload["error_files"] == []

    def test_error_record_is_separate_from_skips(self, tmp_path: Path) -> None:
        """A corrupt file is reported as an error, never as a beatless skip."""
        _write_noise(tmp_path / "noise.wav")
        (tmp_path / "corrupt.mp3").write_bytes(b"not audio")

        payload = _invoke_json(tmp_path, expect_errors=1)

        assert payload["processed"] == 2
        assert payload["skipped"] == 1
        assert payload["errors"] == 1
        assert [record["filename"] for record in payload["skipped_files"]] == [
            "noise.wav"
        ]
        records: list[dict[str, Any]] = payload["error_files"]
        assert [record["filename"] for record in records] == ["corrupt.mp3"]
        assert records[0]["reason"]
        assert records[0]["error_type"] == "BPMDetectionError"

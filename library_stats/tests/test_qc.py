"""The QC pass measures a file, and agrees with FFmpeg about what it measured.

Changed in 2.7.0: new file - the QC / forensics metrics and their locks
(PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S7).

Every reference figure here comes from an independent ``ffmpeg`` invocation made
by the test itself, never from the probe the module uses: a test that compares a
module to its own input proves only that the plumbing is connected.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sf = pytest.importorskip("soundfile")

from audio_suite_shared.audio_probe import FFMPEG_EXECUTABLE  # noqa: E402

SAMPLERATE = 48000


def _write(path: Path, data: np.ndarray, samplerate: int = SAMPLERATE) -> Path:
    """Write float frames to a WAV file and return the path."""
    sf.write(str(path), data, samplerate, subtype="FLOAT")
    return path


def _sine(seconds: float, dbfs: float = -12.0) -> np.ndarray:
    """Return a mono sine at *dbfs* full scale."""
    t = np.arange(int(SAMPLERATE * seconds)) / SAMPLERATE
    amplitude = 10.0 ** (dbfs / 20.0)
    return (amplitude * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)


def _ffmpeg_summary(path: Path) -> str:
    """Return FFmpeg's own ebur128/astats output for *path*."""
    result = subprocess.run(
        [
            FFMPEG_EXECUTABLE,
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "ebur128=peak=true,astats=metadata=1:reset=0",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr[-800:]
    return result.stderr


def _figure(pattern: str, text: str) -> float:
    """Return the last number *pattern* matched in *text*."""
    found = re.findall(pattern, text, re.MULTILINE)
    assert found, f"no match for {pattern!r} in the FFmpeg output"
    return float(found[-1])


class TestAgreementWithFfmpeg:
    """The reported numbers are FFmpeg's, within the plan's tolerances."""

    def test_loudness_and_true_peak_match(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        path = _write(tmp_path / "tone.wav", np.stack([_sine(4.0), _sine(4.0)], axis=1))
        reference = _ffmpeg_summary(path)

        metrics = measure_file(str(path))

        integrated = _figure(r"^\s*I:\s+([-+]?\d+(?:\.\d+)?)\s+LUFS", reference)
        true_peak = _figure(r"^\s*Peak:\s+([-+]?\d+(?:\.\d+)?)\s+dBFS", reference)
        lra = _figure(r"^\s*LRA:\s+([-+]?\d+(?:\.\d+)?)\s+LU", reference)
        assert metrics.integrated_lufs == pytest.approx(integrated, abs=0.1), (
            f"module said {metrics.integrated_lufs} LUFS, FFmpeg said {integrated}"
        )
        assert metrics.true_peak_dbtp == pytest.approx(true_peak, abs=0.2), (
            f"module said {metrics.true_peak_dbtp} dBTP, FFmpeg said {true_peak}"
        )
        assert metrics.lra_lu == pytest.approx(lra, abs=0.5), (
            f"module said {metrics.lra_lu} LU, FFmpeg said {lra}"
        )

    def test_dc_offset_matches(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        left = _sine(2.0) + 0.05
        right = _sine(2.0)
        path = _write(tmp_path / "offset.wav", np.stack([left, right], axis=1))
        reference = _ffmpeg_summary(path)

        metrics = measure_file(str(path))

        # The per-channel block, not the overall one: FFmpeg's overall DC offset
        # describes a single channel's block there, and a test that reads it
        # would pass for a module that reported the same value twice.
        blocks = reference.split("] Overall", 1)[0].split("Channel: ")[1:]
        assert len(blocks) >= 2, "the reference run printed no per-channel blocks"
        expected = _figure(r"DC offset:\s+([-+]?\d+(?:\.\d+)?)", blocks[0])
        assert metrics.dc_offset[0] == pytest.approx(expected, abs=1e-4)
        # The DC sits on the left channel only: a per-channel figure that
        # averaged the two would report half of it.
        assert abs(metrics.dc_offset[1]) < 1e-3

    def test_sample_peak_and_crest_are_the_probes(self, tmp_path: Path) -> None:
        from audio_suite_shared.audio_probe import measure_levels
        from library_stats.core.qc import measure_file

        path = _write(tmp_path / "tone.wav", _sine(2.0))
        probe = measure_levels(str(path))

        metrics = measure_file(str(path))

        assert metrics.sample_peak_dbfs == pytest.approx(probe.sample_peak_dbfs)
        assert metrics.crest_factor_db == pytest.approx(probe.crest_factor_db)


class TestLoudnessRange:
    """``0.0`` is a measurement, ``None`` is its absence, and length decides.

    FFmpeg prints ``LRA: 0.0`` both for a stream too short to gate and for one
    that is genuinely flat.  Reporting the first as ``0.0`` would put "perfectly
    flat dynamic range" in front of a user who has no measurement at all.
    """

    def test_a_short_file_reports_no_range(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        path = _write(tmp_path / "brief.wav", _sine(1.0))

        metrics = measure_file(str(path))

        assert metrics.lra_lu is None
        assert "3.0 s" in metrics.lra_note

    def test_a_long_flat_file_keeps_its_zero(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        path = _write(tmp_path / "flat.wav", _sine(4.0))

        metrics = measure_file(str(path))

        assert metrics.lra_lu == pytest.approx(0.0, abs=1e-6)
        assert metrics.lra_note == "", "a measured zero needs no explanation"


class TestDefaultWorkers:
    """Half the cores, at least one, never past the measured knee."""

    @pytest.mark.parametrize(
        ("cores", "expected"),
        [(1, 1), (2, 1), (3, 1), (4, 2), (8, 4), (16, 8), (20, 8), (64, 8)],
    )
    def test_it_halves_the_cores_inside_the_cap(
        self, cores: int, expected: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from library_stats.core.qc import default_qc_workers

        monkeypatch.setattr("os.cpu_count", lambda: cores)

        assert default_qc_workers() == expected

    def test_an_unknown_core_count_falls_back_to_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from library_stats.core.qc import default_qc_workers

        monkeypatch.setattr("os.cpu_count", lambda: None)

        assert default_qc_workers() == 1

    def test_the_cap_is_eight(self) -> None:
        from library_stats.core.qc import QC_MAX_WORKERS

        assert QC_MAX_WORKERS == 8


class TestQcSummary:
    """One count and one ranking, so three reports cannot disagree."""

    def _metric(
        self,
        name: str,
        *,
        clipped: int = 0,
        dropouts: int = 0,
        phase: float = 0.9,
        crest: float = 10.0,
        error: str = "",
    ) -> Any:
        from library_stats.core.qc import QcMetrics

        return QcMetrics(
            file=name,
            crest_factor_db=None if error else crest,
            phase_correlation=None if error else phase,
            clipped_samples=None if error else clipped,
            dropouts=None if error else dropouts,
            qc_error=error,
        )

    def test_counts_split_measured_from_refused(self) -> None:
        from library_stats.core.qc import qc_summary

        summary = qc_summary(
            [
                self._metric("clean.flac"),
                self._metric("hot.flac", clipped=120),
                self._metric("gap.flac", dropouts=2),
                self._metric("broken.wav", error="unreadable"),
            ]
        )

        assert summary.total == 4
        assert summary.measured == 3
        assert summary.unmeasured == 1
        assert summary.clipped == 1
        assert summary.with_dropouts == 1
        assert not summary.clean

    def test_a_refusal_does_not_hide_a_clean_pass(self) -> None:
        from library_stats.core.qc import qc_summary

        summary = qc_summary(
            [self._metric("clean.flac"), self._metric("broken", error="x")]
        )

        assert not summary.clean, "an unmeasured file is not a clean result"
        assert qc_summary([self._metric("clean.flac")]).clean

    def test_the_ranking_is_the_offenders_ranking(self) -> None:
        from library_stats.core.qc import qc_summary, worst_offenders

        files = [
            self._metric("phase.flac", phase=-0.8),
            self._metric("hot.flac", clipped=4),
            self._metric("gap.flac", dropouts=3),
            self._metric("clean.flac"),
        ]

        assert qc_summary(files).offenders == worst_offenders(files)
        assert [item.file for item in qc_summary(files).offenders][:2] == [
            "hot.flac",
            "gap.flac",
        ]

    def test_the_limit_bounds_the_named_offenders(self) -> None:
        from library_stats.core.qc import qc_summary

        files = [self._metric(f"f{index}.flac", clipped=index) for index in range(1, 9)]

        assert len(qc_summary(files, limit=2).offenders) == 2
        assert qc_summary(files, limit=2).clipped == 8, "the counts are not limited"

    def test_the_dict_is_json_serialisable(self) -> None:
        from library_stats.core.qc import qc_summary

        payload = qc_summary([self._metric("hot.flac", clipped=7)]).as_dict()

        assert json.loads(json.dumps(payload)) == payload
        assert payload["worst_offenders"] == ["hot.flac"]


class TestDefectsAreCounted:
    """A deliberately damaged file reports the damage it was built with."""

    def test_clipped_samples_are_counted(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        data = _sine(2.0, dbfs=-6.0)
        clipped_at = [4000, 4001, 4002, 4003, 4004, 9000, 9001, 14000]
        data[clipped_at] = 1.0
        path = _write(tmp_path / "clipped.wav", data)

        metrics = measure_file(str(path))

        assert metrics.clipped_samples == len(clipped_at)

    def test_dropouts_are_counted(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        data = _sine(3.0, dbfs=-9.0)
        start = 12000
        gap = int(SAMPLERATE * 0.020)
        gaps = 3
        for index in range(gaps):
            begin = start + index * 40000
            data[begin : begin + gap] = 0.0
        path = _write(tmp_path / "dropouts.wav", data)

        metrics = measure_file(str(path))

        assert metrics.dropouts == gaps

    def test_pure_silence_is_one_dropout(self, tmp_path: Path) -> None:
        """Digital silence at the start is a gap, not a file with no gaps."""
        from library_stats.core.qc import measure_file

        silence = np.zeros(int(SAMPLERATE * 0.5), dtype=np.float32)
        path = _write(tmp_path / "silence.wav", np.concatenate([silence, _sine(1.0)]))

        metrics = measure_file(str(path))

        assert metrics.dropouts == 1


class TestPhaseCorrelation:
    """Stereo files get a coefficient; a mono file gets no number at all."""

    def test_identical_channels_are_plus_one(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        mono = _sine(1.0)
        path = _write(tmp_path / "identical.wav", np.stack([mono, mono], axis=1))

        metrics = measure_file(str(path))

        assert metrics.phase_correlation == pytest.approx(1.0, abs=0.01)

    def test_inverted_channels_are_minus_one(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        mono = _sine(1.0)
        path = _write(tmp_path / "inverted.wav", np.stack([mono, -mono], axis=1))

        metrics = measure_file(str(path))

        assert metrics.phase_correlation == pytest.approx(-1.0, abs=0.01)

    def test_mono_reports_no_number(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        path = _write(tmp_path / "mono.wav", _sine(1.0))

        metrics = measure_file(str(path))

        assert metrics.phase_correlation is None
        assert metrics.phase_note, "a mono file must say why the figure is absent"


class TestRefusals:
    """A file that cannot be measured is reported, never raised."""

    def test_unreadable_file_reports_the_reason(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        path = tmp_path / "notes.txt"
        path.write_text("this is not audio", encoding="utf-8")

        metrics = measure_file(str(path))

        assert metrics.qc_error, "a refused file must carry its reason"
        assert metrics.integrated_lufs is None

    def test_a_missing_file_reports_the_reason(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        metrics = measure_file(str(tmp_path / "absent.wav"))

        assert metrics.qc_error
        assert metrics.clipped_samples is None


def _encode(source: Path, target: Path, *codec: str) -> Path:
    """Encode *source* to *target* with FFmpeg, or skip where it cannot."""
    result = subprocess.run(
        [
            FFMPEG_EXECUTABLE,
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            *codec,
            str(target),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0 or not target.is_file():
        pytest.skip(
            f"FFmpeg cannot encode {target.suffix}: {result.stderr.strip()[:80]}"
        )
    return target


class TestFallbackDecode:
    """A container libsndfile cannot read keeps its sample-level figures."""

    def test_a_lossless_container_libsndfile_cannot_read_measures_exactly(
        self, tmp_path: Path
    ) -> None:
        """WavPack round-trips the samples, so the counts can be exact."""
        from library_stats.core.qc import measure_file

        mono = _sine(2.0, dbfs=-9.0)
        clipped_at = [4000, 4001, 4002, 9000, 9001]
        mono[clipped_at] = 1.0
        gap = int(SAMPLERATE * 0.020)
        mono[30000 : 30000 + gap] = 0.0
        source = _write(tmp_path / "damaged.wav", np.stack([mono, mono], axis=1))
        packaged = _encode(source, tmp_path / "damaged.wv", "-c:a", "wavpack")

        with pytest.raises(sf.LibsndfileError):
            sf.read(str(packaged))

        metrics = measure_file(str(packaged))

        assert metrics.qc_error == ""
        assert metrics.clipped_samples == len(clipped_at)
        assert metrics.dropouts == 1
        assert metrics.phase_correlation == pytest.approx(1.0, abs=0.01)

    def test_an_m4a_reports_the_three_sample_figures(self, tmp_path: Path) -> None:
        """The real-world case: AAC, which libsndfile cannot open at all."""
        from library_stats.core.qc import measure_file

        mono = _sine(2.0, dbfs=-12.0)
        source = _write(tmp_path / "track.wav", np.stack([mono, mono], axis=1))
        packaged = _encode(
            source, tmp_path / "track.m4a", "-c:a", "aac", "-b:a", "192k"
        )

        metrics = measure_file(str(packaged))

        assert metrics.qc_error == ""
        assert metrics.clipped_samples is not None
        assert metrics.dropouts is not None
        assert metrics.phase_correlation is not None
        assert metrics.phase_correlation == pytest.approx(1.0, abs=0.05)
        assert metrics.integrated_lufs is not None

    def test_a_readable_wav_never_reaches_the_fallback(self, tmp_path: Path) -> None:
        """The fallback is a fallback: a WAV is read by soundfile alone."""
        from library_stats.core import qc

        path = _write(tmp_path / "plain.wav", np.stack([_sine(1.0)] * 2, axis=1))

        def refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("a readable WAV must not go through FFmpeg")

        monkeypatched = pytest.MonkeyPatch()
        monkeypatched.setattr(qc, "decode_samples", refuse)
        try:
            metrics = qc.measure_file(str(path))
        finally:
            monkeypatched.undo()

        assert metrics.qc_error == ""
        assert metrics.clipped_samples is not None

    def test_both_decoders_failing_keeps_the_probe_figures(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A refused container costs three columns, never the whole row."""
        from audio_suite_shared.exceptions import AudioFormatError
        from library_stats.core import qc

        mono = _sine(2.0, dbfs=-12.0)
        source = _write(tmp_path / "track.wav", np.stack([mono, mono], axis=1))
        packaged = _encode(
            source, tmp_path / "track.m4a", "-c:a", "aac", "-b:a", "192k"
        )

        def refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise AudioFormatError("FFmpeg decoded no audio")

        monkeypatch.setattr(qc, "decode_samples", refuse)
        metrics = qc.measure_file(str(packaged))

        assert metrics.qc_error == ""
        assert metrics.integrated_lufs is not None
        assert metrics.clipped_samples is None
        assert metrics.dropouts is None
        assert metrics.phase_correlation is None
        assert metrics.phase_note == qc.PHASE_UNAVAILABLE


class TestReadOnly:
    """The pass measures; it writes nothing and opens nothing for append."""

    def test_the_file_is_untouched(self, tmp_path: Path) -> None:
        from library_stats.core.qc import measure_file

        path = _write(tmp_path / "tone.wav", _sine(1.0))
        before = os.stat(path)

        measure_file(str(path))

        after = os.stat(path)
        assert after.st_mtime_ns == before.st_mtime_ns
        assert after.st_size == before.st_size

    def test_the_module_runs_no_process_of_its_own(self) -> None:
        """Every FFmpeg call goes through the shared probe, not this module."""
        source = Path("library_stats/core/qc.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert "subprocess" not in imported
        assert not any("secure_subprocess" in name for name in imported)

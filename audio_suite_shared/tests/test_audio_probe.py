"""test_audio_probe.py — the suite's one FFmpeg measurement path.

Changed in 2.4.2: new lock for ``audio_suite_shared.audio_probe``
(``PLAN_2026-11-03_2.4.2_audio_foundation.md`` WP-5.1, extended in WP-5.2 with
the ``loudnorm`` figures the Audio Normalizer feeds its second pass and the
achieved-peak parser it reports).

Every assertion here decodes a real file and measures it.  A test that re-read
a value the probe parsed from its own output would pass with FFmpeg given the
wrong arguments, so the expected numbers come from the signal that was written:
0.5 of full scale is -6.02 dBFS, and a pure sine's crest factor is 3.01 dB.

Changed in 2.7.0: locks ``measure_forensics`` - the per-channel DC offsets the
probe now keeps instead of discarding with the per-channel ``astats`` blocks
(PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S7).
"""

from __future__ import annotations

import dataclasses
import math
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from audio_suite_shared import audio_probe
from audio_suite_shared.exceptions import AudioFormatError

SAMPLE_RATE = 44100
REPO_ROOT = Path(__file__).resolve().parents[2]

#: A real read-only container (APE has no encoder: readable, never writable).
READ_ONLY_FIXTURE = REPO_ROOT / "tests" / "data" / "mac-390-hdr.ape"

HALF_SCALE_PEAK_DBFS = 20.0 * math.log10(0.5)
SINE_CREST_FACTOR_DB = 3.0103


def write_tone(
    path: Path,
    *,
    seconds: float = 1.0,
    amplitude: float = 0.5,
    frequency: float = 440.0,
    channels: int = 2,
    sample_width: int = 2,
) -> str:
    """Write a sine tone as a real PCM WAV file.

    Args:
        path: Destination path; its suffix does not affect the PCM content.
        seconds: Length in seconds.
        amplitude: Peak as a fraction of full scale (0.5 is -6.02 dBFS).
        frequency: Tone frequency in Hz.
        channels: Channel count.
        sample_width: Bytes per sample.

    Returns:
        The path as a string, for convenient use in parametrised fixtures.
    """
    assert sample_width in (1, 2, 3, 4)
    frames = int(SAMPLE_RATE * seconds)
    full_scale = 2 ** (8 * sample_width - 1) - 1
    peak = int(amplitude * full_scale)
    frames_bytes = bytearray()
    for index in range(frames):
        sample = int(peak * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE))
        frames_bytes += sample.to_bytes(sample_width, "little", signed=True) * channels
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(frames_bytes))
    return str(path)


def write_dc_tone(
    path: Path,
    *,
    seconds: float = 1.0,
    amplitude: float = 0.5,
    frequency: float = 440.0,
    dc_left: float = 0.05,
    sample_width: int = 2,
) -> str:
    """Write a stereo tone with a DC offset on the left channel only.

    A whole-file average hides this signal: the right channel has none, so a
    figure that mixed the two would report half of ``dc_left`` and a figure read
    from the wrong block would report zero.

    Args:
        path: Destination path.
        seconds: Length in seconds.
        amplitude: Sine peak as a fraction of full scale.
        frequency: Tone frequency in Hz.
        dc_left: Offset added to every left-channel sample.
        sample_width: Bytes per sample.

    Returns:
        The path as a string.
    """
    frames = int(SAMPLE_RATE * seconds)
    full_scale = 2 ** (8 * sample_width - 1) - 1
    frames_bytes = bytearray()
    for index in range(frames):
        wave_value = amplitude * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE)
        left = int(round((wave_value + dc_left) * full_scale))
        right = int(round(wave_value * full_scale))
        frames_bytes += left.to_bytes(sample_width, "little", signed=True)
        frames_bytes += right.to_bytes(sample_width, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(sample_width)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(frames_bytes))
    return str(path)


@pytest.fixture()
def tone(tmp_path: Path) -> str:
    """A 1-second stereo 440 Hz tone at half scale."""
    return write_tone(tmp_path / "tone.wav")


class TestDataclassContracts:
    """The shapes the plan fixes, so a caller can rely on them."""

    def test_stream_info_is_frozen(self) -> None:
        info = audio_probe.StreamInfo(
            container="wav",
            codec="pcm_s16le",
            sample_rate=44100,
            channels=2,
            bit_depth=16,
            duration_sec=1.0,
            bitrate_kbps=1411,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.codec = "mp3"  # type: ignore[misc]

    def test_level_metrics_fields(self) -> None:
        names = {field.name for field in dataclasses.fields(audio_probe.LevelMetrics)}
        assert names == {"sample_peak_dbfs", "true_peak_dbtp", "crest_factor_db"}

    def test_loudness_metrics_fields(self) -> None:
        names = {
            field.name for field in dataclasses.fields(audio_probe.LoudnessMetrics)
        }
        assert names == {
            "integrated_lufs",
            "loudness_range_lu",
            "true_peak_dbtp",
            "threshold_lufs",
            "duration_sec",
        }

    def test_peak_and_range_are_optional_because_ffmpeg_may_omit_them(self) -> None:
        """A summary without a true-peak or LRA line is not a failure.

        ``ebur128`` prints the peak and range sections it measured; a stream it
        could not gate prints neither.  Reporting ``None`` keeps the absence
        visible instead of fabricating a plausible zero.
        """
        metrics = audio_probe.LoudnessMetrics(
            integrated_lufs=-18.2,
            loudness_range_lu=None,
            true_peak_dbtp=None,
            threshold_lufs=None,
            duration_sec=12.34,
        )
        assert metrics.true_peak_dbtp is None


@pytest.mark.integration
class TestProbeStream:
    def test_reads_the_real_stream_description(self, tone: str) -> None:
        info = audio_probe.probe_stream(tone)
        assert info.container == "wav"
        assert info.codec == "pcm_s16le"
        assert info.sample_rate == SAMPLE_RATE
        assert info.channels == 2
        assert info.bit_depth == 16
        assert info.duration_sec == pytest.approx(1.0, abs=0.01)
        assert info.bitrate_kbps > 0

    def test_refuses_an_extension_the_matrix_cannot_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Refusal names the reason and never reaches FFmpeg."""
        unsupported = write_tone(tmp_path / "song.webm")

        def _must_not_spawn(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("the probe spawned FFmpeg for a refused container")

        monkeypatch.setattr(audio_probe, "run_secure_subprocess", _must_not_spawn)
        with pytest.raises(AudioFormatError) as excinfo:
            audio_probe.probe_stream(unsupported)
        assert ".webm" in excinfo.value.message
        assert "not a container the suite can read" in excinfo.value.message


@pytest.mark.integration
class TestMeasureLevels:
    def test_measures_the_signal_that_was_written(self, tone: str) -> None:
        levels = audio_probe.measure_levels(tone)
        assert levels.sample_peak_dbfs == pytest.approx(HALF_SCALE_PEAK_DBFS, abs=0.15)
        assert levels.crest_factor_db == pytest.approx(SINE_CREST_FACTOR_DB, abs=0.15)
        assert levels.true_peak_dbtp == pytest.approx(levels.sample_peak_dbfs, abs=0.5)

    def test_a_quieter_tone_measures_quieter(self, tmp_path: Path) -> None:
        quiet = write_tone(tmp_path / "quiet.wav", amplitude=0.05)
        levels = audio_probe.measure_levels(quiet)
        assert levels.sample_peak_dbfs == pytest.approx(
            20.0 * math.log10(0.05), abs=0.2
        )


class TestMeasureForensics:
    """The one pass a QC report reads: per channel, not per file."""

    def test_one_channel_dc_is_reported_on_that_channel(self, tmp_path: Path) -> None:
        path = write_dc_tone(tmp_path / "dc.wav")

        forensic = audio_probe.measure_forensics(path)

        assert len(forensic.dc_offset) == 2, "one offset per channel"
        assert len(forensic.channel_peaks_dbfs) == 2
        assert forensic.dc_offset[0] == pytest.approx(0.05, abs=1e-3)
        assert abs(forensic.dc_offset[1]) < 1e-3, (
            f"the clean channel reported {forensic.dc_offset[1]}, so the per-channel "
            "blocks are not being read in order"
        )

    def test_a_mono_file_reports_one_channel(self, tmp_path: Path) -> None:
        path = write_tone(tmp_path / "mono.wav", channels=1)

        forensic = audio_probe.measure_forensics(path)

        assert len(forensic.dc_offset) == 1
        assert forensic.dc_offset[0] == pytest.approx(0.0, abs=1e-3)

    def test_loudness_and_levels_agree_with_the_single_question_calls(
        self, tone: str
    ) -> None:
        """One pass reports what the two narrower calls report."""
        forensic = audio_probe.measure_forensics(tone)
        levels = audio_probe.measure_levels(tone)
        loudness = audio_probe.measure_loudness(tone)

        assert forensic.sample_peak_dbfs == pytest.approx(
            levels.sample_peak_dbfs, abs=0.01
        )
        assert forensic.crest_factor_db == pytest.approx(
            levels.crest_factor_db, abs=0.01
        )
        assert forensic.integrated_lufs == pytest.approx(
            loudness.integrated_lufs, abs=0.01
        )
        assert forensic.true_peak_dbtp == pytest.approx(levels.true_peak_dbtp, abs=0.01)

    def test_a_short_file_reports_the_zero_range_ffmpeg_prints(
        self, tmp_path: Path
    ) -> None:
        """A stream too short to gate gets FFmpeg's ``0.0`` LU, not ``None``.

        ``None`` means the summary carried no range line at all, which is a
        different thing from a range FFmpeg measured as zero: passing ``0.0``
        through is what the probe does, so a consumer that wants "no usable
        range" has to decide that itself rather than reading ``None``.
        """
        path = write_tone(tmp_path / "brief.wav", seconds=0.1)

        forensic = audio_probe.measure_forensics(path)

        assert forensic.integrated_lufs <= -70.0, (
            "a 0.1 s tone measures at the gate floor"
        )
        assert forensic.loudness_range_lu == pytest.approx(0.0, abs=1e-6)

    def test_an_unreadable_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "notes.txt"
        path.write_text("not audio", encoding="utf-8")

        with pytest.raises(AudioFormatError):
            audio_probe.measure_forensics(str(path))


@pytest.mark.integration
class TestMeasureLoudness:
    def test_reports_integrated_loudness_and_duration(self, tone: str) -> None:
        metrics = audio_probe.measure_loudness(tone)
        assert metrics.integrated_lufs == pytest.approx(-6.7, abs=0.5)
        assert metrics.duration_sec == pytest.approx(1.0, abs=0.01)
        assert metrics.true_peak_dbtp is not None
        assert metrics.loudness_range_lu is not None

    def test_the_loudnorm_chain_measures_the_same_signal(self, tone: str) -> None:
        """``target=`` selects loudnorm, which is the normaliser's own chain."""
        ebur128 = audio_probe.measure_loudness(tone)
        loudnorm = audio_probe.measure_loudness(tone, target=-16.0)
        assert loudnorm.integrated_lufs == pytest.approx(
            ebur128.integrated_lufs, abs=0.1
        )


#: One ``loudnorm`` analysis block, as FFmpeg prints it (two decimals, strings).
MOCK_ANALYSIS_BLOCK = (
    "[Parsed_loudnorm_0 @ 0x1] {\n"
    '    "input_i" : "-18.00",\n'
    '    "input_tp" : "-1.50",\n'
    '    "input_lra" : "7.00",\n'
    '    "input_thresh" : "-28.00",\n'
    '    "target_offset" : "-0.25"\n'
    "}\n"
)


def _mock_analysis(monkeypatch: pytest.MonkeyPatch, stderr: str) -> list[list[str]]:
    """Replace the subprocess seam with one canned pass; return its calls."""
    calls: list[list[str]] = []

    def _fake_run(executable: str, args: list[str], **_kwargs: Any) -> Any:
        calls.append([executable, *args])
        return SimpleNamespace(returncode=0, stdout="", stderr=stderr)

    monkeypatch.setattr(audio_probe, "run_secure_subprocess", _fake_run)
    return calls


class TestLoudnormInputs:
    """The normaliser's raw figures: one pass, five keys, absence as ``None``."""

    def test_reads_every_figure_the_second_pass_needs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = write_tone(tmp_path / "tone.wav")
        _mock_analysis(monkeypatch, MOCK_ANALYSIS_BLOCK)
        figures = audio_probe.loudnorm_inputs(path, target=-16.0)
        assert figures == {
            "input_i": -18.0,
            "input_tp": -1.5,
            "input_lra": 7.0,
            "input_thresh": -28.0,
            "target_offset": -0.25,
        }

    def test_the_chain_carries_the_callers_targets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = write_tone(tmp_path / "tone.wav")
        calls = _mock_analysis(monkeypatch, MOCK_ANALYSIS_BLOCK)
        audio_probe.loudnorm_inputs(path, target=-14.0, true_peak=-1.0, lra=7)
        assert calls[0][calls[0].index("-af") + 1] == (
            "loudnorm=I=-14.0:TP=-1.0:LRA=7:print_format=json"
        )

    def test_one_pass_per_measurement(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = write_tone(tmp_path / "tone.wav")
        calls = _mock_analysis(monkeypatch, MOCK_ANALYSIS_BLOCK)
        audio_probe.loudnorm_inputs(path, target=-16.0)
        assert len(calls) == 1

    def test_no_analysis_block_is_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = write_tone(tmp_path / "tone.wav")
        _mock_analysis(monkeypatch, "no json here")
        assert audio_probe.loudnorm_inputs(path, target=-16.0) is None

    def test_a_non_loudnorm_block_is_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = write_tone(tmp_path / "tone.wav")
        _mock_analysis(monkeypatch, '{"codec_name" : "mp3"}')
        assert audio_probe.loudnorm_inputs(path, target=-16.0) is None

    def test_a_non_finite_figure_is_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = write_tone(tmp_path / "tone.wav")
        _mock_analysis(
            monkeypatch,
            '{"input_i" : "-inf", "input_tp" : "-inf", "input_lra" : "0.00",'
            ' "input_thresh" : "-inf", "target_offset" : "0.00"}',
        )
        figures = audio_probe.loudnorm_inputs(path, target=-16.0)
        assert figures is not None
        assert figures["input_i"] is None
        assert figures["input_tp"] is None
        assert figures["input_lra"] == 0.0


@pytest.mark.integration
class TestLoudnormInputsOnRealAudio:
    def test_the_figures_match_the_targeted_measurement(self, tone: str) -> None:
        """The raw block and ``measure_loudness(target=...)`` are one pass."""
        figures = audio_probe.loudnorm_inputs(tone, target=-16.0)
        metrics = audio_probe.measure_loudness(tone, target=-16.0)
        assert figures is not None
        assert figures["input_i"] == pytest.approx(metrics.integrated_lufs, abs=0.01)
        assert figures["input_tp"] == pytest.approx(
            metrics.true_peak_dbtp or 0.0, abs=0.01
        )
        assert figures["input_lra"] == pytest.approx(
            metrics.loudness_range_lu or 0.0, abs=0.01
        )


class TestAchievedTruePeak:
    """The second pass's own peak: two printed forms, one parser."""

    def test_reads_the_summary_line(self) -> None:
        assert audio_probe.achieved_true_peak(
            "Input True Peak:      -0.9 dBTP\nOutput True Peak:     -1.3 dBTP\n"
        ) == pytest.approx(-1.3)

    def test_reads_the_json_figure(self) -> None:
        assert audio_probe.achieved_true_peak('{"output_tp" : "-1.31"}') == (
            pytest.approx(-1.31)
        )

    def test_the_last_block_wins(self) -> None:
        stderr = '{"output_tp" : "-9.0"}\n{"output_tp" : "-1.25"}\n'
        assert audio_probe.achieved_true_peak(stderr) == pytest.approx(-1.25)

    def test_a_non_finite_peak_reports_the_floor(self) -> None:
        """A silent pass publishes the floor, which is what reports show today."""
        assert audio_probe.achieved_true_peak('{"output_tp" : "-inf"}') == -70.0

    def test_no_summary_is_none(self) -> None:
        assert audio_probe.achieved_true_peak("") is None
        assert audio_probe.achieved_true_peak("no json at all") is None
        assert audio_probe.achieved_true_peak('{"input_i" : "-18.0"}') is None


@pytest.mark.integration
class TestAlbumLoudness:
    def test_a_folder_of_like_tracks_measures_like_one_track(
        self, tmp_path: Path
    ) -> None:
        first = write_tone(tmp_path / "01.wav")
        second = write_tone(tmp_path / "02.wav")
        single = audio_probe.measure_loudness(first)
        album = audio_probe.measure_album_loudness([first, second])
        assert album.integrated_lufs == pytest.approx(single.integrated_lufs, abs=0.1)

    def test_an_empty_folder_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _must_not_spawn(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("the probe spawned FFmpeg for an empty album")

        monkeypatch.setattr(audio_probe, "run_secure_subprocess", _must_not_spawn)
        with pytest.raises(AudioFormatError):
            audio_probe.measure_album_loudness([])


@pytest.mark.integration
class TestDecodedDuration:
    def test_returns_the_input_duration(self, tone: str) -> None:
        assert audio_probe.decoded_duration(tone) == pytest.approx(1.0, abs=0.01)

    def test_refuses_an_unsupported_extension(self, tmp_path: Path) -> None:
        unsupported = write_tone(tmp_path / "song.webm")
        with pytest.raises(AudioFormatError):
            audio_probe.decoded_duration(unsupported)


@pytest.mark.integration
class TestDecodeSamples:
    """A full float decode, for the figures no probe reports."""

    def test_it_returns_the_pcm_the_file_holds(self, tone: str) -> None:
        frames, samplerate = audio_probe.decode_samples(tone)

        assert samplerate == SAMPLE_RATE
        assert frames.shape[1] == 2
        assert frames.dtype == np.float32
        assert float(np.max(np.abs(frames))) == pytest.approx(0.5, abs=1e-3)

    def test_channels_stay_unpacked(self, tone: str) -> None:
        """A frame is one sample per channel, not one interleaved row."""
        frames, _ = audio_probe.decode_samples(tone)

        assert frames.shape[0] == SAMPLE_RATE
        assert np.array_equal(frames[:, 0], frames[:, 1])

    def test_an_over_full_sample_is_not_clamped(self, tmp_path: Path) -> None:
        """A lossy decoder overshoots; clamping would hide it."""
        sf = pytest.importorskip("soundfile")
        path = tmp_path / "hot.wav"
        loud = np.full((SAMPLE_RATE, 2), 1.25, dtype=np.float32)
        sf.write(str(path), loud, SAMPLE_RATE, subtype="FLOAT")

        frames, _ = audio_probe.decode_samples(str(path))

        assert float(np.max(frames)) > 1.2

    def test_a_decode_past_the_memory_budget_is_refused(self, tone: str) -> None:
        stream = dataclasses.replace(
            audio_probe.probe_stream(tone), duration_sec=4000.0
        )

        with pytest.raises(AudioFormatError, match="MiB"):
            audio_probe.decode_samples(tone, stream=stream)

    def test_a_file_ffmpeg_cannot_decode_is_refused(self, tmp_path: Path) -> None:
        junk = tmp_path / "junk.wav"
        junk.write_bytes(b"not audio at all" * 64)

        with pytest.raises(
            AudioFormatError, match="no audio stream|not readable|decoded no audio"
        ):
            audio_probe.decode_samples(str(junk))


@pytest.mark.integration
class TestReadOnlyContainers:
    """A read-only container is measured, never written.

    ``PLAN_2026-11-03_2.4.2_audio_foundation.md`` §2.1 says a read-only
    container "is refused before probing"; taken literally that would drop
    ReplayGain's dry-run analysis of ``.ape``/``.mpc``/``.dsf`` files, which the
    matrix advertises as *readable* and which a patch release may not remove.
    The refusal therefore stays at the write seam, and this lock proves both
    halves: the measurement still works, and the write seam still refuses.
    """

    def test_a_read_only_container_is_still_measurable(self) -> None:
        assert READ_ONLY_FIXTURE.is_file(), "the read-only fixture is missing"
        info = audio_probe.probe_stream(str(READ_ONLY_FIXTURE))
        assert info.codec == "ape"
        metrics = audio_probe.measure_loudness(str(READ_ONLY_FIXTURE))
        assert metrics.integrated_lufs < 0.0

    def test_the_write_seam_refuses_it(self) -> None:
        from audio_suite_shared.audio_formats import get_export_args

        with pytest.raises(AudioFormatError):
            get_export_args(".ape")

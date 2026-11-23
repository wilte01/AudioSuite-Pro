"""Tests for the pitch/time engine, measured on decoded output.

Every length and frequency here is read back from the written file, never from
the value the engine returned: a report that quotes its own request proves
nothing about the audio.

Changed in 2.7.0: new module (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

# Changed in 2.9.0: the report's SUMMARY footer is the shared
# ``run_report.summary_lines``, and this suite pins its labels (D39).
from __future__ import annotations

import hashlib
from pathlib import Path

import librosa
import numpy as np
import pytest
from mutagen import File as MutagenFile
from pydub import AudioSegment

from audio_suite_shared.dsp_time_pitch import pitch_shift, time_stretch
from audio_suite_shared.exceptions import AudioConfigValueError
from pitch_time.core.engine import REPORT_NAMES, process_file, run_pitch_time
from pitch_time.core.models import MODE_PITCH, PitchTimeSettings

SAMPLE_RATE = 44_100


def _tone(
    frequency: float = 440.0,
    *,
    seconds: float = 1.0,
    rate: int = SAMPLE_RATE,
    amplitude: float = 0.5,
) -> np.ndarray:
    times = np.arange(int(rate * seconds)) / rate
    return (amplitude * np.sin(2.0 * np.pi * frequency * times)).astype(np.float32)


def _write(
    path: Path, data: np.ndarray, *, rate: int = SAMPLE_RATE, width: int = 2
) -> Path:
    """Write *data* (``(n,)`` or ``(channels, n)``) as an integer PCM WAV."""
    scale = float((1 << (8 * width - 1)) - 1)
    array = np.asarray(data, dtype=np.float64)
    channels = 1 if array.ndim == 1 else array.shape[0]
    interleaved = array if array.ndim == 1 else array.T.reshape(-1)
    dtype = np.int16 if width == 2 else np.int32
    samples = np.round(np.clip(interleaved, -1.0, 1.0) * scale).astype(dtype)
    AudioSegment(
        data=samples.tobytes(),
        sample_width=width,
        frame_rate=rate,
        channels=channels,
    ).export(str(path), format="wav")
    return path


def _decode(path: Path) -> tuple[np.ndarray, int]:
    """Decode *path* at its own rate, channels kept apart."""
    loaded, rate = librosa.load(str(path), sr=None, mono=False)
    return np.atleast_2d(np.asarray(loaded, dtype=np.float64)), int(rate)


def _peak_hz(signal: np.ndarray, rate: int) -> float:
    """Return the dominant frequency of *signal*, interpolated to the bin."""
    windowed = np.asarray(signal, dtype=np.float64) * np.hanning(len(signal))
    spectrum = np.abs(np.fft.rfft(windowed))
    peak = int(np.argmax(spectrum[1:]) + 1)
    left, centre, right = spectrum[peak - 1], spectrum[peak], spectrum[peak + 1]
    offset = 0.5 * (left - right) / (left - 2.0 * centre + right)
    return (peak + offset) * rate / len(signal)


def _cents(measured: float, expected: float) -> float:
    return float(1200.0 * np.log2(measured / expected))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.integration
class TestTimeStretch:
    """A stretch changes the length and leaves the pitch where it was."""

    def test_a_quarter_faster_is_a_quarter_shorter_at_the_same_pitch(self) -> None:
        result = time_stretch(_tone(), 1.25, sample_rate=SAMPLE_RATE)

        assert result.original_seconds == pytest.approx(1.0, abs=0.001)
        assert result.processed_seconds == pytest.approx(0.8, abs=0.001)
        assert _cents(_peak_hz(result.audio, SAMPLE_RATE), 440.0) == pytest.approx(
            0.0, abs=1.0
        )

    def test_each_channel_keeps_its_own_material(self) -> None:
        stereo = np.vstack([_tone(440.0), _tone(880.0)])

        result = time_stretch(stereo, 1.25, sample_rate=SAMPLE_RATE)

        assert result.audio.shape[0] == 2
        assert _cents(_peak_hz(result.audio[0], SAMPLE_RATE), 440.0) == pytest.approx(
            0.0, abs=1.0
        )
        assert _cents(_peak_hz(result.audio[1], SAMPLE_RATE), 880.0) == pytest.approx(
            0.0, abs=1.0
        )

    @pytest.mark.parametrize("rate", [0.0, -1.25, 0.1, 8.0])
    def test_a_rate_the_renderer_cannot_honour_is_refused(self, rate: float) -> None:
        with pytest.raises(AudioConfigValueError, match="rate"):
            time_stretch(_tone(), rate, sample_rate=SAMPLE_RATE)

    def test_an_empty_signal_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="empty"):
            time_stretch(np.zeros(0, dtype=np.float32), 1.25, sample_rate=SAMPLE_RATE)


@pytest.mark.integration
class TestPitchShift:
    """A shift moves the pitch and leaves the length where it was."""

    def test_an_octave_up_doubles_the_frequency_and_keeps_the_length(self) -> None:
        result = pitch_shift(_tone(), 12.0, sample_rate=SAMPLE_RATE)

        assert result.processed_seconds == pytest.approx(1.0, abs=0.01)
        assert _cents(_peak_hz(result.audio, SAMPLE_RATE), 880.0) == pytest.approx(
            0.0, abs=1.0
        )

    def test_a_shift_outside_the_range_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="semitones"):
            pitch_shift(_tone(), 30.0, sample_rate=SAMPLE_RATE)


@pytest.mark.integration
class TestFileRun:
    """The run writes a measured file and reports that same measurement."""

    def test_a_tempo_run_writes_a_shorter_file_at_the_source_rate(
        self, tmp_path: Path
    ) -> None:
        source = _write(tmp_path / "song.wav", _tone())

        outcome = process_file(source, PitchTimeSettings(rate=1.25))

        written = tmp_path / "song_tempo_1.25.wav"
        assert outcome.output == written
        assert written.is_file()
        decoded, rate = _decode(written)
        assert rate == SAMPLE_RATE, "the source's sample rate must be preserved"
        assert decoded.shape[-1] / rate == pytest.approx(0.8, abs=0.002)
        assert outcome.processed_seconds == pytest.approx(
            decoded.shape[-1] / rate, abs=0.002
        )
        assert _cents(_peak_hz(decoded[0], rate), 440.0) == pytest.approx(0.0, abs=2.0)

    def test_a_pitch_run_writes_the_shifted_file(self, tmp_path: Path) -> None:
        source = _write(tmp_path / "song.wav", _tone())

        outcome = process_file(
            source, PitchTimeSettings(mode=MODE_PITCH, semitones=12.0)
        )

        assert outcome.output.name == "song_pitch_+12st.wav"
        decoded, rate = _decode(outcome.output)
        assert _cents(_peak_hz(decoded[0], rate), 880.0) == pytest.approx(0.0, abs=2.0)

    def test_a_dry_run_reports_the_projection_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        source = _write(tmp_path / "song.wav", _tone())
        before = _digest(source)

        outcome = process_file(source, PitchTimeSettings(rate=1.25), dry_run=True)

        assert outcome.written is False
        assert outcome.processed_seconds == pytest.approx(0.8, abs=0.002)
        assert sorted(path.name for path in tmp_path.iterdir()) == ["song.wav"]
        assert _digest(source) == before

    def test_a_24_bit_wav_keeps_its_depth(self, tmp_path: Path) -> None:
        source = _write(tmp_path / "song.wav", _tone(), width=4)

        outcome = process_file(source, PitchTimeSettings(rate=1.25))

        depth = MutagenFile(str(outcome.output)).info.bits_per_sample
        assert depth is not None and depth > 16, f"a 24-bit source became {depth}-bit"

    def test_a_flac_keeps_its_tags_and_its_container(self, tmp_path: Path) -> None:
        source = tmp_path / "song.flac"
        AudioSegment(
            data=(_tone() * 32767).astype(np.int16).tobytes(),
            sample_width=2,
            frame_rate=SAMPLE_RATE,
            channels=1,
        ).export(str(source), format="flac")
        tags = MutagenFile(str(source), easy=True)
        assert tags is not None
        tags["title"] = ["Original Title"]
        tags["artist"] = ["Original Artist"]
        tags.save()

        outcome = process_file(source, PitchTimeSettings(rate=1.25))

        assert outcome.output.suffix == ".flac"
        written = MutagenFile(str(outcome.output), easy=True)
        assert written is not None
        assert written["title"] == ["Original Title"]
        assert written["artist"] == ["Original Artist"]


@pytest.mark.integration
class TestBatchRun:
    """One folder, one report, and the counters that match the disk."""

    def test_the_report_records_the_run_and_both_files(self, tmp_path: Path) -> None:
        _write(tmp_path / "one.wav", _tone())
        _write(tmp_path / "two.wav", _tone(880.0))
        payloads: list[dict[str, object]] = []

        run_pitch_time(
            str(tmp_path),
            settings=PitchTimeSettings(rate=1.25),
            on_complete=lambda **payload: payloads.append(payload),
        )

        report = tmp_path / REPORT_NAMES[False]
        assert report.is_file(), "a finished run writes its report"
        text = report.read_text(encoding="utf-8")
        assert text.startswith("PITCH / TIME REPORT")
        assert "Mode: LIVE UPDATE" in text
        assert "Tempo rate 1.25x" in text
        assert "one.wav" in text and "two.wav" in text
        assert "SUMMARY:" in text
        assert "Files: 2\nWritten: 2\nSkipped: 0\nErrors: 0\n" in text
        assert payloads and payloads[0]["written"] == 2
        assert (tmp_path / "one_tempo_1.25.wav").is_file()
        assert (tmp_path / "two_tempo_1.25.wav").is_file()

    def test_a_dry_run_names_its_own_report_and_writes_no_audio(
        self, tmp_path: Path
    ) -> None:
        _write(tmp_path / "one.wav", _tone())
        payloads: list[dict[str, object]] = []

        run_pitch_time(
            str(tmp_path),
            settings=PitchTimeSettings(rate=1.25),
            dry_run=True,
            on_complete=lambda **payload: payloads.append(payload),
        )

        assert (tmp_path / REPORT_NAMES[True]).is_file()
        assert not (tmp_path / REPORT_NAMES[False]).exists()
        assert not (tmp_path / "one_tempo_1.25.wav").exists()
        assert payloads and payloads[0]["written"] == 0

    def test_a_missing_folder_reports_through_on_error(self, tmp_path: Path) -> None:
        messages: list[str] = []

        run_pitch_time(
            str(tmp_path / "absent"),
            settings=PitchTimeSettings(rate=1.25),
            on_error=messages.append,
        )

        assert messages and "does not exist" in messages[0]

    def test_an_empty_folder_is_reported_not_silently_clean(
        self, tmp_path: Path
    ) -> None:
        messages: list[str] = []

        run_pitch_time(
            str(tmp_path),
            settings=PitchTimeSettings(rate=1.25),
            on_error=messages.append,
        )

        assert messages and "no supported audio" in messages[0]

    def test_a_neutral_setting_skips_every_file_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        """A driver batch with defaults must not re-encode for no change."""
        source = _write(tmp_path / "one.wav", _tone())
        before = _digest(source)
        payloads: list[dict[str, object]] = []

        run_pitch_time(
            str(tmp_path),
            settings=PitchTimeSettings(),
            on_complete=lambda **payload: payloads.append(payload),
        )

        assert sorted(path.name for path in tmp_path.iterdir()) == [
            "one.wav",
            REPORT_NAMES[False],
        ]
        assert _digest(source) == before
        assert payloads and payloads[0]["skipped"] == 1
        assert payloads[0]["written"] == 0
        report = (tmp_path / REPORT_NAMES[False]).read_text(encoding="utf-8")
        assert "SKIPPED (no change requested" in report

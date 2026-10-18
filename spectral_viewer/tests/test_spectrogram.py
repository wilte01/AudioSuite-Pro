"""Tests for the spectrogram core.

The fixture audio is synthesised with the stdlib ``wave`` module rather than
pydub/ffmpeg, so these tests state a known signal (a pure 440 Hz tone) and can
assert where the energy actually landed. The exported PNG is decoded again with
Pillow and checked for real image content: "the file exists" would pass for a
blank image.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from audio_suite_shared.exceptions import AudioAnalysisError
from spectral_viewer.core.spectrogram import (
    DEFAULT_DB_RANGE,
    OUTPUT_SUFFIX,
    build_figure,
    compute_spectrogram,
    export_image,
    iter_audio_files,
    output_path_for,
    render_spectrogram,
)
from spectral_viewer.tests.audio_fixtures import SAMPLE_RATE, write_tone_wav

_SR = SAMPLE_RATE


@pytest.fixture()
def tone_wav(tmp_path: Path) -> Path:
    """A one-second 440 Hz tone."""
    return write_tone_wav(tmp_path / "tone.wav")


class TestComputeSpectrogram:
    def test_energy_lands_on_the_tone_frequency(self, tone_wav: Path) -> None:
        data = compute_spectrogram(str(tone_wav), n_fft=2048)

        per_bin = data.db.mean(axis=1)
        peak_frequency = float(data.frequencies[int(np.argmax(per_bin))])

        # A 2048-point FFT at 22.05 kHz resolves ~10.8 Hz per bin.
        assert abs(peak_frequency - 440.0) <= 25.0, peak_frequency
        # The tone's own bin averages within a decibel of the peak, so the mean
        # profile is dominated by it rather than by broadband noise.
        assert float(per_bin.max()) > -1.0

    def test_shape_axes_and_ranges(self, tone_wav: Path) -> None:
        data = compute_spectrogram(str(tone_wav), n_fft=2048, hop_length=512)

        assert data.shape == (1025, len(data.times))
        assert data.db.shape == (len(data.frequencies), len(data.times))
        assert data.sample_rate == _SR
        assert data.n_fft == 2048
        assert data.hop_length == 512
        assert data.duration_secs == pytest.approx(1.0, abs=0.02)
        assert float(data.db.max()) == pytest.approx(0.0, abs=1e-3)
        assert float(data.db.min()) >= -DEFAULT_DB_RANGE - 1e-6
        # Ascending axes, times starting at the file's beginning.
        assert np.all(np.diff(data.frequencies) > 0)
        assert np.all(np.diff(data.times) > 0)
        assert float(data.times[0]) == pytest.approx(0.0, abs=1e-9)
        assert data.peak_db < 0.0

    def test_time_window_offsets_times(self, tone_wav: Path) -> None:
        data = compute_spectrogram(str(tone_wav), start=0.2, end=0.6, n_fft=1024)

        assert float(data.times[0]) == pytest.approx(0.2, abs=0.01)
        assert data.duration_secs == pytest.approx(0.4, abs=0.02)
        assert float(data.times[-1]) <= 0.6

    def test_max_frequency_trims_the_axis(self, tone_wav: Path) -> None:
        data = compute_spectrogram(str(tone_wav), max_freq=1000.0, n_fft=2048)

        assert float(data.frequencies.max()) <= 1000.0
        assert float(data.frequencies.min()) == 0.0

    def test_digital_silence_is_the_floor_not_nan(self, tmp_path: Path) -> None:
        silent = write_tone_wav(tmp_path / "silent.wav", silent=True, seconds=0.5)

        data = compute_spectrogram(str(silent), n_fft=1024)

        assert np.all(np.isfinite(data.db))
        assert float(data.db.max()) == pytest.approx(-DEFAULT_DB_RANGE)
        assert data.peak_db == pytest.approx(-240.0)

    def test_window_shorter_than_the_minimum_raises(self, tone_wav: Path) -> None:
        with pytest.raises(AudioAnalysisError):
            compute_spectrogram(str(tone_wav), start=0.0, end=0.05)

    def test_end_before_start_raises(self, tone_wav: Path) -> None:
        with pytest.raises(ValueError, match="later than start"):
            compute_spectrogram(str(tone_wav), start=0.5, end=0.3)

    def test_hop_larger_than_fft_raises(self, tone_wav: Path) -> None:
        with pytest.raises(ValueError, match="Hop length"):
            compute_spectrogram(str(tone_wav), n_fft=512, hop_length=1024)

    def test_window_shorter_than_fft_raises(self, tone_wav: Path) -> None:
        with pytest.raises(AudioAnalysisError, match="shorter than the FFT"):
            compute_spectrogram(str(tone_wav), start=0.0, end=0.11, n_fft=8192)


class TestFigure:
    def test_figure_geometry_limits_and_title(self, tone_wav: Path) -> None:
        data = compute_spectrogram(str(tone_wav), n_fft=1024)

        figure = build_figure(data, title="tone.wav", dynamic_range_db=60.0)

        # One data axes plus the colorbar's axes.
        assert len(figure.axes) == 2
        axes = figure.axes[0]
        assert axes.get_title() == "tone.wav"
        assert axes.get_xlabel() == "Time (s)"
        assert axes.get_ylabel() == "Frequency (Hz)"
        image = axes.images[0]
        assert image.get_clim() == (-60.0, 0.0)
        # The image is drawn across the real time range, not a frame index.
        left, right = axes.get_xlim()
        assert left == pytest.approx(float(data.times[0]), abs=1e-6)
        assert right == pytest.approx(float(data.times[-1]), abs=1e-6)

    def test_non_positive_dynamic_range_is_refused(self, tone_wav: Path) -> None:
        data = compute_spectrogram(str(tone_wav), n_fft=1024)
        with pytest.raises(ValueError, match="Dynamic range"):
            build_figure(data, dynamic_range_db=0.0)


class TestExport:
    def test_export_writes_a_real_png(self, tone_wav: Path, tmp_path: Path) -> None:
        from PIL import Image

        data = compute_spectrogram(str(tone_wav), n_fft=1024)
        figure = build_figure(data, title="tone.wav")
        destination = tmp_path / "out" / "tone.png"

        written = export_image(figure, destination)

        assert written == str(destination)
        assert destination.exists()
        assert destination.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        with Image.open(destination) as image:
            colours = image.convert("RGB").getcolors(maxcolors=1_000_000)
        assert colours is not None and len(colours) > 10, (
            "the exported image is blank or flat: the spectrogram did not reach "
            "the file"
        )

    def test_render_spectrogram_is_compute_plus_export(
        self, tone_wav: Path, tmp_path: Path
    ) -> None:
        destination = tmp_path / "rendered.png"

        result = render_spectrogram(str(tone_wav), destination, dynamic_range_db=70)

        assert result == str(destination)
        assert destination.stat().st_size > 5000


class TestPaths:
    def test_output_path_defaults_beside_the_source(self, tmp_path: Path) -> None:
        source = tmp_path / "music" / "track.flac"
        assert output_path_for(source) == tmp_path / "music" / ("track" + OUTPUT_SUFFIX)

    def test_output_path_honours_the_output_directory(self, tmp_path: Path) -> None:
        source = tmp_path / "music" / "track.flac"
        target = tmp_path / "images"
        assert output_path_for(source, target) == target / ("track" + OUTPUT_SUFFIX)

    def test_iter_audio_files_scans_and_sorts(self, tmp_path: Path) -> None:
        write_tone_wav(tmp_path / "b.wav", seconds=0.2)
        write_tone_wav(tmp_path / "a.wav", seconds=0.2)
        (tmp_path / "notes.txt").write_text("not audio", encoding="utf-8")
        nested = tmp_path / "album"
        nested.mkdir()
        write_tone_wav(nested / "c.wav", seconds=0.2)

        found = iter_audio_files(tmp_path)

        # Sorted by full path, so the album subfolder's file sorts between the
        # top-level ones; determinism is the contract, not a name order.
        assert found == sorted(found)
        assert sorted(Path(p).name for p in found) == ["a.wav", "b.wav", "c.wav"]

    def test_iter_audio_files_accepts_a_single_file(self, tone_wav: Path) -> None:
        assert iter_audio_files(tone_wav) == [str(tone_wav)]

    def test_iter_audio_files_ignores_a_non_audio_file(self, tmp_path: Path) -> None:
        notes = tmp_path / "notes.txt"
        notes.write_text("not audio", encoding="utf-8")
        assert iter_audio_files(notes) == []

    def test_iter_audio_files_missing_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            iter_audio_files(tmp_path / "nope")

"""test_ffmpeg_metrics.py — equality lock for the WP-5.1 measurement migration.

Changed in 2.4.2: new lock for ``replaygain_analyzer.core.ffmpeg_metrics``
(``PLAN_2026-11-03_2.4.2_audio_foundation.md`` WP-5.1).

The migration is behaviour-neutral or it is a defect: ReplayGain's reported
numbers are the product's promise, so every file is measured twice — once
through the shipped adapter, once through the frozen 2.4.1 implementation in
``_legacy_metrics.py`` — and the two must agree within the tolerances the plan
states.  Tolerances (0.05 dB loudness, 0.05 dB peak, 1 ms duration) exist only
for FFmpeg's own rounding, never for a different filter chain.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import pytest

from replaygain_analyzer.core.ffmpeg_metrics import (
    get_metrics,
    measure_album_loudness,
)
from replaygain_analyzer.tests import _legacy_metrics as legacy

SAMPLE_RATE = 44100
REPO_ROOT = Path(__file__).resolve().parents[2]

LUFS_TOLERANCE_DB = 0.05
PEAK_TOLERANCE_DB = 0.05
DURATION_TOLERANCE_MS = 1.0

#: Real recordings (CC0, see tests/data/bpm_corpus/ATTRIBUTION.md) plus one
#: read-only container: the corpus must exercise containers the suite cannot
#: write, because those are the ones a probe could silently stop measuring.
CORPUS_FILES = (
    REPO_ROOT / "tests" / "data" / "bpm_corpus" / "hiphop_86.ogg",
    REPO_ROOT / "tests" / "data" / "bpm_corpus" / "blues_shuffle_152.ogg",
    REPO_ROOT / "tests" / "data" / "bpm_corpus" / "ambient_pulse_60.ogg",
    REPO_ROOT / "tests" / "data" / "mac-390-hdr.ape",
)

#: (seconds, amplitude, channels) — levels spread across ~30 dB so a chain that
#: measured the wrong signal could not land inside the tolerance by accident.
TONE_SPECS = (
    (1.0, 0.5, 2),
    (1.0, 0.25, 1),
    (0.75, 0.9, 2),
    (2.0, 0.1, 1),
    (0.5, 0.5, 2),
)


def write_tone(
    path: Path,
    *,
    seconds: float,
    amplitude: float,
    channels: int,
    frequency: float = 440.0,
) -> Path:
    """Write a sine tone as a real PCM WAV file.

    Args:
        path: Destination path.
        seconds: Length in seconds.
        amplitude: Peak as a fraction of full scale.
        channels: Channel count.
        frequency: Tone frequency in Hz.

    Returns:
        The destination path.
    """
    frames = int(SAMPLE_RATE * seconds)
    peak = int(amplitude * 32767)
    payload = bytearray()
    for index in range(frames):
        sample = int(peak * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE))
        payload += sample.to_bytes(2, "little", signed=True) * channels
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(payload))
    return path


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    """The generated tone set plus the real fixture corpus."""
    folder = tmp_path_factory.mktemp("replaygain_equality")
    tones = [
        write_tone(folder / f"tone_{index}.wav", seconds=s, amplitude=a, channels=c)
        for index, (s, a, c) in enumerate(TONE_SPECS)
    ]
    return [*tones, *(path for path in CORPUS_FILES if path.is_file())]


def _close(new: float | None, old: float | None, tolerance: float) -> bool:
    """Compare two measurements, treating an absent value as matching only itself."""
    if new is None or old is None:
        return new is None and old is None
    return abs(new - old) <= tolerance


def _describe(new: object, old: object) -> str:
    return f"shipped={new!r} legacy={old!r}"


@pytest.mark.integration
class TestEqualityWithTheFrozenImplementation:
    def test_the_corpus_is_not_empty(self, corpus: list[Path]) -> None:
        """A scan that found nothing would satisfy every assertion below."""
        assert len(corpus) >= len(TONE_SPECS)

    def test_every_file_measures_the_same_as_at_2_4_1(self, corpus: list[Path]) -> None:
        for path in corpus:
            new_lufs, new_peak, new_duration = get_metrics(str(path))
            old_lufs, old_peak, old_duration = legacy.get_metrics(str(path))

            assert old_lufs is not None, f"legacy could not measure {path.name}"
            assert _close(new_lufs, old_lufs, LUFS_TOLERANCE_DB), (
                f"{path.name} loudness moved: "
                f"{_describe(new_lufs, old_lufs)} (tolerance {LUFS_TOLERANCE_DB} dB)"
            )
            assert _close(new_peak, old_peak, PEAK_TOLERANCE_DB), (
                f"{path.name} true peak moved: {_describe(new_peak, old_peak)}"
            )
            assert new_duration is not None and old_duration is not None
            assert abs(new_duration - old_duration) * 1000.0 <= DURATION_TOLERANCE_MS, (
                f"{path.name} duration moved: {_describe(new_duration, old_duration)}"
            )

    def test_a_read_only_container_still_measures(self, corpus: list[Path]) -> None:
        read_only = [path for path in corpus if path.suffix == ".ape"]
        assert read_only, "the read-only container left the corpus"
        lufs, peak, duration = get_metrics(str(read_only[0]))
        assert lufs is not None and duration is not None
        assert peak <= 0.0


@pytest.mark.integration
class TestAlbumEquality:
    def test_the_combined_signal_measures_the_same(self, tmp_path: Path) -> None:
        paths = [
            str(
                write_tone(
                    tmp_path / "01 loud.wav", seconds=1.0, amplitude=0.5, channels=1
                )
            ),
            str(
                write_tone(
                    tmp_path / "02 quiet.wav", seconds=1.0, amplitude=0.05, channels=1
                )
            ),
        ]
        new = measure_album_loudness(paths)
        old = legacy.measure_album_loudness(paths)
        assert old is not None, "the frozen implementation could not measure the album"
        assert _close(new, old, LUFS_TOLERANCE_DB), _describe(new, old)


class TestAdapterContract:
    """The return shapes ReplayGain's pipeline depends on are unchanged."""

    def test_get_metrics_returns_three_values(self) -> None:
        result = get_metrics("C:/does/not/exist.mp3")
        assert isinstance(result, tuple) and len(result) == 3

    def test_an_unsupported_container_reports_a_failed_measurement(self) -> None:
        lufs, peak, duration = get_metrics("C:/does/not/exist.webm")
        assert lufs is None
        assert peak == 0.0
        assert duration is None

    def test_an_empty_album_returns_none(self) -> None:
        assert measure_album_loudness([]) is None

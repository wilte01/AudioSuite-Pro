"""Cross-tool loudness agreement — the WP-5.1 acceptance criterion.

``PLAN_2026-11-03_2.4.2_audio_foundation.md`` §2.2 asks that ReplayGain, the
Audio Normalizer and the new probe agree within 0.1 dB on the same file, because
that is what a user notices: the same track reported at two loudness values by
two tools.  The two chains are different filters (``ebur128`` versus
``loudnorm``), so this is a real comparison — unlike comparing the probe with
ReplayGain, which now share one implementation and are checked as a wiring
identity at the tighter tolerance.

Changed in 2.4.2: new cross-tool lock (WP-5.1).
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import pytest

from audio_normalizer.core.loudness import measure as normalizer_measure
from audio_suite_shared.audio_probe import measure_loudness
from replaygain_analyzer.core.ffmpeg_metrics import get_metrics

SAMPLE_RATE = 44100

#: The plan's cross-tool tolerance: two different EBU R128 implementations.
CROSS_TOOL_TOLERANCE_DB = 0.1

#: One implementation behind both names: the adapter is checked as wiring only.
SAME_CHAIN_TOLERANCE_DB = 0.05

TARGET_LUFS = -16.0


def write_tone(path: Path, *, seconds: float, amplitude: float) -> str:
    """Write a mono sine tone as a real PCM WAV file.

    Args:
        path: Destination path.
        seconds: Length in seconds.
        amplitude: Peak as a fraction of full scale.

    Returns:
        The path as a string.
    """
    frames = int(SAMPLE_RATE * seconds)
    peak = int(amplitude * 32767)
    payload = bytearray()
    for index in range(frames):
        sample = int(peak * math.sin(2 * math.pi * 440.0 * index / SAMPLE_RATE))
        payload += sample.to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(payload))
    return str(path)


@pytest.mark.integration
class TestThreeToolsAgree:
    @pytest.mark.parametrize("amplitude", [0.5, 0.15])
    def test_the_normalizer_and_the_probe_agree(
        self, tmp_path: Path, amplitude: float
    ) -> None:
        tone = write_tone(tmp_path / "tone.wav", seconds=2.0, amplitude=amplitude)

        measured = normalizer_measure(tone, TARGET_LUFS)
        assert measured is not None, "the normaliser could not measure the tone"
        integrated = measured["input_i"]

        probe = measure_loudness(tone)
        assert abs(probe.integrated_lufs - integrated) <= CROSS_TOOL_TOLERANCE_DB, (
            f"probe {probe.integrated_lufs:.2f} LUFS vs normaliser "
            f"{integrated:.2f} LUFS exceed {CROSS_TOOL_TOLERANCE_DB} dB"
        )

    def test_replaygain_reports_the_probe_value(self, tmp_path: Path) -> None:
        """ReplayGain now measures through the probe; the adapter is the only gap."""
        tone = write_tone(tmp_path / "tone.wav", seconds=2.0, amplitude=0.5)
        lufs, _peak, _duration = get_metrics(tone)
        assert lufs is not None
        assert abs(lufs - measure_loudness(tone).integrated_lufs) <= (
            SAME_CHAIN_TOLERANCE_DB
        )

    def test_all_three_land_in_one_band(self, tmp_path: Path) -> None:
        tone = write_tone(tmp_path / "tone.wav", seconds=2.0, amplitude=0.5)
        measured = normalizer_measure(tone, TARGET_LUFS)
        assert measured is not None
        values = {
            "replaygain": get_metrics(tone)[0],
            "normalizer": measured["input_i"],
            "probe": measure_loudness(tone).integrated_lufs,
        }
        assert all(value is not None for value in values.values())
        spread = max(values.values()) - min(values.values())
        assert spread <= CROSS_TOOL_TOLERANCE_DB, f"tools disagree: {values}"

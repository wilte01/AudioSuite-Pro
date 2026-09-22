"""
gain_calculator.py
Calculates album-level ReplayGain values from a list of per-file
measurement results.

Pure function — no tkinter, no file I/O, no FFmpeg.
"""

import statistics

from audio_suite_shared.exceptions import AudioSuiteError


def calculate_album_gain(
    target_lufs: float,
    lufs_values: list[float],
    peak_values: list[float],
) -> tuple[float, float, str, str]:
    """
    Derive album gain and album peak from per-file measurements.

    Album gain  = target_lufs − mean(integrated LUFS across all files)
    Album peak  = max(true peak across all files)

    Args:
        target_lufs:  Desired integrated loudness level (e.g. -16.0).
        lufs_values:  Non-empty list of per-file integrated LUFS measurements.
        peak_values:  Non-empty list of per-file true peak values (dBFS).

    Returns:
        (album_gain, album_peak, album_gain_str, album_peak_str)

    Raises:
        AudioSuiteError: If either input list is empty.
    """
    # Fix #20: guard against empty lists that would raise StatisticsError / ValueError
    if not lufs_values:
        raise AudioSuiteError(
            "calculate_album_gain: lufs_values must not be empty",
            context={"target_lufs": target_lufs},
        )
    if not peak_values:
        raise AudioSuiteError(
            "calculate_album_gain: peak_values must not be empty",
            context={"target_lufs": target_lufs},
        )

    album_gain: float = target_lufs - statistics.mean(lufs_values)
    album_peak: float = max(peak_values)
    return (
        album_gain,
        album_peak,
        f"{album_gain:+.2f} dB",
        f"{album_peak:.6f}",
    )

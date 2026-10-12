"""
gain_calculator.py
Calculates album-level ReplayGain values from a list of per-file
measurement results.

Pure function — no tkinter, no file I/O, no FFmpeg.

Changed in 1.0.1: album peak is now converted from the ffmpeg dBFS
measurement to the linear amplitude the REPLAYGAIN_*_PEAK tags require.
"""

import statistics

from audio_suite_shared.exceptions import AudioSuiteError


def dbfs_to_linear(peak_dbfs: float) -> float:
    """
    Convert a true-peak measurement in dBFS to linear amplitude.

    The ReplayGain convention (foobar2000, loudgain, metaflac) stores
    ``REPLAYGAIN_*_PEAK`` as a linear sample value in 0.0–1.0, not dBFS.
    The 0.0 dBFS reference maps to 1.0, so the conversion is
    ``10 ** (peak_dbfs / 20)``.

    Args:
        peak_dbfs: True peak in dBFS (0.0 dBFS is full scale).

    Returns:
        Linear peak amplitude; values above full scale (inter-sample true
        peaks) exceed 1.0.
    """
    return 10 ** (peak_dbfs / 20)


def calculate_album_gain(
    target_lufs: float,
    lufs_values: list[float],
    peak_values: list[float],
) -> tuple[float, float, str, str]:
    """
    Derive album gain and album peak from per-file measurements.

    Album gain  = target_lufs − mean(integrated LUFS across all files)
    Album peak  = max(linear true peak across all files)

    Args:
        target_lufs:  Desired integrated loudness level (e.g. -16.0).
        lufs_values:  Non-empty list of per-file integrated LUFS measurements.
        peak_values:  Non-empty list of per-file true peak values (dBFS).

    Returns:
        (album_gain, album_peak, album_gain_str, album_peak_str).
        ``album_peak`` / ``album_peak_str`` are linear amplitude (the
        ReplayGain tag unit), converted from the dBFS inputs.

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
    album_peak: float = max(dbfs_to_linear(peak) for peak in peak_values)
    return (
        album_gain,
        album_peak,
        f"{album_gain:+.2f} dB",
        f"{album_peak:.6f}",
    )

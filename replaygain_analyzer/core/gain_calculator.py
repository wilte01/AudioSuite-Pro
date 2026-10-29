"""
gain_calculator.py
Calculates album-level ReplayGain values from a list of per-file
measurement results.

Pure function — no tkinter, no file I/O, no FFmpeg.

Changed in 1.0.1: album peak is now converted from the ffmpeg dBFS
measurement to the linear amplitude the REPLAYGAIN_*_PEAK tags require.
Changed in 2.1.2: album loudness is the duration-weighted mean-square energy
of the tracks (ReplayGain 2.0-compatible), not the arithmetic mean of their
integrated loudness. A 10 s -10 LUFS track and a 30 s -30 LUFS track used to
count equally, which put a +4.0 dB album gain on a pair whose combined signal
is -15.9 LUFS (audit R-01).
Changed in 2.1.7: ``album_lufs`` accepts the one-pass measurement of the
concatenated album, which is ReplayGain 2.0's actual definition. The
duration-weighted formula remains the fallback for a folder whose combined
signal could not be measured (A1 measured it 2.33 dB out on a silent tail and
3.00 dB out on a loud + quiet pair).
"""

import math

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
    durations_s: list[float],
    album_lufs: float | None = None,
) -> tuple[float, float, str, str]:
    """
    Derive album gain and album peak from per-file measurements.

    Album loudness is ``album_lufs`` when the caller measured the concatenated
    album in one pass; otherwise it is ``10·log10(Σ 10^(Lᵢ/10)·dᵢ / Σ dᵢ)`` —
    the mean-square energy of the tracks, weighted by each track's duration.
    Album gain is ``target_lufs − album loudness``; album peak is the loudest
    linear true peak across the files.

    Args:
        target_lufs:  Desired integrated loudness level (e.g. -16.0).
        lufs_values:  Non-empty list of per-file integrated LUFS measurements.
        peak_values:  Non-empty list of per-file true peak values (dBFS).
            This list is aggregated with ``max()`` and may be longer than
            ``lufs_values``.
        durations_s:  Per-file durations in seconds, one per LUFS value.
            Every entry must be finite and positive.
        album_lufs:   Optional integrated loudness of the album's combined
            signal, measured in one pass. Must be finite when supplied.

    Returns:
        (album_gain, album_peak, album_gain_str, album_peak_str).
        ``album_peak`` / ``album_peak_str`` are linear amplitude (the
        ReplayGain tag unit), converted from the dBFS inputs.

    Raises:
        AudioSuiteError: If a list is empty, the duration list does not match
            ``lufs_values``, a duration is not finite/positive, ``album_lufs``
            is not finite, or the summed energy is not positive.
    """
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
    if len(durations_s) != len(lufs_values):
        raise AudioSuiteError(
            "calculate_album_gain: durations_s must match lufs_values",
            context={
                "target_lufs": target_lufs,
                "lufs_count": len(lufs_values),
                "duration_count": len(durations_s),
            },
        )
    if any((not math.isfinite(duration)) or duration <= 0 for duration in durations_s):
        raise AudioSuiteError(
            "calculate_album_gain: every duration must be finite and positive",
            context={"target_lufs": target_lufs, "durations_s": durations_s},
        )

    if album_lufs is not None and not math.isfinite(album_lufs):
        raise AudioSuiteError(
            "calculate_album_gain: album_lufs must be finite",
            context={"target_lufs": target_lufs, "album_lufs": album_lufs},
        )

    if album_lufs is None:
        total_duration = sum(durations_s)
        energy = sum(
            10 ** (lufs / 10) * duration
            for lufs, duration in zip(lufs_values, durations_s, strict=True)
        )
        if energy <= 0:
            raise AudioSuiteError(
                "calculate_album_gain: the summed track energy must be positive",
                context={"target_lufs": target_lufs, "energy": energy},
            )
        album_lufs = 10 * math.log10(energy / total_duration)

    album_gain: float = target_lufs - album_lufs
    album_peak: float = max(dbfs_to_linear(peak) for peak in peak_values)
    return (
        album_gain,
        album_peak,
        f"{album_gain:+.2f} dB",
        f"{album_peak:.6f}",
    )

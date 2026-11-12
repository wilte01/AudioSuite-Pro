"""dsp_dynamics.py — Compressor and brickwall limiter, one measured report.

This module is the suite's only controllable-dynamics implementation (F-S2 of
``PLAN_2026-11-03_2.7.0_feature_wave_3.md``). It is pure apart from the
measurement step, which writes a temporary WAV and asks the shared probe — the
same FFmpeg path every reporting tool uses — so the numbers in a run report
cannot disagree with the file the user plays.

The report is measured, not requested
-------------------------------------
``GainReductionReport`` is built from the rendered audio: the reduction is the
block-by-block level difference between input and output (with makeup gain added
back), and the output loudness and true peak come from the probe reading the
rendered file. A report built from the settings would say what was asked for
rather than what happened, which is the fabricated-value class the suite bans.

The limiter is Pedalboard's ``BrickwallLimiter``, not ``Limiter``
---------------------------------------------------------------
``pedalboard.Limiter`` is a loudness maximiser: it applies automatic makeup gain
and hard-clips at 0 dBFS, so it cannot enforce a ceiling below full scale. The
installed ``BrickwallLimiter`` takes a real ``ceiling_db``, a ``lookahead_ms``
and a 4x-oversampled ``true_peak`` detector, and applies no makeup gain, which
is the contract this stage promises (verified against pedalboard 0.9.25).

Knee is refused, not ignored
----------------------------
The installed ``Compressor`` exposes threshold, ratio, attack and release only;
its soft knee is fixed. :class:`CompressorSettings` therefore refuses a non-zero
``knee_db`` rather than accepting a control the renderer cannot honour, and the
measured curve carries a constant ~0.86 dB soft-knee offset against the ideal
hard-knee transfer (recorded in the plan's decision log).

Changed in 2.7.0: new module — the compressor and limiter engine (F-S2).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from audio_suite_shared.exceptions import AudioConfigValueError

#: Reduction is summarised over blocks this long. 50 ms is long enough for a
#: stable RMS and short enough to show an attack/release move.
REDUCTION_BLOCK_MS: float = 50.0

#: Blocks quieter than this cannot report a meaningful ratio and are skipped.
REDUCTION_SILENCE_FLOOR_DB: float = -60.0

COMP_MIN_THRESHOLD_DB: float = -60.0
COMP_MAX_RATIO: float = 20.0
COMP_MIN_ATTACK_MS: float = 0.1
COMP_MAX_ATTACK_MS: float = 200.0
COMP_MIN_RELEASE_MS: float = 1.0
COMP_MAX_RELEASE_MS: float = 2_000.0
COMP_MAX_MAKEUP_DB: float = 24.0

LIMIT_MAX_CEILING_DBTP: float = 0.0
LIMIT_MIN_CEILING_DBTP: float = -24.0
LIMIT_MAX_LOOKAHEAD_MS: float = 20.0
LIMIT_MIN_RELEASE_MS: float = 1.0
LIMIT_MAX_RELEASE_MS: float = 2_000.0


@dataclass(frozen=True)
class CompressorSettings:
    """One compressor, as a user sets it.

    Attributes:
        threshold_db: Level above which gain reduction starts, in dBFS.
        ratio: Reduction ratio above the threshold; 4.0 means 4:1.
        attack_ms: Time to reach full reduction after the threshold is crossed.
        release_ms: Time to recover after the signal falls back below it.
        makeup_db: Static gain applied after compression, in dB.
        knee_db: Soft-knee width. The installed compressor has a fixed knee, so
            only ``0.0`` (do not ask for one) is accepted; see the module
            docstring.
        bypass: When true the compressor contributes nothing.
    """

    threshold_db: float = -18.0
    ratio: float = 4.0
    attack_ms: float = 10.0
    release_ms: float = 100.0
    makeup_db: float = 0.0
    knee_db: float = 0.0
    bypass: bool = False

    def __post_init__(self) -> None:
        """Refuse a setting the renderer cannot apply as written.

        Raises:
            AudioConfigValueError: When a value is out of range, or a knee is
                requested that the installed compressor cannot honour.
        """
        if not COMP_MIN_THRESHOLD_DB <= self.threshold_db <= 0.0:
            raise AudioConfigValueError(
                f"Compressor threshold {self.threshold_db} dB is outside "
                f"{COMP_MIN_THRESHOLD_DB:.0f}-0 dB",
                context={"field": "comp_threshold_db", "value": self.threshold_db},
            )
        if not 1.0 <= self.ratio <= COMP_MAX_RATIO:
            raise AudioConfigValueError(
                f"Compressor ratio {self.ratio} is outside 1.0-{COMP_MAX_RATIO:g}",
                context={"field": "comp_ratio", "value": self.ratio},
            )
        if not COMP_MIN_ATTACK_MS <= self.attack_ms <= COMP_MAX_ATTACK_MS:
            raise AudioConfigValueError(
                f"Compressor attack {self.attack_ms} ms is outside "
                f"{COMP_MIN_ATTACK_MS}-{COMP_MAX_ATTACK_MS:.0f} ms",
                context={"field": "comp_attack_ms", "value": self.attack_ms},
            )
        if not COMP_MIN_RELEASE_MS <= self.release_ms <= COMP_MAX_RELEASE_MS:
            raise AudioConfigValueError(
                f"Compressor release {self.release_ms} ms is outside "
                f"{COMP_MIN_RELEASE_MS}-{COMP_MAX_RELEASE_MS:.0f} ms",
                context={"field": "comp_release_ms", "value": self.release_ms},
            )
        if not -COMP_MAX_MAKEUP_DB <= self.makeup_db <= COMP_MAX_MAKEUP_DB:
            raise AudioConfigValueError(
                f"Compressor makeup {self.makeup_db} dB is outside "
                f"+/-{COMP_MAX_MAKEUP_DB:.0f} dB",
                context={"field": "comp_makeup_db", "value": self.makeup_db},
            )
        if self.knee_db != 0.0:
            raise AudioConfigValueError(
                "The installed compressor has a fixed soft knee, so knee_db "
                f"must be 0.0; got {self.knee_db} dB",
                context={"field": "comp_knee_db", "value": self.knee_db},
            )


@dataclass(frozen=True)
class LimiterSettings:
    """One brickwall limiter, as a user sets it.

    Attributes:
        ceiling_dbtp: The true-peak ceiling to hold, in dBTP.
        lookahead_ms: Lookahead the limiter uses to catch peaks before they
            arrive. Pedalboard's brickwall limiter defaults to 5 ms.
        release_ms: Recovery time after a peak, in ms.
        bypass: When true the limiter contributes nothing.
    """

    ceiling_dbtp: float = -1.0
    lookahead_ms: float = 5.0
    release_ms: float = 100.0
    bypass: bool = False

    def __post_init__(self) -> None:
        """Refuse a ceiling or timing the limiter cannot honour.

        Raises:
            AudioConfigValueError: When a value is out of range.
        """
        if not LIMIT_MIN_CEILING_DBTP <= self.ceiling_dbtp <= LIMIT_MAX_CEILING_DBTP:
            raise AudioConfigValueError(
                f"Limiter ceiling {self.ceiling_dbtp} dBTP is outside "
                f"{LIMIT_MIN_CEILING_DBTP:.0f}-{LIMIT_MAX_CEILING_DBTP:.0f} dBTP",
                context={"field": "limiter_ceiling_dbtp", "value": self.ceiling_dbtp},
            )
        if not 0.0 <= self.lookahead_ms <= LIMIT_MAX_LOOKAHEAD_MS:
            raise AudioConfigValueError(
                f"Limiter lookahead {self.lookahead_ms} ms is outside "
                f"0-{LIMIT_MAX_LOOKAHEAD_MS:.0f} ms",
                context={"field": "limiter_lookahead_ms", "value": self.lookahead_ms},
            )
        if not LIMIT_MIN_RELEASE_MS <= self.release_ms <= LIMIT_MAX_RELEASE_MS:
            raise AudioConfigValueError(
                f"Limiter release {self.release_ms} ms is outside "
                f"{LIMIT_MIN_RELEASE_MS}-{LIMIT_MAX_RELEASE_MS:.0f} ms",
                context={"field": "limiter_release_ms", "value": self.release_ms},
            )


@dataclass(frozen=True)
class GainReductionReport:
    """What the dynamics stage measured, not what it was asked for.

    Attributes:
        max_reduction_db: Largest block gain reduction, in dB.
        mean_reduction_db: Mean block gain reduction over the audible blocks.
        total_reduction_db: Integrated-loudness change plus makeup gain, i.e.
            the average reduction across the whole file.
        output_lufs: The rendered file's integrated loudness.
        output_true_peak_dbtp: The rendered file's true peak.
        blocks: How many blocks contributed to the block figures.
    """

    max_reduction_db: float
    mean_reduction_db: float
    total_reduction_db: float
    output_lufs: float
    output_true_peak_dbtp: float
    blocks: int


def build_dynamics_plugins(
    compressor: CompressorSettings | None,
    limiter: LimiterSettings | None,
) -> list[Any]:
    """Return the pedalboard plugins for *compressor* and *limiter*.

    Args:
        compressor: The compressor to build, or ``None``/bypassed for none.
        limiter: The limiter to build, or ``None``/bypassed for none.

    Returns:
        The plugins in processing order.
    """
    from pedalboard import BrickwallLimiter, Compressor

    plugins: list[Any] = []
    if compressor is not None and not compressor.bypass:
        plugins.append(
            Compressor(
                threshold_db=compressor.threshold_db,
                ratio=compressor.ratio,
                attack_ms=compressor.attack_ms,
                release_ms=compressor.release_ms,
            )
        )
    if limiter is not None and not limiter.bypass:
        plugins.append(
            BrickwallLimiter(
                ceiling_db=limiter.ceiling_dbtp,
                release_ms=limiter.release_ms,
                lookahead_ms=limiter.lookahead_ms,
                true_peak=True,
            )
        )
    return plugins


def _db_to_gain(db: float) -> float:
    """Return *db* as a linear amplitude multiplier."""
    return float(10.0 ** (db / 20.0))


def _block_rms_db(
    audio: npt.NDArray[np.floating[Any]],
    block_samples: int,
) -> npt.NDArray[np.floating[Any]]:
    """Return each whole block's RMS level in dB, mixed to mono.

    Args:
        audio: ``(channels, samples)`` audio.
        block_samples: Block length in samples.

    Returns:
        One dB value per whole block; a trailing partial block is dropped.
    """
    mono = np.mean(np.asarray(audio, dtype=np.float64), axis=0)
    usable = len(mono) - len(mono) % block_samples
    if usable == 0:
        return np.zeros(0, dtype=np.float64)
    blocks = mono[:usable].reshape(-1, block_samples)
    rms = np.sqrt(np.mean(blocks**2, axis=1))
    levels: npt.NDArray[np.floating[Any]] = 20.0 * np.log10(np.maximum(rms, 1e-9))
    return levels


def _summarise_reduction(
    before: npt.NDArray[np.floating[Any]],
    after: npt.NDArray[np.floating[Any]],
    *,
    makeup_db: float,
    sample_rate: int,
) -> tuple[float, float, int]:
    """Return ``(max, mean, blocks)`` block gain reduction in dB.

    Args:
        before: The input array.
        after: The rendered array, makeup gain included.
        makeup_db: The makeup gain applied after compression, added back so the
            figure reports compression rather than the net level change.
        sample_rate: The arrays' sample rate in Hz.

    Returns:
        Largest and mean reduction over the audible blocks, and how many blocks
        contributed. Both figures are ``0.0`` when no block was audible.
    """
    block = max(1, int(sample_rate * REDUCTION_BLOCK_MS / 1000.0))
    before_db = _block_rms_db(before, block)
    after_db = _block_rms_db(after, block)
    count = min(len(before_db), len(after_db))
    if count == 0:
        return 0.0, 0.0, 0
    audible = before_db[:count] > REDUCTION_SILENCE_FLOOR_DB
    if not bool(np.any(audible)):
        return 0.0, 0.0, 0
    reduction = (before_db[:count] - after_db[:count] + makeup_db)[audible]
    reduction = np.maximum(reduction, 0.0)
    return (
        float(np.max(reduction)),
        float(np.mean(reduction)),
        int(reduction.size),
    )


def measure_levels(
    audio: npt.NDArray[np.floating[Any]],
    sample_rate: int,
) -> tuple[float, float]:
    """Measure an array's integrated loudness and true peak through the probe.

    The array is written to a temporary 32-bit float WAV and read back with
    :func:`audio_suite_shared.audio_probe.measure_loudness` — the same FFmpeg
    ``ebur128`` pass every reporting tool uses — so a report figure and the file
    the user plays are measured by one implementation.

    Args:
        audio: ``(channels, samples)`` float audio.
        sample_rate: The array's sample rate in Hz.

    Returns:
        ``(integrated_lufs, true_peak_dbtp)`` as measured from the rendered WAV.
    """
    import soundfile

    from audio_suite_shared.audio_probe import measure_loudness

    samples = np.asarray(audio, dtype=np.float32).T
    with tempfile.TemporaryDirectory(prefix="audiosuite-dyn-") as tmp:
        path = os.path.join(tmp, "render.wav")
        soundfile.write(path, samples, sample_rate, subtype="FLOAT")
        measured = measure_loudness(path)
    peak = measured.true_peak_dbtp
    return float(measured.integrated_lufs), float(peak if peak is not None else 0.0)


def apply_dynamics(
    audio: npt.NDArray[np.floating[Any]],
    compressor: CompressorSettings | None,
    limiter: LimiterSettings | None,
    sample_rate: int,
) -> tuple[npt.NDArray[np.floating[Any]], GainReductionReport]:
    """Render *audio* through the compressor and limiter, and measure it.

    Args:
        audio: ``(channels, samples)`` float audio.
        compressor: The compressor to apply, or ``None``/bypassed for none.
        limiter: The limiter to apply, or ``None``/bypassed for none.
        sample_rate: The array's sample rate in Hz.

    Returns:
        The rendered array and the report measured from it. An inactive pair
        returns *audio* itself with a zero-reduction report, so a bypassed stage
        is bit-transparent.
    """
    plugins = build_dynamics_plugins(compressor, limiter)
    makeup_db = 0.0 if compressor is None or compressor.bypass else compressor.makeup_db
    if not plugins:
        return audio, GainReductionReport(
            max_reduction_db=0.0,
            mean_reduction_db=0.0,
            total_reduction_db=0.0,
            output_lufs=0.0,
            output_true_peak_dbtp=0.0,
            blocks=0,
        )

    from pedalboard import Pedalboard

    rendered: npt.NDArray[np.floating[Any]] = Pedalboard(plugins)(audio, sample_rate)
    if makeup_db:
        rendered = rendered * _db_to_gain(makeup_db)

    input_lufs, _input_peak = measure_levels(audio, sample_rate)
    output_lufs, output_peak = measure_levels(rendered, sample_rate)
    max_reduction, mean_reduction, blocks = _summarise_reduction(
        audio, rendered, makeup_db=makeup_db, sample_rate=sample_rate
    )
    report = GainReductionReport(
        max_reduction_db=max_reduction,
        mean_reduction_db=mean_reduction,
        total_reduction_db=input_lufs - output_lufs + makeup_db,
        output_lufs=output_lufs,
        output_true_peak_dbtp=output_peak,
        blocks=blocks,
    )
    return rendered, report

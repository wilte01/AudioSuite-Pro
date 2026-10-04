"""
dsp_chain.py — Shared Pedalboard DSP chain builder and audio measurement utilities.

Single source of truth for the enhancement DSP chain construction used by both
the Audio Refinery pipeline and the standalone Audio Enhancer.  Eliminates
the risk of the two code paths diverging when chain parameters change.

Pure function — no tkinter, no file I/O, no global state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from pedalboard import Pedalboard

logger = logging.getLogger(f"audio_suite.{__name__}")


def build_enhancement_chain(params: Any) -> Pedalboard:
    """Build the 7-plugin Pedalboard DSP chain from an enhancement params object.

    The *params* argument must expose the same attribute names as
    ``audio_enhancer.core.models.EnhancementParams`` (or any object with
    compatible attributes — the function uses duck typing so both the
    standalone ``EnhancementParams`` dataclass and the pipeline's
    ``audio_refinery.core.models.EnhanceParams`` work without imports).

    Parameters
    ----------
    params : object
        Must provide: noise_gate_threshold_db, compressor_threshold_db,
        compressor_ratio, compressor_attack_ms, compressor_release_ms,
        low_shelf_freq_hz, low_shelf_gain_db, presence_freq_hz,
        presence_gain_db, high_shelf_freq_hz, high_shelf_gain_db,
        output_gain_db, limiter_threshold_db.

    Returns
    -------
    Pedalboard
        A Pedalboard instance with the 7 plugins configured in the
        standard order: NoiseGate → Compressor → LowShelf → Peak →
        HighShelf → Gain → Limiter.
    """
    from pedalboard import (
        Compressor,
        Gain,
        HighShelfFilter,
        Limiter,
        LowShelfFilter,
        NoiseGate,
        PeakFilter,
        Pedalboard,
    )

    return Pedalboard(
        [
            NoiseGate(threshold_db=params.noise_gate_threshold_db, ratio=4.0),
            Compressor(
                threshold_db=params.compressor_threshold_db,
                ratio=params.compressor_ratio,
                attack_ms=params.compressor_attack_ms,
                release_ms=params.compressor_release_ms,
            ),
            LowShelfFilter(
                cutoff_frequency_hz=params.low_shelf_freq_hz,
                gain_db=params.low_shelf_gain_db,
            ),
            PeakFilter(
                cutoff_frequency_hz=params.presence_freq_hz,
                gain_db=params.presence_gain_db,
                q=0.8,
            ),
            HighShelfFilter(
                cutoff_frequency_hz=params.high_shelf_freq_hz,
                gain_db=params.high_shelf_gain_db,
            ),
            Gain(gain_db=params.output_gain_db),
            Limiter(threshold_db=params.limiter_threshold_db),
        ]
    )


def compute_rms_db(audio: npt.NDArray[np.floating[Any]]) -> float:
    """Compute the RMS level of an audio array in dBFS.

    Parameters
    ----------
    audio : np.ndarray
        Audio data of any shape.  A small epsilon is added before the
        log to avoid -inf for silence.

    Returns
    -------
    float
        RMS level in dBFS (e.g. -20.0 for a moderate-level signal).
    """
    rms = float(np.sqrt(np.mean(audio**2)))
    return float(20.0 * np.log10(rms + 1e-9))


def post_chain_clip_check(
    audio: npt.NDArray[np.floating[Any]],
    stage_name: str = "dsp_chain",
) -> npt.NDArray[np.floating[Any]]:
    """Check for clipping after DSP processing.

    Logs a warning if peak > -0.5 dBFS (potential clipping risk).
    Does NOT mutate the array - detection only.

    Parameters
    ----------
    audio : np.ndarray
        DSP output in normalized float scale.
    stage_name : str
        Name of the calling stage for log context.

    Returns
    -------
    np.ndarray
        The input array unchanged.
    """
    from audio_suite_shared.audio_conversion import check_headroom

    ok, peak_db = check_headroom(audio, target_db=-0.5)
    if not ok:
        logger.warning(
            "[%s] Clipping risk: peak at %.1f dBFS (target: < -0.5 dBFS)",
            stage_name,
            peak_db,
        )
    return audio

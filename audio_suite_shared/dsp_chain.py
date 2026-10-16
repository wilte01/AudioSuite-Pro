"""
dsp_chain.py — Shared Pedalboard DSP chain builder and audio measurement utilities.

Single source of truth for the enhancement DSP chain construction used by both
the Audio Refinery pipeline and the standalone Audio Enhancer.  Eliminates
the risk of the two code paths diverging when chain parameters change.

Pure function — no tkinter, no file I/O, no global state.

Changed in 1.1.0: added the five Sprint 1 effects (reverse, karaoke, phaser,
flanger, chorus). Phaser/Chorus join the Pedalboard; flanger is a custom
numpy modulated delay; reverse/karaoke are pre-chain array ops. Added
apply_enhancement_chain() as the ordered orchestrator; with effects off the
base chain output is byte-identical to before.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from pedalboard import Pedalboard

logger = logging.getLogger(f"audio_suite.{__name__}")


def _effect_flag(params: Any, name: str) -> bool:
    """Read an effects toggle from *params*, defaulting to ``False``.

    Uses ``getattr`` so duck-typed parameter objects that predate the Sprint 1
    effects (e.g. tests building a ``SimpleNamespace``) stay valid and keep
    effects off.
    """
    return bool(getattr(params, name, False))


def _base_plugins(params: Any) -> list[Any]:
    """Return the five pre-effects plugins in canonical order."""
    from pedalboard import (
        Compressor,
        HighShelfFilter,
        LowShelfFilter,
        NoiseGate,
        PeakFilter,
    )

    return [
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
    ]


def _tail_plugins(params: Any) -> list[Any]:
    """Return the two post-effects plugins (Gain, Limiter)."""
    from pedalboard import Gain, Limiter

    return [
        Gain(gain_db=params.output_gain_db),
        Limiter(threshold_db=params.limiter_threshold_db),
    ]


def _phaser_plugins(params: Any) -> list[Any]:
    """Return a ``Phaser`` plugin when enabled (post-EQ, pre-flanger)."""
    if not _effect_flag(params, "phaser"):
        return []
    from pedalboard import Phaser

    return [Phaser()]


def _chorus_plugins(params: Any) -> list[Any]:
    """Return a ``Chorus`` plugin when enabled (post-flanger, pre-gain)."""
    if not _effect_flag(params, "chorus"):
        return []
    from pedalboard import Chorus

    return [Chorus()]


def build_enhancement_chain(params: Any) -> Pedalboard:
    """Build the Pedalboard DSP chain from an enhancement params object.

    The *params* argument must expose the same attribute names as
    ``audio_enhancer.core.models.EnhancementParams`` (or any object with
    compatible attributes — the function uses duck typing so both the
    standalone ``EnhancementParams`` dataclass and the pipeline's
    ``audio_refinery.core.models.EnhanceParams`` work without imports).

    Parameters
    ----------
    params : object
        Must provide the 13 base EQ/compressor attributes plus the optional
        Sprint 1 effect toggles ``phaser``/``chorus`` (read via
        :func:`_effect_flag`, absent means off).

    Returns
    -------
    Pedalboard
        A Pedalboard with the base plugins in the standard order
        NoiseGate → Compressor → LowShelf → Peak → HighShelf → Gain →
        Limiter, with ``Phaser`` and ``Chorus`` inserted between HighShelf
        and Gain when enabled.  The ``Flanger`` is a non-pedalboard numpy
        stage and is only applied by :func:`apply_enhancement_chain`; with
        every effect off this returns exactly the original 7-plugin board.
    """
    from pedalboard import Pedalboard

    return Pedalboard(
        _base_plugins(params)
        + _phaser_plugins(params)
        + _chorus_plugins(params)
        + _tail_plugins(params)
    )


def _apply_karaoke(
    audio: npt.NDArray[np.floating[Any]],
    strength: float,
) -> npt.NDArray[np.floating[Any]]:
    """Remove centre-panned content via mid/side anti-phase subtraction.

    ``k = L - R`` cancels anything common to both channels (the "centre"
    where lead vocals usually sit).  *strength* (0.0–1.0) blends between the
    original and the fully karaoke-processed signal.  Mono input is returned
    unchanged (there is no stereo centre to remove).

    Args:
        audio: ``(channels, samples)`` array.
        strength: Blend factor, 0.0 = original, 1.0 = full removal.

    Returns:
        A new array of the same shape.
    """
    if audio.shape[0] < 2:
        return audio
    difference = audio[0] - audio[1]
    blended: npt.NDArray[np.floating[Any]] = np.array(audio, copy=True)
    blended[0] = (1.0 - strength) * audio[0] + strength * difference
    blended[1] = (1.0 - strength) * audio[1] - strength * difference
    return blended


def apply_pre_chain_effects(
    audio: npt.NDArray[np.floating[Any]],
    params: Any,
) -> npt.NDArray[np.floating[Any]]:
    """Apply the pre-chain array effects (reverse, then karaoke) per D17.

    Args:
        audio: ``(channels, samples)`` array.
        params: Enhancement params object exposing ``reverse``, ``karaoke``
            and ``karaoke_strength`` (all optional).

    Returns:
        The processed array (a new array when any effect is active, else the
        input unchanged).
    """
    result = audio
    if _effect_flag(params, "reverse"):
        result = np.flip(result, axis=1)
    if _effect_flag(params, "karaoke"):
        strength = float(getattr(params, "karaoke_strength", 1.0))
        result = _apply_karaoke(result, strength)
    return result


def apply_flanger(
    audio: npt.NDArray[np.floating[Any]],
    sample_rate: int,
    *,
    delay_ms: float = 3.0,
    depth_ms: float = 2.0,
    rate_hz: float = 0.5,
    mix: float = 0.5,
) -> npt.NDArray[np.floating[Any]]:
    """Apply a feed-forward flanger as a modulated fractional delay.

    Pedalboard 0.9 ships no ``Flanger`` (confirmed empirically), so this is a
    custom numpy stage: a sine LFO sweeps the read position of a short delay
    line between ``delay_ms`` and ``delay_ms + depth_ms`` and the delayed
    signal is mixed with the dry signal at *mix*.

    Args:
        audio: ``(channels, samples)`` array.
        sample_rate: Sample rate in Hz.
        delay_ms: Base delay in milliseconds.
        depth_ms: LFO modulation depth in milliseconds.
        rate_hz: LFO rate in Hz.
        mix: Wet/dry mix (0.0 = dry, 1.0 = fully wet).

    Returns:
        A new array of the same shape and dtype.
    """
    n = audio.shape[1]
    if n == 0:
        return audio
    t = np.arange(n, dtype=np.float64) / float(sample_rate)
    lfo = 0.5 + 0.5 * np.sin(2.0 * np.pi * rate_hz * t)
    delay_samples = (delay_ms + depth_ms * lfo) * float(sample_rate) / 1000.0
    positions = np.clip(np.arange(n, dtype=np.float64) - delay_samples, 0.0, n - 1.0)
    lower = np.floor(positions).astype(np.intp)
    upper = np.minimum(lower + 1, n - 1)
    fraction = positions - lower
    delayed = audio[:, lower] * (1.0 - fraction) + audio[:, upper] * fraction
    blended: npt.NDArray[np.floating[Any]] = (1.0 - mix) * audio + mix * delayed
    return blended


def apply_enhancement_chain(
    audio: npt.NDArray[np.floating[Any]],
    sample_rate: int,
    params: Any,
    *,
    apply_effects: bool = True,
) -> npt.NDArray[np.floating[Any]]:
    """Apply the full ordered enhancement chain (D17) to an audio array.

    Order: reverse → karaoke (array ops, pre-chain) → NoiseGate → Compressor →
    LowShelf → Peak → HighShelf → Phaser → Flanger (numpy) → Chorus → Gain →
    Limiter.

    When ``apply_effects`` is False (dry-run) the pre-chain array effects and
    every Sprint 1 effect are bypassed and only the base 7-plugin chain is
    applied — matching the original pipeline's dry-run behaviour.  With all
    effects off the output is byte-identical to the pre-Sprint-1 chain.

    Args:
        audio: ``(channels, samples)`` array.
        sample_rate: Sample rate in Hz.
        params: Enhancement params object (duck-typed as in
            :func:`build_enhancement_chain`).
        apply_effects: Whether to apply the Sprint 1 effects.

    Returns:
        The processed array.
    """
    if not apply_effects:
        passthrough: npt.NDArray[np.floating[Any]] = build_enhancement_chain(params)(
            audio, sample_rate
        )
        return passthrough

    processed: npt.NDArray[np.floating[Any]] = apply_pre_chain_effects(audio, params)
    if _effect_flag(params, "flanger"):
        from pedalboard import Pedalboard

        head = Pedalboard(_base_plugins(params) + _phaser_plugins(params))
        processed = head(processed, sample_rate)
        processed = apply_flanger(processed, sample_rate)
        tail = Pedalboard(_chorus_plugins(params) + _tail_plugins(params))
        processed = tail(processed, sample_rate)
    else:
        processed = build_enhancement_chain(params)(processed, sample_rate)
    return processed


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

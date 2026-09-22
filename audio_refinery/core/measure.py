"""
core/measure.py
Audio measurement utilities for Audio Refinery pipeline.

Provides functions to measure various audio properties before and after
processing stages to enable detailed logging and analysis.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import numpy as np
from pydub import AudioSegment

from audio_suite_shared.audio_conversion import segment_to_numpy
from audio_suite_shared.exceptions import map_to_audio_error
from audio_suite_shared.secure_subprocess import run_secure_subprocess

logger = logging.getLogger(__name__)


def measure_audio_metrics(audio: AudioSegment) -> dict[str, Any]:
    """
    Measure comprehensive audio metrics for analysis.

    Args:
        audio: AudioSegment to measure

    Returns:
        Dictionary containing various audio measurements
    """
    try:
        # Convert to normalized float32 [-1, 1] for analysis via shared module.
        # Channel-first (channels, frames) → transpose to (frames, channels).
        samples_f32, _sr = segment_to_numpy(audio)

        # Basic measurements
        duration_seconds = len(audio) / 1000.0
        sample_rate = audio.frame_rate
        channels = audio.channels

        # Peak and RMS measurements — samples are already normalized [-1, 1],
        # so no division by 32768.0 is needed.
        if audio.channels == 2:
            # Stereo - analyze each channel separately
            left_channel = samples_f32[0]
            right_channel = samples_f32[1]

            peak_left = float(np.max(np.abs(left_channel)))
            peak_right = float(np.max(np.abs(right_channel)))
            peak_db = 20 * math.log10(max(peak_left, peak_right, 1e-10))

            rms_left = float(np.sqrt(np.mean(left_channel.astype(np.float64) ** 2)))
            rms_right = float(np.sqrt(np.mean(right_channel.astype(np.float64) ** 2)))
            rms_db = 20 * math.log10(max((rms_left + rms_right) / 2, 1e-10))
        else:
            # Mono
            peak = float(np.max(np.abs(samples_f32)))
            peak_db = 20 * math.log10(max(peak, 1e-10))

            rms = float(np.sqrt(np.mean(samples_f32.astype(np.float64) ** 2)))
            rms_db = 20 * math.log10(max(rms, 1e-10))

        # Dynamic range (simplified)
        if audio.channels == 2:
            signal_left = samples_f32[0]
            signal_right = samples_f32[1]
            noise_floor_left = float(np.percentile(np.abs(signal_left), 10))
            noise_floor_right = float(np.percentile(np.abs(signal_right), 10))
            noise_floor = max(noise_floor_left, noise_floor_right)
        else:
            noise_floor = float(np.percentile(np.abs(samples_f32), 10))

        noise_floor_db = 20 * math.log10(max(noise_floor, 1e-10))
        dynamic_range_db = peak_db - noise_floor_db

        # Zero crossing rate (rough indicator of noise/silence)
        if audio.channels == 2:
            zcr_left = np.mean(np.diff(np.signbit(signal_left)).astype(np.float64))
            zcr_right = np.mean(np.diff(np.signbit(signal_right)).astype(np.float64))
            zero_crossing_rate = (zcr_left + zcr_right) / 2
        else:
            zero_crossing_rate = np.mean(
                np.diff(np.signbit(samples_f32)).astype(np.float64)
            )

        return {
            "duration_seconds": duration_seconds,
            "sample_rate": sample_rate,
            "channels": channels,
            "peak_db": peak_db,
            "rms_db": rms_db,
            "dynamic_range_db": dynamic_range_db,
            "noise_floor_db": noise_floor_db,
            "zero_crossing_rate": zero_crossing_rate,
        }

    except Exception as e:
        # Broad net is intentional: measurement is a best-effort diagnostic
        # over arbitrary real-world audio. Any failure (decode, numpy
        # conversion, degenerate shape) must degrade to defaults, never raise.
        logger.warning(
            "measure_audio_metrics failed, returning defaults: %s", e, exc_info=True
        )
        return {
            "duration_seconds": len(audio) / 1000.0,
            "sample_rate": audio.frame_rate,
            "channels": audio.channels,
            "peak_db": 0.0,
            "rms_db": -60.0,
            "dynamic_range_db": 0.0,
            "noise_floor_db": -60.0,
            "zero_crossing_rate": 0.0,
            "error": str(e),
        }


def measure_click_characteristics(
    audio: AudioSegment, sensitivity: float = 0.1
) -> dict[str, Any]:
    """
    Measure click characteristics for declick analysis.

    Args:
        audio: AudioSegment to analyze
        sensitivity: Click detection sensitivity threshold

    Returns:
        Dictionary with click-related measurements
    """
    try:
        samples_f32, _sr = segment_to_numpy(audio)  # (channels, frames)
        samples = samples_f32.T  # (frames, channels) for channel indexing
        if audio.channels == 2:
            samples = np.mean(samples, axis=1)  # Convert to mono for analysis
        else:
            samples = samples[:, 0]

        # Simple click detection based on high-frequency content
        # This is a simplified version - the actual declicker
        # uses more sophisticated methods
        # sensitivity is a fraction of full scale on the normalized [-1, 1] input.
        threshold = sensitivity

        # Look for sudden changes (potential clicks)
        diff = np.abs(np.diff(samples))
        potential_clicks = diff > threshold

        # Count consecutive samples above threshold as single clicks.
        # A new click begins wherever potential_clicks transitions False→True,
        # which is equivalent to counting rising edges in the boolean array.
        # np.diff on a bool array gives +1 at rising edges and -1 at falling;
        # prepending False handles the case where the very first sample is a click.
        padded = np.concatenate(([False], potential_clicks))
        rising_edges = np.diff(padded.astype(np.int8))
        click_count = int(np.count_nonzero(rising_edges > 0))

        # Calculate click density (clicks per second)
        duration = len(audio) / 1000.0
        click_density = click_count / duration if duration > 0 else 0

        return {
            "estimated_clicks": click_count,
            "click_density": click_density,
            "detection_threshold": threshold,
            "samples_analyzed": len(samples),
        }

    except Exception as e:
        # Broad net is intentional: click detection runs numpy thresholding
        # on user-supplied audio; worst case must degrade to "no clicks".
        logger.warning("measure_click_characteristics failed: %s", e, exc_info=True)
        return {
            "estimated_clicks": 0,
            "click_density": 0.0,
            "detection_threshold": sensitivity,
            "samples_analyzed": 0,
            "error": str(e),
        }


def measure_silence_characteristics(
    audio: AudioSegment, threshold_db: float = -50
) -> dict[str, Any]:
    """
    Measure silence characteristics for trim analysis.

    Args:
        audio: AudioSegment to analyze
        threshold_db: Silence threshold in dBFS

    Returns:
        Dictionary with silence-related measurements
    """
    try:
        samples_f32, _sr = segment_to_numpy(audio)  # (channels, frames)
        samples = samples_f32.T  # (frames, channels) for channel indexing
        if audio.channels == 2:
            samples = np.mean(samples, axis=1)  # Convert to mono for analysis
        else:
            samples = samples[:, 0]

        # Convert to dBFS on normalized [-1, 1] input.
        samples_db = 20 * np.log10(np.abs(samples) + 1e-10)

        # Find silence regions
        silence_mask = samples_db < threshold_db

        # Count silence segments and total silent samples entirely via NumPy —
        # no Python loop over sample arrays.
        # A segment boundary occurs wherever silence_mask transitions False→True.
        padded = np.concatenate(([False], silence_mask))
        segment_starts = np.diff(padded.astype(np.int8)) > 0
        silence_segments = int(np.count_nonzero(segment_starts))
        total_silence_samples = int(np.count_nonzero(silence_mask))

        # Calculate metrics
        duration = len(audio) / 1000.0
        silence_ratio = total_silence_samples / len(samples) if len(samples) > 0 else 0
        silence_duration = (
            (total_silence_samples / audio.frame_rate) if audio.frame_rate > 0 else 0
        )

        return {
            "silence_segments": silence_segments,
            "silence_ratio": silence_ratio,
            "silence_duration_seconds": silence_duration,
            "threshold_db": threshold_db,
            "total_duration_seconds": duration,
        }

    except Exception as e:
        # Broad net is intentional: silence detection consumes decoded array
        # data that can vary in shape/type; must return defaults on any error.
        mapped = map_to_audio_error(e)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        return {
            "silence_segments": 0,
            "silence_ratio": 0.0,
            "silence_duration_seconds": 0.0,
            "threshold_db": threshold_db,
            "total_duration_seconds": len(audio) / 1000.0,
            "error": str(e),
        }


def measure_enhancement_metrics(audio: AudioSegment) -> dict[str, Any]:
    """
    Measure enhancement-related metrics.

    Args:
        audio: AudioSegment to analyze

    Returns:
        Dictionary with enhancement-related measurements
    """
    try:
        # Get basic metrics first
        basic_metrics = measure_audio_metrics(audio)

        # Add enhancement-specific measurements
        samples_f32, _sr = segment_to_numpy(audio)  # (channels, frames)

        # Calculate frequency distribution (simplified)
        if audio.channels == 2:
            left_channel = samples_f32[0]
            right_channel = samples_f32[1]
            combined = (left_channel + right_channel) / 2
        else:
            combined = samples_f32[0]

        # FFT for frequency analysis (simplified)
        fft = np.fft.fft(combined)
        freqs = np.fft.fftfreq(len(combined), 1 / audio.frame_rate)

        # Focus on relevant frequency ranges
        positive_freqs = freqs[: len(freqs) // 2]
        positive_fft = np.abs(fft[: len(fft) // 2])

        # Low frequency energy (below 250 Hz)
        low_freq_mask = positive_freqs < 250
        low_freq_energy = np.sum(positive_fft[low_freq_mask])

        # Mid frequency energy (250 Hz - 4 kHz)
        mid_freq_mask = (positive_freqs >= 250) & (positive_freqs < 4000)
        mid_freq_energy = np.sum(positive_fft[mid_freq_mask])

        # High frequency energy (above 4 kHz)
        high_freq_mask = positive_freqs >= 4000
        high_freq_energy = np.sum(positive_fft[high_freq_mask])

        # Calculate spectral balance
        total_energy = low_freq_energy + mid_freq_energy + high_freq_energy
        if total_energy > 0:
            low_ratio = low_freq_energy / total_energy
            mid_ratio = mid_freq_energy / total_energy
            high_ratio = high_freq_energy / total_energy
        else:
            low_ratio = mid_ratio = high_ratio = 0.33

        enhancement_metrics = {
            "spectral_balance": {
                "low_ratio": low_ratio,
                "mid_ratio": mid_ratio,
                "high_ratio": high_ratio,
            },
            "frequency_energy": {
                "low_hz": low_freq_energy,
                "mid_hz": mid_freq_energy,
                "high_hz": high_freq_energy,
            },
        }

        # Combine with basic metrics
        return {**basic_metrics, **enhancement_metrics}

    except Exception as e:
        # Broad net is intentional: FFT/energy analysis on arbitrary audio
        # must never abort the pipeline; fall back to basic metrics only.
        logger.warning("measure_enhancement_metrics failed: %s", e, exc_info=True)
        basic_metrics = measure_audio_metrics(audio)
        return {**basic_metrics, "error": str(e)}


def measure_loudness_metrics(
    file_path: Path, target_lufs: float = -16.0
) -> dict[str, Any]:
    """
    Measure loudness metrics using ffmpeg for normalization analysis.

    Args:
        file_path: Path to audio file
        target_lufs: Target loudness in LUFS (default -16.0)

    Returns:
        Dictionary with loudness measurements
    """
    try:
        import shutil

        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        cmd = [
            ffmpeg,
            "-i",
            str(file_path),
            "-af",
            f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ]

        result = run_secure_subprocess(
            "ffmpeg",
            cmd[1:],
            capture_output=True,
            timeout=30,
            check=False,
        )

        if result.returncode != 0:
            return {
                "input_i": 0.0,
                "input_tp": 0.0,
                "input_lra": 0.0,
                "input_thresh": 0.0,
                "error": "ffmpeg failed",
            }

        # Parse JSON output from ffmpeg.
        # loudnorm emits a multi-line JSON block to stderr.  Collect every line
        # that could be part of that block, join them, and parse as a unit.
        # This is more robust than grabbing only the first '{' line, which can
        # silently fail if ffmpeg logs an unrelated '{'-prefixed message first.
        import json

        stderr_text = result.stderr
        # Find the JSON block delimited by the outermost { … }
        brace_start = stderr_text.find("{")
        brace_end = stderr_text.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            json_block = stderr_text[brace_start : brace_end + 1]
            try:
                data = json.loads(json_block)
                return {
                    "input_i": float(data.get("input_i", 0.0)),
                    "input_tp": float(data.get("input_tp", 0.0)),
                    "input_lra": float(data.get("input_lra", 0.0)),
                    "input_thresh": float(data.get("input_thresh", 0.0)),
                }
            except json.JSONDecodeError as json_exc:
                logger.warning(
                    "measure_loudness_metrics: JSON parse failed: %s", json_exc
                )

        return {
            "input_i": 0.0,
            "input_tp": 0.0,
            "input_lra": 0.0,
            "input_thresh": 0.0,
            "error": "Could not parse ffmpeg output",
        }

    except Exception as e:
        # Broad net is intentional: loudness measurement wraps an external
        # ffmpeg call (launch, timeout, parse) — report rather than crash.
        logger.error("measure_loudness_metrics failed: %s", e, exc_info=True)
        return {
            "input_i": 0.0,
            "input_tp": 0.0,
            "input_lra": 0.0,
            "input_thresh": 0.0,
            "error": str(e),
        }

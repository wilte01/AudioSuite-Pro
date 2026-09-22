"""
utils/settings.py
Persists the user's last-used pipeline configuration to a JSON file.

The settings file is stored in the same directory as the application so
it roams with the suite installation rather than being tied to a specific
source folder.  This mirrors the pattern used by suite_config for theme
and font preferences.

File location: <suite_root>/audio_refinery/refinery_settings.json

On first run the file does not exist and defaults are used.  On every
successful processing run (or whenever the user changes a setting) the
file is written so the next launch restores exactly the last-used state.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from audio_suite_shared.cli_dataclasses import (
    VALID_TARGET_LUFS_VALUES,
    validate_target_lufs,
)
from noise_reduction.core.models import NoiseReductionParams

from ..core.models import (
    DeclickParams,
    EnhanceParams,
    NormaliseParams,
    StageConfig,
    TrimParams,
)

logger = logging.getLogger(__name__)

_SETTINGS_FILE = Path(__file__).resolve().parents[1] / "refinery_settings.json"

# Fallback preset used when a stored LUFS value is no longer valid.
_DEFAULT_TARGET_LUFS: float = -16.0


def _sanitise_target_lufs(raw: float) -> float:
    """Return *raw* if it is a permitted preset, otherwise the default.

    Args:
        raw: LUFS value read from the settings file.

    Returns:
        A validated preset value from VALID_TARGET_LUFS_VALUES.
    """
    if not validate_target_lufs(raw):
        return raw
    logger.warning(
        "Stored target_lufs %.1f is not a permitted preset %s — resetting to %.1f",
        raw,
        [f"{v:.1f}" for v in VALID_TARGET_LUFS_VALUES],
        _DEFAULT_TARGET_LUFS,
    )
    return _DEFAULT_TARGET_LUFS


def load() -> StageConfig:
    """
    Load persisted settings and return a populated StageConfig.

    Returns a default StageConfig if the file does not exist or is corrupt.
    Any stored target_lufs value that is not one of the permitted presets is
    silently reset to the default (-16.0) and a warning is logged.

    Reads with ``encoding='utf-8-sig'`` so that files saved with a UTF-8
    BOM (e.g. by Notepad or some Windows editors) are accepted without error.
    The BOM is stripped transparently before JSON parsing.
    """
    if not _SETTINGS_FILE.exists():
        return StageConfig()

    try:
        # utf-8-sig accepts both plain UTF-8 and UTF-8-with-BOM files.
        # Using plain 'utf-8' raises a JSONDecodeError on BOM files because
        # the three BOM bytes appear before the opening '{'.
        with open(_SETTINGS_FILE, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)

        config = StageConfig()

        # Stage toggles
        config.declick = data.get("declick", True)
        config.trim = data.get("trim", True)
        config.enhance = data.get("enhance", True)
        config.normalise = data.get("normalise", True)
        config.reduce_noise = data.get("reduce_noise", False)

        # Declick params
        d = data.get("declick_params", {})
        config.declick_params = DeclickParams(
            sensitivity=d.get("sensitivity", 0.31),
            max_width_ms=d.get("max_width_ms", 2),
        )

        # Trim params
        d = data.get("trim_params", {})
        config.trim_params = TrimParams(
            threshold=d.get("threshold", -50),
            apply_fade=d.get("apply_fade", False),
            fade_in_ms=d.get("fade_in_ms", 500),
            fade_out_ms=d.get("fade_out_ms", 1000),
        )

        # Noise Reduction params
        d = data.get("noise_reduction_params", {})
        config.noise_reduction_params = NoiseReductionParams(
            reduce_hum=d.get("reduce_hum", False),
            hum_frequency=d.get("hum_frequency", 60),
            hum_harmonics=d.get("hum_harmonics", 8),
            hum_quality=d.get("hum_quality", 30.0),
            reduce_broadband=d.get("reduce_broadband", False),
            noise_start_ms=d.get("noise_start_ms", 0),
            noise_end_ms=d.get("noise_end_ms", 500),
            gate_threshold_db=d.get("gate_threshold_db", 3.0),
        )

        # Enhance params
        d = data.get("enhance_params", {})
        config.enhance_params = EnhanceParams(
            preset=d.get("preset", "Moderate"),
            noise_gate_threshold_db=d.get("noise_gate_threshold_db", -65.0),
            compressor_threshold_db=d.get("compressor_threshold_db", -22.0),
            compressor_ratio=d.get("compressor_ratio", 3.5),
            compressor_attack_ms=d.get("compressor_attack_ms", 8.0),
            compressor_release_ms=d.get("compressor_release_ms", 120.0),
            low_shelf_gain_db=d.get("low_shelf_gain_db", 2.5),
            low_shelf_freq_hz=d.get("low_shelf_freq_hz", 100.0),
            presence_gain_db=d.get("presence_gain_db", 2.5),
            presence_freq_hz=d.get("presence_freq_hz", 3500.0),
            high_shelf_gain_db=d.get("high_shelf_gain_db", 4.0),
            high_shelf_freq_hz=d.get("high_shelf_freq_hz", 7000.0),
            output_gain_db=d.get("output_gain_db", 0.0),
            limiter_threshold_db=d.get("limiter_threshold_db", -0.5),
        )

        # Normalise params — validate stored LUFS against permitted presets.
        d = data.get("normalise_params", {})
        raw_lufs = d.get("target_lufs", _DEFAULT_TARGET_LUFS)
        config.normalise_params = NormaliseParams(
            target_lufs=_sanitise_target_lufs(raw_lufs),
            tolerance=d.get("tolerance", 0.5),
        )

        logger.info("Settings loaded from %s", _SETTINGS_FILE.name)
        return config

    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.warning("Could not load settings (%s) — using defaults", exc)
        return StageConfig()


def save(config: StageConfig) -> None:
    """
    Persist the current StageConfig to JSON.

    Writes plain UTF-8 without a BOM so the file is portable and can be
    read back by both ``utf-8`` and ``utf-8-sig`` decoders.  Silently logs
    any write errors rather than surfacing them to the user.
    """
    try:
        p = config.enhance_params
        n = config.normalise_params
        d = config.declick_params
        t = config.trim_params
        nr = config.noise_reduction_params

        data = {
            # Stage toggles
            "declick": config.declick,
            "trim": config.trim,
            "enhance": config.enhance,
            "normalise": config.normalise,
            "reduce_noise": config.reduce_noise,
            # Per-stage params
            "declick_params": {
                "sensitivity": d.sensitivity,
                "max_width_ms": d.max_width_ms,
            },
            "trim_params": {
                "threshold": t.threshold,
                "apply_fade": t.apply_fade,
                "fade_in_ms": t.fade_in_ms,
                "fade_out_ms": t.fade_out_ms,
            },
            "noise_reduction_params": {
                "reduce_hum": nr.reduce_hum,
                "hum_frequency": nr.hum_frequency,
                "hum_harmonics": nr.hum_harmonics,
                "hum_quality": nr.hum_quality,
                "reduce_broadband": nr.reduce_broadband,
                "noise_start_ms": nr.noise_start_ms,
                "noise_end_ms": nr.noise_end_ms,
                "gate_threshold_db": nr.gate_threshold_db,
            },
            "enhance_params": {
                "preset": p.preset,
                "noise_gate_threshold_db": p.noise_gate_threshold_db,
                "compressor_threshold_db": p.compressor_threshold_db,
                "compressor_ratio": p.compressor_ratio,
                "compressor_attack_ms": p.compressor_attack_ms,
                "compressor_release_ms": p.compressor_release_ms,
                "low_shelf_gain_db": p.low_shelf_gain_db,
                "low_shelf_freq_hz": p.low_shelf_freq_hz,
                "presence_gain_db": p.presence_gain_db,
                "presence_freq_hz": p.presence_freq_hz,
                "high_shelf_gain_db": p.high_shelf_gain_db,
                "high_shelf_freq_hz": p.high_shelf_freq_hz,
                "output_gain_db": p.output_gain_db,
                "limiter_threshold_db": p.limiter_threshold_db,
            },
            "normalise_params": {
                "target_lufs": n.target_lufs,
                "tolerance": n.tolerance,
            },
        }

        # Write explicit UTF-8 without BOM — readable by
        # both utf-8 and utf-8-sig decoders.
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

        logger.info("Settings saved to %s", _SETTINGS_FILE.name)

    except (OSError, TypeError) as exc:
        logger.warning("Could not save settings: %s", exc)

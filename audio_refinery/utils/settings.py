"""
utils/settings.py
Persists the user's last-used pipeline configuration to a JSON file.

Location
--------
The live file is **outside the checkout**: ``~/.audiosuite/refinery_settings.json``
(the same directory Library Statistics keeps its cache in).  It used to live
beside the tool (``<suite_root>/audio_refinery/refinery_settings.json``), which
made a tracked file change during ordinary use, so every GUI session left
``git status`` dirty and a real change hid among the noise (PLAN D101/S5-7).

Load order, first readable source wins:

1. the live file — what the last run saved;
2. the old in-checkout file — read once so an existing install keeps its
   settings, logged at INFO, never written again;
3. ``refinery_settings.default.json``, committed and generated from
   ``StageConfig()`` (a test asserts byte equality);
4. ``StageConfig()`` itself, when even the shipped default is unreadable.

``save()`` writes the live file only, creating ``~/.audiosuite`` if needed.  A
corrupt source is logged and skipped rather than fatal: the next source in the
chain still gives the user something sensible.

On first run no file exists above the committed default, so the shipped
defaults apply, and nothing is written until the user runs a pipeline.

Changed in 1.1.0: persist the six Sprint 1 effect fields (reverse,
karaoke, karaoke_strength, phaser, flanger, chorus) so GUI effect toggles
survive a restart.
Changed in 1.4.1: live settings move out of the checkout, with a read-only
legacy fallback and a committed default (PLAN D101).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

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

#: Directory the suite keeps per-user state in (LibraryCache uses it too).
_SETTINGS_DIR = ".audiosuite"
_SETTINGS_NAME = "refinery_settings.json"

#: The live file: written by every save, outside the checkout so a pipeline run
#: cannot dirty a tracked path (D101).
_SETTINGS_FILE = Path.home() / _SETTINGS_DIR / _SETTINGS_NAME

#: Where pre-1.4.1 versions kept the file. Read once on first upgrade, never
#: written, so the user's last-used pipeline survives the move.
_LEGACY_FILE = Path(__file__).resolve().parents[1] / _SETTINGS_NAME

#: The committed defaults, generated from ``StageConfig()``.
_DEFAULT_FILE = Path(__file__).resolve().parents[1] / "refinery_settings.default.json"

# Fallback preset used when a stored LUFS value is no longer valid.
_DEFAULT_TARGET_LUFS: float = -16.0

#: Logged once per process when the legacy file is adopted, so a migrated
#: install says why its old settings are in effect without repeating it.
_legacy_notice_emitted = False


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


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read *path* as a JSON object, or return ``None`` with a warning.

    Args:
        path: The candidate settings file.

    Returns:
        The parsed object, or ``None`` when the file is unreadable, not JSON,
        or not an object.  A corrupt source must never stop the chain: the
        next candidate still has something to offer.
    """
    try:
        # utf-8-sig accepts both plain UTF-8 and UTF-8-with-BOM files (Notepad
        # and some Windows editors add the three BOM bytes).
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.warning("Could not read settings from %s (%s) — skipping it", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("Settings file %s is not a JSON object — skipping it", path)
        return None
    return data


def _from_dict(data: dict[str, Any]) -> StageConfig:
    """Build a :class:`StageConfig` from a settings document.

    Args:
        data: A parsed settings object; missing keys take their defaults.

    Returns:
        The populated config, with any invalid stored LUFS preset reset.
    """
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
        reverse=d.get("reverse", False),
        karaoke=d.get("karaoke", False),
        karaoke_strength=d.get("karaoke_strength", 1.0),
        phaser=d.get("phaser", False),
        flanger=d.get("flanger", False),
        chorus=d.get("chorus", False),
    )

    # Normalise params — validate stored LUFS against permitted presets.
    d = data.get("normalise_params", {})
    raw_lufs = d.get("target_lufs", _DEFAULT_TARGET_LUFS)
    config.normalise_params = NormaliseParams(
        target_lufs=_sanitise_target_lufs(raw_lufs),
        tolerance=d.get("tolerance", 0.5),
    )
    return config


def load() -> StageConfig:
    """
    Load persisted settings and return a populated StageConfig.

    Tries the live file, then the legacy in-checkout file (read once, logged),
    then the committed default, then :class:`StageConfig` defaults.  A source
    that exists but cannot be read is logged and skipped.

    Returns:
        The first readable source's configuration, or defaults when no source
        is usable.  Any stored target_lufs value that is not one of the
        permitted presets is reset to the default (-16.0) with a warning.
    """
    global _legacy_notice_emitted

    for candidate in (_SETTINGS_FILE, _LEGACY_FILE, _DEFAULT_FILE):
        if not candidate.exists():
            continue
        data = _read_json(candidate)
        if data is None:
            continue
        if candidate == _LEGACY_FILE and not _legacy_notice_emitted:
            logger.info(
                "Adopted pipeline settings from the old checkout file %s; "
                "future saves go to %s",
                candidate,
                _SETTINGS_FILE,
            )
            _legacy_notice_emitted = True
        else:
            logger.info("Settings loaded from %s", candidate)
        try:
            return _from_dict(data)
        except (TypeError, ValueError, AttributeError) as exc:
            # A value of the wrong type (a string where a number belongs) must
            # fall through to the next source, not crash the pipeline.
            logger.warning(
                "Settings in %s are invalid (%s) — skipping it", candidate, exc
            )

    return StageConfig()


def _to_dict(config: StageConfig) -> dict[str, Any]:
    """Serialise *config* into the on-disk document.

    Args:
        config: The pipeline configuration to persist.

    Returns:
        The JSON-ready mapping :func:`save` writes.
    """
    p = config.enhance_params
    n = config.normalise_params
    d = config.declick_params
    t = config.trim_params
    nr = config.noise_reduction_params

    return {
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
            "reverse": p.reverse,
            "karaoke": p.karaoke,
            "karaoke_strength": p.karaoke_strength,
            "phaser": p.phaser,
            "flanger": p.flanger,
            "chorus": p.chorus,
        },
        "normalise_params": {
            "target_lufs": n.target_lufs,
            "tolerance": n.tolerance,
        },
    }


def settings_text(config: StageConfig) -> str:
    """Return the exact text :func:`save` writes for *config*.

    Args:
        config: The configuration to serialise.

    Returns:
        UTF-8 JSON text (no BOM, no trailing newline).  Exposed so the test
        that compares the committed default with ``StageConfig()`` uses the
        writer itself rather than a second serialiser that could drift.
    """
    return json.dumps(_to_dict(config), indent=2)


def save(config: StageConfig) -> None:
    """
    Persist the current StageConfig to the live settings file.

    Writes ``~/.audiosuite/refinery_settings.json`` (creating the directory),
    plain UTF-8 without a BOM so the file is portable and can be read back by
    both ``utf-8`` and ``utf-8-sig`` decoders.  A write error is logged rather
    than raised: losing the remembered pipeline must not fail a run.
    """
    try:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(settings_text(config), encoding="utf-8")
        logger.info("Settings saved to %s", _SETTINGS_FILE)
    except (OSError, TypeError) as exc:
        logger.warning("Could not save settings: %s", exc)

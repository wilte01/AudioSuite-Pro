"""
config.py — File Reorganizer preference persistence.

Delegates to ``audio_suite_shared.suite_config`` so that settings are stored
in the shared ``audio_suite_config.json`` at the suite root, alongside all
other tool preferences (project convention — see AGENTS.md).

Also performs a one-time migration of the deprecated tool-local
``reorganizer_config.json`` into the shared config.

``config_path`` parameters are accepted for interface compatibility with the
tempo/mood config-wrapper convention and are otherwise unused.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from audio_suite_shared import suite_config
from file_reorganizer.core.defaults import DEFAULT_SPECIFIC, DEFAULT_VARIOUS

logger = logging.getLogger(__name__)

_KEY_DEST_DIR = "file_reorganizer_dest_dir"
_KEY_ACTION = "file_reorganizer_action"
_KEY_SPECIFIC = "file_reorganizer_specific_pattern"
_KEY_VARIOUS = "file_reorganizer_various_pattern"

_LEGACY_CONFIG_NAME = "reorganizer_config.json"

_LEGACY_MAPPING: dict[str, str] = {
    "dest_dir": _KEY_DEST_DIR,
    "action": _KEY_ACTION,
    "specific_pattern": _KEY_SPECIFIC,
    "various_pattern": _KEY_VARIOUS,
}

_ACTION_DEFAULT = "copy"


def _legacy_config_path(legacy_path: str = "") -> Path:
    """Return the legacy config path, honouring an explicit override."""
    if legacy_path:
        return Path(legacy_path)
    return Path(__file__).resolve().parent.parent / _LEGACY_CONFIG_NAME


def migrate_legacy(legacy_path: str = "") -> None:
    """One-time migration of the tool-local config into the shared config.

    Reads the deprecated ``reorganizer_config.json`` (if present) and copies
    each value into the shared config, but only for keys that are not already
    stored there — a fresh shared value always wins over a stale legacy file.
    The legacy file is deleted after a successful read.

    Args:
        legacy_path: Override for tests; defaults to the historical location.

    Returns:
        None. Read/write failures are logged and never raise.
    """
    path = _legacy_config_path(legacy_path)
    if not path.exists():
        return
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Could not read legacy config %s: %s", path, exc, exc_info=True)
        return
    if not isinstance(data, dict):
        logger.warning("Legacy config %s does not contain a JSON object", path)
        return
    for legacy_key, shared_key in _LEGACY_MAPPING.items():
        if legacy_key not in data:
            continue
        if suite_config.load_value(shared_key) is not None:
            continue
        suite_config.save_value(shared_key, data[legacy_key])
    try:
        path.unlink()
    except OSError as exc:
        logger.warning(
            "Could not delete legacy config %s: %s", path, exc, exc_info=True
        )


def load_settings(config_path: str = "") -> dict[str, str]:
    """Load all persisted settings from the shared suite config.

    Values from a legacy tool-local config (if present) are migrated first.

    Args:
        config_path: Ignored; retained for interface compatibility.

    Returns:
        A dict with ``dest_dir``, ``action``, ``specific_pattern`` and
        ``various_pattern``.  Missing or non-string values fall back to the
        module defaults (action ``"copy"``, templates from the defaults).
    """
    migrate_legacy(config_path)

    def _as_str(key: str, default: str) -> str:
        value = suite_config.load_value(key, default)
        return value if isinstance(value, str) else default

    return {
        "dest_dir": _as_str(_KEY_DEST_DIR, ""),
        "action": _as_str(_KEY_ACTION, _ACTION_DEFAULT),
        "specific_pattern": _as_str(_KEY_SPECIFIC, DEFAULT_SPECIFIC),
        "various_pattern": _as_str(_KEY_VARIOUS, DEFAULT_VARIOUS),
    }


def save_settings(
    config_path: str = "",
    *,
    dest_dir: str = "",
    action: str = _ACTION_DEFAULT,
    specific_pattern: str = DEFAULT_SPECIFIC,
    various_pattern: str = DEFAULT_VARIOUS,
) -> None:
    """Persist all File Reorganizer settings to the shared suite config.

    Args:
        config_path: Ignored; retained for interface compatibility.
        dest_dir: Destination directory path.
        action: ``"copy"`` or ``"move"``.
        specific_pattern: Specific-artist pattern template.
        various_pattern: Various-artist pattern template.

    Returns:
        None.
    """
    suite_config.save_value(_KEY_DEST_DIR, dest_dir)
    suite_config.save_value(_KEY_ACTION, action)
    suite_config.save_value(_KEY_SPECIFIC, specific_pattern)
    suite_config.save_value(_KEY_VARIOUS, various_pattern)

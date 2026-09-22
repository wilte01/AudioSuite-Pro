"""
cd_ripper/core/cd_ripper_config.py
Persists CD Ripper user preferences in the shared ``audio_suite_config.json``.
Currently stores: last output directory.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from audio_suite_shared import suite_config

logger = logging.getLogger(__name__)

# Shared-config key holding the last-used output directory.
_KEY_OUTPUT_DIR = "cd_ripper_output_dir"

_LEGACY_CONFIG_NAME = "cd_ripper_prefs.json"

# Plain-text log file in the cd_ripper package folder, distinct from
# audio_suite_shared's centralized RotatingFileHandler logging -- this one
# specifically captures log_cb output from rip/diagnostic runs so it's easy
# to find without digging through the suite-wide log.
_LOG_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "cd_ripper.log",
    )
)


def get_log_path() -> str:
    """Return the path to the CD Ripper's plain-text log_cb output file."""
    return _LOG_PATH


def _legacy_config_path(legacy_path: str = "") -> Path:
    """Return the legacy config path, honouring an explicit override."""
    if legacy_path:
        return Path(legacy_path)
    return Path(__file__).resolve().parent.parent / _LEGACY_CONFIG_NAME


def migrate_legacy(legacy_path: str = "") -> None:
    """One-time migration of the tool-local config into the shared config.

    Reads the deprecated ``cd_ripper_prefs.json`` (if present) and copies
    the saved ``output_dir`` into the shared config, but only when the
    shared key is not already stored there -- a fresh shared value always
    wins over a stale legacy file.  The legacy file is deleted after a
    successful read.

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
    if isinstance(data.get("output_dir"), str) and data["output_dir"]:
        if suite_config.load_value(_KEY_OUTPUT_DIR) is None:
            suite_config.save_value(_KEY_OUTPUT_DIR, data["output_dir"])
    try:
        path.unlink()
    except OSError as exc:
        logger.warning(
            "Could not delete legacy config %s: %s", path, exc, exc_info=True
        )


def load() -> dict[str, Any]:
    """Return saved prefs, or {} if none exist yet."""
    migrate_legacy()
    output_dir = suite_config.load_value(_KEY_OUTPUT_DIR, "")
    if isinstance(output_dir, str) and output_dir:
        return {"output_dir": output_dir}
    return {}


def save(prefs: dict[str, Any]) -> None:
    """Persist pref keys into the shared config, preserving other keys."""
    migrate_legacy()
    for key, value in prefs.items():
        if key == "output_dir" and isinstance(value, str):
            suite_config.save_value(_KEY_OUTPUT_DIR, value)


def get_output_dir() -> str:
    migrate_legacy()
    output_dir = suite_config.load_value(_KEY_OUTPUT_DIR, "")
    return output_dir if isinstance(output_dir, str) else ""


def set_output_dir(path: str) -> None:
    save({"output_dir": path})

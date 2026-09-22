"""
config.py — Mood Analysis Batch Tagger preference persistence.

Delegates to ``audio_suite_shared.suite_config`` so preferences are stored
in the shared ``audio_suite_config.json`` at the suite root, alongside all
other tool preferences.

The ``config_path`` parameter is accepted but ignored — retained for
backward compatibility and consistency with the suite convention.
"""

import logging

from audio_suite_shared import suite_config

logger = logging.getLogger(__name__)

_VALID_RUN_MODES: tuple[str, ...] = ("Dry Run", "Live Update")


def load_run_mode(config_path: str = "", default: str = "Dry Run") -> str:
    """Read the saved run-mode value from the shared suite config.

    Args:
        config_path: Ignored; retained for interface compatibility.
        default: Value returned when nothing is saved or the saved value is
            invalid.

    Returns:
        One of ``"Dry Run"`` or ``"Live Update"``.
    """
    try:
        saved = suite_config.load_value("mood_analysis_batch_run_mode", default)
    except Exception as exc:
        logger.warning("Could not load run-mode config: %s", exc, exc_info=True)
        return default
    if isinstance(saved, str) and saved in _VALID_RUN_MODES:
        return saved
    return default


def save_run_mode(config_path: str = "", run_mode: str = "Dry Run") -> None:
    """Write the current run-mode value to the shared suite config.

    Args:
        config_path: Ignored; retained for interface compatibility.
        run_mode: ``"Dry Run"`` or ``"Live Update"``.
    """
    try:
        suite_config.save_value("mood_analysis_batch_run_mode", run_mode)
    except Exception as exc:
        logger.warning("Could not save run-mode config: %s", exc, exc_info=True)

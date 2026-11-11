"""
config.py — Mood Analysis Batch Tagger preference persistence.

Delegates to ``audio_suite_shared.suite_config`` so preferences are stored
in the shared ``audio_suite_config.json`` at the suite root, alongside all
other tool preferences.

Changed in 2.4.3: C-I7 dropped the accepted-but-ignored ``config_path``
parameter; it was never read, so removing it removes a misuse seam.

Changed in 2.7.0: the blind-``except`` boundary is named for the BLE001 triage
(WP-7 of ``PLAN_2026-11-03_2.4.1_stop_the_drift.md``, section 10).

"""

import logging

from audio_suite_shared import suite_config

logger = logging.getLogger(__name__)

_VALID_RUN_MODES: tuple[str, ...] = ("Dry Run", "Live Update")


def load_run_mode(default: str = "Dry Run") -> str:
    """Read the saved run-mode value from the shared suite config.

    Args:
        default: Value returned when nothing is saved or the saved value is
            invalid.

    Returns:
        One of ``"Dry Run"`` or ``"Live Update"``.
    """
    try:
        saved = suite_config.load_value("mood_analysis_batch_run_mode", default)
    except Exception as exc:  # noqa: BLE001 - config falls back to the default
        logger.warning("Could not load run-mode config: %s", exc, exc_info=True)
        return default
    if isinstance(saved, str) and saved in _VALID_RUN_MODES:
        return saved
    return default


def save_run_mode(run_mode: str = "Dry Run") -> None:
    """Write the current run-mode value to the shared suite config.

    Args:
        run_mode: ``"Dry Run"`` or ``"Live Update"``.
    """
    try:
        suite_config.save_value("mood_analysis_batch_run_mode", run_mode)
    except Exception as exc:  # noqa: BLE001 - a failed preference write is harmless
        logger.warning("Could not save run-mode config: %s", exc, exc_info=True)

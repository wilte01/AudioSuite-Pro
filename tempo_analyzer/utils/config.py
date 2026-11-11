"""
config.py — Tempo Analyzer scheme preference persistence.

Now delegates to ``audio_suite_shared.suite_config`` so that the
preference is stored in the shared ``audio_suite_config.json`` at
the suite root, alongside all other tool preferences.

Changed in 2.4.3: C-I7 dropped the accepted-but-ignored ``config_path``
parameter, so a caller can no longer pass a path that quietly does nothing.

Changed in 2.7.0: the blind-``except`` boundary is named for the BLE001 triage
(WP-7 of ``PLAN_2026-11-03_2.4.1_stop_the_drift.md``, section 10).

"""

import logging

from audio_suite_shared import suite_config

logger = logging.getLogger(__name__)


def load_scheme(
    valid_schemes: list[str],
    default: str = "Italian",
) -> str:
    """
    Read the saved tempo scheme from the shared suite config.

    Args:
        valid_schemes: List of accepted scheme name strings.
        default:       Fallback value when the key is absent or invalid.

    Returns:
        The saved scheme name if it exists and is valid, otherwise default.
        Never raises.
    """
    saved = suite_config.load_value("tempo_scheme", default)
    if isinstance(saved, str) and saved in valid_schemes:
        return saved
    return default


def save_scheme(scheme_name: str) -> None:
    """
    Write the current scheme name to the shared suite config.

    Args:
        scheme_name: The scheme name string to persist.

    Returns:
        None. Fails silently — not critical if the write doesn't work.
    """
    try:
        suite_config.save_value("tempo_scheme", scheme_name)
    except Exception as exc:  # noqa: BLE001 - a failed preference write is harmless
        logger.warning("Could not save scheme config: %s", exc, exc_info=True)

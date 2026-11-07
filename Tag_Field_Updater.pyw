#!/usr/bin/env python3
"""
Tag_Field_Updater.pyw - Launcher for Tag Field Updater.

Imports directly from the tag_field_updater package.

Changed in 2.5.0: the error dialog is the shared one (plan D-42).
"""

import logging
import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit

guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("tag_field_updater")

from audio_suite_shared.launch_failure import show_error_dialog

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        from tag_field_updater.ui.app import main

        main()
    except Exception as e:  # noqa: BLE001 - the dialog is best effort: a broken Tk cannot report itself
        try:
            show_error_dialog(
                "Startup Error", f"Error starting Tag Field Updater:\n{e}"
            )
        except Exception:
            # The error dialog is best-effort: a broken Tk cannot be reported
            # through Tk. Without this the original failure vanishes entirely.
            logger.exception(
                "Could not show the startup-error dialog; the underlying "
                "startup failure was %s",
                e,
            )

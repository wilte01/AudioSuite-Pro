#!/usr/bin/env python3
"""
File_Reorganizer.pyw - Launcher for Tag-Based File Reorganizer.

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

configure_logging("file_reorganizer")

from audio_suite_shared.launch_failure import show_error_dialog

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        from file_reorganizer import main

        main()
    except ImportError as e:
        try:
            show_error_dialog(
                "Import Error",
                f"Error importing file_reorganizer:\n{e}\n\n"
                "Please ensure file_reorganizer/ is in the same directory.",
            )
        except Exception:
            # The error dialog is best-effort: a broken Tk cannot be reported
            # through Tk. Without this the original failure vanishes entirely.
            logger.exception(
                "Could not show the import-error dialog; the underlying "
                "ImportError was %s",
                e,
            )
    except Exception as e:  # noqa: BLE001 - the dialog is best effort: a broken Tk cannot report itself
        try:
            show_error_dialog("Startup Error", f"Error starting File Reorganizer:\n{e}")
        except Exception:
            # See above: the dialog failing must not hide the startup error.
            logger.exception(
                "Could not show the startup-error dialog; the underlying "
                "startup failure was %s",
                e,
            )

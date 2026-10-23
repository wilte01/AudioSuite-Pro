"""
Pop_Click_Remover.pyw — Launcher for Pop & Click Remover.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("pop_click_remover")

from audio_suite_shared.launcher import parse_cli_args
from pop_click_remover.utils.cli_args import parse
from pop_click_remover.app import main

if __name__ == "__main__":
    parse_cli_args(parse)
    main()

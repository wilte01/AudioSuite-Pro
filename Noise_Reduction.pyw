"""
Noise_Reduction.pyw — Launcher for Noise Reduction.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("noise_reduction")

from audio_suite_shared.launcher import parse_cli_args
from noise_reduction.utils.cli_args import parse
from noise_reduction.app import main

if __name__ == "__main__":
    parse_cli_args(parse)
    main()

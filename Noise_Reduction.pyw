"""
Noise_Reduction.pyw — Launcher for Noise Reduction.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("noise_reduction")

from audio_suite_shared.launcher import parse_cli_args
from noise_reduction.utils.cli_args import parse
from noise_reduction.app import main

if __name__ == "__main__":
    parse_cli_args(parse)
    main()

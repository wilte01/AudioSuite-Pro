"""
Audio_Enhancer.pyw — Launcher for Audio Enhancer.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("audio_enhancer")

from audio_enhancer.app import main

if __name__ == "__main__":
    main()

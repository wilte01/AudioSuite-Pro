"""
Library_Stats.pyw — Launcher for Library Statistics Dashboard.

Scans your music library by reading existing tags (BPM, key, genre, mood, etc.)
and displays the aggregated data in an interactive GUI dashboard.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("library_stats")

if __name__ == "__main__":
    from library_stats.app import main
    main()
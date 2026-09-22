"""
cli_app.py — Unified headless CLI for AudioSuite-Pro.

Usage:
    audiosuite bpm /path/to/dir [--bpm-min 60] [--bpm-max 200] [--dry]
    audiosuite key /path/to/dir [--duration 30] [--dry]
    audiosuite tempo /path/to/dir [--scheme Italian] [--dry]
    audiosuite replaygain /path/to/dir [--target-lufs -14] [--dry]
    audiosuite genre-sync /path/to/dir [--dry]
    audiosuite mood /path/to/dir [--dry]
    audiosuite normalise /path/to/dir [--target-lufs -14] [--tolerance 0.5] [--dry]
    audiosuite scrub /path/to/dir [--preserve-lyrics] [--preserve-album-artist] [--dry]
    audiosuite convert /path/to/dir [--format mp3] [--quality highest]
                                    [--output-dir ...] [--dry]
    audiosuite cue parse /path/to/image.cue [--json]
    audiosuite cue generate /path/to/dir [--title "Album"] [--artist "Artist"]
    audiosuite cue split /path/to/image.cue [--output-dir DIR] [--ffmpeg PATH]
    audiosuite lyrics /path/to/dir [--provider lrclib] [--request-timeout 10]
                        [--skip-existing] [--plain-fallback] [--dry]
    audiosuite silence-trim /path/to/dir [--threshold -50] [--fade] [--dry]
    audiosuite declick /path/to/dir [--sensitivity 0.25] [--max-width 5] [--dry]
    audiosuite enhance /path/to/dir --output-dir ... [--preset Moderate] [--dry]

Commands are registered by importing the corresponding tool's cli module.
"""

from __future__ import annotations

# Import each tool's CLI module so its @cli.command() decorator runs and
# registers the command on the shared group.  Order here determines help
# listing order.
import album_art_normalizer.cli  # noqa: F401, E402  — artnormalize
import album_art_sync.cli  # noqa: F401, E402  — album-art
import album_genre_tagger.cli  # noqa: F401, E402  — album-genre
import asx_extractor.cli  # noqa: F401, E402  — asx-extract
import audio_enhancer.cli  # noqa: F401, E402  — enhance
import audio_fingerprinter.cli  # noqa: F401, E402  — fingerprint
import audio_normalizer.cli  # noqa: F401, E402  — normalise
import audio_refinery.cli  # noqa: F401, E402  — refine
import audio_suite_shared.cue_cli  # noqa: F401, E402  — cue (parse/generate/split)
import bpm_analyzer.cli  # noqa: F401, E402  — bpm
import cd_ripper.cli  # noqa: F401, E402  — cd-rip
import file_reorganizer.cli  # noqa: F401, E402  — reorganize
import genre_sync.cli  # noqa: F401, E402  — genre-sync
import key_detector.cli  # noqa: F401, E402  — key
import library_stats.cli  # noqa: F401, E402  — stats
import lyrics_manager.cli  # noqa: F401, E402  — lyrics
import metadata_scrubber.cli  # noqa: F401, E402  — scrub
import mood_analysis_batch_tagger.cli  # noqa: F401, E402  — mood-analysis-batch
import mood_analyzer.cli  # noqa: F401, E402  — mood-analyzer
import music_format_converter.cli  # noqa: F401, E402 — convert
import noise_reduction.cli  # noqa: F401, E402 — reduce
import pop_click_remover.cli  # noqa: F401, E402  — declick
import replaygain_analyzer.cli  # noqa: F401, E402  — replaygain
import silence_trimmer.cli  # noqa: F401, E402  — silence-trim
import tag_field_updater.cli  # noqa: F401, E402  — tag-update
import tempo_analyzer.cli  # noqa: F401, E402  — tempo

# Re-export shared infrastructure for backward compatibility
from audio_suite_shared.cli_base import _Result, _run_tool, cli  # noqa: F401

if __name__ == "__main__":
    cli()

"""
cli_app.py — Unified headless CLI for AudioSuite-Pro.

Every flag shown below is part of the documented contract and is enforced by
``audio_suite_shared/tests/test_cli_app.py::TestDocumentedFlagParity`` — a flag
that is removed from its command fails the suite unless this block is updated
in the same change.  Shown values are the option defaults unless a value is
part of a usage example.

Usage:
    audiosuite bpm /path/to/dir [--bpm-min 60] [--bpm-max 200] [--duration 30]
                           [--parallel] [--workers 4] [--dry] [--json]
    audiosuite key /path/to/dir [--duration 30] [--parallel] [--workers 4]
                           [--dry] [--json]
    audiosuite tempo /path/to/dir [--scheme Italian] [--dry] [--json]
    audiosuite replaygain /path/to/dir [--target-lufs -14] [--apply-gain]
                           [--dry] [--json]
    audiosuite genre-sync /path/to/dir [--dry] [--json]
    audiosuite album-genre /path/to/dir [--coverage 50] [--dry] [--json]
    audiosuite mood-analyzer /path/to/dir [--duration 90] [--parallel]
                           [--workers 4] [--dry] [--json]
    audiosuite mood-analysis-batch /path/to/dir [--duration 90] [--parallel]
                           [--workers 4] [--dry] [--json]
    audiosuite fingerprint /path/to/dir [--write-tags] [--threshold 0.5]
                           [--max-length 120] [--album-mode] [--dry] [--json]
    audiosuite normalise /path/to/dir [--target-lufs -14] [--tolerance 0.5]
                           [--mode lossless] [--dry] [--json]
    audiosuite scrub /path/to/dir [--preserve-lyrics] [--preserve-album-artist]
                           [--preserve-embedded-art] [--dry] [--json]
    audiosuite tag-edit /path/to/track.mp3 --field comment --clear [--dry] [--json]
    audiosuite tag-update /path/to/dir [--dry] [--json]
    audiosuite lyrics /path/to/dir [--provider lrclib] [--request-timeout 10]
                           [--skip-existing] [--plain-fallback] [--dry] [--json]
    audiosuite album-art /path/to/dir [--embed-size 800] [--min-dimension 500]
                           [--match-threshold 0.85] [--purge] [--dry] [--json]
    audiosuite artnormalize /path/to/dir [--size 800] [--dry] [--json]
    audiosuite asx-extract /path/to/dir [--dry] [--json]
    audiosuite reorganize /path/to/dir --output-dir DIR [--action copy]
                           [--specific-pattern PATTERN]
                           [--various-pattern PATTERN] [--dry] [--json]
    audiosuite stats /path/to/dir [--full] [--completeness] [--detail album_art]
                           [--export-csv PATH] [--export-json PATH]
                           [--incremental] [--refresh] [--json]
    audiosuite convert /path/to/dir [--format flac] [--quality highest]
                           [--sample-rate 44100] [--bit-depth 24]
                           [--output-dir DIR] [--normalize-mp3] [--dry] [--json]
    audiosuite refine /path/to/dir [--output FILE] [--stages declick,trim]
                           [--preset Moderate] [--target-lufs -16]
                           [--tolerance 0.5] [--dry] [--json]
    audiosuite reduce /path/to/dir [--reduce-hum] [--reduce-broadband]
                           [--hum-frequency 60] [--dry] [--json]
    audiosuite declick /path/to/dir [--sensitivity 0.25] [--max-width 5]
                           [--dry] [--json]
    audiosuite silence-trim /path/to/dir [--threshold -50] [--fade]
                           [--fade-in 25] [--fade-out 25] [--dry] [--json]
    audiosuite enhance /path/to/dir --output-dir DIR [--preset Moderate]
                           [--dry] [--json]
    audiosuite cd-rip <drive> --output-dir DIR [--format flac] [--tracks N]
                           [--cue] [--verify twice] [--detect-read-offset]
                           [--dry] [--json]
    audiosuite cue parse /path/to/image.cue [--json]
    audiosuite cue generate /path/to/dir [--title "Album"] [--artist "Artist"]
    audiosuite cue split /path/to/image.cue [--output-dir DIR] [--ffmpeg PATH]

The ``--dry/--live`` pair is the shared run-mode option: ``--dry`` analyses and
reports without writing, ``--live`` writes.  ``--json/--text`` selects the
output format.  ``--log-level`` is a group-level option, so it precedes the
subcommand (``audiosuite --log-level DEBUG bpm /path/to/dir``).

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
import tag_editor.cli  # noqa: F401, E402  — tag-edit
import tag_field_updater.cli  # noqa: F401, E402  — tag-update
import tempo_analyzer.cli  # noqa: F401, E402  — tempo

# Re-export shared infrastructure for backward compatibility
from audio_suite_shared.cli_base import _Result, _run_tool, cli  # noqa: F401

if __name__ == "__main__":
    cli()

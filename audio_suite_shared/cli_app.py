"""
cli_app.py — Unified headless CLI for AudioSuite-Pro.

Every flag shown below is part of the documented contract and is enforced by
``audio_suite_shared/tests/test_cli_app.py::TestDocumentedFlagParity`` — a flag
that is removed from its command fails the suite unless this block is updated
in the same change.  Shown values are the option defaults unless a value is
part of a usage example.

Usage::

    audiosuite bpm /path/to/dir [--bpm-min 75] [--bpm-max 175] [--duration 30]
                           [--parallel] [--workers N] [--dry] [--json]
    audiosuite key /path/to/dir [--duration 30] [--parallel] [--workers N]
                           [--dry] [--json]
    audiosuite tempo /path/to/dir [--scheme Italian] [--dry] [--json]
    audiosuite replaygain /path/to/dir [--target-lufs -14] [--apply-gain]
                           [--dry] [--json]
    audiosuite genre-sync /path/to/dir [--dry] [--json]
    audiosuite album-genre /path/to/dir [--coverage 50] [--dry] [--json]
    audiosuite mood-analyzer /path/to/dir [--duration 90] [--parallel]
                           [--workers N] [--dry] [--json]
    audiosuite mood-analysis-batch /path/to/dir [--duration 90] [--parallel]
                           [--workers N] [--dry] [--json]
    audiosuite fingerprint /path/to/dir [--write-tags] [--threshold 0.5]
                           [--max-length 120] [--album-mode] [--musicbrainz]
                           [--write-isrc] [--dry] [--json]
    audiosuite normalise /path/to/dir [--target-lufs -14] [--tolerance 0.5]
                           [--mode lossless] [--dry] [--json]
    audiosuite scrub /path/to/dir [--preserve-lyrics] [--preserve-album-artist]
                           [--preserve-embedded-art] [--dry] [--json]
    audiosuite tag-edit /path/to/track.mp3 --field comment --clear [--dry] [--json]
    audiosuite tag-update /path/to/dir [--no-plugin-tags] [--dry] [--json]
    audiosuite lyrics /path/to/dir [--provider lrclib] [--request-timeout 10]
                           [--skip-existing] [--plain-fallback] [--dry] [--json]
    audiosuite album-art /path/to/dir [--embed-size 800] [--min-dimension 500]
                           [--match-threshold 0.85] [--purge] [--dry] [--json]
    audiosuite artnormalize /path/to/dir [--size 800] [--dry] [--json]
    audiosuite asx-extract /path/to/dir [--dry] [--json]
    audiosuite reorganize /path/to/dir --output-dir DIR [--action copy]
                           [--specific-pattern PATTERN]
                           [--various-pattern PATTERN] [--dry] [--json]
    audiosuite stats /path/to/dir [--full] [--no-plugin-analysis]
                       [--completeness] [--detail album_art]
                           [--export-csv PATH] [--export-json PATH]
                           [--incremental] [--refresh] [--json]
    audiosuite spectrogram /path/to/dir [--output-dir DIR] [--n-fft 2048]
                           [--hop-length 512] [--start 0] [--end 0]
                           [--max-freq 0] [--db-range 80] [--cmap magma]
                           [--dry] [--json]
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
    audiosuite stems /path/to/dir --output-dir DIR [--model htdemucs]
                           [--stems vocals,drums,bass,other] [--mix]
                           [--device auto] [--dry] [--json]
    audiosuite denoise /path/to/dir [--amount 100] [--dry] [--json]
    audiosuite cd-rip <drive> --output-dir DIR [--format flac] [--tracks N]
                           [--cue] [--verify twice] [--detect-read-offset]
                           [--dry] [--json]
    audiosuite cue parse /path/to/image.cue [--json]
    audiosuite cue generate /path/to/dir [--title "Album"] [--artist "Artist"]
    audiosuite cue split /path/to/image.cue [--output-dir DIR] [--ffmpeg PATH]
    audiosuite plugins list [--json]
    audiosuite plugins enable PLUGIN_ID [--json]
    audiosuite plugins disable PLUGIN_ID [--json]

The ``--dry/--live`` pair is the shared run-mode option: ``--dry`` analyses and
reports without writing, ``--live`` writes.  ``--json/--text`` selects the
output format.  ``--log-level`` is a group-level option, so it precedes the
subcommand (``audiosuite --log-level DEBUG bpm /path/to/dir``).

The JSON contract is defined and locked in
``audio_suite_shared/cli_schema.py``, and the generated JSON Schema document is
committed as ``audio_suite_shared/cli_schema.json``.  Pass ``--json-schema``
before any subcommand (``audiosuite --json-schema``) to print that document and
exit, so an external validator needs no Python import.  Each command's variant
carries an ``examples`` array with a payload recorded from that command and the
fatal-error document it prints when an invocation dies before doing any work,
so both the success and the failure shape a script parses are visible without
running the tool.  Every command
publishes ``schema_version``, ``tool``, ``command``, ``dry_run``, ``total``,
``processed``, ``succeeded``, ``skipped``, ``errors``, ``duration_secs``,
``duration_str`` and ``log_entries`` with those exact names and types, plus
the tool-specific keys that file declares for the command.  Payloads go to
stdout; progress and diagnostics stay on stderr.  ``succeeded`` is
``processed - skipped - errors``, so a script does not need to know which
tool counts attempts.  A breaking change to any of those names bumps
``schema_version``, and ``tests/test_cli_json_schema.py`` invokes every
command and fails when the real payload drifts.

Commands are registered by importing the corresponding tool's cli module.

Changed in 1.4.1: ``--json-schema`` prints the committed document, whose
variants now carry a recorded example payload, so a consumer can read real
output from the install (PLAN D104).
Changed in 1.4.1: those examples also carry each command's fatal-error
document, so a script author can see the failure shape without triggering one
(PLAN D105).
Changed in 1.2.0: documents the fingerprint ``--musicbrainz`` and
``--write-isrc`` flags.
Changed in 1.3.0: registers and documents the ``spectrogram`` command.
Changed in 1.4.0: removed the withdrawn ``shell-install`` / ``shell-uninstall``
commands. The Windows Explorer right-click integration is NOT implemented (see
CHANGELOG.md and PLAN_feature_expansion.md D73).
Changed in 1.4.0: command registration is data-driven and tolerant - a missing
tool module prints the stale-install diagnosis from ``runtime_check`` (naming
``uv run audiosuite``) and leaves the other commands, plus ``doctor``, usable
instead of dying with a bare traceback.
Changed in 2.0.0: registers and documents ``stems``, the ML stem separator
(PLAN_feature_expansion.md Item 6.1).  It is registered like any other command:
without the ``ml`` extra it fails with a named missing dependency rather than
at import time, so ``audiosuite --help`` stays complete on a CPU-only install.
Changed in 2.0.0: registers and documents ``denoise``, the ML denoiser
(Item 6.2).  It shares the ``ml`` extra's import tolerance: the command imports,
``--help`` works, and a run without the extra exits 1 naming what to install.
Changed in 2.1.0: registers the ``plugins`` group (list / enable / disable) and
one command per enabled plugin tool.  A plugin command resolves its entry point
when invoked, so a broken plugin costs its own command and nothing else
(Sprint 7, Item 7.1).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from audio_suite_shared.tool_plugin import ToolManifest

# ``doctor`` must be registered even when a tool package is missing: it is the
# command that reports the gap, so it is imported before the factory list is
# attempted rather than listed in it.  ``plugins`` joins it for the same reason:
# the command that manages third-party code must not depend on any of it.
from audio_suite_shared import doctor_cli as _doctor_cli  # noqa: F401
from audio_suite_shared import plugins_cli as _plugins_cli  # noqa: F401

# Re-export shared infrastructure for backward compatibility.  Imported before
# the registration loop so this module is the one that defines the group.
from audio_suite_shared.cli_base import _Result, _run_tool, cli  # noqa: F401
from audio_suite_shared.runtime_check import missing_modules_message

# Import each tool's CLI module so its @cli.command() decorator runs and
# registers the command on the shared group.  Order here determines help
# listing order.  Each entry is ``(module, command)``; ``doctor`` maps a broken
# package back to the commands it would take down.
_TOOL_CLI_MODULES: tuple[tuple[str, str], ...] = (
    ("album_art_normalizer.cli", "artnormalize"),
    ("album_art_sync.cli", "album-art"),
    ("album_genre_tagger.cli", "album-genre"),
    ("asx_extractor.cli", "asx-extract"),
    ("audio_enhancer.cli", "enhance"),
    ("audio_fingerprinter.cli", "fingerprint"),
    ("audio_normalizer.cli", "normalise"),
    ("audio_refinery.cli", "refine"),
    ("audio_suite_shared.cue_cli", "cue"),
    ("bpm_analyzer.cli", "bpm"),
    ("cd_ripper.cli", "cd-rip"),
    ("file_reorganizer.cli", "reorganize"),
    ("genre_sync.cli", "genre-sync"),
    ("key_detector.cli", "key"),
    ("library_stats.cli", "stats"),
    ("lyrics_manager.cli", "lyrics"),
    ("metadata_scrubber.cli", "scrub"),
    ("ml_denoiser.cli", "denoise"),
    ("mood_analysis_batch_tagger.cli", "mood-analysis-batch"),
    ("mood_analyzer.cli", "mood-analyzer"),
    ("music_format_converter.cli", "convert"),
    ("noise_reduction.cli", "reduce"),
    ("pop_click_remover.cli", "declick"),
    ("replaygain_analyzer.cli", "replaygain"),
    ("silence_trimmer.cli", "silence-trim"),
    ("spectral_viewer.cli", "spectrogram"),
    ("stem_separator.cli", "stems"),
    ("tag_editor.cli", "tag-edit"),
    ("tag_field_updater.cli", "tag-update"),
    ("tempo_analyzer.cli", "tempo"),
)


def _register_tool_commands() -> list[str]:
    """Import every tool CLI module, returning the packages that failed.

    Registration is deliberately tolerant: one missing package must not take
    the whole CLI down, because ``audiosuite doctor`` is the command that
    explains the gap and it has to stay reachable.  The caller warns with
    ``runtime_check.missing_modules_message`` when the list is non-empty.

    Returns:
        The top-level module name of each tool package that could not be
        imported, in registration order.
    """
    failures: list[str] = []
    for module_name, _command in _TOOL_CLI_MODULES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            failures.append(exc.name or module_name)
    return failures


def _register_plugin_commands() -> list[str]:
    """Register one command per enabled plugin tool that declares a callable.

    A plugin command is a real top-level command, so a plugin is as usable
    headless as a first-party tool.  The command resolves its entry point when
    invoked, never at registration, so a broken plugin costs its own command
    and nothing else; the failure is also named by ``audiosuite doctor`` and
    ``audiosuite plugins list``.

    Returns:
        One ``plugin: reason`` line per plugin whose command could not be
        registered.
    """
    from audio_suite_shared.tool_plugin import get_registry

    failures: list[str] = []
    for manifest in get_registry().plugins:
        entry_point = manifest.entry_point
        command_name = manifest.cli_command
        if entry_point is None or command_name is None:
            continue
        if command_name in cli.commands:
            failures.append(
                f"{manifest.id}: command {command_name!r} is already registered"
            )
            continue
        cli.add_command(_plugin_command(command_name, manifest, entry_point))
    return failures


def _plugin_command(
    command_name: str, manifest: "ToolManifest", entry_point: str
) -> click.Command:
    """Build the Click command that runs one plugin tool.

    Args:
        command_name: The subcommand name the manifest declares.
        manifest: The plugin's tool manifest, for the help line.
        entry_point: ``module:callable`` resolved when the command runs.

    Returns:
        The command, ready to add to the group.
    """
    help_text = manifest.description or manifest.name

    @click.command(name=command_name, help=help_text)
    @click.argument("directory", type=click.Path(exists=True, file_okay=False))
    @click.option(
        "--dry/--live", "dry_run", default=False, help="Analyse only, do not write."
    )
    def _plugin_entry(directory: str, dry_run: bool) -> None:
        """Run the plugin's own entry point."""
        from audio_suite_shared.plugin_system import PluginError, get_plugins

        try:
            hook = get_plugins().resolve(entry_point)
        except PluginError as exc:
            raise click.ClickException(str(exc)) from exc
        from audio_suite_shared.plugin_system.extension_points import run_tool_entry

        run_tool_entry(hook, directory, dry_run=dry_run)

    return _plugin_entry


_missing_tool_modules = _register_tool_commands()
if _missing_tool_modules:
    click.echo(missing_modules_message(_missing_tool_modules), err=True)

_plugin_command_failures = _register_plugin_commands()

if __name__ == "__main__":
    cli()

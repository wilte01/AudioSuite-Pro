"""CLI command for Tag Field Updater.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
Changed in 2.1.0: ``--no-plugin-tags`` turns off the plugin system's enabled
tag processors, and the payload counts their edits separately (Sprint 7).
Changed in 2.1.4: the command exits 1 when it reports per-file errors, the
same contract ``finish_run`` applies to the ``_run_tool`` commands (PLAN D9).
Changed in 2.2.0: the filename source (functional backlog F-01).  ``--pattern``
(or ``--action-group``) parses each file's name into tag fields and writes
them.  Filename mode **defaults to a dry run** — ``--live`` is required to
write — because a wrong split produces tags that look authoritative, and the
per-file parse is printed so a mis-parse is visible before it is written.  The
JSON payload is unchanged: the per-file detail is text/log output, and adding a
field would change the locked schema for a report no consumer asked for.
"""

from __future__ import annotations

import json as _json_mod
import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import click
from click.core import ParameterSource

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    cli,
    finish_batch,
)
from audio_suite_shared.cli_schema import build_payload

if TYPE_CHECKING:
    from tag_field_updater.core.processor import ProcessingResult
    from tag_field_updater.utils.config import ActionGroup


@cli.command("tag-update")
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--no-plugin-tags",
    is_flag=True,
    default=False,
    help="Skip tag processors contributed by enabled plugins.",
)
@click.option(
    "--pattern",
    "patterns",
    multiple=True,
    help=(
        "Filename pattern tried in order, e.g. '%track%. %artist% - %title%'. "
        "Repeat for a fallback list; using one switches to the filename source."
    ),
)
@click.option(
    "--action-group",
    default=None,
    help="Load a named pattern set saved in the suite config.",
)
@click.option(
    "--save-action-group",
    default=None,
    help="Save the patterns used by this run under this name.",
)
@click.option(
    "--list-action-groups",
    is_flag=True,
    default=False,
    help="List the saved action groups and exit.",
)
@click.option(
    "--only-fill-blanks/--overwrite",
    "only_fill_blanks",
    default=True,
    help="In filename mode, keep a tag that already has a value (default).",
)
def tag_update_cli(
    directory: str,
    dry_run: bool,
    json: bool,
    no_plugin_tags: bool,
    patterns: tuple[str, ...],
    action_group: str | None,
    save_action_group: str | None,
    list_action_groups: bool,
    only_fill_blanks: bool,
) -> None:
    """Scan and update tag fields from a filename pattern or the slash rule.

    Without a pattern the run applies the tool's original rule: bare '/' in
    tag values becomes '; '.  With ``--pattern`` (or ``--action-group``) each
    file's name is parsed into tag fields and those fields are written; that
    mode reports the parse for every file and runs as a **dry run** unless
    ``--live`` is passed.

    With ``--dry`` the rewrites are computed and reported but nothing is
    written: no file is saved and no undo record is created.

    \b
    Examples:
        audiosuite tag-update /Music --dry
        audiosuite tag-update /Music --live
        audiosuite tag-update /Music --no-plugin-tags
        audiosuite tag-update /Music --pattern "%track%. %artist% - %title%"
        audiosuite tag-update /Music --action-group "Bandcamp" --live
        audiosuite tag-update /Music --pattern "%artist% - %title%" \\
            --save-action-group "Plain"
        audiosuite tag-update /Music --list-action-groups
        audiosuite tag-update /Music --json
    """
    from tag_field_updater.core.filename_patterns import PatternError
    from tag_field_updater.core.processor import TagProcessor
    from tag_field_updater.utils import config as action_config

    if list_action_groups:
        _echo_action_groups(action_config.load_action_groups())
        return

    ctx = click.get_current_context()
    effective_patterns, effective_fill = _resolve_patterns(
        ctx,
        patterns=patterns,
        action_group=action_group,
        only_fill_blanks=only_fill_blanks,
    )

    filename_mode = bool(effective_patterns)
    if filename_mode and ctx.get_parameter_source("dry_run") == ParameterSource.DEFAULT:
        # The parse is the risky half: a wrong split writes plausible wrong
        # tags and the file looks tagged afterwards.  Writing therefore needs
        # a deliberate --live, not merely the absence of --dry.
        dry_run = True
        click.echo(
            "Filename mode defaults to a dry run; pass --live to write the "
            "parsed values.",
            err=True,
        )

    if save_action_group is not None:
        if not filename_mode:
            raise click.UsageError(
                "--save-action-group needs --pattern (or --action-group) to "
                "save: there is nothing to store otherwise."
            )
        saved = action_config.save_action_group(
            save_action_group,
            effective_patterns,
            only_fill_blanks=effective_fill,
        )
        click.echo(
            f"Saved action group {saved.name!r} ({len(saved.patterns)} pattern(s)).",
            err=True,
        )

    try:
        processor = TagProcessor(
            plugins=not no_plugin_tags,
            patterns=effective_patterns,
            only_fill_blanks=effective_fill,
        )
    except PatternError as exc:
        # A bad pattern is a usage error, reported before any file is touched:
        # a half-tagged library is worse than a refused run.
        raise click.UsageError(str(exc)) from exc

    started = time.monotonic()
    with active_batch("tag_field_updater", "tag_edit"):
        results = processor.scan_directory(directory, dry_run=dry_run)

    stats = processor.stats

    # processed_files counts every file the scan attempted, so skipped and
    # failed files are already inside it (the shared schema's rule).
    payload = build_payload(
        "tag-update",
        dry_run=dry_run,
        total=stats.processed_files,
        processed=stats.processed_files,
        skipped=stats.skipped_files,
        errors=stats.error_files,
        duration_secs=time.monotonic() - started,
        log_entries=[],
        directory=directory,
        updated=stats.updated_files,
        plugin_updates=processor.plugin_changes,
        plugin_errors=processor.plugin_errors,
    )

    if json:
        click.echo(_json_mod.dumps(payload, indent=2))
    else:
        if filename_mode:
            _echo_parses(results, dry_run=dry_run)
        updated_label = "would update" if dry_run else "updated"
        click.echo(
            f"  Files processed: {stats.processed_files}\n"
            f"  Files {updated_label}: {stats.updated_files}\n"
            f"  Files skipped:   {stats.skipped_files}\n"
            f"  Errors:          {stats.error_files}"
        )
    # The payload's ``errors`` is what the status reports; a plugin failure is
    # counted in ``plugin_errors`` and is never fatal by contract.
    finish_batch(stats.error_files)


def _resolve_patterns(
    ctx: click.Context,
    *,
    patterns: tuple[str, ...],
    action_group: str | None,
    only_fill_blanks: bool,
) -> tuple[tuple[str, ...], bool]:
    """Work out which patterns and write mode this run uses.

    Precedence is deliberate: an explicitly typed ``--pattern`` beats the
    saved group's patterns, and an explicitly passed
    ``--only-fill-blanks``/``--overwrite`` beats the group's stored mode.  A
    group is a starting point, not an override of what the user just typed.

    Args:
        ctx: The click context, used to tell "passed" from "default".
        patterns: ``--pattern`` values in the order given.
        action_group: Name of a saved group, or None.
        only_fill_blanks: The flag's value as click resolved it.

    Returns:
        ``(patterns, only_fill_blanks)`` for the run.  Empty patterns mean the
        slash rule.

    Raises:
        click.UsageError: If the named group is not saved.
    """
    from tag_field_updater.utils import config as action_config

    effective = tuple(patterns)
    fill = only_fill_blanks

    if action_group is not None:
        group = action_config.get_action_group(action_group)
        if group is None:
            saved = ", ".join(sorted(action_config.load_action_groups())) or "none"
            raise click.UsageError(
                f"unknown action group {action_group!r}; saved groups: {saved}"
            )
        if not effective:
            effective = group.patterns
        if ctx.get_parameter_source("only_fill_blanks") == ParameterSource.DEFAULT:
            fill = group.only_fill_blanks

    return effective, fill


def _echo_action_groups(groups: Mapping[str, ActionGroup]) -> None:
    """Print the saved action groups in a readable block.

    Args:
        groups: Name → group, as loaded from the shared config.
    """
    if not groups:
        click.echo(
            "No action groups saved.  Save one with "
            '--pattern "..." --save-action-group NAME.'
        )
        return
    click.echo(f"Saved action groups ({len(groups)}):")
    for name, group in groups.items():
        click.echo(f"  {name}")
        for pattern in group.patterns:
            click.echo(f"      {pattern}")
        mode = "only fill blanks" if group.only_fill_blanks else "overwrite existing"
        click.echo(f"      mode: {mode}")


def _echo_parses(results: Sequence[ProcessingResult], *, dry_run: bool) -> None:
    """Print one line per file: what its name parsed to, and what was done.

    A dry run's whole job is to make a mis-parse visible before it is written,
    so this prints the captured fields, not just the file name.  A file whose
    name matched no pattern is printed too: silence would look like a clean
    library.

    Args:
        results: The scan's per-file results.
        dry_run: Whether the run wrote nothing.
    """
    verb = "would write" if dry_run else "wrote"
    for result in results:
        name = result.file_path.name
        if not result.filename_pattern:
            if result.error is None:
                click.echo(f"  [NO MATCH] {name}")
            continue
        rendered = " ".join(
            f"{field}='{value}'" for field, value in result.filename_fields
        )
        click.echo(f"  [PARSED] {name} -> {rendered}")
        if result.tags_updated:
            click.echo(f"             {verb}: {', '.join(result.tags_updated)}")
        if result.skipped_fields:
            click.echo(
                f"             kept existing: {', '.join(result.skipped_fields)}"
            )

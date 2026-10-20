"""CLI command for Tempo Analyzer.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
Changed in 1.4.1: an unknown ``--scheme`` raises ``click.UsageError`` (exit 2)
instead of exiting 1 after an echo, so ``--json`` gets the schema's error
document (PLAN D91).
"""

from __future__ import annotations

import json as _json_mod

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _run_tool,
    cli,
)


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option("--scheme", default=None, help="Tempo scheme name. Default: Italian")
def tempo(directory: str, dry_run: bool, json: bool, scheme: str | None) -> None:
    """Derive tempo markings from existing BPM tags."""
    from tempo_analyzer.core.file_processor import run_analysis
    from tempo_analyzer.core.tempo_schemes import DEFAULT_SCHEME, TEMPO_SCHEMES

    scheme_name = scheme or DEFAULT_SCHEME
    markings = TEMPO_SCHEMES.get(scheme_name)
    if not markings:
        # A bad ``--scheme`` value is a usage error, so ``--json`` gets the
        # schema's error document instead of an empty stdout (PLAN D91).
        known = ", ".join(TEMPO_SCHEMES)
        raise click.UsageError(f"Unknown scheme '{scheme_name}'. Known: {known}")

    with active_batch("tempo_analyzer", "tag_edit"):
        result = _run_tool(
            "Tempo Analyzer",
            run_analysis,
            dir_path=directory,
            is_dry_run=dry_run,
            markings=markings,
            scheme_name=scheme_name,
        )
    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("tempo", dry_run=dry_run), indent=2)
        )
    else:
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{result.skipped} skipped, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )

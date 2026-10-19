"""
shell_cli.py — ``audiosuite shell-install`` / ``audiosuite shell-uninstall``.

Registered by importing this module from ``audio_suite_shared/cli_app.py``,
the same non-manifest-command shape as ``audio_suite_shared.cue_cli``: the
Explorer integration has no window and no batch role, so it is a CLI
convenience rather than a manifest tool (PLAN D57).

``--dry`` prints the exact registry keys the install would write and writes
none of them, matching the suite's trace-mode discipline.

Changed in 1.4.0: new module (Sprint 4 Item 4.1, PLAN D57).
"""

from __future__ import annotations

import click

from audio_suite_shared.cli_base import cli
from audio_suite_shared.shell_integration import (
    install,
    planned_keys,
    uninstall,
)


@cli.command(name="shell-install")
@click.option(
    "--flat",
    is_flag=True,
    default=False,
    help="Also write the flat-verb fallback keys (PLAN D58).",
)
@click.option(
    "--dry",
    "dry_run",
    is_flag=True,
    default=False,
    help="Print the registry keys without writing them.",
)
def shell_install(flat: bool, dry_run: bool) -> None:
    """Register the Windows Explorer right-click menu."""
    if dry_run:
        keys = planned_keys(flat=flat)
        click.echo(f"[DRY RUN] Would write {len(keys)} registry keys:")
        for key in keys:
            click.echo(f"  HKCU\\{key}")
        return
    try:
        written = install(flat=flat)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"[OK] Installed {len(written)} registry keys.")
    click.echo("Right-click a supported audio file to use AudioSuite-Pro.")


@cli.command(name="shell-uninstall")
@click.option(
    "--dry",
    "dry_run",
    is_flag=True,
    default=False,
    help="Print the registry keys without removing them.",
)
def shell_uninstall(dry_run: bool) -> None:
    """Remove the Windows Explorer right-click menu."""
    if dry_run:
        keys = planned_keys(flat=True)
        click.echo(f"[DRY RUN] Would remove up to {len(keys)} registry keys:")
        for key in keys:
            click.echo(f"  HKCU\\{key}")
        return
    try:
        removed = uninstall()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"[OK] Removed {len(removed)} registry keys.")

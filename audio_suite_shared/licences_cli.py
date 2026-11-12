"""
licences_cli.py — the ``audiosuite licences`` command.

The texts the installer stages into ``licenses/`` were reachable from the GUI
(Help ▸ Licences) and from the filesystem, but not from a terminal. A headless
user — a packaging script, a licence audit, a CI job that ships this build —
needs the same answer without a display, and needs the folder *this* copy uses
rather than a guess.

Text mode prints each document with its title and its full text: the command's
job is the text, not a pointer to it. ``--json`` publishes the **inventory** —
the folder plus one entry per document with its title, file name and character
count — because a payload carrying 27 kB of licence text would bloat every
recorded example and every consumer's log, while a script that wants the bytes
can read the file the payload names.

Changed in 2.7.0: new module. The resolver is ``audio_suite_shared.licences``,
the same one Help ▸ Licences uses, so the command and the window cannot disagree
about what this installation ships or where it keeps it.
"""

from __future__ import annotations

import json as _json_mod
import time
from typing import Any

import click

from audio_suite_shared import licences
from audio_suite_shared.cli_base import _opt_json, cli, finish_batch
from audio_suite_shared.cli_schema import build_payload

#: Rule between two documents in text mode, at the width the run reports use.
_RULE = "=" * 60


@cli.command("licences")
@_opt_json
def licences_command(json: bool) -> None:
    """Print the licence texts this installation ships.

    \b
    Examples:
        audiosuite licences
        audiosuite licences --json
    """
    started = time.monotonic()
    documents = licences.licence_documents()
    folder = licences.licence_directory()

    entries: list[dict[str, Any]] = []
    rendered: list[tuple[str, str]] = []
    read_errors = 0
    for document in documents:
        try:
            text = licences.read_licence(document)
        except OSError as exc:
            # A file listed a moment ago can still be unreadable. It counts as
            # an error in the payload and the exit status, so a scheduler sees
            # the difference between "this build carries no texts" and "it
            # carries them and cannot show them" (D9/D22).
            read_errors += 1
            click.echo(f"  ERROR: {document.title}: {exc}", err=True)
            continue
        entries.append(
            {"title": document.title, "file": document.path.name, "chars": len(text)}
        )
        rendered.append((document.title, text))

    payload = build_payload(
        "licences",
        dry_run=False,
        total=len(documents),
        processed=len(documents),
        skipped=0,
        errors=read_errors,
        duration_secs=time.monotonic() - started,
        log_entries=[],
        licence_dir=str(folder) if folder is not None else None,
        documents=entries,
    )

    if json:
        click.echo(_json_mod.dumps(payload, indent=2))
    elif not documents:
        # The same sentence the window shows: an older or partial installation
        # should say what is absent rather than print nothing at all.
        click.echo(f"  {licences.missing_message()}")
    else:
        click.echo(f"  {len(rendered)} licence text(s) in {folder}")
        for title, text in rendered:
            click.echo()
            click.echo(f"  {_RULE}")
            click.echo(f"  {title}")
            click.echo(f"  {_RULE}")
            click.echo()
            click.echo(text.rstrip("\n"))

    finish_batch(read_errors)

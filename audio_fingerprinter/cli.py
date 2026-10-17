"""CLI command for Audio Fingerprinter.

Changed in 1.2.0: adds ``--musicbrainz`` and ``--write-isrc`` with their
dependency guards (Sprint 2 Item 2.1), and ``--submit-isrc`` with its
authentication guards (Sprint 2 Item 2.3).
Changed in 1.2.0: reports the submission through
:func:`~audio_fingerprinter.core.models.isrc_submission_note`, the same lines
the Results tab and the Master Driver batch report show.
"""

from __future__ import annotations

import json as _json_mod
from typing import cast

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _run_tool,
    cli,
)

from .core.models import FingerprintParams, isrc_submission_note


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--lookup/--no-lookup",
    default=True,
    help="Query the AcoustID service to identify tracks.",
)
@click.option(
    "--write-tags/--no-write-tags",
    default=False,
    help="Write AcoustID tags to matched files (requires live mode).",
)
@click.option(
    "--threshold",
    default=0.5,
    type=float,
    help="Minimum AcoustID match score (0.0-1.0).",
)
@click.option(
    "--max-length",
    default=120,
    type=int,
    help="Maximum analysed duration in seconds passed to fpcalc.",
)
@click.option("--fpcalc", default=None, type=click.Path(), help="Path to fpcalc.")
@click.option(
    "--api-key",
    default=None,
    help="AcoustID API key (overrides stored/env key for this run).",
)
@click.option(
    "--album-mode/--no-album-mode",
    default=False,
    help=(
        "Cluster each folder's lookups by MusicBrainz release group and "
        "tag only when the album is decided (ambiguous albums stay untagged)."
    ),
)
@click.option(
    "--album-min",
    default=3,
    type=click.IntRange(min=1),
    help="Minimum files voting for one release group to form an album cluster.",
)
@click.option(
    "--write-mbids/--no-write-mbids",
    default=False,
    help=(
        "Also write MusicBrainz identifiers (MUSICBRAINZ_TRACKID / ARTISTID / "
        "ALBUMID) on a match. Requires --write-tags and live mode. ALBUMID is "
        "written only when one release is unambiguous."
    ),
)
@click.option(
    "--mbid-region",
    default="",
    metavar="CC",
    help=(
        "Preferred release country (ISO 3166-1 alpha-2, e.g. GB) used to break "
        "ties between otherwise identical releases when writing MBIDs."
    ),
)
@click.option(
    "--write-isrc/--no-write-isrc",
    default=False,
    help=(
        "Also write the ISRCs MusicBrainz returns for the matched recording. "
        "Requires --musicbrainz, --write-tags and live mode."
    ),
)
@click.option(
    "--musicbrainz/--no-musicbrainz",
    default=False,
    help=(
        "Enrich matches with a direct MusicBrainz lookup: retrieve the "
        "recording's ISRCs and release facts, and let MusicBrainz break an "
        "AcoustID near-tie the file's own tags could not settle. Rate-limited "
        "to one request per second."
    ),
)
@click.option(
    "--submit-isrc/--no-submit-isrc",
    default=False,
    help=(
        "Submit the ISRCs the files' own tags carry to MusicBrainz for their "
        "matched recording, skipping codes already registered. Needs "
        "--musicbrainz. A dry run prints the exact XML payload instead of "
        "posting it; a live run needs MUSICBRAINZ_TOKEN or a stored token."
    ),
)
@click.option(
    "--mb-auth",
    default="oauth",
    type=click.Choice(["oauth", "app-token"]),
    help=(
        "Submission authentication: 'oauth' sends the token as a bearer "
        "token (scope submit_isrc); 'app-token' uses the legacy application "
        "token over HTTP Digest with --mb-user."
    ),
)
@click.option(
    "--mb-user",
    default="",
    type=str,
    help=(
        "MusicBrainz account name, needed only by --mb-auth app-token "
        "(digest sends both a username and the token)."
    ),
)
def fingerprint(
    directory: str,
    dry_run: bool,
    json: bool,
    lookup: bool,
    write_tags: bool,
    threshold: float,
    max_length: int,
    fpcalc: str | None,
    api_key: str | None,
    album_mode: bool,
    album_min: int,
    write_mbids: bool,
    mbid_region: str,
    write_isrc: bool,
    musicbrainz: bool,
    submit_isrc: bool,
    mb_auth: str,
    mb_user: str,
) -> None:
    """Generate Chromaprint fingerprints and identify tracks via AcoustID."""
    from .core.file_processor import run_fingerprinting
    from .core.musicbrainz_client import MBAAuthMethod
    from .utils.api_key import load_api_key
    from .utils.musicbrainz_token import build_auth

    key = api_key or load_api_key()
    if lookup and not key:
        click.echo(
            "Fingerprinting requires an AcoustID API key when lookup is enabled. "
            "Pass --api-key or set the ACOUSTID_API_KEY environment variable.",
            err=True,
        )
        raise SystemExit(1)

    if write_mbids and not write_tags:
        click.echo(
            "--write-mbids adds to the AcoustID tags; it also needs --write-tags.",
            err=True,
        )
        raise SystemExit(1)

    if write_isrc and not write_tags:
        click.echo(
            "--write-isrc adds to the AcoustID tags; it also needs --write-tags.",
            err=True,
        )
        raise SystemExit(1)

    if write_isrc and not musicbrainz:
        click.echo(
            "--write-isrc needs --musicbrainz: ISRCs come from the MusicBrainz "
            "recording lookup, not from AcoustID.",
            err=True,
        )
        raise SystemExit(1)

    if submit_isrc and not musicbrainz:
        click.echo(
            "--submit-isrc needs --musicbrainz: the recording lookup is what "
            "tells the run which ISRCs are already registered, so only the new "
            "ones are submitted.",
            err=True,
        )
        raise SystemExit(1)

    if mb_auth == "app-token" and submit_isrc and not mb_user.strip():
        click.echo(
            "--mb-auth app-token needs --mb-user: HTTP Digest sends both the "
            "account name and the application token.",
            err=True,
        )
        raise SystemExit(1)

    auth = build_auth(cast(MBAAuthMethod, mb_auth), mb_user) if submit_isrc else None
    if submit_isrc and not dry_run and auth is not None and auth.problem:
        # Fail before a long run, not after it: without a usable token a live
        # submission could only report that nothing was sent.
        click.echo(auth.problem, err=True)
        raise SystemExit(1)

    params = FingerprintParams(
        lookup_enabled=lookup,
        write_tags=write_tags,
        is_dry_run=dry_run,
        threshold=threshold,
        max_length=max_length,
        fpcalc_path=fpcalc or "",
        album_mode=album_mode,
        album_min=album_min,
        write_mbids=write_mbids,
        mbid_region=mbid_region.strip().upper(),
        musicbrainz=musicbrainz,
        write_isrc=write_isrc,
        submit_isrc=submit_isrc,
    )

    with active_batch("audio_fingerprinter", "tag_edit"):
        result = _run_tool(
            "Audio Fingerprinter",
            run_fingerprinting,
            dir_path=directory,
            api_key=key,
            params=params,
            mb_auth=auth,
        )

    counts = result.extra.get("counts") or {}
    submission = result.extra.get("isrc_submission") or {}
    if json:
        payload = result.to_dict()
        payload["counts"] = counts
        payload["results"] = [
            r.to_dict() if hasattr(r, "to_dict") else r
            for r in (result.extra.get("results") or [])
        ]
        if submission:
            payload["isrc_submission"] = submission
        click.echo(_json_mod.dumps(payload, indent=2))
    else:
        if submission and dry_run:
            # The preview IS the deliverable of a dry run: print the exact body
            # a live run would post, unprefixed so it can be captured as-is.
            click.echo(submission.get("xml", ""))
        elif submission:
            click.echo(f"  {isrc_submission_note(submission)}", err=True)
            if submission.get("reason"):
                click.echo(f"  {submission['reason']}", err=True)
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{counts.get('identified', 0)} identified, "
            f"{counts.get('tagged', 0)} tagged, "
            f"{result.errors} errors in {result.duration_secs:.1f}s"
        )

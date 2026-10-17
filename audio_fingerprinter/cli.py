"""CLI command for Audio Fingerprinter.

Changed in 1.2.0: adds ``--musicbrainz`` and ``--write-isrc`` with their
dependency guards (Sprint 2 Item 2.1).
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

from .core.models import FingerprintParams


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
) -> None:
    """Generate Chromaprint fingerprints and identify tracks via AcoustID."""
    from .core.file_processor import run_fingerprinting
    from .utils.api_key import load_api_key

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
    )

    with active_batch("audio_fingerprinter", "tag_edit"):
        result = _run_tool(
            "Audio Fingerprinter",
            run_fingerprinting,
            dir_path=directory,
            api_key=key,
            params=params,
        )

    counts = result.extra.get("counts") or {}
    if json:
        payload = result.to_dict()
        payload["counts"] = counts
        payload["results"] = [
            r.to_dict() if hasattr(r, "to_dict") else r
            for r in (result.extra.get("results") or [])
        ]
        click.echo(_json_mod.dumps(payload, indent=2))
    else:
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{counts.get('identified', 0)} identified, "
            f"{counts.get('tagged', 0)} tagged, "
            f"{result.errors} errors in {result.duration_secs:.1f}s"
        )

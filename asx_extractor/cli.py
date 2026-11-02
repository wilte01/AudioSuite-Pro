# Changed in 2.4.0: duplicate dispositions and ASX stubs.
"""CLI command for ASX Playlist Extractor.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).

Changed in 1.4.1: a fatal run now exits 1 instead of 0 (``finish_run``), while a
run whose only failures were per-file keeps its exit status (PLAN D92).
"""

from __future__ import annotations

import json as _json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _run_tool,
    cli,
    finish_run,
)

logger = logging.getLogger(__name__)


def _discover_asx_files(source_dir: Path, recursive: bool) -> list[Path]:
    """Return the ASX playlists to process, sorted.

    Args:
        source_dir: The selected directory.
        recursive: Whether to include sub-folders.

    Returns:
        Playlist paths; the default is the top level only, preserving the
        extractor's existing behaviour.
    """
    candidates = source_dir.rglob("*") if recursive else source_dir.iterdir()
    return sorted(
        {
            path
            for path in candidates
            if path.is_file() and path.suffix.lower() == ".asx"
        }
    )


def _no_op(**kwargs: Any) -> None:
    pass


def _no_op_error(msg: str) -> None:
    pass


def run_cli_extraction(
    dir_path: str,
    is_dry_run: bool = False,
    recursive: bool = False,
    on_progress: Callable[..., None] | None = None,
    on_complete: Callable[..., None] | None = None,
    on_error: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> None:
    """Run ASX extraction with CLI progress callbacks."""
    from asx_extractor.core.asx_parser import process_asx_file
    from asx_extractor.core.file_ops import (
        copy_audio_file,
        recreate_from_stub,
        remove_asx_file,
        write_extraction_log,
    )

    if on_progress is None:
        on_progress = _no_op
    if on_complete is None:
        on_complete = _no_op
    if on_error is None:
        on_error = _no_op_error

    start = time.monotonic()
    source_dir = Path(dir_path).resolve()
    log_entries: list[str] = []

    def _log(msg: str) -> None:
        log_entries.append(msg)
        on_progress(display_text=msg)

    try:
        asx_files = _discover_asx_files(source_dir, recursive)
        total = len(asx_files)
        _log(f"Found {total} ASX file(s) in {source_dir}")
        on_progress(processed=0, total=total, display_text="Scanning ASX files...")

        if not asx_files:
            on_complete(
                total=0,
                processed=0,
                skipped=0,
                errors=0,
                duration_secs=time.monotonic() - start,
                log_entries=log_entries,
            )
            return

        failures: list[dict[str, Any]] = []
        successes: list[dict[str, Any]] = []

        for i, asx_file in enumerate(asx_files):
            result = process_asx_file(asx_file, source_dir)
            if result["success"]:
                successes.append(result)
                _log(f"  [OK] {result['asx_fn']} -> {result['audio_path']}")
            else:
                failures.append(result)
                _log(f"  [FAIL] {result['asx_fn']}: {result['reason']}")
            on_progress(processed=i + 1, total=total)

        if not is_dry_run:
            with active_batch("asx_extractor", "file_reorg"):
                copy_failed: dict[Path, str] = {}
                recreated = 0
                _log("Copying audio files...")
                for item in successes:
                    if item.get("stub") is not None:
                        ok, reason = recreate_from_stub(
                            item["asx_path"], item["audio_path"], item["stub"]
                        )
                        if not ok:
                            copy_failed[item["asx_path"]] = f"RECREATE FAILED: {reason}"
                            _log(f"  [RECREATE FAIL] {item['asx_fn']}: {reason}")
                        else:
                            recreated += 1
                    elif not copy_audio_file(item["audio_path"], source_dir):
                        copy_failed[item["asx_path"]] = "COPY FAILED"
                        _log(f"  [COPY FAIL] {item['audio_path'].name}")

                remaining_successes = []
                _log("Removing ASX files...")
                for item in successes:
                    if item["asx_path"] in copy_failed:
                        failures.append(
                            {
                                "asx_fn": item["asx_fn"],
                                "audio_path": str(item["audio_path"]),
                                "reason": copy_failed[item["asx_path"]],
                            }
                        )
                        continue
                    if not remove_asx_file(item["asx_path"]):
                        failures.append(
                            {
                                "asx_fn": item["asx_fn"],
                                "audio_path": str(item["audio_path"]),
                                "reason": "AUDIO COPIED BUT ASX REMOVAL FAILED",
                            }
                        )
                        continue
                    remaining_successes.append(item)
                successes = remaining_successes
        else:
            recreated = 0
            _log("[Dry Run] Would copy audio and remove ASX files")

        log_path = source_dir / "Extraction_Log.txt"
        write_extraction_log(
            log_path=log_path,
            source_dir=source_dir,
            mode_label="Dry Run (Simulated)"
            if is_dry_run
            else "Execute Extraction (Permanent)",
            successes=successes,
            failures=failures,
        )

        elapsed = time.monotonic() - start
        on_complete(
            total=total,
            processed=len(successes),
            skipped=0,
            errors=len(failures),
            duration_secs=elapsed,
            log_entries=log_entries,
            successes=len(successes),
            failures=len(failures),
            recreated=recreated,
        )
    except (OSError, ValueError) as exc:
        elapsed = time.monotonic() - start
        _log(f"FATAL: {exc}")
        on_complete(
            total=0,
            processed=0,
            skipped=0,
            errors=1,
            duration_secs=elapsed,
            log_entries=log_entries,
        )


@cli.command("asx-extract")
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--recursive/--no-recursive",
    default=False,
    show_default=True,
    help="Also process .asx playlists in sub-folders.",
)
def asx_extract(directory: str, dry_run: bool, json: bool, recursive: bool) -> None:
    """Extract audio files from ASX playlists."""
    result = _run_tool(
        "ASX Playlist Extractor",
        run_cli_extraction,
        dir_path=directory,
        is_dry_run=dry_run,
        recursive=recursive,
    )
    if json:
        click.echo(
            _json.dumps(result.to_payload("asx-extract", dry_run=dry_run), indent=2)
        )
    else:
        ok = result.extra.get("successes", 0)
        fail = result.extra.get("failures", 0)
        recreated = result.extra.get("recreated", 0)
        click.echo(
            f"  Summary: {result.total} ASX files, {ok} extracted, "
            f"{recreated} recreated, {fail} failed, "
            f"{result.errors} errors in {result.duration_secs:.1f}s"
        )
    finish_run(result)

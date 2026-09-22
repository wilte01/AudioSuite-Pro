r"""
verify_refinery_log.py

Scans directories recursively, finds every _refinery_completed.log, and
reports audio files that exist on disk but are NOT recorded in the log
(i.e. files that Audio Refinery has not yet processed or needs to
reprocess).

Detects three classes of issue:
  1. MISSING  — audio file on disk with no matching entry in the log
     (never processed).
  2. CHANGED  — file whose on-disk SHA-256 differs from the logged hash
     (modified since it was processed — Audio Refinery would reprocess
     it).  Only detected when --check-hashes is passed.
  3. ORPHAN   — log entry whose audio file no longer exists on disk
     (harmless but worth knowing about).

Use --fix to safely update the log for CHANGED and ORPHAN entries
without re-running Audio Refinery:
  - CHANGED files get their hash updated to match the current file
  - ORPHAN entries are pruned from the log
  - MISSING files are NEVER auto-added (they genuinely need processing)

Usage:
    python verify_refinery_log.py "D:\Music"
    python verify_refinery_log.py --verbose "D:\Music"
    python verify_refinery_log.py --check-hashes "D:\Music"
    python verify_refinery_log.py --check-hashes --fix "D:\Music"
    python verify_refinery_log.py --check-hashes --fix --quiet "D:\Music"
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

_BLOCK = 65536  # 64 KiB read blocks, matching the registry
LOG_FILENAME = "_refinery_completed.log"

_FALLBACK_EXTENSIONS: set[str] = {
    ".mp3",
    ".flac",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
    ".wma",
    ".aiff",
    ".aif",
}


def _sha256(path: Path) -> str:
    """Compute the hex SHA-256 digest of a file, matching the registry."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_BLOCK):
            h.update(chunk)
    return h.hexdigest()


def _resolve_supported_extensions() -> tuple[set[str], bool]:
    """Resolve the real SUPPORTED_EXTENSIONS set from audio_suite_shared.

    Returns:
        A tuple of (extensions, used_fallback).  used_fallback is True
        if the import failed and a hardcoded fallback was used instead.
    """
    try:
        from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS

        return set(SUPPORTED_EXTENSIONS), False
    except ImportError:
        return _FALLBACK_EXTENSIONS.copy(), True


def _parse_log(log_path: Path) -> dict[str, str]:
    """Parse a _refinery_completed.log into {filename: sha256}.

    Returns an empty dict if the file is missing or unreadable.
    """
    entries: dict[str, str] = {}
    if not log_path.exists():
        return entries
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2:
                    sha, name = parts
                    entries[name] = sha
    except OSError as exc:
        print(f"  [ERROR] Could not read {log_path}: {exc}", file=sys.stderr)
    return entries


def _write_log(log_path: Path, entries: dict[str, str]) -> None:
    """Write entries to _refinery_completed.log in the canonical format."""
    try:
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write("# Audio Refinery — completion registry\n")
            fh.write("# Format: <sha256>  <filename>\n")
            fh.write(
                "# Delete this file or use Reset Progress to reprocess all files.\n"
            )
            for name, sha in sorted(entries.items()):
                fh.write(f"{sha}  {name}\n")
    except OSError as exc:
        print(f"  [ERROR] Could not write {log_path}: {exc}", file=sys.stderr)
        raise


def _find_audio_files(directory: Path, extensions: set[str]) -> set[str]:
    """Return the set of audio filenames directly inside *directory*."""
    return {
        p.name
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in extensions
    }


def _fix_log(
    directory: Path,
    log_entries: dict[str, str],
    audio_files: set[str],
    extensions: set[str],
    dry_run: bool,
    quiet: bool = False,
) -> bool:
    """Update log entries for CHANGED files and prune ORPHAN entries.

    Args:
        directory: The directory being processed.
        log_entries: Current parsed log entries {name: sha}.
        audio_files: Set of audio filenames currently on disk.
        extensions: Audio file extensions (for hashing).
        dry_run: If True, preview changes without writing.
        quiet: If True, suppress [FIX HASH]/[FIX PRUNE]/[FIXED] messages.

    Returns:
        True if any changes were made/would-be-made.
    """
    changed_names: list[str] = []
    updated_entries = log_entries.copy()
    modified = False

    # ── Update hashes for CHANGED files ──────────────────────────────
    for name in sorted(audio_files & set(updated_entries.keys())):
        try:
            disk_hash = _sha256(directory / name)
        except OSError as exc:
            print(f"  [ERROR] Could not hash {name}: {exc}", file=sys.stderr)
            continue
        if disk_hash != updated_entries[name]:
            changed_names.append(name)
            if not dry_run:
                updated_entries[name] = disk_hash
            modified = True

    # ── Prune ORPHAN entries (file no longer on disk) ────────────────
    orphaned = set(updated_entries.keys()) - audio_files
    if orphaned:
        modified = True
        for name in sorted(orphaned):
            if not quiet:
                print(f"  [FIX PRUNE] {name}  —  removing orphaned log entry")
            if not dry_run:
                del updated_entries[name]

    if not changed_names and not orphaned:
        return False

    if changed_names:
        for name in changed_names:
            if not quiet:
                print(f"  [FIX HASH]  {name}  —  updating hash to match current file")

    if dry_run:
        print(
            f"  [DRY RUN] Would write {len(updated_entries)} entries to "
            f"{directory / LOG_FILENAME}"
        )
        return modified

    _write_log(directory / LOG_FILENAME, updated_entries)
    if not quiet:
        print(f"  [FIXED] {directory / LOG_FILENAME} ({len(updated_entries)} entries)")
    return True


def verify_directory(
    directory: Path,
    extensions: set[str],
    verbose: bool,
    report_orphans: bool,
    check_hashes: bool,
) -> int:
    """Verify one directory's _refinery_completed.log against its audio files.

    Args:
        directory: The directory to check.
        extensions: Lowercase set of audio file extensions to consider.
        verbose: If True, also report directories that are fully accounted-for.
        report_orphans: If True, report log entries whose files are gone.
        check_hashes: If True, re-compute SHA-256 of on-disk files to
            detect content changes since processing.

    Returns:
        1 if the directory has issues (missing files, hash mismatches, or
        no log), 0 if everything is clean.
    """
    log_path = directory / LOG_FILENAME
    log_entries = _parse_log(log_path)
    audio_files = _find_audio_files(directory, extensions)

    if not log_entries and not audio_files:
        if verbose:
            print(f"  [INFO] No audio files and no log in {directory}")
        return 0

    # ── Case 1: No log at all ────────────────────────────────────────
    if not log_entries and audio_files:
        print(
            f"  [MISSING LOG] {log_path} does not exist; "
            f"{len(audio_files)} audio file(s) present"
        )
        if verbose:
            for name in sorted(audio_files):
                print(f"      {name}")
        return 1

    # ── Case 2: Log exists, check each audio file ────────────────────
    logged_names: set[str] = set(log_entries.keys())
    issues_here = False

    # Files on disk but not in the log at all (never processed).
    missing = audio_files - logged_names
    if missing:
        issues_here = True
        for name in sorted(missing):
            print(f"  [MISSING] {name}  —  not recorded in {LOG_FILENAME}")

    # Files whose name matches but hash differs (modified since processing).
    if check_hashes:
        for name in sorted(audio_files & logged_names):
            try:
                disk_hash = _sha256(directory / name)
            except OSError as exc:
                print(f"  [ERROR] Could not hash {name}: {exc}", file=sys.stderr)
                continue
            if disk_hash != log_entries[name]:
                issues_here = True
                print(
                    f"  [CHANGED] {name}  —  content hash differs from log "
                    f"(file was modified after processing)"
                )

    # Files in the log but no longer on disk (orphaned entries).
    if report_orphans:
        orphaned = logged_names - audio_files
        if orphaned:
            issues_here = True
            for name in sorted(orphaned):
                print(f"  [ORPHAN] {name}  —  in log but file no longer exists")

    if not issues_here:
        if verbose or audio_files:
            print(
                f"  [OK] {len(audio_files)} audio file(s) — "
                f"all accounted for in {LOG_FILENAME}"
            )
        return 0

    return 1


def _collect_directories(root: Path, recursive: bool) -> list[Path]:
    """Walk the tree starting at *root*, returning all directories."""
    dirs: list[Path] = [root]
    if not recursive:
        return dirs
    try:
        for dirpath, dirnames, _filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in dirnames:
                dirs.append(Path(dirpath) / name)
    except OSError as exc:
        print(f"  [ERROR] {exc}", file=sys.stderr)
    return dirs


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Find audio files that are present on disk but NOT recorded "
            f"in a directory's {LOG_FILENAME} — i.e. files that Audio "
            "Refinery has not yet processed."
        ),
    )
    parser.add_argument(
        "directories",
        nargs="+",
        help="One or more root directories to scan recursively.",
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        default=True,
        help="Walk into subdirectories (default: True).",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only check the top-level directory, do not descend.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Also report directories that are fully accounted-for.",
    )
    parser.add_argument(
        "--no-orphans",
        action="store_true",
        help="Do not report log entries whose files no longer exist.",
    )
    parser.add_argument(
        "--check-hashes",
        action="store_true",
        help=(
            "Re-compute SHA-256 of on-disk files to detect hash "
            "mismatches (slower but thorough)."
        ),
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help=(
            "Update log entries for CHANGED files and prune ORPHAN "
            "entries.  MISSING files are never auto-added (they "
            "genuinely need processing)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --fix, preview changes without writing to the log.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=(
            "With --fix, suppress [FIX HASH], [FIX PRUNE], and [FIXED] "
            "messages; only show actionable items ([MISSING], [MISSING LOG], "
            "[ORPHAN])."
        ),
    )
    args = parser.parse_args()

    recursive = not args.no_recursive

    if args.fix and not args.check_hashes:
        print(
            "NOTE: --fix implies --check-hashes (needs to compute hashes "
            "to detect CHANGED files).",
            file=sys.stderr,
        )
        args.check_hashes = True

    if args.dry_run and not args.fix:
        print(
            "NOTE: --dry-run only applies to --fix.  Running in verify-only mode.",
            file=sys.stderr,
        )

    extensions, used_fallback = _resolve_supported_extensions()
    if used_fallback:
        print(
            "[WARNING] Could not import SUPPORTED_EXTENSIONS from "
            "audio_suite_shared.tag_helper. Using a hardcoded fallback "
            f"list ({sorted(extensions)}).",
            file=sys.stderr,
        )

    total_dirs_with_issues = 0
    total_dirs_fixed = 0
    total_dirs_scanned = 0

    for raw_dir in args.directories:
        root = Path(raw_dir)
        if not root.is_dir():
            print(f"[ERROR] Not a directory: {root}", file=sys.stderr)
            continue

        directories = _collect_directories(root, recursive)
        for directory in directories:
            total_dirs_scanned += 1
            print(f"Scanning: {directory}")

            log_entries = _parse_log(directory / LOG_FILENAME)
            audio_files = _find_audio_files(directory, extensions)

            # Run the fix first (reports are part of the fix output)
            if args.fix and log_entries and audio_files:
                fixed = _fix_log(
                    directory,
                    log_entries,
                    audio_files,
                    extensions,
                    dry_run=args.dry_run,
                    quiet=args.quiet,
                )
                if fixed:
                    total_dirs_fixed += 1
                # Re-read log after fix for accurate verification report
                log_entries = _parse_log(directory / LOG_FILENAME)
                audio_files = _find_audio_files(directory, extensions)

            result = verify_directory(
                directory,
                extensions=extensions,
                verbose=args.verbose,
                report_orphans=not args.no_orphans,
                check_hashes=args.check_hashes,
            )
            if result > 0:
                total_dirs_with_issues += 1

    if total_dirs_fixed > 0:
        print(f"\nFixed {total_dirs_fixed} director(ies).")
    if total_dirs_with_issues > 0:
        print(
            f"Summary: {total_dirs_with_issues} of {total_dirs_scanned} "
            f"directories have remaining issues."
        )
    else:
        print(
            f"\nSummary: All {total_dirs_scanned} director(ies) checked — "
            f"no issues found."
        )


if __name__ == "__main__":
    main()

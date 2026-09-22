r"""
rebuild_refinery_log.py

Retroactively builds a `_refinery_completed.log` for one or more directories
whose audio files are already known to have been fully processed by
Audio Refinery, but for which the log file is missing.

This produces a log file in EXACTLY the format and hash semantics that
Audio Refinery's own `audio_refinery.core.registry.CompletionRegistry`
writes for in-place processing runs:

    <sha256_of_current_file_bytes>  <filename>

Because Audio Refinery's in-place mode overwrites the source file with the
refined output, the file currently on disk IS the refined file. Hashing it
now reproduces the same value the program itself would have stored at the
end of a real run. This script does not invent or guess any hash logic of
its own — it imports `_sha256` directly from the real registry module
(falling back to an equivalent local implementation only if that import is
unavailable, with a loud warning).

ASSUMPTIONS — read before running:
  1. Every audio file in each target directory was *fully* refined already.
     This script cannot verify that. If a directory has a mix of done and
     not-done files, this will falsely mark the not-done ones as complete,
     and Audio Refinery will silently skip them forever after. Only point
     this at directories you are certain are fully and correctly refined.
  2. By default, directories are treated as flat (no subfolder scanning).
     Pass --recursive to walk the full tree instead.
  3. Only files with extensions in SUPPORTED_EXTENSIONS are included,
     matching Audio Refinery's own file discovery filter.

Recursive mode (--recursive):
  Audio Refinery writes a SEPARATE _refinery_completed.log into EVERY
  directory it processes (not one log at the top covering everything).
  This matters because the registry keys entries by bare filename only,
  so a single flattened log spanning multiple subfolders could collide
  same-named files from different albums (e.g. "01.mp3" in two folders).
  To stay compatible, --recursive does NOT produce one combined log: it
  walks the full tree and treats EVERY directory containing audio files
  as its own independent unit, writing that directory's own log scoped
  to only the files directly inside it — exactly as if you had run this
  script separately against each subfolder.

Usage:
    python rebuild_refinery_log.py "D:\Music\SomeAlbum" ["D:\Music\Other" ...]
    python rebuild_refinery_log.py --dry-run "D:\Music\SomeAlbum"
    python rebuild_refinery_log.py --recursive "D:\Music\AllAlbums"

By default this WRITES the log file directly (per user instruction — no
dry-run by default). Pass --dry-run to preview without writing.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from audio_suite_shared.exceptions import AudioFileNotFoundError

_BLOCK = 65536  # match registry.py's read block size exactly

LOG_FILENAME = "_refinery_completed.log"

# Fallback extension list, used ONLY if the real audio_suite_shared module
# cannot be imported. This is a best-effort guess and is flagged loudly,
# per the project's "Submodule Verification Rule" — never silently assume.
_FALLBACK_EXTENSIONS = {
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
    """Compute the hex SHA-256 digest of a file's contents.

    Mirrors audio_refinery.core.registry._sha256 exactly (64 KiB blocks,
    raw bytes, hex digest) so output is byte-for-byte compatible with what
    Audio Refinery itself would have written.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_BLOCK):
            h.update(chunk)
    return h.hexdigest()


def _resolve_supported_extensions() -> tuple[set[str], bool]:
    """Resolve the real SUPPORTED_EXTENSIONS set from audio_suite_shared.

    Returns:
        A tuple of (extensions, used_fallback). used_fallback is True if
        the real module could not be imported and the hardcoded fallback
        list had to be used instead.
    """
    try:
        from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS

        return set(SUPPORTED_EXTENSIONS), False
    except ImportError:
        return set(_FALLBACK_EXTENSIONS), True


def _iter_target_directories(root: Path, recursive: bool) -> list[Path]:
    """Resolve the set of directories to process for one input path.

    Args:
        root: The directory the user passed on the command line.
        recursive: If True, include every nested subdirectory as well.
            If False, only `root` itself is returned (legacy flat
            behaviour).

    Returns:
        A list of directories to run `build_log_for_directory` against,
        each treated fully independently (own log, own file scope).
    """
    if not recursive:
        return [root]

    directories = [root]
    for dirpath, dirnames, _filenames in os.walk(root):
        # Skip hidden/system-style directories some libraries create.
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in dirnames:
            directories.append(Path(dirpath) / name)
    return directories


def build_log_for_directory(
    directory: Path, dry_run: bool, extensions: set[str]
) -> int:
    """Build or preview a _refinery_completed.log for one directory.

    Processes only the files directly inside `directory` — never
    descends into subfolders. Callers handle recursion by invoking this
    once per directory in the tree (see `_iter_target_directories`).

    Args:
        directory: A directory containing already-refined audio files.
        dry_run: If True, only print what would be written; do not touch
            the filesystem.
        extensions: Lowercase file extensions (including the leading
            dot) to treat as audio files, resolved once by the caller.

    Returns:
        The number of files that were (or would be) registered.

    Raises:
        FileNotFoundError: If directory does not exist or is not a
            directory.
    """
    if not directory.is_dir():
        raise AudioFileNotFoundError(f"Not a directory: {directory}")

    log_path = directory / LOG_FILENAME
    if log_path.exists():
        print(f"  [SKIP] {log_path} already exists — not overwriting.")
        return 0

    audio_files = sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in extensions
    )

    if not audio_files:
        print(f"  [INFO] No matching audio files found in {directory}")
        return 0

    entries: dict[str, str] = {}
    for path in audio_files:
        digest = _sha256(path)
        entries[path.name] = digest
        print(f"    {digest}  {path.name}")

    if dry_run:
        print(f"  [DRY RUN] Would write {len(entries)} entries to {log_path}")
        return len(entries)

    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write("# Audio Refinery — completion registry\n")
        fh.write("# Format: <sha256>  <filename>\n")
        fh.write("# Delete this file or use Reset Progress to reprocess all files.\n")
        for name, sha in sorted(entries.items()):
            fh.write(f"{sha}  {name}\n")

    print(f"  [WRITTEN] {log_path} ({len(entries)} entries)")
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Retroactively build a _refinery_completed.log for directories "
            "whose audio files are already known to be fully refined."
        )
    )
    parser.add_argument(
        "directories",
        nargs="+",
        help="One or more directories to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be written without touching the filesystem.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help=(
            "Walk into subdirectories too. Each directory containing audio "
            "files gets its own independent log, matching how Audio "
            "Refinery itself writes logs (one per directory, not one "
            "combined log)."
        ),
    )
    args = parser.parse_args()

    extensions, used_fallback = _resolve_supported_extensions()
    if used_fallback:
        print(
            "[WARNING] Could not import SUPPORTED_EXTENSIONS from "
            "audio_suite_shared.tag_helper. Using a hardcoded fallback "
            f"list ({sorted(extensions)}). This may not exactly match "
            "what Audio Refinery itself considers an audio file. Run this "
            "script in the same environment where audio_suite_shared is "
            "installed if possible.",
            file=sys.stderr,
        )

    total = 0
    dir_count = 0
    for raw_dir in args.directories:
        root = Path(raw_dir)
        if not root.is_dir():
            print(f"Processing: {root}")
            print(f"  [ERROR] Not a directory: {root}", file=sys.stderr)
            continue

        for directory in _iter_target_directories(root, args.recursive):
            print(f"Processing: {directory}")
            dir_count += 1
            try:
                total += build_log_for_directory(
                    directory, dry_run=args.dry_run, extensions=extensions
                )
            except FileNotFoundError as exc:
                print(f"  [ERROR] {exc}", file=sys.stderr)

    print(f"\nDone. {total} file(s) registered across {dir_count} directory(ies).")


if __name__ == "__main__":
    main()

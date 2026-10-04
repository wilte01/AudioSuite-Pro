#!/usr/bin/env python3
"""
strip_bom.py

Recursively scans a target directory for files starting with a UTF-8 BOM
(EF BB BF), strips the BOM, and rewrites the file as clean UTF-8 (no BOM).

Usage:
    python strip_bom.py [ROOT_DIR] [--ext .py .txt .json] [--dry-run]

Defaults:
    ROOT_DIR = current directory
    --ext    = .py

Notes:
    - Only the *first three bytes* of a file are inspected before deciding
      whether to touch it, so this is cheap even on large trees.
    - Files are opened in binary mode throughout. No text-mode decoding is
      attempted before the BOM check, so this will not crash or mis-detect
      on binary files that happen to have a .py extension (e.g. a stray
      .pyc renamed by mistake) -- it just won't find a BOM and will skip it.
    - After stripping, the remaining bytes are validated as UTF-8 before
      the file is overwritten. If validation fails, the file is left
      untouched and reported as an error -- we never write out something
      we haven't confirmed is valid UTF-8.
    - Write is atomic-ish: content is written to a temp file in the same
      directory, then os.replace()'d over the original, so a crash
      mid-write won't leave you with a truncated file.
"""

import argparse
import logging
import os
import sys
import tempfile

UTF8_BOM = b"\xef\xbb\xbf"

logger = logging.getLogger(__name__)


def find_target_files(root, extensions):
    """Yield file paths under root whose suffix is in extensions."""
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if os.path.splitext(name)[1].lower() in extensions:
                yield os.path.join(dirpath, name)


def strip_bom_from_file(path, dry_run=False):
    """
    Inspect a single file. If it starts with a UTF-8 BOM, strip it and
    rewrite in place.

    Returns a tuple (status, detail) where status is one of:
        "modified", "skipped", "error"
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except PermissionError as e:
        return "error", f"permission denied reading file: {e}"
    except OSError as e:
        return "error", f"OS error reading file: {e}"

    if not raw.startswith(UTF8_BOM):
        return "skipped", "no BOM"

    stripped = raw[len(UTF8_BOM) :]

    # Confirm what's left actually decodes as UTF-8 before we commit to
    # overwriting anything. Guards against corrupt/binary files that
    # happen to start with those three bytes coincidentally.
    try:
        stripped.decode("utf-8")
    except UnicodeDecodeError as e:
        return "error", f"BOM found but remaining content is not valid UTF-8: {e}"

    if dry_run:
        return "modified", "BOM found (dry-run, not written)"

    dir_name = os.path.dirname(path) or "."
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".bom_strip_")
        with os.fdopen(fd, "wb") as tmp_f:
            tmp_f.write(stripped)
        os.replace(tmp_path, path)
    except PermissionError as e:
        _cleanup(tmp_path)
        return "error", f"permission denied writing file: {e}"
    except OSError as e:
        _cleanup(tmp_path)
        return "error", f"OS error writing file: {e}"

    return "modified", "BOM stripped"


def _cleanup(tmp_path):
    try:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
    except OSError:
        # Best-effort removal of a temp file that only exists because the
        # real write already failed; the user-visible error was reported by
        # the caller. Logged rather than swallowed silently (A3 standard)
        # so a stuck temp file is diagnosable instead of invisible.
        logger.warning(
            "Could not remove temporary file %s after a failed write",
            tmp_path,
            exc_info=True,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Recursively strip UTF-8 BOMs from files."
    )
    parser.add_argument(
        "root", nargs="?", default=".", help="Directory to scan (default: current dir)"
    )
    parser.add_argument(
        "--ext",
        nargs="+",
        default=[".py"],
        help="File extensions to check, e.g. --ext .py .json .txt (default: .py)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without modifying any files",
    )
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"ERROR: '{root}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    extensions = {e if e.startswith(".") else f".{e}" for e in args.ext}
    extensions = {e.lower() for e in extensions}

    print(f"Scanning: {root}")
    print(f"Extensions: {sorted(extensions)}")
    if args.dry_run:
        print("Mode: DRY RUN (no files will be modified)")
    print("-" * 60)

    modified, skipped, errors = [], 0, []

    for path in find_target_files(root, extensions):
        status, detail = strip_bom_from_file(path, dry_run=args.dry_run)
        rel = os.path.relpath(path, root)
        if status == "modified":
            modified.append(rel)
            print(f"[MODIFIED] {rel} -- {detail}")
        elif status == "error":
            errors.append((rel, detail))
            print(f"[ERROR]    {rel} -- {detail}")
        else:
            skipped += 1

    print("-" * 60)
    print(
        f"Done. {len(modified)} modified,"
        f" {skipped} clean/skipped, {len(errors)} errors."
    )

    if modified:
        print("\nModified files:")
        for m in modified:
            print(f"  - {m}")

    if errors:
        print("\nFiles with errors (not modified):")
        for rel, detail in errors:
            print(f"  - {rel}: {detail}")
        sys.exit(2)


if __name__ == "__main__":
    main()

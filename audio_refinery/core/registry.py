"""
core/registry.py
Completion registry for the Audio Refinery pipeline.

Tracks which files have been fully and successfully processed so that a
retry of the same directory skips already-completed files.

Storage
-------
A plain-text file named `_refinery_completed.log` is written into the
source directory.  Each line records:

    <sha256_of_original>  <filename>

The hash is taken from the file as it existed BEFORE processing began,
so if the original is later modified (e.g. by another tool) its hash
will no longer match and the file will be reprocessed.

Thread safety
-------------
All public methods acquire a threading.Lock so workers can call
mark_done() concurrently without corrupting the log.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_FILENAME = "_refinery_completed.log"
_BLOCK = 65536  # 64 KiB read blocks for hashing


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_BLOCK):
            h.update(chunk)
    return h.hexdigest()


class CompletionRegistry:
    """
    Manages the _refinery_completed.log for one source directory.

    Usage
    -----
        registry = CompletionRegistry(source_dir)
        if registry.is_done(path):
            return  # skip
        ...process file...
        registry.mark_done(path, file_hash)  # pass pre-computed hash
    """

    def __init__(self, source_dir: Path) -> None:
        self._log_path = source_dir / LOG_FILENAME
        self._lock = threading.Lock()
        self._completed: dict[str, str] = {}  # filename → sha256
        self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def hash_file(self, path: Path) -> str:
        """Compute and return the SHA-256 of path (call before processing)."""
        return _sha256(path)

    def is_done(self, path: Path, file_hash: str) -> bool:
        """
        Return True if this file has already been processed successfully.
        Matches on both filename and hash so renamed or modified files
        are treated as new.
        """
        with self._lock:
            stored = self._completed.get(path.name)
            return stored == file_hash

    def mark_done(self, path: Path, file_hash: str) -> None:
        """Record a successful completion and persist to disk."""
        with self._lock:
            self._completed[path.name] = file_hash
            self._save()

    def reset(self) -> None:
        """Delete all completion records for this directory."""
        with self._lock:
            self._completed.clear()
            try:
                self._log_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Registry reset: could not delete log — %s", exc)

    @property
    def completed_count(self) -> int:
        with self._lock:
            return len(self._completed)

    @property
    def log_path(self) -> Path:
        return self._log_path

    # ── Private ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Parse the log file if it exists."""
        if not self._log_path.exists():
            return
        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        sha, name = parts
                        self._completed[name] = sha
            logger.info(
                "Registry loaded: %d completed entries from %s",
                len(self._completed),
                self._log_path.name,
            )
        except OSError as exc:
            logger.warning("Could not read registry log: %s", exc)

    def _save(self) -> None:
        """Rewrite the full log file (called under lock)."""
        try:
            with open(self._log_path, "w", encoding="utf-8") as fh:
                fh.write("# Audio Refinery — completion registry\n")
                fh.write("# Format: <sha256>  <filename>\n")
                fh.write(
                    "# Delete this file or use Reset Progress to reprocess all files.\n"
                )
                for name, sha in sorted(self._completed.items()):
                    fh.write(f"{sha}  {name}\n")
        except OSError as exc:
            logger.error("Could not write registry log: %s", exc, exc_info=True)

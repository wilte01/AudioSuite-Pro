# Changed in 2.4.0: duplicate dispositions and ASX stubs.
"""
file_ops.py
File operations for ASX Extractor: copy audio, remove ASX playlists,
write the extraction log.

All functions are free of tkinter and self — callers pass in every
value they need.

The send2trash import guard is preserved: if the library is absent,
removal falls back to Path.unlink().

copy_audio_file() and remove_asx_file() report outcome via a bool
return value rather than swallowing exceptions: every failure is both
logged (via the shared AudioSuiteError mapping, full traceback) and
surfaced to the caller, so app.py can route failed items into the
failure log instead of mis-reporting them as successful extractions.
"""

import datetime
import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from audio_suite_shared.asx_stub import StubMetadata, apply_tags, derive_restore_name
from audio_suite_shared.batch_undo import record_file_reorg_snapshot
from audio_suite_shared.exceptions import map_to_audio_error, user_message_for

try:
    from send2trash import send2trash

    SEND2TRASH_AVAILABLE = True
except ImportError:
    SEND2TRASH_AVAILABLE = False

logger = logging.getLogger(__name__)


def _sha256(path: Path) -> str:
    """Return the file's hex SHA-256 digest.

    Args:
        path: File to hash.

    Returns:
        The digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audio_digest(path: Path) -> str:
    """Return a digest of the file's decoded audio samples.

    A tag write necessarily changes a file's container bytes, so the restored
    file can never be byte-identical to the keeper.  The invariant that matters
    is that its *audio* is unchanged; this decodes both files and hashes the
    raw PCM.

    Args:
        path: The audio file to decode.

    Returns:
        The SHA-256 of the decoded sample data.
    """
    from pydub import AudioSegment

    return hashlib.sha256(AudioSegment.from_file(path).raw_data).hexdigest()


def recreate_from_stub(
    asx_path: Path, keeper_path: Path, metadata: StubMetadata
) -> tuple[bool, str]:
    """Recreate the stubbed file from the keeper and the stub's tags.

    The copy is built at a temporary path in the destination folder, its tags
    are written there, its bytes are checked against the keeper, and only then
    is it atomically renamed to the final name.  On any failure the temporary
    file is removed and the stub is left untouched.

    Args:
        asx_path: The stub being restored.
        keeper_path: The audio the stub points at.
        metadata: The tag snapshot read from the stub.

    Returns:
        ``(True, "")`` on success, or ``(False, reason)`` when nothing was
        finalised.
    """
    destination = derive_restore_name(asx_path, keeper_path)
    # Keep the real extension on the temporary file: the tag handler is chosen
    # by suffix, and a ``.tmp`` staging name is not a supported audio format.
    temporary = destination.with_name(f".{destination.stem}.tmp{destination.suffix}")
    try:
        shutil.copy2(keeper_path, temporary)
        apply_tags(temporary, metadata)
        if _audio_digest(temporary) != _audio_digest(keeper_path):
            raise ValueError("the recreated audio does not match the kept file")
        os.replace(temporary, destination)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        logger.error(
            "recreate_from_stub failed for %s: %s", asx_path, exc, exc_info=True
        )
        return False, str(exc)
    record_file_reorg_snapshot(str(keeper_path), str(destination), "copy")
    return True, ""


def copy_audio_file(audio_path: Path, destination_dir: Path) -> bool:
    """
    Copy an audio file into destination_dir, preserving metadata.

    Failures are logged with full context (never silent) and reported
    via the return value so the caller can record the item as a
    failure rather than a success.

    Args:
        audio_path:      Source audio file to copy.
        destination_dir: Directory to copy the file into.

    Returns:
        True if the copy succeeded, False otherwise.
    """
    try:
        shutil.copy2(audio_path, destination_dir)
        dest_path = destination_dir / audio_path.name
        record_file_reorg_snapshot(str(audio_path), str(dest_path), "copy")
        return True
    except (OSError, ValueError) as exc:
        mapped = map_to_audio_error(exc, context={"audio_path": str(audio_path)})
        logger.error(
            "[%s] copy_audio_file failed for %s: %s",
            type(mapped).__name__,
            audio_path,
            user_message_for(mapped),
            exc_info=True,
        )
        return False


def remove_asx_file(asx_path: Path) -> bool:
    """
    Send asx_path to the system Trash (send2trash) or delete it
    permanently if send2trash is not installed.

    Failures are logged with full context (never silent) and reported
    via the return value so the caller can record the item as a
    failure rather than a success.

    Args:
        asx_path: Path to the .asx playlist file to remove.

    Returns:
        True if the file was removed/trashed successfully, False otherwise.
    """
    try:
        if SEND2TRASH_AVAILABLE:
            send2trash(str(asx_path.resolve()))
        else:
            asx_path.unlink()
        return True
    except (OSError, ValueError) as exc:
        mapped = map_to_audio_error(exc, context={"asx_path": str(asx_path)})
        logger.error(
            "[%s] remove_asx_file failed for %s: %s",
            type(mapped).__name__,
            asx_path,
            user_message_for(mapped),
            exc_info=True,
        )
        return False


def write_extraction_log(
    log_path: Path,
    source_dir: Path,
    mode_label: str,
    successes: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> bool:
    """
    Write the two-section extraction report to log_path.

    Args:
        log_path:   Full path to the output .txt file.
        source_dir: The directory that was processed.
        mode_label: Human-readable mode string for the report header
                    (e.g. "Dry Run (Simulated)").
        successes:  List of success dicts from asx_parser.process_asx_file.
        failures:   List of failure dicts from asx_parser.process_asx_file.

    Raises:
        Nothing — errors are surfaced via the returned bool.

    Returns:
        True on success, False on write error.
    """
    try:
        with log_path.open("w", encoding="utf-8") as log:
            # Header
            log.write("ASX EXTRACTION REPORT\n")
            log.write(f"Processed Directory: {source_dir}\n")
            log.write(
                f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            log.write(f"Mode: {mode_label}\n")
            log.write("=" * 80 + "\n\n")

            # Section 1: Failures (prioritised — errors first)
            log.write(f"SECTION 1: FAILURES ({len(failures)})\n")
            log.write("-" * 40 + "\n")
            if not failures:
                log.write("No failures detected.\n")
            else:
                for item in failures:
                    log.write(f"ASX File: {item['asx_fn']}\n")
                    log.write(f"   Reason: [{item['reason']}]\n")
                    log.write(f"   Path:   {item['audio_path']}\n\n")

            # Section 2: Successful extractions
            log.write(f"\nSECTION 2: SUCCESSFUL EXTRACTIONS ({len(successes)})\n")
            log.write("-" * 40 + "\n")
            if not successes:
                log.write("No successful extractions.\n")
            else:
                for item in successes:
                    log.write(f"ASX File: {item['asx_fn']}\n")
                    log.write(f"   Found: {item['audio_path']}\n\n")

            # Summary
            log.write("\n" + "=" * 80 + "\n")
            log.write("SUMMARY:\n")
            log.write(f"   Success:  {len(successes)}\n")
            log.write(f"   Failures: {len(failures)}\n")

        return True

    except (OSError, ValueError) as _exc:
        logger.warning("asx file_ops failed: %s", _exc, exc_info=True)
        return False

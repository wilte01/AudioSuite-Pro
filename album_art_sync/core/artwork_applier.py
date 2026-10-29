"""
artwork_applier.py — Image processing and multi-format tag embedding.
No tkinter imports; progress reported via callback.

Supports: MP3, FLAC, OGG, M4A, Opus

Changed in 1.0.1: the per-file and outer catches now include AudioSuiteError,
which embed_artwork raises (via handle_audio_errors(reraise=True)), so one
un-embeddable file no longer aborts the rest of the album.
"""
# Changed in 2.1.7: ASCII-only status output (R-14) - typography stays in
# comments and docs; a cp1252 console cannot encode these glyphs.

# ── Standard library imports ─────────────────────────────────────────────────
import io
import logging
import os
from typing import Callable

# ── Third-party imports ─────────────────────────────────────────────────────
from PIL import Image

# ── Shared-library imports ───────────────────────────────────────────────────
from audio_suite_shared.exceptions import (
    AudioSuiteError,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.tag_helper import embed_artwork

# ── Local imports ────────────────────────────────────────────────────────────
from ..config.settings import CONFIG

logger = logging.getLogger(__name__)


def apply(
    path: str,
    files: list[str],
    img_raw: bytes,
    mode: str,  # "Update Artwork" | "Dry Run"
    embed_size: int,
    purge: bool,
    log: Callable[[str], None],
    cancel_flag: Callable[[], bool],
    on_file_progress: Callable[[int], None],
) -> bool:
    """
    Process raw image bytes and optionally embed them into all audio files.

    Args:
        path:             Directory containing the audio files.
        files:            List of audio filenames within path.
        img_raw:          Raw JPEG/PNG bytes from the chosen artwork source.
        mode:             "Update Artwork" performs writes; "Dry Run" only logs.
        embed_size:       Max pixel dimension for the embedded tag image.
        purge:            Whether to delete hidden Windows thumbnail files first.
        log:              Logging callback (thread-safe via caller's bridge).
        cancel_flag:      Returns True if the user has requested cancellation.
        on_file_progress: Called with the index of each file processed.

    Returns:
        True on success (or successful dry run), False if a fatal error occurred.
    """
    try:
        if purge:
            log("  Purging old artwork files...")
            ghost_names = {"albumartsmall.jpg", "folder.jpg", "cover.jpg"}
            ghost_prefixes = ("albumart_",)
            for f in os.listdir(path):
                fl = f.lower()
                if fl in ghost_names or any(fl.startswith(p) for p in ghost_prefixes):
                    try:
                        os.remove(os.path.join(path, f))
                    except OSError as exc:
                        logger.debug("Could not remove %s: %s", f, exc, exc_info=True)
                        log(f"    Warning: Couldn't remove {f}: {exc}")

        original = Image.open(io.BytesIO(img_raw))
        folder_size = CONFIG["FOLDER_IMAGE_SIZE"]
        batch_size = CONFIG["PROGRESS_BATCH_SIZE"]

        if mode == "Update Artwork":
            log(f"  Saving folder.jpg ({folder_size}x{folder_size})...")
            folder_img = original.copy()
            folder_img.thumbnail((folder_size, folder_size), Image.Resampling.LANCZOS)
            folder_img.convert("RGB").save(
                os.path.join(path, "folder.jpg"), "JPEG", quality=95
            )

        # Prepare JPEG bytes at the requested embed size
        log(f"  Preparing embedded artwork ({embed_size}x{embed_size})...")
        tag_img = original.copy()
        tag_img.thumbnail((embed_size, embed_size), Image.Resampling.LANCZOS)
        bio = io.BytesIO()
        tag_img.convert("RGB").save(bio, "JPEG", quality=90)
        tag_bytes = bio.getvalue()

        if mode == "Update Artwork":
            log(f"  Embedding artwork in {len(files)} file(s)...")
            for i, f in enumerate(files):
                if cancel_flag():
                    log("  [Cancelled by user]")
                    return False
                try:
                    embed_artwork(os.path.join(path, f), tag_bytes)
                except (OSError, ValueError, AudioSuiteError) as exc:
                    mapped = map_to_audio_error(exc, context={"file": f})
                    logger.warning(
                        "Artwork embed failed for %s: %s", f, mapped, exc_info=True
                    )
                    log(
                        f"    Warning: Failed to embed in"
                        f" {f}: {user_message_for(mapped)}"
                    )

                if i % batch_size == 0 or i == len(files) - 1:
                    on_file_progress(i + 1)

            log("  [OK] Artwork embedded in all files")
        else:
            log(f"  [Dry Run] Would embed artwork in {len(files)} files")

        return True

    except (OSError, ValueError, AudioSuiteError) as exc:
        mapped = map_to_audio_error(exc, context={"operation": "artwork_apply"})
        logger.error("Artwork apply failed: %s", mapped, exc_info=True)
        log(f"  [X] Error applying artwork: {user_message_for(mapped)}")
        return False

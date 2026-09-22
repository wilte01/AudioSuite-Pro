"""
album_art_normalizer (compatibility layer)
==========================================

Headless orchestrator (run_processing), logging setup, and OS helper.
The GUI class lives in :mod:`album_art_normalizer.app` — this module
provides the synchronous entry point for tests and programmatic use.

Delegates image-processing and per-format audio logic to
:mod:`album_art_normalizer.core.art_processor`.
"""

import logging
import os
import platform
import tkinter.messagebox as messagebox
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import album_art_normalizer as _aan
from album_art_normalizer.core.art_processor import (
    FOLDER_JPG_TARGET,
    AudioTagReadError,
    AudioTagWriteError,
    FolderImageError,
    ImageDecodeError,
    ProcessingResult,
)
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.secure_subprocess import (
    SubprocessSecurityError,
    run_secure_subprocess,
)

LOG_FILE: Path = Path(__file__).parent / "process_log.txt"
logger: logging.Logger = logging.getLogger("album_art_normalizer")


def _configure_file_logging(log_path: Path) -> None:
    """Attach a file handler to the module logger.

    Deferred so that importing this module does not create files as a side
    effect (important for test isolation).
    """
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    )
    logger.setLevel(logging.DEBUG)
    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        logger.addHandler(handler)


LogCallback = Callable[[str], None]
DoneCallback = Callable[[ProcessingResult], None]


def run_processing(
    directory: str,
    target_size: tuple[int, int],
    log_callback: LogCallback,
    done_callback: DoneCallback,
) -> None:
    """Scan *directory* and update all album artwork.

    Intended to run in a background :class:`threading.Thread`.  Progress is
    reported via *log_callback* (called for every log line) and a final
    :class:`ProcessingResult` is delivered via *done_callback*.

    Args:
        directory: Path to the music directory (as a string).
        target_size: Desired embedded image dimensions ``(width, height)``.
        log_callback: Callable that receives one log-line string at a time.
        done_callback: Callable that receives a :class:`ProcessingResult`.
    """
    _process_folder_jpg = _aan.process_folder_jpg
    _process_mp3 = _aan.process_mp3_artwork
    _process_flac = _aan.process_flac_artwork

    dir_path = Path(directory)
    total_files: int = 0
    images_updated: int = 0
    error_count: int = 0

    def emit(msg: str) -> None:
        logger.info(msg)
        log_callback(msg)

    emit(f"=== Session started {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    emit(f"Directory        : {dir_path}")
    emit(f"Embedded target  : {target_size[0]}\u00d7{target_size[1]}")
    emit(f"folder.jpg target: {FOLDER_JPG_TARGET[0]}\u00d7{FOLDER_JPG_TARGET[1]}")
    emit("")

    emit(
        "\u2500\u2500\u2500 folder.jpg check "
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500"
    )
    try:
        folder_result = _process_folder_jpg(dir_path)
        if folder_result is None:
            emit("  folder.jpg not present \u2014 skipped.")
        else:
            emit(f"  {folder_result}")
            if "resized" in folder_result:
                images_updated += 1
    except FolderImageError as exc:
        emit(f"  \u2717 ERROR: {exc}")
        error_count += 1
    emit("")

    audio_files: list[Path] = sorted(
        f for f in dir_path.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    if not audio_files:
        emit("No supported audio files (.mp3 / .flac) found in directory.")
    else:
        emit(
            f"\u2500\u2500\u2500 Audio files ({len(audio_files)} found) "
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        )
        emit("")

    for path in audio_files:
        total_files += 1
        suffix = path.suffix.lower()
        emit(f"[{total_files}/{len(audio_files)}] {path.name}")

        try:
            if suffix == ".mp3":
                outcome = _process_mp3(path, target_size)
            elif suffix == ".flac":
                outcome = _process_flac(path, target_size)
            else:
                outcome = "Unsupported extension \u2014 skipped."

            emit(f"  \u2192 {outcome}")
            if "resized" in outcome and "saved" in outcome:
                images_updated += 1

        except (AudioTagReadError, AudioTagWriteError, ImageDecodeError) as exc:
            logger.exception("Handled error processing %s", path.name)
            emit(f"  \u2717 ERROR: {exc}")
            error_count += 1
        except Exception as exc:
            logger.exception("Unexpected error processing %s", path.name)
            emit(f"  \u2717 UNEXPECTED ERROR: {exc}")
            error_count += 1

    emit("")
    emit(
        "\u2500\u2500\u2500 Summary "
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
    )
    emit(f"  Audio files examined : {total_files}")
    emit(f"  Images updated       : {images_updated}")
    emit(f"  Errors               : {error_count}")
    emit("=== Processing complete ===")

    done_callback(
        ProcessingResult(
            total_files=total_files,
            images_updated=images_updated,
            errors=error_count,
        )
    )


def _open_path_in_os(path: Path) -> None:
    """Open *path* with the operating system's default handler."""
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":
            run_secure_subprocess("open", [str(path)], capture_output=True, check=False)
        else:
            run_secure_subprocess(
                "xdg-open", [str(path)], capture_output=True, check=False
            )
    except (OSError, SubprocessSecurityError) as exc:
        messagebox.showerror("Cannot open", str(exc))

"""
platform_utils.py — Cross-platform helpers for the Audio Suite.

Provides OS-aware file/folder opening, user-guide launching, and
window placement/persistence, used identically across all suite tools.

Changed in 1.0.1: restore saved window geometry on monitors with negative
X/Y coordinates (Tk's ``WxH-X-Y`` form is now parsed instead of split on
``+``, which dropped any signed coordinate).
Changed in 1.3.0: registers the Spectral Viewer's guide filename in
``guide_to_program`` so its Help button resolves the shipped .docx.
Changed in 2.0.0: registers the Stem Separator's guide filename.
Changed in 2.0.0: registers the ML Denoiser's guide filename (Item 6.2).

Changed in 2.1.7: ``open_help`` resolves
``documentation/user_guides/individual_programs/<tool>/``, the one documentation tree.

"""

import logging
import re
import subprocess
import sys
from pathlib import Path
from tkinter import messagebox
from typing import Any

from audio_suite_shared.exceptions import map_to_audio_error

# Import secure subprocess utilities
from .secure_subprocess import SubprocessSecurityError, run_secure_subprocess

__all__ = ["messagebox", "open_help", "open_path", "setup_window"]

logger = logging.getLogger(f"audio_suite.{__name__}")

# os.startfile is the only remaining os.* usage — keep import minimal
import os  # noqa: E402


def open_path(path: str) -> None:
    """Open a file or folder with OS default application."""
    if not Path(path).exists():
        messagebox.showerror(
            "Path Not Found", f"The specified path does not exist:\n{path}"
        )
        return

    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            run_secure_subprocess("open", [path], capture_output=True, check=False)
        else:
            run_secure_subprocess("xdg-open", [path], capture_output=True, check=False)
    except SubprocessSecurityError as exc:
        messagebox.showerror(
            "Security Error",
            f"Cannot open path due to security restrictions:\n{path}\n\n{str(exc)}",
        )
    except PermissionError as exc:
        messagebox.showerror(
            "Permission Denied", f"Cannot open path:\n{path}\n\n{str(exc)}"
        )
    except OSError as exc:
        messagebox.showerror(
            "Open Error", f"Failed to open path:\n{path}\n\n{str(exc)}"
        )
    except subprocess.CalledProcessError as exc:
        # OSError is fully handled by the arms above; only the subprocess
        # failure (start-style handler chain) reaches this catch-all arm.
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        messagebox.showerror(
            "Unexpected Error",
            f"An error occurred while opening:\n{path}\n\n{str(exc)}",
        )


def open_help(guide_filename: str) -> None:
    """
    Open the named user-guide document from ``documentation/user_guides/``.
    Shows a friendly warning dialog if the file is not found.

    Args:
        guide_filename: Filename of the user guide
            (e.g. 'BPM_Analyzer_User_Guide.docx').
    """
    # Use current working directory as the suite root (most reliable approach)
    current_dir = Path.cwd()

    # If not in AudioSuite-Pro directory, try to find it
    if current_dir.name != "AudioSuite-Pro":
        # Navigate up to find the suite root
        max_iterations = 10
        iteration = 0
        while current_dir.name != "AudioSuite-Pro" and iteration < max_iterations:
            current_dir = current_dir.parent
            iteration += 1

    if current_dir.name != "AudioSuite-Pro":
        messagebox.showwarning(
            "Help File Not Found",
            f"Could not locate AudioSuite root directory.\n\n"
            f"Please ensure '{guide_filename}' is available.",
        )
        return

    # Determine program name from guide filename (most reliable approach)
    program_name = None

    # Map guide filenames to program names
    guide_to_program = {
        "Album_Art_Normalizer_User_Guide.docx": "album_art_normalizer",
        "Album_Art_Synchronizer_User_Guide.docx": "album_art_sync",
        "AlbumGenre_Tagger_User_Guide.docx": "album_genre_tagger",
        "ASX_Playlist_Extractor_User_Guide.docx": "asx_extractor",
        "Audio_Enhancer_User_Guide.docx": "audio_enhancer",
        "Audio_Fingerprinter_User_Guide.docx": "audio_fingerprinter",
        "Audio_Normalizer_User_Guide.docx": "audio_normalizer",
        "Audio_Refinery_User_Guide.docx": "audio_refinery",
        "BPM_Analyzer_User_Guide.docx": "bpm_analyzer",
        "CD_Ripper_User_Guide.docx": "cd_ripper",
        "File_Reorganizer_User_Guide.docx": "file_reorganizer",
        "Genre_Sync_User_Guide.docx": "genre_sync",
        "Key_Detector_User_Guide.docx": "key_detector",
        "Library_Stats_User_Guide.docx": "library_stats",
        "Lyrics_Manager_User_Guide.docx": "lyrics_manager",
        "Master_Driver_User_Guide.docx": "master_driver",
        "Metadata_Scrubber_User_Guide.docx": "metadata_scrubber",
        "Mood_Analysis_Batch_Tagger_User_Guide.docx": "mood_analysis_batch_tagger",
        "Mood_Analyzer_User_Guide.docx": "mood_analyzer",
        "Music_Format_Converter_User_Guide.docx": "music_format_converter",
        "ML_Denoiser_User_Guide.docx": "ml_denoiser",
        "Noise_Reduction_User_Guide.docx": "noise_reduction",
        "Pop_Click_Remover_User_Guide.docx": "pop_click_remover",
        "ReplayGain_Analyzer_User_Guide.docx": "replaygain_analyzer",
        "Silence_Trimmer_User_Guide.docx": "silence_trimmer",
        "Spectral_Viewer_User_Guide.docx": "spectral_viewer",
        "Stem_Separator_User_Guide.docx": "stem_separator",
        "Tag_Field_Updater_User_Guide.docx": "tag_field_updater",
        "Tag_Editor_User_Guide.docx": "tag_editor",
        "Tempo_Analyzer_User_Guide.docx": "tempo_analyzer",
        "Undo_Tag_Edits_User_Guide.docx": "undo_tag_edits",
    }

    program_name = guide_to_program.get(guide_filename)

    if not program_name:
        messagebox.showwarning(
            "Help File Not Found",
            f"Unknown help guide: {guide_filename}\n\n"
            f"Please ensure the guide filename is correct.",
        )
        return

    # Check the new centralized location first
    help_file = (
        current_dir
        / "documentation"
        / "user_guides"
        / "individual_programs"
        / program_name
        / guide_filename
    )

    # Fallback to old location if not found in new location
    if not help_file.exists():
        program_dir = Path(str(current_dir)) / program_name.replace("_", "")
        if program_dir.exists():
            old_help_file = program_dir / guide_filename
            if old_help_file.exists():
                help_file = old_help_file

    if not help_file.exists():
        messagebox.showwarning(
            "Help File Not Found",
            f"The user guide could not be found at:\n{help_file}\n\n"
            f"Please ensure '{guide_filename}' is in the "
            f"documentation/user_guides/individual_programs/{program_name}/ folder.",
        )
        return

    try:
        if sys.platform == "win32":
            os.startfile(str(help_file))
        elif sys.platform == "darwin":
            run_secure_subprocess(
                "open", [str(help_file)], capture_output=True, check=False
            )
        else:
            run_secure_subprocess(
                "xdg-open", [str(help_file)], capture_output=True, check=False
            )
    except SubprocessSecurityError as exc:
        messagebox.showerror(
            "Security Error",
            f"Cannot open help file due to security"
            f" restrictions:\n{help_file}\n\n{str(exc)}",
        )
    except PermissionError as exc:
        messagebox.showerror(
            "Permission Denied", f"Cannot open help file:\n{help_file}\n\n{str(exc)}"
        )
    except OSError as exc:
        messagebox.showerror(
            "Help File Error", f"Failed to open help file:\n{help_file}\n\n{str(exc)}"
        )
    except subprocess.CalledProcessError as exc:
        # Same dedup as open_path: OSError is fully handled above.
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        messagebox.showerror(
            "Unexpected Error", f"An error occurred while opening help:\n{str(exc)}"
        )


_GEOMETRY_RE = re.compile(r"^=?(?P<w>\d+)x(?P<h>\d+)(?P<x>[+-]\d+)(?P<y>[+-]\d+)$")


def _parse_geometry_origin(geometry: str) -> tuple[int, int] | None:
    """Extract the signed ``(x, y)`` origin from a Tk geometry string.

    Tk renders a window geometry as ``WxH±X±Y`` where **each** coordinate
    carries its own sign, so a window on a monitor to the left of the primary
    is ``800x600-1920+40`` — not ``800x600+-1920+40``.  Splitting such a
    string on ``"+"`` drops the negative coordinate, so the origin must be
    parsed as a signed pair.  An optional leading ``=`` is accepted and
    ignored.

    Args:
        geometry: The geometry string as returned by ``root.geometry()``.

    Returns:
        The ``(x, y)`` screen offset, or ``None`` when the string is not a
        well-formed ``WxH+X+Y`` / ``WxH-X-Y`` geometry so the caller can fall
        back to centering.
    """
    match = _GEOMETRY_RE.match(geometry)
    if match is None:
        return None
    return int(match.group("x")), int(match.group("y"))


def setup_window(
    root: Any, width: int, height: int, config_module: Any, config_key: str
) -> None:
    """
    Restore a saved window position, or centre the window if none is saved
    or the saved position is no longer on a visible monitor.

    On close the window's current geometry is saved automatically so the
    next launch restores it.

    Args:
        root:          The tk.Tk root window.
        width:         Default window width (used when centring).
        height:        Default window height (used when centring).
        config_module: The suite_config module (must expose load_value /
                       save_value helpers — see note below).
        config_key:    Unique key string for this tool, e.g. 'key_detector_window'.
    """

    def _is_on_screen(x: int, y: int) -> bool:
        """Return True if (x, y) falls within any visible monitor's work area."""
        if sys.platform != "win32":
            # Non-Windows: accept any position that isn't wildly off-screen.
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            return -width < x < sw and -height < y < sh

        try:
            import ctypes
            from ctypes import wintypes

            pt = wintypes.POINT(x, y)
            # MONITOR_DEFAULTTONULL (0) returns NULL if the point is off all monitors.
            hmon = ctypes.windll.user32.MonitorFromPoint(pt, 0)
            return bool(hmon)
        except (OSError, subprocess.CalledProcessError) as _exc:
            logger.debug("MonitorFromPoint API failed: %s", _exc)
            return True  # If the API fails, trust the saved position.

    def _center() -> None:
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"{width}x{height}+{(sw - width) // 2}+{(sh - height) // 2}")

    def _save_geometry(event: Any = None) -> None:
        """Save window geometry to config with error handling."""
        try:
            config_module.save_value(config_key, root.geometry())
        except OSError as _exc:
            logger.debug("Could not save window geometry: %s", _exc, exc_info=True)
        except subprocess.CalledProcessError as _exc:
            # OSError fully handled by the arm above; only subprocess failures
            # (via the shared config write seam) reach this arm.
            logger.debug(
                "Unexpected error saving window geometry: %s", _exc, exc_info=True
            )

    # ── Attempt to restore saved geometry ────────────────────────────────────
    restored = False
    try:
        saved = config_module.load_value(config_key)
        if saved:
            # geometry string is "WxH±X±Y" — X/Y carry their own sign, so
            # "800x600-1920+40" must parse without splitting on "+".
            origin = _parse_geometry_origin(saved)
            if origin is not None and _is_on_screen(*origin):
                root.geometry(saved)
                restored = True
    except (OSError, subprocess.CalledProcessError) as _exc:
        logger.debug(
            "Could not restore window geometry from config: %s", _exc, exc_info=True
        )
        restored = False

    if not restored:
        _center()

    # ── Save position whenever the window is moved or resized ────────────────
    root.bind("<Configure>", _save_geometry)

    def _on_close() -> None:
        _save_geometry()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)

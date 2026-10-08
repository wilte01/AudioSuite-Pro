"""
audio_suite_shared/exceptions.py
─────────────────────────────────────────────────────────────────────────────
Centralised exception hierarchy and @handle_audio_errors decorator for
AudioSuite-Pro.

DROP-IN PLACEMENT: copy this file to  audio_suite_shared/exceptions.py

INTEGRATION POINTS (all pre-existing):
  • audio_suite_shared/error_logger.py  — stdlib logging shim (already wired)
  • audio_suite_shared/security/error_handler.py — SecureErrorHandler for
    sanitised user-facing messages
  • audio_suite_shared/error_recovery.py — retry / recovery action helpers

USAGE QUICK-REFERENCE:
  from audio_suite_shared.exceptions import handle_audio_errors, AudioSuiteError

  @handle_audio_errors(reraise=False, context="tag_writer")
  def write_tags(path: Path, tags: dict) -> bool:
      ...

  # Or raise explicitly from domain logic:
  raise AudioCodecError("mutagen returned unsupported codec", path=path)
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import errno
import functools
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Module logger — namespaced under "audio_suite" (iteration-8 C8) so records
# propagate to the RotatingFileHandler that
# logging_setup.configure_logging() attaches to the audio_suite logger and
# share one searchable namespace with the rest of the shared infrastructure.
# (Since iteration-9 G4.2 a first-party package logger reaches that handler
# as well, but audio_suite.* remains the convention for shared modules.)
# ---------------------------------------------------------------------------
logger = logging.getLogger(f"audio_suite.{__name__}")


# ===========================================================================
# 1. EXCEPTION HIERARCHY
# ===========================================================================


class AudioSuiteError(Exception):
    """
    Root of the AudioSuite-Pro exception tree.

    Every custom exception in the suite inherits from here, which means:
      • A single ``except AudioSuiteError`` in the UI layer catches everything
        domain-specific while still letting KeyboardInterrupt and SystemExit
        propagate unimpeded.
      • ``isinstance(exc, AudioSuiteError)`` is a reliable domain-error test.

    Attributes
    ----------
    message : str
        Human-readable description (without internal path details — those go
        in context).
    context : dict
        Optional key/value metadata attached at raise-site (file path, codec,
        operation name, etc.).  Logged in full; never shown raw to users.
    original : Exception | None
        The upstream built-in or third-party exception that triggered this one.
        Preserved so the decorator can log the full causal chain.
    """

    def __init__(
        self,
        message: str,
        *,
        context: Optional[dict[str, Any]] = None,
        original: Optional[Exception] = None,
    ) -> None:  # explicit for completeness
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context or {}
        self.original: Optional[Exception] = original

    def __str__(self) -> str:
        parts = [self.message]
        if self.context:
            parts.append(f"  context={self.context}")
        return " | ".join(parts)

    # Convenience so callers can do:  raise AudioFileNotFoundError(...) from exc
    def with_original(self, exc: Exception) -> "AudioSuiteError":
        self.original = exc
        return self


# ── 1a. IO Errors ────────────────────────────────────────────────────────────


class AudioIOError(AudioSuiteError):
    """Base for all file-system / IO problems."""


class AudioFileNotFoundError(AudioIOError):
    """A required audio or config file does not exist on disk.

    Maps from: FileNotFoundError
    """

    def __init__(
        self, message: str, *, path: Optional[Path | str] = None, **kw: Any
    ) -> None:
        ctx = kw.pop("context", {})
        if path:
            ctx.setdefault("path", str(path))
        super().__init__(message, context=ctx, **kw)


class AudioPermissionError(AudioIOError):
    """The process lacks read/write permissions for a file or directory.

    Maps from: PermissionError
    """

    def __init__(
        self, message: str, *, path: Optional[Path | str] = None, **kw: Any
    ) -> None:
        ctx = kw.pop("context", {})
        if path:
            ctx.setdefault("path", str(path))
        super().__init__(message, context=ctx, **kw)


class AudioDiskFullError(AudioIOError):
    """Output could not be written because the disk is full.

    Maps from: OSError with errno ENOSPC (28)
    """


class AudioDirectoryError(AudioIOError):
    """A directory could not be created, read, or is not a directory.

    Maps from: NotADirectoryError, IsADirectoryError, OSError (various)
    """


# ── 1b. Processing Errors ─────────────────────────────────────────────────────


class AudioProcessingError(AudioSuiteError):
    """Base for errors that occur during audio analysis or transformation."""


class AudioCodecError(AudioProcessingError):
    """A codec or container format is unsupported or corrupted.

    Maps from: mutagen errors, TypeError on binary data, ValueError on codec
    strings.
    """

    def __init__(
        self, message: str, *, path: Optional[Path | str] = None, **kw: Any
    ) -> None:
        ctx = kw.pop("context", {})
        if path:
            ctx.setdefault("path", str(path))
        super().__init__(message, context=ctx, **kw)


class AudioFormatError(AudioProcessingError):
    """The file has an unexpected or invalid internal format.

    Maps from: struct.error, ValueError on audio data, mutagen.MutagenError
    """


class AudioExternalToolError(AudioProcessingError):
    """An external tool (ffmpeg, cdparanoia, etc.) returned a non-zero exit code
    or could not be found.

    Maps from: subprocess.CalledProcessError, FileNotFoundError (for binaries)
    """

    def __init__(
        self,
        message: str,
        *,
        tool: Optional[str] = None,
        returncode: Optional[int] = None,
        stderr: Optional[str] = None,
        **kw: Any,
    ) -> None:
        ctx = kw.pop("context", {})
        if tool:
            ctx.setdefault("tool", tool)
        if returncode is not None:
            ctx.setdefault("returncode", returncode)
        if stderr:
            ctx.setdefault("stderr", stderr[:300])  # truncate; full version is in logs
        super().__init__(message, context=ctx, **kw)


class AudioTagError(AudioProcessingError):
    """Reading or writing audio metadata tags failed.

    Maps from: mutagen errors, KeyError on tag fields, UnicodeDecodeError
    """


class AudioAnalysisError(AudioProcessingError):
    """An analysis step (loudness, BPM, key detection, etc.) failed.

    Maps from: RuntimeError, numpy/scipy errors, ZeroDivisionError
    """


class MutagenError(AudioProcessingError):
    """Fallback ``MutagenError`` for environments without mutagen.

    When mutagen is installed the real ``mutagen.MutagenError`` is used
    directly; this class exists only so that ``except MutagenError`` in
    modules that define a local fallback never degrades to
    ``except Exception``.  It subclasses :class:`AudioProcessingError`
    so the suite's error-handling hierarchy is maintained regardless of
    whether mutagen is present.
    """


# ── 1c. Configuration Errors ─────────────────────────────────────────────────


class AudioConfigurationError(AudioSuiteError):
    """Base for configuration / settings problems."""


class AudioConfigFileError(AudioConfigurationError):
    """A config file is missing, unreadable, or structurally invalid.

    Maps from: FileNotFoundError (config), json.JSONDecodeError,
               configparser.Error
    """

    def __init__(
        self,
        message: str,
        *,
        config_file: Optional[str] = None,
        **kw: Any,
    ) -> None:
        ctx = kw.pop("context", {})
        if config_file:
            ctx.setdefault("config_file", config_file)
        super().__init__(message, context=ctx, **kw)


class AudioConfigValueError(AudioConfigurationError):
    """A configuration value is out-of-range or has the wrong type.

    Maps from: ValueError, TypeError raised from settings parsing
    """


class AudioMissingDependencyError(AudioConfigurationError):
    """A required external dependency (binary, library) is not installed.

    Maps from: FileNotFoundError for binaries, ImportError
    """

    def __init__(
        self, message: str, *, dependency: Optional[str] = None, **kw: Any
    ) -> None:
        ctx = kw.pop("context", {})
        if dependency:
            ctx.setdefault("dependency", dependency)
        super().__init__(message, context=ctx, **kw)


# ===========================================================================
# 2. BUILT-IN → CUSTOM EXCEPTION MAPPING TABLE
# ===========================================================================
#
# This table is the single source of truth for how Python built-ins map to
# our hierarchy.  The decorator (below) and any explicit raise sites both use
# it so there is NO duplication.
#
# Format:  built-in_type → (AudioSuiteError subclass, kwargs_fn | None)
#
# kwargs_fn receives the original exception and the context dict, and returns
# extra keyword arguments to pass to the custom constructor.
# ---------------------------------------------------------------------------


def _is_disk_full(exc: OSError) -> bool:
    return getattr(exc, "errno", None) == errno.ENOSPC


def _oslike_map(
    exc: OSError, ctx: dict[str, Any]
) -> tuple[type[AudioSuiteError], dict[str, Any]]:
    """Dispatch OSError sub-cases: disk-full, dir errors, generic OS."""
    if _is_disk_full(exc):
        return AudioDiskFullError, {}
    if isinstance(exc, (NotADirectoryError, IsADirectoryError)):
        return AudioDirectoryError, {}
    return AudioIOError, {}


# (source_type, predicate_or_None) → custom_class
# Evaluated top-to-bottom; first match wins.
_MAPPING: list[tuple[type, type[AudioSuiteError] | None]] = [
    # File / permission ──────────────────────────────────────────────────────
    (FileNotFoundError, AudioFileNotFoundError),
    (PermissionError, AudioPermissionError),
    # OSError family (after the specific subclasses above) ───────────────────
    (OSError, None),  # → _oslike_map at runtime
    # Processing ─────────────────────────────────────────────────────────────
    (subprocess.CalledProcessError, AudioExternalToolError),
    (UnicodeDecodeError, AudioTagError),
    (UnicodeEncodeError, AudioTagError),
    # Config ─────────────────────────────────────────────────────────────────
    (json.JSONDecodeError, AudioConfigFileError),
    (ImportError, AudioMissingDependencyError),
    # Broad value / type errors in processing context ────────────────────────
    (TypeError, AudioCodecError),
    (ValueError, AudioFormatError),
    (RuntimeError, AudioAnalysisError),
    (ZeroDivisionError, AudioAnalysisError),
]


def map_to_audio_error(
    exc: Exception,
    context: Optional[dict[str, Any]] = None,
) -> AudioSuiteError:
    """
    Convert a built-in or third-party exception to the nearest AudioSuiteError
    subclass, preserving the original as ``mapped.original``.

    If ``exc`` is already an ``AudioSuiteError`` it is returned unchanged (no
    double-wrapping).

    Parameters
    ----------
    exc     : The exception to map.
    context : Optional extra metadata to attach (merged with any already on
              the exception if it is already an AudioSuiteError).

    Returns
    -------
    AudioSuiteError subclass instance.
    """
    if isinstance(exc, AudioSuiteError):
        if context:
            exc.context.update(context)
        return exc

    ctx = dict(context or {})
    message = str(exc)

    for src_type, target_class in _MAPPING:
        if isinstance(exc, src_type):
            if target_class is None:
                # Dynamic dispatch for OSError family
                target_class, extra = _oslike_map(exc, ctx)  # type: ignore[arg-type]
                ctx.update(extra)
            # Special-case CalledProcessError to surface tool info
            if isinstance(exc, subprocess.CalledProcessError):
                return AudioExternalToolError(
                    message,
                    returncode=exc.returncode,
                    stderr=getattr(exc, "stderr", None),
                    context=ctx,
                    original=exc,
                )
            return target_class(message, context=ctx, original=exc)

    # No specific mapping — wrap in the root class so callers can still
    # catch AudioSuiteError at the UI boundary.
    return AudioSuiteError(message, context=ctx, original=exc)


# ===========================================================================
# 3.  @handle_audio_errors DECORATOR
# ===========================================================================


def handle_audio_errors(
    *,
    reraise: bool = True,
    context: Optional[str] = None,
    return_on_error: Any = None,
    log_level: int = logging.ERROR,
    suppress_types: tuple[type[Exception], ...] = (),
) -> Callable[[_F], _F]:
    """
    Decorator that wraps a function with structured error handling.

    Behaviour
    ---------
    1. If the decorated function raises **any** exception:
         a. Maps it to the appropriate AudioSuiteError subclass via
            ``map_to_audio_error()``.
         b. Logs it at ``log_level`` **with the full stack trace**
            (exc_info=True) so no failure is ever silent.
         c. Re-raises the mapped exception if ``reraise=True`` (default).
            Otherwise swallows it and returns ``return_on_error``.
    2. If the exception is already an AudioSuiteError it is logged and
       re-raised / suppressed without double-wrapping.
    3. KeyboardInterrupt and SystemExit are **never** caught here.

    Parameters
    ----------
    reraise     : Re-raise the (mapped) exception after logging.
                  Set False for fire-and-forget helpers where you want
                  failures logged but not surfaced.
    context     : Optional string label added to the log message and the
                  mapped exception's ``context`` dict, e.g. "tag_writer".
                  Defaults to the decorated function's qualified name.
    return_on_error : Value returned when reraise=False and an error occurs.
                  Defaults to None.
    log_level   : logging level for the error record (default: ERROR).
    suppress_types : Tuple of AudioSuiteError subclasses that should be
                  suppressed (not re-raised) even when reraise=True.
                  Useful for non-critical operations like spin-down.

    Usage Examples
    --------------
    # 1. Core processing — re-raise so the worker thread sees the failure
    @handle_audio_errors(context="loudness_measurement")
    def measure_loudness(path: Path) -> dict:
        ...

    # 2. Best-effort helper — log and return None, never crash
    @handle_audio_errors(reraise=False, context="album_art_fetch")
    def fetch_cover_art(artist: str, album: str) -> Optional[bytes]:
        ...

    # 3. Suppress only minor teardown errors (replaces `except Exception: pass`)
    @handle_audio_errors(
        reraise=True,
        suppress_types=(AudioExternalToolError,),
        context="drive_spindown",
    )
    def spin_down_drive(drive: str) -> None:
        ...
    """

    def decorator(func: _F) -> _F:
        _ctx_label = context or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)

            # Never silence these — let Python's runtime handle them.
            except (KeyboardInterrupt, SystemExit):
                raise

            except Exception as exc:
                mapped = map_to_audio_error(exc, context={"operation": _ctx_label})

                # Always log with full traceback — this is the contract.
                logger.log(
                    log_level,
                    "[%s] %s: %s",
                    type(mapped).__name__,
                    _ctx_label,
                    mapped.message,
                    exc_info=True,  # ← guarantees the stack trace is ALWAYS captured
                )

                # Suppress-list: treat like reraise=False for these types
                if suppress_types and isinstance(mapped, suppress_types):
                    logger.debug(
                        "Suppressing %s as per suppress_types in %s",
                        type(mapped).__name__,
                        _ctx_label,
                    )
                    return return_on_error

                if reraise:
                    # Re-raise the *mapped* custom exception so callers get the
                    # richer type, not a raw built-in.
                    cause = getattr(mapped, "original", None) or (
                        exc if exc is not mapped else None
                    )
                    raise mapped from cause

                return return_on_error

        return wrapper  # type: ignore[return-value]

    return decorator


# ===========================================================================
# 4.  UI / CLI BOUNDARY HELPER
# ===========================================================================


def user_message_for(exc: Exception) -> str:
    """
    Return a short, non-technical string suitable for display in a dialog or
    CLI error line.  Internal path details and stack traces are never included.

    This is the ONLY place that translates AudioSuiteError subclasses to
    human language.  All UI layers (tkinter dialogs, CLI --verbose output)
    should call this rather than str(exc).

    If ``AUDIOSUITE_DEBUG=1`` is set in the environment the full str(exc) is
    returned instead — useful during development without touching production
    code.
    """
    debug = os.environ.get("AUDIOSUITE_DEBUG", "").lower() in ("1", "true", "yes")
    if debug:
        return str(exc)

    # Map to clean user messages — extend this table as new subclasses are added.
    _user_messages: dict[type, str] = {
        AudioFileNotFoundError: (
            "The file could not be found. It may have been moved or deleted."
        ),
        AudioPermissionError: (
            "Permission denied. Check that AudioSuite has read/write access."
        ),
        AudioDiskFullError: ("The disk is full. Free up space and try again."),
        AudioDirectoryError: (
            "Could not access the folder. Check that it exists and is accessible."
        ),
        AudioCodecError: ("This file uses an unsupported or unreadable codec."),
        AudioFormatError: ("The file format is invalid or corrupted."),
        AudioExternalToolError: (
            "An external tool (e.g. ffmpeg) failed."
            " Check that it is installed and up to date."
        ),
        AudioTagError: ("Could not read or write the file's metadata tags."),
        AudioAnalysisError: (
            "Audio analysis failed. The file may be corrupted or too short."
        ),
        AudioConfigFileError: (
            "The configuration file is missing or corrupted."
            " Default settings will be used."
        ),
        AudioConfigValueError: (
            "An invalid configuration value was detected. Please check your settings."
        ),
        AudioMissingDependencyError: ("A required tool or library is not installed."),
        AudioIOError: "A file system error occurred.",
        AudioProcessingError: ("An error occurred during processing."),
        AudioConfigurationError: ("A configuration error occurred."),
        AudioSuiteError: (
            "An unexpected error occurred. Please check the log for details."
        ),
    }

    # Walk the MRO so the most specific match wins.
    for exc_type in type(exc).__mro__:
        if exc_type in _user_messages:
            return _user_messages[exc_type]

    return "An unexpected error occurred. Please check the log for details."

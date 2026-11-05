"""
reporting.py - part of BaseFileProcessor, split out in 2.4.3.

WP-9 #2 moved this group of methods off :class:`BaseFileProcessor` into
``ReportingMixin``. Method bodies are unchanged, and ``file_processor_base``
still re-exports every public name, so existing importers are
unaffected.

Changed in 2.4.3: split out of ``audio_suite_shared.file_processor_base``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Protocol

from .error_recovery import RetryConfig
from .exceptions import map_to_audio_error, user_message_for
from .resource_manager import cleanup_expired_resources

logger = logging.getLogger(f"audio_suite.{__name__}")

# Type aliases for callback signatures
ProgressCallback = Callable[..., None]
CompleteCallback = Callable[..., None]
ErrorCallback = Callable[[str], None]


class ReportingMixin:
    """Progress tracking, retry defaults and the shared completion payload."""

    def create_progress_tracker(
        self, on_progress: ProgressCallback, total_files: int
    ) -> tuple[list[int], list[int], list[int], list[str], Callable[..., None]]:
        """Create standardised progress tracking infrastructure."""
        processed = [0]
        skipped = [0]
        errors = [0]
        log_entries: list[str] = []
        lock = threading.Lock()

        def _on_progress(
            n_skipped: int = 0,
            n_errors: int = 0,
            display_text: str = "",
            log_text: str = "",
        ) -> None:
            with lock:
                processed[0] += 1
                skipped[0] += n_skipped
                errors[0] += n_errors
                log_entries.append(log_text)
            on_progress(
                processed=processed[0],
                total=total_files,
                skipped=skipped[0],
                errors=errors[0],
                display_text=display_text,
            )

        return processed, skipped, errors, log_entries, _on_progress

    def create_retry_config(
        self,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        backoff_factor: float = 1.5,
    ) -> RetryConfig:
        """Create standardised retry configuration."""
        return RetryConfig(
            max_retries=max_retries,
            retry_delay=retry_delay,
            backoff_factor=backoff_factor,
            retry_on_exceptions=[IOError, OSError, PermissionError],
        )


class _DiscoversFiles(Protocol):
    """The one method ``_preflight_discover`` needs from its processor."""

    def discover_audio_files(
        self, dir_path: str, extensions: tuple[str, ...] | None = None
    ) -> list[str]: ...


def _preflight_discover(
    processor: _DiscoversFiles,
    dir_path: str,
    extensions: tuple[str, ...] | None,
    on_error: ErrorCallback,
    *,
    sort: bool = False,
    empty_message: str = "No supported audio files found in selected directory.",
) -> list[str] | None:
    """Shared pre-flight: discover audio files, report errors or empty.

    Returns the discovered file list on success, or ``None`` after calling
    *on_error* for a fatal discovery failure or an empty directory.

    Args:
        processor: The ``BaseFileProcessor`` whose ``discover_audio_files``
            method performs the scan.
        dir_path: Directory to scan.
        extensions: Optional extension filter (``None`` uses the default set).
        on_error: Called with a sanitised ``user_message_for()`` string when
            discovery fails or the directory is empty.
        sort: When ``True``, sort the discovered file list (used by the
            in-place DSP entry point so workers process files in a stable
            order).
        empty_message: The exact string passed to *on_error* when discovery
            returns an empty list.  Two variants exist across the four entry
            points; callers pass the variant that preserves the historical
            message.

    Returns:
        The discovered (and optionally sorted) file list, or ``None``.
    """
    try:
        files = processor.discover_audio_files(dir_path, extensions)
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error(
            "File discovery failed for %s: %s", dir_path, mapped, exc_info=True
        )
        on_error(user_message_for(mapped))
        return None

    if sort:
        files = sorted(files)

    if not files:
        on_error(empty_message)
        return None

    return files


def _emit_completion(
    on_complete: CompleteCallback,
    total: int,
    processed: int,
    skipped: int,
    errors: int,
    start_time: float,
    log_entries: list[str],
) -> None:
    """Shared completion: invoke *on_complete* and release expired resources.

    Used by :meth:`BaseFileProcessor.run_parallel_processing`,
    :meth:`BaseFileProcessor.run_cpu_bound_processing`, and
    :func:`run_analysis_workflow`.  The in-place DSP entry point
    (:meth:`BaseFileProcessor.run_inplace_dsp_batch`) uses its own
    completion call because it carries an extra ``succeeded`` counter and
    uses ``time.monotonic()``.
    """
    on_complete(
        total=total,
        processed=processed,
        skipped=skipped,
        errors=errors,
        duration_secs=time.time() - start_time,
        log_entries=log_entries,
    )
    cleanup_expired_resources(max_age_hours=1)

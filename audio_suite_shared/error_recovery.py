"""
error_recovery.py — Retry logic and recovery action determination.

Provides retry_with_backoff() for exponential-backoff retry loops and
get_recovery_action() for deciding skip/retry/abort per exception type.
No checkpoint persistence or decorator wrappers.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from audio_suite_shared.exceptions import map_to_audio_error

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class RecoveryAction(Enum):
    """Types of recovery actions."""

    RETRY = "retry"
    SKIP = "skip"
    ABORT = "abort"
    USER_CHOICE = "user_choice"


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    retry_delay: float = 1.0
    backoff_factor: float = 2.0
    retry_on_exceptions: list[type] = field(
        default_factory=lambda: [IOError, OSError, PermissionError]
    )
    max_delay: float = 60.0


def retry_with_backoff(
    func: Callable[..., _T],
    retry_config: RetryConfig,
    operation_id: str,
    *args: Any,
    **kwargs: Any,
) -> _T:
    """Execute a function with retry logic and exponential backoff.

    Args:
        func: Function to execute.
        retry_config: Retry configuration.
        operation_id: Operation identifier for tracking.
        *args: Function arguments.
        **kwargs: Function keyword arguments.

    Returns:
        Function result if successful.

    Raises:
        Last exception if all retries are exhausted.
    """
    last_exception: Optional[Exception] = None

    for attempt in range(retry_config.max_retries + 1):
        try:
            result = func(*args, **kwargs)

            if attempt > 0:
                logger.info(
                    "Operation %s succeeded on attempt %d",
                    operation_id,
                    attempt + 1,
                )

            return result

        except Exception as e:
            mapped = map_to_audio_error(e)
            logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
            last_exception = e

            if not any(
                isinstance(e, exc_type) for exc_type in retry_config.retry_on_exceptions
            ):
                logger.error(
                    "Operation %s failed with non-retryable error: %s",
                    operation_id,
                    e,
                    exc_info=True,
                )
                raise

            if attempt < retry_config.max_retries:
                delay = min(
                    retry_config.retry_delay * (retry_config.backoff_factor**attempt),
                    retry_config.max_delay,
                )

                logger.warning(
                    "Operation %s failed (attempt %d), retrying in %.1fs: %s",
                    operation_id,
                    attempt + 1,
                    delay,
                    e,
                )

                time.sleep(delay)
            else:
                logger.error(
                    "Operation %s failed after %d attempts: %s",
                    operation_id,
                    attempt + 1,
                    e,
                    exc_info=True,
                )

    raise last_exception  # type: ignore[misc]


def get_recovery_action(
    error: Exception,
    operation_type: str,
    user_callback: Optional[Callable[[Exception, str], RecoveryAction]] = None,
) -> RecoveryAction:
    """Determine the appropriate recovery action for an error.

    Args:
        error: The exception that occurred.
        operation_type: Type of operation being performed.
        user_callback: Optional callback for user decision.

    Returns:
        RecoveryAction to take.
    """
    if isinstance(error, (MemoryError, KeyboardInterrupt)):
        return RecoveryAction.ABORT

    if isinstance(error, FileNotFoundError):
        return RecoveryAction.SKIP

    if isinstance(error, (PermissionError, OSError)):
        if user_callback:
            return user_callback(error, operation_type)
        return RecoveryAction.RETRY

    if user_callback:
        return user_callback(error, operation_type)

    return RecoveryAction.RETRY

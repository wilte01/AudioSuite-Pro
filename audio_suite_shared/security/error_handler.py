"""
error_handler.py — Secure error handling utilities.

Provides secure error handling that minimises information disclosure
while maintaining proper logging for debugging purposes.

CHANGES (centralised error handling refactor):
  • All logger.error() calls now pass exc_info=True — stack traces are always
    captured in the log file even when the UI only sees a sanitised string.
  • User-facing messages now delegate to exceptions.user_message_for() so the
    message table lives in exactly one place.
  • Module-level logger instantiated once (not per-method) for efficiency.
  • Public API (all class methods and their signatures) is unchanged.
"""

import logging
import os
from typing import Optional

from audio_suite_shared.exceptions import map_to_audio_error, user_message_for

# Module-level logger — instantiated once, not inside each method.
_logger = logging.getLogger(f"audio_suite.{__name__}")


class SecureErrorHandler:
    """Secure error handling that minimises information disclosure.

    All public class methods return a sanitised, user-facing error string and
    log the full exception detail (including stack trace) at ERROR level via the
    module logger.  When ``AUDIOSUITE_DEBUG=1`` is set in the environment the raw
    exception detail is returned instead of the sanitised message, which is
    useful during development.

    The debug-mode flag is evaluated per-call (not at import time) so that
    ``set_debug_mode()`` or environment changes are picked up immediately,
    matching ``exceptions.user_message_for()``'s behaviour.
    """

    @classmethod
    def _is_debug(cls) -> bool:
        """Return True if debug mode is active (per-call env check)."""
        return os.environ.get("AUDIOSUITE_DEBUG", "").lower() in (
            "1",
            "true",
            "yes",
        )

    @classmethod
    def handle_error(
        cls, error: Exception, context: str = "", show_details: Optional[bool] = None
    ) -> str:
        """Handle a generic error, log it, and return a user-facing message.

        Args:
            error:        The exception that was raised.
            context:      Optional label identifying where the error occurred
                          (e.g. ``'tag_writer'``).  Included in the log record.
            show_details: Override the debug-mode flag for this call.  Pass
                          ``True`` to return raw detail regardless of the
                          environment variable.

        Returns:
            A sanitised, user-facing error string.  In debug mode the full
            ``str(error)`` is returned instead.
        """
        _logger.error("Error in %s: %s", context, error, exc_info=True)

        if show_details is None:
            show_details = cls._is_debug()
        if show_details:
            return f"Error in {context}: {str(error)}"

        mapped = map_to_audio_error(error, context={"operation": context})
        return user_message_for(mapped)

    @classmethod
    def handle_file_error(cls, error: Exception, file_path: str = "") -> str:
        """Handle a file-system error, log it, and return a user-facing message.

        Args:
            error:     The exception that was raised.
            file_path: Path to the file that triggered the error.  Only the
                       basename is included in debug-mode output.

        Returns:
            A sanitised, user-facing error string.
        """
        _logger.error("File error with %s: %s", file_path, error, exc_info=True)

        if cls._is_debug():
            return f"File error with {os.path.basename(file_path)}: {str(error)}"

        mapped = map_to_audio_error(error, context={"path": file_path})
        return user_message_for(mapped)

    @classmethod
    def handle_network_error(cls, error: Exception, service: str = "") -> str:
        """Handle a network/connectivity error, log it,
        and return a user-facing message.

        Args:
            error:   The exception that was raised.
            service: Name of the remote service (e.g. ``'MusicBrainz'``).

        Returns:
            A sanitised, user-facing error string advising the user to check
            their internet connection.
        """
        _logger.error("Network error with %s: %s", service, error, exc_info=True)

        if cls._is_debug():
            return f"Network error with {service}: {str(error)}"

        if service:
            return (
                f"Unable to connect to {service}. "
                "Please check your internet connection."
            )
        return "Network error occurred. Please check your internet connection."

    @classmethod
    def handle_api_error(cls, error: Exception, api_name: str = "") -> str:
        """Handle an API error, log it, and return a user-facing message.

        Provides specific guidance for common HTTP status codes (401, 403, 404,
        429) and timeout conditions.

        Args:
            error:    The exception that was raised.
            api_name: Name of the API that returned the error (e.g. ``'Last.fm'``).

        Returns:
            A sanitised, user-facing error string.
        """
        _logger.error("API error with %s: %s", api_name, error, exc_info=True)

        if cls._is_debug():
            return f"API error with {api_name}: {str(error)}"

        error_str = str(error)
        if "401" in error_str or "unauthorized" in error_str.lower():
            return f"Authentication failed with {api_name}. Please check your API keys."
        if "403" in error_str or "forbidden" in error_str.lower():
            return f"Access denied by {api_name}. Please check your permissions."
        if "404" in error_str or "not found" in error_str.lower():
            return f"Resource not found on {api_name}."
        if "429" in error_str or "rate limit" in error_str.lower():
            return f"Rate limit exceeded for {api_name}. Please try again later."
        if "timeout" in error_str.lower():
            return f"Request to {api_name} timed out. Please try again."
        return f"An error occurred with {api_name}. Please try again later."

    @classmethod
    def handle_processing_error(cls, error: Exception, file_name: str = "") -> str:
        """Handle an audio processing error, log it, and return a user-facing message.

        Args:
            error:     The exception that was raised.
            file_name: Name (not full path) of the file being processed.

        Returns:
            A sanitised, user-facing error string.
        """
        _logger.error("Processing error with %s: %s", file_name, error, exc_info=True)

        if cls._is_debug():
            return f"Processing error with {file_name}: {str(error)}"

        mapped = map_to_audio_error(error, context={"file": file_name})
        return user_message_for(mapped)

    @classmethod
    def handle_config_error(cls, error: Exception, config_file: str = "") -> str:
        """Handle a configuration file error, log it, and return a user-facing message.

        Args:
            error:       The exception that was raised.
            config_file: Name or path of the configuration file involved.

        Returns:
            A sanitised, user-facing error string.
        """
        _logger.error("Config error with %s: %s", config_file, error, exc_info=True)

        if cls._is_debug():
            return f"Configuration error in {config_file}: {str(error)}"

        mapped = map_to_audio_error(error, context={"config_file": config_file})
        return user_message_for(mapped)

    @classmethod
    def set_debug_mode(cls, debug: bool) -> None:
        """Toggle debug mode, controlling whether raw error detail is exposed.

        Sets the ``AUDIOSUITE_DEBUG`` environment variable so that
        ``_is_debug()`` and ``user_message_for()`` pick up the change
        on the next call (no import-time evaluation).

        Args:
            debug: ``True`` to enable raw error output; ``False`` to sanitise.
        """
        os.environ["AUDIOSUITE_DEBUG"] = "1" if debug else "0"

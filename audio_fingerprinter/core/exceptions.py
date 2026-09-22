"""Domain-specific exceptions for the Audio Fingerprinter tool.

All classes inherit from ``AudioProcessingError`` so the shared suite
``except AudioSuiteError`` / ``user_message_for()`` boundaries keep working
unchanged.
"""

from audio_suite_shared.exceptions import (
    AudioExternalToolError,
    AudioMissingDependencyError,
    AudioProcessingError,
)


class FingerprintError(AudioProcessingError):
    """Root error for the Audio Fingerprinter tool."""


class FingerprintToolError(FingerprintError):
    """The ``fpcalc`` binary could not be found or failed to produce output.

    Maps from: FileNotFoundError (binary not on PATH), non-zero fpcalc exit.
    """


class FingerprintUnsupportedError(FingerprintError):
    """An input file could not be fingerprinted (no audio track, unsupported
    container, or corrupted data)."""


class AcoustidError(FingerprintError):
    """Root error for AcoustID web-service communication."""


class AcoustidAuthError(AcoustidError):
    """The AcoustID API key was rejected by the web service."""


class AcoustidApiError(AcoustidError):
    """The AcoustID web service returned a non-2xx HTTP response."""


__all__ = [
    "AcoustidApiError",
    "AcoustidAuthError",
    "AcoustidError",
    "FingerprintError",
    "FingerprintToolError",
    "FingerprintUnsupportedError",
    "AudioExternalToolError",
    "AudioMissingDependencyError",
]

"""AcoustID API-key storage — encrypted persistence + environment fallback.

The key is stored at the top level of ``audio_suite_config.json`` under
``acoustid_api_key``, encrypted with the suite's shared ``KeyManager``.
Resolution order is:

    ``ACOUSTID_API_KEY`` env var  >  decrypted ``acoustid_api_key`` config value
"""

from __future__ import annotations

import logging
import os

from audio_suite_shared.exceptions import AudioProcessingError, handle_audio_errors
from audio_suite_shared.security.key_manager import KeyManager
from audio_suite_shared.suite_config import CONFIG_PATH, load_value, save_value

logger = logging.getLogger(__name__)

CONFIG_KEY = "acoustid_api_key"
ENV_VAR = "ACOUSTID_API_KEY"


def get_key_manager() -> KeyManager:
    """Return a KeyManager bound to the suite config file.

    Returns:
        A fresh ``KeyManager`` instance.
    """
    return KeyManager(str(CONFIG_PATH))


@handle_audio_errors(reraise=False, context="load_api_key")
def load_api_key() -> str:
    """Return the configured AcoustID API key, if any.

    Resolution order: ``ACOUSTID_API_KEY`` environment variable, then the
    encrypted ``acoustid_api_key`` value in the suite config.

    Returns:
        The key string, or ``""`` when none is configured.
    """
    from_env = os.environ.get(ENV_VAR, "").strip()
    if from_env:
        return from_env

    stored = load_value(CONFIG_KEY, "")
    if not isinstance(stored, str) or not stored:
        return ""

    try:
        return get_key_manager().decrypt_string(stored)
    except AudioProcessingError:
        logger.warning("Stored AcoustID API key could not be decrypted.", exc_info=True)
        return ""


def save_api_key(api_key: str) -> None:
    """Encrypt and persist the AcoustID API key.

    Args:
        api_key: The key to store.  An empty string clears the stored key.

    Raises:
        AudioProcessingError: If encryption fails.
    """
    value = ""
    if api_key:
        value = get_key_manager().encrypt_string(api_key.strip())
    save_value(CONFIG_KEY, value)


def clear_api_key() -> None:
    """Remove the stored AcoustID API key from the config."""
    save_value(CONFIG_KEY, "")


def has_api_key() -> bool:
    """Return whether an API key is available via env var or config."""
    return bool(load_api_key())

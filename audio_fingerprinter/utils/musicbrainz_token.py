"""MusicBrainz submission-token storage — encrypted persistence + env fallback.

The token is stored at the top level of ``audio_suite_config.json`` under
``musicbrainz_token``, encrypted with the suite's shared ``KeyManager``.
Resolution order is:

    ``MUSICBRAINZ_TOKEN`` env var  >  decrypted ``musicbrainz_token`` config value

The token is deliberately **never** accepted as a command-line argument: argv is
visible in process listings and shell history, and this secret creates public
edits in the user's name.  The environment variable covers one-off runs.

Changed in 1.2.0: new module — the credential for ``--submit-isrc``
(PLAN_feature_expansion.md D27).

Changed in 2.9.0: the credential store is the shared SecretStore (A6).
"""

from __future__ import annotations

import logging
import os

from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.secret_store import SecretStore
from audio_suite_shared.security.key_manager import KeyManager
from audio_suite_shared.suite_config import CONFIG_PATH, load_value, save_value

from ..core.musicbrainz_client import MBAAuthMethod, MBAuth

logger = logging.getLogger(__name__)

CONFIG_KEY = "musicbrainz_token"
ENV_VAR = "MUSICBRAINZ_TOKEN"

#: Same shared resolution order as the AcoustID key; only the credential, its
#: environment variable and its user-facing label differ.
_STORE = SecretStore(config_key=CONFIG_KEY, env_var=ENV_VAR, label="MusicBrainz token")


def get_key_manager() -> KeyManager:
    """Return a KeyManager bound to the suite config file.

    Returns:
        A fresh ``KeyManager`` instance.
    """
    return KeyManager(str(CONFIG_PATH))


@handle_audio_errors(reraise=False, context="load_musicbrainz_token")
def load_token() -> str:
    """Return the configured MusicBrainz token, if any.

    Resolution order: ``MUSICBRAINZ_TOKEN`` environment variable, then the
    encrypted ``musicbrainz_token`` value in the suite config.

    Returns:
        The token string, or ``""`` when none is configured.
    """
    return _STORE.load(get_key_manager(), load_value)


def save_token(token: str) -> None:
    """Encrypt and persist the MusicBrainz token.

    Args:
        token: The token to store.  An empty string clears the stored token.

    Raises:
        AudioProcessingError: If encryption fails.
    """
    _STORE.save(token, get_key_manager(), save_value)


def clear_token() -> None:
    """Remove the stored MusicBrainz token from the config."""
    _STORE.clear(save_value)


def has_token() -> bool:
    """Return whether a token is available via env var or config."""
    return bool(load_token())


def build_auth(method: MBAAuthMethod = "oauth", username: str = "") -> MBAuth:
    """Build the credentials for one run from the resolved token.

    Args:
        method: ``"oauth"`` (bearer) or ``"app-token"`` (legacy digest).
        username: MusicBrainz account name; required by ``"app-token"``.

    Returns:
        An :class:`MBAuth` carrying whatever token resolution found — an empty
        one when none is configured, which reports its own problem rather than
        sending an unauthenticated request.
    """
    return MBAuth(token=load_token(), method=method, username=username.strip())


def describe_source() -> str:
    """Return a caption naming where the token resolves from.

    Returns:
        One line for the Setup tab, mirroring the AcoustID key caption.
    """
    if os.environ.get(ENV_VAR, "").strip():
        return f"MusicBrainz token: set via the {ENV_VAR} environment variable."
    if load_token():
        return "MusicBrainz token: stored (encrypted) in the suite config."
    return (
        "No MusicBrainz token configured — ISRC submission only previews the "
        "payload until one is set."
    )


__all__ = [
    "CONFIG_KEY",
    "ENV_VAR",
    "build_auth",
    "clear_token",
    "describe_source",
    "get_key_manager",
    "has_token",
    "load_token",
    "save_token",
]

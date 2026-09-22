"""
core.providers — pluggable lyric-source architecture.

A provider fetches lyrics for a given artist/title pair from a remote
service.  New sources are added by subclassing :class:`LyricProvider` and
registering the class via :func:`register_provider`, so the Setup-tab
provider list and the registry-driven resolution stay in sync.
"""

from .base import LyricProvider, LyricProviderError, LyricResult
from .registry import get_provider, get_provider_names, register_provider

__all__ = [
    "LyricProvider",
    "LyricProviderError",
    "LyricResult",
    "get_provider",
    "get_provider_names",
    "register_provider",
]

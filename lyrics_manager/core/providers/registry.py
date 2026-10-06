"""
registry.py — provider registry and factory.

Providers register themselves by class; ``get_provider(name)`` hands out a
fresh instance so the processor never shares mutable state across worker
threads.  LRCLIB is registered at import time; future sources register in
the same way (drop-in + one registration line).
"""

from __future__ import annotations

from typing import TypeAlias

from .base import LyricProvider, LyricProviderError
from .lrclib import LRCLIBProvider
from .sidecar import SidecarProvider

ProviderFactory: TypeAlias = type[LyricProvider]

_registry: dict[str, ProviderFactory] = {}


def register_provider(provider_cls: ProviderFactory) -> None:
    """Register a provider class under its ``name`` attribute.

    Args:
        provider_cls: A :class:`LyricProvider` subclass with a non-empty
            ``name``.

    Raises:
        ValueError: If the class has an empty name or the name is already
            registered.
    """
    if not provider_cls.name:
        raise ValueError(f"Provider class {provider_cls.__name__} has no name")
    if provider_cls.name in _registry:
        raise ValueError(f"Lyric provider '{provider_cls.name}' already registered")
    _registry[provider_cls.name] = provider_cls


def get_provider(name: str) -> LyricProvider:
    """Return a fresh provider instance for *name*.

    Args:
        name: Registered provider identifier (e.g. ``'lrclib'``).

    Returns:
        A new provider instance.

    Raises:
        LyricProviderError: If *name* is not registered.
    """
    provider_cls = _registry.get(name)
    if provider_cls is None:
        raise LyricProviderError(f"Unknown lyric provider: {name}")
    return provider_cls()


def get_provider_names() -> list[str]:
    """Return the registered provider identifiers, sorted alphabetically."""
    return sorted(_registry)


register_provider(LRCLIBProvider)
register_provider(SidecarProvider)

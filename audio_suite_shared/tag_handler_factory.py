"""
tag_handler_factory.py — the tag-handler registry, in a leaf module.

Part of audio_suite_shared. ``TagHandlerFactory`` used to live at the bottom of
``tag_helper_base`` beside ``BaseTagHandler``, so the registry imported its six
handler modules there while every handler imported the base back — a cycle that
made a handler module unusable as the first tag-helper import in a fresh
interpreter. The registry is a leaf now: nothing is imported at module level
except the format matrix it declares itself against, and the handler table is
built on first use.

Changed in 2.4.1: new leaf module extracted from ``tag_helper_base`` (plan
WP-2, C-M7).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Mapping
from importlib import import_module
from typing import TYPE_CHECKING

from .audio_formats import FORMAT_MATRIX
from .exceptions import AudioFormatError

if TYPE_CHECKING:
    from .tag_helper_base import BaseTagHandler

logger = logging.getLogger(f"audio_suite.{__name__}")

#: ``(module, class, extensions)`` for each tag convention. The extensions are
#: declared here by hand rather than read from the matrix, so the two sides can
#: still disagree loudly; :func:`_handlers` only accepts a declared extension
#: when the matrix also marks it ``tag_writable``.
_HANDLER_FAMILIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("tag_helper_mp3", "MP3Handler", (".mp3",)),
    ("tag_helper_vorbis", "VorbisHandler", (".flac", ".ogg", ".opus", ".spx")),
    ("tag_helper_mp4", "MP4Handler", (".m4a", ".mp4")),
    ("tag_helper_iffid3", "IFFID3Handler", (".wav", ".aiff", ".aif")),
    ("tag_helper_apev2", "APEv2Handler", (".wv", ".ape", ".mpc")),
    ("tag_helper_dsf", "DSFID3Handler", (".dsf",)),
)


def _normalise(extension: str) -> str:
    """Return an extension in the canonical ``".ext"`` lower-case form.

    Args:
        extension: Extension with or without its leading dot, any case.

    Returns:
        The canonical dotted, lower-case extension.
    """
    key = extension.strip().lower()
    return key if key.startswith(".") else f".{key}"


def _handlers() -> dict[str, type[BaseTagHandler]]:
    """Build the extension-to-handler-class table.

    The six handler modules are imported *inside* this function: each of them
    imports ``BaseTagHandler``, so importing them at module level is exactly the
    cycle this module exists to avoid.

    Returns:
        Mapping of every tag-writable container to the class that handles it.
    """
    table: dict[str, type[BaseTagHandler]] = {}
    for module_name, class_name, extensions in _HANDLER_FAMILIES:
        writable = tuple(
            ext
            for ext in extensions
            if ext in FORMAT_MATRIX and FORMAT_MATRIX[ext].tag_writable
        )
        if not writable:
            logger.debug("No tag-writable container in handler family %s", module_name)
            continue
        module = import_module(f".{module_name}", __package__)
        handler_cls: type[BaseTagHandler] = getattr(module, class_name)
        for ext in writable:
            table[ext] = handler_cls
    return table


class _HandlerTable(Mapping[str, "type[BaseTagHandler]"]):
    """Extension-to-handler mapping that is built on first access.

    A plain dict cannot be used: it would have to be populated at import time,
    which reintroduces the cycle. Everything a dict consumer does — iteration,
    ``in``, indexing, ``.get`` — goes through this mapping instead.
    """

    __slots__ = ("_built",)

    def __init__(self) -> None:
        """Create an unbuilt table."""
        self._built: dict[str, type[BaseTagHandler]] | None = None

    def _table(self) -> dict[str, type[BaseTagHandler]]:
        """Return the table, building it once.

        Returns:
            The extension-to-handler-class mapping.
        """
        if self._built is None:
            self._built = _handlers()
        return self._built

    def __getitem__(self, key: str) -> type[BaseTagHandler]:
        """Return the handler class registered for ``key``.

        Args:
            key: Dotted, lower-case extension.

        Returns:
            The handler class.

        Raises:
            KeyError: When the extension has no handler.
        """
        return self._table()[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate the registered extensions.

        Returns:
            Iterator over the extension keys.
        """
        return iter(self._table())

    def __len__(self) -> int:
        """Return how many extensions are registered.

        Returns:
            The number of registered extensions.
        """
        return len(self._table())


class TagHandlerFactory:
    """Factory for the tag handler appropriate to a file's container."""

    #: Kept as a name for the registry itself: existing callers (and the
    #: ``tag_writable`` lock in ``tests/test_audio_formats.py``) read the table
    #: directly, and a mapping preserves that surface without an eager import.
    _handlers: Mapping[str, type[BaseTagHandler]] = _HandlerTable()

    @classmethod
    def for_extension(cls, extension: str) -> type[BaseTagHandler]:
        """Return the handler class for one extension.

        Args:
            extension: Extension with or without its leading dot, any case.

        Returns:
            The handler class registered for the container.

        Raises:
            AudioFormatError: When the container has no tag handler.
        """
        key = _normalise(extension)
        try:
            return cls._handlers[key]
        except KeyError:
            raise AudioFormatError(f"Unsupported format: {key}") from None

    @classmethod
    def is_supported(cls, extension: str) -> bool:
        """Report whether an extension has a tag handler.

        Args:
            extension: Extension with or without its leading dot, any case.

        Returns:
            True when the factory can dispatch the container.
        """
        return _normalise(extension) in cls._handlers

    @classmethod
    def supported_extensions(cls) -> frozenset[str]:
        """Return every extension the factory can dispatch.

        Returns:
            The registered extensions, dotted and lower-case.
        """
        return frozenset(cls._handlers)

    @classmethod
    def get_handler(cls, path: str) -> BaseTagHandler:
        """Return a loaded handler appropriate for the file's extension.

        Args:
            path: Path to the audio file.

        Returns:
            A fully loaded ``BaseTagHandler`` subclass instance.

        Raises:
            AudioFormatError: If the file extension has no registered handler.
        """
        ext = os.path.splitext(path)[1].lower()
        handler_cls = cls._handlers.get(ext)
        if handler_cls is None:
            raise AudioFormatError(f"Unsupported format: {ext}")

        handler = handler_cls(path)
        handler.load()
        return handler

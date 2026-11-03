"""
tests/test_tag_handler_factory.py
Locks for ``audio_suite_shared/tag_handler_factory.py`` (2.4.1 WP-2).

The factory moved out of ``tag_helper_base`` because that module also owns
``BaseTagHandler``, which every handler subclasses: keeping the registry there
meant its bottom imports and the handlers' own import of the base formed a
cycle, so a handler module could not be the first tag-helper import in a fresh
interpreter. These locks pin the leaf's surface and its agreement with the
format matrix. The import direction itself is locked separately, in a fresh
interpreter, by ``tests/test_import_isolation.py``.

Changed in 2.4.1: new lock module for the extracted tag-handler factory.
"""

from __future__ import annotations

import pytest

from audio_suite_shared.audio_formats import FORMAT_MATRIX
from audio_suite_shared.exceptions import AudioFormatError
from audio_suite_shared.tag_handler_factory import TagHandlerFactory
from audio_suite_shared.tag_helper_base import BaseTagHandler

#: Frozen: the containers the factory dispatches, transcribed by hand from the
#: handler modules themselves, so the lock fails when the two drift apart.
FACTORY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp3",
        ".flac",
        ".ogg",
        ".opus",
        ".spx",
        ".m4a",
        ".mp4",
        ".wav",
        ".aiff",
        ".aif",
        ".wv",
        ".ape",
        ".mpc",
        ".dsf",
    }
)


class TestRegistry:
    def test_handles_exactly_the_transcribed_extensions(self) -> None:
        assert TagHandlerFactory.supported_extensions() == FACTORY_EXTENSIONS

    def test_every_handled_container_is_tag_writable_in_the_matrix(self) -> None:
        declared = {ext for ext, row in FORMAT_MATRIX.items() if row.tag_writable}
        assert declared == FACTORY_EXTENSIONS
        for ext in FACTORY_EXTENSIONS:
            assert FORMAT_MATRIX[ext].tag_writable is True

    def test_writable_but_untaggable_containers_are_refused(self) -> None:
        # Both decode and encode, but no ASF or ADTS tag handler exists yet
        # (WP-6 owns ASF), so a writer must refuse them rather than discover
        # an untaggable file halfway through a batch.
        for ext in (".wma", ".aac"):
            assert ext in FORMAT_MATRIX
            assert FORMAT_MATRIX[ext].tag_writable is False
            assert TagHandlerFactory.is_supported(ext) is False

    def test_is_supported_accepts_bare_and_upper_case_extensions(self) -> None:
        assert TagHandlerFactory.is_supported("MP3") is True
        assert TagHandlerFactory.is_supported(" .flac ") is True
        assert TagHandlerFactory.is_supported(".xyz") is False

    def test_table_attribute_still_lists_the_container_set(self) -> None:
        # ``_handlers`` is the name existing callers read; it stays a mapping.
        assert set(TagHandlerFactory._handlers) == FACTORY_EXTENSIONS
        assert len(TagHandlerFactory._handlers) == len(FACTORY_EXTENSIONS)


class TestForExtension:
    @pytest.mark.parametrize(
        ("extension", "handler_name"),
        [
            (".mp3", "MP3Handler"),
            (".flac", "VorbisHandler"),
            (".ogg", "VorbisHandler"),
            (".opus", "VorbisHandler"),
            (".spx", "VorbisHandler"),
            (".m4a", "MP4Handler"),
            (".mp4", "MP4Handler"),
            (".wav", "IFFID3Handler"),
            (".aiff", "IFFID3Handler"),
            (".aif", "IFFID3Handler"),
            (".wv", "APEv2Handler"),
            (".ape", "APEv2Handler"),
            (".mpc", "APEv2Handler"),
            (".dsf", "DSFID3Handler"),
        ],
    )
    def test_resolves_the_declared_handler_class(
        self, extension: str, handler_name: str
    ) -> None:
        handler_cls = TagHandlerFactory.for_extension(extension)
        assert handler_cls.__name__ == handler_name
        assert issubclass(handler_cls, BaseTagHandler)

    def test_accepts_a_bare_extension(self) -> None:
        assert TagHandlerFactory.for_extension("mp3") is (
            TagHandlerFactory.for_extension(".mp3")
        )

    def test_unknown_extension_raises(self) -> None:
        with pytest.raises(AudioFormatError, match="Unsupported"):
            TagHandlerFactory.for_extension(".xyz")


class TestGetHandler:
    def test_unknown_extension_raises(self, tmp_path) -> None:
        target = tmp_path / "file.xyz"
        target.write_bytes(b"x")
        with pytest.raises(AudioFormatError, match="Unsupported"):
            TagHandlerFactory.get_handler(str(target))

    def test_refuses_a_writable_but_untaggable_container(self, tmp_path) -> None:
        target = tmp_path / "file.wma"
        target.write_bytes(b"x")
        with pytest.raises(AudioFormatError, match="Unsupported"):
            TagHandlerFactory.get_handler(str(target))

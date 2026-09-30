"""
tag_helper_iffid3.py — WAV/AIFF (RIFF ID3) tag handler.

The ``IFFID3Handler`` implementation, relocated verbatim from
``tag_helper_base.py`` by iteration-7 C2 (plan-governed god-file split).
It subclasses ``MP3Handler`` (tag_helper_mp3.py). Import the public surface
through ``audio_suite_shared.tag_helper_base``: this module participates in
the facade import cycle and must not be the first tag-helper module imported
in a fresh interpreter.
"""

import logging
import os

from .exceptions import AudioFormatError
from .tag_helper_mp3 import MP3Handler

# Emit through the tag-helper subsystem logger: the logger name is part of
# the module's observable behaviour (pinned by the test suite's caplog
# filters) and must survive the per-format module split unchanged.
logger = logging.getLogger("audio_suite_shared.tag_helper_base")


class IFFID3Handler(MP3Handler):
    """Handler for WAV and AIFF files, both of which embed ID3 tags.

    ``mutagen.wave.WAVE`` and ``mutagen.aiff.AIFF`` both expose a ``tags``
    attribute backed by ``mutagen.id3.ID3``, identical to ``mutagen.mp3.MP3``.
    All read/write logic (TCON, TXXX, TPE1, TPE2, TALB, APIC, etc.) is
    therefore inherited unchanged from :class:`MP3Handler`; only the
    format-specific ``load()`` differs.
    """

    _MUTAGEN_CLASS_BY_EXT: dict[str, str] = {
        ".wav": "wave.WAVE",
        ".aiff": "aiff.AIFF",
        ".aif": "aiff.AIFF",
    }

    def load(self) -> None:
        """Load the WAV or AIFF file and its ID3 tags.

        Selects ``mutagen.wave.WAVE`` for ``.wav`` files and
        ``mutagen.aiff.AIFF`` for ``.aiff``/``.aif`` files, based on the
        file's extension. Falls back to a tagless load if ID3 parsing
        fails on an otherwise valid file (e.g. unusual padding).

        Raises:
            ValueError: If the file extension is neither WAV nor AIFF.
        """
        import mutagen.aiff
        import mutagen.wave

        ext = os.path.splitext(self.path)[1].lower()
        audio_cls: type[mutagen.wave.WAVE] | type[mutagen.aiff.AIFF]
        if ext == ".wav":
            audio_cls = mutagen.wave.WAVE
        elif ext in (".aiff", ".aif"):
            audio_cls = mutagen.aiff.AIFF
        else:
            raise AudioFormatError(f"IFFID3Handler cannot load extension: {ext}")

        try:
            self._audio = audio_cls(self.path)
            self._tags = self._audio.tags
        except Exception as _id3_exc:
            logger.debug(
                "ID3 load failed for %s, retrying without tags: %s",
                self.path,
                _id3_exc,
            )
            self._audio = audio_cls(self.path)
            self._tags = self._audio.tags

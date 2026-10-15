"""
tag_helper_dsf.py — DSD (DSF) ID3 tag handler.

The ``DSFID3Handler`` implementation for ``.dsf`` files added by Sprint 1 of
``PLAN_feature_expansion.md`` item 1.1 (D15).  ``mutagen.dsf.DSF`` exposes a
``tags`` attribute backed by ``mutagen.id3.ID3`` (and ``add_tags()`` to
create one), identical to ``mutagen.mp3.MP3``.  All read/write logic (TCON,
TXXX, TPE1, TPE2, TALB, APIC, etc.) is therefore inherited unchanged from
:class:`MP3Handler`; only the format-specific ``load()`` differs.

Import the public surface through ``audio_suite_shared.tag_helper_base``:
this module participates in the facade import cycle and must not be the
first tag-helper module imported in a fresh interpreter.

Note (empirically pinned, D20): ``mutagen.dsf.DSF`` accepts only ``ID3``
*Frame* instances (e.g. ``TBPM(...)``) via ``tags.add``; assigning a plain
``str`` raises ``TypeError``.  This matches ``MP3Handler``'s existing frame
usage.

Changed in 1.1.0: new DSF (ID3-backed) tag handler for .dsf.
"""

import logging

from .exceptions import AudioFormatError
from .tag_helper_mp3 import MP3Handler

# Emit through the tag-helper subsystem logger: the logger name is part of
# the module's observable behaviour (pinned by the test suite's caplog
# filters) and must survive the per-format module split unchanged. The name
# tracks tag_helper_base's own namespaced logger (iteration-8 C8), so all
# format modules keep sharing one logger and their records still reach the
# RotatingFileHandler attached to the "audio_suite" logger.
logger = logging.getLogger("audio_suite.audio_suite_shared.tag_helper_base")


class DSFID3Handler(MP3Handler):
    """Handler for DSF (DSD) files, which embed ID3 tags."""

    def load(self) -> None:
        """Load the DSF file and its ID3 tags.

        Falls back to a tagless load if ID3 parsing fails on an otherwise
        valid file.

        Raises:
            AudioFormatError: If the file extension is not ``.dsf``.
        """
        import os

        import mutagen.dsf

        ext = os.path.splitext(self.path)[1].lower()
        if ext != ".dsf":
            raise AudioFormatError(f"DSFID3Handler cannot load extension: {ext}")

        try:
            self._audio = mutagen.dsf.DSF(self.path)
            self._tags = self._audio.tags
        except Exception as _id3_exc:
            logger.debug(
                "ID3 load failed for %s, retrying without tags: %s",
                self.path,
                _id3_exc,
            )
            audio = mutagen.dsf.DSF(self.path)
            self._audio = audio
            self._tags = None

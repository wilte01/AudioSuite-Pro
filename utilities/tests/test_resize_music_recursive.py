"""Tests for ``utilities/resize_music_recursive.py``.

Plan iteration 7, item A3 (audit A5): the embedded-artwork size check used a
bare ``except Exception: pass``. A corrupt ``APIC`` frame therefore became
indistinguishable from "already at the target size", so corrupt art was
silently re-processed with no diagnostic anywhere.

The resize-on-corrupt *behaviour* was always correct - a frame PIL cannot
decode cannot be size-checked, so proceeding to the resize is the safe action.
The defect was the silence. These tests lock both halves:

1. *Witness* - a corrupt frame reaches the resize and emits a ``DEBUG`` record
   naming the file and the tag key, with the underlying decode traceback.
2. *No false positives* - a decodable frame that is genuinely already at the
   target size is still skipped, still emits no such record. Without this, a
   blanket ``logger.debug`` in the ``except`` would satisfy assertion 1 while
   destroying the skip path.
3. *Narrow catch* - the handler is typed to ``(UnidentifiedImageError, OSError)``
   rather than ``Exception``, so an unrelated programming error is no longer
   disguised as "corrupt artwork".
"""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utilities import resize_music_recursive as rmr  # noqa: E402

CORRUPT_APIC = b"\x00\x01\x02 this is not a decodable image"


def _make_mp3(directory: Path, name: str = "track.mp3") -> Path:
    """Write a real, decodable MP3 to ``directory`` and return its path."""
    from pydub import AudioSegment

    path = directory / name
    AudioSegment.silent(duration=200, frame_rate=44100).export(
        str(path), format="mp3", bitrate="192k"
    )
    return path


def _make_mp3_with_apic(directory: Path, image_data: bytes) -> Path:
    """Write a real MP3 carrying an ``APIC`` frame with the given bytes.

    The bytes are stored verbatim, so a corrupt payload produces a real file
    whose embedded frame PIL genuinely cannot decode.
    """
    from mutagen.id3 import APIC, ID3

    path = _make_mp3(directory)
    tags = ID3()
    tags.add(
        APIC(
            encoding=3,
            mime="image/jpeg",
            type=3,
            desc="Cover (front)",
            data=image_data,
        )
    )
    tags.save(str(path))
    return path


def _real_png(size: int = 64) -> bytes:
    """Return a genuinely decodable PNG of ``size`` x ``size``."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (size, size), "red").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def resize_spy(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Record every payload handed to ``resize_image_bytes``.

    The real implementation is wrapped, not replaced, so the end-to-end
    outcome is still measured on the genuine code path.
    """
    calls: list[bytes] = []
    original = rmr.resize_image_bytes

    def spy(image_bytes: bytes, target_size: int) -> bytes | None:
        calls.append(image_bytes)
        return original(image_bytes, target_size)

    monkeypatch.setattr(rmr, "resize_image_bytes", spy)
    return calls


class TestCorruptEmbeddedArtIsWitnessed:
    """The defect surface: a corrupt APIC frame."""

    def test_corrupt_frame_still_reaches_the_resize(
        self, tmp_path: Path, resize_spy: list[bytes]
    ) -> None:
        """The size check cannot judge a corrupt frame, so it must not skip it."""
        path = _make_mp3_with_apic(tmp_path, CORRUPT_APIC)

        # Must not raise: the corrupt frame is handled, not propagated.
        rmr.resize_embedded_art(path, 300)

        assert resize_spy == [CORRUPT_APIC], (
            "the corrupt frame must proceed to the resize; it cannot be "
            "size-checked, so skipping it would silently re-process bad art"
        )

    def test_corrupt_frame_logs_debug_naming_file_and_key(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The silence is the defect; the record must name the file and key."""
        path = _make_mp3_with_apic(tmp_path, CORRUPT_APIC)

        with caplog.at_level(logging.DEBUG, logger="utilities.resize_music_recursive"):
            rmr.resize_embedded_art(path, 300)

        records = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG
            and r.name == "utilities.resize_music_recursive"
        ]
        assert records, (
            "no DEBUG record was emitted for the corrupt APIC frame; the "
            f"handler is still silent. caplog had: {caplog.text!r}"
        )
        message = records[0].getMessage()
        assert path.name in message, f"record does not name the file: {message!r}"
        assert "APIC" in message, f"record does not name the tag key: {message!r}"
        assert records[0].exc_info is not None, (
            "the record must carry the underlying UnidentifiedImageError "
            "traceback via exc_info=True"
        )

    def test_corrupt_frame_is_not_reported_as_already_at_size(
        self, tmp_path: Path, resize_spy: list[bytes]
    ) -> None:
        """A corrupt frame must never be silently accepted as on-target."""
        path = _make_mp3_with_apic(tmp_path, CORRUPT_APIC)

        rmr.resize_embedded_art(path, 300)

        assert CORRUPT_APIC in resize_spy, "the corrupt frame was skipped, not resized"


class TestDecodableArtIsUnaffected:
    """No false positives: the working paths must stay silent."""

    def test_frame_already_at_target_is_skipped(
        self, tmp_path: Path, resize_spy: list[bytes], caplog: pytest.LogCaptureFixture
    ) -> None:
        """A genuine on-target frame still short-circuits without a resize."""
        path = _make_mp3_with_apic(tmp_path, _real_png(300))

        with caplog.at_level(logging.DEBUG, logger="utilities.resize_music_recursive"):
            rmr.resize_embedded_art(path, 300)

        assert resize_spy == [], "an on-target frame must not be resized"
        assert not [
            r
            for r in caplog.records
            if r.levelno >= logging.DEBUG and "not decodable" in r.getMessage()
        ], "the corrupt-frame record must not fire for a decodable frame"

    def test_oversized_frame_is_resized_without_a_warning(
        self, tmp_path: Path, resize_spy: list[bytes], caplog: pytest.LogCaptureFixture
    ) -> None:
        """The normal resize path is a size mismatch, not a decode failure."""
        png = _real_png(500)
        path = _make_mp3_with_apic(tmp_path, png)

        with caplog.at_level(logging.DEBUG, logger="utilities.resize_music_recursive"):
            rmr.resize_embedded_art(path, 300)

        assert resize_spy == [png], "an oversized frame must be resized"
        assert not [
            r
            for r in caplog.records
            if r.name == "utilities.resize_music_recursive"
            and "not decodable" in r.getMessage()
        ], "a plain size mismatch must not be reported as undecodable"


class TestMissingArtIsNotAnError:
    """Pre-existing early returns must stay intact."""

    def test_non_audio_file_returns_false(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-audio file has no tags and is not a corrupt-frame case."""
        path = tmp_path / "notes.txt"
        path.write_text("not audio", encoding="utf-8")

        with caplog.at_level(logging.DEBUG, logger="utilities.resize_music_recursive"):
            result = rmr.resize_embedded_art(path, 300)

        assert result is False
        assert not [
            r for r in caplog.records if r.name.endswith("resize_music_recursive")
        ]


class TestUndecodableBytesHelper:
    """``resize_image_bytes`` still reports corrupt payloads as a None result."""

    def test_corrupt_payload_returns_none(self) -> None:
        assert rmr.resize_image_bytes(CORRUPT_APIC, 300) is None

    def test_decodable_payload_returns_jpeg(self) -> None:
        out: Any = rmr.resize_image_bytes(_real_png(500), 300)
        assert isinstance(out, bytes) and out
        from PIL import Image

        assert Image.open(io.BytesIO(out)).size == (300, 300)


# ─── Iteration-8 C6 (audit M16): the artwork branches ───
#
# The audit reported that
# ``if isinstance(audio, MP3) or hasattr(audio.tags, "add")`` captured FLAC
# (VorbisComment) and MP4 (MP4Tags) too, "because both implement .add",
# making the dedicated FLAC/MP4 branches unreachable. **That premise does
# not hold on the resolved mutagen (1.47.0): probed against real files, a
# FLAC's tags are VCFLACDict and an M4A's are MP4Tags, and neither has an
# ``add`` attribute.** The FLAC/MP4 branches were therefore already
# reachable, and restoring the old condition does not fail any test here.
#
# What the audit's other instruction — "verify the FLAC/MP4 art paths handle
# their real mutagen structures" — did surface is a genuine live defect: the
# reachable FLAC branch read ``pic.description``, which does not exist on
# mutagen's ``Picture`` (the field is ``desc``), so any FLAC file whose art
# was not already at the target size raised an uncaught AttributeError. The
# tests below pin that outcome by decoding what the tool wrote back.
#
# The narrowing keys on the TAGS class — ``isinstance(audio.tags, ID3)`` —
# not ``isinstance(audio, MP3)``: AIFF carries APIC frames in an ID3 subclass
# (``_IFFID3``) and was already served by the first branch, so keying on the
# file class would trade one silent loss for another. On mutagen 1.47.0 the
# narrowing is behaviour-identical for every supported format; it replaces an
# accidental ``hasattr`` probe whose meaning would silently break if a future
# mutagen grows ``.add`` on VComment/MP4Tags.


def _make_flac_with_art(directory: Path, image_data: bytes, size: int) -> Path:
    """Write a real FLAC carrying one embedded Picture of ``size``."""
    from mutagen.flac import FLAC, Picture
    from pydub import AudioSegment

    path = directory / "track.flac"
    AudioSegment.silent(duration=200, frame_rate=44100).export(str(path), format="flac")
    audio = FLAC(str(path))
    pic = Picture()
    pic.data = image_data
    pic.mime = "image/png"
    pic.type = 3
    pic.desc = "Cover (front)"
    pic.width = size
    pic.height = size
    pic.depth = 24
    audio.add_picture(pic)
    audio.save()
    return path


def _make_mp4_with_art(directory: Path, image_data: bytes) -> Path:
    """Write a real M4A carrying one embedded ``covr`` cover."""
    from mutagen.mp4 import MP4, MP4Cover
    from pydub import AudioSegment

    path = directory / "track.m4a"
    AudioSegment.silent(duration=200, frame_rate=44100).export(str(path), format="mp4")
    audio = MP4(str(path))
    audio["covr"] = [MP4Cover(image_data, imageformat=MP4Cover.FORMAT_PNG)]
    audio.save()
    return path


def _make_aiff_with_apic(directory: Path, image_data: bytes) -> Path:
    """Write a real AIFF carrying an ID3 ``APIC`` frame.

    AIFF's tags are mutagen's ``_IFFID3`` — an ``ID3`` subclass — so it
    depends on the tags-class narrowing to keep being served by the first
    branch. This is the regression guard for choosing
    ``isinstance(audio.tags, ID3)`` over ``isinstance(audio, MP3)``.
    """
    from mutagen import File
    from mutagen.id3 import APIC
    from pydub import AudioSegment

    path = directory / "track.aiff"
    AudioSegment.silent(duration=200, frame_rate=44100).export(str(path), format="aiff")
    audio = File(str(path), easy=False)
    if audio.tags is None:
        audio.add_tags()
    audio.tags.add(
        APIC(
            encoding=3,
            mime="image/png",
            type=3,
            desc="Cover (front)",
            data=image_data,
        )
    )
    audio.save()
    return path


class TestFlacEmbeddedArtIsResized:
    def test_flac_art_enters_the_flac_branch(
        self, tmp_path: Path, resize_spy: list[bytes]
    ) -> None:
        png = _real_png(500)
        path = _make_flac_with_art(tmp_path, png, size=500)

        assert rmr.resize_embedded_art(path, 300) is True
        assert resize_spy == [png], "FLAC art never reached the resize"

    def test_flac_art_outcome_is_measured_on_disk(self, tmp_path: Path) -> None:
        """Decode what the tool wrote back and measure it."""
        from mutagen.flac import FLAC
        from PIL import Image

        path = _make_flac_with_art(tmp_path, _real_png(500), size=500)
        assert rmr.resize_embedded_art(path, 300) is True

        reloaded = FLAC(str(path))
        assert len(reloaded.pictures) == 1
        pic = reloaded.pictures[0]
        assert (pic.width, pic.height) == (300, 300)
        assert Image.open(io.BytesIO(pic.data)).size == (300, 300)

    def test_flac_art_extractable(
        self, tmp_path: Path, resize_spy: list[bytes]
    ) -> None:
        """``extract_embedded_art_bytes`` reads the FLAC picture, not APIC."""
        png = _real_png(500)
        path = _make_flac_with_art(tmp_path, png, size=500)

        assert rmr.extract_embedded_art_bytes(path) == png


class TestMp4EmbeddedArtIsResized:
    def test_mp4_art_enters_the_mp4_branch(
        self, tmp_path: Path, resize_spy: list[bytes]
    ) -> None:
        png = _real_png(500)
        path = _make_mp4_with_art(tmp_path, png)

        assert rmr.resize_embedded_art(path, 300) is True
        assert resize_spy == [png], "MP4 art never reached the resize"

    def test_mp4_art_outcome_is_measured_on_disk(self, tmp_path: Path) -> None:
        """Decode what the tool wrote back and measure it."""
        from mutagen.mp4 import MP4
        from PIL import Image

        path = _make_mp4_with_art(tmp_path, _real_png(500))
        assert rmr.resize_embedded_art(path, 300) is True

        reloaded = MP4(str(path))
        covers = reloaded["covr"]
        assert len(covers) == 1
        assert Image.open(io.BytesIO(bytes(covers[0]))).size == (300, 300)

    def test_mp4_art_extractable(self, tmp_path: Path) -> None:
        png = _real_png(500)
        path = _make_mp4_with_art(tmp_path, png)

        assert bytes(rmr.extract_embedded_art_bytes(path)) == png


class TestAiffStillServedByTheId3Branch:
    def test_aiff_apic_art_is_resized(
        self, tmp_path: Path, resize_spy: list[bytes]
    ) -> None:
        """AIFF's ID3-subclass tags must keep reaching the APIC branch.

        Guards the deviation from the plan's literal
        ``isinstance(audio, MP3)``: that wording would have silently dropped
        AIFF embedded art, which the pre-fix code did resize.
        """
        png = _real_png(500)
        path = _make_aiff_with_apic(tmp_path, png)

        assert rmr.resize_embedded_art(path, 300) is True
        assert resize_spy == [png]

    def test_aiff_art_extractable(self, tmp_path: Path) -> None:
        png = _real_png(500)
        path = _make_aiff_with_apic(tmp_path, png)

        assert rmr.extract_embedded_art_bytes(path) == png


class TestMp3BehaviourIsUnchanged:
    def test_mp3_still_resized(self, tmp_path: Path, resize_spy: list[bytes]) -> None:
        png = _real_png(500)
        path = _make_mp3_with_apic(tmp_path, png)

        assert rmr.resize_embedded_art(path, 300) is True
        assert resize_spy == [png]

    def test_mp3_art_extractable(self, tmp_path: Path) -> None:
        png = _real_png(500)
        path = _make_mp3_with_apic(tmp_path, png)

        assert rmr.extract_embedded_art_bytes(path) == png

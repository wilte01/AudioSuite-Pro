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

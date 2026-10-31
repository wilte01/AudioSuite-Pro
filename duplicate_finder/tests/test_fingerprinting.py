"""Tests for building a record from one file on disk.

``build_record`` borrows fpcalc's fingerprint, mutagen's stream properties and
the shared tag reader.  The pieces that are *this module's* decisions are what is
pinned here: the ``Unknown`` sentinel becoming an empty tag, the bitrate
fallback when a container reports none, and a container mutagen cannot describe
staying a record instead of an error.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from audio_fingerprinter.core.fingerprinter import FingerprintToolError
from duplicate_finder.core import fingerprinting
from duplicate_finder.core.fingerprint_distance import FingerprintFormatError


class FakeFingerprint(SimpleNamespace):
    """The three fields ``generate_fingerprint`` returns that this module reads."""


@pytest.fixture()
def fingerprinted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace fpcalc with a stub and record the calls it receives.

    Args:
        monkeypatch: pytest's patch helper.

    Returns:
        The list the stub appends each fingerprinted path to.
    """
    calls: list[str] = []

    def _fake(path: str, *, raw: bool = False, **kwargs: object) -> FakeFingerprint:
        calls.append(path)
        assert raw is True, "a comparable fingerprint needs fpcalc -raw"
        return FakeFingerprint(fingerprint="1,2,3,4", duration=210.0)

    monkeypatch.setattr(fingerprinting, "generate_fingerprint", _fake)
    return calls


@pytest.fixture()
def no_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make mutagen and the tag reader report a file with nothing to read.

    Args:
        monkeypatch: pytest's patch helper.
    """
    monkeypatch.setattr(fingerprinting.mutagen, "File", lambda _path: None)
    monkeypatch.setattr(
        fingerprinting, "read_artist_title", lambda _path: ("Unknown", "Unknown")
    )


class TestBuildRecord:
    """What one file contributes to the decision."""

    def test_the_fingerprint_is_asked_for_in_raw_form(
        self, tmp_path: Path, fingerprinted: list[str], no_metadata: None
    ) -> None:
        path = tmp_path / "song.flac"
        path.write_bytes(b"audio")

        record = fingerprinting.build_record(str(path), 1000.0, path.stat().st_size)

        assert fingerprinted == [str(path)]
        assert record.words == (1, 2, 3, 4)
        assert record.duration == 210.0

    def test_the_stamp_is_the_one_the_caller_measured(
        self, tmp_path: Path, fingerprinted: list[str], no_metadata: None
    ) -> None:
        path = tmp_path / "song.flac"
        path.write_bytes(b"audio")

        record = fingerprinting.build_record(str(path), 1234.5, 4242)

        assert (record.mtime, record.size) == (1234.5, 4242)

    def test_the_cached_reader_sentinel_becomes_an_empty_tag(
        self, tmp_path: Path, fingerprinted: list[str], no_metadata: None
    ) -> None:
        path = tmp_path / "song.flac"
        path.write_bytes(b"audio")

        record = fingerprinting.build_record(str(path), 1.0, 5)

        assert record.artist == ""
        assert record.title == ""

    def test_real_tags_are_kept(
        self, tmp_path: Path, fingerprinted: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            fingerprinting, "read_artist_title", lambda _path: ("Artist", "Title")
        )
        path = tmp_path / "song.flac"
        path.write_bytes(b"audio")

        record = fingerprinting.build_record(str(path), 1.0, 5)

        assert (record.artist, record.title) == ("Artist", "Title")

    def test_the_bitrate_falls_back_to_size_over_duration(
        self, tmp_path: Path, fingerprinted: list[str], no_metadata: None
    ) -> None:
        path = tmp_path / "song.flac"
        path.write_bytes(b"x" * 1000)

        # 1000 bytes over 210 s is ~0.038 kbit/s; the point is that the fallback
        # is derived from the file rather than left at zero.
        record = fingerprinting.build_record(str(path), 1.0, 1000)

        assert record.bitrate_kbps > 0.0

    def test_a_container_mutagen_cannot_read_still_yields_a_record(
        self, tmp_path: Path, fingerprinted: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _explode(_path: str) -> object:
            raise ValueError("no handler for this container")

        monkeypatch.setattr(fingerprinting.mutagen, "File", _explode)
        monkeypatch.setattr(
            fingerprinting, "read_artist_title", lambda _path: ("Unknown", "Unknown")
        )
        path = tmp_path / "song.opus"
        path.write_bytes(b"audio")

        record = fingerprinting.build_record(str(path), 1.0, 5)

        # No stream properties, so the bitrate falls back to size over the
        # fingerprinted duration; the record still exists and still ranks.
        assert (record.sample_rate, record.channels) == (0, 0)
        assert record.bitrate_kbps == pytest.approx((5 * 8.0) / 210.0 / 1000.0)
        assert record.lossless is False

    def test_stream_properties_are_read_when_present(
        self, tmp_path: Path, fingerprinted: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        info = SimpleNamespace(sample_rate=96000, channels=2, bitrate=2304000)
        monkeypatch.setattr(
            fingerprinting.mutagen,
            "File",
            lambda _path: SimpleNamespace(info=info),
        )
        path = tmp_path / "song.flac"
        path.write_bytes(b"audio")

        record = fingerprinting.build_record(str(path), 1.0, 5)

        assert (record.sample_rate, record.channels) == (96000, 2)
        assert record.bitrate_kbps == pytest.approx(2304.0)

    def test_lossless_is_decided_by_the_container(
        self, tmp_path: Path, fingerprinted: list[str], no_metadata: None
    ) -> None:
        flac = tmp_path / "song.flac"
        mp3 = tmp_path / "song.mp3"
        flac.write_bytes(b"audio")
        mp3.write_bytes(b"audio")

        assert fingerprinting.build_record(str(flac), 1.0, 5).lossless is True
        assert fingerprinting.build_record(str(mp3), 1.0, 5).lossless is False

    def test_the_path_is_normalised(
        self, tmp_path: Path, fingerprinted: list[str], no_metadata: None
    ) -> None:
        path = tmp_path / "song.flac"
        path.write_bytes(b"audio")
        messy = os.path.join(str(tmp_path), ".", "song.flac")

        record = fingerprinting.build_record(messy, 1.0, 5)

        assert record.path == str(path)

    def test_a_fpcalc_failure_propagates_as_the_tool_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_metadata: None
    ) -> None:
        def _fail(_path: str, **_kwargs: object) -> object:
            raise FingerprintToolError("fpcalc is unavailable")

        monkeypatch.setattr(fingerprinting, "generate_fingerprint", _fail)
        path = tmp_path / "song.flac"
        path.write_bytes(b"audio")

        with pytest.raises(FingerprintToolError):
            fingerprinting.build_record(str(path), 1.0, 5)

    def test_a_fingerprint_that_is_not_a_word_array_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_metadata: None
    ) -> None:
        monkeypatch.setattr(
            fingerprinting,
            "generate_fingerprint",
            lambda _path, **_kwargs: FakeFingerprint(
                fingerprint="AQAA", duration=210.0
            ),
        )
        path = tmp_path / "song.flac"
        path.write_bytes(b"audio")

        with pytest.raises(FingerprintFormatError):
            fingerprinting.build_record(str(path), 1.0, 5)

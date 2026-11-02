"""End-to-end tests for restoring a suite stub and recursive discovery.

The outcome is measured on disk: the recreated file's bytes, its name and the
tags a fresh ``mutagen`` read returns.  The stub must survive every failure,
because it is the only pointer back to the kept audio.

Changed in 2.4.0: new tests for the ASX-stub restore path
(PLAN_duplicate_disposition_2026-11-02.md DD-4).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydub import AudioSegment

from asx_extractor.core import file_ops
from asx_extractor.core.asx_parser import process_asx_file
from asx_extractor.core.file_ops import recreate_from_stub
from audio_suite_shared.asx_stub import (
    StubMetadata,
    build_stub,
    snapshot_tags,
    with_keeper,
    write_stub,
)
from audio_suite_shared.tag_helper_reader import (
    read_editable_tags,
    read_lyrics_tags,
)
from audio_suite_shared.tag_helper_writer import (
    write_editable_tag,
    write_plain_lyrics,
)


def _sha256(path: Path) -> str:
    """Return the file's hex digest.

    Args:
        path: File to hash.

    Returns:
        The SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audio(path: Path, fmt: str) -> Path:
    """Write a short silent file in *fmt*.

    Args:
        path: Destination path.
        fmt: ``pydub`` export format.

    Returns:
        *path*.
    """
    AudioSegment.silent(duration=250).export(str(path), format=fmt)
    return path


@pytest.fixture()
def keeper(tmp_path: Path) -> Path:
    """A real lossless file that a stub can point at."""
    return _audio(tmp_path / "song.flac", "flac")


@pytest.fixture()
def duplicate(tmp_path: Path) -> Path:
    """A tagged lossy file whose metadata a stub carries."""
    path = _audio(tmp_path / "song_128.mp3", "mp3")
    write_editable_tag(str(path), "title", "Stub Title")
    write_editable_tag(str(path), "artist", "Stub Artist")
    write_editable_tag(str(path), "album", "Stub Album")
    write_editable_tag(str(path), "album_artist", "")
    write_editable_tag(str(path), "track", "7")
    write_editable_tag(str(path), "comment", "line one\nline two")
    write_plain_lyrics(str(path), "lyric one\nlyric two")
    return path


def _stub(tmp_path: Path, keeper: Path, duplicate: Path) -> Path:
    """Write a real stub for *duplicate* beside it, pointing at *keeper*.

    Args:
        tmp_path: Folder for the stub.
        keeper: The audio the stub references.
        duplicate: The file the stub describes.

    Returns:
        The stub path.
    """
    metadata = with_keeper(snapshot_tags(duplicate), keeper)
    path = tmp_path / "song_128.asx"
    write_stub(path, metadata)
    return path


class TestRestore:
    """A stub recreates the keeper's content with the duplicate's name/tags."""

    def test_content_name_and_tags_are_recreated(
        self, tmp_path: Path, keeper: Path, duplicate: Path
    ) -> None:
        stub = _stub(tmp_path, keeper, duplicate)
        expected_fields = read_editable_tags(str(duplicate))
        expected_lyrics = read_lyrics_tags(str(duplicate)).plain

        parsed = process_asx_file(stub, tmp_path)

        assert parsed["success"] is True
        assert parsed["audio_path"] == keeper.resolve()
        assert parsed["stub"] is not None
        ok, reason = recreate_from_stub(
            parsed["asx_path"], parsed["audio_path"], parsed["stub"]
        )

        assert ok is True, reason
        restored = tmp_path / "song_128.flac"
        assert restored.exists()
        # Tags change the container bytes, so compare the decoded audio, which
        # is the only surface a copy must preserve.
        assert (
            hashlib.sha256(AudioSegment.from_file(restored).raw_data).hexdigest()
            == hashlib.sha256(AudioSegment.from_file(keeper).raw_data).hexdigest()
        )
        assert restored.with_name(".song_128.tmp.flac").exists() is False
        fields = read_editable_tags(str(restored))
        assert fields == expected_fields
        assert read_lyrics_tags(str(restored)).plain == expected_lyrics
        assert stub.exists(), "the stub must survive a successful restore"

    def test_an_uppercase_ref_is_resolved(self, tmp_path: Path, keeper: Path) -> None:
        stub = tmp_path / "upper.asx"
        stub.write_text(
            f'<ASX Version="3.0"><ENTRY><REF HREF="{keeper.resolve()}"/></ENTRY></ASX>',
            encoding="utf-8",
        )

        result = process_asx_file(stub, tmp_path)

        assert result["success"] is True
        assert result["audio_path"] == keeper.resolve()

    def test_a_plain_asx_is_still_plain(self, tmp_path: Path, keeper: Path) -> None:
        stub = tmp_path / "plain.asx"
        stub.write_text(
            f'<ASX><ENTRY><REF HREF="{keeper.resolve()}"/></ENTRY></ASX>',
            encoding="utf-8",
        )

        result = process_asx_file(stub, tmp_path)

        assert result["success"] is True
        assert result["stub"] is None

    def test_a_tag_write_failure_leaves_no_final_file_and_keeps_the_stub(
        self, tmp_path: Path, keeper: Path, duplicate: Path, monkeypatch
    ) -> None:
        stub = _stub(tmp_path, keeper, duplicate)
        parsed = process_asx_file(stub, tmp_path)

        def _fail(*_args, **_kwargs):
            raise RuntimeError("tag writer failed")

        monkeypatch.setattr(file_ops, "apply_tags", _fail)

        ok, reason = recreate_from_stub(
            parsed["asx_path"], parsed["audio_path"], parsed["stub"]
        )

        assert ok is False
        assert "tag writer failed" in reason
        assert not (tmp_path / "song_128.flac").exists()
        assert not (tmp_path / ".song_128.tmp.flac").exists()
        assert stub.exists()

    def test_a_missing_keeper_is_reported_and_keeps_the_stub(
        self, tmp_path: Path
    ) -> None:
        missing = tmp_path / "gone.flac"
        metadata = StubMetadata(
            original_name="song_128.mp3",
            keeper_name="gone.flac",
            keeper_path=str(missing),
            reference=missing.name,
        )
        stub = tmp_path / "song_128.asx"
        write_stub(stub, metadata)

        result = process_asx_file(stub, tmp_path)

        assert result["success"] is False
        assert result["reason"] == "FILE NOT FOUND"
        assert stub.exists()
        assert not (tmp_path / "song_128.flac").exists()

    def test_an_unknown_stub_version_is_refused(
        self, tmp_path: Path, keeper: Path
    ) -> None:
        stub = tmp_path / "future.asx"
        data = build_stub(
            StubMetadata(
                original_name="x.mp3",
                keeper_name=keeper.name,
                reference=keeper.name,
                keeper_path=str(keeper),
            )
        )
        stub.write_bytes(data.replace(b'VALUE="1"', b'VALUE="99"', 1))

        result = process_asx_file(stub, tmp_path)

        assert result["success"] is False
        assert result["reason"].startswith("STUB ERROR:")
        assert "99" in result["reason"]


class TestRecursiveDiscovery:
    """The default stays top-level; recursion is an explicit choice."""

    def test_the_default_ignores_subfolders(self, tmp_path: Path) -> None:
        nested = tmp_path / "album"
        nested.mkdir()
        (nested / "a.asx").write_text("<ASX/>", encoding="utf-8")

        from asx_extractor.cli import _discover_asx_files

        assert _discover_asx_files(tmp_path, False) == []

    def test_recursive_finds_the_nested_playlist(self, tmp_path: Path) -> None:
        nested = tmp_path / "album"
        nested.mkdir()
        playlist = nested / "a.asx"
        playlist.write_text("<ASX/>", encoding="utf-8")

        from asx_extractor.cli import _discover_asx_files

        assert _discover_asx_files(tmp_path, True) == [playlist]

"""Tests for the exact-duplicate hashes and grouping (F-E9).

Every claim here is measured on real encoded audio: the "same PCM" question is
only worth asking if a tag rewrite really leaves the decoded samples alone and a
bitrate change really does not, and a fake hash cannot show either.

Changed in 2.6.0: new module (F-E9).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from audio_suite_shared.tag_helper_writer import write_editable_tag
from duplicate_finder.core.exact import (
    KIND_BYTES,
    KIND_PCM,
    attach_hashes,
    build_exact_groups,
    file_sha256,
    pcm_sha256,
)
from duplicate_finder.core.fingerprinting import build_properties_record
from duplicate_finder.core.models import FingerprintRecord


def _hashed(path: Path) -> FingerprintRecord:
    """Return *path*'s measured record with both digests filled in.

    Args:
        path: File to describe and hash.

    Returns:
        The complete record.
    """
    stat = path.stat()
    return attach_hashes(
        build_properties_record(str(path), stat.st_mtime, stat.st_size)
    )


class TestFileHash:
    """The byte question: a copy is a copy, a changed byte is not."""

    def test_a_byte_identical_copy_hashes_the_same(self, library: Path) -> None:
        original = library / "song_128.mp3"
        copy = library / "renamed.mp3"
        shutil.copy2(original, copy)

        assert file_sha256(str(original)) == file_sha256(str(copy))

    def test_one_changed_byte_changes_the_digest(self, library: Path) -> None:
        original = library / "song_128.mp3"
        edited = library / "edited.mp3"
        data = original.read_bytes()
        edited.write_bytes(data[:-1] + bytes([data[-1] ^ 0xFF]))

        assert file_sha256(str(original)) != file_sha256(str(edited))


class TestPcmHash:
    """The decoded-samples question: metadata is not audio."""

    def test_a_tag_edit_keeps_the_pcm_digest_and_changes_the_bytes(
        self, library: Path
    ) -> None:
        original = library / "song_128.mp3"
        tagged = library / "tagged.mp3"
        shutil.copy2(original, tagged)
        write_editable_tag(str(tagged), "title", "A different title")

        assert file_sha256(str(original)) != file_sha256(str(tagged))
        assert pcm_sha256(str(original)) == pcm_sha256(str(tagged))

    def test_a_different_bitrate_is_not_the_same_pcm(self, library: Path) -> None:
        assert pcm_sha256(str(library / "song_96.mp3")) != pcm_sha256(
            str(library / "song_320.mp3")
        )


class TestAttachHashes:
    """A record is hashed once, and a complete record is left alone."""

    def test_a_record_gains_both_digests(self, library: Path) -> None:
        record = _hashed(library / "song.flac")

        assert len(record.file_sha256) == 64
        assert len(record.pcm_sha256) == 64

    def test_a_complete_record_is_returned_unchanged(self, library: Path) -> None:
        complete = _hashed(library / "song.flac")

        assert attach_hashes(complete) is complete


class TestGrouping:
    """Which files join, under which claim, and who is kept."""

    def test_renamed_copies_form_a_byte_identical_group(self, library: Path) -> None:
        original = library / "song.flac"
        copy = library / "song copy.flac"
        shutil.copy2(original, copy)

        groups = build_exact_groups([_hashed(original), _hashed(copy)])

        assert len(groups) == 1
        group = groups[0]
        assert group.kind == KIND_BYTES
        assert len(group.duplicates) == 1
        assert group.keeper.path.endswith(
            "song copy.flac"
        ) or group.keeper.path.endswith("song.flac")
        assert group.worst_distance == 0.0

    def test_a_tag_edit_groups_by_pcm_not_by_bytes(self, library: Path) -> None:
        original = library / "song.flac"
        tagged = library / "tagged.flac"
        shutil.copy2(original, tagged)
        write_editable_tag(str(tagged), "title", "A different title")

        groups = build_exact_groups([_hashed(original), _hashed(tagged)])

        assert len(groups) == 1
        assert groups[0].kind == KIND_PCM
        # The digest that decides the kind is the byte one, and it differs.
        assert file_sha256(str(original)) != file_sha256(str(tagged))

    def test_different_masters_do_not_group(self, library: Path) -> None:
        assert (
            build_exact_groups(
                [_hashed(library / "song_128.mp3"), _hashed(library / "take2.mp3")]
            )
            == []
        )

    def test_the_lossless_copy_is_the_keeper(self, library: Path) -> None:
        lossy = library / "song_96 copy.mp3"
        shutil.copy2(library / "song_96.mp3", lossy)

        groups = build_exact_groups([_hashed(library / "song_96.mp3"), _hashed(lossy)])

        (group,) = groups
        assert group.keeper.path.endswith("song_96 copy.mp3")

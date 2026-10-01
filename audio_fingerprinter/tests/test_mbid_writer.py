"""Tests for audio_fingerprinter.core.mbid_writer.

E2's selection policy: ``MUSICBRAINZ_TRACKID`` and ``MUSICBRAINZ_ARTISTID``
come straight from the AcoustID response; ``MUSICBRAINZ_ALBUMID`` is written
only when exactly one release candidate survives the agreed criteria
(D2-am1). These tests pin each criterion and the never-guess guarantee.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from audio_fingerprinter.core.mbid_writer import (
    ALBUMID_TAG,
    ARTISTID_TAG,
    TRACKID_TAG,
    select_mbid_tags,
    write_mbid_tags,
)
from audio_fingerprinter.core.models import AcoustidRecording, Release

TRACK_ID = "cd2e7c47-16f5-46c6-a37c-a1eb7bf599ff"
ARTIST_ID = "6d7b7cd4-254b-4c25-83f6-dd20f98ceacd"
ALBUM_TITLE = "Before the Dawn Heals Us"


@pytest.fixture
def album_dir() -> Generator[Path, None, None]:
    """Yield a temp folder, cleaned up after the test."""
    d = Path(tempfile.mkdtemp(prefix="mbid_sel_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _release(
    release_id: str,
    *,
    title: str = "",
    track_count: int | None = None,
    medium_count: int | None = None,
    countries: tuple[str, ...] = (),
    year: int | None = None,
    group_id: str = "g-1",
    group_title: str = ALBUM_TITLE,
    group_type: str = "Album",
) -> Release:
    return Release(
        release_id=release_id,
        title=title,
        track_count=track_count,
        medium_count=medium_count,
        countries=countries,
        year=year,
        release_group_id=group_id,
        release_group_title=group_title,
        release_group_type=group_type,
    )


def _recording(
    *releases: Release,
    artist_ids: tuple[str, ...] = (ARTIST_ID,),
) -> AcoustidRecording:
    return AcoustidRecording(
        acoustid_id="ac-1",
        recording_id=TRACK_ID,
        title="Lower Your Eyelids to Die With the Sun",
        artist="M83",
        artist_ids=artist_ids,
        releases=releases,
    )


def _export_mp3(path: Path) -> None:
    AudioSegment.silent(duration=50).export(str(path), format="mp3")


class TestTrackAndArtistIds:
    def test_trackid_and_artistid_from_response(self) -> None:
        tags = select_mbid_tags(_recording(_release("rel-1")))
        assert tags[TRACKID_TAG] == TRACK_ID
        assert tags[ARTISTID_TAG] == ARTIST_ID

    def test_artistid_omitted_when_service_reported_none(self) -> None:
        tags = select_mbid_tags(_recording(_release("rel-1"), artist_ids=()))
        assert TRACKID_TAG in tags
        assert ARTISTID_TAG not in tags

    def test_artistid_uses_first_credited_artist(self) -> None:
        tags = select_mbid_tags(
            _recording(_release("rel-1"), artist_ids=("a-1", "a-2"))
        )
        assert tags[ARTISTID_TAG] == "a-1"


class TestAlbumIdSelection:
    """D2-am1 criteria — an id only when exactly one candidate survives."""

    def test_tied_candidates_omit_albumid(self) -> None:
        # The real M83 case: nine 15-track editions differing only by
        # country/date. With no discriminating signal, none is written.
        tags = select_mbid_tags(
            _recording(
                _release("rel-fr", track_count=15, countries=("FR",), year=2005),
                _release("rel-us", track_count=15, countries=("US",), year=2005),
            ),
            album_title=ALBUM_TITLE,
        )
        assert ALBUMID_TAG not in tags

    def test_album_title_narrows_to_matching_group(self, album_dir: Path) -> None:
        tags = select_mbid_tags(
            _recording(
                _release(
                    "rel-album",
                    group_id="g-1",
                    group_title="Before the Dawn Heals Us",
                ),
                _release(
                    "rel-cafe",
                    group_id="g-2",
                    group_title="Café del Mar, Volumen Veinte",
                ),
            ),
            album_title="before the dawn heals us",
        )
        assert tags[ALBUMID_TAG] == "rel-album"

    def test_title_match_survives_curly_apostrophe(self) -> None:
        tags = select_mbid_tags(
            _recording(
                _release(
                    "rel-dont",
                    group_id="g-1",
                    group_title="Don\u2019t Stop",
                ),
                _release(
                    "rel-other",
                    group_id="g-2",
                    group_title="Other Album",
                ),
            ),
            album_title="Don't Stop",
        )
        assert tags[ALBUMID_TAG] == "rel-dont"

    def test_track_count_narrows_by_sibling_folder(self, album_dir: Path) -> None:
        # 17 local tracks: only the 17-track JP edition can match.
        for i in range(17):
            (album_dir / f"t{i:02}.mp3").write_bytes(b"\x00" * 8)
        tags = select_mbid_tags(
            _recording(
                _release("rel-15", track_count=15),
                _release("rel-17", track_count=17),
            ),
            album_title=ALBUM_TITLE,
            file_path=str(album_dir / "t00.mp3"),
        )
        assert tags[ALBUMID_TAG] == "rel-17"

    def test_disc_count_narrows_by_tagged_discs(self, album_dir: Path) -> None:
        # A 2-disc folder isolates the 2014 US 2x15 edition from two 1x15s.
        import mutagen

        for name, disc in (("d1t0.mp3", "1"), ("d2t0.mp3", "2")):
            path = album_dir / name
            _export_mp3(path)
            audio = mutagen.File(str(path))
            from mutagen.id3 import TPOS

            audio.tags.add(TPOS(encoding=3, text=[disc]))
            audio.save()
        tags = select_mbid_tags(
            _recording(
                _release("rel-1x15", track_count=15, medium_count=1),
                _release("rel-2x15", track_count=15, medium_count=2),
            ),
            album_title=ALBUM_TITLE,
            file_path=str(album_dir / "d1t0.mp3"),
        )
        assert tags[ALBUMID_TAG] == "rel-2x15"

    def test_release_group_type_preferred(self, album_dir: Path) -> None:
        # Same title and counts: the full-length edition wins over the Single.
        tags = select_mbid_tags(
            _recording(
                _release(
                    "rel-single",
                    group_id="g-2",
                    group_title=ALBUM_TITLE,
                    group_type="Single",
                ),
                _release("rel-album", group_type="Album"),
            ),
            album_title=ALBUM_TITLE,
        )
        assert tags[ALBUMID_TAG] == "rel-album"

    def test_region_preference_breaks_country_tie(self) -> None:
        # Nine 15-track editions collapse to the user's region when only
        # the country differs.
        tags = select_mbid_tags(
            _recording(
                _release("rel-fr", track_count=15, countries=("FR",)),
                _release("rel-us", track_count=15, countries=("US",)),
            ),
            album_title=ALBUM_TITLE,
            region="US",
        )
        assert tags[ALBUMID_TAG] == "rel-us"

    def test_region_matching_no_candidate_is_not_decisive(self) -> None:
        tags = select_mbid_tags(
            _recording(
                _release("rel-fr", countries=("FR",)),
                _release("rel-us", countries=("US",)),
            ),
            album_title=ALBUM_TITLE,
            region="JP",
        )
        assert ALBUMID_TAG not in tags

    def test_existing_albumid_is_decisive(self, album_dir: Path) -> None:
        # A file already carrying a valid ALBUMID keeps it, even though the
        # album title alone would have been ambiguous.
        from audio_suite_shared.tag_helper_writer import write_musicbrainz_ids

        path = album_dir / "keep.mp3"
        _export_mp3(path)
        write_musicbrainz_ids(str(path), {ALBUMID_TAG: "rel-existing"})
        tags = select_mbid_tags(
            _recording(
                _release("rel-existing"),
                _release("rel-other"),
            ),
            album_title=ALBUM_TITLE,
            file_path=str(path),
        )
        assert tags[ALBUMID_TAG] == "rel-existing"

    def test_no_release_metadata_omits_albumid(self) -> None:
        tags = select_mbid_tags(_recording())
        assert TRACKID_TAG in tags
        assert ALBUMID_TAG not in tags

    def test_criterion_that_empties_the_set_is_ignored(self) -> None:
        # A wrong local album title must not suppress an otherwise
        # unambiguous single candidate.
        tags = select_mbid_tags(
            _recording(_release("rel-only")),
            album_title="Some Unrelated Title",
        )
        assert tags[ALBUMID_TAG] == "rel-only"


class TestWriteMbidTags:
    def test_empty_tags_write_nothing(self) -> None:
        with patch(
            "audio_fingerprinter.core.mbid_writer._write_musicbrainz_ids"
        ) as writer:
            ok, msg = write_mbid_tags("x.mp3", {})
        assert ok is True
        assert "No MusicBrainz identifiers" in msg
        writer.assert_not_called()

    def test_success_names_written_fields(self) -> None:
        tags = {TRACKID_TAG: TRACK_ID, ALBUMID_TAG: "rel-1"}
        with patch(
            "audio_fingerprinter.core.mbid_writer._write_musicbrainz_ids"
        ) as writer:
            ok, msg = write_mbid_tags("x.mp3", tags)
        assert ok is True
        writer.assert_called_once_with("x.mp3", tags)
        assert ALBUMID_TAG in msg
        assert TRACKID_TAG in msg

    def test_failure_returns_false_with_message(self) -> None:
        from audio_suite_shared.exceptions import AudioTagError

        with patch(
            "audio_fingerprinter.core.mbid_writer._write_musicbrainz_ids",
            side_effect=AudioTagError("cannot open"),
        ):
            ok, msg = write_mbid_tags("x.mp3", {TRACKID_TAG: TRACK_ID})
        assert ok is False
        assert "cannot open" in msg

    def test_mapped_base_error_keeps_tuple_contract(self) -> None:
        # Regression: the shared layer does not always produce the
        # AudioTagError subclass; a mapped base error used to escape the
        # narrow catch, get swallowed into None by the decorator, and crash
        # every caller that unpacks the declared (ok, message) tuple.
        from audio_suite_shared.exceptions import AudioSuiteError

        with patch(
            "audio_fingerprinter.core.mbid_writer._write_musicbrainz_ids",
            side_effect=AudioSuiteError("mapped base error"),
        ):
            ok, msg = write_mbid_tags("x.mp3", {TRACKID_TAG: TRACK_ID})
        assert ok is False
        assert "mapped base error" in msg.lower()


class TestSelectMbidTagsContract:
    def test_returned_tags_are_str_values(self) -> None:
        tags = select_mbid_tags(_recording(_release("rel-1")))
        assert all(isinstance(value, str) for value in tags.values())

    def test_mock_target_uses_importing_module_binding(self) -> None:
        # write_mbid_tags imports the shared writer at module level, so the
        # sanctioned patch target is this module's binding, not the source
        # module (AGENTS.md mock-patch rule).
        probe = MagicMock()
        with patch(
            "audio_fingerprinter.core.mbid_writer._write_musicbrainz_ids",
            probe,
        ):
            write_mbid_tags("x.mp3", {TRACKID_TAG: TRACK_ID})
        probe.assert_called_once()

"""Tests for audio_fingerprinter.core.models."""

from audio_fingerprinter.core.models import (
    AcoustidRecording,
    Fingerprint,
    FingerprintFileResult,
    FingerprintParams,
    FingerprintStatus,
    LookupResult,
    Release,
    ReleaseGroup,
    status_text,
)


class TestFingerprintStatus:
    """The status vocabulary every producer and display site shares."""

    def test_covers_every_emitted_status(self):
        # Non-vacuity: the enum is the closed vocabulary of per-file
        # outcomes, so a dropped member silently mislabels a file.
        assert len(FingerprintStatus) == 8
        assert {member.value for member in FingerprintStatus} == {
            "ERROR",
            "LOOKUP SKIPPED",
            "ANALYSED",
            "NO MATCH",
            "MATCHED",
            "TAGGED",
            "TAG WRITE FAILED",
            "ALBUM AMBIGUOUS",
        }

    def test_member_compares_equal_to_its_display_string(self):
        for member in FingerprintStatus:
            assert member == member.value

    def test_display_string_is_never_the_enum_repr(self):
        # The footgun status_text() exists for: a str-mixin enum's __str__
        # is "FingerprintStatus.MATCHED", which would reach the UI/log.
        assert str(FingerprintStatus.MATCHED) != "MATCHED"
        for member in FingerprintStatus:
            assert status_text(member) == member.value

    def test_status_text_accepts_a_plain_string(self):
        assert status_text("MATCHED") == "MATCHED"

    def test_to_dict_serialises_the_plain_display_string(self):
        result = FingerprintFileResult(
            file_path="/x/a.mp3",
            filename="a.mp3",
            status=FingerprintStatus.TAG_WRITE_FAILED,
        )
        payload = result.to_dict()
        assert payload["status"] == "TAG WRITE FAILED"
        assert type(payload["status"]) is str


class TestFingerprint:
    def test_construction(self):
        fp = Fingerprint(duration=60.0, fingerprint="abc")
        assert fp.duration == 60.0
        assert fp.fingerprint == "abc"

    def test_to_dict(self):
        fp = Fingerprint(duration=120.0, fingerprint="xyz")
        d = fp.to_dict()
        assert d == {"duration": 120.0, "fingerprint": "xyz"}


class TestAcoustidRecording:
    def test_to_dict_includes_all_fields(self):
        rec = AcoustidRecording(
            acoustid_id="a1",
            recording_id="b2",
            title="Song",
            artist="Band",
            score=0.9,
            duration=210,
        )
        d = rec.to_dict()
        assert d["acoustid_id"] == "a1"
        assert d["recording_id"] == "b2"
        assert d["title"] == "Song"
        assert d["score"] == 0.9

    def test_release_groups_default_empty(self):
        rec = AcoustidRecording("a", "b", "Song", score=0.9)
        assert rec.release_groups == ()

    def test_artist_ids_and_releases_default_empty(self):
        rec = AcoustidRecording("a", "b", "Song", score=0.9)
        assert rec.artist_ids == ()
        assert rec.releases == ()

    def test_to_dict_includes_release_groups(self):
        rec = AcoustidRecording(
            acoustid_id="a1",
            recording_id="b2",
            title="Song",
            release_groups=(ReleaseGroup("rg-1", "Album Title"),),
        )
        d = rec.to_dict()
        assert list(d["release_groups"]) == [
            {"release_group_id": "rg-1", "title": "Album Title"}
        ]

    def test_to_dict_includes_artist_ids_and_releases(self):
        rec = AcoustidRecording(
            acoustid_id="a1",
            recording_id="b2",
            title="Song",
            artist_ids=("mb-art",),
            releases=(
                Release(
                    release_id="rel-1",
                    track_count=15,
                    medium_count=1,
                    countries=("FR",),
                    year=2005,
                    release_group_id="rg-1",
                    release_group_title="Album",
                    release_group_type="Album",
                ),
            ),
        )
        d = rec.to_dict()
        assert list(d["artist_ids"]) == ["mb-art"]
        release = d["releases"][0]
        assert release["release_id"] == "rel-1"
        assert release["track_count"] == 15
        assert release["medium_count"] == 1
        assert release["countries"] == ("FR",)
        assert release["year"] == 2005
        assert release["release_group_title"] == "Album"


class TestReleaseGroup:
    def test_construction_and_to_dict(self):
        group = ReleaseGroup(release_group_id="rg-1", title="Album")
        assert group.release_group_id == "rg-1"
        assert group.title == "Album"
        assert group.to_dict() == {"release_group_id": "rg-1", "title": "Album"}

    def test_title_defaults_empty(self):
        assert ReleaseGroup("rg-2").title == ""


class TestRelease:
    """E2's release candidate — one of the many releases a recording spans."""

    def test_defaults(self):
        release = Release("rel-1")
        assert release.release_id == "rel-1"
        assert release.title == ""
        assert release.track_count is None
        assert release.medium_count is None
        assert release.countries == ()
        assert release.year is None
        assert release.release_group_id == ""
        assert release.release_group_title == ""
        assert release.release_group_type == ""

    def test_to_dict(self):
        release = Release(
            "rel-1",
            track_count=15,
            medium_count=2,
            countries=("US", "AU"),
            year=2014,
            release_group_type="Album",
        )
        d = release.to_dict()
        assert d["release_id"] == "rel-1"
        assert d["track_count"] == 15
        assert d["medium_count"] == 2
        assert d["countries"] == ("US", "AU")
        assert d["year"] == 2014
        assert d["release_group_type"] == "Album"


class TestLookupResult:
    def test_best_match_returns_first(self):
        rec = AcoustidRecording("a", "b", "Song", score=0.9)
        result = LookupResult(status="ok", recordings=(rec,))
        assert result.best_match is rec

    def test_best_match_empty_returns_none(self):
        result = LookupResult(status="no results", recordings=())
        assert result.best_match is None

    def test_to_dict(self):
        rec = AcoustidRecording("a", "b", "Song", score=0.9)
        result = LookupResult(status="ok", recordings=(rec,))
        d = result.to_dict()
        assert d["status"] == "ok"
        assert len(d["recordings"]) == 1
        assert d["recordings"][0]["acoustid_id"] == "a"


class TestFingerprintParams:
    def test_defaults(self):
        p = FingerprintParams()
        assert p.lookup_enabled is True
        assert p.write_tags is False
        assert p.is_dry_run is True
        assert p.threshold == 0.5
        assert p.max_length == 120
        assert p.fpcalc_path == ""
        assert p.requests_per_second == 1.0
        assert p.album_mode is False
        assert p.album_min == 3
        assert p.write_mbids is False
        assert p.mbid_region == ""

    def test_to_dict_roundtrip(self):
        p = FingerprintParams(threshold=0.7, max_length=180)
        d = p.to_dict()
        assert d["threshold"] == 0.7
        assert d["max_length"] == 180
        assert d["album_mode"] is False
        assert d["album_min"] == 3
        assert d["write_mbids"] is False
        assert d["mbid_region"] == ""

    def test_mbid_preferences_roundtrip(self):
        p = FingerprintParams(write_mbids=True, mbid_region="GB")
        d = p.to_dict()
        assert d["write_mbids"] is True
        assert d["mbid_region"] == "GB"


class TestFingerprintFileResult:
    def test_defaults(self):
        r = FingerprintFileResult(
            file_path="/x/a.mp3", filename="a.mp3", status="NO MATCH"
        )
        assert r.tag_written is False
        assert r.acoustid_id == ""
        assert r.fingerprint == ""

    def test_to_dict(self):
        r = FingerprintFileResult(
            file_path="/x/a.mp3",
            filename="a.mp3",
            status="MATCHED",
            message="Song — Artist",
            acoustid_id="abc123",
        )
        d = r.to_dict()
        assert d["status"] == "MATCHED"
        assert d["acoustid_id"] == "abc123"
        assert isinstance(d["recordings"], list)

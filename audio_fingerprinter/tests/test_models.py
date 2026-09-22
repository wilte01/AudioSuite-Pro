"""Tests for audio_fingerprinter.core.models."""

from audio_fingerprinter.core.models import (
    AcoustidRecording,
    Fingerprint,
    FingerprintFileResult,
    FingerprintParams,
    LookupResult,
)


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

    def test_to_dict_roundtrip(self):
        p = FingerprintParams(threshold=0.7, max_length=180)
        d = p.to_dict()
        assert d["threshold"] == 0.7
        assert d["max_length"] == 180


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

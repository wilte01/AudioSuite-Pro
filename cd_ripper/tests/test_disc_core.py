"""
Tests for cd_ripper.core.disc (G-39)

Coverage strategy
-----------------
- DiscInfo dataclass: construction and defaults.
- _apply_release / apply_release: pure metadata mapping — no I/O.
- _mb_lookup: mock musicbrainzngs at the module level.
- read_disc: mock both discid and mbz; test all four code paths
  (discid present, discid absent + ffprobe data, discid absent + empty ffprobe,
  discid error).
- list_cd_drives: exercise the non-Windows branch directly; Windows branch
  mocked via ctypes.windll.
- format_duration: pure function, parameterised.
- _ffprobe_tracks: mock run_secure_subprocess.

Hardware-dependent:
- Real discid.read() and MusicBrainz HTTP → ``@pytest.mark.hardware``
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub audio_suite_shared.secure_subprocess before importing disc.py
# ---------------------------------------------------------------------------
_secure_sub_stub = MagicMock()
_secure_sub_stub.SubprocessSecurityError = type(
    "SubprocessSecurityError", (Exception,), {}
)
_secure_sub_stub.run_secure_subprocess = MagicMock()
sys.modules.setdefault("audio_suite_shared", MagicMock())
sys.modules.setdefault("audio_suite_shared.secure_subprocess", _secure_sub_stub)

# ---------------------------------------------------------------------------
# Stub optional dependencies before importing disc.py
# ---------------------------------------------------------------------------

# discid stub
_discid_stub = MagicMock()
_discid_stub.read = MagicMock()
sys.modules.setdefault("discid", _discid_stub)

# musicbrainzngs stub
_mbz_stub = MagicMock()
_mbz_stub.set_useragent = MagicMock()
_mbz_stub.get_releases_by_discid = MagicMock(
    return_value={"disc": {"release-list": []}}
)
_mbz_stub.search_releases = MagicMock(return_value={"release-list": []})
sys.modules.setdefault("musicbrainzngs", _mbz_stub)

from cd_ripper.core.disc import (  # noqa: E402
    DiscInfo,
    _apply_release,
    _ffprobe_tracks,  # noqa: E402
    _mb_lookup,
    apply_release,
    format_duration,
    list_cd_drives,
    read_disc,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _make_release(
    title="Test Album",
    date="2020-06-15",
    album_artist="Test Artist",
    tracks=None,
):
    """Build a minimal MusicBrainz release dict."""
    tracks = tracks or [
        {
            "position": 1,
            "recording": {
                "title": "Track One",
                "artist-credit": [{"artist": {"name": "Solo"}}],
                "length": 200000,  # ms
            },
        },
        {
            "position": 2,
            "recording": {
                "title": "Track Two",
                "artist-credit": [],
                "length": 180000,
            },
        },
    ]
    return {
        "title": title,
        "date": date,
        "artist-credit": [{"artist": {"name": album_artist}}],
        "medium-list": [{"track-list": tracks}],
    }


def _make_disc_info(num_tracks=2, disc_id="abc123"):
    info = DiscInfo()
    info.disc_id = disc_id
    info.tracks = [
        {
            "number": i + 1,
            "title": f"Track {i + 1:02d}",
            "artist": "",
            "album": "",
            "year": "",
            "genre": "",
            "duration": 0.0,
        }
        for i in range(num_tracks)
    ]
    return info


# ===========================================================================
# DiscInfo
# ===========================================================================


class TestDiscInfo:
    def test_default_construction(self):
        info = DiscInfo()
        assert info.drive == ""
        assert info.disc_id is None
        assert info.tracks == []
        assert info.release_info is None
        assert info.mb_releases == []
        assert info.error is None

    def test_attributes_are_mutable(self):
        info = DiscInfo()
        info.drive = "D:"
        info.disc_id = "xyz"
        info.tracks = [{"number": 1}]
        assert info.drive == "D:"
        assert info.disc_id == "xyz"
        assert len(info.tracks) == 1


# ===========================================================================
# format_duration
# ===========================================================================


class TestFormatDuration:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, "--:--"),
            (-1, "--:--"),
            (60, "1:00"),
            (61, "1:01"),
            (3599, "59:59"),
            (3600, "60:00"),
            (90, "1:30"),
            (5, "0:05"),
        ],
    )
    def test_format(self, seconds, expected):
        assert format_duration(seconds) == expected

    def test_float_input(self):
        assert format_duration(90.9) == "1:30"

    def test_large_value(self):
        result = format_duration(7200)
        assert result == "120:00"


# ===========================================================================
# _apply_release / apply_release
# ===========================================================================


class TestApplyRelease:
    def test_album_title_set_on_all_tracks(self):
        info = _make_disc_info(num_tracks=2)
        release = _make_release(title="Great Album")
        _apply_release(info, release)
        assert all(t["album"] == "Great Album" for t in info.tracks)

    def test_year_extracted_from_date(self):
        info = _make_disc_info(num_tracks=2)
        release = _make_release(date="2023-03-01")
        _apply_release(info, release)
        assert all(t["year"] == "2023" for t in info.tracks)

    def test_short_date_string(self):
        info = _make_disc_info(num_tracks=1)
        release = _make_release(date="1999")
        _apply_release(info, release)
        assert info.tracks[0]["year"] == "1999"

    def test_track_titles_applied(self):
        info = _make_disc_info(num_tracks=2)
        release = _make_release()
        _apply_release(info, release)
        assert info.tracks[0]["title"] == "Track One"
        assert info.tracks[1]["title"] == "Track Two"

    def test_track_artist_set_from_recording(self):
        info = _make_disc_info(num_tracks=2)
        release = _make_release()
        _apply_release(info, release)
        assert info.tracks[0]["artist"] == "Solo"

    def test_track_artist_falls_back_to_album_artist(self):
        info = _make_disc_info(num_tracks=2)
        release = _make_release(album_artist="Album Artist")
        _apply_release(info, release)
        # Track 2 has empty artist-credit → should fall back to album_artist
        assert info.tracks[1]["artist"] == "Album Artist"

    def test_album_artist_stored_on_every_track(self):
        """Regression: album_artist must survive onto each track dict so
        ripper.py can use it for folder naming / tagging. Previously the
        computed album_artist was used only as a per-track fallback and then
        discarded, so compilations (distinct per-track artists) never carried
        the release-level artist forward."""
        info = _make_disc_info(num_tracks=2)
        release = _make_release(album_artist="Various Artists")
        _apply_release(info, release)
        assert info.tracks[0]["album_artist"] == "Various Artists"
        assert info.tracks[1]["album_artist"] == "Various Artists"

    def test_album_artist_distinct_from_per_track_artist_on_compilation(self):
        """Compilation: each track keeps its own artist, but album_artist
        stays the release-level artist on every track regardless."""
        info = _make_disc_info(num_tracks=2)
        release = _make_release(album_artist="Various Artists")
        # Track 1 in the default fixture has its own artist-credit ("Solo")
        _apply_release(info, release)
        assert info.tracks[0]["artist"] == "Solo"
        assert info.tracks[0]["album_artist"] == "Various Artists"

    def test_duration_applied_from_recording_length(self):
        info = _make_disc_info(num_tracks=2)
        release = _make_release()
        _apply_release(info, release)
        # Track 1: length=200000ms → 200.0s
        assert info.tracks[0]["duration"] == pytest.approx(200.0)

    def test_release_info_stored(self):
        info = _make_disc_info(num_tracks=1)
        release = _make_release()
        _apply_release(info, release)
        assert info.release_info is release

    def test_extra_mb_tracks_ignored_gracefully(self):
        """MB release has 3 tracks but disc only has 2 — no crash."""
        info = _make_disc_info(num_tracks=2)
        release = _make_release(
            tracks=[
                {
                    "position": 1,
                    "recording": {"title": "T1", "artist-credit": [], "length": 0},
                },
                {
                    "position": 2,
                    "recording": {"title": "T2", "artist-credit": [], "length": 0},
                },
                {
                    "position": 3,
                    "recording": {"title": "T3", "artist-credit": [], "length": 0},
                },
            ]
        )
        _apply_release(info, release)  # must not raise

    def test_missing_tracks_in_release_leaves_originals(self):
        """MB release has no medium-list at all → original titles preserved."""
        info = _make_disc_info(num_tracks=2)
        info.tracks[0]["title"] = "Original One"
        release = {
            "title": "Album",
            "date": "2020",
            "artist-credit": [{"artist": {"name": "Artist"}}],
            "medium-list": [],  # no mediums → recording_map stays empty
        }
        _apply_release(info, release)
        assert info.tracks[0]["title"] == "Original One"

    def test_apply_release_public_wrapper(self):
        info = _make_disc_info(num_tracks=1)
        release = _make_release(title="Public Wrapper Test")
        apply_release(info, release)
        assert info.tracks[0]["album"] == "Public Wrapper Test"

    def test_artist_credit_string_items_concatenated(self):
        """artist-credit can contain raw strings (joiners) between dict entries."""
        info = _make_disc_info(num_tracks=1)
        release = {
            "title": "Album",
            "date": "2020",
            "artist-credit": [
                {"artist": {"name": "Artist A"}},
                " & ",
                {"artist": {"name": "Artist B"}},
            ],
            "medium-list": [
                {
                    "track-list": [
                        {
                            "position": 1,
                            "recording": {
                                "title": "T",
                                "artist-credit": [],
                                "length": 0,
                            },
                        }
                    ]
                }
            ],
        }
        _apply_release(info, release)
        assert (
            "Artist A" in info.tracks[0]["artist"]
            or info.tracks[0]["artist"] == "Artist A & Artist B"
        )


# ===========================================================================
# _ffprobe_tracks
# ===========================================================================


class TestFfprobeTracks:
    def _ffprobe_stdout(self):
        import json

        return json.dumps(
            {
                "streams": [
                    {"index": 0, "duration": "200.0", "tags": {"title": "Track 01"}},
                    {"index": 1, "duration": "180.0", "tags": {"title": "Track 02"}},
                ]
            }
        )

    def test_parses_valid_ffprobe_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = self._ffprobe_stdout()

        with patch(
            "cd_ripper.core.disc.run_secure_subprocess", return_value=mock_result
        ):
            tracks = _ffprobe_tracks("D:")

        assert len(tracks) == 2
        assert tracks[0]["number"] == 1
        assert tracks[0]["title"] == "Track 01"
        assert tracks[0]["duration"] == pytest.approx(200.0)

    def test_ffprobe_failure_returns_empty_list(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch(
            "cd_ripper.core.disc.run_secure_subprocess", return_value=mock_result
        ):
            tracks = _ffprobe_tracks("D:")

        assert tracks == []

    def test_ffprobe_exception_returns_empty_list(self):
        with patch(
            "cd_ripper.core.disc.run_secure_subprocess",
            side_effect=OSError("timeout"),
        ):
            tracks = _ffprobe_tracks("D:")

        assert tracks == []

    def test_each_track_has_required_keys(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = self._ffprobe_stdout()

        with patch(
            "cd_ripper.core.disc.run_secure_subprocess", return_value=mock_result
        ):
            tracks = _ffprobe_tracks("D:")

        required = {"number", "title", "artist", "album", "year", "genre", "duration"}
        for t in tracks:
            assert required.issubset(t.keys())

    def test_missing_title_tag_uses_fallback(self):
        import json

        stdout = json.dumps({"streams": [{"index": 0, "duration": "100.0"}]})
        mock_result = MagicMock(returncode=0, stdout=stdout)
        with patch(
            "cd_ripper.core.disc.run_secure_subprocess", return_value=mock_result
        ):
            tracks = _ffprobe_tracks("D:")
        assert tracks[0]["title"] == "Track 01"


# ===========================================================================
# _mb_lookup
# ===========================================================================


class TestMbLookup:
    def test_lookup_by_disc_id(self):
        info = _make_disc_info(disc_id="real-disc-id")
        release = _make_release()
        mbz_result = {"disc": {"release-list": [release]}}

        with (
            patch("cd_ripper.core.disc.HAS_MBZ", True),
            patch("cd_ripper.core.disc.mbz") as mock_mbz,
        ):
            mock_mbz.get_releases_by_discid.return_value = mbz_result
            _mb_lookup(info)

        assert info.release_info is not None
        assert info.mb_releases == [release]

    def test_lookup_by_track_count_when_no_disc_id(self):
        info = _make_disc_info(num_tracks=3, disc_id=None)
        release = _make_release()
        mbz_result = {"release-list": [release]}

        with (
            patch("cd_ripper.core.disc.HAS_MBZ", True),
            patch("cd_ripper.core.disc.mbz") as mock_mbz,
        ):
            mock_mbz.search_releases.return_value = mbz_result
            _mb_lookup(info)

        assert info.release_info is not None

    def test_empty_release_list_leaves_release_info_none(self):
        info = _make_disc_info(disc_id="abc")
        with (
            patch("cd_ripper.core.disc.HAS_MBZ", True),
            patch("cd_ripper.core.disc.mbz") as mock_mbz,
        ):
            mock_mbz.get_releases_by_discid.return_value = {
                "disc": {"release-list": []}
            }
            _mb_lookup(info)

        assert info.release_info is None
        assert info.mb_releases == []

    def test_mbz_exception_sets_error(self):
        info = _make_disc_info(disc_id="abc")
        with (
            patch("cd_ripper.core.disc.HAS_MBZ", True),
            patch("cd_ripper.core.disc.mbz") as mock_mbz,
        ):
            mock_mbz.get_releases_by_discid.side_effect = OSError("Network error")
            _mb_lookup(info)

        assert info.error is not None
        assert "MusicBrainz" in info.error


# ===========================================================================
# read_disc — integration of all paths
# ===========================================================================


class TestReadDisc:
    def test_discid_path_populates_tracks(self):
        fake_disc = MagicMock()
        fake_disc.id = "test-disc-id"
        fake_track = MagicMock()
        fake_track.number = 1
        fake_track.seconds = 200
        fake_disc.tracks = [fake_track]

        with (
            patch("cd_ripper.core.disc.HAS_DISCID", True),
            patch("cd_ripper.core.disc.discid") as mock_discid,
            patch("cd_ripper.core.disc.HAS_MBZ", False),
        ):
            mock_discid.read.return_value = fake_disc
            info = read_disc("D:")

        assert info.disc_id == "test-disc-id"
        assert len(info.tracks) == 1
        assert info.tracks[0]["number"] == 1
        assert info.tracks[0]["duration"] == 200

    def test_discid_error_sets_error_field(self):
        with (
            patch("cd_ripper.core.disc.HAS_DISCID", True),
            patch("cd_ripper.core.disc.discid") as mock_discid,
            patch("cd_ripper.core.disc.HAS_MBZ", False),
        ):
            mock_discid.read.side_effect = OSError("No disc")
            info = read_disc("D:")

        assert info.error is not None
        assert "discid error" in info.error

    def test_no_discid_uses_ffprobe_path(self):
        import json

        stdout = json.dumps({"streams": [{"index": 0, "duration": "90.0"}]})
        mock_proc = MagicMock(returncode=0, stdout=stdout)

        with (
            patch("cd_ripper.core.disc.HAS_DISCID", False),
            patch("cd_ripper.core.disc.HAS_MBZ", False),
            patch("cd_ripper.core.disc.run_secure_subprocess", return_value=mock_proc),
        ):
            info = read_disc("D:")

        assert len(info.tracks) == 1
        assert info.disc_id is None

    def test_no_discid_no_ffprobe_creates_placeholder(self):
        mock_proc = MagicMock(returncode=1, stdout="")

        with (
            patch("cd_ripper.core.disc.HAS_DISCID", False),
            patch("cd_ripper.core.disc.HAS_MBZ", False),
            patch("cd_ripper.core.disc.run_secure_subprocess", return_value=mock_proc),
        ):
            info = read_disc("D:")

        assert len(info.tracks) >= 1
        assert info.error is not None

    def test_mbz_lookup_called_when_no_error(self):
        fake_disc = MagicMock()
        fake_disc.id = "disc-123"
        fake_disc.tracks = []

        with (
            patch("cd_ripper.core.disc.HAS_DISCID", True),
            patch("cd_ripper.core.disc.discid") as mock_discid,
            patch("cd_ripper.core.disc.HAS_MBZ", True),
            patch("cd_ripper.core.disc._mb_lookup") as mock_mb,
        ):
            mock_discid.read.return_value = fake_disc
            info = read_disc("D:")

        mock_mb.assert_called_once_with(info)

    def test_mbz_not_called_when_error_present(self):
        with (
            patch("cd_ripper.core.disc.HAS_DISCID", True),
            patch("cd_ripper.core.disc.discid") as mock_discid,
            patch("cd_ripper.core.disc.HAS_MBZ", True),
            patch("cd_ripper.core.disc._mb_lookup") as mock_mb,
        ):
            mock_discid.read.side_effect = OSError("disc read fail")
            read_disc("D:")

        mock_mb.assert_not_called()

    def test_drive_field_set_correctly(self):
        with (
            patch("cd_ripper.core.disc.HAS_DISCID", False),
            patch("cd_ripper.core.disc.HAS_MBZ", False),
            patch(
                "cd_ripper.core.disc.run_secure_subprocess",
                return_value=MagicMock(returncode=1, stdout=""),
            ),
        ):
            info = read_disc("E:")

        assert info.drive == "E:"

    def test_no_discid_with_mbz_lookup_invoked(self):
        """
        When discid is unavailable but MusicBrainz is available, read_disc
        must use ffprobe to get track data and then call _mb_lookup.
        """
        import json

        stdout = json.dumps(
            {
                "streams": [
                    {
                        "index": 0,
                        "duration": "200.0",
                        "tags": {"title": "Track 01"},
                    }
                ]
            }
        )
        mock_proc = MagicMock(returncode=0, stdout=stdout)

        with (
            patch("cd_ripper.core.disc.HAS_DISCID", False),
            patch("cd_ripper.core.disc.HAS_MBZ", True),
            patch("cd_ripper.core.disc.run_secure_subprocess", return_value=mock_proc),
            patch("cd_ripper.core.disc._mb_lookup") as mock_mb,
        ):
            info = read_disc("D:")

        mock_mb.assert_called_once_with(info)
        assert info.disc_id is None
        assert len(info.tracks) == 1

    def test_ffprobe_failure_with_mbz_skips_lookup(self):
        """
        When ffprobe fails (no tracks returned) and MBZ is available,
        _mb_lookup must NOT be called because info.error is set by
        the placeholder track path, blocking the MBZ call.
        """
        mock_proc = MagicMock(returncode=1, stdout="")

        with (
            patch("cd_ripper.core.disc.HAS_DISCID", False),
            patch("cd_ripper.core.disc.HAS_MBZ", True),
            patch("cd_ripper.core.disc.run_secure_subprocess", return_value=mock_proc),
            patch("cd_ripper.core.disc._mb_lookup") as mock_mb,
        ):
            info = read_disc("D:")

        mock_mb.assert_not_called()
        assert info.error is not None


# ===========================================================================
# list_cd_drives — non-Windows path
# ===========================================================================


class TestListCdDrives:
    def test_linux_returns_existing_device_paths(self, tmp_path):
        # Create fake device-like files
        fake_cdrom = tmp_path / "cdrom"
        fake_cdrom.touch()

        with (
            patch("os.name", "posix"),
            patch("os.path.exists", side_effect=lambda p: p == str(fake_cdrom)),
        ):
            # Can't easily control /dev/cdrom path — just ensure it runs
            result = list_cd_drives()
            assert isinstance(result, list)

    def test_linux_fallback_when_no_devices(self):
        # Non-Windows now returns [] rather than a fabricated /dev/cdrom
        # path: ripper.py's SCSI pass-through can't act on it anyway (see
        # _require_windows fail-fast guard), so offering it in the UI
        # just deferred the failure to a more confusing point.
        with patch("os.name", "posix"), patch("os.path.exists", return_value=False):
            result = list_cd_drives()
            assert result == []

    @pytest.mark.hardware
    def test_windows_bitmask_filtering(self):
        """Windows branch: mock GetLogicalDrives and GetDriveTypeW."""
        import ctypes

        if not hasattr(ctypes, "windll"):
            pytest.skip("ctypes.windll not available")

        mock_kernel32 = MagicMock()
        # Bit 3 (index 3) = 'D' drive; GetDriveTypeW returns 5 (CDROM)
        mock_kernel32.GetLogicalDrives.return_value = 0b00001000
        mock_kernel32.GetDriveTypeW.return_value = 5  # DRIVE_CDROM

        with patch("os.name", "nt"), patch("ctypes.windll") as mock_windll:
            mock_windll.kernel32 = mock_kernel32
            result = list_cd_drives()

        assert "D:" in result

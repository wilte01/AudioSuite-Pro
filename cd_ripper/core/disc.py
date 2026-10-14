"""
core/disc.py  –  CD drive detection, TOC reading via FFmpeg, MusicBrainz lookup.

Changed in 1.0.1: fixed discid import guard to catch OSError/FileNotFoundError
when native libdiscid is missing (discid wheel present but DLL absent).

Dependencies (pip install --break-system-packages):
    musicbrainzngs   – MusicBrainz Web Service client
    discid           – reads disc TOC / calculates MusicBrainz disc ID
                       (optional but best)

If discid is unavailable we fall back to a FFmpeg-based TOC read which gives us
track count and durations but no cryptographic disc ID, so MusicBrainz lookup
uses a text search on the first track rather than an exact disc-id query.

Changed in 1.0.1: the optional-``discid`` import guard now also catches
``OSError`` (incl. ``FileNotFoundError``), because the wheel can import while
the native ``libdiscid`` shared library is absent; the guard previously let
that abort the whole ``cd_ripper`` package import. The guarded name is also
pre-declared ``Any`` via an aliased import, because discid 1.4.2 ships
``py.typed`` and a Module-typed ``discid`` could not be rebound to ``None``
under ``mypy --strict`` once the extra is installed.
"""

import logging as _logging
import os
import string
from typing import Any, Optional

from audio_suite_shared.secure_subprocess import (
    SubprocessSecurityError,
    run_secure_subprocess,
)

# ── optional imports ────────────────────────────────────────────────────────────
# `discid` is pre-declared Any rather than left to the import's Module type so
# the except path can keep it bound to None without an assignment error under
# mypy --strict: discid 1.4.2 ships py.typed, so with the cd-ripping extra
# installed (CI run 38552791651's typecheck leg) `import discid` resolves to a
# typed Module and a bare `discid = None` failed "Incompatible types in
# assignment". The aliased import keeps the public name a plain Any-typed
# module attribute that tests can patch while the real module is still loaded.
discid: Any = None
try:
    import discid as _discid

    discid = _discid
    HAS_DISCID = True
    # discid/musicbrainzngs are declared OPTIONAL extras ([project]
    # optional-dependencies "cd-ripping"), installed when that extra is
    # synced; the import guards then cannot run. Every decision point they
    # down-select (HAS_DISCID / HAS_MBZ) is exercised by tests patching those
    # flags (tests/test_disc_core.py), so only the import-time guards and
    # their env-conditional assignments are excluded (plan D2).
    #
    # discid is a pure-Python wrapper around a C library, so `import discid`
    # can succeed (the wheel is installed) while the native lib is absent —
    # the loader then raises OSError (Linux/Win32) or FileNotFoundError (its
    # OSError subclass). The guard must catch both, or a machine without
    # libdiscid crashes the whole `cd_ripper` package import (CI run
    # 38548380226: exit code 4 on every test leg). On that failure the name
    # stays bound to the None pre-declared above, so the module attribute
    # still resolves for tests patching it.
except (ImportError, OSError):  # pragma: no cover
    HAS_DISCID = False

try:
    import musicbrainzngs as mbz

    mbz.set_useragent("AudioSuiteCDRipper", "1.0", "https://github.com/audio-suite")
    HAS_MBZ = True
except ImportError:  # pragma: no cover
    HAS_MBZ = False


# ── Drive enumeration ────────────────────────────────────────────────────────────


def platform_supported() -> bool:
    """Return whether CD ripping is supported on this OS.

    Extraction (core/ripper.py) is Windows-only (SCSI pass-through via
    ctypes.windll). macOS/Linux support is a possible future enhancement,
    not implemented today.
    """
    return os.name == "nt"


def list_cd_drives() -> list[str]:  # noqa: D401
    """Return a list of drive letters that contain an audio CD (Windows).

    Returns an empty list on non-Windows platforms rather than fabricated
    /dev/cdrom-style paths: extraction can't act on them (see
    core/ripper.py's Windows-only SCSI pass-through), so offering them in
    the UI would just defer the failure to a confusing point later.
    """
    if not platform_supported():
        return []

    drives = []
    import ctypes

    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if bitmask & (1 << i):
            drive = f"{letter}:\\"
            dtype = ctypes.windll.kernel32.GetDriveTypeW(drive)
            if dtype == 5:  # DRIVE_CDROM
                drives.append(f"{letter}:")
    return drives


def _ffprobe_tracks(drive: str) -> list[dict[str, Any]]:
    """
    Use ffprobe to read the CD TOC from a drive letter.
    Returns list of {'number': int, 'title': str, 'duration': float}.
    Falls back gracefully if ffprobe isn't on PATH.
    """
    tracks = []
    try:
        result = run_secure_subprocess(
            "ffprobe",
            [
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_entries",
                "stream_tags:format_tags:stream=index,duration",
                f"cdda://{drive}",
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            import json

            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            for s in streams:
                idx = s.get("index", 0)
                dur = float(s.get("duration", 0))
                title = s.get("tags", {}).get("title", f"Track {idx + 1:02d}")
                tracks.append(
                    {
                        "number": idx + 1,
                        "title": title,
                        "duration": dur,
                        "artist": "",
                        "album": "",
                        "year": "",
                        "genre": "",
                    }
                )
    except (SubprocessSecurityError, OSError, ValueError) as _exc:
        _logging.getLogger(__name__).warning(
            "ffprobe TOC read failed: %s", _exc, exc_info=True
        )
    return tracks


# ── Main disc-read function ──────────────────────────────────────────────────────


class DiscInfo:
    """Container returned by read_disc()."""

    def __init__(self) -> None:
        self.drive: str = ""
        self.disc_id: Optional[str] = None
        self.tracks: list[
            dict[str, Any]
        ] = []  # [{number, title, artist, album, year, genre, duration}]
        self.release_info: Optional[dict[str, Any]] = None  # raw MusicBrainz release
        self.mb_releases: list[dict[str, Any]] = []  # multiple candidates if ambiguous
        self.error: Optional[str] = None


def read_disc(drive: str) -> DiscInfo:
    """
    Read the TOC from *drive* and attempt a MusicBrainz lookup.
    Blocking – call from a worker thread.
    """
    info = DiscInfo()
    info.drive = drive

    # 1. Try libdiscid (most accurate)
    if HAS_DISCID:
        try:
            disc = discid.read(drive)
            info.disc_id = disc.id
            info.tracks = [
                {
                    "number": t.number,
                    "title": f"Track {t.number:02d}",
                    "artist": "",
                    "album": "",
                    "year": "",
                    "genre": "",
                    "duration": t.seconds,
                }
                for t in disc.tracks
            ]
        except (OSError, ValueError, RuntimeError) as e:
            _logging.getLogger(__name__).error(
                "discid read failed: %s", e, exc_info=True
            )
            info.error = f"discid error: {e}"
    else:
        # Fallback: ffprobe
        info.tracks = _ffprobe_tracks(drive)
        if not info.tracks:
            # Last resort: build placeholder tracks (user can edit metadata manually)
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
                for i in range(1)
            ]
            info.error = (
                "Could not read disc TOC automatically. Please check drive and disc."
            )

    # 2. MusicBrainz lookup
    if HAS_MBZ and not info.error:
        _mb_lookup(info)

    return info


def _mb_lookup(info: DiscInfo) -> None:
    """Populate info.mb_releases and info.release_info via MusicBrainz."""
    try:
        if info.disc_id:
            result = mbz.get_releases_by_discid(
                info.disc_id, includes=["artists", "recordings", "release-groups"]
            )
            releases = result.get("disc", {}).get("release-list", [])
        else:
            # Fallback: search by track count
            result = mbz.search_releases(tracks=len(info.tracks), limit=5)
            releases = result.get("release-list", [])

        info.mb_releases = releases

        if releases:
            _apply_release(info, releases[0])

    except (OSError, KeyError, ValueError) as e:
        _logging.getLogger(__name__).error(
            "MusicBrainz lookup failed: %s", e, exc_info=True
        )
        # Non-fatal – user can fill in metadata manually
        info.error = f"MusicBrainz lookup failed: {e}"


def apply_release(info: DiscInfo, release: dict[str, Any]) -> None:
    """Public wrapper so the UI can swap to a different release candidate."""
    _apply_release(info, release)


def _apply_release(info: DiscInfo, release: dict[str, Any]) -> None:
    """Copy MusicBrainz release data into info.tracks."""
    info.release_info = release

    album = release.get("title", "")
    year = release.get("date", "")[:4]
    artist_credit = release.get("artist-credit", [])
    album_artist = "".join(
        a.get("artist", {}).get("name", "") if isinstance(a, dict) else a
        for a in artist_credit
    )

    medium_list = release.get("medium-list", [])
    recording_map: dict[int, dict[str, Any]] = {}
    for medium in medium_list:
        for track in medium.get("track-list", []):
            pos = int(track.get("position", 0))
            rec = track.get("recording", {})
            recording_map[pos] = {
                "title": rec.get("title", track.get("title", f"Track {pos:02d}")),
                "artist": "".join(
                    a.get("artist", {}).get("name", "") if isinstance(a, dict) else a
                    for a in rec.get("artist-credit", artist_credit)
                )
                or album_artist,
                "duration": int(rec.get("length", 0)) / 1000.0,
            }

    for t in info.tracks:
        num = t["number"]
        rec = recording_map.get(num, {})
        t["title"] = rec.get("title", t["title"])
        t["artist"] = rec.get("artist", album_artist)
        t["album_artist"] = album_artist
        t["album"] = album
        t["year"] = year
        if rec.get("duration"):
            t["duration"] = rec["duration"]


def format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"

"""Immutable data models for the Audio Fingerprinter tool.

Records are frozen dataclasses carrying only the fields the UI and CLI need.
Every record exposes ``to_dict()`` so JSON output (CLI ``--json``) and logs
share one serialisation path.
"""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Fingerprint:
    """A Chromaprint fingerprint produced by ``fpcalc``.

    Attributes:
        duration: DURATION from fpcalc — full file duration, not the
            analysed window length.
        fingerprint: The raw Chromaprint string (``FINGERPRINT=`` value).
    """

    duration: float
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReleaseGroup:
    """A MusicBrainz release group a recording candidate appears on.

    Attributes:
        release_group_id: MusicBrainz release-group MBID (the album-level
            clustering key in album match mode).
        title: Release-group title as reported by the service (display only).
    """

    release_group_id: str
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Release:
    """One MusicBrainz release a recording candidate appears on.

    A recording is frequently released many times (one sampled M83 track spans
    12 releases across 3 release groups), so a release is a *candidate*, never a
    single answer.  The selection criteria in
    :mod:`audio_fingerprinter.core.mbid_writer` narrow the candidates and write
    an id only when exactly one survives.

    Attributes:
        release_id: MusicBrainz release MBID.
        title: Release title. Empty when the service omitted it — with
            ``compress`` the title is dropped whenever it equals the parent
            release group's title, so the group title is the practical
            comparison target.
        track_count: Total tracks on the release, when reported.
        medium_count: Number of discs in the release, when reported.
        countries: Countries the release was issued in (a multi-region
            release reports every one of them).
        year: Release year, when reported.
        release_group_id: Parent release-group MBID.
        release_group_title: Parent release-group title.
        release_group_type: Release-group primary type (``"Album"``,
            ``"Compilation"``, ``"EP"``, ``"Single"``, ...).
    """

    release_id: str
    title: str = ""
    track_count: int | None = None
    medium_count: int | None = None
    countries: tuple[str, ...] = ()
    year: int | None = None
    release_group_id: str = ""
    release_group_title: str = ""
    release_group_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AcoustidRecording:
    """A single recording candidate returned by the AcoustID lookup.

    Attributes:
        acoustid_id: AcoustID id of the source result this recording
            came from (written to the ``Acoustid Id`` tag).
        recording_id: MusicBrainz recording MBID.
        title: Recording title.
        artist: Artist name (album-artist joinphrase is a precomputed string).
        artist_ids: MusicBrainz artist MBIDs credited on the recording, in
            service order (empty when the service reported none).
        score: AcoustID match score in the range 0.0-1.0.
        duration: Recording duration in seconds when the API reported it.
        release_groups: MusicBrainz release groups the recording appears
            on (empty when the service reported no release metadata) —
            the clustering key for album match mode.
        releases: Every release the recording appears on, as selection
            candidates for ``MUSICBRAINZ_ALBUMID``.
    """

    acoustid_id: str
    recording_id: str
    title: str
    artist: str = ""
    artist_ids: tuple[str, ...] = ()
    score: float = 0.0
    duration: int | None = None
    release_groups: tuple[ReleaseGroup, ...] = ()
    releases: tuple[Release, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LookupResult:
    """Outcome of a single AcoustID web-service lookup.

    Attributes:
        status: One of ``"ok"``, ``"no results"``, or ``"error"``.
        recordings: Recordings that met the score threshold, best first.
        error: Service-reported error text (empty when status != "error").
    """

    status: str
    recordings: tuple[AcoustidRecording, ...] = ()
    error: str = ""

    @property
    def best_match(self) -> AcoustidRecording | None:
        """Return the highest-scoring recording, or None when none matched."""
        return self.recordings[0] if self.recordings else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error": self.error,
            "recordings": [r.to_dict() for r in self.recordings],
        }


@dataclass(frozen=True)
class FingerprintParams:
    """Runtime parameters for a fingerprinting batch run.

    Attributes:
        lookup_enabled: Whether the AcoustID service is queried.
        write_tags: Whether to write the AcoustID tags on a match.  Still
            gated by ``is_dry_run`` — a Live Update is required for writes.
        is_dry_run: When True only analyse; never write tags.
        threshold: Minimum AcoustID score (0.0-1.0) for a candidate match.
        max_length: Maximum analysed duration in seconds sent to fpcalc.
        fpcalc_path: Explicit ``fpcalc`` binary path; empty resolves via env
            var ``FPCALC`` then ``shutil.which``.
        requests_per_second: Max AcoustID API request rate (per process).
        album_mode: Cluster each folder's lookups by MusicBrainz release
            group; tag files only when the folder's album is decided.
        album_min: Minimum files voting for one release group before an
            album cluster can form (album match mode only).
        write_mbids: Also write ``MUSICBRAINZ_TRACKID`` / ``MUSICBRAINZ_ARTISTID``
            / ``MUSICBRAINZ_ALBUMID`` on a match. Opt-in, off by default, and
            additive to the AcoustID tags (which are governed by
            ``write_tags``). Requires a Live Update like any other write.
        mbid_region: Preferred release country (ISO 3166-1 alpha-2, e.g.
            ``"GB"``). Empty means no regional preference. Only ever used to
            break a tie between otherwise indistinguishable release
            candidates — it can never select a release on its own.
    """

    lookup_enabled: bool = True
    write_tags: bool = False
    is_dry_run: bool = True
    threshold: float = 0.5
    max_length: int = 120
    fpcalc_path: str = ""
    requests_per_second: float = 1.0
    album_mode: bool = False
    album_min: int = 3
    write_mbids: bool = False
    mbid_region: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FingerprintFileResult:
    """Per-file outcome of a fingerprinting run, surfaced in the UI and the
    CLI summary / JSON.

    Attributes:
        file_path: Absolute path of the processed file.
        filename: Basename used in the progress listbox.
        status: One of ``"IDENTIFIED"``, ``"MATCHED"``, ``"NO MATCH"``,
            ``"LOOKUP SKIPPED"``, ``"ANALYSED"`` (album mode: fingerprint
            ready, awaiting the album decision), ``"ALBUM AMBIGUOUS"``
            (album mode: cluster tie, left untagged), ``"TAGGED"``,
            ``"TAG WRITE FAILED"``, or ``"ERROR"``.
        message: Short human-readable detail (e.g. the error text, or the
            matched artist / title with its AcoustID score).
        duration: fpcalc-reported file duration.
        fingerprint: The generated Chromaprint string.
        acoustid_id: AcoustID id of the best match (empty when unmatched).
        tag_written: Whether the AcoustID tags were written to disk.
    """

    file_path: str
    filename: str
    status: str
    message: str = ""
    duration: float = 0.0
    fingerprint: str = ""
    acoustid_id: str = ""
    recordings: tuple[AcoustidRecording, ...] = field(default_factory=tuple)
    tag_written: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "filename": self.filename,
            "status": self.status,
            "message": self.message,
            "duration": self.duration,
            "fingerprint": self.fingerprint,
            "acoustid_id": self.acoustid_id,
            "tag_written": self.tag_written,
            "recordings": [r.to_dict() for r in self.recordings],
        }

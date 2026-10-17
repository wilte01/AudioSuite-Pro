"""Immutable data models for the Audio Fingerprinter tool.

Records are frozen dataclasses carrying only the fields the UI and CLI need.
Every record exposes ``to_dict()`` so JSON output (CLI ``--json``) and logs
share one serialisation path.

Changed in 1.2.0: adds the MusicBrainz enrichment models (``MBReleaseFacts``,
``MBRecording``, ``MBEnrichment``), the ``Release.date`` field, the
``musicbrainz`` / ``write_isrc`` / ``submit_isrc`` runtime flags, and the
ISRC/enrichment fields on ``FingerprintFileResult``
(PLAN_feature_expansion.md D28, D29, D31, D27).
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class FingerprintStatus(str, Enum):
    """Per-file outcome of a fingerprinting run.

    The member values are the exact strings the Processing tab, the log file
    and the CLI summary display — this enum types the vocabulary, it does not
    change a single displayed byte.

    Attributes:
        ERROR: The file could not be processed (missing, unreadable, or the
            lookup failed).
        LOOKUP SKIPPED: Fingerprinted, but no lookup was attempted (lookup
            disabled, no API key, or no client).
        ANALYSED: Album mode only — the fingerprint is ready and the album
            phase has not decided yet.
        NO MATCH: No AcoustID candidate cleared the score threshold.
        MATCHED: A candidate was identified; any tag write is reported
            separately as TAGGED or TAG WRITE FAILED.
        TAGGED: The AcoustID tags were written to disk.
        TAG WRITE FAILED: The AcoustID tag write failed; the file is
            reported as an error and left untagged.
        ALBUM AMBIGUOUS: Album mode only — the folder's cluster tied and the
            file was left untagged.
    """

    ERROR = "ERROR"
    LOOKUP_SKIPPED = "LOOKUP SKIPPED"
    ANALYSED = "ANALYSED"
    NO_MATCH = "NO MATCH"
    MATCHED = "MATCHED"
    TAGGED = "TAGGED"
    TAG_WRITE_FAILED = "TAG WRITE FAILED"
    ALBUM_AMBIGUOUS = "ALBUM AMBIGUOUS"


def status_text(status: FingerprintStatus | str) -> str:
    """Return the display string for a result status.

    ``FingerprintStatus`` derives from ``str``, so a member *is* its value for
    every comparison — but its ``__str__`` is the enum repr, so interpolating
    one directly would print ``FingerprintStatus.MATCHED`` instead of
    ``MATCHED``. Every display site routes through this helper.

    Args:
        status: An enum member, or a plain status string.

    Returns:
        The exact text to display, byte-identical to the pre-enum strings.
    """
    return status.value if isinstance(status, FingerprintStatus) else status


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
    date: str = ""

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
class MBReleaseFacts:
    """Release-level facts fetched from MusicBrainz for one release MBID.

    Distinct from :class:`Release`, which is a *candidate* the AcoustID lookup
    returned and that ``mbid_writer`` narrows down.  This record describes a
    release the tool has already decided on and asked MusicBrainz about
    directly, so its fields are complete rather than best-effort.

    Attributes:
        release_id: MusicBrainz release MBID.
        title: Release title.
        date: Release date as reported (``YYYY``, ``YYYY-MM`` or
            ``YYYY-MM-DD``; partial dates are normal on MusicBrainz).
        countries: Release-event countries, upper-cased and deduplicated.
        labels: Label names in catalog order (empty when the service
            reported none).
        track_count: Track count reported for the release.
        medium_count: Number of media (discs) in the release.
        release_group_id: Parent release-group MBID.
        release_group_type: Release-group primary type.
    """

    release_id: str
    title: str = ""
    date: str = ""
    countries: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    track_count: int | None = None
    medium_count: int | None = None
    release_group_id: str = ""
    release_group_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MBRecording:
    """A recording looked up directly from MusicBrainz by its MBID.

    The AcoustID candidate record (:class:`AcoustidRecording`) is a *scored
    match*; this is the canonical MusicBrainz entity, which is where ISRCs
    live (``inc=isrcs``) and which therefore backs both the ISRC retrieval and
    the near-tie resolution.

    Attributes:
        recording_id: MusicBrainz recording MBID.
        title: Recording title.
        artist: Artist credit rendered with MusicBrainz joinphrases.
        artist_ids: Artist MBIDs in credit order.
        length_ms: Recording length in milliseconds, when reported.
        isrcs: ISRCs registered for this recording (may be empty).
        releases: Releases the recording appears on, as ``Release``
            candidates carrying the MusicBrainz date and country fields.
        release_group_ids: Release-group MBIDs the recording appears on.
    """

    recording_id: str
    title: str = ""
    artist: str = ""
    artist_ids: tuple[str, ...] = ()
    length_ms: int | None = None
    isrcs: tuple[str, ...] = ()
    releases: tuple[Release, ...] = ()
    release_group_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MBArtist:
    """An artist looked up directly from MusicBrainz by its MBID.

    Attributes:
        artist_id: MusicBrainz artist MBID.
        name: Artist name as the service renders it.
        sort_name: Sort name (``"Bowie, David"``), when reported.
        country: ISO country code of the artist's area, when reported.
        artist_type: Artist type (``"Person"``, ``"Group"``, ...).
        disambiguation: The service's disambiguation comment, when reported —
            the field that separates same-named artists.
    """

    artist_id: str
    name: str = ""
    sort_name: str = ""
    country: str = ""
    artist_type: str = ""
    disambiguation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MBEnrichment:
    """MusicBrainz enrichment attached to one processed file.

    Carried on :class:`FingerprintFileResult` so the log, the CLI JSON and the
    GUI all read one record.  An enrichment failure is never a new file
    status: the file keeps the status its AcoustID outcome earned and the
    failure is stated in ``note`` (see ``FingerprintStatus``' docstring for why
    no status member was added).

    Attributes:
        recording_id: MusicBrainz recording MBID the facts came from.
        isrcs: ISRCs registered for the recording.
        release: Facts for the release the tool selected, when one was.
        resolved_ambiguity: True when MusicBrainz broke an AcoustID near-tie
            the file's own tags could not.
        evidence: One-line reason for the ambiguity resolution.
        note: Enrichment failure text (empty on success).
    """

    recording_id: str = ""
    isrcs: tuple[str, ...] = ()
    release: MBReleaseFacts | None = None
    resolved_ambiguity: bool = False
    evidence: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "recording_id": self.recording_id,
            "isrcs": list(self.isrcs),
            "release": self.release.to_dict() if self.release else None,
            "resolved_ambiguity": self.resolved_ambiguity,
            "evidence": self.evidence,
            "note": self.note,
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
        musicbrainz: Query MusicBrainz directly to enrich matches: retrieve the
            recording's ISRCs, fetch release-level facts (date, label,
            country), and break AcoustID near-ties the file's tags could not.
            Off by default — MusicBrainz allows one request per second, so an
            album run costs one request per unique recording plus one per
            unique release.
        write_isrc: Write the retrieved ISRCs as tags.  Opt-in, off by default,
            additive to the AcoustID tags and governed by ``write_tags`` and
            ``is_dry_run`` exactly like ``write_mbids``.
        submit_isrc: Submit the ISRCs the *files' own tags* carry to
            MusicBrainz, as a pending edit on the matched recording.  Opt-in
            and off by default; requires ``musicbrainz`` (the recording lookup
            is what tells the run which codes are already registered).  In a
            dry run the exact XML payload is rendered and logged instead of
            posted, so the preview is the live request.
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
    musicbrainz: bool = False
    write_isrc: bool = False
    submit_isrc: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FingerprintFileResult:
    """Per-file outcome of a fingerprinting run, surfaced in the UI and the
    CLI summary / JSON.

    Attributes:
        file_path: Absolute path of the processed file.
        filename: Basename used in the progress listbox.
        status: One of the ``FingerprintStatus`` values — ``"ERROR"``,
            ``"LOOKUP SKIPPED"``, ``"ANALYSED"`` (album mode: fingerprint
            ready, awaiting the album decision), ``"NO MATCH"``,
            ``"MATCHED"``, ``"TAGGED"``, ``"TAG WRITE FAILED"``, or
            ``"ALBUM AMBIGUOUS"`` (album mode: cluster tie, left untagged).
            Producers pass the enum member; use :func:`status_text` to
            display it.
        message: Short human-readable detail (e.g. the error text, or the
            matched artist / title with its AcoustID score).
        duration: fpcalc-reported file duration.
        fingerprint: The generated Chromaprint string.
        acoustid_id: AcoustID id of the best match (empty when unmatched).
        tag_written: Whether the AcoustID tags were written to disk.
        recording_id: MusicBrainz recording MBID this file matched (empty when
            unmatched).  The identity ISRC submission attaches codes to, and
            the one field a result needs besides its own tags to say what is
            already registered.
        isrcs: ISRCs retrieved for the matched recording (empty when the
            MusicBrainz enrichment is off, unavailable, or reports none).
        mb: MusicBrainz enrichment for this file, or None when enrichment was
            not requested.
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
    recording_id: str = ""
    isrcs: tuple[str, ...] = ()
    mb: MBEnrichment | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "filename": self.filename,
            "status": status_text(self.status),
            "message": self.message,
            "duration": self.duration,
            "fingerprint": self.fingerprint,
            "acoustid_id": self.acoustid_id,
            "tag_written": self.tag_written,
            "recordings": [r.to_dict() for r in self.recordings],
            "recording_id": self.recording_id,
            "isrcs": list(self.isrcs),
            "musicbrainz": self.mb.to_dict() if self.mb else None,
        }

"""MusicBrainz web-service (WS/2 JSON) client for enrichment and ISRC retrieval.

The Audio Fingerprinter already identifies recordings through AcoustID, which
carries MusicBrainz identifiers and release candidates with every match.  This
client exists for the facts AcoustID does *not* return: the recording's
registered ISRCs, the canonical recording/artist entities behind an MBID, and
complete release-level facts (date, label, country) for a release the tool has
already chosen.

Conventions deliberately mirror ``acoustid_client`` and the CD Ripper's
``accuraterip`` client:

* every failure is a typed result — never an exception — so the caller degrades
  to AcoustID-only behaviour instead of failing a file;
* one shared :class:`~audio_fingerprinter.core.acoustid_client.RateLimiter`
  spaces requests, because MusicBrainz allows one request per second per
  client;
* results are cached per entity for the life of the run, so an album of twelve
  tracks on one release costs one recording request per track plus *one*
  release request, not one per file.

ISRC submission lives here too: :func:`build_isrc_submission_xml` renders the
MMD 2.0 document MusicBrainz accepts and :meth:`MusicBrainzClient.submit_isrcs`
POSTs it to ``/ws/2/recording/?client=…``.  The submission body is XML only —
MusicBrainz's JSON service is read-only — and needs either an OAuth bearer token
(scope ``submit_isrc``) or the legacy application token over HTTP Digest.
Building the payload is a pure function so a dry run can render the exact bytes
a live run would send without contacting the service.

Changed in 1.2.0: new module — MusicBrainz lookup by MBID, recording ISRCs,
release-level facts, the MusicBrainz near-tie tie-break, and token-based ISRC
submission (PLAN_feature_expansion.md D28, D31, D27).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar
from urllib.parse import quote

import requests
from requests.auth import HTTPDigestAuth

from audio_suite_shared.project_version import declared_version

from .acoustid_client import RateLimiter, tied_candidates
from .models import (
    AcoustidRecording,
    MBArtist,
    MBRecording,
    MBReleaseFacts,
    Release,
    ReleaseGroup,
)

logger = logging.getLogger(__name__)

MUSICBRAINZ_WS_BASE = "https://musicbrainz.org/ws/2"
DEFAULT_TIMEOUT_SECS = 30.0
#: MusicBrainz asks every client to stay at or below one request per second.
REQUESTS_PER_SECOND = 1.0
#: MusicBrainz requires a meaningful User-Agent identifying the application.
CONTACT_URL = "https://github.com/audio-suite"
USER_AGENT = f"AudioSuite-Pro/{declared_version()} ( {CONTACT_URL} )"
#: ``client`` query parameter: the submitting application and its version.
#: Mandatory on every submission — including OAuth-authenticated ones — and it
#: belongs in the URL, never in the XML body.
CLIENT_PARAM = f"audio-suite-pro-{declared_version()}"
#: Submission endpoint, relative to the WS/2 base.  The trailing slash is part
#: of the documented URL (``/ws/2/recording/?client=…``).
SUBMIT_PATH = "recording/"
#: A successful submission is an *edit*, not a write: MusicBrainz keeps new
#: edits open for review before they apply.
EDIT_REVIEW_DAYS = 7

#: ISRCs as MusicBrainz stores them: 12 characters, upper case, no separators.
#: Two letter country, three character registrant, then seven digits (a two
#: digit year plus a five digit designation).  This is the service's own
#: submission validator, so a value that passes here is one it will accept.
_ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$")
#: Separators the display form (``CC-XXX-YY-NNNNN``) may carry.
_ISRC_SEPARATORS_RE = re.compile(r"[\s-]+")

#: Includes for a recording lookup: ISRCs (the point of the request), the
#: artist credit, and the releases + release groups used by the tie-break.
RECORDING_INCLUDES: tuple[str, ...] = (
    "isrcs",
    "artist-credits",
    "releases",
    "release-groups",
)
#: Includes for a release lookup: the release-level facts the plan asks for.
RELEASE_INCLUDES: tuple[str, ...] = (
    "artist-credits",
    "labels",
    "media",
    "release-groups",
)
#: Includes for an artist lookup: nothing beyond the entity itself is needed.
ARTIST_INCLUDES: tuple[str, ...] = ()

_MBID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

#: Worst-case entity fetches for one near-tie resolution (the two top
#: candidates); each is a separate rate-limited request.
_TIE_BREAK_MAX_CANDIDATES = 2

MBStatus = Literal["ok", "not found", "offline", "invalid id"]
#: ``ok`` — accepted as a pending edit; ``nothing to submit`` — no codes left
#: after removing what MusicBrainz already has; ``no auth`` — no usable token,
#: so no request was made; ``rejected`` — the service refused the payload
#: (HTTP 400: invalid ISRC or recording MBID); ``not authorised`` — the token
#: is missing the ``submit_isrc`` scope, was revoked, or the account's email is
#: unverified; ``offline`` — network, throttle or unexpected HTTP failure.
ISRCSubmitStatus = Literal[
    "ok",
    "nothing to submit",
    "no auth",
    "rejected",
    "not authorised",
    "offline",
]
_T = TypeVar("_T")


def is_valid_mbid(value: str) -> bool:
    """Return whether *value* has the shape of a MusicBrainz identifier.

    Checked locally, before any request, so a typo costs a clear message
    instead of a round trip and an opaque 400.

    Args:
        value: Candidate MBID (with or without surrounding whitespace).

    Returns:
        True for a canonical 36-character UUID string.
    """
    return bool(_MBID_RE.match(value.strip()))


def normalize_isrc(value: str) -> str:
    """Return *value* in the form MusicBrainz stores and accepts.

    Tags frequently carry the display form (``CC-XXX-YY-NNNNN``); the service
    takes the compact upper-case form only, so hyphens and whitespace are
    stripped and the code upper-cased.  Nothing else is changed, so a value
    that is simply wrong stays wrong and :func:`isrc_error` can say why.

    Args:
        value: A candidate ISRC in either form.

    Returns:
        The compact, upper-cased candidate (possibly still invalid).
    """
    return _ISRC_SEPARATORS_RE.sub("", value.strip()).upper()


def is_valid_isrc(value: str) -> bool:
    """Return whether *value* is an ISRC MusicBrainz would accept.

    Args:
        value: Candidate ISRC in display or compact form.

    Returns:
        True for a compact, upper-case 12-character ISRC.
    """
    return bool(_ISRC_RE.match(normalize_isrc(value)))


def isrc_error(value: str) -> str:
    """Explain why *value* cannot be submitted as an ISRC, or return ``""``.

    One helper serves both the per-file report and the pre-submission check, so
    the reason a code is refused is written exactly once.  Validation is local
    and structural only: it cannot know whether a registrant code is assigned,
    but it can catch the mistakes tags actually carry (a truncated code, a
    letter where the designation needs a digit).

    Args:
        value: Candidate ISRC in display or compact form.

    Returns:
        An empty string when the code is submittable, otherwise a sentence
        naming the defect.
    """
    cleaned = normalize_isrc(value)
    if not cleaned:
        return "the ISRC is empty"
    if len(cleaned) != 12:
        return (
            f"{value.strip()!r} is not an ISRC: expected 12 characters "
            "(CC-XXX-YY-NNNNN), "
            f"got {len(cleaned)} after removing separators"
        )
    if not _ISRC_RE.match(cleaned):
        return (
            f"{value.strip()!r} is not an ISRC: expected two letters, three "
            "letters or digits, then seven digits (CC-XXX-YY-NNNNN)"
        )
    return ""


@dataclass(frozen=True)
class MBResult(Generic[_T]):
    """Outcome of one MusicBrainz lookup, typed by the entity it carries.

    Attributes:
        status: ``"ok"`` when the entity was fetched, otherwise
            ``"not found"`` (no such MBID), ``"offline"`` (network, HTTP or
            parse failure) or ``"invalid id"`` (rejected before any request).
        value: The parsed entity, present only for ``status == "ok"``.
        reason: Human-readable failure text (empty on success).
        url: The request URL, for the log and for reproduction.
    """

    status: MBStatus
    value: _T | None = None
    reason: str = ""
    url: str = ""

    @property
    def ok(self) -> bool:
        """Whether the lookup succeeded."""
        return self.status == "ok"


@dataclass(frozen=True)
class MBTieBreak:
    """Result of resolving an AcoustID near-tie with MusicBrainz.

    Attributes:
        recording: The candidate to use — the resolved one, or the original
            rank-order top when MusicBrainz could not separate the tie.
        resolved: True when MusicBrainz chose a different candidate than the
            rank order did.
        evidence: One-line explanation for the message text (empty when
            unresolved).
    """

    recording: AcoustidRecording
    resolved: bool = False
    evidence: str = ""


@dataclass(frozen=True)
class ISRCSubmission:
    """ISRCs one file wants MusicBrainz to attach to a recording.

    Attributes:
        recording_id: MusicBrainz recording MBID the codes belong to.
        isrcs: Candidate ISRCs, in any form — they are normalised and
            validated when the payload is built.  Empty means the file had
            nothing new to say.
    """

    recording_id: str
    isrcs: tuple[str, ...] = ()


MBAAuthMethod = Literal["oauth", "app-token"]


@dataclass(frozen=True)
class MBAuth:
    """Credentials for a MusicBrainz submission.

    Args:
        token: OAuth access token (scope ``submit_isrc``) or, for
            ``method="app-token"``, a legacy application token.
        method: ``"oauth"`` sends ``Authorization: Bearer <token>``;
            ``"app-token"`` uses HTTP Digest with the account's username and
            the application token in place of the password.  Digest is
            deprecated by MusicBrainz (removal announced for 2027-08-01) and
            remains only for accounts that already generated a token.
        username: MusicBrainz account name — required by ``app-token`` only.
    """

    token: str = ""
    method: MBAAuthMethod = "oauth"
    username: str = ""

    @property
    def problem(self) -> str:
        """Return why these credentials cannot submit, or ``""`` if they can.

        One property feeds the GUI pre-flight, the CLI guard and the client's
        refusal, so the three can never phrase the same gap differently.
        """
        if not self.token.strip():
            return (
                "No MusicBrainz token is configured. Set MUSICBRAINZ_TOKEN or "
                "store an OAuth token with the submit_isrc scope."
            )
        if self.method == "app-token" and not self.username.strip():
            return (
                "Legacy app-token submission needs the MusicBrainz username "
                "(--mb-user): digest authentication sends both."
            )
        return ""

    @property
    def describe(self) -> str:
        """Short label for logs — the method, never the secret."""
        return (
            "OAuth bearer token"
            if self.method == "oauth"
            else f"application token (digest, user {self.username})"
        )


@dataclass(frozen=True)
class ISRCSubmitResult:
    """Outcome of one ISRC submission attempt.

    Attributes:
        status: See :data:`ISRCSubmitStatus`.
        recordings: Recordings in the payload (0 when nothing was sent).
        isrcs: ISRCs in the payload (0 when nothing was sent).
        url: The POST target, for the log and for reproduction.
        reason: Human-readable failure text (empty on success).
    """

    status: ISRCSubmitStatus
    recordings: int = 0
    isrcs: int = 0
    url: str = ""
    reason: str = ""

    @property
    def ok(self) -> bool:
        """Whether the service accepted the submission."""
        return self.status == "ok"


@dataclass(frozen=True)
class _Fetch:
    """One HTTP attempt's raw outcome, before entity parsing."""

    url: str = ""
    status: MBStatus = "ok"
    payload: dict[str, Any] | None = None
    reason: str = ""


def _opt_int(value: object) -> int | None:
    """Coerce a JSON number to int, or None when absent/not numeric."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _text(value: object) -> str:
    """Return a JSON string field, or an empty string."""
    return value if isinstance(value, str) else ""


def _join_artist_credit(raw: object) -> str:
    """Render a MusicBrainz ``artist-credit`` array with its joinphrases.

    Each entry carries the ``joinphrase`` that follows its name (``" & "``,
    ``" feat. "``, ...), so concatenating in order reproduces the credited
    string exactly as MusicBrainz displays it.
    """
    if not isinstance(raw, list):
        return ""
    parts: list[str] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = _text(entry.get("name")) or _text(
            (entry.get("artist") or {}).get("name")
            if isinstance(entry.get("artist"), dict)
            else ""
        )
        if name:
            parts.append(name)
        parts.append(_text(entry.get("joinphrase")))
    return "".join(parts)


def _artist_ids(raw: object) -> tuple[str, ...]:
    """Collect the artist MBIDs of an ``artist-credit`` array, in order."""
    if not isinstance(raw, list):
        return ()
    found: list[str] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        artist = entry.get("artist")
        artist_id = _text(artist.get("id")) if isinstance(artist, dict) else ""
        artist_id = artist_id or _text(entry.get("artist_id"))
        if artist_id and artist_id not in found:
            found.append(artist_id)
    return tuple(found)


def _release_countries(release: Mapping[str, Any]) -> tuple[str, ...]:
    """Collect a release's countries from either JSON shape.

    A release nested in a recording lookup reports a single flattened
    ``country``; a release fetched in its own right can carry the full
    ``release-events`` list.  Both are read, deduplicated and upper-cased.
    """
    found: list[str] = []
    events = release.get("release-events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            area = event.get("area")
            country = _text(event.get("country")) or (
                _text(area.get("iso-3166-1-code")) if isinstance(area, dict) else ""
            )
            country = country.upper()
            if country and country not in found:
                found.append(country)
    flat = _text(release.get("country")).upper()
    if flat and flat not in found:
        found.append(flat)
    return tuple(found)


def _release_from_json(raw: object) -> Release | None:
    """Build a ``Release`` candidate from a MusicBrainz release object."""
    if not isinstance(raw, dict):
        return None
    release_id = _text(raw.get("id"))
    if not release_id:
        return None
    group = raw.get("release-group")
    group = group if isinstance(group, dict) else {}
    date = _text(raw.get("date"))
    media = raw.get("media")
    medium_count = len(media) if isinstance(media, list) and media else None
    return Release(
        release_id=release_id,
        title=_text(raw.get("title")),
        track_count=_opt_int(raw.get("track-count")),
        medium_count=medium_count,
        countries=_release_countries(raw),
        year=int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None,
        release_group_id=_text(group.get("id")),
        release_group_title=_text(group.get("title")),
        release_group_type=_text(group.get("primary-type")),
        date=date,
    )


def _release_groups_from_recording(raw: object) -> tuple[ReleaseGroup, ...]:
    """Collect a recording's release-group MBIDs from its releases."""
    groups: list[ReleaseGroup] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return ()
    for release in raw:
        if not isinstance(release, dict):
            continue
        group = release.get("release-group")
        if not isinstance(group, dict):
            continue
        group_id = _text(group.get("id"))
        if group_id and group_id not in seen:
            seen.add(group_id)
            groups.append(
                ReleaseGroup(release_group_id=group_id, title=_text(group.get("title")))
            )
    return tuple(groups)


def _string_list(raw: object) -> tuple[str, ...]:
    """Collect a JSON array of strings, deduplicated and order-preserving."""
    if not isinstance(raw, list):
        return ()
    found: list[str] = []
    for item in raw:
        value = item if isinstance(item, str) else ""
        if value and value not in found:
            found.append(value)
    return tuple(found)


def _isrc_list(raw: object) -> tuple[str, ...]:
    """Collect a recording's ISRCs from either JSON shape.

    ``inc=isrcs`` returns an array of plain strings; a nested-entity response
    (or a future shape) may return ``{"id": ...}`` objects instead, so both
    are read rather than silently yielding nothing.  Each entry is handled on
    its own, so a mixed array loses neither shape.
    """
    if not isinstance(raw, list):
        return ()
    values = [
        entry
        if isinstance(entry, str)
        else _text(entry.get("id"))
        if isinstance(entry, dict)
        else ""
        for entry in raw
    ]
    return _string_list(values)


def parse_recording(payload: Mapping[str, Any]) -> MBRecording:
    """Parse a WS/2 recording lookup body into an :class:`MBRecording`.

    The same parser also serves the ``recording-list`` entries of other
    responses, because the entity shape is identical.

    Args:
        payload: The decoded JSON body of a recording lookup.

    Returns:
        The parsed recording; unrecognised or absent optional fields come back
        empty rather than raising, mirroring the AcoustID client's tolerance of
        partial responses.
    """
    isrcs = _isrc_list(payload.get("isrcs"))
    releases_raw = payload.get("releases")
    releases: list[Release] = []
    if isinstance(releases_raw, list):
        for item in releases_raw:
            release = _release_from_json(item)
            if release is not None:
                releases.append(release)
    return MBRecording(
        recording_id=_text(payload.get("id")),
        title=_text(payload.get("title")),
        artist=_join_artist_credit(payload.get("artist-credit")),
        artist_ids=_artist_ids(payload.get("artist-credit")),
        length_ms=_opt_int(payload.get("length")),
        isrcs=isrcs,
        releases=tuple(releases),
        release_group_ids=tuple(
            group.release_group_id
            for group in _release_groups_from_recording(releases_raw)
        ),
    )


def parse_release(payload: Mapping[str, Any]) -> MBReleaseFacts:
    """Parse a WS/2 release lookup body into :class:`MBReleaseFacts`.

    Args:
        payload: The decoded JSON body of a release lookup.

    Returns:
        The release's identity, date, countries, labels and counts.  Media
        without a ``track-count`` are still counted as a medium, and media that
        report one have their counts summed.
    """
    group = payload.get("release-group")
    group = group if isinstance(group, dict) else {}
    labels: list[str] = []
    media = payload.get("media")
    medium_count = 0
    track_count = 0
    if isinstance(media, list):
        for medium in media:
            if not isinstance(medium, dict):
                continue
            medium_count += 1
            count = _opt_int(medium.get("track-count"))
            if count:
                track_count += count
    label_info = payload.get("label-info")
    if isinstance(label_info, list):
        for info in label_info:
            if not isinstance(info, dict):
                continue
            label = info.get("label")
            name = _text(label.get("name")) if isinstance(label, dict) else ""
            if name and name not in labels:
                labels.append(name)
    return MBReleaseFacts(
        release_id=_text(payload.get("id")),
        title=_text(payload.get("title")),
        date=_text(payload.get("date")),
        countries=_release_countries(payload),
        labels=tuple(labels),
        track_count=track_count or _opt_int(payload.get("track-count")),
        medium_count=medium_count or None,
        release_group_id=_text(group.get("id")),
        release_group_type=_text(group.get("primary-type")),
    )


def _normalise_submissions(
    submissions: Sequence[ISRCSubmission],
) -> dict[str, tuple[str, ...]]:
    """Group submissions by recording, validating and ordering every value.

    The single validation point for a payload: a bad MBID or ISRC raises here,
    before any bytes reach the wire, and both the dry-run renderer and the live
    POST go through it.  Grouping merges two files that matched the same
    recording, which also removes an ISRC two files both carry.

    Args:
        submissions: One entry per file (or per recording).

    Returns:
        ``{recording_id: sorted ISRCs}`` sorted by recording id, so the same
        input always produces the same payload bytes.

    Raises:
        ValueError: If a recording id is not an MBID, or an ISRC is invalid.
    """
    grouped: dict[str, set[str]] = {}
    for submission in submissions:
        recording_id = submission.recording_id.strip().lower()
        if not is_valid_mbid(recording_id):
            raise ValueError(
                f"Cannot submit ISRCs: {submission.recording_id!r} is not a "
                "MusicBrainz recording id (expected a 36-character UUID)."
            )
        codes = grouped.setdefault(recording_id, set())
        for value in submission.isrcs:
            problem = isrc_error(value)
            if problem:
                raise ValueError(f"Cannot submit ISRCs: {problem}.")
            codes.add(normalize_isrc(value))
    return {
        recording_id: tuple(sorted(codes))
        for recording_id, codes in sorted(grouped.items())
        if codes
    }


def build_isrc_submission_xml(submissions: Sequence[ISRCSubmission]) -> str:
    """Render ISRC submissions as the MMD 2.0 document MusicBrainz accepts.

    This is the whole submission body.  It is a pure function of its input, and
    :meth:`MusicBrainzClient.submit_isrcs` posts exactly this string, so a dry
    run that shows it is showing the live request byte for byte.

    Ordering is normalised (recordings and their ISRCs sorted), because files
    are processed in parallel and an unordered payload could not be shown ahead
    of time and then matched later.

    Args:
        submissions: One entry per file or recording.

    Returns:
        The XML body, ending in a newline; ``""`` when nothing is left to
        submit (an empty document must never be posted).

    Raises:
        ValueError: If a recording id is not an MBID, or an ISRC is invalid —
            the service would answer 400, and a local reason is more useful.
    """
    groups = _normalise_submissions(submissions)
    if not groups:
        return ""
    lines = ['<metadata xmlns="http://musicbrainz.org/ns/mmd-2.0#">']
    lines.append("  <recording-list>")
    for recording_id, isrcs in groups.items():
        lines.append(f'    <recording id="{recording_id}">')
        lines.append(f'      <isrc-list count="{len(isrcs)}">')
        for isrc in isrcs:
            lines.append(f'        <isrc id="{isrc}"/>')
        lines.append("      </isrc-list>")
        lines.append("    </recording>")
    lines.append("  </recording-list>")
    lines.append("</metadata>")
    return "\n".join(lines) + "\n"


def parse_artist(payload: Mapping[str, Any]) -> MBArtist:
    """Parse a WS/2 artist lookup body into an :class:`MBArtist`.

    Args:
        payload: The decoded JSON body of an artist lookup.

    Returns:
        The artist's identity, sort name, country, type and disambiguation.
    """
    area = payload.get("area")
    begin_area = payload.get("begin-area")
    country = _text(area.get("iso-3166-1-code")) if isinstance(area, dict) else ""
    if not country and isinstance(begin_area, dict):
        country = _text(begin_area.get("iso-3166-1-code"))
    if not country:
        country = _text(payload.get("country"))
    return MBArtist(
        artist_id=_text(payload.get("id")),
        name=_text(payload.get("name")),
        sort_name=_text(payload.get("sort-name")),
        country=country.upper(),
        artist_type=_text(payload.get("type")),
        disambiguation=_text(payload.get("disambiguation")),
    )


class MusicBrainzClient:
    """Small read-only client for the MusicBrainz web service.

    Args:
        requests_per_second: Maximum request rate for this instance.  The
            default matches MusicBrainz's documented one request per second.
        timeout: HTTP timeout in seconds.
        base_url: WS/2 base URL (override for tests).
        user_agent: User-Agent sent with every request.
        session: Optional pre-built ``requests.Session`` (tests inject one).
        client_param: Value of the mandatory ``client`` query parameter.

    Attributes:
        requests_issued: Number of HTTP requests this instance has attempted,
            including failures — the counter the log and the tests read.
    """

    def __init__(
        self,
        *,
        requests_per_second: float = REQUESTS_PER_SECOND,
        timeout: float = DEFAULT_TIMEOUT_SECS,
        base_url: str = MUSICBRAINZ_WS_BASE,
        user_agent: str = USER_AGENT,
        session: requests.Session | None = None,
        client_param: str = CLIENT_PARAM,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._rate_limiter = RateLimiter(1.0 / max(requests_per_second, 0.01))
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": user_agent})
        self._submit_url = (
            f"{self._base_url}/{SUBMIT_PATH}"
            f"?client={quote(client_param.strip(), safe='')}"
        )
        self._recording_cache: dict[str, MBResult[MBRecording]] = {}
        self._release_cache: dict[str, MBResult[MBReleaseFacts]] = {}
        self._artist_cache: dict[str, MBResult[MBArtist]] = {}
        self.requests_issued = 0

    # ── Public lookups ────────────────────────────────────────────────────

    def get_recording(self, recording_id: str) -> MBResult[MBRecording]:
        """Fetch one recording by MBID, including its ISRCs.

        Args:
            recording_id: MusicBrainz recording MBID.

        Returns:
            An :class:`MBResult`; repeated calls for the same MBID reuse the
            cached outcome, including a cached failure, so a down service is
            not hammered once per file.
        """
        return self._cached_lookup(
            recording_id,
            self._recording_cache,
            lambda key: self._fetch(
                f"recording/{key}", {"inc": " ".join(RECORDING_INCLUDES)}
            ),
            parse_recording,
        )

    def get_release(self, release_id: str) -> MBResult[MBReleaseFacts]:
        """Fetch one release by MBID, with its date, labels and country.

        Args:
            release_id: MusicBrainz release MBID.

        Returns:
            An :class:`MBResult` carrying :class:`MBReleaseFacts`.
        """
        return self._cached_lookup(
            release_id,
            self._release_cache,
            lambda key: self._fetch(
                f"release/{key}", {"inc": " ".join(RELEASE_INCLUDES)}
            ),
            parse_release,
        )

    def get_artist(self, artist_id: str) -> MBResult[MBArtist]:
        """Fetch one artist by MBID.

        Args:
            artist_id: MusicBrainz artist MBID.

        Returns:
            An :class:`MBResult` carrying :class:`MBArtist`.
        """
        return self._cached_lookup(
            artist_id,
            self._artist_cache,
            lambda key: self._fetch(
                f"artist/{key}", {"inc": " ".join(ARTIST_INCLUDES)}
            ),
            parse_artist,
        )

    # ── Submission ────────────────────────────────────────────────────────

    def submit_isrcs(
        self,
        submissions: Sequence[ISRCSubmission],
        auth: MBAuth,
    ) -> ISRCSubmitResult:
        """Attach ISRCs to their recordings, as a pending MusicBrainz edit.

        The body is :func:`build_isrc_submission_xml` of the same submissions,
        so a caller that showed a preview showed this request.  A successful
        response is an *edit* awaiting review — the codes are not on the
        recording yet.

        Args:
            submissions: ISRCs to add, one entry per file or recording.
            auth: OAuth token or legacy application-token credentials.

        Returns:
            An :class:`ISRCSubmitResult`.  Nothing is sent when every ISRC is
            already registered (``nothing to submit``) or when no usable token
            is configured (``no auth``) — neither is an error, and neither
            spends an edit on a no-op.
        """
        groups = _normalise_submissions(submissions)
        recordings = len(groups)
        isrcs = sum(len(codes) for codes in groups.values())
        if not groups:
            return ISRCSubmitResult(
                status="nothing to submit",
                url=self._submit_url,
                reason="Every ISRC in these files is already registered.",
            )
        problem = auth.problem
        if problem:
            return ISRCSubmitResult(
                status="no auth",
                recordings=recordings,
                isrcs=isrcs,
                url=self._submit_url,
                reason=problem,
            )

        body = build_isrc_submission_xml(submissions)
        headers = {
            "Content-Type": "application/xml; charset=UTF-8",
            "Accept": "application/xml",
        }
        request_kwargs: dict[str, Any] = {
            "data": body.encode("utf-8"),
            "timeout": self._timeout,
            "headers": headers,
        }
        if auth.method == "oauth":
            headers["Authorization"] = f"Bearer {auth.token.strip()}"
        else:
            request_kwargs["auth"] = HTTPDigestAuth(
                auth.username.strip(), auth.token.strip()
            )

        self.requests_issued += 1
        self._rate_limiter.wait_for_slot()
        logger.info(
            "Submitting %d ISRC(s) for %d recording(s) to MusicBrainz (%s)",
            isrcs,
            recordings,
            auth.describe,
        )
        try:
            response = self._session.post(self._submit_url, **request_kwargs)
        except requests.RequestException as exc:
            logger.warning("MusicBrainz ISRC submission failed: %s", exc)
            return ISRCSubmitResult(
                status="offline",
                recordings=recordings,
                isrcs=isrcs,
                url=self._submit_url,
                reason=f"Network error submitting to MusicBrainz: {exc}",
            )

        status_code = response.status_code
        if status_code == 200:
            return ISRCSubmitResult(
                status="ok",
                recordings=recordings,
                isrcs=isrcs,
                url=self._submit_url,
            )
        if status_code in (401, 403):
            return ISRCSubmitResult(
                status="not authorised",
                recordings=recordings,
                isrcs=isrcs,
                url=self._submit_url,
                reason=(
                    f"MusicBrainz refused the submission (HTTP {status_code}): "
                    "the token needs the submit_isrc scope, may be expired, and "
                    "the account's email address must be verified."
                ),
            )
        if status_code == 400:
            return ISRCSubmitResult(
                status="rejected",
                recordings=recordings,
                isrcs=isrcs,
                url=self._submit_url,
                reason=(
                    "MusicBrainz rejected the submission as invalid (HTTP 400): "
                    "check the ISRCs and recording ids in the payload."
                ),
            )
        if status_code == 503:
            return ISRCSubmitResult(
                status="offline",
                recordings=recordings,
                isrcs=isrcs,
                url=self._submit_url,
                reason=(
                    "MusicBrainz asked the client to slow down (HTTP 503); "
                    "nothing was submitted — retry later."
                ),
            )
        return ISRCSubmitResult(
            status="offline",
            recordings=recordings,
            isrcs=isrcs,
            url=self._submit_url,
            reason=f"MusicBrainz returned HTTP {status_code}; nothing was submitted.",
        )

    # ── Internals ─────────────────────────────────────────────────────────

    def _cached_lookup(
        self,
        entity_id: str,
        cache: dict[str, MBResult[_T]],
        fetch: Callable[[str], _Fetch],
        parse: Callable[[Mapping[str, Any]], _T],
    ) -> MBResult[_T]:
        """Run one cached entity lookup, validating the MBID first."""
        cleaned = entity_id.strip()
        if not is_valid_mbid(cleaned):
            reason = (
                f"Not a MusicBrainz identifier: {entity_id!r} "
                "(expected a 36-character UUID)."
            )
            logger.debug("MusicBrainz lookup rejected: %s", reason)
            return MBResult(status="invalid id", reason=reason)
        key = cleaned.lower()
        cached = cache.get(key)
        if cached is not None:
            return cached
        result = self._to_result(fetch(key), parse)
        cache[key] = result
        return result

    def _to_result(
        self, fetch: _Fetch, parse: Callable[[Mapping[str, Any]], _T]
    ) -> MBResult[_T]:
        """Map a raw fetch into a typed result, parsing on success."""
        if fetch.payload is None:
            return MBResult(status=fetch.status, reason=fetch.reason, url=fetch.url)
        try:
            value: _T = parse(fetch.payload)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("MusicBrainz payload unparseable for %s: %s", fetch.url, exc)
            return MBResult(
                status="offline",
                reason=f"Malformed MusicBrainz payload: {exc}",
                url=fetch.url,
            )
        return MBResult(status="ok", value=value, url=fetch.url)

    def _fetch(self, path: str, params: Mapping[str, str]) -> _Fetch:
        """Perform one rate-limited GET, mapping every failure to a status."""
        url = f"{self._base_url}/{path}"
        query = dict(params, fmt="json")
        self.requests_issued += 1
        self._rate_limiter.wait_for_slot()
        try:
            response = self._session.get(url, params=query, timeout=self._timeout)
        except requests.RequestException as exc:
            logger.warning("MusicBrainz request failed for %s: %s", url, exc)
            return _Fetch(
                url=url,
                status="offline",
                reason=f"Network error querying MusicBrainz: {exc}",
            )

        if response.status_code == 404:
            logger.debug("MusicBrainz: no entity at %s", url)
            return _Fetch(
                url=url,
                status="not found",
                reason="MusicBrainz has no entity with that MBID.",
            )
        if response.status_code in (401, 403):
            return _Fetch(
                url=url,
                status="offline",
                reason=(
                    f"MusicBrainz refused the request (HTTP {response.status_code}); "
                    "lookups are anonymous, so this is a service-side rejection."
                ),
            )
        if response.status_code != 200:
            return _Fetch(
                url=url,
                status="offline",
                reason=f"MusicBrainz returned HTTP {response.status_code}.",
            )
        try:
            payload: object = response.json()
        except ValueError:
            return _Fetch(
                url=url,
                status="offline",
                reason="MusicBrainz returned a non-JSON response.",
            )
        if not isinstance(payload, dict):
            return _Fetch(
                url=url,
                status="offline",
                reason="MusicBrainz returned an unexpected payload shape.",
            )
        return _Fetch(url=url, payload=payload)


def resolve_ambiguous_with_mb(
    recordings: Sequence[AcoustidRecording],
    client: MusicBrainzClient,
    *,
    album_tag: str = "",
    title_tag: str = "",
    artist_tag: str = "",
) -> MBTieBreak:
    """Break an AcoustID near-tie with MusicBrainz facts.

    Called only after the file's own tags failed to settle the near-tie
    (``resolve_best_match`` reports ``ambiguous=True, tag_resolved=False``).
    The tied candidates are looked up in MusicBrainz and the winner is chosen
    only on evidence that actually distinguishes them, in this order:

    1. the recording whose MusicBrainz title **and** artist fold to the file's
       existing title/artist tags;
    2. the recording that appears on a release whose title folds to the file's
       album tag, when only one of them does;
    3. the recording that has ISRCs registered, when only one of them does.

    If none of those separate the candidates — or MusicBrainz is offline — the
    rank-order top is returned unchanged, so an unavailable service degrades
    the run to its previous behaviour instead of inventing a match.

    Args:
        recordings: Candidates sorted by score (best first), already
            duration-consistent with the file.
        client: The MusicBrainz client to query.
        album_tag: The file's existing album tag (empty when absent).
        title_tag: The file's existing title tag (empty when absent).
        artist_tag: The file's existing artist tag (empty when absent).

    Returns:
        An :class:`MBTieBreak` naming the candidate to use.
    """
    from .mbid_writer import normalize_title

    tied = tied_candidates(recordings)[:_TIE_BREAK_MAX_CANDIDATES]
    if len(tied) < 2:
        return MBTieBreak(recording=recordings[0])
    top = recordings[0]

    lookups: dict[str, MBRecording] = {}
    for candidate in tied:
        result = client.get_recording(candidate.recording_id)
        if result.ok and result.value is not None:
            lookups[candidate.recording_id] = result.value
    if len(lookups) < 2:
        reason = "MusicBrainz unreachable or incomplete" if not lookups else ""
        logger.debug("Near-tie not resolved by MusicBrainz: %s", reason or "no data")
        return MBTieBreak(recording=top)

    file_title = normalize_title(title_tag)
    file_artist = normalize_title(artist_tag)
    if file_title and file_artist:
        matches = [
            candidate
            for candidate in tied
            if normalize_title(lookups[candidate.recording_id].title) == file_title
            and normalize_title(lookups[candidate.recording_id].artist) == file_artist
        ]
        if len(matches) == 1:
            return MBTieBreak(
                recording=matches[0],
                resolved=matches[0].recording_id != top.recording_id,
                evidence="MusicBrainz recording matches the file tags",
            )

    file_album = normalize_title(album_tag)
    if file_album:
        on_album = [
            candidate
            for candidate in tied
            if any(
                normalize_title(release.title) == file_album
                or normalize_title(release.release_group_title) == file_album
                for release in lookups[candidate.recording_id].releases
            )
        ]
        if len(on_album) == 1:
            return MBTieBreak(
                recording=on_album[0],
                resolved=on_album[0].recording_id != top.recording_id,
                evidence="MusicBrainz release matches the file's album tag",
            )

    with_isrc = [
        candidate for candidate in tied if lookups[candidate.recording_id].isrcs
    ]
    if len(with_isrc) == 1:
        return MBTieBreak(
            recording=with_isrc[0],
            resolved=with_isrc[0].recording_id != top.recording_id,
            evidence="MusicBrainz has ISRCs for this recording",
        )

    logger.debug(
        "MusicBrainz could not separate %d tied candidates; keeping rank order",
        len(tied),
    )
    return MBTieBreak(recording=top)


__all__ = [
    "ARTIST_INCLUDES",
    "CLIENT_PARAM",
    "CONTACT_URL",
    "DEFAULT_TIMEOUT_SECS",
    "EDIT_REVIEW_DAYS",
    "ISRCSubmission",
    "ISRCSubmitResult",
    "ISRCSubmitStatus",
    "MBAAuthMethod",
    "MBAuth",
    "MBResult",
    "MBStatus",
    "MBTieBreak",
    "MUSICBRAINZ_WS_BASE",
    "MusicBrainzClient",
    "RECORDING_INCLUDES",
    "RELEASE_INCLUDES",
    "REQUESTS_PER_SECOND",
    "SUBMIT_PATH",
    "USER_AGENT",
    "build_isrc_submission_xml",
    "is_valid_isrc",
    "is_valid_mbid",
    "isrc_error",
    "normalize_isrc",
    "parse_artist",
    "parse_recording",
    "parse_release",
    "resolve_ambiguous_with_mb",
]

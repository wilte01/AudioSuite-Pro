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

Only reads are implemented here; ISRC submission lives in the same module but
is added by Item 2.3 of ``PLAN_feature_expansion.md``.

Changed in 1.2.0: new module — MusicBrainz lookup by MBID, recording ISRCs,
release-level facts, and the MusicBrainz near-tie tie-break
(PLAN_feature_expansion.md D28, D31).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

import requests

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
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._rate_limiter = RateLimiter(1.0 / max(requests_per_second, 0.01))
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": user_agent})
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
    "CONTACT_URL",
    "DEFAULT_TIMEOUT_SECS",
    "MBResult",
    "MBStatus",
    "MBTieBreak",
    "MUSICBRAINZ_WS_BASE",
    "MusicBrainzClient",
    "RECORDING_INCLUDES",
    "RELEASE_INCLUDES",
    "REQUESTS_PER_SECOND",
    "USER_AGENT",
    "is_valid_mbid",
    "parse_artist",
    "parse_recording",
    "parse_release",
    "resolve_ambiguous_with_mb",
]

"""AcoustID web-service client built on ``requests``.

Only the ``lookup`` endpoint is used.  The client is thread-safe — worker
threads share a single instance, and a lock enforces a global request rate
limit upstream of the socket send.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence

import requests

from audio_suite_shared.exceptions import handle_audio_errors

from .exceptions import AcoustidApiError, AcoustidAuthError
from .models import AcoustidRecording, Fingerprint, LookupResult, ReleaseGroup

logger = logging.getLogger(__name__)

ACOUSTID_LOOKUP_URL = "https://api.acoustid.org/v2/lookup"
DEFAULT_META = "recordings releases releasegroups compress sources"
DEFAULT_TIMEOUT_SECS = 30
_MAX_CANDIDATES_PER_LOOKUP = 10
# The v2 lookup endpoint accepts exactly one fingerprint per HTTP request,
# so "batching" below means chunked iteration for progress reporting —
# never multiple fingerprints in one payload.
_LOOKUP_BATCH_SIZE = 5
# MusicBrainz documents that a lookup result whose recording differs from the
# source audio by more than a few seconds is always an error, so candidates
# are accepted only when their reported duration is within this 7-second
# threshold (plus fractional slack for metadata rounding on long tracks).
_MAX_DURATION_DIFF_SECS = 7
_DURATION_DIFF_RATIO = 0.05
# Distinct recordings that share the same underlying audio (an original and a
# remix/cover built from it) can score within a hair of each other — e.g.
# score 0.984 vs 0.947 for the same file.  When the top two candidates are
# within this margin, AcoustID's ranking is not decisive and the file's
# existing artist/title tags break the tie.
_AMBIGUITY_SCORE_GAP = 0.10


class RateLimiter:
    """Sliding-rate limiter for a single shared client instance.

    Threads acquire ``_lock`` before requesting; each call waits until
    ``min_interval`` seconds have elapsed since the previous request in
    that process, then records its own request time.
    """

    def __init__(self, min_interval: float) -> None:
        self._lock = threading.Lock()
        self._min_interval = max(min_interval, 0.0)
        self._last_request_time = 0.0

    def wait_for_slot(self) -> None:
        """Block until this process is allowed to issue its next request."""
        if self._min_interval <= 0.0:
            return
        with self._lock:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request_time = time.monotonic()


class AcoustidClient:
    """Minimal client for the AcoustID ``lookup`` endpoint.

    Args:
        api_key: AcoustID API key (or ``appkey``).  Required.
        min_score: Drop candidates scoring below this value (0.0-1.0).
        requests_per_second: Max lookup rate per client instance.
        timeout: HTTP timeout in seconds.

    Raises:
        AcoustidAuthError: On HTTP 401, or HTTP 400 answered with an
            "invalid API key" body (points the caller at
            https://acoustid.org/my-applications).
        AcoustidApiError: On other HTTP failures, network errors, or
            malformed responses.  HTTP 400 messages from the service are
            echoed into the exception text so the caller can see the
            rejected parameter.
    """

    def __init__(
        self,
        api_key: str,
        *,
        min_score: float = 0.5,
        requests_per_second: float = 1.0,
        timeout: int = DEFAULT_TIMEOUT_SECS,
    ) -> None:
        self._api_key = api_key
        self._min_score = min_score
        self._timeout = timeout
        self._rate_limiter = RateLimiter(1.0 / max(requests_per_second, 0.01))
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": "audio_suite_pro/1.0 (AudioSuite-Pro)"}
        )

    @handle_audio_errors(reraise=True, context="acoustid_lookup")
    def lookup(self, fingerprint: str, duration: int) -> LookupResult:
        """Fingerprint the file with the AcoustID service.

        Args:
            fingerprint: Chromaprint string produced by fpcalc.
            duration: File duration in whole seconds (fpcalc DURATION).

        Returns:
            A ``LookupResult`` whose recordings are ordered best first and
            filtered to ``min_score`` and to candidates whose reported
            length is consistent with ``duration``.

        Raises:
            AcoustidAuthError: If the API key was rejected (HTTP 401).
            AcoustidApiError: For any other transport or protocol failure.
        """
        self._rate_limiter.wait_for_slot()
        try:
            response = self._session.post(
                ACOUSTID_LOOKUP_URL,
                data={
                    "client": self._api_key,
                    "format": "json",
                    "fingerprint": fingerprint,
                    "duration": max(int(duration), 0),
                    "meta": DEFAULT_META,
                },
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.error("AcoustID request failed: %s", exc, exc_info=True)
            raise AcoustidApiError(
                f"AcoustID request failed: {exc}",
                original=exc,
            ) from exc

        if response.status_code == 401 or (
            response.status_code == 400 and _is_api_key_error(response)
        ):
            detail = _service_error_message(response).strip()
            raise AcoustidAuthError(
                "AcoustID rejected the application API key "
                f"(HTTP {response.status_code})."
                + (f"  Service message: {detail}" if detail else "")
                + " Register or inspect your application key at "
                "https://acoustid.org/my-applications "
                "(the key on https://acoustid.org/api-key is the per-user "
                "key, only valid for fingerprint submission).",
                context={
                    "status_code": response.status_code,
                    **({"service_message": detail} if detail else {}),
                },
            )
        if response.status_code != 200:
            detail = _service_error_message(response)
            raise AcoustidApiError(
                f"AcoustID returned HTTP {response.status_code}."
                + (f"  {detail}" if detail else ""),
                context={
                    "status_code": response.status_code,
                    **({"service_message": detail} if detail else {}),
                },
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AcoustidApiError(
                "AcoustID returned a non-JSON response.",
                original=exc,
            ) from exc

        return self._parse_payload(payload, duration)

    def lookup_many(
        self,
        fingerprints: Sequence[Fingerprint],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[LookupResult]:
        """Look up many fingerprints in input order, honouring the rate limit.

        Used by album match mode, which needs every folder's lookups in
        hand before clustering can decide.  Iteration is chunked into
        batches of ``_LOOKUP_BATCH_SIZE`` purely so progress can be
        reported between chunks — each fingerprint still issues exactly
        one rate-limited request through ``lookup`` (the v2 endpoint
        accepts one fingerprint per request).

        Args:
            fingerprints: Fingerprints to look up, in the desired result
                order.
            on_progress: Optional callback(done, total) invoked after each
                batch completes.

        Returns:
            Results aligned with ``fingerprints`` by position.

        Raises:
            AcoustidAuthError: Propagated from the first lookup that
                rejects the API key — a rejected key fails every
                request, so the caller should abort instead of issuing
                doomed lookups.
        """
        results: list[LookupResult] = []
        total = len(fingerprints)
        for start in range(0, total, _LOOKUP_BATCH_SIZE):
            for fingerprint in fingerprints[start : start + _LOOKUP_BATCH_SIZE]:
                try:
                    results.append(
                        self.lookup(fingerprint.fingerprint, int(fingerprint.duration))
                    )
                except AcoustidApiError as exc:
                    # Transport/protocol failures are per-file conditions
                    # (mirroring the per-file worker path); the run
                    # continues with the remaining fingerprints.
                    logger.warning("Album-mode lookup failed for one file: %s", exc)
                    results.append(LookupResult(status="error", error=str(exc)))
            if on_progress is not None:
                on_progress(min(start + _LOOKUP_BATCH_SIZE, total), total)
        return results

    def _parse_payload(self, payload: object, duration: int) -> LookupResult:
        """Decode the lookup JSON into a ``LookupResult``."""
        if not isinstance(payload, dict):
            raise AcoustidApiError("AcoustID returned an unexpected payload.")

        status: object = payload.get("status")
        if status == "error":
            return LookupResult(
                status="error",
                error=_extract_error_text(payload),
            )
        if status != "ok":
            raise AcoustidApiError(
                f"AcoustID returned unknown status {status!r}.",
                context={"status": status},
            )

        results_raw = payload.get("results", [])
        if not isinstance(results_raw, list):
            raise AcoustidApiError("AcoustID 'results' field is not a list.")

        recordings: list[AcoustidRecording] = []
        seen_ids: set[str] = set()
        for result in results_raw:
            if not isinstance(result, dict):
                continue
            try:
                score = float(result.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            if score < self._min_score:
                continue
            acoustid_id = str(result.get("id", ""))
            result_recordings = result.get("recordings", [])
            if not isinstance(result_recordings, list):
                continue
            for rec in result_recordings:
                if not isinstance(rec, dict):
                    continue
                recording = _build_recording(rec, acoustid_id, score)
                if recording is None or recording.recording_id in seen_ids:
                    continue
                if not _duration_consistent(recording.duration, duration):
                    continue
                seen_ids.add(recording.recording_id)
                recordings.append(recording)
            if len(recordings) >= _MAX_CANDIDATES_PER_LOOKUP:
                break

        if not recordings:
            return LookupResult(status="no results", recordings=())

        recordings.sort(key=lambda r: r.score, reverse=True)
        return LookupResult(status="ok", recordings=tuple(recordings))


def _extract_error_text(payload: dict[str, object]) -> str:
    """Best-effort extraction of the service error message."""
    error = payload.get("error")
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message
    return str(error) if error is not None else ""


def _service_error_message(response: requests.Response) -> str:
    """Extract the `error.message` dict from a non-2xx AcoustID response.

    The web service returns failures as
    ``{"status": "error", "error": {"message": "...", "code": N}}``;
    older clients also received a bare string or ``error: {message: ...}``.
    """
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    message = _extract_error_text(payload)
    return message[:300]


def _is_api_key_error(response: requests.Response) -> bool:
    """Match AcoustID's HTTP-400-with-message form of an invalid key.

    Invalid client keys are normally answered with HTTP 401, but the service
    has historically served *blocked* application keys as HTTP 400 with an
    "invalid API key" message body instead.
    """
    message = _service_error_message(response).lower()
    return "api" in message and "key" in message


def _build_release_groups(rec: dict[str, object]) -> tuple[ReleaseGroup, ...]:
    """Collect the MusicBrainz release groups a recording appears on.

    With ``meta=releases releasegroups`` the service nests the groups
    under each release (``recordings[].releases[].releasegroups[]``).
    Entries are deduplicated by id and malformed links are skipped —
    release metadata is an optional enrichment, never a hard requirement.
    """
    releases = rec.get("releases")
    if not isinstance(releases, list):
        return ()
    groups: list[ReleaseGroup] = []
    seen: set[str] = set()
    for release in releases:
        if not isinstance(release, dict):
            continue
        raw_groups = release.get("releasegroups")
        if not isinstance(raw_groups, list):
            continue
        for group in raw_groups:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("id", "") or "")
            if not group_id or group_id in seen:
                continue
            seen.add(group_id)
            groups.append(
                ReleaseGroup(
                    release_group_id=group_id,
                    title=str(group.get("title", "") or ""),
                )
            )
    return tuple(groups)


def _build_recording(
    rec: dict[str, object],
    acoustid_id: str,
    score: float,
) -> AcoustidRecording | None:
    """Convert a raw recording dict into a model, skipping untiled entries."""
    recording_id = str(rec.get("id", ""))
    if not recording_id:
        return None

    title = str(rec.get("title", "") or "")
    artist = _join_artists(rec.get("artists"))
    duration = rec.get("duration")
    duration_int: int | None = None
    if isinstance(duration, (int, float)):
        duration_int = int(duration)

    return AcoustidRecording(
        acoustid_id=acoustid_id,
        recording_id=recording_id,
        title=title,
        artist=artist,
        score=score,
        duration=duration_int,
        release_groups=_build_release_groups(rec),
    )


def _normalize_tag_text(value: str) -> str:
    """Collapse a tag or candidate string to a punctuation-insensitive key.

    Titles frequently differ from the MusicBrainz spelling only by
    punctuation or casing (``Johnny, Don't Do It`` vs ``Johnny, Don't Do
    It``), so only alphanumeric characters survive the comparison.
    """
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def resolve_best_match(
    recordings: tuple[AcoustidRecording, ...],
    artist_tag: str,
    title_tag: str,
) -> tuple[AcoustidRecording | None, bool, bool]:
    """Pick the best candidate, breaking near-ties with the file's tags.

    AcoustID orders recordings by score, but distinct recordings that share
    the same underlying audio (an original and a remix built on it) can score
    neck-and-neck — the analysed fingerprint window does not distinguish
    them.  When the top two scores are inside ``_AMBIGUITY_SCORE_GAP`` the
    candidate whose artist and title agree with the file's existing tags is
    preferred; otherwise the rank order is kept.

    Args:
        recordings:  Candidates sorted by score (best first), already
                     duration-consistent with the file.
        artist_tag:  Existing artist tag of the file (``''``/``'Unknown'``
                     when absent).
        title_tag:   Existing title tag of the file.

    Returns:
        Tuple ``(best, ambiguous, tag_resolved)``:
            *best* is the chosen recording (``None`` when the list is empty),
            *ambiguous* is True when the top two scores were within
            ``_AMBIGUITY_SCORE_GAP``, and *tag_resolved* is True when that
            ambiguity was settled by the file tags.
    """
    if not recordings:
        return None, False, False
    if len(recordings) == 1:
        return recordings[0], False, False

    top = recordings[0]
    ambiguous = (top.score - recordings[1].score) < _AMBIGUITY_SCORE_GAP
    if not ambiguous:
        return top, False, False

    file_artist = _normalize_tag_text(artist_tag)
    file_title = _normalize_tag_text(title_tag)
    if file_artist and file_title:
        for recording in recordings:
            if (top.score - recording.score) >= _AMBIGUITY_SCORE_GAP:
                break
            if _normalize_tag_text(recording.artist) == file_artist and (
                _normalize_tag_text(recording.title) == file_title
            ):
                return recording, True, True
    return top, True, False


def _duration_consistent(recording_duration: int | None, file_duration: int) -> bool:
    """Reject candidates whose reported length disagrees with the file's.

    MusicBrainz documents that a lookup result whose recording differs from
    the source audio by more than a few seconds always indicates an error, so
    a candidate is only accepted when its duration is within
    ``_MAX_DURATION_DIFF_SECS`` of the file, with proportional slack for
    rounding on longer files.  Candidates that report no duration are allowed
    through.
    """
    if recording_duration is None or recording_duration <= 0 or file_duration <= 0:
        return True
    difference = abs(recording_duration - file_duration)
    return difference <= max(
        _MAX_DURATION_DIFF_SECS, _DURATION_DIFF_RATIO * file_duration
    )


def _join_artists(raw_artists: object) -> str:
    """Join an AcoustID artists array honouring ``joinphrase`` values.

    Each artist entry carries a ``joinphrase`` rendered *after* that
    artist's name and before the next artist (MusicBrainz convention); the
    final entry typically carries an empty joinphrase.
    """
    if not isinstance(raw_artists, list):
        return ""
    parts: list[str] = []
    for artist in raw_artists:
        if not isinstance(artist, dict):
            continue
        name = str(artist.get("name", "") or "")
        if not name:
            continue
        parts.append(name)
        joinphrase = str(artist.get("joinphrase", "") or "")
        if joinphrase:
            parts.append(joinphrase)
    return "".join(parts)

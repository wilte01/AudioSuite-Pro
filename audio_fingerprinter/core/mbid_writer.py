"""Selection of the MusicBrainz identifiers to write, and the tag write itself.

Changed in 1.2.0: adds ``selected_release_id`` so the MusicBrainz enrichment
fetches facts for the same release the tag writer selects
(PLAN_feature_expansion.md D31).

E2 decision D2-am1: ``MUSICBRAINZ_TRACKID`` and ``MUSICBRAINZ_ARTISTID`` come
straight from the AcoustID response.  ``MUSICBRAINZ_ALBUMID`` cannot — a
recording is typically released many times (one sampled M83 track spans 12
releases across 3 release groups) and no MusicBrainz release lookup is permitted
to choose between them.  :func:`select_mbid_tags` therefore narrows the
candidates with the agreed criteria and returns an id **only when exactly one
survives**; otherwise the field is omitted rather than guessed.
"""

from __future__ import annotations

import logging
import os
import unicodedata

from audio_suite_shared.exceptions import (
    AudioSuiteError,
    handle_audio_errors,
)
from audio_suite_shared.tag_helper_writer import (
    write_musicbrainz_ids as _write_musicbrainz_ids,
)

from .models import AcoustidRecording, Release

logger = logging.getLogger(__name__)

TRACKID_TAG = "MUSICBRAINZ_TRACKID"
ALBUMID_TAG = "MUSICBRAINZ_ALBUMID"
ARTISTID_TAG = "MUSICBRAINZ_ARTISTID"

RECOVERY_CHARS = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'"})


def normalize_title(value: str) -> str:
    """Fold a title for comparison: case, punctuation, accents, whitespace.

    MusicBrainz uses a typographic apostrophe where a local tag usually has an
    ASCII one, and release titles differ from album tags by punctuation far more
    often than by wording.  Comparing the folded forms avoids failing a match
    the user would consider exact.  Shared by the per-file near-tie break
    (``resolve_best_match``), the release selection (D2-am1) and the
    album-cluster tie-break so every title comparison in the tool folds the
    same way.
    """
    folded = unicodedata.normalize("NFKD", value.translate(RECOVERY_CHARS))
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    kept = [ch.lower() for ch in stripped if ch.isalnum() or ch.isspace()]
    return " ".join("".join(kept).split())


def _album_disc_count(file_path: str) -> int | None:
    """Count distinct disc values among the sibling files of ``file_path``.

    Only meaningful in album match mode, where a folder holds one album; a
    single-file run cannot infer a disc count and returns None.
    """
    folder = os.path.dirname(file_path)
    try:
        siblings = os.listdir(folder)
    except OSError:
        return None
    discs: set[str] = set()
    for name in siblings:
        if not name.lower().endswith((".mp3", ".flac", ".ogg", ".opus", ".m4a")):
            continue
        try:
            from audio_suite_shared.tag_helper_reader import read_disc_number

            disc = read_disc_number(os.path.join(folder, name))
        except (OSError, AudioSuiteError):
            continue
        if disc:
            discs.add(disc)
    return len(discs) if discs else None


def select_mbid_tags(
    recording: AcoustidRecording,
    album_title: str = "",
    file_path: str = "",
    region: str = "",
) -> dict[str, str]:
    """Choose the MusicBrainz tags to write for one matched recording.

    Applies the D2-am1 criteria in order, each one acting as a filter that is
    skipped when the local signal is unavailable:

    1. the file's existing ``MUSICBRAINZ_ALBUMID``, when it names a candidate;
    2. the album title against each release / release-group title;
    3. the album's track count against the release's ``track_count``;
    4. the album's disc count against the release's ``medium_count``;
    5. the release-group primary type.

    A criterion that would eliminate *every* candidate is ignored rather than
    emptying the set, so an uninformative signal never suppresses the field.

    Args:
        recording: The matched AcoustID candidate.
        album_title: The file's existing album tag, when readable.
        file_path: Path to the audio file, used to infer the album's track
            and disc counts and to read an existing ``MUSICBRAINZ_ALBUMID``.
        region: Preferred release country (ISO 3166-1 alpha-2). Empty means no
            preference; it is only ever a tie-break between candidates that are
            otherwise indistinguishable.

    Returns:
        Mapping of tag name to MBID.  ``MUSICBRAINZ_TRACKID`` and
        ``MUSICBRAINZ_ARTISTID`` are always present when the service reported
        them; ``MUSICBRAINZ_ALBUMID`` appears only when exactly one release
        candidate survives.
    """
    tags: dict[str, str] = {}
    if recording.recording_id:
        tags[TRACKID_TAG] = recording.recording_id
    if recording.artist_ids:
        tags[ARTISTID_TAG] = recording.artist_ids[0]

    release_id = _select_release_id(recording, album_title, file_path, region)
    if release_id:
        tags[ALBUMID_TAG] = release_id
    elif recording.releases:
        logger.debug(
            "No unambiguous release for recording %s (%d candidates); omitting %s.",
            recording.recording_id,
            len(recording.releases),
            ALBUMID_TAG,
        )
    return tags


def selected_release_id(
    recording: AcoustidRecording,
    album_title: str = "",
    file_path: str = "",
    region: str = "",
) -> str:
    """Return the release MBID this recording's tags would select, if any.

    Public wrapper over the D2-am1 selection so the MusicBrainz enrichment can
    fetch release-level facts for exactly the release the tag writer would
    name — the two must never disagree about which edition a file is on.

    Args:
        recording: The matched AcoustID candidate.
        album_title: The file's existing album tag, when readable.
        file_path: Path to the audio file (track/disc count and existing
            ``MUSICBRAINZ_ALBUMID``).
        region: Preferred release country, used only as a last-resort tie-break.

    Returns:
        The single surviving release MBID, or ``""`` when none or several
        candidates survive.
    """
    return _select_release_id(recording, album_title, file_path, region)


def _select_release_id(
    recording: AcoustidRecording,
    album_title: str,
    file_path: str,
    region: str = "",
) -> str:
    """Return the single surviving release MBID, or empty when ambiguous.

    Each criterion is applied only while more than one candidate survives, and
    one that would eliminate every candidate is skipped rather than emptying
    the set. The region preference is likewise a last-resort tie-break: it can
    never select a release on its own.
    """
    candidates = list(recording.releases)
    if not candidates:
        return ""

    existing = _existing_album_id(file_path)
    if existing:
        for candidate in candidates:
            if candidate.release_id == existing:
                return existing

    for narrow in (
        lambda c: _narrow_by_title(c, album_title),
        lambda c: _narrow_by_counts(c, file_path),
        _narrow_by_type,
        lambda c: _narrow_by_region(c, region),
    ):
        narrowed = narrow(candidates)
        if len(narrowed) == 1:
            return narrowed[0].release_id
        if 0 < len(narrowed) < len(candidates):
            candidates = narrowed

    # Still tied: an arbitrary pick would write a release the file may not be
    # on, which is worse than omitting the tag.
    return ""


def _existing_album_id(file_path: str) -> str:
    """Read an existing ``MUSICBRAINZ_ALBUMID`` from the file, if any."""
    if not file_path:
        return ""
    try:
        from audio_suite_shared.tag_helper_reader import read_musicbrainz_ids

        return read_musicbrainz_ids(file_path).get(ALBUMID_TAG, "") or ""
    except (OSError, AudioSuiteError):
        return ""


def _narrow_by_title(candidates: list[Release], album_title: str) -> list[Release]:
    """Keep candidates whose release or release-group title matches the album."""
    target = normalize_title(album_title)
    if not target:
        return candidates
    matched = [
        candidate
        for candidate in candidates
        if target
        in {
            normalize_title(candidate.release_group_title),
            normalize_title(candidate.title),
        }
    ]
    return matched or candidates


def _narrow_by_counts(candidates: list[Release], file_path: str) -> list[Release]:
    """Keep candidates whose track/disc counts match the local album.

    A candidate that reported no count is never excluded on that basis —
    MusicBrainz coverage is patchy, and a missing ``track_count`` says nothing
    about which release the file is on.
    """
    if not file_path:
        return candidates

    siblings = _sibling_audio_files(file_path)
    if siblings:
        by_track_count = [
            candidate
            for candidate in candidates
            if candidate.track_count is None or candidate.track_count == len(siblings)
        ]
        if 0 < len(by_track_count) < len(candidates):
            candidates = by_track_count

    disc_count = _album_disc_count(file_path)
    if disc_count is not None:
        by_disc_count = [
            candidate
            for candidate in candidates
            if candidate.medium_count is None or candidate.medium_count == disc_count
        ]
        if 0 < len(by_disc_count) < len(candidates):
            candidates = by_disc_count

    return candidates


def _sibling_audio_files(file_path: str) -> list[str]:
    """List the audio files sharing a folder with ``file_path``."""
    folder = os.path.dirname(file_path)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return [
        os.path.join(folder, name)
        for name in names
        if name.lower().endswith((".mp3", ".flac", ".ogg", ".opus", ".m4a"))
    ]


def _narrow_by_type(candidates: list[Release]) -> list[Release]:
    """Prefer full-length release-group types when they discriminate."""
    preferred = ("album", "compilation", "ep")
    matched = [
        candidate
        for candidate in candidates
        if candidate.release_group_type.lower() in preferred
    ]
    return matched or candidates


def _narrow_by_region(candidates: list[Release], region: str) -> list[Release]:
    """Prefer releases issued in the user's region when they discriminate.

    A region preference resolves editions that differ *only* by country (the
    FR / US / AU editions of one album all share a track count, disc count and
    release group). Releases carrying no country information are kept, so an
    incomplete response is not silently discarded.
    """
    target = region.strip().upper()
    if not target:
        return candidates
    matched = [candidate for candidate in candidates if target in candidate.countries]
    unknown = [candidate for candidate in candidates if not candidate.countries]
    preferred = matched + unknown
    return preferred or candidates


@handle_audio_errors(reraise=False, context="mbid_tag_write")
def write_mbid_tags(file_path: str, tags: dict[str, str]) -> tuple[bool, str]:
    """Write the selected MusicBrainz identifiers to a file.

    Args:
        file_path: Path to the audio file.
        tags: Mapping of canonical MBID tag name to MBID, as returned by
            :func:`select_mbid_tags`.

    Returns:
        A ``(ok, message)`` tuple.  ``ok`` is False when the write fails;
        the message then carries the error text.
    """
    if not tags:
        return True, "No MusicBrainz identifiers to write."
    try:
        _write_musicbrainz_ids(file_path, tags)
    except AudioSuiteError as exc:
        # Catch the mapped-error base: the shared layer does not always
        # produce the AudioTagError subclass, and anything escaping to the
        # decorator would be swallowed into None — breaking the tuple
        # contract at every call site.
        logger.warning("MusicBrainz tag write failed for %s: %s", file_path, exc)
        return False, str(exc)
    written = ", ".join(sorted(tags))
    return True, f"MusicBrainz identifiers written: {written}."

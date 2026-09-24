"""Album-level clustering of AcoustID lookups by MusicBrainz release group.

Per-file matching ranks candidates by AcoustID score alone, so a remix
built on an original's recording can out-score the original; the only
per-file defence is the tag-aware near-tie break in
``resolve_best_match``.  Album clustering adds *cross-file* evidence:
when enough files in one folder resolve to candidates sharing a
MusicBrainz release group, that consensus decides the folder's
ambiguous files too — the core of Picard-style album matching.

Clustering only ever *adds* evidence.  The per-file score/duration
guardrails and the tag-aware tie-break stay in force, and every file
that no decided cluster claims falls back to exactly today's per-file
matching.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass

from .acoustid_client import resolve_best_match
from .models import AcoustidRecording

logger = logging.getLogger(__name__)

DEFAULT_CLUSTER_MIN_FILES = 3
# A cluster is only decided when its score leads the runner-up by this
# relative margin; a closer tie means the album evidence itself is
# ambiguous and the files are left untagged with the runner-up surfaced.
CLUSTER_DECISION_MARGIN = 0.25


@dataclass(frozen=True)
class AlbumFile:
    """Clustering input for one fingerprinted file.

    Attributes:
        file_path: Absolute path of the file.
        folder_path: Folder the file lives in (one album candidate).
        fingerprint: Chromaprint string (carried for the tag write).
        duration: fpcalc-reported file duration.
        artist_tag: Existing artist tag of the file (``''``/``'Unknown'``
            when absent) — used by the per-file fallback tie-break.
        title_tag: Existing title tag of the file.
        recordings: Duration- and score-filtered candidates, best first.
    """

    file_path: str
    folder_path: str
    fingerprint: str
    duration: float
    artist_tag: str
    title_tag: str
    recordings: tuple[AcoustidRecording, ...]


@dataclass(frozen=True)
class ReleaseGroupCluster:
    """A MusicBrainz release group voted for by the files of one folder.

    Attributes:
        release_group_id: MusicBrainz release-group MBID.
        title: Best release-group title seen among the voting candidates.
        file_count: Number of files with at least one candidate in this
            release group.
        avg_score: Mean of the voting files' best candidate scores.
        score: Cluster score — ``file_count * avg_score`` — the
            files-voting weight times the per-file confidence.
    """

    release_group_id: str
    title: str
    file_count: int
    avg_score: float
    score: float


@dataclass(frozen=True)
class AlbumFileDecision:
    """Clustering outcome for one file.

    Attributes:
        outcome: ``"cluster"`` when a decided album chose the file's
            candidate, ``"ambiguous"`` when the album's clusters tie (the
            file is left untagged, runner-up surfaced), or ``"fallback"``
            when no decided cluster claims the file (today's per-file
            matching applies).
        best: Chosen recording.  For ``"cluster"``: the file's best
            candidate inside the winning release group.  For
            ``"fallback"``: the ``resolve_best_match`` result (``None``
            when no candidate survives, i.e. NO MATCH).
        ambiguous: Per-file near-tie flag from ``resolve_best_match``
            (fallback outcome only).
        tag_resolved: Per-file tag tie-break flag (fallback outcome only).
        cluster_title: Winning release-group title (cluster outcome) or
            the runner-up surface text (ambiguous outcome); empty
            otherwise.
    """

    outcome: str
    best: AcoustidRecording | None
    ambiguous: bool = False
    tag_resolved: bool = False
    cluster_title: str = ""


@dataclass(frozen=True)
class AlbumResolution:
    """Clustering outcome for one folder (album).

    Attributes:
        folder_path: The folder the resolution covers.
        status: ``"decided"`` when one cluster won by the margin,
            ``"ambiguous"`` when clusters tie inside the margin, or
            ``"no cluster"`` when no release group reached the minimum.
        winner: Top cluster (``None`` when no cluster formed).
        runner_up: Second cluster (``None`` when absent).
        decisions: Outcomes aligned with the input files by position.
        report_line: One-line album summary for the run report.
    """

    folder_path: str
    status: str
    winner: ReleaseGroupCluster | None
    runner_up: ReleaseGroupCluster | None
    decisions: tuple[AlbumFileDecision, ...]
    report_line: str


def group_albums(files: Sequence[AlbumFile]) -> dict[str, list[AlbumFile]]:
    """Group clustering inputs by their folder, preserving input order."""
    albums: dict[str, list[AlbumFile]] = {}
    for file in files:
        albums.setdefault(file.folder_path, []).append(file)
    return albums


def _build_clusters(
    files: Sequence[AlbumFile],
) -> tuple[list[ReleaseGroupCluster], dict[str, dict[int, float]], dict[str, str]]:
    """Map each release group to its voting files, best score, and title.

    Returns:
        Tuple ``(clusters_in_score_order, votes, titles)`` where *votes*
        maps release-group id → file index → that file's best candidate
        score in the group, and *titles* maps release-group id → the
        first title reported for the group (candidates arrive best
        first, so the strongest candidate's title wins).
    """
    votes: dict[str, dict[int, float]] = {}
    titles: dict[str, str] = {}
    for idx, file in enumerate(files):
        for recording in file.recordings:
            for group in recording.release_groups:
                group_id = group.release_group_id
                per_file = votes.setdefault(group_id, {})
                if recording.score > per_file.get(idx, -1.0):
                    per_file[idx] = recording.score
                if not titles.get(group_id) and group.title:
                    titles[group_id] = group.title

    clusters: list[ReleaseGroupCluster] = []
    for group_id, per_file in votes.items():
        file_count = len(per_file)
        avg_score = sum(per_file.values()) / file_count
        clusters.append(
            ReleaseGroupCluster(
                release_group_id=group_id,
                title=titles.get(group_id, ""),
                file_count=file_count,
                avg_score=avg_score,
                score=file_count * avg_score,
            )
        )
    clusters.sort(key=lambda c: (-c.score, c.release_group_id))
    return clusters, votes, titles


def _best_recording_in_group(
    file: AlbumFile, group_id: str
) -> AcoustidRecording | None:
    """Return the file's highest-scoring candidate inside a release group."""
    best: AcoustidRecording | None = None
    for recording in file.recordings:
        if any(g.release_group_id == group_id for g in recording.release_groups):
            if best is None or recording.score > best.score:
                best = recording
    return best


def _report_line(
    folder_path: str,
    status: str,
    winner: ReleaseGroupCluster | None,
    runner_up: ReleaseGroupCluster | None,
    album_min: int,
) -> str:
    """Build the one-line album summary for the run report."""
    label = os.path.basename(folder_path) or folder_path
    if status == "decided" and winner is not None:
        return (
            f"[ALBUM] {label}: decided — {winner.title or winner.release_group_id} "
            f"({winner.file_count} files, avg score {winner.avg_score:.2f})"
        )
    if status == "ambiguous" and winner is not None and runner_up is not None:
        return (
            f"[ALBUM] {label}: ambiguous — "
            f"{winner.title or winner.release_group_id} (score {winner.score:.2f}) vs "
            f"{runner_up.title or runner_up.release_group_id} "
            f"(score {runner_up.score:.2f}); files left untagged"
        )
    return f"[ALBUM] {label}: no release group reached the {album_min}-file minimum"


def resolve_album(files: Sequence[AlbumFile], album_min: int) -> AlbumResolution:
    """Cluster one folder's lookups and decide every file.

    A release group forms a cluster when at least ``album_min`` files
    carry a candidate in it.  Clusters are scored by (files voting) x
    (average per-file confidence); the top cluster is *decided* only
    when it leads the runner-up by ``CLUSTER_DECISION_MARGIN``, otherwise
    the tie is surfaced and the voting files are left untagged.  Files
    no decided cluster claims always fall back to per-file matching.

    Args:
        files: The folder's fingerprinted files with their candidates.
        album_min: Minimum files voting for one release group before a
            cluster can form (values below 1 are treated as 1).

    Returns:
        An ``AlbumResolution`` with per-file decisions aligned with
        ``files`` by position, plus the report line.
    """
    album_min = max(album_min, 1)
    clusters, votes, _titles = _build_clusters(files)
    formed = [c for c in clusters if c.file_count >= album_min]

    winner: ReleaseGroupCluster | None = None
    runner_up: ReleaseGroupCluster | None = None
    status = "no cluster"
    if formed:
        winner = formed[0]
        runner_up = formed[1] if len(formed) > 1 else None
        decisively_ahead = runner_up is None or (
            winner.score >= runner_up.score * (1.0 + CLUSTER_DECISION_MARGIN)
        )
        status = "decided" if decisively_ahead else "ambiguous"
    else:
        logger.debug(
            "No album cluster formed for %d files (min %d)",
            len(files),
            album_min,
        )

    decisions: list[AlbumFileDecision] = []
    for file in files:
        if status == "decided" and winner is not None:
            clustered = _best_recording_in_group(file, winner.release_group_id)
            if clustered is not None:
                decisions.append(
                    AlbumFileDecision(
                        outcome="cluster",
                        best=clustered,
                        cluster_title=winner.title or winner.release_group_id,
                    )
                )
                continue
        if status == "ambiguous" and winner is not None and runner_up is not None:
            voted_ids = {
                group.release_group_id
                for recording in file.recordings
                for group in recording.release_groups
            }
            if (
                winner.release_group_id in voted_ids
                or runner_up.release_group_id in voted_ids
            ):
                decisions.append(
                    AlbumFileDecision(
                        outcome="ambiguous",
                        best=None,
                        cluster_title=(
                            f"{winner.title or winner.release_group_id} vs "
                            f"{runner_up.title or runner_up.release_group_id}"
                        ),
                    )
                )
                continue
        best, ambiguous, tag_resolved = resolve_best_match(
            file.recordings, file.artist_tag, file.title_tag
        )
        decisions.append(
            AlbumFileDecision(
                outcome="fallback",
                best=best,
                ambiguous=ambiguous,
                tag_resolved=tag_resolved,
            )
        )

    return AlbumResolution(
        folder_path=files[0].folder_path if files else "",
        status=status,
        winner=winner,
        runner_up=runner_up,
        decisions=tuple(decisions),
        report_line=_report_line(
            files[0].folder_path if files else "",
            status,
            winner,
            runner_up,
            album_min,
        ),
    )


__all__ = [
    "AlbumFile",
    "AlbumFileDecision",
    "AlbumResolution",
    "CLUSTER_DECISION_MARGIN",
    "DEFAULT_CLUSTER_MIN_FILES",
    "ReleaseGroupCluster",
    "group_albums",
    "resolve_album",
]

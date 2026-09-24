"""Tests for audio_fingerprinter.core.album_cluster."""

from __future__ import annotations

from audio_fingerprinter.core.album_cluster import (
    CLUSTER_DECISION_MARGIN,
    AlbumFile,
    group_albums,
    resolve_album,
)
from audio_fingerprinter.core.models import AcoustidRecording, ReleaseGroup

_FOLDER = "/music/album"


def _rec(
    recording_id: str,
    score: float,
    groups: tuple[ReleaseGroup, ...] = (),
    title: str = "Song",
    artist: str = "Artist",
) -> AcoustidRecording:
    return AcoustidRecording(
        acoustid_id=f"ac-{recording_id}",
        recording_id=recording_id,
        title=title,
        artist=artist,
        score=score,
        duration=218,
        release_groups=groups,
    )


def _file(
    name: str,
    recordings: tuple[AcoustidRecording, ...],
    artist_tag: str = "",
    title_tag: str = "",
    folder: str = _FOLDER,
) -> AlbumFile:
    return AlbumFile(
        file_path=f"{folder}/{name}",
        folder_path=folder,
        fingerprint=f"fp-{name}",
        duration=218.0,
        artist_tag=artist_tag,
        title_tag=title_tag,
        recordings=recordings,
    )


def _album_rg() -> ReleaseGroup:
    return ReleaseGroup("rg-album", "The Album")


def _other_rg() -> ReleaseGroup:
    return ReleaseGroup("rg-other", "Other Album")


class TestGroupAlbums:
    def test_groups_by_folder_preserving_order(self):
        a = _file("a.mp3", (), folder="/x")
        b = _file("b.mp3", (), folder="/y")
        c = _file("c.mp3", (), folder="/x")
        albums = group_albums([a, b, c])
        assert list(albums.keys()) == ["/x", "/y"]
        assert albums["/x"] == [a, c]
        assert albums["/y"] == [b]


class TestDecidedCluster:
    def test_majority_album_decides_ambiguous_files(self):
        """The album-mode value case: a remix out-scores the original on
        one file, but the folder consensus pulls the file to the album's
        release group."""
        album = _album_rg()
        files = [
            # Three clear votes for rg-album.
            _file(f"t{i}.mp3", (_rec(f"mb-{i}", 0.93, (album,)),))
            for i in range(3)
        ]
        # Fourth file: the remix candidate scores higher but belongs to a
        # different release group; the album candidate is the runner-up.
        files.append(
            _file(
                "t3.mp3",
                (
                    _rec("mb-remix", 0.984, (_other_rg(),), title="Remix"),
                    _rec("mb-orig", 0.947, (album,), title="Original"),
                ),
            )
        )
        resolution = resolve_album(files, album_min=3)
        assert resolution.status == "decided"
        assert resolution.winner is not None
        assert resolution.winner.release_group_id == "rg-album"
        assert resolution.winner.file_count == 4
        assert all(d.outcome == "cluster" for d in resolution.decisions)
        pulled = resolution.decisions[3]
        assert pulled.best is not None
        assert pulled.best.recording_id == "mb-orig"
        assert "decided" in resolution.report_line
        assert "The Album" in resolution.report_line

    def test_file_outside_winning_cluster_falls_back(self):
        """A file whose candidates point at another release group is not
        claimed by the decided cluster — it falls back to per-file
        matching."""
        album = _album_rg()
        files = [
            _file(f"t{i}.mp3", (_rec(f"mb-{i}", 0.9, (album,)),)) for i in range(3)
        ]
        stranger = _rec("mb-x", 0.95, (_other_rg(),), title="Stranger")
        files.append(_file("t9.mp3", (stranger,)))
        resolution = resolve_album(files, album_min=3)
        assert resolution.status == "decided"
        outcomes = [d.outcome for d in resolution.decisions]
        assert outcomes == ["cluster", "cluster", "cluster", "fallback"]
        assert resolution.decisions[3].best is stranger

    def test_single_cluster_with_min_votes_is_decided(self):
        album = _album_rg()
        files = [
            _file(f"t{i}.mp3", (_rec(f"mb-{i}", 0.8, (album,)),)) for i in range(3)
        ]
        resolution = resolve_album(files, album_min=3)
        assert resolution.status == "decided"
        assert resolution.runner_up is None

    def test_album_min_parameter_controls_formation(self):
        album = _album_rg()
        files = [
            _file(f"t{i}.mp3", (_rec(f"mb-{i}", 0.9, (album,)),)) for i in range(2)
        ]
        assert resolve_album(files, album_min=3).status == "no cluster"
        assert resolve_album(files, album_min=2).status == "decided"

    def test_album_min_below_one_is_treated_as_one(self):
        album = _album_rg()
        files = [_file("t0.mp3", (_rec("mb-0", 0.9, (album,)),))]
        assert resolve_album(files, album_min=0).status == "decided"


class TestAmbiguousCluster:
    def _tied_albums(self) -> list[object]:
        album, other = _album_rg(), _other_rg()
        return [
            _file(
                f"a{i}.mp3",
                (_rec(f"mb-a{i}", 0.90, (album,), title="A Song"),),
            )
            for i in range(3)
        ] + [
            _file(
                f"b{i}.mp3",
                (_rec(f"mb-b{i}", 0.90, (other,), title="B Song"),),
            )
            for i in range(3)
        ]

    def test_tied_clusters_leave_files_untagged_with_runner_up(self):
        files = self._tied_albums()
        resolution = resolve_album(files, album_min=3)
        assert resolution.status == "ambiguous"
        assert resolution.winner is not None
        assert resolution.runner_up is not None
        for decision in resolution.decisions:
            assert decision.outcome == "ambiguous"
            assert decision.best is None
            assert "vs" in decision.cluster_title
        assert "ambiguous" in resolution.report_line
        assert "left untagged" in resolution.report_line
        # Runner-up convention: both cluster titles surface.
        assert "The Album" in resolution.decisions[0].cluster_title
        assert "Other Album" in resolution.decisions[0].cluster_title

    def test_file_voting_for_neither_tied_cluster_falls_back(self):
        files = self._tied_albums()
        third = ReleaseGroup("rg-third", "Third Album")
        stranger = _rec("mb-z", 0.95, (third,), title="Stranger")
        files.append(_file("z.mp3", (stranger,)))
        resolution = resolve_album(files, album_min=3)
        assert resolution.status == "ambiguous"
        assert resolution.decisions[-1].outcome == "fallback"
        assert resolution.decisions[-1].best is stranger

    def test_margin_boundary_decides(self):
        """Winner at exactly 1 + CLUSTER_DECISION_MARGIN times the
        runner-up is decided; a hair below is ambiguous."""
        album, other = _album_rg(), _other_rg()
        winner_files = [
            _file(f"w{i}.mp3", (_rec(f"mb-w{i}", 0.8, (album,)),)) for i in range(4)
        ]  # score 3.2
        runner_files = [
            _file(f"r{i}.mp3", (_rec(f"mb-r{i}", 0.8533, (other,)),)) for i in range(3)
        ]  # score 2.5599 -> 3.2 / 2.5599 = 1.25004 (just above the margin)
        files = winner_files + runner_files
        resolution = resolve_album(files, album_min=3)
        assert resolution.status == "decided", (
            f"expected decided, got {resolution.status}"
        )

        # Nudge the runner-up closer to flip to ambiguous.
        runner_files = [
            _file(f"r{i}.mp3", (_rec(f"mb-r{i}", 0.86, (other,)),)) for i in range(3)
        ]  # score 2.58 -> ratio 1.2403 (inside the margin)
        resolution = resolve_album(winner_files + runner_files, album_min=3)
        assert resolution.status == "ambiguous"


class TestNoCluster:
    def test_below_minimum_falls_back_to_per_file_matching(self):
        album = _album_rg()
        files = [
            _file(f"t{i}.mp3", (_rec(f"mb-{i}", 0.9, (album,)),)) for i in range(2)
        ]
        resolution = resolve_album(files, album_min=3)
        assert resolution.status == "no cluster"
        assert resolution.winner is None
        for decision in resolution.decisions:
            assert decision.outcome == "fallback"
            assert decision.best is not None

    def test_fallback_resolves_per_file_near_tie_with_tags(self):
        """The per-file tag-aware tie-break stays in force on fallback."""
        album = _album_rg()
        files = [
            _file(f"t{i}.mp3", (_rec(f"mb-{i}", 0.9, (album,)),)) for i in range(2)
        ]
        files.append(
            _file(
                "tie.mp3",
                (
                    _rec(
                        "mb-remix",
                        0.984,
                        (_other_rg(),),
                        title="Remix",
                        artist="Someone",
                    ),
                    _rec(
                        "mb-orig",
                        0.947,
                        (_other_rg(),),
                        title="Original",
                        artist="10cc",
                    ),
                ),
                artist_tag="10cc",
                title_tag="Original",
            )
        )
        resolution = resolve_album(files, album_min=3)
        assert resolution.status == "no cluster"
        tie = resolution.decisions[2]
        assert tie.outcome == "fallback"
        assert tie.best is not None
        assert tie.best.recording_id == "mb-orig"
        assert tie.tag_resolved is True
        assert tie.ambiguous is True

    def test_file_without_candidates_falls_back_to_no_match(self):
        files = [_file(f"t{i}.mp3", (_rec(f"mb-{i}", 0.9),)) for i in range(3)]
        files.append(_file("empty.mp3", ()))
        resolution = resolve_album(files, album_min=3)
        empty = resolution.decisions[-1]
        assert empty.outcome == "fallback"
        assert empty.best is None

    def test_report_line_names_the_minimum(self):
        files = [_file("t0.mp3", ())]
        resolution = resolve_album(files, album_min=3)
        assert "3-file minimum" in resolution.report_line


class TestClusterScoring:
    def test_score_is_file_count_times_avg_confidence(self):
        album = _album_rg()
        files = [
            _file("a.mp3", (_rec("mb-a", 0.8, (album,)),)),
            _file("b.mp3", (_rec("mb-b", 0.9, (album,)),)),
            _file("c.mp3", (_rec("mb-c", 1.0, (album,)),)),
        ]
        resolution = resolve_album(files, album_min=3)
        winner = resolution.winner
        assert winner is not None
        assert winner.file_count == 3
        assert abs(winner.avg_score - 0.9) < 1e-9
        assert abs(winner.score - 2.7) < 1e-9

    def test_file_votes_with_its_best_candidate_per_group(self):
        """A file with several candidates in one group votes once, with
        its best score."""
        album = _album_rg()
        files = [
            _file(
                f"t{i}.mp3",
                (
                    _rec(f"mb-{i}-weak", 0.6, (album,)),
                    _rec(f"mb-{i}-best", 0.95, (album,)),
                ),
            )
            for i in range(3)
        ]
        resolution = resolve_album(files, album_min=3)
        winner = resolution.winner
        assert winner is not None
        assert winner.file_count == 3
        assert abs(winner.avg_score - 0.95) < 1e-9
        for decision in resolution.decisions:
            assert decision.best is not None
            assert decision.best.recording_id.endswith("-best")

    def test_margin_constant_documented(self):
        assert CLUSTER_DECISION_MARGIN == 0.25

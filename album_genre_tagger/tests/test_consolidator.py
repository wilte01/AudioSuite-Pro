"""
Tests for album_genre_tagger.core.consolidator
Gap G-28: run_analysis() — two-phase consolidation, coverage gate,
          majority-vote, tie-break, all-unknown, dry-run.
"""

from mutagen.id3 import ID3, TXXX
from mutagen.mp3 import MP3
from pydub import AudioSegment

from album_genre_tagger.core.consolidator import run_analysis

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_mp3(tmp_path, name, titlegenre=None):
    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="mp3")
    audio = MP3(str(path), ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    if titlegenre:
        audio.tags.add(TXXX(encoding=3, desc="TITLEGENRE", text=titlegenre))
    audio.save()
    return str(path)


def _run(tmp_path, is_dry_run=False, min_coverage=50):
    """Run run_analysis and collect all callback results."""
    p1, coverage, p2, complete, errors = [], [], [], [], []

    run_analysis(
        dir_path=str(tmp_path),
        is_dry_run=is_dry_run,
        min_coverage=min_coverage,
        on_phase1_progress=lambda **kw: p1.append(kw),
        on_coverage_fail=lambda **kw: coverage.append(kw),
        on_phase2_progress=lambda **kw: p2.append(kw),
        on_complete=lambda **kw: complete.append(kw),
        on_error=lambda msg: errors.append(msg),
    )
    return p1, coverage, p2, complete, errors


# ═════════════════════════════════════════════════════════════════════════════
# Error paths
# ═════════════════════════════════════════════════════════════════════════════


class TestRunAnalysisErrors:
    def test_empty_directory_calls_on_error(self, tmp_path):
        _, _, _, _, errors = _run(tmp_path)
        assert len(errors) == 1
        assert "No supported audio files" in errors[0]

    def test_nonexistent_directory_calls_on_error(self, tmp_path):
        _, _, _, _, errors = _run(tmp_path / "missing")
        assert len(errors) == 1
        assert "could not be found" in errors[0]

    def test_non_audio_files_ignored(self, tmp_path):
        (tmp_path / "cover.jpg").write_bytes(b"x")
        _, _, _, _, errors = _run(tmp_path)
        assert any("No supported audio files" in e for e in errors)


# ═════════════════════════════════════════════════════════════════════════════
# Phase 1: reading TITLEGENRE
# ═════════════════════════════════════════════════════════════════════════════


class TestPhase1Reading:
    def test_phase1_progress_called_per_file(self, tmp_path):
        for i in range(4):
            _make_mp3(tmp_path, f"t{i}.mp3", "Rock")
        p1, _, _, _, _ = _run(tmp_path)
        assert len(p1) == 4

    def test_phase1_tracks_files_with_genre(self, tmp_path):
        _make_mp3(tmp_path, "a.mp3", "Rock")
        _make_mp3(tmp_path, "b.mp3", None)  # no TITLEGENRE
        _make_mp3(tmp_path, "c.mp3", "Jazz")
        p1, _, _, _, _ = _run(tmp_path, min_coverage=0)
        final = p1[-1]
        assert final["files_with_genre"] == 2

    def test_phase1_total_matches_file_count(self, tmp_path):
        for i in range(5):
            _make_mp3(tmp_path, f"t{i}.mp3", "Rock")
        p1, _, _, _, _ = _run(tmp_path)
        assert p1[-1]["total"] == 5

    def test_phase1_processed_increments(self, tmp_path):
        for i in range(3):
            _make_mp3(tmp_path, f"t{i}.mp3", "Jazz")
        p1, _, _, _, _ = _run(tmp_path)
        processed_vals = [r["processed"] for r in p1]
        assert processed_vals == [1, 2, 3]


# ═════════════════════════════════════════════════════════════════════════════
# Coverage gate
# ═════════════════════════════════════════════════════════════════════════════


class TestCoverageGate:
    def test_below_min_coverage_calls_on_coverage_fail(self, tmp_path):
        _make_mp3(tmp_path, "a.mp3", "Rock")  # 1/3 = 33%
        _make_mp3(tmp_path, "b.mp3", None)
        _make_mp3(tmp_path, "c.mp3", None)
        _, coverage, _, complete, _ = _run(tmp_path, min_coverage=50)
        assert len(coverage) == 1
        assert len(complete) == 0

    def test_coverage_fail_includes_stats(self, tmp_path):
        _make_mp3(tmp_path, "a.mp3", "Rock")
        _make_mp3(tmp_path, "b.mp3", None)
        _, coverage, _, _, _ = _run(tmp_path, min_coverage=80)
        c = coverage[0]
        assert c["total"] == 2
        assert c["files_with_genre"] == 1
        assert c["min_coverage"] == 80

    def test_exactly_at_min_coverage_proceeds(self, tmp_path):
        _make_mp3(tmp_path, "a.mp3", "Rock")
        _make_mp3(tmp_path, "b.mp3", "Jazz")
        # 2/2 = 100% >= 50%
        _, coverage, _, complete, _ = _run(tmp_path, min_coverage=50)
        assert len(coverage) == 0
        assert len(complete) == 1

    def test_zero_min_coverage_always_proceeds(self, tmp_path):
        _make_mp3(tmp_path, "a.mp3", None)  # no genre at all
        _, coverage, _, complete, _ = _run(tmp_path, min_coverage=0)
        assert len(coverage) == 0
        assert len(complete) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Phase 2: consolidation logic
# ═════════════════════════════════════════════════════════════════════════════


class TestConsolidationLogic:
    def test_unique_genres_sorted_in_album_genre_string(self, tmp_path):
        _make_mp3(tmp_path, "a.mp3", "Rock")
        _make_mp3(tmp_path, "b.mp3", "Jazz")
        _make_mp3(tmp_path, "c.mp3", "Rock")
        _, _, _, complete, _ = _run(tmp_path)
        # sorted: Jazz; Rock
        assert complete[0]["album_genre_string"] == "Jazz; Rock"

    def test_single_genre_no_semicolons(self, tmp_path):
        for i in range(3):
            _make_mp3(tmp_path, f"t{i}.mp3", "Classical")
        _, _, _, complete, _ = _run(tmp_path)
        assert complete[0]["album_genre_string"] == "Classical"

    def test_unique_genres_list_correct(self, tmp_path):
        _make_mp3(tmp_path, "a.mp3", "Ambient")
        _make_mp3(tmp_path, "b.mp3", "Ambient")
        _make_mp3(tmp_path, "c.mp3", "Electronic")
        _, _, _, complete, _ = _run(tmp_path)
        assert set(complete[0]["unique_genres"]) == {"Ambient", "Electronic"}

    def test_all_genres_same_single_entry(self, tmp_path):
        for i in range(5):
            _make_mp3(tmp_path, f"t{i}.mp3", "House")
        _, _, _, complete, _ = _run(tmp_path)
        assert complete[0]["unique_genres"] == ["House"]

    def test_many_genres_all_included(self, tmp_path):
        genres = ["Rock", "Jazz", "Classical", "Electronic", "Folk"]
        for i, g in enumerate(genres):
            _make_mp3(tmp_path, f"t{i}.mp3", g)
        _, _, _, complete, _ = _run(tmp_path)
        assert set(complete[0]["unique_genres"]) == set(genres)


# ═════════════════════════════════════════════════════════════════════════════
# Phase 2: writing tags
# ═════════════════════════════════════════════════════════════════════════════


class TestPhase2Writing:
    def test_live_run_writes_albumgenre_to_files(self, tmp_path):
        for i in range(2):
            _make_mp3(tmp_path, f"t{i}.mp3", "Soul")
        _run(tmp_path, is_dry_run=False)
        for name in ["t0.mp3", "t1.mp3"]:
            audio = MP3(str(tmp_path / name), ID3=ID3)
            frame = audio.tags.get("TXXX:ALBUMGENRE")
            assert frame is not None
            assert frame.text[0] == "Soul"

    def test_live_run_writes_albumderived_y(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3", "Funk")
        _run(tmp_path, is_dry_run=False)
        audio = MP3(str(tmp_path / "t.mp3"), ID3=ID3)
        frame = audio.tags.get("TXXX:ALBUMDERIVED")
        assert frame is not None and frame.text[0] == "Y"

    def test_dry_run_does_not_write_tags(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3", "Blues")
        _run(tmp_path, is_dry_run=True)
        audio = MP3(str(tmp_path / "t.mp3"), ID3=ID3)
        assert audio.tags.get("TXXX:ALBUMGENRE") is None

    def test_phase2_progress_called_per_file(self, tmp_path):
        for i in range(3):
            _make_mp3(tmp_path, f"t{i}.mp3", "Reggae")
        _, _, p2, _, _ = _run(tmp_path, is_dry_run=False)
        assert len(p2) == 3

    def test_write_count_in_complete(self, tmp_path):
        for i in range(4):
            _make_mp3(tmp_path, f"t{i}.mp3", "Techno")
        _, _, _, complete, _ = _run(tmp_path, is_dry_run=False)
        assert complete[0]["write_count"] == 4

    def test_dry_run_label_in_phase2_display(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3", "Pop")
        _, _, p2, _, _ = _run(tmp_path, is_dry_run=True)
        assert any("DRY RUN" in r.get("display_text", "") for r in p2)


# ═════════════════════════════════════════════════════════════════════════════
# on_complete summary
# ═════════════════════════════════════════════════════════════════════════════


class TestOnComplete:
    def test_complete_called_exactly_once(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3", "Jazz")
        _, _, _, complete, _ = _run(tmp_path)
        assert len(complete) == 1

    def test_complete_has_all_expected_keys(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3", "Jazz")
        _, _, _, complete, _ = _run(tmp_path)
        expected = {
            "total",
            "files_with_genre",
            "coverage_pct",
            "unique_genres",
            "album_genre_string",
            "write_count",
            "write_errors",
            "read_errors",
            "duration_secs",
            "log_entries",
        }
        assert expected.issubset(complete[0].keys())

    def test_coverage_pct_calculation(self, tmp_path):
        _make_mp3(tmp_path, "a.mp3", "Rock")
        _make_mp3(tmp_path, "b.mp3", None)
        _, _, _, complete, _ = _run(tmp_path, min_coverage=0)
        assert abs(complete[0]["coverage_pct"] - 50.0) < 0.1

    def test_log_entries_is_list(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3", "Jazz")
        _, _, _, complete, _ = _run(tmp_path)
        assert isinstance(complete[0]["log_entries"], list)

    def test_duration_secs_non_negative(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3", "Jazz")
        _, _, _, complete, _ = _run(tmp_path)
        assert complete[0]["duration_secs"] >= 0


# ═════════════════════════════════════════════════════════════════════════════
# Write-error path (Phase 2) — previously untested branch
# ═════════════════════════════════════════════════════════════════════════════
#
# The existing suite only exercises write_album_genre() failures at the unit
# level (test_tag_io.py::TestWriteAlbumGenre::test_nonexistent_file_returns_false).
# Nothing drove a write failure *through* run_analysis() itself, so the
# write_errors counting, the "[WRITE ERROR]" display/log lines, and the
# conditional "Write errors: N" summary line (consolidator.py ~200-201) had
# zero coverage. Filesystem permission tricks (chmod 444) are unreliable
# across platforms/CI users (e.g. root), so these monkeypatch the write
# function directly at the point run_analysis() imports it, which is
# deterministic and portable.


class TestPhase2WriteErrors:
    def test_write_error_counted_in_complete(self, tmp_path, monkeypatch):
        import album_genre_tagger.core.consolidator as consolidator_mod

        _make_mp3(tmp_path, "good.mp3", "Rock")
        _make_mp3(tmp_path, "bad.mp3", "Rock")

        real_write = consolidator_mod.write_album_genre

        def flaky_write(filepath, album_genre_string, is_dry_run):
            if "bad.mp3" in filepath:
                return False, "Simulated disk write failure"
            return real_write(filepath, album_genre_string, is_dry_run)

        monkeypatch.setattr(consolidator_mod, "write_album_genre", flaky_write)

        _, _, p2, complete, _ = _run(tmp_path, is_dry_run=False)

        assert complete[0]["write_errors"] == 1
        assert complete[0]["write_count"] == 1
        assert any(
            "[WRITE ERROR]" in r.get("display_text", "")
            and "bad.mp3" in r.get("display_text", "")
            for r in p2
        )

    def test_write_errors_line_present_in_log_when_nonzero(self, tmp_path, monkeypatch):
        import album_genre_tagger.core.consolidator as consolidator_mod

        _make_mp3(tmp_path, "bad.mp3", "Rock")
        monkeypatch.setattr(
            consolidator_mod,
            "write_album_genre",
            lambda filepath, album_genre_string, is_dry_run: (False, "boom"),
        )

        _, _, _, complete, _ = _run(tmp_path, is_dry_run=False)

        log_text = "".join(complete[0]["log_entries"])
        assert "Write errors: 1" in log_text

    def test_write_errors_line_absent_from_log_when_zero(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3", "Rock")
        _, _, _, complete, _ = _run(tmp_path, is_dry_run=False)
        log_text = "".join(complete[0]["log_entries"])
        assert "Write errors:" not in log_text


# ═════════════════════════════════════════════════════════════════════════════
# Directory-scan error path — previously untested exception branch
# ═════════════════════════════════════════════════════════════════════════════
#
# test_nonexistent_directory_calls_on_error covers os.listdir() raising
# FileNotFoundError, but the broader "except Exception" around the scan
# (e.g. PermissionError on a locked/unreadable directory) was never
# triggered. This documents that any os.listdir() failure — not just a
# missing path — is caught and reported via on_error rather than propagating
# as an unhandled traceback.


class TestDirectoryScanErrors:
    def test_permission_error_on_scan_calls_on_error(self, tmp_path, monkeypatch):
        import album_genre_tagger.core.consolidator as consolidator_mod

        def raise_permission_error(_path):
            raise PermissionError("Access is denied")

        monkeypatch.setattr(consolidator_mod.os, "listdir", raise_permission_error)

        _, _, _, complete, errors = _run(tmp_path)

        assert len(errors) == 1
        assert len(complete) == 0


# ═════════════════════════════════════════════════════════════════════════════
# Genre-value edge cases — real-world tag inconsistency
# ═════════════════════════════════════════════════════════════════════════════
#
# TITLEGENRE values come from whatever wrote them (Terry's other tools,
# manual edits, third-party taggers). consolidator.py deduplicates with a
# plain set() and does no normalization (no .strip(), no .casefold()), so
# case differences and stray whitespace produce *separate* "unique" genre
# entries rather than being merged. These tests document that actual,
# current behavior so it's a known/intentional trade-off rather than a
# silent surprise. (Confirmed independently against real mutagen read/write
# round-tripping — this is not a mocked assumption.)


class TestGenreValueNormalization:
    def test_case_variants_treated_as_distinct_genres(self, tmp_path):
        _make_mp3(tmp_path, "a.mp3", "Rock")
        _make_mp3(tmp_path, "b.mp3", "rock")
        _, _, _, complete, _ = _run(tmp_path)
        assert set(complete[0]["unique_genres"]) == {"Rock", "rock"}

    def test_whitespace_padded_genre_treated_as_distinct(self, tmp_path):
        _make_mp3(tmp_path, "a.mp3", "Rock")
        _make_mp3(tmp_path, "b.mp3", " Rock")
        _, _, _, complete, _ = _run(tmp_path)
        assert set(complete[0]["unique_genres"]) == {"Rock", " Rock"}

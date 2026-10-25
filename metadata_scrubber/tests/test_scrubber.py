"""
Tests for metadata_scrubber.core.scrubber
Gap G-27: process_single_file(), run_scrubbing()

Uses pydub + mutagen to build real MP3 test fixtures.
slot_vars and slot_queue are simulated with MagicMock/Queue.

Changed in 2.1.3: `TestFormatDiscoveryMatchesLoader` locks discovery to the
`_LOADERS` table and proves a valid `.wv` file is no longer reported as an
error (R-05).
"""

import shutil
import threading
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock

import pytest
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TPE2, TXXX, USLT, Encoding
from mutagen.mp3 import MP3
from pydub import AudioSegment

from metadata_scrubber.core.scrubber import (
    _collect_tags_to_preserve,
    _get_frame_safe,
    _restore_tags,
    process_single_file,
    run_scrubbing,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

# Minimal valid 1x1 PNG, used as fake embedded artwork payload.
_FAKE_ART_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_mp3(
    tmp_path, name: str = "track.mp3", tags: dict = None, embed_art: bool = False
) -> str:
    """Create a real MP3 with optional tags. tags={field_id: text}.

    Args:
        embed_art: If True, attaches an APIC (front cover) frame using a
            minimal fake PNG payload.
    """
    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="mp3")
    audio = MP3(str(path), ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    if tags:
        for fid, text in tags.items():
            if fid == "TPE1":
                audio.tags.add(TPE1(encoding=3, text=text))
            elif fid == "TPE2":
                audio.tags.add(TPE2(encoding=3, text=text))
            elif fid == "TALB":
                audio.tags.add(TALB(encoding=3, text=text))
            elif fid == "TIT2":
                audio.tags.add(TIT2(encoding=3, text=text))
            elif fid.startswith("TXXX:"):
                desc = fid[5:]
                audio.tags.add(TXXX(encoding=3, desc=desc, text=text))
    if embed_art:
        audio.tags.add(
            APIC(
                encoding=3,
                mime="image/png",
                type=3,  # front cover
                desc="Cover",
                data=_FAKE_ART_BYTES,
            )
        )
    audio.save()
    return str(path)


def _make_slot_fixtures(n: int = 4):
    """Return (slot_vars, slot_queue) with n slots, all seeded."""
    slot_vars = [MagicMock() for _ in range(n)]
    slot_queue: Queue = Queue()
    for i in range(n):
        slot_queue.put(i)
    return slot_vars, slot_queue


def _collect_progress():
    """Return (callback, results_list) for capturing on_progress calls."""
    results = []
    lock = threading.Lock()

    def cb(**kwargs):
        with lock:
            results.append(kwargs)

    return cb, results


# ═════════════════════════════════════════════════════════════════════════════
# process_single_file
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessSingleFileDryRun:
    def test_dry_run_reports_dry_run_status(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE1": "Artist"})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        assert len(results) == 1
        assert "DRY RUN" in results[0].get("display_text", "")

    def test_dry_run_does_not_modify_file(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE1": "Original Artist"})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, _ = _collect_progress()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        assert audio.tags.get("TPE1") is not None

    def test_slot_returned_after_dry_run(self, tmp_path):
        _make_mp3(tmp_path)
        slot_vars, slot_q = _make_slot_fixtures(n=1)

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        assert slot_q.qsize() == 1


class TestProcessSingleFileLive:
    def test_scrubbed_file_has_artist_preserved(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE1": "Test Artist", "TXXX:JUNK": "delete_me"})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        assert audio.tags.get("TPE1") is not None
        assert audio.tags.get("TPE1").text[0] == "Test Artist"

    def test_junk_txxx_removed(self, tmp_path):
        _make_mp3(tmp_path, tags={"TXXX:JUNK_TAG": "remove_me"})
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        txxx = {f.desc for f in audio.tags.values() if isinstance(f, TXXX)}
        assert "JUNK_TAG" not in txxx

    def test_preserved_txxx_kept(self, tmp_path):
        _make_mp3(tmp_path, tags={"TXXX:KEEP_ME": "important", "TXXX:JUNK": "go"})
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=["KEEP_ME"],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        txxx = {f.desc: f.text[0] for f in audio.tags.values() if isinstance(f, TXXX)}
        assert txxx.get("KEEP_ME") == "important"
        assert "JUNK" not in txxx

    def test_cleaned_status_in_log(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE1": "Artist"})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        assert any("CLEANED" in r.get("display_text", "") for r in results)

    def test_album_and_title_preserved(self, tmp_path):
        _make_mp3(tmp_path, tags={"TALB": "My Album", "TIT2": "My Title"})
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        assert audio.tags.get("TALB").text[0] == "My Album"
        assert audio.tags.get("TIT2").text[0] == "My Title"

    def test_slot_always_returned_after_live_run(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE1": "Artist"})
        slot_vars, slot_q = _make_slot_fixtures(n=1)

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        assert slot_q.qsize() == 1

    def test_missing_file_reports_error(self, tmp_path):
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()

        process_single_file(
            name="ghost.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        assert any(r.get("n_errors", 0) == 1 for r in results)

    # ── preserve_album_artist tests ───────────────────────────────────────────

    def test_album_artist_preserved_when_flag_true(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE2": "Various Artists"})
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=True,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        tpe2 = audio.tags.get("TPE2")
        assert tpe2 is not None
        assert tpe2.text[0] == "Various Artists"

    def test_album_artist_removed_when_flag_false(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE2": "Various Artists"})
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        assert audio.tags.get("TPE2") is None

    def test_dry_run_preserve_album_artist_true_no_modification(self, tmp_path):
        """Dry run must never modify the file regardless of preserve_album_artist."""
        _make_mp3(tmp_path, tags={"TPE2": "Album Artist"})
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=True,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        assert audio.tags.get("TPE2") is not None

    # ── preserve_embedded_art tests ───────────────────────────────────────────

    def test_embedded_art_preserved_when_flag_true(self, tmp_path):
        _make_mp3(tmp_path, embed_art=True)
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=True,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        apic_frames = [f for f in audio.tags.values() if isinstance(f, APIC)]
        assert len(apic_frames) == 1
        assert apic_frames[0].data == _FAKE_ART_BYTES
        assert apic_frames[0].mime == "image/png"

    def test_embedded_art_removed_when_flag_false(self, tmp_path):
        _make_mp3(tmp_path, embed_art=True)
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        apic_frames = [f for f in audio.tags.values() if isinstance(f, APIC)]
        assert len(apic_frames) == 0

    def test_dry_run_preserve_embedded_art_true_no_modification(self, tmp_path):
        """Dry run must never modify the file regardless of preserve_embedded_art."""
        _make_mp3(tmp_path, embed_art=True)
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=True,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        apic_frames = [f for f in audio.tags.values() if isinstance(f, APIC)]
        assert len(apic_frames) == 1

    def test_embedded_art_and_album_artist_independent_flags(self, tmp_path):
        """Each preserve flag must act independently of the other."""
        _make_mp3(tmp_path, tags={"TPE2": "VA"}, embed_art=True)
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=True,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        assert audio.tags.get("TPE2") is not None
        apic_frames = [f for f in audio.tags.values() if isinstance(f, APIC)]
        assert len(apic_frames) == 0


# ═════════════════════════════════════════════════════════════════════════════
# run_scrubbing
# ═════════════════════════════════════════════════════════════════════════════


class TestRunScrubbing:
    def _run(
        self,
        tmp_path,
        is_dry_run: bool = True,
        preserve_list: list = None,
        preserve_lyrics: bool = False,
        preserve_album_artist: bool = True,
        preserve_embedded_art: bool = True,
    ):
        slot_vars, slot_q = _make_slot_fixtures()
        progress_calls = []
        complete_calls = []
        error_calls = []

        run_scrubbing(
            dir_path=str(tmp_path),
            is_dry_run=is_dry_run,
            preserve_list=preserve_list or [],
            preserve_lyrics=preserve_lyrics,
            preserve_album_artist=preserve_album_artist,
            preserve_embedded_art=preserve_embedded_art,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=lambda **kw: progress_calls.append(kw),
            on_complete=lambda **kw: complete_calls.append(kw),
            on_error=lambda msg: error_calls.append(msg),
        )
        return progress_calls, complete_calls, error_calls

    def test_empty_directory_calls_on_error(self, tmp_path):
        _, _, errors = self._run(tmp_path)
        assert len(errors) == 1
        assert "No supported audio files" in errors[0]

    def test_nonexistent_directory_calls_on_error(self, tmp_path):
        slot_vars, slot_q = _make_slot_fixtures()
        errors = []
        run_scrubbing(
            dir_path=str(tmp_path / "missing"),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=True,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: None,
            on_error=errors.append,
        )
        assert len(errors) == 1

    def test_on_complete_called_with_total(self, tmp_path):
        for i in range(3):
            _make_mp3(tmp_path, f"t{i}.mp3", tags={"TPE1": f"Artist{i}"})
        _, complete, _ = self._run(tmp_path, is_dry_run=True)
        assert len(complete) == 1
        assert complete[0]["total"] == 3

    def test_on_progress_called_per_file(self, tmp_path):
        for i in range(3):
            _make_mp3(tmp_path, f"t{i}.mp3")
        progress, _, _ = self._run(tmp_path, is_dry_run=True)
        assert len(progress) == 3

    def test_processed_count_matches_total(self, tmp_path):
        for i in range(4):
            _make_mp3(tmp_path, f"t{i}.mp3", tags={"TPE1": "A"})
        _, complete, _ = self._run(tmp_path, is_dry_run=True)
        assert complete[0]["processed"] == 4

    def test_non_mp3_files_ignored(self, tmp_path):
        (tmp_path / "cover.jpg").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")
        _make_mp3(tmp_path, "track.mp3", tags={"TPE1": "A"})
        _, complete, _ = self._run(tmp_path, is_dry_run=True)
        assert complete[0]["total"] == 1

    def test_wma_files_no_longer_enumerated(self, tmp_path):
        """Regression: the scrubber has no WMA/ASF tag handler, so .wma files
        must not be discovered (they previously failed at load with an
        'Unsupported audio format' error)."""
        _make_mp3(tmp_path, "track.mp3", tags={"TPE1": "A"})
        (tmp_path / "old.wma").write_bytes(b"not really wma")
        _, complete, errors = self._run(tmp_path, is_dry_run=True)
        assert complete[0]["total"] == 1
        assert errors == []

    def test_live_scrub_all_files_processed(self, tmp_path):
        for i in range(3):
            _make_mp3(tmp_path, f"t{i}.mp3", tags={"TPE1": f"A{i}", "TXXX:JUNK": "x"})
        _, complete, _ = self._run(tmp_path, is_dry_run=False)
        assert complete[0]["processed"] == 3

    def test_duration_secs_in_complete(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE1": "A"})
        _, complete, _ = self._run(tmp_path, is_dry_run=True)
        assert complete[0]["duration_secs"] >= 0

    def test_log_entries_in_complete(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE1": "A"})
        _, complete, _ = self._run(tmp_path, is_dry_run=True)
        assert isinstance(complete[0]["log_entries"], list)

    def test_album_artist_preserved_in_live_run(self, tmp_path):
        _make_mp3(tmp_path, "track.mp3", tags={"TPE2": "VA"})
        _, complete, errors = self._run(
            tmp_path, is_dry_run=False, preserve_album_artist=True
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        assert audio.tags.get("TPE2") is not None
        assert audio.tags.get("TPE2").text[0] == "VA"

    def test_album_artist_removed_when_flag_false(self, tmp_path):
        _make_mp3(tmp_path, "track.mp3", tags={"TPE2": "VA"})
        _, complete, errors = self._run(
            tmp_path, is_dry_run=False, preserve_album_artist=False
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        assert audio.tags.get("TPE2") is None

    def test_embedded_art_preserved_in_live_run(self, tmp_path):
        _make_mp3(tmp_path, "track.mp3", embed_art=True)
        _, complete, errors = self._run(
            tmp_path, is_dry_run=False, preserve_embedded_art=True
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        apic_frames = [f for f in audio.tags.values() if isinstance(f, APIC)]
        assert len(apic_frames) == 1
        assert apic_frames[0].data == _FAKE_ART_BYTES

    def test_embedded_art_removed_when_flag_false(self, tmp_path):
        _make_mp3(tmp_path, "track.mp3", embed_art=True)
        _, complete, errors = self._run(
            tmp_path, is_dry_run=False, preserve_embedded_art=False
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        apic_frames = [f for f in audio.tags.values() if isinstance(f, APIC)]
        assert len(apic_frames) == 0


# ═════════════════════════════════════════════════════════════════════════════
# Regression: multi-value / encoding preservation for TPE1, TALB, TIT2
#
# Bug: _get_text_safe() previously extracted only field.text[0] and rebuilt
# the frame with encoding=3 (UTF-8), silently discarding any additional
# values in a multi-value text frame and overwriting the original encoding.
# ID3v2.4 permits multiple values per text frame (e.g. several artists
# stored as separate values within one TPE1), so this was real data loss
# on every preserve operation, not a synthetic edge case.
# ═════════════════════════════════════════════════════════════════════════════


class TestMultiValueAndEncodingPreservation:
    def test_multivalue_artist_fully_preserved(self, tmp_path):
        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TPE1(encoding=3, text=["Artist A", "Artist B"]))
        audio.save()

        slot_vars, slot_q = _make_slot_fixtures()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        result = MP3(str(path), ID3=ID3)
        tpe1 = result.tags.get("TPE1")
        assert list(tpe1.text) == ["Artist A", "Artist B"]

    def test_multivalue_album_and_title_fully_preserved(self, tmp_path):
        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TALB(encoding=3, text=["Album A", "Album B"]))
        audio.tags.add(TIT2(encoding=3, text=["Title A", "Title B"]))
        audio.save()

        slot_vars, slot_q = _make_slot_fixtures()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        result = MP3(str(path), ID3=ID3)
        assert list(result.tags.get("TALB").text) == ["Album A", "Album B"]
        assert list(result.tags.get("TIT2").text) == ["Title A", "Title B"]

    def test_original_text_encoding_preserved(self, tmp_path):
        """A LATIN1-encoded TPE1 must not be silently re-encoded as UTF-8."""
        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TPE1(encoding=Encoding.LATIN1, text="Solo Artist"))
        audio.save()

        slot_vars, slot_q = _make_slot_fixtures()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        result = MP3(str(path), ID3=ID3)
        tpe1 = result.tags.get("TPE1")
        assert tpe1.encoding == Encoding.LATIN1
        assert str(tpe1.text[0]) == "Solo Artist"

    def test_single_value_artist_still_preserved(self, tmp_path):
        """Non-regression: the ordinary single-value case still round-trips."""
        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TPE1(encoding=3, text="Solo Artist"))
        audio.save()

        slot_vars, slot_q = _make_slot_fixtures()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        result = MP3(str(path), ID3=ID3)
        assert str(result.tags.get("TPE1").text[0]) == "Solo Artist"

    def test_no_artist_frame_present_no_error(self, tmp_path):
        """A file with no TPE1 at all must process cleanly (no spurious frame added)."""
        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TALB(encoding=3, text="Album Only"))
        audio.save()

        slot_vars, slot_q = _make_slot_fixtures()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        result = MP3(str(path), ID3=ID3)
        assert result.tags.get("TPE1") is None
        assert str(result.tags.get("TALB").text[0]) == "Album Only"


# ═════════════════════════════════════════════════════════════════════════════
# Regression: preserve_lyrics coverage gap
#
# Every existing test in this file passes preserve_lyrics=False, so neither
# direction of the flag had ever been exercised. Behaviour was verified
# correct by manual inspection before these tests were added; they exist to
# prevent a future silent regression, not because a bug was found here.
# ═════════════════════════════════════════════════════════════════════════════


class TestPreserveLyrics:
    def test_lyrics_preserved_when_flag_true(self, tmp_path):
        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(USLT(encoding=3, lang="eng", desc="", text="La la la"))
        audio.save()

        slot_vars, slot_q = _make_slot_fixtures()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=True,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        result = MP3(str(path), ID3=ID3)
        uslt_frames = [f for f in result.tags.values() if isinstance(f, USLT)]
        assert len(uslt_frames) == 1
        assert str(uslt_frames[0].text) == "La la la"

    def test_lyrics_removed_when_flag_false(self, tmp_path):
        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(USLT(encoding=3, lang="eng", desc="", text="La la la"))
        audio.save()

        slot_vars, slot_q = _make_slot_fixtures()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        result = MP3(str(path), ID3=ID3)
        uslt_frames = [f for f in result.tags.values() if isinstance(f, USLT)]
        assert len(uslt_frames) == 0


# ═════════════════════════════════════════════════════════════════════════════
# Direct unit tests: _get_frame_safe
# ═════════════════════════════════════════════════════════════════════════════


class TestGetFrameSafe:
    def test_returns_frame_when_text_present(self):
        from unittest.mock import MagicMock

        audio = MagicMock()
        frame = MagicMock()
        frame.text = ["Artist"]
        audio.tags.get.return_value = frame
        result = _get_frame_safe(audio, "TPE1")
        assert result is frame

    def test_returns_none_when_frame_absent(self):
        from unittest.mock import MagicMock

        audio = MagicMock()
        audio.tags.get.return_value = None
        assert _get_frame_safe(audio, "TPE1") is None

    def test_returns_none_when_empty_text_list(self):
        from unittest.mock import MagicMock

        audio = MagicMock()
        frame = MagicMock()
        frame.text = []
        audio.tags.get.return_value = frame
        assert _get_frame_safe(audio, "TPE1") is None

    def test_returns_none_when_empty_string_text(self):
        from unittest.mock import MagicMock

        audio = MagicMock()
        frame = MagicMock()
        frame.text = ""
        audio.tags.get.return_value = frame
        assert _get_frame_safe(audio, "TPE1") is None

    def test_returns_none_when_field_lacks_text_attr(self):
        from unittest.mock import MagicMock

        audio = MagicMock()
        frame = MagicMock(spec=[])
        audio.tags.get.return_value = frame
        assert _get_frame_safe(audio, "APIC") is None

    def test_returns_none_when_tags_get_raises(self):
        from unittest.mock import MagicMock

        audio = MagicMock()
        audio.tags.get.side_effect = ValueError("corrupt frame")
        assert _get_frame_safe(audio, "TPE1") is None


# ═════════════════════════════════════════════════════════════════════════════
# Error-recovery paths: process_single_file Stage 4 / Stage 5
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessSingleFileErrorRecovery:
    def test_corrupt_tags_reported_when_delete_save_fails(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE1": "Artist"})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()

        original_save = MP3.save
        call_count = [0]

        def _failing_save(self):
            call_count[0] += 1
            if call_count[0] == 1:
                raise PermissionError("Simulated permission error on save")
            return original_save(self)

        with unittest.mock.patch.object(MP3, "save", _failing_save):
            process_single_file(
                name="track.mp3",
                dir_path=str(tmp_path),
                is_dry_run=False,
                preserve_list=[],
                preserve_lyrics=False,
                preserve_album_artist=False,
                preserve_embedded_art=False,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=threading.Lock(),
                on_progress=cb,
            )
        assert any("[CORRUPT TAGS]" in r.get("display_text", "") for r in results)
        assert any(r.get("n_errors", 0) == 1 for r in results)

    def test_write_failed_reported_when_restore_save_fails(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE1": "Artist", "TALB": "Album"})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()
        mock_handler = MagicMock()
        mock_handler.set_raw_tags.side_effect = PermissionError(
            "Simulated permission error on restore"
        )

        with unittest.mock.patch(
            "metadata_scrubber.core.scrubber.TagHandlerFactory.get_handler",
            return_value=mock_handler,
        ):
            process_single_file(
                name="track.mp3",
                dir_path=str(tmp_path),
                is_dry_run=False,
                preserve_list=[],
                preserve_lyrics=False,
                preserve_album_artist=False,
                preserve_embedded_art=False,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=threading.Lock(),
                on_progress=cb,
            )
        assert any("[WRITE FAILED]" in r.get("display_text", "") for r in results)
        assert any(r.get("n_errors", 0) == 1 for r in results)

    def test_preserve_list_non_txxx_is_noop(self, tmp_path):
        _make_mp3(tmp_path, tags={"TXXX:JUNK": "delete_me"})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=["TPE1"],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        audio = MP3(str(tmp_path / "track.mp3"), ID3=ID3)
        txxx_frames = {f.desc for f in audio.tags.values() if isinstance(f, TXXX)}
        assert "JUNK" not in txxx_frames
        assert not any(r.get("n_errors", 0) > 0 for r in results)


# ═════════════════════════════════════════════════════════════════════════════
# Undo-snapshot integration (Phase 3b)
#
# The live wipe path must record exactly one "scrub_wipe" snapshot via
# record_tag_edit_snapshot(), and the restore phase must delegate the write
# through TagHandlerFactory.get_handler().set_raw_tags() instead of
# write_tags_raw() (whose internal auto-snapshot would duplicate the undo
# record with a post-wipe state) or a bare audio.save(). These tests pin that
# plumbing so a future refactor cannot silently drop undo coverage.
# ═════════════════════════════════════════════════════════════════════════════


class TestUndoSnapshotRecording:
    def test_live_wipe_records_scrub_wipe_snapshot(self, tmp_path, monkeypatch):
        _make_mp3(tmp_path, tags={"TPE1": "Artist"})
        slot_vars, slot_q = _make_slot_fixtures()
        recorded = []

        def _fake_snapshot(path: str, operation: str) -> None:
            recorded.append((path, operation))

        monkeypatch.setattr(
            "metadata_scrubber.core.scrubber.record_tag_edit_snapshot",
            _fake_snapshot,
        )
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        assert recorded == [(str(tmp_path / "track.mp3"), "scrub_wipe")]

    def test_dry_run_records_no_snapshot(self, tmp_path, monkeypatch):
        _make_mp3(tmp_path, tags={"TPE1": "Artist"})
        slot_vars, slot_q = _make_slot_fixtures()
        recorded = []

        def _fake_snapshot(path: str, operation: str) -> None:
            recorded.append((path, operation))

        monkeypatch.setattr(
            "metadata_scrubber.core.scrubber.record_tag_edit_snapshot",
            _fake_snapshot,
        )
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        assert recorded == []

    def test_restore_phase_delegates_to_tag_handler(self, tmp_path):
        _make_mp3(tmp_path, tags={"TPE1": "Artist", "TALB": "Album"})
        slot_vars, slot_q = _make_slot_fixtures()
        mock_handler = MagicMock()
        with unittest.mock.patch(
            "metadata_scrubber.core.scrubber.TagHandlerFactory.get_handler",
            return_value=mock_handler,
        ) as mock_get_handler:
            process_single_file(
                name="track.mp3",
                dir_path=str(tmp_path),
                is_dry_run=False,
                preserve_list=[],
                preserve_lyrics=False,
                preserve_album_artist=False,
                preserve_embedded_art=False,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=threading.Lock(),
                on_progress=lambda **kw: None,
            )
        assert mock_get_handler.call_count == 1
        assert mock_handler.set_raw_tags.call_count == 1
        call_tags = mock_handler.set_raw_tags.call_args.args[0]
        assert call_tags.get("TPE1").text[0] == "Artist"
        assert call_tags.get("TALB").text[0] == "Album"


# ═════════════════════════════════════════════════════════════════════════════
# run_scrubbing edge cases
# ═════════════════════════════════════════════════════════════════════════════


class TestRunScrubbingEdgeCases:
    def test_only_non_audio_files_triggers_on_error(self, tmp_path):
        (tmp_path / "notes.txt").write_bytes(b"hello")
        (tmp_path / "cover.jpg").write_bytes(b"image")
        slot_vars, slot_q = _make_slot_fixtures()
        errors = []

        run_scrubbing(
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=True,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: None,
            on_error=errors.append,
        )
        assert len(errors) == 1
        assert "No supported audio files" in errors[0]

    def test_mixed_success_no_errors(self, tmp_path):
        _make_mp3(tmp_path, "good.mp3", tags={"TPE1": "Artist"})
        (tmp_path / "readme.txt").write_bytes(b"x")
        slot_vars, slot_q = _make_slot_fixtures(n=4)
        progress_calls = []
        complete_calls = []
        errors = []

        run_scrubbing(
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=lambda **kw: progress_calls.append(kw),
            on_complete=lambda **kw: complete_calls.append(kw),
            on_error=errors.append,
        )
        assert len(errors) == 0
        assert complete_calls[0]["total"] == 1
        assert complete_calls[0]["processed"] == 1
        assert complete_calls[0]["errors"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Regression: SYLT frame preservation alongside USLT
# ═════════════════════════════════════════════════════════════════════════════


class TestPreserveSyltLyrics:
    def test_sylt_preserved_when_flag_true(self, tmp_path):
        from mutagen.id3 import SYLT, Encoding

        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        sylt = SYLT(
            encoding=Encoding.UTF8,
            lang="eng",
            format=2,
            type=1,
            text=[("Line one", 0), ("Line two", 5000)],
        )
        audio.tags.add(sylt)
        audio.save()

        slot_vars, slot_q = _make_slot_fixtures()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=True,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        result = MP3(str(path), ID3=ID3)
        sylt_frames = [f for f in result.tags.values() if isinstance(f, SYLT)]
        assert len(sylt_frames) == 1
        assert len(sylt_frames[0].text) == 2

    def test_sylt_removed_when_flag_false(self, tmp_path):
        from mutagen.id3 import SYLT, Encoding

        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        sylt = SYLT(
            encoding=Encoding.UTF8,
            lang="eng",
            format=2,
            type=1,
            text=[("Line one", 0)],
        )
        audio.tags.add(sylt)
        audio.save()

        slot_vars, slot_q = _make_slot_fixtures()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        result = MP3(str(path), ID3=ID3)
        sylt_frames = [f for f in result.tags.values() if isinstance(f, SYLT)]
        assert len(sylt_frames) == 0


# ═════════════════════════════════════════════════════════════════════════════
# Multi-format support: FLAC, OGG, M4A
# ═════════════════════════════════════════════════════════════════════════════


def _make_flac(tmp_path, name: str = "track.flac", tags: dict | None = None) -> str:
    """Create a real FLAC with optional Vorbis comments."""
    from mutagen.flac import FLAC

    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="flac")
    audio = FLAC(str(path))
    if tags:
        for key, val in tags.items():
            audio[key] = val
        audio.save()
    return str(path)


def _make_ogg(tmp_path, name: str = "track.ogg", tags: dict | None = None) -> str:
    """Create a real OGG Vorbis with optional Vorbis comments."""
    from mutagen.oggvorbis import OggVorbis

    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="ogg")
    audio = OggVorbis(str(path))
    if tags:
        for key, val in tags.items():
            audio[key] = val
        audio.save()
    return str(path)


class TestMultiFormatFLAC:
    def test_dry_run_flac_reports_status(self, tmp_path):
        _make_flac(tmp_path, tags={"artist": ["Test Artist"]})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()

        process_single_file(
            name="track.flac",
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        assert len(results) == 1
        assert "DRY RUN" in results[0].get("display_text", "")

    def test_scrub_flac_preserves_essential_tags(self, tmp_path):
        """FLAC scrub preserves artist/album/title, removes other tags."""
        _make_flac(
            tmp_path, tags={"artist": ["Test"], "album": ["Album"], "genre": ["Rock"]}
        )
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.flac",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        from mutagen.flac import FLAC

        audio = FLAC(str(tmp_path / "track.flac"))
        assert audio.tags.get("artist") == ["Test"]
        assert audio.tags.get("album") == ["Album"]
        assert audio.tags.get("genre") is None

    def test_preserve_artist_flac(self, tmp_path):
        """FLAC scrub always preserves essential tags (artist/album/title)."""
        _make_flac(
            tmp_path,
            tags={"artist": ["Keep Me"], "album": ["Also Kept"], "genre": ["Delete"]},
        )
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.flac",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=["artist"],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        from mutagen.flac import FLAC

        audio = FLAC(str(tmp_path / "track.flac"))
        assert audio.tags.get("artist") == ["Keep Me"]
        assert audio.tags.get("album") == ["Also Kept"]
        assert audio.tags.get("genre") is None

    def test_cleaned_status_in_log_flac(self, tmp_path):
        _make_flac(tmp_path, tags={"artist": ["A"]})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()

        process_single_file(
            name="track.flac",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        assert any("CLEANED" in r.get("display_text", "") for r in results)

    def test_slot_returned_after_flac(self, tmp_path):
        _make_flac(tmp_path)
        slot_vars, slot_q = _make_slot_fixtures(n=1)

        process_single_file(
            name="track.flac",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        assert slot_q.qsize() == 1

    def test_flac_detected_in_run_scrubbing(self, tmp_path):
        _make_flac(tmp_path, "track.flac", tags={"artist": ["A"]})
        slot_vars, slot_q = _make_slot_fixtures()
        complete_calls = []

        run_scrubbing(
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: complete_calls.append(kw),
            on_error=lambda msg: None,
        )
        assert len(complete_calls) == 1
        assert complete_calls[0]["total"] == 1


class TestMultiFormatOGG:
    def test_dry_run_ogg_reports_status(self, tmp_path):
        _make_ogg(tmp_path, tags={"artist": ["Test Artist"]})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()

        process_single_file(
            name="track.ogg",
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        assert len(results) == 1
        assert "DRY RUN" in results[0].get("display_text", "")

    def test_scrub_ogg_preserves_essential_tags(self, tmp_path):
        """OGG scrub preserves artist/album/title, removes other tags."""
        _make_ogg(
            tmp_path, tags={"artist": ["Test"], "album": ["Album"], "genre": ["Rock"]}
        )
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.ogg",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        from mutagen.oggvorbis import OggVorbis

        audio = OggVorbis(str(tmp_path / "track.ogg"))
        assert audio.tags.get("artist") == ["Test"]
        assert audio.tags.get("album") == ["Album"]
        assert audio.tags.get("genre") is None

    def test_preserve_artist_ogg(self, tmp_path):
        """OGG scrub always preserves essential tags (artist/album/title)."""
        _make_ogg(
            tmp_path,
            tags={"artist": ["Keep Me"], "album": ["Also Kept"], "genre": ["Delete"]},
        )
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.ogg",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=["artist"],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        from mutagen.oggvorbis import OggVorbis

        audio = OggVorbis(str(tmp_path / "track.ogg"))
        assert audio.tags.get("artist") == ["Keep Me"]
        assert audio.tags.get("album") == ["Also Kept"]
        assert audio.tags.get("genre") is None

    def test_cleaned_status_in_log_ogg(self, tmp_path):
        _make_ogg(tmp_path, tags={"artist": ["A"]})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()

        process_single_file(
            name="track.ogg",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        assert any("CLEANED" in r.get("display_text", "") for r in results)

    def test_ogg_detected_in_run_scrubbing(self, tmp_path):
        _make_ogg(tmp_path, "track.ogg", tags={"artist": ["A"]})
        slot_vars, slot_q = _make_slot_fixtures()
        complete_calls = []

        run_scrubbing(
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: complete_calls.append(kw),
            on_error=lambda msg: None,
        )
        assert len(complete_calls) == 1
        assert complete_calls[0]["total"] == 1


class TestMixedFormatScan:
    def test_run_scrubbing_finds_all_formats(self, tmp_path):
        _make_mp3(tmp_path, "track.mp3", tags={"TPE1": "A"})
        _make_flac(tmp_path, "track.flac", tags={"artist": ["B"]})
        _make_ogg(tmp_path, "track.ogg", tags={"artist": ["C"]})
        slot_vars, slot_q = _make_slot_fixtures()
        complete_calls = []

        run_scrubbing(
            dir_path=str(tmp_path),
            is_dry_run=True,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: complete_calls.append(kw),
            on_error=lambda msg: None,
        )
        assert len(complete_calls) == 1
        assert complete_calls[0]["total"] == 3


# ── Residual branch coverage: MP4, unsupported ext, no-tags, vorbis flags ───


def _make_m4a(tmp_path, name: str = "track.m4a", tags: dict | None = None) -> str:
    """Create a real M4A with optional iTunes atoms."""
    from mutagen.mp4 import MP4

    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="mp4")
    audio = MP4(str(path))
    if tags:
        for key, val in tags.items():
            audio[key] = val
        audio.save()
    return str(path)


class TestResidualBranches:
    def test_unsupported_extension_raises_value_error(self):
        from metadata_scrubber.core.scrubber import _load_audio

        with pytest.raises(ValueError, match="Unsupported audio format"):
            _load_audio("whatever.xyz")

    def test_has_tags_false_without_tags_attr(self):
        from metadata_scrubber.core.scrubber import _has_tags

        assert _has_tags(object()) is False

    def test_m4a_full_scrub_preserves_essential_and_flags(self, tmp_path):
        from mutagen.mp4 import MP4Cover

        art = MP4Cover(b"\xff\xd8\xff\xd9", imageformat=MP4Cover.FORMAT_JPEG)
        _make_m4a(
            tmp_path,
            tags={
                "\xa9ART": ["Keeper"],
                "\xa9alb": ["Album"],
                "\xa9nam": ["Title"],
                "\xa9lyr": ["la la"],
                "covr": [art],
                "\xa9gen": ["Delete Me"],
                "----:com.apple.iTunes:BPM": [b"120"],
            },
        )
        slot_vars, slot_q = _make_slot_fixtures()

        process_single_file(
            name="track.m4a",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=["----:com.apple.iTunes:BPM"],
            preserve_lyrics=True,
            preserve_album_artist=False,
            preserve_embedded_art=True,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        from mutagen.mp4 import MP4

        audio = MP4(str(tmp_path / "track.m4a"))
        assert audio.tags.get("\xa9ART") == ["Keeper"]
        assert audio.tags.get("\xa9alb") == ["Album"]
        assert audio.tags.get("\xa9nam") == ["Title"]
        assert audio.tags.get("\xa9lyr") == ["la la"]
        assert "covr" in audio.tags
        assert audio.tags.get("\xa9gen") is None

    def test_m4a_no_art_preserved_when_flag_off(self, tmp_path):
        from mutagen.mp4 import MP4Cover

        art = MP4Cover(b"\xff\xd8\xff\xd9", imageformat=MP4Cover.FORMAT_JPEG)
        _make_m4a(tmp_path, tags={"covr": [art], "\xa9nam": ["N"]})
        slot_vars, slot_q = _make_slot_fixtures()
        process_single_file(
            name="track.m4a",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        from mutagen.mp4 import MP4

        audio = MP4(str(tmp_path / "track.m4a"))
        assert "covr" not in audio.tags

    def test_flac_preserves_lyrics_albumartist_picture(self, tmp_path):
        _make_flac(
            tmp_path,
            tags={
                "artist": ["A"],
                "album": ["B"],
                "title": ["T"],
                "lyrics": ["words"],
                "albumartist": ["AA"],
                "metadata_block_picture": ["x"],
                "genre": ["Drop"],
                "customfield": ["keep-me-via-list"],
            },
        )
        slot_vars, slot_q = _make_slot_fixtures()
        process_single_file(
            name="track.flac",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=["CUSTOMFIELD"],
            preserve_lyrics=True,
            preserve_album_artist=True,
            preserve_embedded_art=True,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=lambda **kw: None,
        )
        from mutagen.flac import FLAC

        audio = FLAC(str(tmp_path / "track.flac"))
        assert audio.tags.get("lyrics") == ["words"]
        assert audio.tags.get("albumartist") == ["AA"]
        assert audio.tags.get("metadata_block_picture") == ["x"]
        assert audio.tags.get("customfield") == ["keep-me-via-list"]
        assert audio.tags.get("genre") is None

    def test_mp3_unreadable_frame_skipped(self, tmp_path):
        """A frame whose inspection raises is skipped without aborting."""
        _make_mp3(
            tmp_path,
            tags={"TPE1": ["Artist"], "TALB": ["Album"], "TIT2": ["Title"]},
            embed_art=True,
        )

        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=True,
            preserve_album_artist=True,
            preserve_embedded_art=True,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        assert any("CLEANED" in r.get("display_text", "") for r in results)


# ═════════════════════════════════════════════════════════════════════════════
# Direct _collect_tags_to_preserve() coverage: MP3 (ID3), FLAC (Vorbis), M4A
# ═════════════════════════════════════════════════════════════════════════════


class TestCollectTagsToPreserveMP3:
    """Direct tests of _collect_tags_to_preserve() for MP3/ID3 fixtures."""

    def test_essentials_always_preserved_when_flags_off(self, tmp_path):
        _make_mp3(
            tmp_path,
            tags={"TPE1": "Artist", "TALB": "Album", "TIT2": "Title"},
        )
        from metadata_scrubber.core.scrubber import _load_audio

        audio = _load_audio(str(tmp_path / "track.mp3"))
        preserved = _collect_tags_to_preserve(audio, [], False, False, False)
        assert set(preserved) == {"id3:TPE1", "id3:TALB", "id3:TIT2"}

    def test_custom_and_flagged_frames_kept(self, tmp_path):
        _make_mp3(
            tmp_path,
            tags={
                "TPE1": "Artist",
                "TALB": "Album",
                "TIT2": "Title",
                "TXXX:KEEP": "kept-value",
                "TXXX:DELETE": "dropped-value",
            },
            embed_art=True,
        )
        from mutagen.id3 import TPE2, USLT, Encoding

        from metadata_scrubber.core.scrubber import _load_audio

        audio = _load_audio(str(tmp_path / "track.mp3"))
        audio.tags.add(TPE2(encoding=3, text="Compilation Artist"))
        audio.tags.add(
            USLT(
                encoding=Encoding.UTF8,
                desc="",
                text="line one\nline two",
            )
        )
        audio.save()

        audio = _load_audio(str(tmp_path / "track.mp3"))
        preserved = _collect_tags_to_preserve(
            audio,
            ["KEEP"],
            preserve_lyrics=True,
            preserve_album_artist=True,
            preserve_embedded_art=True,
        )
        assert "id3:TPE2" in preserved
        assert "id3:TPE1" in preserved
        assert "id3:TALB" in preserved
        assert "id3:TIT2" in preserved
        assert "id3:USLT" in preserved
        assert "id3:APIC:Cover" in preserved
        assert "id3:TXXX:KEEP" in preserved
        assert "id3:TXXX:DELETE" not in preserved

    def test_unreadable_frame_skipped(self):
        """An ID3 frame whose descendant lookup raises is skipped (115-116)."""
        from mutagen.id3 import TXXX

        class _BrokenTXXX(TXXX):
            def __getattribute__(self, name):
                if name == "desc":
                    raise ValueError("boom")
                return super().__getattribute__(name)

        broken = _BrokenTXXX(encoding=3, desc="x", text="v")
        audio = MagicMock()
        audio.filename = "track.mp3"
        audio.tags.get.side_effect = lambda fid, **kw: broken
        audio.tags.values.return_value = [broken]

        preserved = _collect_tags_to_preserve(audio, [], False, False, False)
        # Essential frames are still collected via _get_frame_safe.
        assert "id3:TPE1" in preserved


class TestCollectTagsToPreserveFLAC:
    """Direct tests of _collect_tags_to_preserve() for FLAC/Vorbis fixtures."""

    def test_essentials_always_preserved_when_flags_off(self, tmp_path):
        _make_flac(
            tmp_path,
            tags={
                "artist": ["Artist"],
                "album": ["Album"],
                "title": ["Title"],
                "genre": ["Drop Me"],
            },
        )
        from metadata_scrubber.core.scrubber import _load_audio

        audio = _load_audio(str(tmp_path / "track.flac"))
        preserved = _collect_tags_to_preserve(audio, [], False, False, False)
        assert preserved == {
            "artist": ["Artist"],
            "album": ["Album"],
            "title": ["Title"],
        }

    def test_flagged_and_custom_vorbis_tags(self, tmp_path):
        _make_flac(
            tmp_path,
            tags={
                "artist": ["Artist"],
                "album": ["Album"],
                "title": ["Title"],
                "lyrics": ["la la"],
                "albumartist": ["Compilation"],
                "metadata_block_picture": ["art"],
                "genre": ["Drop Me"],
                "custom": ["keepme"],
            },
        )
        from metadata_scrubber.core.scrubber import _load_audio

        audio = _load_audio(str(tmp_path / "track.flac"))
        preserved = _collect_tags_to_preserve(
            audio,
            ["CUSTOM"],
            preserve_lyrics=True,
            preserve_album_artist=True,
            preserve_embedded_art=True,
        )
        assert preserved["lyrics"] == ["la la"]
        assert preserved["albumartist"] == ["Compilation"]
        assert preserved["metadata_block_picture"] == ["art"]
        assert preserved["custom"] == ["keepme"]
        assert "genre" not in preserved

    def test_empty_value_skipped(self):
        """A Vorbis tag with an empty value list is skipped (line 127)."""
        audio = MagicMock()
        audio.filename = "track.flac"
        audio.tags.get.side_effect = lambda key, default=None: (
            ["Artist"] if key == "artist" else ["T"] if key == "title" else []
        )
        audio.tags.keys.return_value = ["artist", "album", "title", "empty"]
        preserved = _collect_tags_to_preserve(audio, [], False, False, False)
        assert "artist" in preserved and "empty" not in preserved

    def test_unreadable_vorbis_tag_skipped(self):
        """A Vorbis tag whose read raises is skipped (141-142)."""
        audio = MagicMock()
        audio.filename = "track.flac"
        real = {"artist": ["Artist"], "album": ["Album"], "title": ["Title"]}

        def _get(key, default=None):
            if key == "_boom":
                raise ValueError("read failure")
            return real.get(key, default)

        audio.tags.get.side_effect = _get
        audio.tags.keys.return_value = list(real) + ["_boom", "album"]
        preserved = _collect_tags_to_preserve(audio, [], False, False, False)
        assert set(preserved) == {"artist", "album", "title"}


class TestCollectTagsToPreserveMP4:
    """Direct tests of _collect_tags_to_preserve() for M4A/MP4 fixtures."""

    def test_essentials_always_preserved_when_flags_off(self, tmp_path):
        _make_m4a(
            tmp_path,
            tags={
                "\xa9ART": ["Artist"],
                "\xa9alb": ["Album"],
                "\xa9nam": ["Title"],
                "\xa9gen": ["Drop"],
            },
        )
        from metadata_scrubber.core.scrubber import _load_audio

        audio = _load_audio(str(tmp_path / "track.m4a"))
        preserved = _collect_tags_to_preserve(audio, [], False, False, False)
        assert preserved == {
            "\xa9ART": ["Artist"],
            "\xa9alb": ["Album"],
            "\xa9nam": ["Title"],
        }

    def test_flagged_and_custom_atoms(self, tmp_path):
        _make_m4a(
            tmp_path,
            tags={
                "\xa9ART": ["Artist"],
                "\xa9alb": ["Album"],
                "\xa9nam": ["Title"],
                "\xa9lyr": ["words"],
                "covr": [b"art"],
                "\xa9gen": ["Drop"],
                "----:com.apple.iTunes:BPM": [b"120"],
            },
        )
        from metadata_scrubber.core.scrubber import _load_audio

        audio = _load_audio(str(tmp_path / "track.m4a"))
        preserved = _collect_tags_to_preserve(
            audio,
            ["----:com.apple.iTunes:BPM"],
            preserve_lyrics=True,
            preserve_album_artist=False,
            preserve_embedded_art=True,
        )
        assert preserved["\xa9lyr"] == ["words"]
        assert "covr" in preserved
        assert "----:com.apple.iTunes:BPM" in preserved
        assert "\xa9gen" not in preserved

    def test_none_atom_skipped(self):
        """An MP4 atom whose value is None is skipped (line 153)."""
        audio = MagicMock()
        audio.filename = "track.m4a"
        audio.tags.get.side_effect = lambda key, default=None: {
            "\xa9ART": ["A"],
            "\xa9alb": ["B"],
            "\xa9nam": ["T"],
            "covr": None,
        }.get(key, default)
        audio.tags.keys.return_value = ["\xa9ART", "\xa9alb", "\xa9nam", "covr"]
        preserved = _collect_tags_to_preserve(
            audio,
            [],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=True,
        )
        assert set(preserved) == {"\xa9ART", "\xa9alb", "\xa9nam"}

    def test_unreadable_mp4_atom_skipped(self):
        """An MP4 atom whose read raises is skipped (160-161)."""
        audio = MagicMock()
        audio.filename = "track.m4a"
        real = {"\xa9ART": ["A"], "\xa9alb": ["B"], "\xa9nam": ["T"]}

        def _get(key, default=None):
            if key == "_boom":
                raise ValueError("read failure")
            return real.get(key, default)

        audio.tags.get.side_effect = _get
        audio.tags.keys.return_value = list(real) + ["_boom", "\xa9nam"]
        preserved = _collect_tags_to_preserve(audio, [], False, False, False)
        assert set(preserved) == {"\xa9ART", "\xa9alb", "\xa9nam"}


class TestRestoreTagsErrors:
    def test_unreadable_id3_frame_restore_skipped(self):
        """A failing tags.add() during restore is swallowed (179-180)."""
        audio = MagicMock()
        audio.filename = "track.mp3"
        audio.tags.add.side_effect = ValueError("cannot add frame")
        preserved = {"id3:TXXX:custom": MagicMock()}
        _restore_tags(audio, preserved)  # must not raise


class TestNoSupportedScrubExtensions:
    def test_non_scrub_extension_reports_no_files(self, tmp_path):
        """A directory with only unsupported files triggers on_error."""
        d = tmp_path / "only_txt"
        d.mkdir()
        (d / "notes.txt").write_text("hello")
        slot_vars, slot_q = _make_slot_fixtures()
        errors = []

        run_scrubbing(
            dir_path=str(d),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: None,
            on_error=lambda msg: errors.append(msg),
        )
        assert errors == ["No supported audio files found in the selected directory."]


class TestNoTagsFile:
    def test_file_without_tags_reports_no_tags(self, tmp_path):
        """A supported file with no tags hits the [NO TAGS] path (233-239)."""
        from mutagen.id3 import ID3
        from mutagen.mp3 import MP3

        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        audio = MP3(str(path), ID3=ID3)
        audio.delete()
        audio.save()

        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()

        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=threading.Lock(),
            on_progress=cb,
        )
        done = [r for r in results if r.get("display_text")]
        assert any("[NO TAGS]" in r.get("display_text", "") for r in done)


class TestTopLevelErrorHandler:
    def test_unexpected_error_reported_via_on_progress(self, tmp_path):
        """An unexpected exception is caught by the outer handler (305-309)."""
        from unittest.mock import patch

        _make_mp3(tmp_path, tags={"TPE1": "Artist"})
        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()
        real_slots = list(slot_vars)
        call_count = [0]

        def _flaky_set(value):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("slot display failure")

        with patch.object(real_slots[0], "set", side_effect=_flaky_set):
            process_single_file(
                name="track.mp3",
                dir_path=str(tmp_path),
                is_dry_run=False,
                preserve_list=[],
                preserve_lyrics=False,
                preserve_album_artist=False,
                preserve_embedded_art=False,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=threading.Lock(),
                on_progress=cb,
            )
        errors = [r for r in results if r.get("n_errors", 0) > 0]
        assert any("[ERROR]" in r.get("display_text", "") for r in errors)


# ═════════════════════════════════════════════════════════════════════════════
# Format discovery (R-05): advertise exactly what the loader table can open
# ═════════════════════════════════════════════════════════════════════════════

#: pydub/ffmpeg export format per advertised extension. A new loader without an
#: entry here fails the per-extension test by KeyError: the probe has to be
#: extended deliberately, it cannot silently skip the new format.
_EXPORT_FORMAT = {
    ".mp3": "mp3",
    ".flac": "flac",
    ".ogg": "ogg",
    ".opus": "opus",
    ".m4a": "mp4",
    ".mp4": "mp4",
    ".wav": "wav",
    ".aiff": "aiff",
    ".aif": "aiff",
}

#: Containers every full ffmpeg build can encode. If none of these can be
#: produced, `test_every_advertised_extension_loads` would skip every case and
#: pass vacuously, so it asserts this floor explicitly.
_CORE_CONTAINERS = (".mp3", ".flac", ".ogg", ".wav", ".m4a")

#: Containers the user's library may hold that the scrubber cannot scrub yet.
#: Absent from discovery on purpose - see the deferred APEv2 item in the plan.
_UNSUPPORTED_CONTAINERS = (".wv", ".ape", ".mpc", ".spx", ".dsf", ".wma")

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestFormatDiscoveryMatchesLoader:
    def test_supported_extensions_is_exactly_the_loader_table(self):
        """Discovery and loading derive from one table, so they cannot drift."""
        from metadata_scrubber.core import scrubber

        assert scrubber.SUPPORTED_EXTENSIONS == frozenset(scrubber._LOADERS)
        assert isinstance(scrubber.SUPPORTED_EXTENSIONS, frozenset)

    def test_every_advertised_extension_loads(self, tmp_path):
        """Every advertised extension has a loader that opens a real file."""
        import mutagen

        from metadata_scrubber.core.scrubber import (
            SUPPORTED_EXTENSIONS,
            _load_audio,
        )

        assert set(SUPPORTED_EXTENSIONS) == set(_EXPORT_FORMAT)

        exercised: list[str] = []
        for ext in sorted(SUPPORTED_EXTENSIONS):
            path = tmp_path / f"probe{ext}"
            try:
                AudioSegment.silent(duration=100).export(
                    str(path), format=_EXPORT_FORMAT[ext]
                )
            except Exception:  # ffmpeg absent, or built without this encoder
                continue
            audio = _load_audio(str(path))
            assert isinstance(audio, mutagen.FileType), ext
            exercised.append(ext)

        missing = [ext for ext in _CORE_CONTAINERS if ext not in exercised]
        assert not missing, (
            "core containers could not be generated, so the load check skipped "
            f"them instead of proving them: {missing} (exercised: {exercised})"
        )

    def test_unsupported_containers_are_not_advertised(self):
        """WavPack/APE/MPC/Speex/DSF/WMA stay out until a loader exists."""
        from metadata_scrubber.core.scrubber import SUPPORTED_EXTENSIONS

        assert SUPPORTED_EXTENSIONS.isdisjoint(_UNSUPPORTED_CONTAINERS)

    def test_scan_reports_no_unreadable_error_for_a_wavpack_file(self, tmp_path):
        """A `.wv` file is not discovered, so it is neither read nor reported.

        Before R-05 the suite-wide extension list offered the file and the
        missing loader turned it into a `[UNREADABLE]` error with a non-zero
        error count, on a file that is perfectly valid.
        """
        source = _REPO_ROOT / "tests" / "data" / "silence-44-s.wv"
        assert source.is_file()
        shutil.copyfile(source, tmp_path / "silence-44-s.wv")

        slot_vars, slot_q = _make_slot_fixtures()
        cb, results = _collect_progress()
        complete_calls: list[dict] = []
        errors: list[str] = []

        run_scrubbing(
            dir_path=str(tmp_path),
            is_dry_run=False,
            preserve_list=[],
            preserve_lyrics=False,
            preserve_album_artist=False,
            preserve_embedded_art=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=cb,
            on_complete=lambda **kw: complete_calls.append(kw),
            on_error=errors.append,
        )

        assert not complete_calls
        assert not [r for r in results if "UNREADABLE" in r.get("display_text", "")], (
            results
        )
        # Nothing was discovered, so the run reports "no supported files" rather
        # than a per-file error against a valid WavPack file.
        assert errors == ["No supported audio files found in the selected directory."]

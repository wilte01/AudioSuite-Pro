"""
Tests for genre_sync.core.file_processor
Gap G-34: process_single_file(), run_processing()

Strategy: mock the one tag-handler load (read_custom_genre_fields,
          read_album_artist, read_genre share it) and write_genre_sync_result
          so no real audio files are needed for unit tests. Integration tests
          use real MP3 fixtures.

Changed in 1.4.0: tests patch the single handler load instead of the three
removed facade imports (PLAN D55).
"""

import threading
from queue import Queue
from unittest.mock import MagicMock, patch

from mutagen.id3 import ID3, TXXX
from mutagen.mp3 import MP3
from pydub import AudioSegment

from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from genre_sync.core.file_processor import process_single_file, run_processing

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_slots(n=DEFAULT_MAX_WORKERS):
    slot_vars = [MagicMock() for _ in range(n)]
    slot_q = Queue()
    for i in range(n):
        slot_q.put(i)
    return slot_vars, slot_q


def _make_mp3(tmp_path, name="track.mp3", titlegenre=None, genre=None):
    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="mp3")
    audio = MP3(str(path), ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    if titlegenre:
        audio.tags.add(TXXX(encoding=3, desc="TITLEGENRE", text=titlegenre))
    if genre:
        from mutagen.id3 import TCON

        audio.tags.add(TCON(encoding=3, text=genre))
    audio.save()
    return str(path)


def _fields(titlegenre=None, artistgenre=None, albumgenre=None, albumartistgenre=None):
    return {
        "TITLEGENRE": titlegenre,
        "ARTISTGENRE": artistgenre,
        "ALBUMGENRE": albumgenre,
        "ALBUMARTISTGENRE": albumartistgenre,
        "GENREDERIVED": None,
        "ALBUMDERIVED": None,
    }


def _mock_handler(fields=None, album_artist=None, current_genre=None):
    """A handler mock whose three genre reads answer independently."""
    handler = MagicMock()
    handler.read_custom_genre_fields.return_value = (
        fields if fields is not None else _fields()
    )
    handler.read_album_artist.return_value = album_artist
    handler.read_genre.return_value = current_genre
    return handler


def _handler_patch(handler_or_effect):
    """Patch the one handler load the worker performs.

    Pass an exception instance to make the load itself fail.
    """
    if isinstance(handler_or_effect, BaseException):
        return patch(
            "genre_sync.core.file_processor.TagHandlerFactory.get_handler",
            side_effect=handler_or_effect,
        )
    return patch(
        "genre_sync.core.file_processor.TagHandlerFactory.get_handler",
        return_value=handler_or_effect,
    )


# ═════════════════════════════════════════════════════════════════════════════
# process_single_file — unit (all I/O mocked)
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessSingleFileUnit:
    def _call(
        self, tmp_path, fields, current_genre=None, album_artist=None, is_dry_run=True
    ):
        slot_vars, slot_q = _make_slots()
        results = []
        (tmp_path / "track.mp3").write_bytes(b"x")  # file must exist for normpath

        with (
            _handler_patch(
                _mock_handler(
                    fields=fields,
                    album_artist=album_artist,
                    current_genre=current_genre,
                )
            ),
            patch(
                "genre_sync.core.file_processor.write_genre_sync_result"
            ) as mock_write,
        ):
            process_single_file(
                filename="track.mp3",
                dir_path=str(tmp_path),
                is_dry_run=is_dry_run,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=threading.Lock(),
                on_progress=lambda **kw: results.append(kw),
            )
        return results, mock_write

    # ── no_genre path ─────────────────────────────────────────────────────────

    def test_one_handler_load_per_file(self, tmp_path):
        slot_vars, slot_q = _make_slots()
        (tmp_path / "track.mp3").write_bytes(b"x")
        with _handler_patch(_mock_handler()) as factory:
            process_single_file(
                filename="track.mp3",
                dir_path=str(tmp_path),
                is_dry_run=True,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=threading.Lock(),
                on_progress=lambda **kw: None,
            )
        assert factory.call_count == 1

    def test_no_genre_fields_reports_no_genre(self, tmp_path):
        results, _ = self._call(tmp_path, _fields())
        assert results[0]["n_no_genre"] == 1

    def test_no_genre_does_not_call_write(self, tmp_path):
        results, mock_write = self._call(tmp_path, _fields())
        mock_write.assert_not_called()
        assert results[0]["n_no_genre"] == 1

    def test_no_genre_log_entry_populated(self, tmp_path):
        results, _ = self._call(tmp_path, _fields())
        assert results[0]["log_no_genre"] != ""

    def test_no_genre_display_contains_no_change(self, tmp_path):
        results, _ = self._call(tmp_path, _fields())
        assert "NO_CHANGE" in results[0]["display_text"]
        assert "No genre fields available" in results[0]["display_text"]

    # ── skipped path (genre already correct) ──────────────────────────────────

    def test_already_correct_genre_reports_skipped(self, tmp_path):
        results, _ = self._call(
            tmp_path, _fields(titlegenre="Rock"), current_genre="Rock"
        )
        assert results[0]["n_skipped"] == 1

    def test_already_correct_no_write(self, tmp_path):
        results, mock_write = self._call(
            tmp_path, _fields(titlegenre="Rock"), current_genre="Rock"
        )
        mock_write.assert_not_called()
        assert results[0]["n_skipped"] == 1

    def test_skipped_log_entry_contains_filename(self, tmp_path):
        results, _ = self._call(
            tmp_path, _fields(titlegenre="Rock"), current_genre="Rock"
        )
        assert "track.mp3" in results[0]["log_skipped"]

    # ── dry run update path ───────────────────────────────────────────────────

    def test_dry_run_reports_updated(self, tmp_path):
        results, _ = self._call(
            tmp_path, _fields(titlegenre="Jazz"), current_genre="Rock", is_dry_run=True
        )
        assert results[0]["n_updated"] == 1

    def test_dry_run_does_not_write(self, tmp_path):
        results, mock_write = self._call(
            tmp_path, _fields(titlegenre="Jazz"), current_genre="Rock", is_dry_run=True
        )
        mock_write.assert_not_called()
        assert results[0]["n_updated"] == 1
        assert "Jazz" in results[0]["display_text"]

    def test_dry_run_display_contains_dry_run(self, tmp_path):
        results, _ = self._call(
            tmp_path, _fields(titlegenre="Jazz"), current_genre="Rock", is_dry_run=True
        )
        assert (
            "DRY_RUN" in results[0]["display_text"]
            or "DRY RUN" in results[0]["display_text"]
        )

    def test_dry_run_display_contains_genre(self, tmp_path):
        results, _ = self._call(
            tmp_path, _fields(titlegenre="Jazz"), current_genre="Rock", is_dry_run=True
        )
        assert "Jazz" in results[0]["display_text"]

    def test_dry_run_display_shows_previous_genre(self, tmp_path):
        results, _ = self._call(
            tmp_path, _fields(titlegenre="Jazz"), current_genre="Rock", is_dry_run=True
        )
        assert "Rock" in results[0]["display_text"]

    # ── live update path ──────────────────────────────────────────────────────

    def test_live_calls_write(self, tmp_path):
        _, mock_write = self._call(
            tmp_path, _fields(titlegenre="Jazz"), current_genre="Rock", is_dry_run=False
        )
        mock_write.assert_called_once()

    def test_live_writes_correct_genre(self, tmp_path):
        _, mock_write = self._call(
            tmp_path, _fields(titlegenre="Jazz"), current_genre="Rock", is_dry_run=False
        )
        call_args = mock_write.call_args[0]
        assert "Jazz" in call_args

    def test_live_display_contains_updated(self, tmp_path):
        results, _ = self._call(
            tmp_path, _fields(titlegenre="Jazz"), current_genre="Rock", is_dry_run=False
        )
        assert "UPDATED" in results[0]["display_text"]

    def test_live_reports_zero_errors(self, tmp_path):
        results, _ = self._call(
            tmp_path, _fields(titlegenre="Jazz"), current_genre="Rock", is_dry_run=False
        )
        assert results[0]["n_errors"] == 0

    # ── slot management ───────────────────────────────────────────────────────

    def test_slot_always_returned(self, tmp_path):
        slot_vars, slot_q = _make_slots(n=1)
        (tmp_path / "t.mp3").write_bytes(b"x")
        with _handler_patch(_mock_handler(fields=_fields())):
            process_single_file(
                filename="t.mp3",
                dir_path=str(tmp_path),
                is_dry_run=True,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=threading.Lock(),
                on_progress=lambda **kw: None,
            )
        assert slot_q.qsize() == 1

    def test_slot_returned_even_on_exception(self, tmp_path):
        slot_vars, slot_q = _make_slots(n=1)
        (tmp_path / "t.mp3").write_bytes(b"x")
        with _handler_patch(RuntimeError("read failed")):
            process_single_file(
                filename="t.mp3",
                dir_path=str(tmp_path),
                is_dry_run=True,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=threading.Lock(),
                on_progress=lambda **kw: None,
            )
        assert slot_q.qsize() == 1

    def test_exception_reports_error(self, tmp_path):
        slot_vars, slot_q = _make_slots()
        (tmp_path / "t.mp3").write_bytes(b"x")
        results = []
        with _handler_patch(RuntimeError("bang")):
            process_single_file(
                filename="t.mp3",
                dir_path=str(tmp_path),
                is_dry_run=True,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=threading.Lock(),
                on_progress=lambda **kw: results.append(kw),
            )
        assert results[0]["n_errors"] == 1

    # ── VA vs regular album routing ───────────────────────────────────────────

    def test_va_uses_artist_genre_over_album_genre(self, tmp_path):
        results, _ = self._call(
            tmp_path,
            _fields(artistgenre="Soul", albumgenre="Pop"),
            current_genre=None,
            album_artist="Various Artists",
            is_dry_run=True,
        )
        assert "Soul" in results[0]["display_text"]

    def test_regular_uses_album_genre_over_artist_genre(self, tmp_path):
        results, _ = self._call(
            tmp_path,
            _fields(artistgenre="Soul", albumgenre="Jazz"),
            current_genre=None,
            album_artist="Miles Davis",
            is_dry_run=True,
        )
        assert "Jazz" in results[0]["display_text"]

    def test_filename_truncation_long_name(self, tmp_path):
        long_name = "a" * 60 + ".mp3"
        slot_vars, slot_q = _make_slots()
        (tmp_path / long_name).write_bytes(b"x")
        results = []
        with (
            _handler_patch(_mock_handler(fields=_fields(titlegenre="Rock"))),
            patch("genre_sync.core.file_processor.write_genre_sync_result"),
        ):
            process_single_file(
                filename=long_name,
                dir_path=str(tmp_path),
                is_dry_run=True,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=threading.Lock(),
                on_progress=lambda **kw: results.append(kw),
            )
        truncated_display = "a" * 47 + "..."
        assert truncated_display in results[0]["display_text"]

    def test_live_log_updated_contains_previous_genre(self, tmp_path):
        results, _ = self._call(
            tmp_path,
            _fields(titlegenre="Jazz"),
            current_genre="Rock",
            is_dry_run=False,
        )
        assert "Rock" in results[0]["log_updated"]
        assert "Previous: Rock" in results[0]["log_updated"]

    def test_live_log_updated_no_previous_when_no_current_genre(self, tmp_path):
        results, _ = self._call(
            tmp_path,
            _fields(titlegenre="Jazz"),
            current_genre=None,
            is_dry_run=False,
        )
        assert "Previous:" not in results[0]["log_updated"]


# ═════════════════════════════════════════════════════════════════════════════
# run_processing
# ═════════════════════════════════════════════════════════════════════════════


class TestRunProcessing:
    def _run(self, tmp_path, fields_map=None, genre_map=None, is_dry_run=True):
        """fields_map: {name: fields_dict}, genre_map: {name: current_genre}"""
        slot_vars, slot_q = _make_slots()
        progress, complete, errors = [], [], []
        fields_map = fields_map or {}
        genre_map = genre_map or {}

        def handler_for(path):
            name = path.split("/")[-1].split("\\")[-1]
            return _mock_handler(
                fields=fields_map.get(name, _fields()),
                current_genre=genre_map.get(name),
            )

        with (
            patch(
                "genre_sync.core.file_processor.TagHandlerFactory.get_handler",
                side_effect=handler_for,
            ),
            patch("genre_sync.core.file_processor.write_genre_sync_result"),
        ):
            run_processing(
                dir_path=str(tmp_path),
                is_dry_run=is_dry_run,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=lambda **kw: progress.append(kw),
                on_complete=lambda **kw: complete.append(kw),
                on_error=lambda msg: errors.append(msg),
            )
        return progress, complete, errors

    def test_empty_directory_calls_on_error(self, tmp_path):
        _, _, errors = self._run(tmp_path)
        assert len(errors) == 1

    def test_nonexistent_directory_calls_on_error(self, tmp_path):
        _, _, errors = self._run(tmp_path / "missing")
        assert len(errors) == 1

    def test_on_complete_called_once(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3")
        _, complete, _ = self._run(tmp_path)
        assert len(complete) == 1

    def test_total_matches_file_count(self, tmp_path):
        for i in range(4):
            _make_mp3(tmp_path, f"t{i}.mp3")
        _, complete, _ = self._run(tmp_path)
        assert complete[0]["total"] == 4

    def test_updated_count_correct(self, tmp_path):
        for i in range(3):
            _make_mp3(tmp_path, f"t{i}.mp3")
        fields_map = {f"t{i}.mp3": _fields(titlegenre="Rock") for i in range(3)}
        genre_map = {f"t{i}.mp3": None for i in range(3)}  # no current genre
        _, complete, _ = self._run(
            tmp_path, fields_map=fields_map, genre_map=genre_map, is_dry_run=True
        )
        assert complete[0]["updated"] == 3

    def test_skipped_count_correct(self, tmp_path):
        for i in range(2):
            _make_mp3(tmp_path, f"t{i}.mp3")
        fields_map = {f"t{i}.mp3": _fields(titlegenre="Jazz") for i in range(2)}
        genre_map = {f"t{i}.mp3": "Jazz" for i in range(2)}  # already set
        _, complete, _ = self._run(tmp_path, fields_map=fields_map, genre_map=genre_map)
        assert complete[0]["skipped"] == 2

    def test_no_genre_count_correct(self, tmp_path):
        for i in range(2):
            _make_mp3(tmp_path, f"t{i}.mp3")
        _, complete, _ = self._run(tmp_path)  # all have no genre fields
        assert complete[0]["no_genre"] == 2

    def test_non_audio_files_excluded(self, tmp_path):
        (tmp_path / "cover.jpg").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")
        _make_mp3(tmp_path, "t.mp3")
        _, complete, _ = self._run(tmp_path)
        assert complete[0]["total"] == 1

    def test_duration_secs_in_complete(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3")
        _, complete, _ = self._run(tmp_path)
        assert complete[0]["duration_secs"] >= 0

    def test_log_lists_in_complete(self, tmp_path):
        _make_mp3(tmp_path, "t.mp3")
        _, complete, _ = self._run(tmp_path)
        for key in ("log_updated", "log_skipped", "log_no_genre", "log_errors"):
            assert isinstance(complete[0][key], list)

    def test_mixed_status_counts_aggregate(self, tmp_path):
        for i in range(4):
            _make_mp3(tmp_path, f"t{i}.mp3")
        fields_map = {
            "t0.mp3": _fields(titlegenre="Rock"),  # updated (no current)
            "t1.mp3": _fields(titlegenre="Jazz"),  # skipped (already Jazz)
            "t2.mp3": _fields(),  # no_genre
            "t3.mp3": _fields(albumgenre="Blues"),  # updated (no current)
        }
        genre_map = {
            "t0.mp3": None,
            "t1.mp3": "Jazz",
            "t2.mp3": None,
            "t3.mp3": None,
        }
        _, complete, _ = self._run(
            tmp_path, fields_map=fields_map, genre_map=genre_map, is_dry_run=True
        )
        assert complete[0]["updated"] == 2
        assert complete[0]["skipped"] == 1
        assert complete[0]["no_genre"] == 1
        assert complete[0]["errors"] == 0
        assert complete[0]["total"] == 4

    def test_error_count_aggregated(self, tmp_path):
        for i in range(2):
            _make_mp3(tmp_path, f"t{i}.mp3")
        fields_map = {f"t{i}.mp3": _fields(titlegenre="Rock") for i in range(2)}
        genre_map = {f"t{i}.mp3": None for i in range(2)}

        # Make the handler load fail for the second file
        def handler_for(path):
            name = path.split("/")[-1].split("\\")[-1]
            if name == "t1.mp3":
                raise RuntimeError("Simulated failure")
            return _mock_handler(
                fields=fields_map.get(name, _fields()),
                current_genre=genre_map.get(name),
            )

        slot_vars, slot_q = _make_slots()
        progress, complete, errors = [], [], []

        with (
            patch(
                "genre_sync.core.file_processor.TagHandlerFactory.get_handler",
                side_effect=handler_for,
            ),
            patch("genre_sync.core.file_processor.write_genre_sync_result"),
        ):
            run_processing(
                dir_path=str(tmp_path),
                is_dry_run=True,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=lambda **kw: progress.append(kw),
                on_complete=lambda **kw: complete.append(kw),
                on_error=lambda msg: errors.append(msg),
            )
        assert complete[0]["updated"] == 1
        assert complete[0]["errors"] == 1
        assert complete[0]["total"] == 2

    def _skip_test_checkpoint_creation_failure_calls_on_error(self, tmp_path):
        """Removed with error recovery strip — no more checkpoint creation."""
        pass


class TestUndoBatchRecording:
    """Phase 2: worker threads must join the orchestrator's active undo
    batch so tag snapshots are recorded against it (batch_undo.use_batch)."""

    def _run(self, tmp_path, is_dry_run):
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches

        undo_db = tmp_path / "undo_log.db"
        (tmp_path / "a.mp3").write_bytes(b"")
        (tmp_path / "b.mp3").write_bytes(b"")
        slot_vars, slot_q = _make_slots()

        handler = MagicMock()
        handler.get_raw_tags.return_value = {"TCON": "Rock"}
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler

        with (
            _handler_patch(_mock_handler(fields=_fields(titlegenre="Rock"))),
            patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory", shared_factory
            ),
            patch(
                "audio_suite_shared.tag_helper_reader.TagHandlerFactory", shared_factory
            ),
            patch(
                "audio_suite_shared.tag_helper_writer.TagHandlerFactory", shared_factory
            ),
        ):
            with active_batch("genre_sync", "tag_edit", db_path=undo_db):
                run_processing(
                    dir_path=str(tmp_path),
                    is_dry_run=is_dry_run,
                    slot_vars=slot_vars,
                    slot_queue=slot_q,
                    on_progress=MagicMock(),
                    on_complete=MagicMock(),
                    on_error=MagicMock(),
                )

        return list_recent_batches(limit=10, db_path=undo_db)

    def test_live_mode_records_snapshots_from_workers(self, tmp_path):
        batches = self._run(tmp_path, is_dry_run=False)
        assert len(batches) == 1
        assert batches[0].tool_name == "genre_sync"
        assert batches[0].operation_type == "tag_edit"
        assert batches[0].record_count == 2

    def test_dry_run_prunes_empty_batch(self, tmp_path):
        assert self._run(tmp_path, is_dry_run=True) == []

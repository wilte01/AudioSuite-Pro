"""
Tests for audio_refinery.core.registry.CompletionRegistry
Gap G-32: hash_file, is_done, mark_done, reset, persist-across-instantiation,
          corrupt-log recovery, thread safety.
"""

import threading
from pathlib import Path

from audio_refinery.core.registry import LOG_FILENAME, CompletionRegistry, _sha256

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_file(
    tmp_path: Path, name: str = "track.mp3", content: bytes = b"audio"
) -> Path:
    f = tmp_path / name
    f.write_bytes(content)
    return f


# ── _sha256 ───────────────────────────────────────────────────────────────────


class TestSha256:
    def test_returns_64_char_hex_string(self, tmp_path):
        f = _make_file(tmp_path)
        digest = _sha256(f)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_deterministic(self, tmp_path):
        f = _make_file(tmp_path)
        assert _sha256(f) == _sha256(f)

    def test_different_content_gives_different_hash(self, tmp_path):
        f1 = _make_file(tmp_path, "a.mp3", b"content_a")
        f2 = _make_file(tmp_path, "b.mp3", b"content_b")
        assert _sha256(f1) != _sha256(f2)

    def test_same_content_same_hash(self, tmp_path):
        f1 = _make_file(tmp_path, "a.mp3", b"identical")
        f2 = _make_file(tmp_path, "b.mp3", b"identical")
        assert _sha256(f1) == _sha256(f2)


# ── Initialisation ────────────────────────────────────────────────────────────


class TestInit:
    def test_log_path_property(self, tmp_path):
        r = CompletionRegistry(tmp_path)
        assert r.log_path == tmp_path / LOG_FILENAME

    def test_completed_count_zero_on_fresh_directory(self, tmp_path):
        r = CompletionRegistry(tmp_path)
        assert r.completed_count == 0

    def test_no_log_file_created_on_init(self, tmp_path):
        CompletionRegistry(tmp_path)
        assert not (tmp_path / LOG_FILENAME).exists()

    def test_loads_existing_log_file(self, tmp_path):
        f = _make_file(tmp_path)
        r1 = CompletionRegistry(tmp_path)
        h = r1.hash_file(f)
        r1.mark_done(f, h)
        # Second instance should load the persisted entry
        r2 = CompletionRegistry(tmp_path)
        assert r2.completed_count == 1
        assert r2.is_done(f, h)


# ── hash_file ─────────────────────────────────────────────────────────────────


class TestHashFile:
    def test_returns_string(self, tmp_path):
        f = _make_file(tmp_path)
        r = CompletionRegistry(tmp_path)
        assert isinstance(r.hash_file(f), str)

    def test_matches_standalone_sha256(self, tmp_path):
        f = _make_file(tmp_path)
        r = CompletionRegistry(tmp_path)
        assert r.hash_file(f) == _sha256(f)

    def test_changes_when_file_content_changes(self, tmp_path):
        f = _make_file(tmp_path, content=b"original")
        r = CompletionRegistry(tmp_path)
        h1 = r.hash_file(f)
        f.write_bytes(b"modified")
        h2 = r.hash_file(f)
        assert h1 != h2


# ── is_done / mark_done ───────────────────────────────────────────────────────


class TestIsDoneMarkDone:
    def test_fresh_file_is_not_done(self, tmp_path):
        f = _make_file(tmp_path)
        r = CompletionRegistry(tmp_path)
        assert r.is_done(f, r.hash_file(f)) is False

    def test_marked_file_is_done(self, tmp_path):
        f = _make_file(tmp_path)
        r = CompletionRegistry(tmp_path)
        h = r.hash_file(f)
        r.mark_done(f, h)
        assert r.is_done(f, h) is True

    def test_wrong_hash_is_not_done(self, tmp_path):
        f = _make_file(tmp_path)
        r = CompletionRegistry(tmp_path)
        h = r.hash_file(f)
        r.mark_done(f, h)
        assert r.is_done(f, "a" * 64) is False

    def test_different_file_not_done(self, tmp_path):
        f1 = _make_file(tmp_path, "a.mp3")
        f2 = _make_file(tmp_path, "b.mp3")
        r = CompletionRegistry(tmp_path)
        r.mark_done(f1, r.hash_file(f1))
        assert r.is_done(f2, r.hash_file(f2)) is False

    def test_mark_done_increments_count(self, tmp_path):
        f = _make_file(tmp_path)
        r = CompletionRegistry(tmp_path)
        r.mark_done(f, r.hash_file(f))
        assert r.completed_count == 1

    def test_mark_done_creates_log_file(self, tmp_path):
        f = _make_file(tmp_path)
        r = CompletionRegistry(tmp_path)
        r.mark_done(f, r.hash_file(f))
        assert (tmp_path / LOG_FILENAME).exists()

    def test_multiple_files_tracked_independently(self, tmp_path):
        files = [_make_file(tmp_path, f"t{i}.mp3", bytes([i])) for i in range(5)]
        r = CompletionRegistry(tmp_path)
        for f in files[:3]:
            r.mark_done(f, r.hash_file(f))
        assert r.completed_count == 3
        for f in files[:3]:
            assert r.is_done(f, r.hash_file(f))
        for f in files[3:]:
            assert not r.is_done(f, r.hash_file(f))

    def test_modified_file_no_longer_done(self, tmp_path):
        f = _make_file(tmp_path, content=b"original")
        r = CompletionRegistry(tmp_path)
        h = r.hash_file(f)
        r.mark_done(f, h)
        f.write_bytes(b"modified")
        new_h = r.hash_file(f)
        assert not r.is_done(f, new_h)


# ── Persistence ───────────────────────────────────────────────────────────────


class TestPersistence:
    def test_entries_survive_across_instances(self, tmp_path):
        f = _make_file(tmp_path)
        r1 = CompletionRegistry(tmp_path)
        h = r1.hash_file(f)
        r1.mark_done(f, h)
        r2 = CompletionRegistry(tmp_path)
        assert r2.is_done(f, h)

    def test_log_file_format_is_valid(self, tmp_path):
        f = _make_file(tmp_path, "track.mp3")
        r = CompletionRegistry(tmp_path)
        h = r.hash_file(f)
        r.mark_done(f, h)
        content = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")
        assert h in content
        assert "track.mp3" in content

    def test_log_file_has_header_comment(self, tmp_path):
        f = _make_file(tmp_path)
        r = CompletionRegistry(tmp_path)
        r.mark_done(f, r.hash_file(f))
        first_line = (
            (tmp_path / LOG_FILENAME).read_text(encoding="utf-8").splitlines()[0]
        )
        assert first_line.startswith("#")

    def test_multiple_mark_done_all_persist(self, tmp_path):
        files = [_make_file(tmp_path, f"t{i}.mp3", bytes([i])) for i in range(4)]
        r1 = CompletionRegistry(tmp_path)
        hashes = {f: r1.hash_file(f) for f in files}
        for f in files:
            r1.mark_done(f, hashes[f])
        r2 = CompletionRegistry(tmp_path)
        assert r2.completed_count == 4
        for f in files:
            assert r2.is_done(f, hashes[f])

    def test_corrupt_log_file_loads_without_crash(self, tmp_path):
        """Lines with only one token (no space) are silently skipped."""
        log = tmp_path / LOG_FILENAME
        log.write_text("# comment\n!@#$%single_token_no_space\n\n", encoding="utf-8")
        r = CompletionRegistry(tmp_path)  # must not raise
        assert r.completed_count == 0

    def test_empty_log_file_loads_cleanly(self, tmp_path):
        (tmp_path / LOG_FILENAME).write_text("", encoding="utf-8")
        r = CompletionRegistry(tmp_path)
        assert r.completed_count == 0

    def test_comment_lines_in_log_ignored(self, tmp_path):
        log = tmp_path / LOG_FILENAME
        log.write_text("# this is a comment\n# another comment\n", encoding="utf-8")
        r = CompletionRegistry(tmp_path)
        assert r.completed_count == 0


# ── reset ─────────────────────────────────────────────────────────────────────


class TestReset:
    def test_reset_clears_in_memory_entries(self, tmp_path):
        f = _make_file(tmp_path)
        r = CompletionRegistry(tmp_path)
        r.mark_done(f, r.hash_file(f))
        r.reset()
        assert r.completed_count == 0

    def test_reset_deletes_log_file(self, tmp_path):
        f = _make_file(tmp_path)
        r = CompletionRegistry(tmp_path)
        r.mark_done(f, r.hash_file(f))
        r.reset()
        assert not (tmp_path / LOG_FILENAME).exists()

    def test_reset_when_no_log_does_not_raise(self, tmp_path):
        r = CompletionRegistry(tmp_path)
        r.reset()  # must not raise

    def test_is_done_false_after_reset(self, tmp_path):
        f = _make_file(tmp_path)
        r = CompletionRegistry(tmp_path)
        h = r.hash_file(f)
        r.mark_done(f, h)
        r.reset()
        assert not r.is_done(f, h)

    def test_new_instance_empty_after_reset(self, tmp_path):
        f = _make_file(tmp_path)
        r1 = CompletionRegistry(tmp_path)
        r1.mark_done(f, r1.hash_file(f))
        r1.reset()
        r2 = CompletionRegistry(tmp_path)
        assert r2.completed_count == 0


# ── Thread safety ─────────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_mark_done_all_recorded(self, tmp_path):
        files = [_make_file(tmp_path, f"t{i}.mp3", bytes([i])) for i in range(20)]
        r = CompletionRegistry(tmp_path)
        hashes = {f: r.hash_file(f) for f in files}

        def worker(f):
            r.mark_done(f, hashes[f])

        threads = [threading.Thread(target=worker, args=(f,)) for f in files]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert r.completed_count == 20
        for f in files:
            assert r.is_done(f, hashes[f])

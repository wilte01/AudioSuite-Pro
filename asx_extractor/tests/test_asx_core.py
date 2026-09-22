"""
Tests for asx_extractor.core.asx_parser and asx_extractor.core.file_ops
Gap G-09: process_asx_file(), get_fallback_audio_path()
Gap G-10: copy_audio_file(), remove_asx_file(), write_extraction_log()
"""

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from asx_extractor.core.asx_parser import (
    ASX_REF_PATTERN,
    get_fallback_audio_path,
    process_asx_file,
)
from asx_extractor.core.file_ops import (
    copy_audio_file,
    remove_asx_file,
    write_extraction_log,
)

# ─────────────────────────────────────────────────────────────────────────────
# G-09 — asx_parser
# ─────────────────────────────────────────────────────────────────────────────


def _write_asx(path: Path, href: str) -> Path:
    """Write a minimal ASX file with a single <ref href="..."> element."""
    path.write_text(
        f'<ASX Version="3.0">\n  <Entry>\n    <ref href="{href}"/>\n  </Entry>\n</ASX>',
        encoding="utf-8",
    )
    return path


# ── get_fallback_audio_path ────────────────────────────────────────────────


class TestGetFallbackAudioPath:
    def test_mp3_sibling_flac(self, tmp_path):
        (tmp_path / "track.flac").write_bytes(b"x")
        p = tmp_path / "track.mp3"  # does not exist itself
        assert get_fallback_audio_path(p) == (tmp_path / "track.flac").resolve()

    def test_flac_sibling_mp3(self, tmp_path):
        (tmp_path / "song.mp3").write_bytes(b"x")
        p = tmp_path / "song.flac"  # does not exist itself
        assert get_fallback_audio_path(p) == (tmp_path / "song.mp3").resolve()

    def test_first_supported_extension_wins(self, tmp_path):
        """Candidates are probed in SUPPORTED_EXTENSIONS order, so flac
        (index 1) wins over ogg (index 2) when both exist."""
        (tmp_path / "track.ogg").write_bytes(b"x")
        (tmp_path / "track.flac").write_bytes(b"x")
        p = tmp_path / "track.mp3"
        assert get_fallback_audio_path(p) == (tmp_path / "track.flac").resolve()

    def test_excludes_the_original_extension(self, tmp_path):
        """An existing same-stem sibling that IS the original href
        extension is skipped — only alternate files qualify."""
        (tmp_path / "track.mp3").write_bytes(b"x")
        assert get_fallback_audio_path(tmp_path / "track.mp3") is None

    def test_case_insensitive_exclusion(self, tmp_path):
        (tmp_path / "Track.MP3").write_bytes(b"x")
        assert get_fallback_audio_path(tmp_path / "TRACK.mp3") is None

    def test_unknown_input_extension_uses_supported_sibling(self, tmp_path):
        (tmp_path / "track.mp3").write_bytes(b"x")
        p = tmp_path / "track.xyz"  # not a supported extension — no exclusion
        assert get_fallback_audio_path(p) == (tmp_path / "track.mp3").resolve()

    def test_no_existing_sibling_returns_none(self, tmp_path):
        assert get_fallback_audio_path(tmp_path / "track.mp3") is None

    def test_preserves_parent_directory(self, tmp_path):
        deep = tmp_path / "deep" / "nested" / "dir"
        deep.mkdir(parents=True)
        (deep / "track.flac").write_bytes(b"x")
        result = get_fallback_audio_path(deep / "track.mp3")
        assert result is not None
        assert result.parent == deep

    def test_preserves_stem(self, tmp_path):
        (tmp_path / "My Track Name.mp3").write_bytes(b"x")
        result = get_fallback_audio_path(tmp_path / "My Track Name.flac")
        assert result is not None
        assert result.stem == "My Track Name"

    def test_no_extension_returns_none(self, tmp_path):
        assert get_fallback_audio_path(tmp_path / "tracknoext") is None


# ── ASX_REF_PATTERN ────────────────────────────────────────────────────────


class TestAsxRefPattern:
    def test_matches_standard_ref(self):
        m = ASX_REF_PATTERN.search('<ref href="/music/track.mp3"/>')
        assert m and m.group(1) == "/music/track.mp3"

    def test_matches_case_insensitive_tag(self):
        m = ASX_REF_PATTERN.search('<REF HREF="/music/track.flac"/>')
        assert m and m.group(1) == "/music/track.flac"

    def test_no_match_on_missing_href(self):
        assert ASX_REF_PATTERN.search("<ref/>") is None

    def test_matches_with_spaces_before_href(self):
        m = ASX_REF_PATTERN.search('<ref   href="/track.mp3"/>')
        assert m is not None

    def test_single_quoted_href_does_not_match(self):
        # Gap: documents current behaviour. The pattern is hard-coded to
        # double quotes only, so a single-quoted href (valid-ish XML/ASX
        # in the wild) is NOT matched. Not asserting this is a "bug" —
        # per the Data Premise Verification Rule, whether Terry's actual
        # ASX files ever use single quotes is unconfirmed, so this test
        # only pins down existing behaviour rather than changing it.
        m = ASX_REF_PATTERN.search("<ref href='/music/track.mp3'/>")
        assert m is None

    def test_first_of_multiple_refs_wins(self):
        # Gap: real ASX playlists can contain multiple <ref> entries
        # (e.g. alternate bitrate streams). search() only ever returns
        # the first match — pin down that this is deliberate/expected
        # behaviour, not an oversight.
        content = '<ref href="/first.mp3"/><ref href="/second.mp3"/>'
        m = ASX_REF_PATTERN.search(content)
        assert m.group(1) == "/first.mp3"


# ── process_asx_file — success paths ─────────────────────────────────────


class TestProcessAsxFileSuccess:
    def test_primary_audio_file_exists(self, tmp_path):
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"x")
        asx = _write_asx(tmp_path / "track.asx", str(audio.resolve()))

        result = process_asx_file(asx, tmp_path)
        assert result["success"] is True
        assert result["audio_path"] == audio.resolve()
        assert result["asx_fn"] == "track.asx"
        assert result["asx_path"] == asx

    def test_fallback_flac_when_mp3_missing(self, tmp_path):
        flac = tmp_path / "track.flac"
        flac.write_bytes(b"x")
        mp3_path = tmp_path / "track.mp3"  # does NOT exist
        asx = _write_asx(tmp_path / "track.asx", str(mp3_path.resolve()))

        result = process_asx_file(asx, tmp_path)
        assert result["success"] is True
        assert result["audio_path"] == flac.resolve()

    def test_fallback_mp3_when_flac_missing(self, tmp_path):
        mp3 = tmp_path / "track.mp3"
        mp3.write_bytes(b"x")
        flac_path = tmp_path / "track.flac"  # does NOT exist
        asx = _write_asx(tmp_path / "track.asx", str(flac_path.resolve()))

        result = process_asx_file(asx, tmp_path)
        assert result["success"] is True
        assert result["audio_path"] == mp3.resolve()

    def test_fallback_ogg_when_mp3_missing(self, tmp_path):
        ogg = tmp_path / "track.ogg"
        ogg.write_bytes(b"x")
        mp3_path = tmp_path / "track.mp3"  # does NOT exist
        asx = _write_asx(tmp_path / "track.asx", str(mp3_path.resolve()))

        result = process_asx_file(asx, tmp_path)
        assert result["success"] is True
        assert result["audio_path"] == ogg.resolve()

    def test_first_ref_used_when_asx_has_multiple_entries(self, tmp_path):
        first = tmp_path / "first.mp3"
        first.write_bytes(b"x")
        second = tmp_path / "second.mp3"
        second.write_bytes(b"x")
        asx = tmp_path / "multi.asx"
        asx.write_text(
            f'<ASX><Entry><ref href="{first.resolve()}"/></Entry>'
            f'<Entry><ref href="{second.resolve()}"/></Entry></ASX>',
            encoding="utf-8",
        )
        result = process_asx_file(asx, tmp_path)
        assert result["success"] is True
        assert result["audio_path"] == first.resolve()


class TestProcessAsxFileKnownEdgeCase:
    """Documents (does not fix) a discovered edge case: Path.exists()
    returns True for directories, not only regular files. If an href
    ever resolves to a directory, process_asx_file currently reports
    success. Whether this is reachable with Terry's real ASX data is
    unconfirmed (Data Premise Verification Rule) — this test only pins
    down current behaviour so a future change is a deliberate decision,
    not an accidental regression."""

    def test_href_pointing_to_a_directory_is_reported_as_success(self, tmp_path):
        dir_target = tmp_path / "not_actually_a_file"
        dir_target.mkdir()
        asx = _write_asx(tmp_path / "x.asx", str(dir_target.resolve()))

        result = process_asx_file(asx, tmp_path)

        # Current behaviour — flagged to Terry, not silently changed.
        assert result["success"] is True
        assert result["audio_path"] == dir_target.resolve()


# ── process_asx_file — failure paths ─────────────────────────────────────


class TestProcessAsxFileFailures:
    def test_no_ref_link_in_asx(self, tmp_path):
        asx = tmp_path / "empty.asx"
        asx.write_text("<ASX><Entry></Entry></ASX>", encoding="utf-8")
        result = process_asx_file(asx, tmp_path)
        assert result["success"] is False
        assert result["reason"] == "NO REF LINK IN ASX"
        assert result["asx_fn"] == "empty.asx"

    def test_file_not_found_when_dir_exists(self, tmp_path):
        # directory exists, file does not
        missing_audio = tmp_path / "ghost.mp3"
        asx = _write_asx(tmp_path / "ghost.asx", str(missing_audio.resolve()))
        result = process_asx_file(asx, tmp_path)
        assert result["success"] is False
        assert result["reason"] == "FILE NOT FOUND"

    def test_directory_not_found_when_dir_missing(self, tmp_path):
        missing_dir_audio = tmp_path / "missing_dir" / "track.mp3"
        asx = _write_asx(tmp_path / "track.asx", str(missing_dir_audio.resolve()))
        result = process_asx_file(asx, tmp_path)
        assert result["success"] is False
        assert result["reason"] == "DIRECTORY NOT FOUND"

    def test_read_error_returns_failure(self, tmp_path):
        asx = tmp_path / "unreadable.asx"
        asx.write_text("content", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=IOError("Permission denied")):
            result = process_asx_file(asx, tmp_path)
        assert result["success"] is False
        assert "READ ERROR" in result["reason"]

    def test_asx_fn_always_populated(self, tmp_path):
        asx = tmp_path / "myfile.asx"
        asx.write_text("<ASX></ASX>", encoding="utf-8")
        result = process_asx_file(asx, tmp_path)
        assert result["asx_fn"] == "myfile.asx"

    def test_audio_path_is_na_when_no_ref(self, tmp_path):
        asx = tmp_path / "noref.asx"
        asx.write_text("<ASX></ASX>", encoding="utf-8")
        result = process_asx_file(asx, tmp_path)
        assert result["audio_path"] == "N/A"

    def test_malformed_asx_with_no_ref(self, tmp_path):
        asx = tmp_path / "malformed.asx"
        asx.write_text("this is not xml at all !!!", encoding="utf-8")
        result = process_asx_file(asx, tmp_path)
        assert result["success"] is False

    def test_dtd_bearing_asx_is_rejected(self, tmp_path):
        asx = tmp_path / "doctype.asx"
        asx.write_text(
            '<!DOCTYPE foo [<!ENTITY e "boom">]><ASX><REF HREF="&e;"/></ASX>',
            encoding="utf-8",
        )
        result = process_asx_file(asx, tmp_path)
        assert result["success"] is False
        assert result["reason"] == "DTD-BEARING ASX REJECTED"

    def test_entity_free_asx_still_parsed(self, tmp_path):
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"x")
        asx = tmp_path / "clean.asx"
        asx.write_text(
            f'<ASX><ENTRY><ref href="{audio.resolve()}"/></ENTRY></ASX>',
            encoding="utf-8",
        )
        result = process_asx_file(asx, tmp_path)
        assert result["success"] is True


# ─────────────────────────────────────────────────────────────────────────────
# G-10 — file_ops
# ─────────────────────────────────────────────────────────────────────────────


class TestCopyAudioFile:
    def test_copies_file_to_destination(self, tmp_path):
        src = tmp_path / "src" / "track.mp3"
        dst = tmp_path / "dst"
        src.parent.mkdir()
        dst.mkdir()
        src.write_bytes(b"audio data")

        copy_audio_file(src, dst)
        assert (dst / "track.mp3").exists()
        assert (dst / "track.mp3").read_bytes() == b"audio data"

    def test_returns_true_on_success(self, tmp_path):
        src = tmp_path / "track.mp3"
        dst = tmp_path / "dst"
        dst.mkdir()
        src.write_bytes(b"x")
        assert copy_audio_file(src, dst) is True

    def test_missing_source_does_not_raise(self, tmp_path):
        dst = tmp_path / "dst"
        dst.mkdir()
        copy_audio_file(tmp_path / "ghost.mp3", dst)  # must not raise

    def test_missing_source_returns_false(self, tmp_path):
        """Failures must be reported, not swallowed: the caller needs
        this signal to avoid logging the item as a successful extraction."""
        dst = tmp_path / "dst"
        dst.mkdir()
        assert copy_audio_file(tmp_path / "ghost.mp3", dst) is False

    def test_missing_destination_does_not_raise(self, tmp_path):
        src = tmp_path / "track.mp3"
        src.write_bytes(b"x")
        # shutil.copy2 treats a non-existent destination path as a literal
        # target filename (not an error) when its parent exists, so this
        # exercises the "no parent directory at all" failure case instead.
        # must not raise
        copy_audio_file(src, tmp_path / "no_such_parent" / "dest")

    def test_missing_destination_returns_false(self, tmp_path):
        src = tmp_path / "track.mp3"
        src.write_bytes(b"x")
        assert copy_audio_file(src, tmp_path / "no_such_parent" / "dest") is False

    def test_preserves_file_content(self, tmp_path):
        content = b"\xff\xfb\x90\x00" + b"\xab" * 200
        src = tmp_path / "src"
        src.mkdir()
        audio = src / "high_quality.flac"
        audio.write_bytes(content)
        dst = tmp_path / "dst"
        dst.mkdir()
        copy_audio_file(audio, dst)
        assert (dst / "high_quality.flac").read_bytes() == content


class TestRemoveAsxFile:
    def test_removes_file_when_send2trash_unavailable(self, tmp_path):
        asx = tmp_path / "playlist.asx"
        asx.write_text("content")
        with patch("asx_extractor.core.file_ops.SEND2TRASH_AVAILABLE", False):
            remove_asx_file(asx)
        assert not asx.exists()

    def test_returns_true_on_success(self, tmp_path):
        asx = tmp_path / "playlist.asx"
        asx.write_text("content")
        with patch("asx_extractor.core.file_ops.SEND2TRASH_AVAILABLE", False):
            assert remove_asx_file(asx) is True

    def test_nonexistent_file_does_not_raise(self, tmp_path):
        remove_asx_file(tmp_path / "ghost.asx")  # must not raise

    def test_nonexistent_file_returns_false(self, tmp_path):
        """Failures must be reported, not swallowed."""
        with patch("asx_extractor.core.file_ops.SEND2TRASH_AVAILABLE", False):
            assert remove_asx_file(tmp_path / "ghost.asx") is False

    def test_calls_send2trash_when_available(self, tmp_path):
        """When send2trash is available, remove_asx_file delegates to it."""
        asx = tmp_path / "playlist.asx"
        asx.write_text("content")
        import asx_extractor.core.file_ops as file_ops_mod

        mock_trash = MagicMock()
        # Use create=True because send2trash may not be installed in this env
        with (
            patch.object(file_ops_mod, "SEND2TRASH_AVAILABLE", True),
            patch.object(file_ops_mod, "send2trash", mock_trash, create=True),
        ):
            result = file_ops_mod.remove_asx_file(asx)
            mock_trash.assert_called_once_with(str(asx.resolve()))
            assert result is True


class TestWriteExtractionLog:
    def _successes(self):
        return [{"asx_fn": "a.asx", "audio_path": Path("/music/a.mp3")}]

    def _failures(self):
        return [
            {
                "asx_fn": "b.asx",
                "reason": "FILE NOT FOUND",
                "audio_path": "/music/b.mp3",
            }
        ]

    def test_returns_true_on_success(self, tmp_path):
        log = tmp_path / "log.txt"
        result = write_extraction_log(
            log, tmp_path, "Dry Run", self._successes(), self._failures()
        )
        assert result is True

    def test_log_file_created(self, tmp_path):
        log = tmp_path / "log.txt"
        write_extraction_log(log, tmp_path, "Live", self._successes(), [])
        assert log.exists()

    def test_log_contains_header(self, tmp_path):
        log = tmp_path / "log.txt"
        write_extraction_log(log, tmp_path, "Live", self._successes(), [])
        content = log.read_text(encoding="utf-8")
        assert "ASX EXTRACTION REPORT" in content

    def test_log_contains_mode_label(self, tmp_path):
        log = tmp_path / "log.txt"
        write_extraction_log(log, tmp_path, "Dry Run (Simulated)", [], [])
        assert "Dry Run (Simulated)" in log.read_text(encoding="utf-8")

    def test_log_contains_source_dir(self, tmp_path):
        log = tmp_path / "log.txt"
        write_extraction_log(log, tmp_path, "Live", [], [])
        assert str(tmp_path) in log.read_text(encoding="utf-8")

    def test_log_contains_success_section(self, tmp_path):
        log = tmp_path / "log.txt"
        write_extraction_log(log, tmp_path, "Live", self._successes(), [])
        content = log.read_text(encoding="utf-8")
        assert "SECTION 2: SUCCESSFUL EXTRACTIONS" in content
        assert "a.asx" in content

    def test_log_contains_failure_section(self, tmp_path):
        log = tmp_path / "log.txt"
        write_extraction_log(log, tmp_path, "Live", [], self._failures())
        content = log.read_text(encoding="utf-8")
        assert "SECTION 1: FAILURES" in content
        assert "b.asx" in content
        assert "FILE NOT FOUND" in content

    def test_log_contains_summary_counts(self, tmp_path):
        log = tmp_path / "log.txt"
        write_extraction_log(log, tmp_path, "Live", self._successes(), self._failures())
        content = log.read_text(encoding="utf-8")
        assert "SUMMARY" in content
        assert "Success:  1" in content
        assert "Failures: 1" in content

    def test_empty_successes_shows_no_successful_extractions(self, tmp_path):
        log = tmp_path / "log.txt"
        write_extraction_log(log, tmp_path, "Live", [], [])
        content = log.read_text(encoding="utf-8")
        assert "No successful extractions" in content

    def test_empty_failures_shows_no_failures(self, tmp_path):
        log = tmp_path / "log.txt"
        write_extraction_log(log, tmp_path, "Live", [], [])
        content = log.read_text(encoding="utf-8")
        assert "No failures detected" in content

    def test_returns_false_on_write_error(self, tmp_path):
        log = tmp_path / "log.txt"
        with patch.object(Path, "open", side_effect=IOError("disk full")):
            result = write_extraction_log(log, tmp_path, "Live", [], [])
        assert result is False

    def test_log_contains_datestamp(self, tmp_path):
        log = tmp_path / "log.txt"
        write_extraction_log(log, tmp_path, "Live", [], [])
        content = log.read_text(encoding="utf-8")
        year = str(datetime.datetime.now().year)
        assert year in content

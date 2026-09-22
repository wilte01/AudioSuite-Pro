"""
tests/test_integrity.py
Unit tests for the File Integrity Checker (core/integrity.py).

Tests cover:
  - File existence and readability checks
  - File size validation (empty, too small, too large)
  - Magic bytes / header validation for various formats
  - Decode test via pydub
  - Audio property validation (sample rate, duration, channels)
  - Batch validation utilities
  - Integration with pipeline pre-flight check
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from audio_refinery.core.integrity import (
    IntegrityResult,
    IntegrityStatus,
    check_audio_properties,
    check_decode,
    check_magic_bytes,
    filter_invalid,
    filter_valid,
    validate_file,
    validate_files,
)
from audio_refinery.core.models import FileStatus


class TestIntegrityResult:
    """Tests for the IntegrityResult dataclass."""

    def test_default_status_is_pass(self, tmp_path: Path) -> None:
        result = IntegrityResult(path=tmp_path)
        assert result.status == IntegrityStatus.PASS
        assert result.is_valid is True

    def test_add_check_records_check(self, tmp_path: Path) -> None:
        result = IntegrityResult(path=tmp_path)
        result.add_check("existence")
        assert "existence" in result.checks

    def test_add_failure_sets_fail_status(self, tmp_path: Path) -> None:
        result = IntegrityResult(path=tmp_path)
        result.add_failure("test", "something went wrong")
        assert result.status == IntegrityStatus.FAIL
        assert result.is_valid is False
        assert "test: something went wrong" in result.failures

    def test_add_warning_sets_warn_status(self, tmp_path: Path) -> None:
        result = IntegrityResult(path=tmp_path)
        result.add_warning("ext", "unrecognised extension")
        assert result.status == IntegrityStatus.WARN
        assert result.is_valid is True

    def test_summary_when_valid(self, tmp_path: Path) -> None:
        result = IntegrityResult(
            path=tmp_path,
            file_size_bytes=1024,
            duration_ms=3000.0,
            sample_rate=44100,
            channels=2,
        )
        summary = result.summary
        assert "OK" in summary
        assert "44100 Hz" in summary
        assert "2ch" in summary

    def test_summary_when_fail(self, tmp_path: Path) -> None:
        result = IntegrityResult(path=tmp_path)
        result.add_failure("decode", "codec error")
        assert "FAIL" in result.summary
        assert "codec error" in result.summary


class TestFileExistence:
    """Tests for file existence and readability checks."""

    def test_nonexistent_file_fails(self, tmp_path: Path) -> None:
        result = validate_file(tmp_path / "nonexistent.mp3")
        assert result.status == IntegrityStatus.FAIL
        assert any("existence" in f for f in result.failures)

    def test_directory_fails(self, tmp_path: Path) -> None:
        result = validate_file(tmp_path)
        assert result.status == IntegrityStatus.FAIL
        assert any("regular file" in f for f in result.failures)

    def test_empty_file_fails(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.wav"
        empty.write_bytes(b"")
        result = validate_file(empty)
        assert result.status == IntegrityStatus.FAIL
        assert any("empty" in f for f in result.failures)

    def test_too_small_file_fails(self, tmp_path: Path) -> None:
        tiny = tmp_path / "tiny.wav"
        tiny.write_bytes(b"RI" * 10)  # 20 bytes, below MIN_FILE_SIZE_BYTES
        result = validate_file(tiny)
        assert result.status == IntegrityStatus.FAIL
        assert any("below minimum" in f for f in result.failures)


class TestMagicBytes:
    """Tests for magic bytes / header validation."""

    def test_wav_valid_header(self, tmp_path: Path) -> None:
        wav = tmp_path / "test.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 20)
        result = IntegrityResult(path=wav)
        check_magic_bytes(wav, result)
        assert "magic_bytes" in result.checks

    def test_wav_invalid_header(self, tmp_path: Path) -> None:
        wav = tmp_path / "test.wav"
        wav.write_bytes(b"NOT_RIFF" + b"\x00" * 20)
        result = IntegrityResult(path=wav)
        check_magic_bytes(wav, result)
        assert result.status == IntegrityStatus.FAIL
        assert any("magic_bytes" in f for f in result.failures)

    def test_flac_valid_header(self, tmp_path: Path) -> None:
        flac = tmp_path / "test.flac"
        flac.write_bytes(b"fLaC" + b"\x00" * 20)
        result = IntegrityResult(path=flac)
        check_magic_bytes(flac, result)
        assert "magic_bytes" in result.checks

    def test_flac_invalid_header(self, tmp_path: Path) -> None:
        flac = tmp_path / "test.flac"
        flac.write_bytes(b"NOT_FLAC" + b"\x00" * 20)
        result = IntegrityResult(path=flac)
        check_magic_bytes(flac, result)
        assert result.status == IntegrityStatus.FAIL

    def test_ogg_valid_header(self, tmp_path: Path) -> None:
        ogg = tmp_path / "test.ogg"
        ogg.write_bytes(b"OggS" + b"\x00" * 20)
        result = IntegrityResult(path=ogg)
        check_magic_bytes(ogg, result)
        assert "magic_bytes" in result.checks

    def test_m4a_valid_header(self, tmp_path: Path) -> None:
        m4a = tmp_path / "test.m4a"
        m4a.write_bytes(b"\x00" * 4 + b"ftyp" + b"\x00" * 20)
        result = IntegrityResult(path=m4a)
        check_magic_bytes(m4a, result)
        assert "magic_bytes" in result.checks

    def test_m4a_invalid_header(self, tmp_path: Path) -> None:
        m4a = tmp_path / "test.m4a"
        m4a.write_bytes(b"\x00" * 4 + b"NOT_FTYP" + b"\x00" * 20)
        result = IntegrityResult(path=m4a)
        check_magic_bytes(m4a, result)
        assert result.status == IntegrityStatus.FAIL

    def test_mp3_id3_tagged_header_valid(self, tmp_path: Path) -> None:
        """Regression: ID3v2-tagged MP3s start with b'ID3', not the frame
        sync byte — these must not fail the magic-byte pre-check."""
        mp3 = tmp_path / "test.mp3"
        mp3.write_bytes(b"ID3\x04\x00" + b"\x00" * 30)
        result = IntegrityResult(path=mp3)
        check_magic_bytes(mp3, result)
        assert result.status == IntegrityStatus.PASS
        assert "magic_bytes" in result.checks

    def test_mp3_raw_frame_sync_header_valid(self, tmp_path: Path) -> None:
        """Untagged MP3s start with the 0xFF MPEG frame sync — still valid."""
        mp3 = tmp_path / "test.mp3"
        mp3.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 30)
        result = IntegrityResult(path=mp3)
        check_magic_bytes(mp3, result)
        assert result.status == IntegrityStatus.PASS
        assert "magic_bytes" in result.checks

    def test_mp3_invalid_header(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "test.mp3"
        mp3.write_bytes(b"NOT_MP3_OR_ANYTHING" + b"\x00" * 20)
        result = IntegrityResult(path=mp3)
        check_magic_bytes(mp3, result)
        assert result.status == IntegrityStatus.FAIL
        assert any("magic_bytes" in f for f in result.failures)

    def test_unknown_extension_skips(self, tmp_path: Path) -> None:
        xyz = tmp_path / "test.xyz"
        xyz.write_bytes(b"DATA" * 10)
        result = IntegrityResult(path=xyz)
        check_magic_bytes(xyz, result)
        assert any("skipped" in c for c in result.checks)


class TestDecodeCheck:
    """Tests for pydub decode validation."""

    def test_decode_calls_pydub(self, tmp_path: Path) -> None:
        mock_audio = MagicMock()
        mock_audio.frame_rate = 44100
        mock_audio.channels = 2
        mock_audio.__len__ = MagicMock(return_value=3000)

        with patch(
            "pydub.AudioSegment",
            create=True,
        ) as mock_cls:
            mock_cls.from_file.return_value = mock_audio
            result = IntegrityResult(path=tmp_path / "test.wav")
            check_decode(tmp_path / "test.wav", result)
            assert "decode" in result.checks
            assert result.sample_rate == 44100
            assert result.channels == 2
            assert result.duration_ms == 3000.0

    def test_decode_failure_sets_error(self, tmp_path: Path) -> None:
        with patch(
            "pydub.AudioSegment",
            create=True,
        ) as mock_cls:
            mock_cls.from_file.side_effect = Exception("corrupt file")
            result = IntegrityResult(path=tmp_path / "test.wav")
            check_decode(tmp_path / "test.wav", result)
            assert result.status == IntegrityStatus.FAIL
            assert any("decode" in f for f in result.failures)


class TestAudioProperties:
    """Tests for audio property validation."""

    def test_valid_properties(self) -> None:
        result = IntegrityResult(path=Path("test.wav"))
        result.sample_rate = 44100
        result.duration_ms = 60000.0
        result.channels = 2
        check_audio_properties(result)
        assert result.status == IntegrityStatus.PASS
        assert "sample_rate" in result.checks
        assert "duration" in result.checks
        assert "channels" in result.checks

    def test_low_sample_rate_fails(self) -> None:
        result = IntegrityResult(path=Path("test.wav"))
        result.sample_rate = 4000
        result.duration_ms = 60000.0
        result.channels = 2
        check_audio_properties(result)
        assert result.status == IntegrityStatus.FAIL
        assert any("sample_rate" in f for f in result.failures)

    def test_high_sample_rate_fails(self) -> None:
        result = IntegrityResult(path=Path("test.wav"))
        result.sample_rate = 200000
        result.duration_ms = 60000.0
        result.channels = 2
        check_audio_properties(result)
        assert result.status == IntegrityStatus.FAIL
        assert any("sample_rate" in f for f in result.failures)

    def test_too_short_duration_fails(self) -> None:
        result = IntegrityResult(path=Path("test.wav"))
        result.sample_rate = 44100
        result.duration_ms = 5.0  # Below MIN_DURATION_MS (10)
        result.channels = 2
        check_audio_properties(result)
        assert result.status == IntegrityStatus.FAIL
        assert any("duration" in f for f in result.failures)

    def test_too_long_duration_fails(self) -> None:
        result = IntegrityResult(path=Path("test.wav"))
        result.sample_rate = 44100
        result.duration_ms = 25 * 60 * 60 * 1000.0  # 25 hours
        result.channels = 2
        check_audio_properties(result)
        assert result.status == IntegrityStatus.FAIL
        assert any("duration" in f for f in result.failures)

    def test_zero_channels_fails(self) -> None:
        result = IntegrityResult(path=Path("test.wav"))
        result.sample_rate = 44100
        result.duration_ms = 60000.0
        result.channels = 0
        check_audio_properties(result)
        assert result.status == IntegrityStatus.FAIL
        assert any("channels" in f for f in result.failures)

    def test_too_many_channels_fails(self) -> None:
        result = IntegrityResult(path=Path("test.wav"))
        result.sample_rate = 44100
        result.duration_ms = 60000.0
        result.channels = 16
        check_audio_properties(result)
        assert result.status == IntegrityStatus.FAIL
        assert any("channels" in f for f in result.failures)


class TestBatchValidation:
    """Tests for batch validation utilities."""

    def test_filter_valid(self, tmp_path: Path) -> None:
        r1 = IntegrityResult(path=tmp_path / "good.wav")
        r1.add_check("all")
        r2 = IntegrityResult(path=tmp_path / "bad.wav")
        r2.add_failure("test", "error")
        results = [r1, r2]
        valid = filter_valid(results)
        assert len(valid) == 1
        assert valid[0] == tmp_path / "good.wav"

    def test_filter_invalid(self, tmp_path: Path) -> None:
        r1 = IntegrityResult(path=tmp_path / "good.wav")
        r1.add_check("all")
        r2 = IntegrityResult(path=tmp_path / "bad.wav")
        r2.add_failure("test", "error")
        results = [r1, r2]
        invalid = filter_invalid(results)
        assert len(invalid) == 1
        assert invalid[0].path == tmp_path / "bad.wav"

    def test_validate_files_batch(self, tmp_path: Path) -> None:
        paths = [tmp_path / f"file{i}.wav" for i in range(3)]
        for p in paths:
            p.write_bytes(b"RIFF" + b"\x00" * 100)

        with patch(
            "pydub.AudioSegment",
            create=True,
        ) as mock_cls:
            mock_audio = MagicMock()
            mock_audio.frame_rate = 44100
            mock_audio.channels = 2
            mock_audio.__len__ = MagicMock(return_value=5000)
            mock_cls.from_file.return_value = mock_audio

            results = validate_files(paths)
            assert len(results) == 3
            assert all(r.is_valid for r in results)


class TestValidateFileEdgeCases:
    """Additional branch coverage for validate_file."""

    def test_oversized_file_fails(self, tmp_path: Path) -> None:
        big = tmp_path / "big.wav"
        big.write_bytes(b"RIFF" + b"\x00" * 100)

        with patch.object(type(big), "stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=5 * 1024 * 1024 * 1024)
            result = validate_file(big)
            assert result.status == IntegrityStatus.FAIL
            assert any("exceeds maximum" in f for f in result.failures)

    def test_stat_error_fails(self, tmp_path: Path) -> None:
        f = tmp_path / "broken.wav"
        f.write_bytes(b"RIFF" + b"\x00" * 100)

        with patch.object(type(f), "stat", side_effect=OSError("cannot stat")):
            result = validate_file(f)
            assert result.status == IntegrityStatus.FAIL
            assert any("Cannot stat" in fl for fl in result.failures)

    def test_unknown_extension_warns(self, tmp_path: Path) -> None:
        f = tmp_path / "song.xyz"
        f.write_bytes(b"DATA" * 50)

        with patch("pydub.AudioSegment", create=True) as mock_cls:
            mock_audio = MagicMock()
            mock_audio.frame_rate = 44100
            mock_audio.channels = 2
            mock_audio.__len__ = MagicMock(return_value=5000)
            mock_cls.from_file.return_value = mock_audio

            result = validate_file(f)
            assert result.is_valid is True
            assert any("extension" in w for w in result.warnings)

    def test_magic_bytes_read_error_fails(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.wav"
        f.write_bytes(b"RIFF" + b"\x00" * 100)

        with patch("builtins.open", side_effect=OSError("locked file")):
            result = IntegrityResult(path=f)
            check_magic_bytes(f, result)
            assert result.status == IntegrityStatus.FAIL
            assert any("Could not read header" in fl for fl in result.failures)

    def test_decode_failure_short_circuits(self, tmp_path: Path) -> None:
        """If magic bytes fail, decode is never attempted."""
        f = tmp_path / "bad.wav"
        f.write_bytes(b"NOT_RIFF" + b"\x00" * 100)

        with patch(
            "audio_refinery.core.integrity.check_decode",
        ) as mock_decode:
            result = validate_file(f)
            mock_decode.assert_not_called()
            assert result.status == IntegrityStatus.FAIL


class TestPipelineIntegration:
    """Tests for integrity check integration with pipeline."""

    def test_pipeline_rejects_corrupt_file(self, tmp_path: Path) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.core.pipeline import process_file

        corrupt = tmp_path / "corrupt.wav"
        corrupt.write_bytes(b"RIFF" + b"\x00" * 100)

        config = StageConfig(dry_run=True)

        with patch(
            "pydub.AudioSegment",
            create=True,
        ) as mock_cls:
            mock_cls.from_file.side_effect = Exception("corrupt data")

            result = process_file(
                source_path=corrupt,
                output_path=tmp_path / "out.wav",
                config=config,
            )
            assert result.status == FileStatus.ERROR
            assert (
                "integrity" in result.error.lower()
                or "check failed" in result.error.lower()
            )

    def test_pipeline_passes_valid_file(self, tmp_path: Path) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.core.pipeline import process_file

        valid = tmp_path / "valid.wav"
        valid.write_bytes(b"RIFF" + b"\x00" * 200)

        config = StageConfig(dry_run=True)

        mock_audio = MagicMock()
        mock_audio.frame_rate = 44100
        mock_audio.channels = 2
        mock_audio.sample_width = 2
        mock_audio.__len__ = MagicMock(return_value=5000)

        with (
            patch(
                "audio_refinery.core.integrity.check_decode",
            ) as mock_decode,
        ):

            def _fake_decode(path: Path, result: IntegrityResult) -> None:
                result.sample_rate = 44100
                result.channels = 2
                result.duration_ms = 5000.0
                result.add_check("decode")

            mock_decode.side_effect = _fake_decode

            with (
                patch(
                    "audio_refinery.core.pipeline.AudioSegment",
                    create=True,
                ) as mock_pipeline_cls,
                patch(
                    "audio_refinery.core.pipeline.read_tags_raw",
                    return_value={},
                ),
                patch(
                    "audio_refinery.core.pipeline.segment_to_numpy",
                    return_value=(b"\x00" * 100, 44100),
                ),
                patch(
                    "audio_refinery.core.pipeline.compute_rms_db",
                    return_value=-20.0,
                ),
            ):
                mock_pipeline_cls.from_file.return_value = mock_audio

                result = process_file(
                    source_path=valid,
                    output_path=tmp_path / "out.wav",
                    config=config,
                )
                assert result.error is None
                assert any(s.stage == "DryRun" for s in result.stages)
                assert not any(
                    s.stage == "Validate" and s.status == FileStatus.ERROR
                    for s in result.stages
                )

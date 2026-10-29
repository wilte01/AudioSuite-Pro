"""
Tests for audio_suite_shared.audio_formats
Gap G-01: is_supported_format, is_lossless_extension,
is_compressed_extension, get_format_type

Changed in 1.1.0: added coverage for the five new formats and the read-only extension
set.

Changed in 2.1.7: ``preserve_depth_params``/``source_bit_depth`` are locked — a
24-bit WAV must export as ``pcm_s24le`` and a lossy target must get no pin
(F-10).
"""

import pytest

from audio_suite_shared.audio_formats import (
    COMPRESSED_EXTENSIONS,
    LOSSLESS_EXTENSIONS,
    READ_ONLY_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    get_format_type,
    is_compressed_extension,
    is_lossless_extension,
    is_read_only_extension,
    is_supported_format,
)

# ── Constants sanity ──────────────────────────────────────────────────────────


class TestConstants:
    def test_supported_extensions_is_tuple(self):
        assert isinstance(SUPPORTED_EXTENSIONS, tuple)

    def test_lossless_extensions_subset_of_supported(self):
        for ext in LOSSLESS_EXTENSIONS:
            assert ext in SUPPORTED_EXTENSIONS, f"{ext} lossless but not in SUPPORTED"

    def test_compressed_extensions_subset_of_supported(self):
        for ext in COMPRESSED_EXTENSIONS:
            assert ext in SUPPORTED_EXTENSIONS, f"{ext} compressed but not in SUPPORTED"

    def test_lossless_and_compressed_are_disjoint(self):
        overlap = set(LOSSLESS_EXTENSIONS) & set(COMPRESSED_EXTENSIONS)
        assert not overlap, f"Extensions in both lossless and compressed: {overlap}"

    def test_all_supported_are_classified(self):
        """Every supported extension must be lossless or compressed — no orphans."""
        all_classified = set(LOSSLESS_EXTENSIONS) | set(COMPRESSED_EXTENSIONS)
        for ext in SUPPORTED_EXTENSIONS:
            assert ext in all_classified, (
                f"{ext} is supported but neither lossless nor compressed"
            )


# ── Sprint-1 widened format set (D5/B1/B2) ────────────────────────────────────


class TestSprint1Formats:
    @pytest.mark.parametrize(
        "filename",
        ["a.wv", "a.ape", "a.mpc", "a.spx", "a.dsf", "A.WV", "A.DSF"],
    )
    def test_new_formats_are_supported(self, filename):
        assert is_supported_format(filename) is True

    @pytest.mark.parametrize("ext", [".wv", ".ape", ".mpc", ".dsf"])
    def test_new_lossless_formats_classified_lossless(self, ext):
        assert ext in LOSSLESS_EXTENSIONS
        assert is_lossless_extension(f"a{ext}") is True

    def test_spx_is_compressed(self):
        assert ".spx" in COMPRESSED_EXTENSIONS
        assert is_compressed_extension("a.spx") is True

    @pytest.mark.parametrize("ext", [".wv", ".ape", ".mpc", ".spx", ".dsf"])
    def test_new_formats_have_a_format_type(self, ext):
        assert get_format_type(f"a{ext}") in {"lossless", "compressed"}


class TestReadOnlyExtensions:
    """READ_ONLY_EXTENSIONS = containers with no FFmpeg encoder/muxer."""

    def test_set_is_exactly_ape_mpc_dsf(self):
        assert set(READ_ONLY_EXTENSIONS) == {".ape", ".mpc", ".dsf"}

    @pytest.mark.parametrize("filename", ["a.ape", "a.mpc", "a.dsf", "A.APE"])
    def test_read_only_matches(self, filename):
        assert is_read_only_extension(filename) is True

    @pytest.mark.parametrize(
        "filename", ["a.wv", "a.spx", "a.mp3", "a.flac", "a.wav", "a.txt"]
    )
    def test_writable_and_foreign_are_not_read_only(self, filename):
        assert is_read_only_extension(filename) is False

    def test_read_only_extensions_are_supported(self):
        for ext in READ_ONLY_EXTENSIONS:
            assert ext in SUPPORTED_EXTENSIONS


# ── is_supported_format ───────────────────────────────────────────────────────


class TestIsSupportedFormat:
    @pytest.mark.parametrize(
        "filename",
        [
            "track.mp3",
            "song.flac",
            "audio.ogg",
            "music.m4a",
            "podcast.opus",
            "sample.wav",
            "recording.aiff",
            "clip.aif",
        ],
    )
    def test_supported_formats_return_true(self, filename):
        assert is_supported_format(filename) is True

    @pytest.mark.parametrize(
        "filename",
        [
            "document.pdf",
            "image.jpg",
            "archive.zip",
            "script.py",
            "data.txt",
            "playlist.m3u",
            "no_extension",
        ],
    )
    def test_unsupported_formats_return_false(self, filename):
        assert is_supported_format(filename) is False

    @pytest.mark.parametrize(
        "filename",
        [
            "Track.MP3",
            "Song.FLAC",
            "Audio.OGG",
            "Music.M4A",
            "Sample.WAV",
            "Recording.AIFF",
            "Clip.AIF",
        ],
    )
    def test_case_insensitive(self, filename):
        assert is_supported_format(filename) is True

    def test_path_with_directory_components(self):
        assert is_supported_format("/home/user/music/track.mp3") is True

    def test_path_with_spaces_in_name(self):
        assert is_supported_format("My Favourite Song.flac") is True

    def test_dotfile_with_no_real_extension(self):
        # ".mp3" is a hidden file named mp3 on Linux — no trailing extension
        # is_supported_format checks endswith so ".mp3" should still match
        assert is_supported_format(".mp3") is True

    def test_empty_string(self):
        assert is_supported_format("") is False

    def test_extension_only_check_not_content(self):
        # A .txt file renamed to .mp3 should still pass — we check extension only
        assert is_supported_format("actually_a_text_file.mp3") is True


# ── is_lossless_extension ──────────────────────────────────────────────────────


class TestIsLosslessExtension:
    @pytest.mark.parametrize(
        "filename",
        [
            "track.flac",
            "sample.wav",
            "recording.aiff",
            "clip.aif",
        ],
    )
    def test_lossless_formats_return_true(self, filename):
        assert is_lossless_extension(filename) is True

    @pytest.mark.parametrize(
        "filename",
        [
            "track.mp3",
            "audio.ogg",
            "music.m4a",
            "podcast.opus",
            "document.pdf",
            "image.jpg",
        ],
    )
    def test_non_lossless_formats_return_false(self, filename):
        assert is_lossless_extension(filename) is False

    @pytest.mark.parametrize("filename", ["Track.FLAC", "Sample.WAV", "Recording.AIFF"])
    def test_case_insensitive(self, filename):
        assert is_lossless_extension(filename) is True

    def test_empty_string(self):
        assert is_lossless_extension("") is False


# ── is_compressed_extension ───────────────────────────────────────────────────


class TestIsCompressedExtension:
    @pytest.mark.parametrize(
        "filename",
        [
            "track.mp3",
            "audio.ogg",
            "music.m4a",
            "podcast.opus",
        ],
    )
    def test_compressed_formats_return_true(self, filename):
        assert is_compressed_extension(filename) is True

    @pytest.mark.parametrize(
        "filename",
        [
            "track.flac",
            "sample.wav",
            "recording.aiff",
            "clip.aif",
            "document.pdf",
            "video.mkv",
        ],
    )
    def test_non_compressed_formats_return_false(self, filename):
        assert is_compressed_extension(filename) is False

    @pytest.mark.parametrize("filename", ["Track.MP3", "Audio.OGG", "Podcast.OPUS"])
    def test_case_insensitive(self, filename):
        assert is_compressed_extension(filename) is True

    def test_empty_string(self):
        assert is_compressed_extension("") is False


# ── get_format_type ───────────────────────────────────────────────────────────


class TestGetFormatType:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("track.flac", "lossless"),
            ("sample.wav", "lossless"),
            ("clip.aiff", "lossless"),
            ("clip.aif", "lossless"),
        ],
    )
    def test_lossless_files(self, filename, expected):
        assert get_format_type(filename) == expected

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("track.mp3", "compressed"),
            ("audio.ogg", "compressed"),
            ("music.m4a", "compressed"),
            ("pod.opus", "compressed"),
        ],
    )
    def test_compressed_files(self, filename, expected):
        assert get_format_type(filename) == expected

    @pytest.mark.parametrize(
        "filename",
        [
            "document.pdf",
            "image.jpg",
            "archive.zip",
            "notes.txt",
            "",
        ],
    )
    def test_unsupported_files_return_unsupported(self, filename):
        assert get_format_type(filename) == "unsupported"

    def test_returns_string(self):
        assert isinstance(get_format_type("track.mp3"), str)

    def test_case_insensitive_lossless(self):
        assert get_format_type("TRACK.FLAC") == "lossless"

    def test_case_insensitive_compressed(self):
        assert get_format_type("TRACK.MP3") == "compressed"

    def test_return_values_are_valid_enum_set(self):
        valid = {"lossless", "compressed", "unsupported"}
        for ext in SUPPORTED_EXTENSIONS + (".pdf", ".jpg", ""):
            result = get_format_type(f"file{ext}")
            assert result in valid, f"Unexpected return value '{result}' for file{ext}"


# ═════════════════════════════════════════════════════════════════════════════
# preserve_depth_params (F-10): a lossless rewrite must not drop bit depth
# ═════════════════════════════════════════════════════════════════════════════


class TestPreserveDepthParams:
    """The export arguments that keep a lossless source's integer depth."""

    @pytest.mark.parametrize("ext", [".mp3", ".ogg", ".m4a", ".mp4", ".opus", ".spx"])
    def test_lossy_containers_get_no_depth_pin(self, ext, monkeypatch):
        from audio_suite_shared import audio_formats

        monkeypatch.setattr(audio_formats, "source_bit_depth", lambda _path: 32)
        assert audio_formats.preserve_depth_params(ext, "track" + ext) == []

    @pytest.mark.parametrize("ext", [".wav", ".aiff", ".aif", ".flac"])
    def test_unreadable_depth_gets_no_pin(self, ext, monkeypatch):
        from audio_suite_shared import audio_formats

        monkeypatch.setattr(audio_formats, "source_bit_depth", lambda _path: None)
        assert audio_formats.preserve_depth_params(ext, "track" + ext) == []

    @pytest.mark.parametrize("ext", [".wav", ".aiff", ".aif", ".flac"])
    def test_sixteen_bit_keeps_the_encoder_default(self, ext, monkeypatch):
        from audio_suite_shared import audio_formats

        monkeypatch.setattr(audio_formats, "source_bit_depth", lambda _path: 16)
        assert audio_formats.preserve_depth_params(ext, "track" + ext) == []

    @pytest.mark.parametrize(
        "ext,expected_codec",
        [
            (".wav", "pcm_s24le"),
            (".aiff", "pcm_s24be"),
            (".aif", "pcm_s24be"),
        ],
    )
    def test_twenty_four_bit_pins_the_matching_pcm_codec(
        self, ext, expected_codec, monkeypatch
    ):
        from audio_suite_shared import audio_formats

        monkeypatch.setattr(audio_formats, "source_bit_depth", lambda _path: 24)
        assert audio_formats.preserve_depth_params(ext, "track" + ext) == [
            "-c:a",
            expected_codec,
        ]

    @pytest.mark.parametrize("ext,expected_codec", [(".wav", "pcm_s32le")])
    def test_thirty_two_bit_pins_the_matching_pcm_codec(
        self, ext, expected_codec, monkeypatch
    ):
        from audio_suite_shared import audio_formats

        monkeypatch.setattr(audio_formats, "source_bit_depth", lambda _path: 32)
        assert audio_formats.preserve_depth_params(ext, "track" + ext) == [
            "-c:a",
            expected_codec,
        ]

    def test_flac_uses_the_24_bit_sample_format(self, monkeypatch):
        from audio_suite_shared import audio_formats

        monkeypatch.setattr(audio_formats, "source_bit_depth", lambda _path: 24)
        assert audio_formats.preserve_depth_params(".flac", "track.flac") == [
            "-sample_fmt",
            "s32",
        ]

    def test_extension_lookup_is_case_insensitive(self, monkeypatch):
        from audio_suite_shared import audio_formats

        monkeypatch.setattr(audio_formats, "source_bit_depth", lambda _path: 24)
        assert audio_formats.preserve_depth_params(".WAV", "track.WAV") == [
            "-c:a",
            "pcm_s24le",
        ]


class TestSourceBitDepth:
    """``source_bit_depth`` reads the container's declared depth."""

    def test_unreadable_file_returns_none(self, tmp_path):
        from audio_suite_shared.audio_formats import source_bit_depth

        bogus = tmp_path / "not-audio.wav"
        bogus.write_bytes(b"not audio")
        assert source_bit_depth(str(bogus)) is None

    def test_non_depth_format_returns_none(self, tmp_path):
        from pydub import AudioSegment

        from audio_suite_shared.audio_formats import source_bit_depth

        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100, frame_rate=32000).export(
            str(path), format="mp3"
        )
        assert source_bit_depth(str(path)) is None

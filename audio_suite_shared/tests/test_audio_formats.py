"""
Tests for audio_suite_shared.audio_formats
Gap G-01: is_supported_format, is_lossless_extension,
is_compressed_extension, get_format_type
"""

import pytest

from audio_suite_shared.audio_formats import (
    COMPRESSED_EXTENSIONS,
    LOSSLESS_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    get_format_type,
    is_compressed_extension,
    is_lossless_extension,
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

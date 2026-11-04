"""
Tests for audio_suite_shared.audio_formats
Gap G-01: is_supported_format, is_lossless_extension,
is_compressed_extension, get_format_type

Changed in 1.1.0: added coverage for the five new formats and the read-only extension
set.

Changed in 2.1.7: ``preserve_depth_params``/``source_bit_depth`` are locked — a
24-bit WAV must export as ``pcm_s24le`` and a lossy target must get no pin
(F-10).

Changed in 2.4.1: hosts the format-capability locks (WP-1): the matrix
invariant, the ``tag_writable``/``TagHandlerFactory`` agreement, the
export refusal that replaced the MP3 fallback, and a measured round trip
per writable row. They live here rather than in a composite file because
this module is the one under test.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from audio_suite_shared import audio_formats
from audio_suite_shared.audio_formats import (
    CODEC_TO_EXTENSION,
    COMPRESSED_EXTENSIONS,
    FORMAT_MATRIX,
    LOSSLESS_EXTENSIONS,
    PYDUB_FORMAT,
    READ_ONLY_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    FormatCapability,
    get_export_args,
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


# =============================================================================
# One format capability matrix (2.4.1 WP-1)
# =============================================================================

FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

requires_ffmpeg = pytest.mark.skipif(
    not FFMPEG, reason="ffmpeg/ffprobe are required for the round-trip lock"
)

#: The suite's format count. Frozen so a format added without its guide update
#: (and without this constant) fails instead of silently widening discovery.
EXPECTED_FORMAT_COUNT = 16

#: Encoder name -> the codec ``ffprobe`` reports for a file it produced.
_PROBE_CODEC: dict[str, str] = {
    "libmp3lame": "mp3",
    "flac": "flac",
    "libvorbis": "vorbis",
    "aac": "aac",
    "libopus": "opus",
    "pcm_s16le": "pcm_s16le",
    "pcm_s16be": "pcm_s16be",
    "wavpack": "wavpack",
    "libspeex": "speex",
    "wmav2": "wmav2",
}

#: Rows the pydub export path can write (an encoder *and* a pydub muxer name).
_EXPORTABLE = tuple(
    ext
    for ext, cap in FORMAT_MATRIX.items()
    if cap.writable and cap.pydub_format is not None
)


class TestMatrixIsTheVocabulary:
    """The table and the projections cannot disagree."""

    def test_the_matrix_is_non_empty(self) -> None:
        assert FORMAT_MATRIX, "the matrix is empty - the scan would pass vacuously"

    def test_supported_extensions_are_exactly_the_matrix_rows(self) -> None:
        assert set(SUPPORTED_EXTENSIONS) == set(FORMAT_MATRIX)
        assert len(SUPPORTED_EXTENSIONS) == EXPECTED_FORMAT_COUNT
        assert len(set(SUPPORTED_EXTENSIONS)) == len(SUPPORTED_EXTENSIONS)

    def test_every_row_is_keyed_by_its_own_extension(self) -> None:
        for key, capability in FORMAT_MATRIX.items():
            assert isinstance(capability, FormatCapability)
            assert capability.extension == key
            assert key.startswith(".")
            assert capability.display_name

    def test_read_only_projection_is_the_unwritable_rows(self) -> None:
        assert set(READ_ONLY_EXTENSIONS) == {
            ext for ext, cap in FORMAT_MATRIX.items() if not cap.writable
        }
        assert READ_ONLY_EXTENSIONS, "no read-only row - the projection is unused"

    def test_lossless_and_compressed_project_the_lossless_flag(self) -> None:
        assert set(LOSSLESS_EXTENSIONS) == {
            ext for ext, cap in FORMAT_MATRIX.items() if cap.lossless
        }
        assert set(COMPRESSED_EXTENSIONS) == {
            ext for ext, cap in FORMAT_MATRIX.items() if not cap.lossless
        }
        assert not set(LOSSLESS_EXTENSIONS) & set(COMPRESSED_EXTENSIONS)

    def test_every_extension_is_lossless_or_compressed(self) -> None:
        classified = set(LOSSLESS_EXTENSIONS) | set(COMPRESSED_EXTENSIONS)
        assert set(SUPPORTED_EXTENSIONS) == classified

    def test_pydub_format_projects_exactly_the_exportable_rows(self) -> None:
        assert set(PYDUB_FORMAT) == set(_EXPORTABLE)
        for ext in _EXPORTABLE:
            capability = FORMAT_MATRIX[ext]
            assert PYDUB_FORMAT[ext] == (
                capability.pydub_format,
                list(capability.export_args),
            )

    def test_output_extension_is_the_container_itself(self) -> None:
        for ext, capability in FORMAT_MATRIX.items():
            assert capability.output_extension == ext

    def test_depth_codecs_are_only_on_integer_pcm_containers(self) -> None:
        for ext, capability in FORMAT_MATRIX.items():
            if capability.depth_codecs:
                assert capability.lossless, f"{ext} pins a depth but is lossy"
                assert capability.writable, f"{ext} pins a depth but cannot be written"
                assert set(capability.depth_codecs) <= {2, 3, 4}, ext

    def test_lossless_codecs_are_codec_names_not_rows(self) -> None:
        """ALAC is lossless although the M4A row it lands in is not."""
        assert audio_formats.LOSSLESS_CODECS
        for codec in audio_formats.LOSSLESS_CODECS:
            assert codec in CODEC_TO_EXTENSION, codec
            assert codec not in FORMAT_MATRIX, codec

    def test_codec_names_map_onto_matrix_rows(self) -> None:
        assert CODEC_TO_EXTENSION, "no codec mapping - ALAC could not be written"
        for codec, ext in CODEC_TO_EXTENSION.items():
            assert ext in FORMAT_MATRIX, f"{codec} maps to unknown {ext}"
            assert codec and not codec.startswith(".")


class TestTagWritabilityIsHonest:
    """``tag_writable`` must match the handler a writer will actually get."""

    def test_tag_writable_agrees_with_the_handler_factory(self) -> None:
        from audio_suite_shared.tag_helper_base import TagHandlerFactory

        handled = set(TagHandlerFactory._handlers)
        claimed = {ext for ext, cap in FORMAT_MATRIX.items() if cap.tag_writable}
        assert claimed, "no row claims tag support - the scan would pass vacuously"
        assert claimed == handled, (
            "FORMAT_MATRIX.tag_writable disagrees with TagHandlerFactory: "
            f"claims-without-handler={sorted(claimed - handled)}, "
            f"handler-without-claim={sorted(handled - claimed)}"
        )

    def test_formats_beyond_the_handlers_refuse_rather_than_lie(self) -> None:
        for ext in (".wma", ".aac"):
            assert ext in FORMAT_MATRIX
            assert FORMAT_MATRIX[ext].tag_writable is False


class TestExportRefusesWhatItCannotWrite:
    """The old MP3 fallback wrote a mislabelled codec into the target file."""

    @pytest.mark.parametrize("ext", sorted(READ_ONLY_EXTENSIONS))
    def test_read_only_extension_raises(self, ext: str) -> None:
        with pytest.raises(audio_formats.AudioFormatError):
            get_export_args(ext)

    @pytest.mark.parametrize("ext", [".xyz", ".txt", ""])
    def test_unknown_extension_raises(self, ext: str) -> None:
        with pytest.raises(audio_formats.AudioFormatError):
            get_export_args(ext)

    def test_refusal_is_not_a_silent_mp3(self) -> None:
        with pytest.raises(audio_formats.AudioFormatError) as excinfo:
            get_export_args(".xyz")
        assert "mp3" not in str(excinfo.value).lower()

    @pytest.mark.parametrize("ext", sorted(_EXPORTABLE))
    def test_every_exportable_row_still_returns_arguments(self, ext: str) -> None:
        fmt, args = get_export_args(ext)
        assert fmt == FORMAT_MATRIX[ext].pydub_format
        assert isinstance(args, list)

    def test_case_insensitive(self) -> None:
        assert get_export_args(".MP3") == get_export_args(".mp3")


@pytest.fixture(scope="module")
def source_tone(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One 1-second 440 Hz WAV the round-trip lock reuses for every format."""
    from pydub.generators import Sine

    path = tmp_path_factory.mktemp("format_caps") / "tone.wav"
    Sine(440).to_audio_segment(duration=1000, volume=-6).export(str(path), format="wav")
    return path


@requires_ffmpeg
class TestWritableFormatsRoundTrip:
    """Every writable row survives the shared export arguments, measured."""

    @pytest.mark.integration
    @pytest.mark.parametrize("ext", sorted(_EXPORTABLE))
    def test_the_declared_encoder_is_what_lands_in_the_file(
        self, ext: str, source_tone: Path, tmp_path: Path
    ) -> None:
        from pydub import AudioSegment

        capability = FORMAT_MATRIX[ext]
        out = tmp_path / f"tone{ext}"
        fmt, args = get_export_args(ext)
        AudioSegment.from_file(str(source_tone)).export(
            str(out), format=fmt, parameters=args
        )

        assert out.exists() and out.stat().st_size > 0
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert capability.ffmpeg_encoder is not None
        expected = _PROBE_CODEC[capability.ffmpeg_encoder]
        assert probe.stdout.strip() == expected, (
            f"{ext} wrote {probe.stdout.strip()!r}, not {expected!r} - "
            "a silently mislabelled encode"
        )

        # Decoding proves the container is readable, not just present.
        decoded = AudioSegment.from_file(str(out))
        assert len(decoded) > 500, f"{ext} decoded to {len(decoded)} ms"

    @pytest.mark.integration
    def test_wma_is_a_real_asf_container(
        self, source_tone: Path, tmp_path: Path
    ) -> None:
        """The D-4 decision rests on this: wmav2 inside an ASF container."""
        from pydub import AudioSegment

        out = tmp_path / "tone.wma"
        fmt, args = get_export_args(".wma")
        AudioSegment.from_file(str(source_tone)).export(
            str(out), format=fmt, parameters=args
        )
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert probe.stdout.strip().split(",")[0] == "asf"

    @pytest.mark.integration
    def test_wma_is_the_only_new_extension_on_the_disk(
        self, source_tone: Path, tmp_path: Path
    ) -> None:
        """A conversion to .wma writes .wma and nothing else."""
        from pydub import AudioSegment

        fmt, args = get_export_args(".wma")
        AudioSegment.from_file(str(source_tone)).export(
            str(tmp_path / "tone.wma"), format=fmt, parameters=args
        )
        assert sorted(p.name for p in tmp_path.iterdir()) == ["tone.wma"]


class TestDiscoverySeesWma:
    """The user-observable fix: one discovery, not the converter's private one."""

    def test_converter_discovery_finds_a_wma_file(self, tmp_path: Path) -> None:
        from music_format_converter.core.formats import discover_input_files

        (tmp_path / "track.wma").write_bytes(b"not real audio")
        assert discover_input_files(str(tmp_path)) == ["track.wma"]

    def test_shared_discovery_finds_a_wma_file(self, tmp_path: Path) -> None:
        from audio_suite_shared.file_processor_base import BaseFileProcessor

        (tmp_path / "track.wma").write_bytes(b"not real audio")
        processor = BaseFileProcessor.__new__(BaseFileProcessor)
        found = processor.discover_audio_files(str(tmp_path))
        assert [Path(p).name for p in found] == ["track.wma"]

    def test_is_supported_format_accepts_wma(self) -> None:
        assert audio_formats.is_supported_format("track.wma") is True
        assert audio_formats.is_supported_format("TRACK.WMA") is True
        assert audio_formats.is_supported_format("track.wma.bak") is False


# Changed in 2.4.1: WP-7's in-place, tag-write and narrowed-tuple locks live
# here rather than in files of their own names: the test-naming lock
# (tests/test_test_file_naming.py) mirrors test_<module>.py and its
# allowlist is frozen, so the arbiter decides the home (plan D-33).


class TestNarrowedTupleIsLoadBearing:
    """WP-7 bucket (b): the narrowed tuple changes the outcome, both ways."""

    def test_a_mutagen_error_is_an_unknown_depth(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        import mutagen

        from audio_suite_shared.audio_formats import source_bit_depth

        path = tmp_path / "song.flac"
        path.write_bytes(b"not really a flac")
        with patch("mutagen.File", side_effect=mutagen.MutagenError("no header")):
            assert source_bit_depth(str(path)) is None

    def test_an_unexpected_error_is_not_swallowed(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from audio_suite_shared.audio_formats import source_bit_depth

        path = tmp_path / "song.flac"
        path.write_bytes(b"not really a flac")
        with patch("mutagen.File", side_effect=RuntimeError("programming error")):
            with pytest.raises(RuntimeError):
                source_bit_depth(str(path))

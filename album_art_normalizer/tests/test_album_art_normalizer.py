"""
test_album_art_normalizer.py
=========================
Comprehensive pytest suite for album_art_normalizer.py.

All external I/O (Pillow file open, mutagen file open/save, os.startfile,
subprocess.Popen) is stubbed so the tests are fully self-contained and do
not require real audio or image files on disk.

Run with:
    pytest album_art_normalizer/tests/ -v
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------
import album_art_normalizer as aan
from album_art_normalizer import (
    AlbumArtError,
    AudioTagReadError,
    AudioTagWriteError,
    FolderImageError,
    ImageDecodeError,
    ImageResizeSpec,
    ProcessingResult,
    center_crop_to_square,
    encode_image_to_jpeg_bytes,
    load_image_from_bytes,
    process_flac_artwork,
    process_folder_jpg,
    process_mp3_artwork,
    run_processing,
)
from audio_suite_shared.secure_subprocess import SubprocessSecurityError

# ---------------------------------------------------------------------------
# Helpers — synthetic image construction
# ---------------------------------------------------------------------------


def _make_jpeg_bytes(
    width: int, height: int, colour: tuple[int, int, int] = (200, 100, 50)
) -> bytes:
    """Return JPEG-encoded bytes for a solid-colour image of given dimensions."""
    img = Image.new("RGB", (width, height), colour)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _make_png_bytes(width: int, height: int) -> bytes:
    """Return PNG-encoded bytes."""
    img = Image.new("RGB", (width, height), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _garbage_bytes() -> bytes:
    """Return bytes that are not a valid image."""
    return b"\x00\xff\xfe" * 20


# ===========================================================================
# 1. ProcessingResult dataclass
# ===========================================================================


class TestProcessingResult:
    def test_fields_accessible(self) -> None:
        r = ProcessingResult(total_files=10, images_updated=3, errors=1)
        assert r.total_files == 10
        assert r.images_updated == 3
        assert r.errors == 1

    def test_is_frozen(self) -> None:
        r = ProcessingResult(total_files=5, images_updated=2, errors=0)
        with pytest.raises(Exception):
            r.total_files = 99  # type: ignore[misc]


# ===========================================================================
# 2. ImageResizeSpec dataclass
# ===========================================================================


class TestImageResizeSpec:
    def test_square_source_no_crop(self) -> None:
        spec = ImageResizeSpec(source_size=(500, 500), target_size=(800, 800))
        assert spec.needs_crop is False

    def test_landscape_source_needs_crop(self) -> None:
        spec = ImageResizeSpec(source_size=(1200, 600), target_size=(800, 800))
        assert spec.needs_crop is True

    def test_portrait_source_needs_crop(self) -> None:
        spec = ImageResizeSpec(source_size=(400, 700), target_size=(600, 600))
        assert spec.needs_crop is True

    def test_frozen(self) -> None:
        spec = ImageResizeSpec(source_size=(100, 100), target_size=(200, 200))
        with pytest.raises(Exception):
            spec.target_size = (300, 300)  # type: ignore[misc]


# ===========================================================================
# 3. center_crop_to_square
# ===========================================================================


class TestCenterCropToSquare:
    def test_already_square_returns_same_object(self) -> None:
        img = Image.new("RGB", (500, 500))
        result = center_crop_to_square(img)
        assert result is img

    def test_landscape_crops_to_height(self) -> None:
        img = Image.new("RGB", (800, 400))
        result = center_crop_to_square(img)
        assert result.size == (400, 400)

    def test_portrait_crops_to_width(self) -> None:
        img = Image.new("RGB", (300, 900))
        result = center_crop_to_square(img)
        assert result.size == (300, 300)

    def test_crop_is_centred_landscape(self) -> None:
        """Pixels in the centre column survive; edges do not."""
        img = Image.new("RGB", (600, 200), (0, 0, 0))
        # Paint left third red, right third blue; centre is black
        for x in range(200):
            for y in range(200):
                img.putpixel((x, y), (255, 0, 0))
        for x in range(400, 600):
            for y in range(200):
                img.putpixel((x, y), (0, 0, 255))

        cropped = center_crop_to_square(img)
        assert cropped.size == (200, 200)
        # Centre pixel should be black (original centre)
        centre_pixel = cropped.getpixel((100, 100))
        assert centre_pixel == (0, 0, 0)

    def test_single_pixel_square(self) -> None:
        img = Image.new("RGB", (1, 1))
        assert center_crop_to_square(img).size == (1, 1)

    def test_wide_extreme_ratio(self) -> None:
        img = Image.new("RGB", (10000, 100))
        result = center_crop_to_square(img)
        assert result.size == (100, 100)


# ===========================================================================
# 4. load_image_from_bytes
# ===========================================================================


class TestLoadImageFromBytes:
    def test_valid_jpeg(self) -> None:
        data = _make_jpeg_bytes(400, 300)
        img = load_image_from_bytes(data)
        assert img.mode == "RGB"
        assert img.size == (400, 300)

    def test_valid_png(self) -> None:
        data = _make_png_bytes(200, 200)
        img = load_image_from_bytes(data)
        assert img.mode == "RGB"

    def test_garbage_raises_image_decode_error(self) -> None:
        with pytest.raises(ImageDecodeError):
            load_image_from_bytes(_garbage_bytes())

    def test_empty_bytes_raises_image_decode_error(self) -> None:
        with pytest.raises(ImageDecodeError):
            load_image_from_bytes(b"")

    def test_truncated_jpeg_raises(self) -> None:
        data = _make_jpeg_bytes(100, 100)[:50]  # deliberately truncated
        with pytest.raises(ImageDecodeError):
            load_image_from_bytes(data)


# ===========================================================================
# 5. encode_image_to_jpeg_bytes
# ===========================================================================


class TestEncodeImageToJpegBytes:
    def test_output_is_decodable_jpeg(self) -> None:
        img = Image.new("RGB", (400, 400), (128, 64, 32))
        data = encode_image_to_jpeg_bytes(img, (200, 200))
        result = Image.open(io.BytesIO(data))
        assert result.format == "JPEG"
        assert result.size == (200, 200)

    def test_non_square_source_auto_cropped(self) -> None:
        img = Image.new("RGB", (800, 400))
        data = encode_image_to_jpeg_bytes(img, (600, 600))
        result = Image.open(io.BytesIO(data))
        assert result.size == (600, 600)

    def test_large_upscale(self) -> None:
        img = Image.new("RGB", (50, 50))
        data = encode_image_to_jpeg_bytes(img, (1200, 1200))
        result = Image.open(io.BytesIO(data))
        assert result.size == (1200, 1200)

    def test_rgba_source_converted(self) -> None:
        img = Image.new("RGBA", (200, 200), (255, 0, 0, 128))
        data = encode_image_to_jpeg_bytes(img, (100, 100))
        result = Image.open(io.BytesIO(data))
        assert result.mode == "RGB"


# ===========================================================================
# 6. process_folder_jpg
# ===========================================================================


class TestProcessFolderJpg:
    def test_no_folder_jpg_returns_none(self, tmp_path: Path) -> None:
        result = process_folder_jpg(tmp_path)
        assert result is None

    def test_already_correct_size_skipped(self, tmp_path: Path) -> None:
        fj = tmp_path / "folder.jpg"
        img = Image.new("RGB", (1000, 1000), (50, 50, 50))
        img.save(fj, format="JPEG")

        result = process_folder_jpg(tmp_path)
        assert result is not None
        assert "skipped" in result

    def test_wrong_size_resized_and_saved(self, tmp_path: Path) -> None:
        fj = tmp_path / "folder.jpg"
        img = Image.new("RGB", (500, 500), (100, 200, 100))
        img.save(fj, format="JPEG")

        result = process_folder_jpg(tmp_path)
        assert result is not None
        assert "resized" in result

        saved = Image.open(fj)
        assert saved.size == (1000, 1000)

    def test_non_square_folder_jpg_cropped(self, tmp_path: Path) -> None:
        fj = tmp_path / "folder.jpg"
        img = Image.new("RGB", (1200, 600), (0, 128, 255))
        img.save(fj, format="JPEG")

        result = process_folder_jpg(tmp_path)
        assert result is not None
        assert "centre-cropped" in result

        saved = Image.open(fj)
        assert saved.size == (1000, 1000)

    def test_corrupt_folder_jpg_raises(self, tmp_path: Path) -> None:
        fj = tmp_path / "folder.jpg"
        fj.write_bytes(_garbage_bytes())

        with pytest.raises(FolderImageError):
            process_folder_jpg(tmp_path)


# ===========================================================================
# 7. process_mp3_artwork  (mutagen stubbed)
# ===========================================================================


class TestProcessMp3Artwork:
    def _make_mock_mp3(
        self,
        apic_data: bytes | None,
        *,
        has_tags: bool = True,
    ) -> MagicMock:
        mock_audio = MagicMock()
        if not has_tags:
            mock_audio.tags = None
            return mock_audio

        mock_tags = MagicMock()
        mock_audio.tags = mock_tags

        if apic_data is None:
            mock_tags.getall.return_value = []
        else:
            frame = MagicMock()
            frame.data = apic_data
            frame.encoding = 3
            frame.type = 3
            frame.desc = "Cover"
            mock_tags.getall.return_value = [frame]

        return mock_audio

    def test_no_tags_returns_skipped(self, tmp_path: Path) -> None:
        mock_audio = self._make_mock_mp3(None, has_tags=False)
        path = tmp_path / "track.mp3"
        path.touch()

        with patch("album_art_normalizer.MP3", return_value=mock_audio):
            result = process_mp3_artwork(path, (800, 800))
        assert "No ID3 tags" in result

    def test_no_apic_frame_returns_skipped(self, tmp_path: Path) -> None:
        mock_audio = self._make_mock_mp3(None)
        path = tmp_path / "track.mp3"
        path.touch()

        with patch("album_art_normalizer.MP3", return_value=mock_audio):
            result = process_mp3_artwork(path, (800, 800))
        assert "skipped" in result

    def test_correct_size_skipped(self, tmp_path: Path) -> None:
        data = _make_jpeg_bytes(800, 800)
        mock_audio = self._make_mock_mp3(data)
        path = tmp_path / "track.mp3"
        path.touch()

        with patch("album_art_normalizer.MP3", return_value=mock_audio):
            result = process_mp3_artwork(path, (800, 800))
        assert "skipped" in result

    def test_wrong_size_triggers_resize_and_shared_embed(self, tmp_path: Path) -> None:
        data = _make_jpeg_bytes(500, 500)
        mock_audio = self._make_mock_mp3(data)
        path = tmp_path / "track.mp3"
        path.touch()

        with (
            patch("album_art_normalizer.MP3", return_value=mock_audio),
            patch("album_art_normalizer.core.art_processor.embed_artwork") as embed,
        ):
            result = process_mp3_artwork(path, (800, 800))

        assert "resized to 800×800" in result
        assert "saved" in result
        embed.assert_called_once_with(str(path), ANY)
        resized = Image.open(io.BytesIO(embed.call_args.args[1]))
        assert resized.size == (800, 800)

    def test_non_square_source_crop_noted(self, tmp_path: Path) -> None:
        data = _make_jpeg_bytes(1200, 600)
        mock_audio = self._make_mock_mp3(data)
        path = tmp_path / "track.mp3"
        path.touch()

        with (
            patch("album_art_normalizer.MP3", return_value=mock_audio),
            patch("album_art_normalizer.core.art_processor.embed_artwork"),
        ):
            result = process_mp3_artwork(path, (800, 800))

        assert "centre-cropped" in result

    def test_corrupt_apic_raises_image_decode_error(self, tmp_path: Path) -> None:
        mock_audio = self._make_mock_mp3(_garbage_bytes())
        path = tmp_path / "track.mp3"
        path.touch()

        with patch("album_art_normalizer.MP3", return_value=mock_audio):
            with pytest.raises(ImageDecodeError):
                process_mp3_artwork(path, (800, 800))

    def test_mp3_open_failure_raises_audio_tag_read_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.mp3"
        path.touch()

        from mutagen.mp3 import HeaderNotFoundError

        with patch("album_art_normalizer.MP3", side_effect=HeaderNotFoundError("bad")):
            with pytest.raises(AudioTagReadError):
                process_mp3_artwork(path, (800, 800))

    def test_write_failure_raises_shared_audio_error(self, tmp_path: Path) -> None:
        from audio_suite_shared.exceptions import AudioIOError

        data = _make_jpeg_bytes(500, 500)
        mock_audio = self._make_mock_mp3(data)
        path = tmp_path / "track.mp3"
        path.touch()

        with (
            patch("album_art_normalizer.MP3", return_value=mock_audio),
            patch(
                "album_art_normalizer.core.art_processor.embed_artwork",
                side_effect=AudioIOError("disk full"),
            ),
        ):
            with pytest.raises(AudioIOError):
                process_mp3_artwork(path, (800, 800))


# ===========================================================================
# 8. process_flac_artwork  (mutagen stubbed)
# ===========================================================================


class TestProcessFlacArtwork:
    def _make_mock_flac(self, pic_data: bytes | None) -> MagicMock:
        mock_audio = MagicMock()
        if pic_data is None:
            mock_audio.pictures = []
        else:
            pic = MagicMock()
            pic.data = pic_data
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.desc = ""
            mock_audio.pictures = [pic]
        return mock_audio

    def test_no_pictures_skipped(self, tmp_path: Path) -> None:
        mock_audio = self._make_mock_flac(None)
        path = tmp_path / "track.flac"
        path.touch()

        with patch("album_art_normalizer.FLAC", return_value=mock_audio):
            result = process_flac_artwork(path, (600, 600))
        assert "skipped" in result

    def test_correct_size_skipped(self, tmp_path: Path) -> None:
        data = _make_jpeg_bytes(1000, 1000)
        mock_audio = self._make_mock_flac(data)
        path = tmp_path / "track.flac"
        path.touch()

        with patch("album_art_normalizer.FLAC", return_value=mock_audio):
            result = process_flac_artwork(path, (1000, 1000))
        assert "skipped" in result

    def test_wrong_size_resized_and_shared_embed(self, tmp_path: Path) -> None:
        data = _make_jpeg_bytes(400, 400)
        mock_audio = self._make_mock_flac(data)
        path = tmp_path / "track.flac"
        path.touch()

        with (
            patch("album_art_normalizer.FLAC", return_value=mock_audio),
            patch("album_art_normalizer.core.art_processor.embed_artwork") as embed,
        ):
            result = process_flac_artwork(path, (1200, 1200))

        assert "resized to 1200×1200" in result
        assert "saved" in result
        embed.assert_called_once_with(str(path), ANY)
        resized = Image.open(io.BytesIO(embed.call_args.args[1]))
        assert resized.size == (1200, 1200)

    def test_non_square_crop_noted(self, tmp_path: Path) -> None:
        data = _make_jpeg_bytes(800, 400)
        mock_audio = self._make_mock_flac(data)
        path = tmp_path / "track.flac"
        path.touch()

        with (
            patch("album_art_normalizer.FLAC", return_value=mock_audio),
            patch("album_art_normalizer.core.art_processor.embed_artwork"),
        ):
            result = process_flac_artwork(path, (600, 600))
        assert "centre-cropped" in result

    def test_corrupt_picture_raises_image_decode_error(self, tmp_path: Path) -> None:
        mock_audio = self._make_mock_flac(_garbage_bytes())
        path = tmp_path / "track.flac"
        path.touch()

        with patch("album_art_normalizer.FLAC", return_value=mock_audio):
            with pytest.raises(ImageDecodeError):
                process_flac_artwork(path, (800, 800))

    def test_flac_open_failure_raises_audio_tag_read_error(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "bad.flac"
        path.touch()

        from mutagen.flac import FLACNoHeaderError

        with patch("album_art_normalizer.FLAC", side_effect=FLACNoHeaderError("bad")):
            with pytest.raises(AudioTagReadError):
                process_flac_artwork(path, (800, 800))

    def test_save_failure_raises_shared_audio_error(self, tmp_path: Path) -> None:
        from audio_suite_shared.exceptions import AudioIOError

        data = _make_jpeg_bytes(400, 400)
        mock_audio = self._make_mock_flac(data)
        path = tmp_path / "track.flac"
        path.touch()

        with (
            patch("album_art_normalizer.FLAC", return_value=mock_audio),
            patch(
                "album_art_normalizer.core.art_processor.embed_artwork",
                side_effect=AudioIOError("read-only filesystem"),
            ),
        ):
            with pytest.raises(AudioIOError):
                process_flac_artwork(path, (800, 800))


# ===========================================================================
# 9. run_processing orchestrator
# ===========================================================================


class TestRunProcessing:
    """Tests for the thread-worker orchestrator.

    All audio processing functions are patched so we isolate the
    orchestration logic from format-specific code tested above.
    """

    def _collect(
        self, directory: str, target: tuple[int, int]
    ) -> tuple[list[str], ProcessingResult | None]:
        """Run processing synchronously and collect log lines + result."""
        log_lines: list[str] = []
        result_holder: list[ProcessingResult] = []

        run_processing(
            directory=directory,
            target_size=target,
            log_callback=log_lines.append,
            done_callback=result_holder.append,
        )
        return log_lines, result_holder[0] if result_holder else None

    def test_empty_directory_produces_zero_totals(self, tmp_path: Path) -> None:
        with (
            patch("album_art_normalizer.process_folder_jpg", return_value=None),
        ):
            logs, result = self._collect(str(tmp_path), (800, 800))

        assert result is not None
        assert result.total_files == 0
        assert result.images_updated == 0
        assert result.errors == 0

    def test_single_mp3_updated(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "song.mp3"
        mp3.touch()

        with (
            patch("album_art_normalizer.process_folder_jpg", return_value=None),
            patch(
                "album_art_normalizer.process_mp3_artwork",
                return_value=(
                    "Embedded image was 500×500; resized to 800×800 and saved."
                ),
            ),
        ):
            logs, result = self._collect(str(tmp_path), (800, 800))

        assert result is not None
        assert result.total_files == 1
        assert result.images_updated == 1
        assert result.errors == 0

    def test_single_flac_updated(self, tmp_path: Path) -> None:
        flac = tmp_path / "track.flac"
        flac.touch()

        with (
            patch("album_art_normalizer.process_folder_jpg", return_value=None),
            patch(
                "album_art_normalizer.process_flac_artwork",
                return_value=(
                    "Embedded image was 400×400; resized to 1000×1000 and saved."
                ),
            ),
        ):
            logs, result = self._collect(str(tmp_path), (1000, 1000))

        assert result is not None
        assert result.total_files == 1
        assert result.images_updated == 1

    def test_skipped_file_not_counted_as_updated(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "song.mp3"
        mp3.touch()

        with (
            patch("album_art_normalizer.process_folder_jpg", return_value=None),
            patch(
                "album_art_normalizer.process_mp3_artwork",
                return_value="Embedded image already 800×800 — skipped.",
            ),
        ):
            logs, result = self._collect(str(tmp_path), (800, 800))

        assert result is not None
        assert result.images_updated == 0

    def test_error_increments_error_count(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "broken.mp3"
        mp3.touch()

        with (
            patch("album_art_normalizer.process_folder_jpg", return_value=None),
            patch(
                "album_art_normalizer.process_mp3_artwork",
                side_effect=AudioTagReadError("cannot open"),
            ),
        ):
            logs, result = self._collect(str(tmp_path), (800, 800))

        assert result is not None
        assert result.errors == 1
        assert result.images_updated == 0
        assert any("✗ ERROR" in line for line in logs)

    def test_folder_jpg_updated_increments_count(self, tmp_path: Path) -> None:
        with (
            patch(
                "album_art_normalizer.process_folder_jpg",
                return_value="folder.jpg was 500×500; resized to 1000×1000.",
            ),
        ):
            logs, result = self._collect(str(tmp_path), (800, 800))

        assert result is not None
        assert result.images_updated == 1

    def test_folder_jpg_error_increments_error_count(self, tmp_path: Path) -> None:
        with (
            patch(
                "album_art_normalizer.process_folder_jpg",
                side_effect=FolderImageError("read error"),
            ),
        ):
            logs, result = self._collect(str(tmp_path), (800, 800))

        assert result is not None
        assert result.errors == 1

    def test_mixed_mp3_and_flac_both_processed(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").touch()
        (tmp_path / "b.flac").touch()
        (tmp_path / "notes.txt").touch()  # non-audio file excluded

        with (
            patch("album_art_normalizer.process_folder_jpg", return_value=None),
            patch(
                "album_art_normalizer.process_mp3_artwork",
                return_value=(
                    "Embedded image was 300×300; resized to 600×600 and saved."
                ),
            ),
            patch(
                "album_art_normalizer.process_flac_artwork",
                return_value=(
                    "Embedded image was 300×300; resized to 600×600 and saved."
                ),
            ),
        ):
            logs, result = self._collect(str(tmp_path), (600, 600))

        assert result is not None
        assert result.total_files == 2  # .txt excluded
        assert result.images_updated == 2

    def test_unexpected_exception_caught_safely(self, tmp_path: Path) -> None:
        mp3 = tmp_path / "weird.mp3"
        mp3.touch()

        with (
            patch("album_art_normalizer.process_folder_jpg", return_value=None),
            patch(
                "album_art_normalizer.process_mp3_artwork",
                side_effect=MemoryError("OOM"),
            ),
        ):
            logs, result = self._collect(str(tmp_path), (800, 800))

        assert result is not None
        assert result.errors == 1
        assert any("UNEXPECTED ERROR" in line for line in logs)

    def test_log_contains_session_header(self, tmp_path: Path) -> None:
        with patch("album_art_normalizer.process_folder_jpg", return_value=None):
            logs, _ = self._collect(str(tmp_path), (800, 800))

        assert any("Session started" in line for line in logs)
        assert any("Processing complete" in line for line in logs)


# ===========================================================================
# 10. Constants & module-level correctness
# ===========================================================================


class TestModuleConstants:
    def test_supported_extensions_is_tuple(self) -> None:
        assert isinstance(aan.SUPPORTED_EXTENSIONS, tuple)

    def test_supported_extensions_content(self) -> None:
        assert ".mp3" in aan.SUPPORTED_EXTENSIONS
        assert ".flac" in aan.SUPPORTED_EXTENSIONS

    def test_resolution_labels_match_map(self) -> None:
        for label in aan.RESOLUTION_LABELS:
            assert label in aan.RESOLUTION_MAP

    def test_all_allowed_sizes_are_square(self) -> None:
        for w, h in aan.ALLOWED_EMBEDDED_SIZES:
            assert w == h, f"Non-square size found: {w}×{h}"

    def test_folder_jpg_target_is_1000(self) -> None:
        assert aan.FOLDER_JPG_TARGET == (1000, 1000)

    def test_exception_hierarchy(self) -> None:
        assert issubclass(AudioTagReadError, AlbumArtError)
        assert issubclass(AudioTagWriteError, AlbumArtError)
        assert issubclass(ImageDecodeError, AlbumArtError)
        assert issubclass(FolderImageError, AlbumArtError)


# ===========================================================================
# 11. _open_path_in_os (OS-shell helper)
# ===========================================================================


class TestOpenPathInOs:
    def test_windows_calls_startfile(self, tmp_path: Path) -> None:
        with (
            patch(
                "album_art_normalizer.album_art_normalizer.platform.system",
                return_value="Windows",
            ),
            patch(
                "album_art_normalizer.album_art_normalizer.os.startfile", create=True
            ) as mock_sf,
        ):
            aan._open_path_in_os(tmp_path)
        mock_sf.assert_called_once_with(tmp_path)

    def test_darwin_calls_open(self, tmp_path: Path) -> None:
        with (
            patch(
                "album_art_normalizer.album_art_normalizer.platform.system",
                return_value="Darwin",
            ),
            patch(
                "album_art_normalizer.album_art_normalizer.run_secure_subprocess"
            ) as mock_run,
        ):
            aan._open_path_in_os(tmp_path)
        mock_run.assert_called_once_with(
            "open", [str(tmp_path)], capture_output=True, check=False
        )

    def test_linux_calls_xdg_open(self, tmp_path: Path) -> None:
        with (
            patch(
                "album_art_normalizer.album_art_normalizer.platform.system",
                return_value="Linux",
            ),
            patch(
                "album_art_normalizer.album_art_normalizer.run_secure_subprocess"
            ) as mock_run,
        ):
            aan._open_path_in_os(tmp_path)
        mock_run.assert_called_once_with(
            "xdg-open", [str(tmp_path)], capture_output=True, check=False
        )

    def test_os_error_handled_gracefully(self, tmp_path: Path) -> None:
        with (
            patch(
                "album_art_normalizer.album_art_normalizer.platform.system",
                return_value="Linux",
            ),
            patch(
                "album_art_normalizer.album_art_normalizer.run_secure_subprocess",
                side_effect=OSError("not found"),
            ),
            patch(
                "album_art_normalizer.album_art_normalizer.messagebox.showerror"
            ) as mock_err,
        ):
            aan._open_path_in_os(tmp_path)  # must not raise
        mock_err.assert_called_once()

    def test_security_error_handled_gracefully(self, tmp_path: Path) -> None:
        with (
            patch(
                "album_art_normalizer.album_art_normalizer.platform.system",
                return_value="Linux",
            ),
            patch(
                "album_art_normalizer.album_art_normalizer.run_secure_subprocess",
                side_effect=SubprocessSecurityError("blocked"),
            ),
            patch(
                "album_art_normalizer.album_art_normalizer.messagebox.showerror"
            ) as mock_err,
        ):
            aan._open_path_in_os(tmp_path)  # must not raise
        mock_err.assert_called_once()

"""
album_art_normalizer
====================
Orchestrator, image-processing, and embed-writer modules for normalising
album artwork in MP3, FLAC, OGG, Opus, M4A, MP4, WAV, AIFF and AIF files.

Sub-modules
-----------
app
    Tkinter GUI application (thin orchestrator).
core
    Business logic: file_processor, art_processor, art_writer.
ui
    Widget builders: setup_tab, processing_tab, results_tab.
utils
    CLI argument parsing.
"""

# Re-export mutagen symbols so that
#   ``unittest.mock.patch("album_art_normalizer.MP3", …)``
# works even when the per-format processors import these names
# from ``album_art_normalizer`` at function call time.
from mutagen.flac import FLAC, FLACNoHeaderError, Picture  # noqa: F401
from mutagen.id3 import (  # noqa: F401
    APIC,
    ID3,
    ID3NoHeaderError,
    ID3UnsupportedVersionError,
)
from mutagen.mp3 import MP3, HeaderNotFoundError, InvalidMPEGHeader  # noqa: F401

# Re-export old orchestrator function for direct API compatibility
from album_art_normalizer.album_art_normalizer import (  # noqa: F401
    _configure_file_logging,
    _open_path_in_os,
    run_processing,
)

# Re-export the GUI app class
from album_art_normalizer.app import ArtNormalizerApp  # noqa: F401

# Re-export core processing symbols
from album_art_normalizer.core.art_processor import (  # noqa: F401
    ALLOWED_EMBEDDED_SIZES,
    FOLDER_JPG_TARGET,
    RESOLUTION_LABELS,
    RESOLUTION_MAP,
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
    process_audio_artwork,
    process_flac_artwork,
    process_folder_jpg,
    process_mp3_artwork,
)

# Re-export the unified write API
from album_art_normalizer.core.art_writer import embed_artwork_into_file  # noqa: F401
from album_art_normalizer.core.file_processor import (
    run_normalization,  # noqa: F401
)
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS  # noqa: F401

__all__ = [
    "ALLOWED_EMBEDDED_SIZES",
    "APIC",
    "AlbumArtError",
    "ArtNormalizerApp",
    "AudioTagReadError",
    "AudioTagWriteError",
    "FLAC",
    "FLACNoHeaderError",
    "FOLDER_JPG_TARGET",
    "FolderImageError",
    "HeaderNotFoundError",
    "ID3",
    "ID3NoHeaderError",
    "ID3UnsupportedVersionError",
    "ImageDecodeError",
    "ImageResizeSpec",
    "InvalidMPEGHeader",
    "MP3",
    "Picture",
    "ProcessingResult",
    "RESOLUTION_LABELS",
    "RESOLUTION_MAP",
    "SUPPORTED_EXTENSIONS",
    "_configure_file_logging",
    "_open_path_in_os",
    "center_crop_to_square",
    "embed_artwork_into_file",
    "encode_image_to_jpeg_bytes",
    "load_image_from_bytes",
    "process_audio_artwork",
    "process_flac_artwork",
    "process_folder_jpg",
    "process_mp3_artwork",
    "run_normalization",
    "run_processing",
]

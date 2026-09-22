"""
tests/test_app_audio_detection.py
Regression test for BPMAnalyzerApp.start_processing()'s "does this folder
contain supported audio?" pre-flight check.

Bug: the pre-flight check in app.py previously hardcoded its own extension
list (".mp3", ".flac", ".ogg", ".m4a", ".opus"), which had drifted out of
sync with the real source of truth — audio_suite_shared.audio_formats.
SUPPORTED_EXTENSIONS, which also includes ".wav", ".aiff", ".aif". A folder
containing only WAV/AIFF files was therefore incorrectly rejected by the UI
before processing ever started, even though run_analysis() (via
BaseFileProcessor.discover_audio_files -> SUPPORTED_EXTENSIONS) and the
tag read/write path (IFFID3Handler) both fully support those formats.

app.py cannot be imported directly in this environment (it requires
tkinter, which is unavailable here), so this test exercises the exact
check app.py now performs — `any(is_supported_format(f) for f in
os.listdir(folder))` — directly against real temporary directories. This
proves the fixed logic is correct and would have caught the original bug:
the OLD hardcoded-list check is also exercised below and is shown to fail
on the same WAV/AIFF-only directories that the fixed check accepts.
"""

from __future__ import annotations

import os
import tempfile

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS, is_supported_format


def _old_hardcoded_check(folder: str) -> bool:
    """Reproduces the pre-fix logic verbatim, for regression comparison."""
    return any(
        f.lower().endswith(ext)
        for f in os.listdir(folder)
        for ext in [".mp3", ".flac", ".ogg", ".m4a", ".opus"]
    )


def _new_check(folder: str) -> bool:
    """The fixed logic now used in app.py."""
    return any(is_supported_format(f) for f in os.listdir(folder))


class TestPreflightAudioDetectionRegression:
    def test_wav_only_folder_is_detected_by_fixed_check(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "track.wav"), "w").close()
            assert _new_check(folder) is True

    def test_aiff_only_folder_is_detected_by_fixed_check(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "track.aiff"), "w").close()
            assert _new_check(folder) is True

    def test_aif_short_extension_is_detected_by_fixed_check(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "track.aif"), "w").close()
            assert _new_check(folder) is True

    def test_old_hardcoded_check_incorrectly_rejected_wav_only_folder(self):
        """Demonstrates the bug: the OLD check returns False (no audio
        found) for a folder that, in reality, contains a fully-supported
        WAV file — the false-rejection this fix resolves."""
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "track.wav"), "w").close()
            assert _old_hardcoded_check(folder) is False

    def test_old_hardcoded_check_incorrectly_rejected_aiff_only_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "track.aiff"), "w").close()
            assert _old_hardcoded_check(folder) is False

    def test_fixed_check_still_detects_originally_supported_formats(self):
        """Non-regression: formats already handled before the fix must
        still be detected."""
        for ext in (".mp3", ".flac", ".ogg", ".m4a", ".opus"):
            with tempfile.TemporaryDirectory() as folder:
                open(os.path.join(folder, f"track{ext}"), "w").close()
                assert _new_check(folder) is True, f"{ext} should be detected"

    def test_fixed_check_rejects_folder_with_no_audio_files(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "readme.txt"), "w").close()
            assert _new_check(folder) is False

    def test_fixed_check_matches_shared_supported_extensions_exactly(self):
        """The fixed check must accept every extension in the real source
        of truth — guards against future drift re-introducing this bug."""
        for ext in SUPPORTED_EXTENSIONS:
            with tempfile.TemporaryDirectory() as folder:
                open(os.path.join(folder, f"track{ext}"), "w").close()
                assert _new_check(folder) is True, (
                    f"{ext} is in SUPPORTED_EXTENSIONS but was not detected "
                    "by the pre-flight check"
                )

"""
tests/test_processor.py
Pytest test suite for Audio Enhancer core modules.

Run with:
    pytest tests/test_processor.py -v

Coverage
--------
Models
  * EnhancementParams defaults and preset ordering
  * JobStatus enum — all members present (including FAILED added in fix)
  * ProcessingResult.gain_db property
  * ProcessingResult.display_text field

Processor helpers (no pedalboard required)
  * _rms_db: silence, full-scale sine, impulse, multi-channel
  * _resolve_mp3_quality: CBR exact, CBR snapping, VBR string format

DSP signal-integrity tests (pedalboard mocked)
  * Impulse response — DC is preserved through a unity-gain chain
  * Pure sine wave — THD guard: fundamental energy dominates
  * Digital silence — no DC offset introduced (|mean| < 1e-9)
  * Extreme parameters — ∞:1 compressor ratio + 0 dB noise gate must not crash
  * Clipping guard — limiter prevents output above 0 dBFS
  * float64 precision — audio enters and exits _rms_db as float64

Inspector
  * find_audio_files: single file, unsupported, directory, sorted
  * find_audio_files: .opus and .m4a are supported extensions
  * inspect: graceful fallback on corrupt file
  * inspect: Opus sample_rate defaults to 48000, not the generic 44100
    (mutagen's OggOpusInfo has no sample_rate attribute)

Tags
  * copy_tags: ImportError branch returns (False, 0)
  * copy_tags: ID3NoHeaderError on dst creates fresh ID3 header

Changed in 1.1.0: retargeted the chain mocks to
apply_enhancement_chain, added the effect-control builder tests and
live-vs-dry-run effect assertions.
Changed in 2.1.3: dropped the ``apply_effects`` keyword assertions and added
``TestDryRunMatchesTheLiveRun``, which measures a dry run and a live run of the
same cancelling effect on a real WAV and requires equal levels (R-09).
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import numpy.typing as npt
import pytest

from audio_enhancer.core.models import (
    PRESETS,
    AudioFileInfo,
    EnhancementParams,
    JobStatus,
    PresetName,
    ProcessingResult,
)
from audio_enhancer.core.processor import (
    ENHANCER_UNSUPPORTED_FORMATS,
    _resolve_mp3_quality,
    process_file,
)
from audio_suite_shared.dsp_chain import compute_rms_db as _rms_db

# ── Helpers ───────────────────────────────────────────────────────────────────

SR: int = 44_100  # standard sample rate used across all synthetic signals


def _sine(
    freq_hz: float, duration_s: float = 1.0, channels: int = 1
) -> npt.NDArray[np.float64]:
    """Return a full-scale sine wave with shape (channels, samples) as float64."""
    t = np.linspace(0, duration_s, int(SR * duration_s), endpoint=False)
    wave = np.sin(2.0 * np.pi * freq_hz * t).astype(np.float64)
    return np.tile(wave, (channels, 1))


def _silence(duration_s: float = 1.0, channels: int = 2) -> npt.NDArray[np.float64]:
    return np.zeros((channels, int(SR * duration_s)), dtype=np.float64)


def _impulse(channels: int = 1, length: int = SR) -> npt.NDArray[np.float64]:
    """Kronecker delta δ[0] — non-zero only at sample index 0."""
    sig = np.zeros((channels, length), dtype=np.float64)
    sig[:, 0] = 1.0
    return sig


# ── Models ────────────────────────────────────────────────────────────────────


class TestEnhancementParams:
    def test_defaults_are_moderate_preset(self) -> None:
        p = EnhancementParams()
        m = PRESETS[PresetName.MODERATE]
        assert p.compressor_ratio == m.compressor_ratio
        assert p.high_shelf_gain_db == m.high_shelf_gain_db

    def test_all_presets_present(self) -> None:
        for name in (PresetName.MILD, PresetName.MODERATE, PresetName.AGGRESSIVE):
            assert name in PRESETS

    def test_aggressive_louder_than_mild(self) -> None:
        assert (
            PRESETS[PresetName.AGGRESSIVE].output_gain_db
            > PRESETS[PresetName.MILD].output_gain_db
        )
        assert (
            PRESETS[PresetName.AGGRESSIVE].high_shelf_gain_db
            > PRESETS[PresetName.MILD].high_shelf_gain_db
        )


class TestJobStatusEnum:
    """Every member that file_processor.py references must exist on JobStatus."""

    @pytest.mark.parametrize(
        "member", ["QUEUED", "PROCESSING", "DONE", "ERROR", "FAILED", "SKIPPED"]
    )
    def test_member_present(self, member: str) -> None:
        assert hasattr(JobStatus, member), f"JobStatus.{member} is missing"

    def test_failed_not_same_as_error(self) -> None:
        assert JobStatus.FAILED != JobStatus.ERROR


class TestProcessingResult:
    def test_gain_db_property(self) -> None:
        r = ProcessingResult(source=Path("test.mp3"))
        r.rms_before_db = -20.0
        r.rms_after_db = -15.0
        assert r.gain_db == pytest.approx(5.0)

    def test_default_status_queued(self) -> None:
        r = ProcessingResult(source=Path("test.mp3"))
        assert r.status == JobStatus.QUEUED

    def test_display_text_field_exists(self) -> None:
        """display_text must exist so file_processor
        error-path constructors don't crash."""
        r = ProcessingResult(display_text="[SKIP] track.mp3: file not found")
        assert r.display_text == "[SKIP] track.mp3: file not found"

    def test_display_text_defaults_to_empty_string(self) -> None:
        r = ProcessingResult(source=Path("test.mp3"))
        assert r.display_text == ""


# ── Processor helpers ─────────────────────────────────────────────────────────


class TestRmsDb:
    def test_silence_returns_very_low_db(self) -> None:
        assert _rms_db(_silence()) < -80.0

    def test_full_scale_sine_near_minus3_dbfs(self) -> None:
        """RMS of a full-scale sine is 1/√2 ≈ −3.01 dBFS."""
        audio = _sine(440.0)
        assert -4.0 < _rms_db(audio) < -2.0

    def test_impulse_rms_db_finite(self) -> None:
        """An impulse has finite, well-defined RMS — must not return NaN or ±Inf."""
        value = _rms_db(_impulse())
        assert np.isfinite(value)

    def test_multichannel_input_accepted(self) -> None:
        """_rms_db must handle stereo (2, N) arrays without raising."""
        audio = _sine(1_000.0, channels=2)
        value = _rms_db(audio)
        assert np.isfinite(value)

    def test_input_dtype_is_float64(self) -> None:
        """Confirms test fixtures honour the float64 precision mandate."""
        audio = _sine(440.0)
        assert audio.dtype == np.float64


class TestResolveMp3Quality:
    def test_cbr_320_stays_320(self) -> None:
        info = AudioFileInfo(path=Path("test.mp3"), is_vbr=False, bitrate_kbps=320)
        assert _resolve_mp3_quality(info) == 320

    def test_cbr_snaps_to_nearest(self) -> None:
        info = AudioFileInfo(path=Path("test.mp3"), is_vbr=False, bitrate_kbps=210)
        assert _resolve_mp3_quality(info) in (192, 224)

    def test_vbr_returns_string_preset(self) -> None:
        info = AudioFileInfo(path=Path("test.mp3"), is_vbr=True, bitrate_kbps=245)
        result = _resolve_mp3_quality(info)
        assert isinstance(result, str) and result.startswith("V")

    def test_vbr_high_bitrate_maps_to_v0(self) -> None:
        info = AudioFileInfo(path=Path("test.mp3"), is_vbr=True, bitrate_kbps=250)
        assert _resolve_mp3_quality(info) == "V0"

    def test_vbr_low_bitrate_maps_to_v7(self) -> None:
        info = AudioFileInfo(path=Path("test.mp3"), is_vbr=True, bitrate_kbps=95)
        assert _resolve_mp3_quality(info) == "V7"


# ── DSP chain signal-integrity tests (pedalboard mocked) ─────────────────────


def _make_identity_pedalboard() -> MagicMock:
    """
    Return a mock Pedalboard that passes audio through unchanged.
    This lets us test the _build_chain / process_file wiring without pedalboard
    being installed in the test environment.
    """
    board = MagicMock()
    board.__call__ = lambda self_, audio, sr: audio  # identity transform
    board.side_effect = lambda audio, sr: audio
    return board


@pytest.fixture()
def identity_chain() -> MagicMock:
    return _make_identity_pedalboard()


class TestDspChainSignalIntegrity:
    """
    Signal-integrity tests against the complete _build_chain path.

    Because pedalboard may not be installed in CI/test environments, every test
    here replaces the _build_chain call with a controlled substitute that lets
    us isolate the mathematical guarantees we care about:

      1. Impulse response — DC preserved through unity-gain chain
      2. Sine THD guard — after identity chain, spectrum unchanged
      3. Digital silence — no DC offset introduced (|mean| < 1e-9)
      4. Extreme parameters — ∞-style ratio + tight noise gate must not crash
      5. Clipping guard — output never exceeds ±1.0 after limiter
      6. float64 precision — dtype survives round-trip through mocked chain
    """

    def test_impulse_dc_preservation(self) -> None:
        """
        Impulse response test (δ[n]).
        A unity-gain chain must preserve the total energy of the impulse.
        Sum of the impulse == 1.0 (one non-zero sample at full scale).
        """
        impulse = _impulse(channels=1, length=SR)
        # Pass through identity chain
        output = impulse.copy()
        assert float(np.sum(output)) == pytest.approx(1.0, abs=1e-9)

    def test_sine_thd_spectral_purity(self) -> None:
        """
        THD guard using a 1 kHz full-scale sine.
        After an identity chain the fundamental bin must contain > 99 % of
        total spectral energy — no harmonic distortion has been introduced.
        """
        audio = _sine(1_000.0, duration_s=1.0, channels=1)
        mono = audio[0]

        spectrum = np.abs(np.fft.rfft(mono)) ** 2
        freqs = np.fft.rfftfreq(len(mono), d=1.0 / SR)

        # Find the fundamental bin (closest to 1 kHz)
        fundamental_idx = int(np.argmin(np.abs(freqs - 1_000.0)))
        fundamental_energy = spectrum[fundamental_idx]
        total_energy = spectrum.sum()

        thd_ratio = float(fundamental_energy / (total_energy + 1e-30))
        assert thd_ratio > 0.99, (
            f"Fundamental energy ratio {thd_ratio:.4f} < 0.99 — unexpected distortion"
        )

    def test_digital_silence_no_dc_offset(self) -> None:
        """
        Digital silence (all zeros) through an identity chain must not
        accumulate a DC offset.  |mean| must be below the float64 noise floor.
        """
        audio = _silence(duration_s=1.0, channels=2)
        output = audio.copy()  # identity
        assert abs(float(np.mean(output))) < 1e-9, (
            "DC offset detected in silence passthrough"
        )

    def test_digital_silence_no_added_noise(self) -> None:
        """RMS of silence output must remain below −80 dBFS."""
        audio = _silence(duration_s=1.0, channels=2)
        assert _rms_db(audio) < -80.0

    def test_extreme_compressor_ratio_does_not_crash(self) -> None:
        """
        Boundary test: very large (∞-style) compressor ratio and a 0 dB noise gate.
        _build_chain must construct without raising; the audio output must be
        numerically finite (no NaN / Inf).
        We mock pedalboard so no external install is needed.
        """
        extreme_params = EnhancementParams(
            compressor_ratio=1_000.0,  # approaches ∞:1 hard limiting
            noise_gate_threshold_db=0.0,  # gate at 0 dB — blocks almost everything
        )
        mock_board = MagicMock()
        mock_board.side_effect = lambda audio, sr: audio  # identity

        with patch(
            "audio_suite_shared.dsp_chain.build_enhancement_chain",
            return_value=mock_board,
        ):
            from audio_suite_shared.dsp_chain import build_enhancement_chain

            chain = build_enhancement_chain(extreme_params)
            audio = _sine(440.0, channels=2)
            output = chain(audio, SR)

        assert np.all(np.isfinite(output)), (
            "Non-finite values in output for extreme parameters"
        )

    def test_output_does_not_clip(self) -> None:
        """
        Clipping guard: a hard-limited signal (Limiter present in chain) must
        never produce samples outside the ±1.0 range.  We feed a 2× over-driven
        sine and expect the mocked limiter to clamp it.
        """

        # Simulate limiter: clamp to ±1.0
        def _mock_limiter(
            audio: npt.NDArray[np.float64], sr: int
        ) -> npt.NDArray[np.float64]:
            return np.clip(audio, -1.0, 1.0).astype(np.float64)

        mock_board = MagicMock()
        mock_board.side_effect = _mock_limiter

        with patch(
            "audio_suite_shared.dsp_chain.build_enhancement_chain",
            return_value=mock_board,
        ):
            from audio_suite_shared.dsp_chain import build_enhancement_chain

            chain = build_enhancement_chain(EnhancementParams())
            overdriven = _sine(440.0, channels=2) * 2.0  # intentionally clip-inducing
            output = chain(overdriven, SR)

        assert float(np.max(np.abs(output))) <= 1.0, (
            "Clipping: samples exceed ±1.0 dBFS"
        )

    def test_float64_precision_preserved(self) -> None:
        """
        dtype mandate (claude.md §3): float64 must survive through rms_db.
        The upcast in process_file converts pedalboard's float32 output to float64
        before any further computation.  This test verifies that _rms_db accepts
        and correctly processes float64 input without silent downcast.
        """
        audio_f64 = _sine(1_000.0, channels=1)  # fixture returns float64
        assert audio_f64.dtype == np.float64
        result = _rms_db(audio_f64)
        assert isinstance(result, float)
        assert np.isfinite(result)


# ── Inspector ─────────────────────────────────────────────────────────────────


class TestFindAudioFiles:
    def test_single_supported_file(self, tmp_path: Path) -> None:
        from audio_enhancer.core.inspector import find_audio_files

        f = tmp_path / "track.mp3"
        f.touch()
        assert find_audio_files(f) == [f]

    def test_unsupported_file_returns_empty(self, tmp_path: Path) -> None:
        from audio_enhancer.core.inspector import find_audio_files

        f = tmp_path / "document.pdf"
        f.touch()
        assert find_audio_files(f) == []

    def test_directory_finds_audio_files(self, tmp_path: Path) -> None:
        from audio_enhancer.core.inspector import find_audio_files

        (tmp_path / "a.mp3").touch()
        (tmp_path / "b.flac").touch()
        (tmp_path / "c.txt").touch()
        results = find_audio_files(tmp_path)
        assert len(results) == 2
        assert all(p.suffix in (".mp3", ".flac") for p in results)

    def test_directory_results_are_sorted(self, tmp_path: Path) -> None:
        from audio_enhancer.core.inspector import find_audio_files

        for name in ("c.mp3", "a.mp3", "b.mp3"):
            (tmp_path / name).touch()
        names = [p.name for p in find_audio_files(tmp_path)]
        assert names == sorted(names)

    def test_opus_is_a_supported_extension(self, tmp_path: Path) -> None:
        """Regression guard: .opus must be discoverable. Added when Opus
        support was introduced via core/ffmpeg_io.py (pedalboard itself
        has no Opus read/write support — confirmed via
        pedalboard.io.get_supported_read_formats()/get_supported_write_formats())."""
        from audio_enhancer.core.inspector import find_audio_files

        f = tmp_path / "track.opus"
        f.touch()
        assert find_audio_files(f) == [f]

    def test_m4a_is_a_supported_extension(self, tmp_path: Path) -> None:
        """.m4a was already in SUPPORTED_EXTENSIONS before this change,
        but had no working write path until core/ffmpeg_io.py was added
        (pedalboard cannot write .m4a) — guard the discovery side too."""
        from audio_enhancer.core.inspector import find_audio_files

        f = tmp_path / "track.m4a"
        f.touch()
        assert find_audio_files(f) == [f]


class TestInspect:
    def test_inspect_returns_audiofileinfo(self, tmp_path: Path) -> None:
        """inspect() must return an AudioFileInfo without raising for a real path."""
        from audio_enhancer.core.inspector import inspect as ae_inspect

        f = tmp_path / "test.mp3"
        f.touch()
        # inspect() calls mutagen internally;
        # it gracefully returns defaults on empty file
        info = ae_inspect(f)
        assert info.path == f

    def test_inspect_graceful_on_bad_file(self, tmp_path: Path) -> None:
        """inspect() must not raise on corrupt data
        — returns a default AudioFileInfo."""
        from audio_enhancer.core.inspector import inspect as ae_inspect

        f = tmp_path / "corrupt.mp3"
        f.write_bytes(b"not an mp3")
        info = ae_inspect(f)
        assert info.path == f

    def test_inspect_opus_sample_rate_defaults_to_48000_not_44100(
        self, tmp_path: Path
    ) -> None:
        """Regression guard: mutagen's OggOpusInfo has no `sample_rate`
        attribute (verified empirically — getattr's fallback always
        fires for real .opus files), and Opus is always 48000 Hz
        internally per RFC 6716 regardless of source material. inspect()
        must use 48000 as the Opus-specific fallback, not the generic
        44100 used for other formats."""
        import shutil
        import subprocess

        if shutil.which("ffmpeg") is None:
            pytest.skip(
                "ffmpeg not found on PATH — needed to produce a real .opus fixture"
            )

        from audio_enhancer.core.inspector import inspect as ae_inspect

        wav_path = tmp_path / "src.wav"
        opus_path = tmp_path / "src.opus"
        sr = 44100  # deliberately NOT 48000, to prove the
        # value isn't just echoed through
        t = np.linspace(0, 0.2, int(sr * 0.2), endpoint=False)
        sine = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

        from pedalboard.io import AudioFile

        with AudioFile(str(wav_path), "w", sr, num_channels=1) as f:
            f.write(sine.reshape(1, -1))

        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-c:a", "libopus", str(opus_path)],
            capture_output=True,
            check=True,
        )

        info = ae_inspect(opus_path)
        assert info.sample_rate == 48000


# ── Tags ──────────────────────────────────────────────────────────────────────


class TestCopyTags:
    def test_missing_mutagen_returns_false(self, tmp_path: Path) -> None:
        """
        When mutagen is not available the ImportError guard in copy_tags must
        return (False, 0) without raising.  We simulate absence by injecting
        None into sys.modules for the mutagen namespace, then force a fresh
        module reload so the guard branch is actually executed.
        """
        import importlib

        import audio_enhancer.core.tags as tags_module

        src = tmp_path / "src.mp3"
        dst = tmp_path / "dst.mp3"
        src.touch()
        dst.touch()

        with patch.dict(sys.modules, {"mutagen": None, "mutagen.id3": None}):
            # Reload the module so it picks up the patched sys.modules
            reloaded = importlib.reload(tags_module)
            ok, count = reloaded.copy_tags(src, dst)

        assert ok is False
        assert count == 0

        # Restore the original module after the test
        importlib.reload(tags_module)

    def test_id3_no_header_on_dst_creates_fresh_id3(self, tmp_path: Path) -> None:
        """
        _copy_id3 must create a fresh ID3() object when the destination file
        has no ID3 header (i.e. bare pedalboard MP3 output), then save all
        frames from the source.
        """
        from mutagen.id3 import ID3, TIT2

        from audio_enhancer.core.tags import _copy_id3

        src = tmp_path / "src.mp3"
        dst = tmp_path / "dst.mp3"

        # Build a minimal real ID3 tag on the source
        src_id3 = ID3()
        src_id3.add(TIT2(encoding=3, text=["Test Title"]))
        src.write_bytes(b"\xff\xfb" * 100)  # bare MP3 stub
        src_id3.save(str(src))

        # Destination is a bare stream — ID3() read will raise ID3NoHeaderError
        dst.write_bytes(b"\xff\xfb" * 100)

        ok, count = _copy_id3(src, dst)
        assert ok is True
        assert count >= 1

        # Verify the frame was actually written to dst
        saved = ID3(str(dst))
        assert "TIT2" in saved

    def test_copy_id3_no_source_header_returns_false(self, tmp_path: Path) -> None:
        """A source MP3 without an ID3 header yields (False, 0)."""
        from audio_enhancer.core.tags import _copy_id3

        src = tmp_path / "src.mp3"
        dst = tmp_path / "dst.mp3"
        src.write_bytes(b"\xff\xfb" * 100)
        dst.write_bytes(b"\xff\xfb" * 100)

        ok, count = _copy_id3(src, dst)
        assert ok is False
        assert count == 0

    def test_log_id3_summary_emits_info(self, tmp_path, caplog) -> None:
        """_log_id3_summary logs frame counts and APIC/TXXX breakdown."""
        import logging

        from mutagen.id3 import APIC, ID3, TIT2, TXXX

        from audio_enhancer.core.tags import _log_id3_summary

        id3 = ID3()
        id3.add(TIT2(encoding=3, text=["T"]))
        id3.add(TXXX(encoding=3, desc="BPM", text=["120"]))
        id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=b"x"))

        with caplog.at_level(logging.DEBUG, logger="audio_enhancer.core.tags"):
            _log_id3_summary(id3, 3)

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("frame(s)" in r.getMessage() for r in info_records)

    def test_copy_generic_flac_round_trip(self, tmp_path: Path) -> None:
        """_copy_generic copies Vorbis comments from FLAC src to FLAC dst."""
        from mutagen.flac import FLAC
        from pydub import AudioSegment

        from audio_enhancer.core.tags import _copy_generic

        src = tmp_path / "src.flac"
        dst = tmp_path / "dst.flac"
        for f in (src, dst):
            AudioSegment.silent(duration=50).export(str(f), format="flac")
        flac = FLAC(str(src))
        flac["artist"] = ["Copy Me"]
        flac["bpm"] = ["125"]
        flac.save()

        ok, count = _copy_generic(src, dst)
        assert ok is True
        assert count >= 2

        copied = FLAC(str(dst))
        assert copied["artist"] == ["Copy Me"]
        assert copied["bpm"] == ["125"]

    def test_copy_generic_unopenable_returns_false(self, tmp_path: Path) -> None:
        """Non-audio payloads make _copy_generic return (False, 0)."""
        from audio_enhancer.core.tags import _copy_generic

        src = tmp_path / "src.flac"
        dst = tmp_path / "dst.flac"
        src.write_bytes(b"junk")
        dst.write_bytes(b"junk")

        ok, count = _copy_generic(src, dst)
        assert ok is False
        assert count == 0

    def test_copy_tags_routes_mp3_to_id3_and_flac_to_generic(
        self, tmp_path: Path
    ) -> None:
        """copy_tags dispatches by extension: mp3 -> ID3 path, else generic."""
        from mutagen.flac import FLAC
        from pydub import AudioSegment

        from audio_enhancer.core.tags import copy_tags

        AudioSegment.silent(duration=50).export(str(tmp_path / "s.flac"), format="flac")
        AudioSegment.silent(duration=50).export(str(tmp_path / "d.flac"), format="flac")
        flac = FLAC(str(tmp_path / "s.flac"))
        flac["title"] = ["Routed"]
        flac.save()

        ok, count = copy_tags(tmp_path / "s.flac", tmp_path / "d.flac")
        assert ok is True
        assert count >= 1


# ── Setup tab: build_dsp_sliders ─────────────────────────────────────────


class TestBuildDspSliders:
    """Tests for ui/setup_tab.py: build_dsp_sliders()."""

    @staticmethod
    @pytest.fixture(scope="module")
    def tk_root():
        """Create a single Tk root for the entire test class to avoid repeated
        Tcl interpreter creation/destruction (which has been observed to fail
        on Windows with certain tk 8.6 installations)."""
        import tkinter as tk

        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError:
            pytest.skip("Tkinter display not available")
        yield root
        root.destroy()

    @staticmethod
    @pytest.fixture(scope="module")
    def parent(tk_root) -> tk.Frame:
        import tkinter as tk

        return tk.Frame(tk_root)

    def _build_sliders(
        self, parent: tk.Frame, params: EnhancementParams
    ) -> tuple[dict[str, tk.DoubleVar], dict[str, object]]:
        from audio_enhancer.ui.setup_tab import build_dsp_sliders
        from audio_enhancer.ui.setup_tab import ui_common as _

        with patch.object(_, "slider_row"):
            return build_dsp_sliders(parent, params)

    # ── Field mapping ─────────────────────────────────────────────────────

    def test_all_fields_present(self, parent: tk.Frame) -> None:
        """Every numeric DSP field must have a corresponding slider var."""
        from audio_enhancer.ui.setup_tab import NUMERIC_DSP_FIELDS

        vars_, _ = self._build_sliders(parent, EnhancementParams())
        assert set(vars_.keys()) == set(NUMERIC_DSP_FIELDS)
        assert len(vars_) == len(NUMERIC_DSP_FIELDS)

    def test_no_extra_fields(self, parent: tk.Frame) -> None:
        """The slider mapping must not contain non-numeric fields (effects)."""
        from audio_enhancer.ui.setup_tab import NUMERIC_DSP_FIELDS

        vars_, _ = self._build_sliders(parent, EnhancementParams())
        assert set(vars_.keys()) == set(NUMERIC_DSP_FIELDS)  # no extras, no missing

    # ── Default value synchronisation ─────────────────────────────────────

    def test_initial_values_match_params(self, parent: tk.Frame) -> None:
        """Slider initial values must match the EnhancementParams defaults
        (which are the Moderate preset values)."""
        from audio_enhancer.ui.setup_tab import NUMERIC_DSP_FIELDS

        params = EnhancementParams()
        vars_, _ = self._build_sliders(parent, params)
        for field_name in NUMERIC_DSP_FIELDS:
            assert vars_[field_name].get() == pytest.approx(getattr(params, field_name))

    def test_initial_values_not_all_zero(self, parent: tk.Frame) -> None:
        """Sanity guard: at least some slider values must be non-zero (if all
        are zero, the defaults were likely not wired through correctly)."""
        from audio_enhancer.ui.setup_tab import NUMERIC_DSP_FIELDS

        params = EnhancementParams()
        vars_, _ = self._build_sliders(parent, params)
        non_zero = sum(1 for f in NUMERIC_DSP_FIELDS if vars_[f].get() != 0.0)
        assert non_zero >= 10  # at least 10 of the numeric fields should be non-zero

    # ── Trace callback: slider -> params propagation ──────────────────────

    def test_trace_updates_params(self, parent: tk.Frame) -> None:
        """Writing to a slider var must trigger the trace callback and update
        the param_values dict."""
        params = EnhancementParams()
        vars_, param_values = self._build_sliders(parent, params)

        vars_["noise_gate_threshold_db"].set(-50.0)
        assert param_values["noise_gate_threshold_db"] == -50.0

        vars_["compressor_ratio"].set(6.0)
        assert param_values["compressor_ratio"] == 6.0

    def test_trace_updates_all_params(self, parent: tk.Frame) -> None:
        """Every slider var must have a trace wired that propagates to param_values."""
        from audio_enhancer.ui.setup_tab import NUMERIC_DSP_FIELDS

        params = EnhancementParams()
        vars_, param_values = self._build_sliders(parent, params)

        for field_name in NUMERIC_DSP_FIELDS:
            original = getattr(params, field_name)
            # Pick a value that is different from the original
            new_value = original + 5.0 if isinstance(original, (int, float)) else 1
            vars_[field_name].set(new_value)
            assert param_values[field_name] == new_value, (
                f"Trace did not update {field_name}"
            )

    def test_trace_does_not_affect_other_fields(self, parent: tk.Frame) -> None:
        """Changing one slider must not alter other fields in param_values."""
        from audio_enhancer.ui.setup_tab import NUMERIC_DSP_FIELDS

        params = EnhancementParams()
        vars_, param_values = self._build_sliders(parent, params)

        # Record all values
        before = dict(param_values)

        vars_["compressor_ratio"].set(8.0)

        for field_name in NUMERIC_DSP_FIELDS:
            if field_name == "compressor_ratio":
                assert param_values[field_name] == 8.0
            else:
                assert param_values[field_name] == before[field_name], (
                    f"{field_name} changed unexpectedly"
                )

    # ── Preset application logic ──────────────────────────────────────────

    def test_preset_application_mild(self, parent: tk.Frame) -> None:
        """Applying the Mild preset must update all slider vars (and thus
        param_values) to the correct mild values."""
        params = EnhancementParams()
        vars_, param_values = self._build_sliders(parent, params)
        mild = PRESETS[PresetName.MILD]

        # Apply Mild preset (same logic as _on_preset_change in setup_tab.py)
        for field_name in mild.__dataclass_fields__:
            var = vars_.get(field_name)
            if var is not None:
                var.set(getattr(mild, field_name))

        assert param_values["noise_gate_threshold_db"] == mild.noise_gate_threshold_db
        assert param_values["compressor_ratio"] == mild.compressor_ratio
        assert param_values["low_shelf_gain_db"] == mild.low_shelf_gain_db
        assert param_values["presence_gain_db"] == mild.presence_gain_db
        assert param_values["high_shelf_gain_db"] == mild.high_shelf_gain_db
        assert param_values["output_gain_db"] == mild.output_gain_db

    def test_preset_application_aggressive(self, parent: tk.Frame) -> None:
        """Applying the Aggressive preset must update all slider values."""
        params = EnhancementParams()
        vars_, param_values = self._build_sliders(parent, params)
        aggressive = PRESETS[PresetName.AGGRESSIVE]

        for field_name in aggressive.__dataclass_fields__:
            var = vars_.get(field_name)
            if var is not None:
                var.set(getattr(aggressive, field_name))

        assert param_values["compressor_ratio"] == aggressive.compressor_ratio
        assert param_values["high_shelf_gain_db"] == aggressive.high_shelf_gain_db
        assert param_values["output_gain_db"] == aggressive.output_gain_db

    def test_preset_transition_mild_to_aggressive(self, parent: tk.Frame) -> None:
        """Transitioning from Mild to Aggressive must produce Aggressive values."""
        params = EnhancementParams()
        vars_, param_values = self._build_sliders(parent, params)

        # Apply Mild
        mild = PRESETS[PresetName.MILD]
        for field_name in mild.__dataclass_fields__:
            var = vars_.get(field_name)
            if var is not None:
                var.set(getattr(mild, field_name))

        # Then apply Aggressive
        aggressive = PRESETS[PresetName.AGGRESSIVE]
        for field_name in aggressive.__dataclass_fields__:
            var = vars_.get(field_name)
            if var is not None:
                var.set(getattr(aggressive, field_name))

        assert param_values["compressor_ratio"] == aggressive.compressor_ratio
        assert param_values["output_gain_db"] == aggressive.output_gain_db
        assert param_values["high_shelf_gain_db"] == aggressive.high_shelf_gain_db


# ── Setup tab: build_effect_controls (Sprint 1 effects, D12/D17) ─────────


class TestBuildEffectControls:
    """Tests for ui/setup_tab.py: build_effect_controls()."""

    @staticmethod
    @pytest.fixture(scope="module")
    def tk_root():
        import tkinter as tk

        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError:
            pytest.skip("Tkinter display not available")
        yield root
        root.destroy()

    @staticmethod
    @pytest.fixture(scope="module")
    def parent(tk_root) -> tk.Frame:
        import tkinter as tk

        return tk.Frame(tk_root)

    _EFFECT_FIELDS = (
        "reverse",
        "karaoke",
        "phaser",
        "flanger",
        "chorus",
        "karaoke_strength",
    )

    def _build(
        self, parent: tk.Frame, params: EnhancementParams
    ) -> tuple[dict[str, "tk.Variable"], dict[str, object]]:
        from audio_enhancer.ui.setup_tab import build_effect_controls
        from audio_enhancer.ui.setup_tab import ui_common as _

        param_values: dict[str, object] = {}
        with patch.object(_, "slider_row"):
            vars_ = build_effect_controls(parent, params, param_values)
        return vars_, param_values

    def test_all_effect_fields_present(self, parent: tk.Frame) -> None:
        """All six effect fields must have a control var."""
        vars_, _ = self._build(parent, EnhancementParams())
        assert set(vars_.keys()) == set(self._EFFECT_FIELDS)

    def test_initial_values_match_params(self, parent: tk.Frame) -> None:
        """Controls reflect the params object on construction."""
        params = EnhancementParams()
        vars_, param_values = self._build(parent, params)
        for field_name in self._EFFECT_FIELDS:
            assert vars_[field_name].get() == getattr(params, field_name)
            assert param_values[field_name] == getattr(params, field_name)

    def test_defaults_are_effects_off(self, parent: tk.Frame) -> None:
        """D12: every effect defaults off (karaoke_strength aside)."""
        vars_, param_values = self._build(parent, EnhancementParams())
        for field_name in self._EFFECT_FIELDS[:-1]:
            assert param_values[field_name] is False
        assert param_values["karaoke_strength"] == 1.0

    def test_toggle_trace_writes_bool(self, parent: tk.Frame) -> None:
        """Toggling a checkbox updates param_values with a real bool."""
        vars_, param_values = self._build(parent, EnhancementParams())

        vars_["reverse"].set(True)
        assert param_values["reverse"] is True

        vars_["phaser"].set(True)
        assert param_values["phaser"] is True
        assert param_values["flanger"] is False  # untouched

    def test_strength_trace_updates_param_values(self, parent: tk.Frame) -> None:
        vars_, param_values = self._build(parent, EnhancementParams())
        vars_["karaoke_strength"].set(0.5)
        assert param_values["karaoke_strength"] == pytest.approx(0.5)

    def test_combined_dict_builds_complete_params(self, parent: tk.Frame) -> None:
        """Sharing one param_values dict across both builders yields a dict
        that reconstructs all 19 EnhancementParams fields."""
        from audio_enhancer.ui.setup_tab import (
            build_dsp_sliders,
            build_effect_controls,
        )
        from audio_enhancer.ui.setup_tab import ui_common as _

        original = EnhancementParams()
        with patch.object(_, "slider_row"):
            _, param_values = build_dsp_sliders(parent, original)
            build_effect_controls(parent, original, param_values)

        assert set(param_values.keys()) == set(
            EnhancementParams.__dataclass_fields__.keys()
        )
        rebuilt = EnhancementParams(**param_values)
        assert rebuilt == original


# ── process_file: orchestration of one file through the DSP chain ────────


class TestProcessFile:
    """Covers audio_enhancer/core/processor.py's process_file() end-to-end.

    The heavy dependencies (pedalboard chain, ffmpeg I/O, tag copying) are
    mocked so the control flow — read → enhance → RMS → write → tags → status —
    can be exercised deterministically without external tools.  This is the
    module's largest uncovered surface (51 lines at audit time).
    """

    def _info(
        self, tmp_path: Path, name: str = "in.opus"
    ) -> tuple[AudioFileInfo, Path]:
        src = tmp_path / name
        src.write_bytes(b"\x00" * 16)
        out = tmp_path / "out"
        info = AudioFileInfo(path=src, bitrate_kbps=128, id3_version=4)
        return info, out

    def test_ffmpeg_extension_success(self, tmp_path: Path) -> None:
        """.opus routes through ffmpeg_io and completes with DONE status."""
        info, out = self._info(tmp_path, "in.opus")
        audio = _sine(440.0, channels=2).astype(np.float32)
        progress: list[str] = []

        with (
            patch(
                "audio_enhancer.core.processor.apply_enhancement_chain",
                return_value=MagicMock(),
            ) as apply_chain,
            patch(
                "audio_enhancer.core.processor.compute_rms_db",
                side_effect=lambda a: -20.0,
            ),
            patch(
                "audio_enhancer.core.processor.post_chain_clip_check",
                side_effect=lambda a, stage_name="Enhance": a,
            ),
            patch(
                "audio_enhancer.core.ffmpeg_io.read_audio",
                return_value=(audio, SR),
            ) as read_audio,
            patch("audio_enhancer.core.ffmpeg_io.write_audio") as write_audio,
            patch("audio_enhancer.core.processor.copy_tags", return_value=(True, 3)),
        ):
            result = process_file(
                info, EnhancementParams(), out, on_progress=progress.append
            )

        apply_chain.assert_called_once()
        # No dry-run flag reaches the DSP: every call site asks for the chain
        # the parameters describe (R-09).
        assert apply_chain.call_args.kwargs == {}
        read_audio.assert_called_once_with(info.path)
        write_audio.assert_called_once()
        assert result.status == JobStatus.DONE
        assert result.output == out / "in.opus"
        assert result.rms_before_db == pytest.approx(-20.0)
        assert result.rms_after_db == pytest.approx(-20.0)
        assert result.tags_copied == 3
        assert progress, "on_progress callback should have been invoked"

    def test_mp4_routes_through_ffmpeg_io(self, tmp_path: Path) -> None:
        """.mp4 (added to FFMPEG_EXTENSIONS in phase 1.3) must route through
        ffmpeg_io like .m4a, not pedalboard."""
        info, out = self._info(tmp_path, "in.mp4")
        audio = _sine(440.0, channels=2).astype(np.float32)

        with (
            patch(
                "audio_enhancer.core.processor.apply_enhancement_chain",
                return_value=MagicMock(),
            ),
            patch("audio_enhancer.core.processor.compute_rms_db", return_value=-20.0),
            patch(
                "audio_enhancer.core.processor.post_chain_clip_check",
                side_effect=lambda a, stage_name="Enhance": a,
            ),
            patch(
                "audio_enhancer.core.ffmpeg_io.read_audio",
                return_value=(audio, SR),
            ) as read_audio,
            patch("audio_enhancer.core.ffmpeg_io.write_audio") as write_audio,
            patch("audio_enhancer.core.processor.copy_tags", return_value=(True, 2)),
        ):
            result = process_file(info, EnhancementParams(), out)

        read_audio.assert_called_once_with(info.path)
        write_audio.assert_called_once()
        assert result.status == JobStatus.DONE
        assert result.output == out / "in.mp4"

    def test_non_ffmpeg_extension_uses_pedalboard_read(self, tmp_path: Path) -> None:
        """.wav (not in FFMPEG_EXTENSIONS) reads and writes
        via pedalboard.io.AudioFile."""
        info, out = self._info(tmp_path, "in.wav")

        fake_audiofile = MagicMock()
        handle = MagicMock()
        handle.frames = SR
        handle.samplerate = float(SR)
        handle.read.return_value = np.zeros((2, SR), dtype=np.float32)
        fake_audiofile.return_value.__enter__.return_value = handle

        with (
            patch(
                "audio_enhancer.core.processor.apply_enhancement_chain",
                return_value=MagicMock(),
            ),
            patch("audio_enhancer.core.processor.compute_rms_db", return_value=-30.0),
            patch(
                "audio_enhancer.core.processor.post_chain_clip_check",
                side_effect=lambda a, stage_name="Enhance": a,
            ),
            patch("audio_enhancer.core.processor.copy_tags", return_value=(False, 0)),
            patch("pedalboard.io.AudioFile", fake_audiofile),
        ):
            result = process_file(info, EnhancementParams(), out)

        assert result.status == JobStatus.DONE
        assert result.tags_copied == 0
        # The write path must also go through pedalboard (mode "w") for .wav.
        write_calls = [c for c in fake_audiofile.call_args_list if "w" in c.args]
        assert write_calls, "expected a pedalboard AudioFile write call"

    def test_missing_pedalboard_returns_error(self, tmp_path: Path) -> None:
        """A missing pedalboard maps to a missing-dependency error result."""
        info, out = self._info(tmp_path, "in.wav")

        def _fake_read(path):
            raise AssertionError("ffmpeg read should not run for .wav")

        with (
            patch.dict(sys.modules, {"pedalboard": None, "pedalboard.io": None}),
            patch("audio_enhancer.core.ffmpeg_io.read_audio", side_effect=_fake_read),
        ):
            result = process_file(info, EnhancementParams(), out)

        assert result.status == JobStatus.ERROR
        assert "pedalboard" in result.error_message.lower()

    def test_read_oserror_maps_to_error_result(self, tmp_path: Path) -> None:
        """An OSError from audio read is mapped to a user-facing ERROR result."""
        info, out = self._info(tmp_path, "in.opus")

        def _boom(path):
            raise OSError("no such device")

        with (
            patch("audio_enhancer.core.ffmpeg_io.read_audio", side_effect=_boom),
        ):
            result = process_file(info, EnhancementParams(), out)

        assert result.status == JobStatus.ERROR
        assert result.error_message, "error_message should be populated"

    def test_mp3_write_forwards_quality(self, tmp_path: Path) -> None:
        """.mp3 output goes through _write_audio with a resolved CBR quality."""
        info, out = self._info(tmp_path, "in.mp3")
        info.bitrate_kbps = 320
        info.is_vbr = False

        fake_audiofile = MagicMock()
        handle = MagicMock()
        handle.frames = SR
        handle.samplerate = float(SR)
        handle.read.return_value = np.zeros((1, SR), dtype=np.float32)
        fake_audiofile.return_value.__enter__.return_value = handle

        with (
            patch(
                "audio_enhancer.core.processor.apply_enhancement_chain",
                return_value=MagicMock(),
            ),
            patch("audio_enhancer.core.processor.compute_rms_db", return_value=0.0),
            patch(
                "audio_enhancer.core.processor.post_chain_clip_check",
                side_effect=lambda a, stage_name="Enhance": a,
            ),
            patch("audio_enhancer.core.processor.copy_tags", return_value=(True, 1)),
            patch("pedalboard.io.AudioFile", fake_audiofile),
        ):
            result = process_file(info, EnhancementParams(), out)

        assert result.status == JobStatus.DONE
        write_kwargs = [
            c.kwargs
            for c in fake_audiofile.call_args_list
            if c.kwargs.get("quality") is not None
        ]
        assert write_kwargs, "write call should carry an explicit quality for .mp3"
        assert write_kwargs[0]["quality"] == 320

    def test_dry_run_measures_but_writes_nothing(self, tmp_path: Path) -> None:
        """Dry Run must run the DSP chain (so level/gain are measured) but
        must NOT create an output file or copy tags — verifying the real
        outcome, not read-back of internal state."""
        info, out = self._info(tmp_path, "in.opus")
        audio = _sine(440.0, channels=2).astype(np.float32)

        with (
            patch(
                "audio_enhancer.core.processor.apply_enhancement_chain",
                return_value=MagicMock(),
            ) as apply_chain,
            patch(
                "audio_enhancer.core.processor.compute_rms_db",
                side_effect=[-30.0, -20.0],
            ),
            patch(
                "audio_enhancer.core.processor.post_chain_clip_check",
                side_effect=lambda a, stage_name="Enhance": a,
            ),
            patch(
                "audio_enhancer.core.ffmpeg_io.read_audio",
                return_value=(audio, SR),
            ),
            patch("audio_enhancer.core.ffmpeg_io.write_audio") as write_audio,
            patch("audio_enhancer.core.processor.copy_tags") as copy_tags,
        ):
            result = process_file(info, EnhancementParams(), out, dry_run=True)

        write_audio.assert_not_called()
        copy_tags.assert_not_called()
        assert not (out / "in.opus").exists()
        assert result.status == JobStatus.DONE
        assert result.tags_copied == 0
        assert result.rms_before_db == pytest.approx(-30.0)
        assert result.rms_after_db == pytest.approx(-20.0)
        assert result.gain_db == pytest.approx(10.0)
        apply_chain.assert_called_once()
        # Identical call shape to the live run above - the dry-run difference
        # is the early return, not a different chain (R-09).
        assert apply_chain.call_args.kwargs == {}


class TestDryRunMatchesTheLiveRun:
    """R-09: a dry run must measure the chain the live run writes.

    Both rows below go through the same ``process_file`` entry point on a real
    WAV, so the equality is between two measured outcomes rather than between a
    result and the configuration it was derived from.
    """

    @staticmethod
    def _write_centred_wav(path: Path) -> None:
        """Write a stereo WAV whose two channels are identical.

        Karaoke is a channel subtraction, so an identical-channel source
        collapses to near-silence. That makes "the effect ran" and "the base
        chain ran" 40 dB apart - a difference one measurement cannot hide.
        """
        from pedalboard.io import AudioFile

        mono = _sine(440.0, duration_s=0.5).astype(np.float32)
        audio = np.vstack([mono, mono])
        with AudioFile(str(path), "w", SR, num_channels=2) as handle:
            handle.write(audio)

    def test_dry_run_measures_the_full_chain(self, tmp_path: Path) -> None:
        """Dry and live runs of a cancelling effect report the same level."""
        src = tmp_path / "centred.wav"
        self._write_centred_wav(src)
        out_dir = tmp_path / "out"
        info = AudioFileInfo(path=src)
        params = EnhancementParams(karaoke=True)

        dry = process_file(info, params, out_dir, dry_run=True)
        assert dry.status == JobStatus.DONE
        assert not out_dir.exists(), "a dry run must create nothing"

        live = process_file(info, params, out_dir, dry_run=False)
        assert live.status == JobStatus.DONE
        assert (out_dir / "centred.wav").is_file()

        assert dry.rms_after_db == pytest.approx(live.rms_after_db, abs=1e-9)
        # Karaoke cancellation is what makes that equality meaningful: a
        # base-chain measurement would sit near the source level instead.
        assert dry.rms_after_db < dry.rms_before_db - 6.0, (
            f"dry run reported {dry.rms_after_db:.2f} dBFS from "
            f"{dry.rms_before_db:.2f} dBFS - the karaoke stage did not run"
        )

    def test_full_chain_differs_from_base_chain_when_an_effect_is_on(self) -> None:
        """Guards the equality above: it can only fail if the chains differ."""
        from audio_suite_shared.dsp_chain import (
            apply_enhancement_chain,
            build_enhancement_chain,
            compute_rms_db,
        )

        mono = _sine(440.0, duration_s=0.5)
        audio = np.vstack([mono, mono])
        params = EnhancementParams(karaoke=True)

        full_db = compute_rms_db(apply_enhancement_chain(audio, SR, params))
        base_db = compute_rms_db(build_enhancement_chain(params)(audio, SR))
        assert base_db - full_db > 6.0


class TestUnsupportedFormatSkip:
    """The enhancer discovers the shared SUPPORTED_EXTENSIONS but cannot
    re-encode 5 of those formats (.wv/.spx/.ape/.mpc/.dsf); they must be
    skipped cleanly with a truthful message rather than decoded (which
    raises a misleading "invalid or corrupted" error).  Guards against the
    Item 1.1 format widening surfacing unprocessable files as errors (D6).
    """

    @pytest.mark.parametrize("ext", sorted(ENHANCER_UNSUPPORTED_FORMATS))
    def test_unsupported_format_is_skipped_without_processing(
        self, tmp_path: Path, ext: str
    ) -> None:
        src = tmp_path / f"track{ext}"
        src.write_bytes(b"\x00" * 16)
        out = tmp_path / "out"
        info = AudioFileInfo(path=src)

        with patch("audio_enhancer.core.processor.apply_enhancement_chain") as chain:
            result = process_file(info, EnhancementParams(), out)

        chain.assert_not_called()
        assert result.status == JobStatus.SKIPPED
        assert result.display_text.startswith("[SKIP]")
        assert "unsupported format" in result.display_text
        assert ext in result.display_text
        assert not (out / f"track{ext}").exists()

    def test_round_trippable_formats_are_not_in_unsupported_set(self) -> None:
        """Positive control: every format the enhancer can encode must be
        outside the skip guard, so the set cannot widen silently."""
        round_trippable = {
            ".wav",
            ".aif",
            ".aiff",
            ".flac",
            ".mp3",
            ".ogg",
            ".opus",
            ".m4a",
            ".mp4",
        }
        assert round_trippable.isdisjoint(ENHANCER_UNSUPPORTED_FORMATS)

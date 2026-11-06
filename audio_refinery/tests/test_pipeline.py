"""Album-mode plumbing through the REFINE pipeline's Normalise stage.

Changed in 2.5.0: new file (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E1).

Album mode is the one place where the stage must *not* measure the file it is
about to write: the gain belongs to the folder, so the run's plan supplies it.
These locks therefore fail if the per-file measurement runs, and they read the
stage message and the file state rather than the pipeline's own flags alone.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import numpy as np
import pytest
from pydub import AudioSegment

from audio_normalizer.core.album import AlbumPlan, plan_key
from audio_refinery.core.models import (
    FileStatus,
    NormaliseParams,
    StageConfig,
    TrimParams,
)

FS = 44100


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _valid_integrity() -> Iterator[None]:
    """Placeholder bytes are not real audio; pass the pre-flight."""
    from audio_refinery.core.integrity import IntegrityResult, IntegrityStatus

    fake = IntegrityResult(path=Path("fake.flac"), status=IntegrityStatus.PASS)
    fake.file_size_bytes = 1024
    fake.duration_ms = 5000.0
    fake.sample_rate = 44100
    fake.channels = 2
    with patch("audio_refinery.core.pipeline.validate_file", return_value=fake):
        yield


def _sine(duration_ms: int = 200, amplitude: float = 0.3) -> AudioSegment:
    n = int(FS * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    pcm = (amplitude * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    return AudioSegment(pcm.tobytes(), frame_rate=FS, sample_width=2, channels=1)


def _source(tmp_path: Path, name: str = "track.flac") -> Path:
    path = tmp_path / name
    path.write_bytes(b"ORIGINAL-AUDIO-BYTES")
    return path


def _fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (
        hashlib.sha256(path.read_bytes()).hexdigest(),
        stat.st_mtime_ns,
        stat.st_size,
    )


def _album_config(
    *, dry_run: bool = False, declick: bool = False, **overrides: float | bool
) -> StageConfig:
    """An album-mode config whose stage toggles never share a param name."""
    config = StageConfig(
        declick=declick, trim=False, enhance=False, normalise=True, dry_run=dry_run
    )
    config.normalise_params = NormaliseParams(
        target_lufs=-16.0, tolerance=0.5, true_peak=-1.5, album_mode=True
    )
    for key, value in overrides.items():
        setattr(config.normalise_params, key, value)
    return config


def _plan(source: Path, gain: float, *, limited: bool = False) -> AlbumPlan:
    key = plan_key(source)
    return AlbumPlan(
        album_lufs=-23.0,
        target_lufs=-16.0,
        true_peak_ceiling=-1.5,
        gains={key: gain},
        limited={key: limited},
        album_true_peak=-3.0,
        notes=(),
    )


def _stage_messages(result: Any) -> dict[str, str]:
    return {stage.stage: stage.message for stage in result.stages}


# ── The stage consumes the plan ─────────────────────────────────────────────


class TestAlbumNormaliseStage:
    """One gain from the plan, no per-file measurement, honest reporting."""

    def test_album_mode_applies_the_plan_gain_without_measuring(
        self, tmp_path: Path
    ) -> None:
        from audio_refinery.core.pipeline import process_file

        source = _source(tmp_path)
        plan = _plan(source, -3.2)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as segment,
            patch(
                "audio_normalizer.core.album.apply_album_gain", return_value=True
            ) as applied,
            patch("audio_refinery.core.pipeline.record_tag_edit_snapshot") as snapshot,
            patch(
                "audio_normalizer.core.loudness.measure",
                side_effect=AssertionError("album mode must not measure per file"),
            ),
        ):
            segment.from_file.return_value = _sine()
            result = process_file(source, source, _album_config(), album_plan=plan)

        assert result.status is FileStatus.DONE
        assert result.was_modified is True
        applied.assert_called_once()
        assert applied.call_args.args[0] == str(source)
        assert applied.call_args.args[1] == pytest.approx(-3.2)
        snapshot.assert_called_once()

        message = _stage_messages(result)["Normalise"]
        assert "album gain -3.2 dB" in message
        assert "-23.0" in message and "-16.0" in message

    def test_a_limited_track_reports_the_ceiling(self, tmp_path: Path) -> None:
        from audio_refinery.core.pipeline import process_file

        source = _source(tmp_path)
        plan = _plan(source, -0.8, limited=True)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as segment,
            patch(
                "audio_normalizer.core.album.apply_album_gain", return_value=True
            ) as applied,
            patch("audio_refinery.core.pipeline.record_tag_edit_snapshot"),
        ):
            segment.from_file.return_value = _sine()
            result = process_file(source, source, _album_config(), album_plan=plan)

        assert applied.call_args.kwargs["limit"] is True
        assert (
            "limited to the -1.5 dBTP ceiling" in _stage_messages(result)["Normalise"]
        )

    def test_zero_gain_leaves_the_file_untouched(self, tmp_path: Path) -> None:
        from audio_refinery.core.pipeline import process_file

        source = _source(tmp_path)
        before = _fingerprint(source)
        plan = _plan(source, 0.0)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as segment,
            patch("audio_normalizer.core.album.apply_album_gain") as applied,
            patch("audio_refinery.core.pipeline.record_tag_edit_snapshot") as snapshot,
        ):
            segment.from_file.return_value = _sine()
            result = process_file(source, source, _album_config(), album_plan=plan)

        assert result.status is FileStatus.SKIPPED
        assert result.was_modified is False
        applied.assert_not_called()
        snapshot.assert_not_called()
        assert "no adjustment needed" in _stage_messages(result)["Normalise"]
        assert _fingerprint(source) == before

    def test_a_dry_run_reports_the_planned_gain_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        from audio_refinery.core.pipeline import process_file

        source = _source(tmp_path)
        before = _fingerprint(source)
        plan = _plan(source, -3.2)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as segment,
            patch("audio_normalizer.core.album.apply_album_gain") as applied,
            patch("audio_refinery.core.pipeline.record_tag_edit_snapshot") as snapshot,
        ):
            segment.from_file.return_value = _sine()
            result = process_file(
                source,
                source,
                _album_config(dry_run=True),
                album_plan=plan,
            )

        assert result.status is FileStatus.DONE
        assert result.was_modified is False
        applied.assert_not_called()
        snapshot.assert_not_called()
        assert _stage_messages(result)["Normalise"] == (
            "Would apply album gain -3.2 dB (album -23.0 LUFS -> -16.0 LUFS)"
        )
        assert _fingerprint(source) == before

    def test_a_staged_run_takes_the_source_gain(self, tmp_path: Path) -> None:
        """A multi-stage run normalises the staged copy, keyed by the source."""
        from audio_refinery.core.pipeline import process_file

        source = _source(tmp_path)
        plan = _plan(source, -2.5)
        config = _album_config(declick=True)

        def _write(
            audio: AudioSegment, path: Path | str, *args: Any, **kwargs: Any
        ) -> None:
            Path(path).write_bytes(b"PROCESSED-AUDIO-BYTES")

        def _declick(audio: AudioSegment, **kwargs: Any) -> Any:
            from types import SimpleNamespace

            return SimpleNamespace(audio=audio, was_modified=True, clicks_found=2)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as segment,
            patch(
                "pop_click_remover.core.declicker.declick_audio", side_effect=_declick
            ),
            patch("audio_refinery.core.pipeline._write_output", side_effect=_write),
            patch(
                "audio_normalizer.core.album.apply_album_gain", return_value=True
            ) as applied,
            patch("audio_refinery.core.pipeline.record_tag_edit_snapshot") as snapshot,
        ):
            segment.from_file.return_value = _sine()
            result = process_file(source, source, config, album_plan=plan)

        assert result.status is FileStatus.DONE
        applied.assert_called_once()
        staged = applied.call_args.args[0]
        assert staged != str(source)
        assert Path(staged).name.endswith(".flac")
        assert applied.call_args.args[1] == pytest.approx(-2.5)
        # One snapshot, against the real output — never the staging file.
        snapshot.assert_called_once()
        assert snapshot.call_args.args[0] == str(source)


class TestAlbumModeDefaults:
    def test_album_mode_is_off_unless_asked_for(self) -> None:
        assert NormaliseParams().album_mode is False


# ── Exact trim ───────────────────────────────────────────────────────────


def _exact_config(*, dry_run: bool = False, **overrides: object) -> StageConfig:
    """A trim-only config in exact mode, so no other stage can share a name."""
    config = StageConfig(
        declick=False, trim=True, enhance=False, normalise=False, dry_run=dry_run
    )
    params = TrimParams(mode="exact", start_ms=250, end_ms=750)
    for key, value in overrides.items():
        setattr(params, key, value)
    config.trim_params = params
    return config


class TestExactTrimStage:
    """The stage keeps the range it was given instead of detecting silence."""

    def test_exact_mode_slices_without_detecting_silence(self) -> None:
        from audio_refinery.core.pipeline import _run_trim_stage

        with patch(
            "silence_trimmer.core.trimmer.trim_and_fade",
            side_effect=AssertionError("exact mode must not detect silence"),
        ):
            sliced, message, changed = _run_trim_stage(
                _sine(2000), _exact_config(), lambda *_: None
            )

        assert changed is True
        assert len(sliced) == 500
        assert message == (
            "Exact trim to 0.500 s (0.250-0.750 s), sample-accurate re-encode"
        )

    def test_a_dry_run_reports_the_range_and_leaves_the_audio_alone(self) -> None:
        from audio_refinery.core.pipeline import _run_trim_stage

        audio = _sine(2000)

        returned, message, changed = _run_trim_stage(
            audio, _exact_config(dry_run=True), lambda *_: None
        )

        assert returned is audio
        assert changed is False
        assert message == "Would trim to 0.500 s (0.250-0.750 s)"

    def test_a_range_past_the_end_fails_the_stage(self) -> None:
        from audio_refinery.core.pipeline import _run_trim_stage
        from audio_suite_shared.exceptions import AudioProcessingError

        with pytest.raises(AudioProcessingError) as raised:
            _run_trim_stage(
                _sine(200),
                _exact_config(start_ms=100, end_ms=5000),
                lambda *_: None,
            )

        assert "200 ms long" in str(raised.value)


class TestExactCopyTrimRun:
    """Copy mode writes one stream copy and never decodes the audio."""

    @staticmethod
    def _copy(source: Path, destination: Path, exact_range: Any) -> float:
        Path(destination).write_bytes(b"TRIMMED-COPY")
        return 500.0

    def test_the_copied_range_replaces_the_file_with_one_snapshot(
        self, tmp_path: Path
    ) -> None:
        from audio_refinery.core.pipeline import process_file

        source = _source(tmp_path)
        before = _fingerprint(source)
        config = _exact_config(copy_mode=True)

        with (
            patch(
                "audio_refinery.core.pipeline.probe_duration_ms",
                return_value=2000.0,
            ),
            patch(
                "audio_refinery.core.pipeline.copy_trim", side_effect=self._copy
            ) as copied,
            patch("audio_refinery.core.pipeline.record_tag_edit_snapshot") as snapshot,
            patch("audio_refinery.core.pipeline.read_tags_raw") as tags,
        ):
            result = process_file(source, source, config)

        assert result.status is FileStatus.DONE
        assert result.was_modified is True
        assert source.read_bytes() == b"TRIMMED-COPY"
        assert _fingerprint(source) != before
        copied.assert_called_once()
        tags.assert_not_called()
        snapshot.assert_called_once()
        assert snapshot.call_args.args[0] == str(source)
        assert "frame-accurate stream copy" in _stage_messages(result)["Trim"]
        metrics = result.get_stage_metrics("Trim")
        assert metrics is not None
        assert metrics.after_values["duration_ms"] == 500.0

    def test_a_dry_run_reports_the_range_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        from audio_refinery.core.pipeline import process_file

        source = _source(tmp_path)
        before = _fingerprint(source)

        with (
            patch(
                "audio_refinery.core.pipeline.probe_duration_ms",
                return_value=2000.0,
            ),
            patch(
                "audio_refinery.core.pipeline.copy_trim",
                side_effect=AssertionError("a dry run must not copy"),
            ),
        ):
            result = process_file(
                source, source, _exact_config(dry_run=True, copy_mode=True)
            )

        assert result.status is FileStatus.DONE
        assert result.was_modified is False
        assert _fingerprint(source) == before
        assert _stage_messages(result)["Trim"] == (
            "Would trim to 0.500 s (0.250-0.750 s)"
        )

    def test_copy_mode_beside_another_stage_fails_with_the_reason(
        self, tmp_path: Path
    ) -> None:
        from audio_refinery.core.pipeline import process_file

        source = _source(tmp_path)
        before = _fingerprint(source)
        config = _exact_config(copy_mode=True)
        config.enhance = True

        result = process_file(source, source, config)

        assert result.status is FileStatus.ERROR
        assert "Enhance" in (result.error or "")
        assert _fingerprint(source) == before

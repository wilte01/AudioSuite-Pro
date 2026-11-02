"""No-op, Dry Run and single-pass normalise contract for the REFINE pipeline.

Locks U-02 (`PLAN_restoration_2026-10-31.md` §11): a run no enabled stage
changed must leave the destination byte-identical (no export, tag rewrite,
undo snapshot or replace), a Dry Run must detect with the enabled stages
while writing nothing anywhere, and a normalise-only run must apply FFmpeg
loudnorm directly to the source instead of exporting first.

Every assertion compares the file on disk (SHA-256, size and mtime) or the
decoded outcome, never the pipeline's own ``was_modified`` field alone — a
broken "nothing happened" flag cannot pass silently because each clean case
has a damaged counter-case that must still rewrite the file.

Changed in 2.3.1 (U-02): new file — the no-op, Dry Run and single-pass
normalise contract the retirement of the five DSP cards depends on.
"""

from __future__ import annotations

import hashlib
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from pydub import AudioSegment

from audio_refinery.core.integrity import IntegrityResult, IntegrityStatus
from audio_refinery.core.models import FileResult, FileStatus, StageConfig
from audio_refinery.core.registry import CompletionRegistry

FS = 44100


# ── Fixtures and small builders ───────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _valid_integrity() -> Iterator[None]:
    """Synthetic placeholder bytes are not real audio; pass the pre-flight."""
    fake = IntegrityResult(path=Path("fake.flac"), status=IntegrityStatus.PASS)
    fake.file_size_bytes = 1024
    fake.duration_ms = 5000.0
    fake.sample_rate = 44100
    fake.channels = 2
    with patch(
        "audio_refinery.core.pipeline.validate_file",
        return_value=fake,
    ):
        yield


def _sine(
    freq: float = 440, duration_ms: int = 200, amplitude: float = 0.3
) -> AudioSegment:
    n = int(FS * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    pcm = (amplitude * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    return AudioSegment(pcm.tobytes(), frame_rate=FS, sample_width=2, channels=1)


def _config(**enabled: bool) -> StageConfig:
    stages: dict[str, bool] = {
        "declick": False,
        "trim": False,
        "reduce_noise": False,
        "enhance": False,
        "normalise": False,
    }
    stages.update(enabled)
    return StageConfig(**stages)


def _source(tmp_path: Path, name: str = "track.flac") -> Path:
    path = tmp_path / name
    path.write_bytes(b"ORIGINAL-AUDIO-BYTES")
    return path


def _fingerprint(path: Path) -> tuple[str, int, int]:
    """SHA-256, mtime_ns and size — what a byte-identical file must keep."""
    stat = path.stat()
    return (
        hashlib.sha256(path.read_bytes()).hexdigest(),
        stat.st_mtime_ns,
        stat.st_size,
    )


def _tree_state(root: Path) -> dict[str, tuple[str, int, int]]:
    return {
        str(path.relative_to(root)): _fingerprint(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _declick_result(audio: AudioSegment, damaged: bool) -> SimpleNamespace:
    return SimpleNamespace(
        audio=audio,
        was_modified=damaged,
        clicks_found=3 if damaged else 0,
    )


def _trim_result(audio: AudioSegment, damaged: bool) -> SimpleNamespace:
    if damaged:
        return SimpleNamespace(
            trimmed=audio,
            action="trimmed 2.1s of silence",
            apply_fade=False,
        )
    return SimpleNamespace(trimmed=None, action="No silence detected", apply_fade=False)


def _noise_result(audio: AudioSegment, damaged: bool) -> SimpleNamespace:
    return SimpleNamespace(
        audio=audio,
        was_modified=damaged,
        energy_before_db=-30.0,
        energy_after_db=-42.0 if damaged else -30.0,
    )


_ENABLED_KEY = {"declick": "declick", "trim": "trim", "noise": "reduce_noise"}

_STAGE_PATCH = {
    "declick": "pop_click_remover.core.declicker.declick_audio",
    "trim": "silence_trimmer.core.trimmer.trim_and_fade",
    "noise": "noise_reduction.core.noise_reducer.reduce_noise",
}

_STAGE_RESULT = {
    "declick": _declick_result,
    "trim": _trim_result,
    "noise": _noise_result,
}


@contextmanager
def _pipeline(
    audio: AudioSegment,
    *,
    stage: str | None = None,
    damaged: bool = False,
    measure_value: dict[str, float] | None = None,
) -> Iterator[None]:
    """Patch the pipeline's I/O and one engine stage for a synthetic run."""
    with ExitStack() as stack:
        stack.enter_context(
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={})
        )
        stack.enter_context(patch("audio_refinery.core.pipeline.write_tags_raw"))
        mock_seg = stack.enter_context(
            patch("audio_refinery.core.pipeline.AudioSegment")
        )
        mock_seg.from_file.return_value = audio
        if stage is not None:
            stack.enter_context(
                patch(
                    _STAGE_PATCH[stage],
                    return_value=_STAGE_RESULT[stage](audio, damaged),
                )
            )
        if measure_value is not None:
            stack.enter_context(
                patch(
                    "audio_normalizer.core.loudness.measure",
                    return_value=measure_value,
                )
            )
        yield


def _write_side_effect(
    audio: AudioSegment, tmp_path: Path | str, *args: Any, **kwargs: Any
) -> None:
    """Stand in for the real encode: the staged file gets different bytes."""
    Path(tmp_path).write_bytes(b"PROCESSED-AUDIO-BYTES")


# ── Single pre-write stage: clean vs damaged ─────────────────────────────────


@pytest.mark.parametrize("stage", ["declick", "trim", "noise"])
@pytest.mark.parametrize("damaged", [False, True], ids=["clean", "damaged"])
def test_single_stage_rewrites_only_when_it_changed_audio(
    tmp_path: Path, stage: str, damaged: bool
) -> None:
    from audio_refinery.core.pipeline import process_file

    src = _source(tmp_path)
    before = _fingerprint(src)
    config = _config(**{_ENABLED_KEY[stage]: True})

    with (
        _pipeline(_sine(), stage=stage, damaged=damaged),
        patch("audio_refinery.core.pipeline._write_output") as write,
        patch("audio_refinery.core.pipeline.record_tag_edit_snapshot") as snapshot,
    ):
        if damaged:
            write.side_effect = _write_side_effect
        result = process_file(src, src, config, on_progress=lambda s, m: None)

    if damaged:
        # Counter-case: the flag cannot be stuck on "unchanged".
        assert result.status is FileStatus.DONE
        assert result.was_modified is True
        assert write.call_count == 1
        assert snapshot.call_count == 1
        assert _fingerprint(src) != before
    else:
        assert result.status is FileStatus.SKIPPED
        assert result.was_modified is False
        assert "left untouched" in (result.error or "")
        write.assert_not_called()
        snapshot.assert_not_called()
        assert _fingerprint(src) == before


def test_no_enabled_stage_writes_nothing(tmp_path: Path) -> None:
    from audio_refinery.core.pipeline import process_file

    src = _source(tmp_path)
    before = _fingerprint(src)

    with (
        _pipeline(_sine()),
        patch("audio_refinery.core.pipeline._write_output") as write,
        patch("audio_refinery.core.pipeline.record_tag_edit_snapshot") as snapshot,
    ):
        result = process_file(src, src, _config(), on_progress=lambda s, m: None)

    assert result.status is FileStatus.SKIPPED
    assert "No stages enabled" in (result.error or "")
    write.assert_not_called()
    snapshot.assert_not_called()
    assert _fingerprint(src) == before


# ── Normalise ────────────────────────────────────────────────────────────────


def test_normalise_within_tolerance_leaves_file_untouched(tmp_path: Path) -> None:
    from audio_refinery.core.pipeline import process_file

    src = _source(tmp_path)
    before = _fingerprint(src)

    config = _config(normalise=True)
    # Stated explicitly: since 2.6.0 the shipped target is -14.0 (U-04).
    config.normalise_params.target_lufs = -16.0

    with (
        _pipeline(_sine(), measure_value={"input_i": -16.2}),
        patch("audio_refinery.core.pipeline._run_normalise") as apply_mock,
        patch("audio_refinery.core.pipeline._write_output") as write,
        patch("audio_refinery.core.pipeline.record_tag_edit_snapshot") as snapshot,
    ):
        result = process_file(src, src, config)

    assert result.status is FileStatus.SKIPPED
    assert result.was_modified is False
    assert "no adjustment needed" in result.stages[-1].message
    apply_mock.assert_not_called()
    write.assert_not_called()
    snapshot.assert_not_called()
    assert _fingerprint(src) == before


def test_normalise_only_out_of_tolerance_is_one_ffmpeg_pass(tmp_path: Path) -> None:
    """Loudnorm runs on the source itself: no staging encode, one apply."""
    from audio_refinery.core.pipeline import process_file

    src = _source(tmp_path)
    before = _fingerprint(src)

    def _fake_apply(
        path: str, target: float, data: dict[str, float], **kwargs: Any
    ) -> None:
        Path(path).write_bytes(b"LOUDNORM-IN-PLACE")

    with (
        _pipeline(_sine(), measure_value={"input_i": -23.0}),
        patch(
            "audio_normalizer.core.normalizer.apply", side_effect=_fake_apply
        ) as apply_mock,
        patch("audio_refinery.core.pipeline._write_output") as write,
        patch("audio_refinery.core.pipeline.record_tag_edit_snapshot") as snapshot,
    ):
        result = process_file(src, src, _config(normalise=True))

    assert result.status is FileStatus.DONE
    assert result.was_modified is True
    assert "Adjusted loudness" in result.stages[-1].message
    write.assert_not_called()
    apply_mock.assert_called_once()
    assert apply_mock.call_args.args[0] == str(src)
    assert snapshot.call_count == 1
    # The decoded outcome: the source now holds the normalised bytes.
    assert src.read_bytes() == b"LOUDNORM-IN-PLACE"
    assert _fingerprint(src) != before


def test_normalise_only_real_audio_reaches_target(tmp_path: Path) -> None:
    """Decode the result: one pass, target reached, duration and tags kept.

    The mocked test above proves the call path; this one proves the audio
    outcome on a real FLAC through the real FFmpeg normaliser.
    """
    from audio_normalizer.core.loudness import measure
    from audio_refinery.core.pipeline import process_file
    from audio_suite_shared.tag_helper import read_tags_raw, write_tags_raw

    src = tmp_path / "quiet.flac"
    _sine(duration_ms=2000, amplitude=0.02).export(str(src), format="flac")
    write_tags_raw(str(src), {"TIT2": "Quiet Tone"}, record_snapshot=False)
    duration_before = len(AudioSegment.from_file(str(src)))

    with patch("audio_refinery.core.pipeline._write_output") as write:
        result = process_file(src, src, _config(normalise=True))

    assert result.status is FileStatus.DONE
    assert result.was_modified is True
    write.assert_not_called()

    decoded = AudioSegment.from_file(str(src))
    assert abs(len(decoded) - duration_before) <= 50
    assert decoded.frame_rate == FS
    assert decoded.channels == 1
    measured = measure(str(src), -14.0)
    assert measured is not None
    assert abs(measured["input_i"] - (-14.0)) <= 1.0
    tags = read_tags_raw(str(src))
    assert any("Quiet Tone" in str(value) for value in tags.values())


def test_multi_stage_run_writes_then_normalises_the_temp_file(
    tmp_path: Path,
) -> None:
    """A run with audio to write keeps the write-then-normalise pair."""
    from audio_refinery.core.pipeline import process_file

    src = _source(tmp_path)
    applied_to: list[str] = []

    def _fake_apply(
        path: str, target: float, data: dict[str, float], **kwargs: Any
    ) -> None:
        applied_to.append(path)
        Path(path).write_bytes(b"LOUDNORM-TEMP")

    with (
        _pipeline(
            _sine(),
            stage="declick",
            damaged=True,
            measure_value={"input_i": -23.0},
        ),
        patch("audio_normalizer.core.normalizer.apply", side_effect=_fake_apply),
        patch("audio_refinery.core.pipeline._write_output") as write,
        patch("audio_refinery.core.pipeline.record_tag_edit_snapshot"),
    ):
        write.side_effect = _write_side_effect
        result = process_file(src, src, _config(declick=True, normalise=True))

    assert result.status is FileStatus.DONE
    assert write.call_count == 1
    assert len(applied_to) == 1
    # The normalise pass targets the staged copy, never the source directly.
    assert applied_to[0] != str(src)
    assert Path(applied_to[0]).name.endswith(".flac")
    # os.replace put the normalised temp content in place.
    assert src.read_bytes() == b"LOUDNORM-TEMP"


# ── Dry Run ──────────────────────────────────────────────────────────────────


def test_dry_run_detects_without_writing_anything(tmp_path: Path) -> None:
    from audio_refinery.core.pipeline import process_file

    src = _source(tmp_path)
    before = _tree_state(tmp_path)

    config = StageConfig(
        dry_run=True,
        declick=True,
        trim=True,
        reduce_noise=False,
        enhance=False,
        normalise=True,
    )

    with (
        _pipeline(
            _sine(),
            stage="declick",
            damaged=True,
            measure_value={"input_i": -23.0},
        ),
        patch("audio_refinery.core.pipeline._write_output") as write,
        patch("audio_refinery.core.pipeline.record_tag_edit_snapshot") as snapshot,
    ):
        # Trim needs its own engine result; the helper patches one stage.
        with patch(
            "silence_trimmer.core.trimmer.trim_and_fade",
            return_value=_trim_result(_sine(), damaged=False),
        ):
            result = process_file(src, src, config, on_progress=lambda s, m: None)

    assert result.status is FileStatus.DONE
    assert result.was_modified is False
    messages = {stage.stage: stage.message for stage in result.stages}
    assert "repaired 3 click" in messages["Declick"]
    assert "No silence detected" in messages["Trim"]
    assert messages["Normalise"] == "Would adjust loudness from -23.0 to -14.0 LUFS"
    write.assert_not_called()
    snapshot.assert_not_called()
    # No file changed, and no temp file was left behind.
    assert _tree_state(tmp_path) == before


# ── Completion registry ──────────────────────────────────────────────────────


def _make_slots() -> tuple[list[MagicMock], Any]:
    from queue import Queue

    slot_vars = [MagicMock() for _ in range(2)]
    slot_queue: Queue[int] = Queue()
    for index in range(2):
        slot_queue.put(index)
    return slot_vars, slot_queue


def _run_registry_batch(tmp_path: Path, result: FileResult) -> CompletionRegistry:
    from audio_refinery.core.file_processor import run_pipeline

    registry = CompletionRegistry(tmp_path)
    slot_vars, slot_queue = _make_slots()

    with (
        patch(
            "audio_refinery.core.file_processor.process_file",
            side_effect=lambda **kwargs: result,
        ),
        patch("audio_suite_shared.resource_manager.get_resource_manager"),
        patch("audio_suite_shared.resource_manager.cleanup_expired_resources"),
        patch("audio_suite_shared.resource_manager.track_thread"),
    ):
        run_pipeline(
            source_dir=tmp_path,
            output_dir=tmp_path,
            config=_config(enhance=True),
            registry=registry,
            slot_vars=slot_vars,
            slot_queue=slot_queue,
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: None,
            on_error=lambda msg: None,
        )
    return registry


def test_dry_run_result_is_not_recorded_as_completed(tmp_path: Path) -> None:
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"opaque bytes")
    registry = _run_registry_batch(
        tmp_path,
        FileResult(path=audio, status=FileStatus.DONE, was_modified=False),
    )

    assert registry.is_done(audio, registry.hash_file(audio)) is False
    assert not (tmp_path / "_refinery_completed.log").exists()


def test_real_write_is_recorded_as_completed(tmp_path: Path) -> None:
    """Counter-case: the registry check cannot be stuck at 'never done'."""
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"opaque bytes")
    registry = _run_registry_batch(
        tmp_path,
        FileResult(path=audio, status=FileStatus.DONE, was_modified=True),
    )

    assert registry.is_done(audio, registry.hash_file(audio)) is True


def test_noop_result_is_not_recorded_as_completed(tmp_path: Path) -> None:
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"opaque bytes")
    registry = _run_registry_batch(
        tmp_path,
        FileResult(
            path=audio,
            status=FileStatus.SKIPPED,
            error="No changes needed - file left untouched",
        ),
    )

    assert registry.is_done(audio, registry.hash_file(audio)) is False

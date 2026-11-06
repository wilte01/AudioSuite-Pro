"""The album plan is built once per run, before any worker starts.

Changed in 2.5.0: new file (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E1).

Changed in 2.5.0: an exact copy-mode trim that shares a run with a decoding
stage is refused once, before dispatch (F-E3).

The per-file workers are the wrong place to measure an album: N workers each
measuring the folder is N concatenated decodes and N different answers.  These
locks therefore count the builder's calls and check that every worker received
the same plan object, and they read the plan's configured targets rather than
the pipeline's stage config.
"""

from __future__ import annotations

from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

from audio_normalizer.core.album import AlbumPlan, plan_key
from audio_refinery.core.file_processor import run_pipeline
from audio_refinery.core.models import (
    FileResult,
    FileStatus,
    NormaliseParams,
    StageConfig,
    TrimParams,
)
from audio_refinery.core.registry import CompletionRegistry
from audio_suite_shared.exceptions import AudioProcessingError

NAMES = ("01.flac", "02.flac", "03.flac")


def _config(*, album_mode: bool) -> StageConfig:
    config = StageConfig(declick=False, trim=False, enhance=False, normalise=True)
    config.normalise_params = NormaliseParams(
        target_lufs=-23.0,
        tolerance=0.25,
        true_peak=-1.0,
        album_mode=album_mode,
    )
    return config


def _slots(count: int = 2) -> tuple[list[MagicMock], Queue[int]]:
    slot_vars = [MagicMock() for _ in range(count)]
    slot_queue: Queue[int] = Queue()
    for index in range(count):
        slot_queue.put(index)
    return slot_vars, slot_queue


def _album(files: list[Path]) -> AlbumPlan:
    return AlbumPlan(
        album_lufs=-20.0,
        target_lufs=-23.0,
        true_peak_ceiling=-1.0,
        gains={plan_key(path): -3.0 for path in files},
        limited={plan_key(path): False for path in files},
        album_true_peak=-2.0,
        notes=(),
    )


def _run(
    tmp_path: Path,
    config: StageConfig,
    *,
    builder: Any = None,
) -> tuple[dict[str, Any], MagicMock]:
    """Run one batch over three placeholder files and capture the seams."""
    files: list[Path] = []
    for name in NAMES:
        path = tmp_path / name
        path.write_bytes(b"placeholder audio bytes")
        files.append(path)

    plan = _album(files)
    captured: dict[str, Any] = {
        "plans": [],
        "paths": None,
        "errors": [],
        "completes": [],
    }

    def _default_builder(paths: list[str], **kwargs: Any) -> AlbumPlan:
        captured["paths"] = list(paths)
        captured["kwargs"] = kwargs
        return plan

    def _process(**kwargs: Any) -> FileResult:
        captured["plans"].append(kwargs.get("album_plan"))
        return FileResult(path=kwargs["source_path"], status=FileStatus.SKIPPED)

    registry = CompletionRegistry(tmp_path)
    slot_vars, slot_queue = _slots()

    with (
        patch(
            "audio_refinery.core.file_processor.build_album_plan",
            side_effect=builder or _default_builder,
        ) as build_mock,
        patch("audio_refinery.core.file_processor.process_file", side_effect=_process),
        patch("audio_suite_shared.resource_manager.get_resource_manager"),
        patch("audio_suite_shared.resource_manager.cleanup_expired_resources"),
        patch("audio_suite_shared.resource_manager.track_thread"),
    ):
        run_pipeline(
            source_dir=tmp_path,
            output_dir=tmp_path,
            config=config,
            registry=registry,
            slot_vars=slot_vars,
            slot_queue=slot_queue,
            on_progress=lambda **kwargs: None,
            on_complete=lambda **kwargs: captured["completes"].append(kwargs),
            on_error=lambda message: captured["errors"].append(message),
        )
    return captured, build_mock


def test_album_mode_builds_one_plan_for_the_whole_folder(tmp_path: Path) -> None:
    captured, build_mock = _run(tmp_path, _config(album_mode=True))

    assert build_mock.call_count == 1
    assert sorted(Path(path).name for path in captured["paths"]) == sorted(NAMES)
    assert len(captured["plans"]) == len(NAMES)
    assert all(plan is captured["plans"][0] for plan in captured["plans"])
    assert captured["plans"][0] is not None


def test_the_plan_uses_the_configured_delivery_targets(tmp_path: Path) -> None:
    captured, _ = _run(tmp_path, _config(album_mode=True))

    assert captured["kwargs"] == {
        "target_lufs": -23.0,
        "true_peak_ceiling": -1.0,
        "tolerance": 0.25,
    }


def test_without_album_mode_no_plan_is_built(tmp_path: Path) -> None:
    captured, build_mock = _run(tmp_path, _config(album_mode=False))

    build_mock.assert_not_called()
    assert captured["plans"] == [None, None, None]


def _copy_config() -> StageConfig:
    config = StageConfig(declick=False, trim=True, enhance=False, normalise=False)
    config.trim_params = TrimParams(mode="exact", end_ms=500, copy_mode=True)
    return config


def test_copy_mode_alone_dispatches_every_file(tmp_path: Path) -> None:
    captured, _ = _run(tmp_path, _copy_config())

    assert captured["errors"] == []
    assert captured["plans"] == [None, None, None]


def test_copy_mode_beside_a_decoding_stage_stops_the_run(tmp_path: Path) -> None:
    config = _copy_config()
    config.declick = True

    captured, _ = _run(tmp_path, config)

    assert captured["errors"], "the run must refuse copy mode, not process files"
    assert "Declick" in captured["errors"][0]
    assert captured["plans"] == []
    assert captured["completes"] == []


def test_a_plan_failure_stops_the_run_before_a_file_is_processed(
    tmp_path: Path,
) -> None:
    def _failing_builder(paths: list[str], **kwargs: Any) -> AlbumPlan:
        raise AudioProcessingError("the folder could not be measured")

    captured, _ = _run(tmp_path, _config(album_mode=True), builder=_failing_builder)

    assert captured["errors"], "a failed album measurement must report an error"
    assert captured["plans"] == []
    assert captured["completes"] == []

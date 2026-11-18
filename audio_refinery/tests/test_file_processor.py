"""The album plan is built once per run, before any worker starts.

Changed in 2.5.0: new file (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E1).

Changed in 2.5.0: an exact copy-mode trim that shares a run with a decoding
stage is refused once, before dispatch (F-E3).

The per-file workers are the wrong place to measure an album: N workers each
measuring the folder is N concatenated decodes and N different answers.  These
locks therefore count the builder's calls and check that every worker received
the same plan object, and they read the plan's configured targets rather than
the pipeline's stage config.
Changed in 2.7.0: the run writes the album table and records the caveat (F-S5).
Changed in 2.9.0: the run writes the Best Audio decisions table - one row
per file and stage, only when Auto was requested, and including the files
the run skipped because they print no stage lines.
"""

from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

from audio_normalizer.core.album import AlbumPlan, AlbumTrack, plan_key
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
from audio_suite_shared.run_outcome import clear_outcome, read_outcome

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
        tracks=tuple(
            AlbumTrack(
                file=path.name,
                track_lufs=-20.0,
                track_tp=-4.0,
                applied_gain_db=-3.0,
                limited=False,
                deviation_lu=0.0,
            )
            for path in files
        ),
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


def test_the_run_writes_the_album_table_beside_its_report(tmp_path: Path) -> None:
    """The per-track table is a file a user can open, not a log line (F-S5)."""
    clear_outcome("audio_refinery")

    _run(tmp_path, _config(album_mode=True))

    written = tmp_path / "refinery_album.csv"
    assert written.exists()
    with written.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["file"] for row in rows] == list(NAMES)
    assert {row["album_lufs"] for row in rows} == {"-20.00"}
    # Every track sits on the album's own level, so there is nothing to report.
    assert read_outcome("audio_refinery") == ""


def test_the_results_table_is_published_with_the_run(tmp_path: Path) -> None:
    """The GUI's album table is fed the plan, not a re-read of the CSV (F-S6)."""
    captured, _ = _run(tmp_path, _config(album_mode=True))

    payload = captured["completes"][-1]
    assert [row["file"] for row in payload["album_rows"]] == list(NAMES)
    assert payload["album_rows"][0] == {
        "file": "01.flac",
        "album_lufs": "-20.00",
        "track_lufs": "-20.00",
        "track_tp": "-4.00",
        "applied_gain_db": "-3.00",
        "limited": "no",
        "deviation_lu": "0.00",
    }


def test_a_per_file_run_publishes_no_album_rows(tmp_path: Path) -> None:
    """A run that planned no album has nothing to tabulate, and says so."""
    captured, _ = _run(tmp_path, _config(album_mode=False))

    assert captured["completes"][-1]["album_rows"] == ()


def test_a_track_outside_the_window_is_named_in_the_run_outcome(
    tmp_path: Path,
) -> None:
    """An outlier reaches the batch report through the shared outcome channel."""
    clear_outcome("audio_refinery")

    def _outlier(paths: list[str], **_kwargs: Any) -> AlbumPlan:
        plan = _album([Path(path) for path in paths])
        return replace(
            plan,
            tracks=tuple(
                replace(row, deviation_lu=4.0 if row.file == "02.flac" else 0.0)
                for row in plan.tracks
            ),
        )

    _run(tmp_path, _config(album_mode=True), builder=_outlier)

    assert read_outcome("audio_refinery") == (
        "1 of 3 tracks sits more than 3.0 LU from the album target: 02"
    )


# ── Best Audio decisions table (2.9.0) ───────────────────────────────────────


def _run_with_result(
    tmp_path: Path, config: StageConfig, result_for: "Any"
) -> dict[str, Any]:
    """Run one batch whose worker returns whatever *result_for* builds."""
    for name in NAMES:
        (tmp_path / name).write_bytes(b"placeholder audio bytes")

    captured: dict[str, Any] = {"completes": [], "errors": []}

    def _process(**kwargs: Any) -> FileResult:
        return result_for(kwargs["source_path"])

    registry = CompletionRegistry(tmp_path)
    slot_vars, slot_queue = _slots()

    with (
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
    return captured


def _best_audio_plan(tmp_path: Path, config: StageConfig):
    """A real plan from a real segment, so the rows are the run's own."""
    import numpy as np

    from audio_refinery.core import best_audio

    n = int(44_100 * 1.0)
    samples = (0.15 * np.sin(2 * np.pi * 440 * np.arange(n) / 44_100) * 32767).astype(
        np.int16
    )
    samples[10_000] = 30_000
    from audio_suite_shared.audio_conversion import numpy_to_segment

    segment = numpy_to_segment(
        samples.astype(np.float32) / 32767.0,
        44_100,
        sample_width=2,
        num_channels=1,
    )
    return best_audio.decide(segment, tmp_path / NAMES[0], config)


def test_a_best_audio_run_writes_the_decisions_table(tmp_path: Path) -> None:
    """The table is the record for every file, read back from disk."""
    config = StageConfig(declick=True, trim=False, enhance=False, normalise=False)
    config.auto_stages = ("declick",)
    plan = _best_audio_plan(tmp_path, config)

    def _result(path: Path) -> FileResult:
        return FileResult(path=path, status=FileStatus.DONE, best_audio=plan)

    _run_with_result(tmp_path, config, _result)

    written = tmp_path / "refinery_decisions.csv"
    assert written.exists()
    with written.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    from audio_refinery.core.best_audio import CSV_HEADER

    assert list(rows[0]) == list(CSV_HEADER)
    assert [row["file"] for row in rows] == list(NAMES)
    assert {row["stage"] for row in rows} == {"declick"}
    assert {row["decision"] for row in rows} == {"active"}


def test_a_run_without_auto_writes_no_decisions_table(tmp_path: Path) -> None:
    config = StageConfig(declick=True, trim=False, enhance=False, normalise=False)

    def _result(path: Path) -> FileResult:
        return FileResult(path=path, status=FileStatus.DONE)

    _run_with_result(tmp_path, config, _result)

    assert not (tmp_path / "refinery_decisions.csv").exists()


def test_a_skipped_file_still_reaches_the_table(tmp_path: Path) -> None:
    """A skipped file prints no stage lines, so the table is its only record."""
    config = StageConfig(declick=True, trim=False, enhance=False, normalise=False)
    config.auto_stages = ("declick",)
    plan = _best_audio_plan(tmp_path, config)

    def _result(path: Path) -> FileResult:
        return FileResult(
            path=path, status=FileStatus.SKIPPED, error="No clicks", best_audio=plan
        )

    _run_with_result(tmp_path, config, _result)

    with (tmp_path / "refinery_decisions.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert {row["status"] for row in rows} == {"Skipped"}

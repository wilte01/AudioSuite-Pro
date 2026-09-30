"""Immutability locks for the dataclasses frozen by iteration-7 C1.

Each parametrised entry constructs the class with its minimal field set and
asserts that assigning to an attribute raises ``FrozenInstanceError``. The
construction doubles as the non-vacuity proof that the field set still
matches the class definition.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

import audio_refinery.utils.cli_args as refinery_cli_args
from audio_enhancer.utils.cli_args import CliArgs
from audio_refinery.core.models import StageMetrics, StageResult
from audio_suite_shared.error_recovery import RetryConfig
from master_driver.batch_orchestrator import BatchProgress, BatchReport
from music_format_converter.core.formats import ScanResult
from tag_editor.core.processor import TagRow

_FROZEN_CASES: list[tuple[type[Any], dict[str, Any], str]] = [
    (ScanResult, {"ok": True}, "file_count"),
    (
        BatchProgress,
        {
            "total_steps": 1,
            "completed_steps": 0,
            "current_step": None,
            "current_progress": 0.0,
            "elapsed": timedelta(0),
            "estimated_remaining": timedelta(0),
            "failed_steps": [],
            "running_steps": [],
            "pending_steps": [],
        },
        "completed_steps",
    ),
    (
        BatchReport,
        {
            "total": 1,
            "completed": 1,
            "failed": 0,
            "skipped": 0,
            "steps": [],
            "total_elapsed": timedelta(0),
        },
        "completed",
    ),
    (StageMetrics, {"stage": "Declick"}, "processing_time"),
    (StageResult, {"stage": "Declick"}, "message"),
    (RetryConfig, {}, "max_retries"),
    (TagRow, {"path": Path("x.mp3"), "values": {}}, "error"),
    (CliArgs, {}, "source"),
    (refinery_cli_args.RefineryArgs, {}, "source"),
]

_IDS: list[str] = [cls.__name__ for cls, _kwargs, _attr in _FROZEN_CASES]


@pytest.mark.parametrize(("cls", "kwargs", "attr"), _FROZEN_CASES, ids=_IDS)
def test_newly_frozen_dataclass_rejects_assignment(
    cls: type[Any], kwargs: dict[str, Any], attr: str
) -> None:
    """Assigning to a frozen record raises FrozenInstanceError."""
    instance = cls(**kwargs)

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, attr, None)


def test_frozen_case_list_covers_all_newly_frozen_classes() -> None:
    """The parametrised list is the C1 freeze list — never silently shrunk."""
    assert len(_FROZEN_CASES) == 9
    assert _IDS == [
        "ScanResult",
        "BatchProgress",
        "BatchReport",
        "StageMetrics",
        "StageResult",
        "RetryConfig",
        "TagRow",
        "CliArgs",
        "RefineryArgs",
    ]

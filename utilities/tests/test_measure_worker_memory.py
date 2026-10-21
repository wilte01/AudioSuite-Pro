"""Tests for ``utilities/measure_worker_memory.py`` (PLAN D100, S5-6).

The script's whole value is that its numbers are real, so the tests check the
two ways a memory harness lies:

* it reports 0 MB because ``GetProcessMemoryInfo`` was called without
  ``argtypes``/``restype`` (the documented trap), or
* it measures a batch that is not the batch the app runs.

``test_peak_rss_responds_to_an_allocation`` proves the probe reacts to memory
the process actually holds; ``test_main_measures_every_configured_worker_count``
drives the real entry point end to end on a tiny corpus.

Changed in 1.4.1: new suite for the D100 worker-memory measurement.
"""

from __future__ import annotations

import json
import sys
import wave
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script() -> ModuleType:
    """Import ``utilities/measure_worker_memory.py`` by path (not a package).

    The module is registered in ``sys.modules`` before it executes: its frozen
    dataclass resolves its own annotations through ``cls.__module__``, and on
    3.14 an unregistered module makes that lookup raise ``AttributeError``
    during class creation.
    """
    spec = spec_from_file_location(
        "measure_worker_memory", REPO_ROOT / "utilities" / "measure_worker_memory.py"
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


class TestPeakRss:
    """The probe reports this process's real peak, not a zero."""

    def test_peak_rss_is_positive(self) -> None:
        """A probe that returns 0 would make every measurement meaningless."""
        peak = script.peak_rss_bytes()
        assert peak > 1_048_576, f"peak RSS reported as {peak} bytes"

    def test_peak_rss_responds_to_an_allocation(self) -> None:
        """Holding 64 MB must move the reported peak by at least 32 MB.

        ``bytes(64 << 20)`` is touched after allocation so the pages are
        resident; without the touch a lazy allocator could report nothing and
        the assertion below would pass on a broken probe.
        """
        before = script.peak_rss_bytes()
        block = bytearray(64 << 20)
        for index in range(0, len(block), 4096):
            block[index] = 1
        after = script.peak_rss_bytes()
        assert after >= before + (32 << 20), (
            f"peak moved only {(after - before) / 1_048_576:.1f} MB while holding "
            "64 MB - the probe is not reading the working set"
        )
        del block


class TestCorpus:
    """The corpus builder writes the batch the app analyses."""

    def test_builds_the_requested_files_at_the_requested_length(
        self, tmp_path: Path
    ) -> None:
        """Every file exists, is mono 16-bit at 44.1 kHz, and has the length."""
        paths = script.build_corpus(tmp_path, files=2, seconds=2)
        assert [path.name for path in paths] == ["measure_00.wav", "measure_01.wav"]
        assert sorted(p.name for p in tmp_path.glob("*.wav")) == [
            "measure_00.wav",
            "measure_01.wav",
        ]
        for path in paths:
            with wave.open(str(path), "rb") as handle:
                assert handle.getnchannels() == 1
                assert handle.getsampwidth() == 2
                assert handle.getframerate() == 44_100
                assert handle.getnframes() == 44_100 * 2


class TestPerWorkerCost:
    """The marginal per-worker figure is derived, never hard-coded."""

    def test_marginal_cost_between_two_thread_runs(self) -> None:
        """(wide - narrow) / (wide_workers - narrow_workers)."""
        narrow = script.Measurement(
            mode="threads",
            workers=4,
            files=8,
            seconds=60,
            analysis_seconds=30,
            baseline_mb=22.0,
            peak_mb=600.0,
            elapsed_s=5.0,
            exit_status=0,
        )
        wide = script.Measurement(
            mode="threads",
            workers=8,
            files=8,
            seconds=60,
            analysis_seconds=30,
            baseline_mb=22.0,
            peak_mb=800.0,
            elapsed_s=6.0,
            exit_status=0,
        )
        assert script._per_worker([narrow, wide]) == pytest.approx(50.0)

    def test_a_single_thread_run_has_no_marginal_cost(self) -> None:
        """One configuration cannot imply a per-worker slope."""
        only = script.Measurement(
            mode="threads",
            workers=4,
            files=1,
            seconds=2,
            analysis_seconds=1,
            baseline_mb=20.0,
            peak_mb=100.0,
            elapsed_s=1.0,
            exit_status=0,
        )
        assert script._per_worker([only]) == 0.0


class TestCli:
    """The script reports the batch it actually ran, through both exits."""

    def test_main_measures_every_configured_worker_count(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A real run reports one row per worker count plus the process path."""
        status = script.main(
            [
                "--files",
                "1",
                "--seconds",
                "2",
                "--analysis-seconds",
                "1",
                "--workers",
                "1,2",
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert status == 0, payload
        assert "python" in payload["host"], payload["host"]
        modes = [(row["mode"], row["workers"]) for row in payload["measurements"]]
        assert modes == [("threads", 1), ("threads", 2), ("processes", 2)]
        for row in payload["measurements"]:
            assert row["peak_mb"] > 0, row
            assert row["exit_status"] == 0, row
            assert row["analysis_seconds"] == 1
        assert payload["within_budget"] is True

    def test_an_over_budget_peak_exits_one(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The budget check is a real exit status, not a printed word."""
        status = script.main(
            [
                "--files",
                "1",
                "--seconds",
                "2",
                "--analysis-seconds",
                "1",
                "--workers",
                "1",
                "--budget-mb",
                "0.001",
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert status == 1
        assert payload["within_budget"] is False

    def test_bad_worker_counts_are_usage_errors(self) -> None:
        """A malformed list is exit 2, not a traceback."""
        assert script.main(["--workers", "four"]) == 2
        assert script.main(["--workers", "0"]) == 2
        assert script.main(["--files", "0"]) == 2


def test_the_script_is_not_imported_as_a_package() -> None:
    """Guard the loader: a namespace import would pass silently with no tests."""
    assert script.__file__ is not None
    assert script.__file__.endswith("measure_worker_memory.py")
    assert sys.version_info >= (3, 11)

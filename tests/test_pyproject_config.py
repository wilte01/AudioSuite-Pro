"""Tests for the ``integration``/``hardware`` marker contract (plan D1).

The audit found the markers registered but never acted upon: 30 hardware tests
and 273 integration tests ran in every default run, so a reader could conclude
CI skips hardware tests when it does not. D1 pins the contract at three
layers, so it cannot silently rot back to "everything runs":

1. *Configuration lock* — ``pyproject.toml``'s ``addopts`` deselects
   ``hardware`` by default and the marker descriptions state the contracts.
2. *Full-tree collection contract* — a subprocess runs the real pytest
   configuration: the default run deselects exactly the hardware set, the
   documented opt-in ``pytest -m hardware`` restores it, and every
   integration test is collected by the default run.
3. *Behaviour lock* — against a byte-copy of the real root ``conftest.py``
   (the ``pytester`` technique used by ``tests/test_conftest.py``): the
   missing-ffmpeg auto-skip fires per integration test with a reason naming
   the missing executables, and a plain test beside it still runs.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_conftest import _load_root_conftest, _outcome, _outcome_line

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"

try:
    import tomllib

    _HAS_TOMLLIB = True
except ModuleNotFoundError:
    # Python 3.10 (a CI leg) has no tomllib. The config lock below is enforced
    # by the 3.12 legs; the 3.10 skip names its constraint instead of hiding.
    _HAS_TOMLLIB = False

#: Mirrors the real ``[tool.pytest.ini_options]`` markers and addopts in the
#: pytester sandbox: ``--strict-markers`` accepts the three real markers and
#: the addopts deselection is the one D1 installs.
PYTEST_INI = """\
[pytest]
addopts = --strict-markers -ra -m "not hardware"
markers =
    integration: requires ffmpeg and real audio files
    hardware: requires real drive hardware (deselected by default; opt in: -m hardware)
    gui: requires a graphical display
"""

#: A stand-in exercising every side of the contract: the integration-marked
#: test (conditional on ffmpeg), the hardware-marked test (conditional on the
#: addopts/opt-in) and an unmarked control that must always run.
SAMPLE_MARKER_TESTS = """\
import pytest


@pytest.mark.integration
def test_marked_integration():
    assert True


@pytest.mark.hardware
def test_marked_hardware():
    assert True


def test_plain():
    assert True
"""

#: Replaces the A5 declaration module before any probe runs, simulating a
#: host with no ffmpeg and no ffprobe. Applied at plugin import time —
#: before the copied conftest's hooks run — so the probe's function-local
#: import resolves against the replaced module, per the AGENTS.md patch rule.
FAKE_MISSING_PLUGIN = '''\
"""Simulate a host where ffmpeg and ffprobe are absent."""
import audio_suite_shared.system_requirements as declaration

from audio_suite_shared.system_requirements import SystemRequirement

declaration.find_missing_requirements = lambda *_args, **_kwargs: [
    SystemRequirement("fake ffmpeg", "fake purpose", ("fake install hint",)),
    SystemRequirement("fake ffprobe", "fake purpose", ("fake install hint",)),
]
'''


# ---------------------------------------------------------------------------
# Layer 1 — configuration lock
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _HAS_TOMLLIB,
    reason="tomllib requires Python 3.11+; the 3.12 CI legs enforce this lock",
)
class TestConfigLock:
    """The wiring must be in the config file itself, not in ritual."""

    @staticmethod
    def _marker_description(name: str) -> str:
        pyproject = tomllib.load(open(PYPROJECT, "rb"))
        tool = pyproject["tool"]
        assert isinstance(tool, dict)
        pytest_options = tool["pytest"]
        assert isinstance(pytest_options, dict)
        ini_options = pytest_options["ini_options"]
        markers = ini_options.get("markers")
        assert isinstance(markers, list)
        for entry in markers:
            assert isinstance(entry, str)
            if entry.startswith(f"{name}:"):
                return entry[len(name) + 1 :].strip()
        raise AssertionError(f"marker {name!r} missing from pyproject.toml")

    @staticmethod
    def _addopts() -> str:
        pyproject = tomllib.load(open(PYPROJECT, "rb"))
        tool = pyproject["tool"]
        assert isinstance(tool, dict)
        pytest_options = tool["pytest"]
        assert isinstance(pytest_options, dict)
        addopts = pytest_options["ini_options"].get("addopts")
        assert isinstance(addopts, str)
        return addopts

    def test_addopts_deselects_hardware_by_default(self) -> None:
        addopts = self._addopts()
        assert ' -m "not hardware"' in addopts
        assert "--strict-markers" in addopts

    def test_hardware_marker_states_the_opt_in(self) -> None:
        description = self._marker_description("hardware")
        assert "pytest -m hardware" in description
        assert "never run in CI" in description

    def test_integration_marker_states_the_presence_contract(self) -> None:
        description = self._marker_description("integration")
        assert "ffmpeg" in description and "ffprobe" in description
        assert "auto-skips" in description
        assert "naming the missing executable" in description

    def test_the_conftest_probe_defaults_to_the_real_declaration(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The conftest and the startup preflight must read one declaration.

        Loaded as a standalone module and compared against a plain
        ``shutil.which`` replay of the declared order, so the two mechanisms
        cannot drift apart (the same anti-drift invariant A5 gave the guides).
        """
        root_conftest = _load_root_conftest()
        monkeypatch.setattr(root_conftest, "_missing_executables", None)
        missing = root_conftest.probe_missing_executables()
        assert isinstance(missing, list)
        assert missing == [
            name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None
        ]


# ---------------------------------------------------------------------------
# Layer 2 — full-tree collection contract (real config via subprocess)
# ---------------------------------------------------------------------------


def _collect_tree(*extra_args: str) -> tuple[list[str], str]:
    """Collect the whole real tree through the real pyproject config.

    Args:
        extra_args: Extra pytest arguments, e.g. ``("-m", "hardware")``.

    Returns:
        (collected node-ids, raw stdout). The pytest summary line
        ("N/total tests collected (M deselected)") is asserted verbatim by
        the callers — that is the "the summary line says so" evidence.
    """
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-cov",
            "-p",
            "no:cacheprovider",
            *extra_args,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        check=False,
        env=environment,
    )
    assert result.returncode == 0, (
        f"collect-only subprocess failed ({result.returncode}):\n"
        f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}"
    )
    collected_ids = [
        line.strip() for line in result.stdout.splitlines() if "::" in line
    ]
    return collected_ids, result.stdout


def _summary_numbers(stdout: str) -> dict[str, int]:
    match = re.search(r"(\d+)/(\d+) tests collected \((\d+) deselected\)", stdout)
    assert match is not None, f"no collection summary found in:\n{stdout[-1500:]}"
    collected, total, deselected = (int(part) for part in match.groups())
    return {"collected": collected, "total": total, "deselected": deselected}


@pytest.fixture(scope="module")
def tree_views() -> dict[str, dict[str, object]]:
    """Collect the three views of the real tree once per module.

    Three full-tree subprocess collections are the honest evidence; a
    module-scoped fixture caches both node-ids and raw stdout so the expense
    is paid once and every assertion works on the same tree state.
    """
    views: dict[str, dict[str, object]] = {}
    for key, extra in (
        ("default", ()),
        ("hardware", ("-m", "hardware")),
        ("integration", ("-m", "integration")),
    ):
        ids, stdout = _collect_tree(*extra)
        views[key] = {"ids": ids, "stdout": stdout}
    return views


class TestFullTreeContract:
    """The default, opt-in and integration views must agree.

    The deselected count is compared *between the runs* rather than
    hard-coded, so adding or removing a genuine hardware test keeps this
    lock intact while silently un-filtering the default run fails it.
    """

    def test_the_default_run_deselects_exactly_the_hardware_set(
        self, tree_views: dict[str, dict[str, object]]
    ) -> None:
        default_stdout = tree_views["default"]["stdout"]
        assert isinstance(default_stdout, str)
        summary = _summary_numbers(default_stdout)
        hardware_ids = tree_views["hardware"]["ids"]
        assert isinstance(hardware_ids, list)

        assert summary["collected"] + summary["deselected"] == summary["total"]
        assert summary["deselected"] == len(hardware_ids), (
            "the default deselect set and the hardware opt-in set must be the same size"
        )
        assert all(node.startswith("cd_ripper/tests/") for node in hardware_ids), (
            "hardware tests live in the CD-ripper suite only"
        )

    def test_the_hardware_set_never_runs_in_the_default_session(
        self, tree_views: dict[str, dict[str, object]]
    ) -> None:
        default_ids = tree_views["default"]["ids"]
        hardware_ids = tree_views["hardware"]["ids"]
        assert isinstance(default_ids, list) and isinstance(hardware_ids, list)
        overlap = set(default_ids) & set(hardware_ids)
        assert not overlap, (
            "hardware tests must be deselected by default; "
            f"{len(overlap)} were not: {sorted(overlap)[:5]}"
        )

    def test_integration_tests_run_in_the_default_session(
        self, tree_views: dict[str, dict[str, object]]
    ) -> None:
        default_ids = tree_views["default"]["ids"]
        integration_ids = tree_views["integration"]["ids"]
        assert isinstance(default_ids, list) and isinstance(integration_ids, list)
        assert integration_ids, "the integration suite collected nothing"
        missing = set(integration_ids) - set(default_ids)
        assert not missing, (
            f"every integration test must be inside the default selection; "
            f"{len(missing)} were not: {sorted(missing)[:5]}"
        )
        assert len(integration_ids) >= 250, (
            "the integration set is expected to be the audit's 273-test order "
            f"of magnitude, got {len(integration_ids)}"
        )


# ---------------------------------------------------------------------------
# Layer 3 — behaviour lock (pytester, copied real conftest)
# ---------------------------------------------------------------------------


def _install_pytester_sandbox(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Copy the real conftest and the marker contract into the sandbox."""
    shutil.copyfile(REPO_ROOT / "conftest.py", pytester.path / "conftest.py")
    (pytester.path / "pytest.ini").write_text(PYTEST_INI, encoding="utf-8")
    (pytester.path / "test_sample.py").write_text(SAMPLE_MARKER_TESTS, encoding="utf-8")
    (pytester.path / "fake_missing.py").write_text(
        FAKE_MISSING_PLUGIN, encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(pytester.path))
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")


class TestIntegrationAutoSkipBehaviour:
    """End-to-end against the real skip logic, both presence states."""

    def test_a_missing_ffmpeg_skips_only_the_integration_test(
        self,
        pytester: pytest.Pytester,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _install_pytester_sandbox(pytester, monkeypatch)
        outcomes = pytester.runpytest_subprocess(
            "-p", "fake_missing", "-p", "no:cacheprovider", "-v"
        )
        assert outcomes.ret == 0
        outcomes.assert_outcomes(passed=1, skipped=1)
        skipped_groups = [
            line
            for line in outcomes.stdout.lines
            if line.startswith("SKIPPED") and "[" in line
        ]
        assert skipped_groups
        for group in skipped_groups:
            assert "fake ffmpeg, fake ffprobe not found on PATH" in group

    def test_an_ffmpeg_present_host_runs_the_integration_test(
        self,
        pytester: pytest.Pytester,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Honours the *live* presence state, whichever it is.

        On this host (ffmpeg + ffprobe installed) the integration test runs;
        on a host missing them, the same assertion holds inverted — the
        sandbox must skip the integration test with a reason naming the
        missing executables, which is what CI without the system packages
        gets (that skip must be attributable, never a blanket).
        """
        _install_pytester_sandbox(pytester, monkeypatch)
        root_conftest = _load_root_conftest()
        outcomes = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-v")

        if root_conftest.probe_missing_executables():
            line = _outcome_line(outcomes, "test_marked_integration")
            assert _outcome(line) == "SKIPPED"
        else:
            outcomes.assert_outcomes(passed=2, skipped=0)
            output = outcomes.stdout.str()
            assert "test_marked_integration PASSED" in output

    def test_the_documented_opt_in_runs_a_hardware_test(
        self,
        pytester: pytest.Pytester,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``pytest -m hardware`` overrides the addopts deselection.

        This is the acceptance's opt-in path: the CLI flag wins over the
        default ``-m "not hardware"``, and the (mocked-hardware) test runs.
        """
        _install_pytester_sandbox(pytester, monkeypatch)
        outcomes = pytester.runpytest_subprocess(
            "-p", "no:cacheprovider", "-m", "hardware", "-v"
        )
        assert outcomes.ret == 0
        outcomes.assert_outcomes(passed=1)
        line = _outcome_line(outcomes, "test_marked_hardware")
        assert _outcome(line) == "PASSED"

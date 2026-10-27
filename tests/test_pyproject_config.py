"""Tests for the ``integration``/``hardware`` marker contract (plan D1).

Changed in 1.0.1: reverted LICENSE to the version at d362948 and updated
_GPL3_SHA256 to match (the refetched version had unwanted formatting changes).

The audit found the markers registered but never acted upon: 30 hardware tests
and 273 integration tests ran in every default run, so a reader could conclude
CI skips hardware tests when it does not. D1 pins the contract at three
layers, so it cannot silently rot back to "everything runs":

1. *Configuration lock* — ``pyproject.toml``'s ``addopts`` deselects
   ``hardware`` (and, since 2.0.0, ``real_ml``; since 2.1.0, ``worker_memory``)
   by default and the marker descriptions state the contracts.
2. *Full-tree collection contract* — a subprocess runs the real pytest
   configuration: the default run deselects exactly the opt-in sets
   (``hardware``, ``real_ml`` and ``worker_memory``), each documented opt-in
   ``pytest -m <marker>`` restores its own set, and every integration test is
   collected by the default run.
3. *Behaviour lock* — against a byte-copy of the real root ``conftest.py``
   (the ``pytester`` technique used by ``tests/test_conftest.py``): the
   missing-ffmpeg auto-skip fires per integration test with a reason naming
   the missing executables, and a plain test beside it still runs.

Changed in 2.0.0: the configuration lock reads the ``-m`` expression and
asserts both opt-in markers are deselected (``real_ml`` joins ``hardware``,
PLAN D115) instead of pinning the old whole-string form.  The full-tree
contract gains a ``real_ml`` view for the same reason: the default run now
deselects the union of the two opt-in sets, and the overlap check is
parametrised over both markers.

Changed in 2.1.0: ``worker_memory`` joins the opt-in sets (the worker-memory
harness's real batches), so the collection contract gains its view and the
overlap check covers three markers.  The four collections now run in a single
interpreter (``tests/_collect_views.py``) instead of four whole-tree
subprocesses: the views and their assertions are the same evidence, but the
interpreter startup and test-module imports are paid once (~35 s → ~19 s).

Changed in 2.1.1: the licence lock hashes the licence's *text*, not the bytes
one checkout happens to hold. ``_GPL3_SHA256`` was the digest of a CRLF working
copy while the repository stores LF, so the same unedited licence passed on a
host with ``core.autocrlf=true`` and failed everywhere else - every Linux CI
leg - with the message reserved for a corrupted file. Line endings are now
normalised before hashing, and a bare CR, which no conversion produces, still
fails.

Changed in 2.1.6: the three nested pytest runs are given a deadline. They used
``runpytest_subprocess``'s default ``timeout=None``, so the first 3.14 CI leg
sat at 6% for forty minutes on the first of them and had to be cancelled, with
no output to say why. A wedged inner run now fails this test and reports the
inner stdout/stderr instead of hanging the job.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import tomllib

from tests.test_conftest import _load_root_conftest, _outcome, _outcome_line

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: Every nested pytest run gets a deadline. ``runpytest_subprocess`` defaults to
#: ``timeout=None``, so a wedged inner run hung the whole leg with no output
#: until GitHub's six-hour cap - which is what the first 3.14 run did, at the
#: first of these three calls. A timeout fails the test with the inner output
#: instead, which is the only way to see what wedged it.
_SUBPROCESS_TIMEOUT_SECONDS = 600

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


class TestCoverageExclusionLock:
    """Plan D2: no syntax-pattern exclusion may hide arbitrary error handling.

    The former ``except ImportError`` and ``raise AudioMissingDependencyError``
    exclusions hid every *real* error handler on those patterns tree-wide, so
    an untested error path was permanently invisible. Legitimate guards now
    carry a per-line ``pragma: no cover`` with a reason; this lock stops the
    broad patterns from quietly returning (and no ``fail_under`` move absorbing
    the newly-visible lines — decision D3 holds 75).
    """

    @staticmethod
    def _coverage_field(name: str) -> object:
        with PYPROJECT.open("rb") as fh:
            pyproject = tomllib.load(fh)
        tool = pyproject["tool"]
        assert isinstance(tool, dict)
        coverage_config = tool["coverage"]
        assert isinstance(coverage_config, dict)
        report = coverage_config["report"]
        assert isinstance(report, dict)
        return report.get(name)

    def test_exclusions_contain_no_broad_error_pattern(self) -> None:
        exclude_lines = self._coverage_field("exclude_lines")
        assert isinstance(exclude_lines, list)
        assert "except ImportError" not in exclude_lines
        assert "raise AudioMissingDependencyError" not in exclude_lines
        assert not any(
            isinstance(entry, str) and "except ImportError" in entry
            for entry in exclude_lines
        )

    def test_the_universal_exclusions_are_untouched(self) -> None:
        exclude_lines = self._coverage_field("exclude_lines")
        assert isinstance(exclude_lines, list)
        assert "pragma: no cover" in exclude_lines
        assert "if TYPE_CHECKING:" in exclude_lines
        assert "@abstractmethod" in exclude_lines
        assert "raise NotImplementedError" in exclude_lines
        assert 'if __name__ == "__main__":' in exclude_lines

    def test_the_gate_holds_seventy_five(self) -> None:
        fail_under = self._coverage_field("fail_under")
        assert fail_under == 75, (
            "decision D3 holds fail_under at 75; lowering it would "
            "re-institutionalise the audit's finding 17"
        )


class TestConfigLock:
    """The wiring must be in the config file itself, not in ritual."""

    @staticmethod
    def _marker_description(name: str) -> str:
        with PYPROJECT.open("rb") as fh:
            pyproject = tomllib.load(fh)
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
        with PYPROJECT.open("rb") as fh:
            pyproject = tomllib.load(fh)
        tool = pyproject["tool"]
        assert isinstance(tool, dict)
        pytest_options = tool["pytest"]
        assert isinstance(pytest_options, dict)
        addopts = pytest_options["ini_options"].get("addopts")
        assert isinstance(addopts, str)
        return addopts

    def test_addopts_deselects_the_opt_in_markers_by_default(self) -> None:
        """Every opt-in marker is out of the default run, whatever the wording.

        ``hardware`` was the only opt-in marker until 2.0.0 added ``real_ml``
        for the Demucs/RNNoise paths (PLAN D115).  Parsing the ``-m``
        expression rather than pinning the whole literal keeps the lock on
        what it is for - each opt-in marker is deselected - and lets the
        expression grow without weakening it.
        """
        addopts = self._addopts()
        assert "--strict-markers" in addopts
        assert ' -m "' in addopts
        expression = addopts.split(' -m "', 1)[1].split('"', 1)[0]
        assert "not hardware" in expression
        assert "not real_ml" in expression
        assert "not worker_memory" in expression

    def test_hardware_marker_states_the_opt_in(self) -> None:
        description = self._marker_description("hardware")
        assert "pytest -m hardware" in description
        assert "never run in CI" in description

    def test_worker_memory_marker_states_the_opt_in(self) -> None:
        description = self._marker_description("worker_memory")
        assert "pytest -m worker_memory" in description
        assert "host that ran them" in description

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
# E2 — packaging metadata lock (licence)
# ---------------------------------------------------------------------------

#: SHA-256 of the canonical GNU GPL v3 text (https://www.gnu.org/licenses/
#: gpl-3.0.txt), taken over the text with **LF** line endings - the form the
#: repository stores, so the digest describes the licence rather than one
#: host's checkout. Locking the hash, not just the header, means a corrupted or
#: silently re-flowed LICENSE fails here - the plan requires the D1 licence
#: text verbatim.
_GPL3_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"


def _canonical_licence_text(raw: bytes) -> bytes:
    """Return ``raw`` with its line endings normalised to LF.

    ``LICENSE`` carries no ``.gitattributes`` entry, so a working copy with
    ``core.autocrlf=true`` holds it as CRLF (35,823 bytes) while the repository
    stores LF (35,149).  That conversion belongs to the checkout, not to the
    licence, so the hash is taken over the normalised text; hashing raw bytes
    made one unmodified file pass on this host and fail on any clone without
    the conversion.

    Args:
        raw: The file's bytes.

    Returns:
        The same text with every CRLF pair replaced by LF.

    Raises:
        ValueError: if ``raw`` carries a bare CR. No line-ending conversion
            produces one, so it is corruption rather than a checkout
            difference and must not be normalised away.
    """
    if b"\r" in raw.replace(b"\r\n", b""):
        raise ValueError("bare CR in the licence text - not a line-ending conversion")
    return raw.replace(b"\r\n", b"\n")


_BASELINE_DOCS = ("CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md")


class TestPackagingMetadataLock:
    """Plan E2 (audit #11): the licence is declared and real.

    A metadata-only change otherwise has no verification at all, so this
    lock asserts the SPDX declaration in ``[project]``, the on-disk licence
    file (verbatim, hash-locked), and the E2 acceptance requirement that
    the baseline documents exist and are referenced from the README.
    """

    @staticmethod
    def _project_section() -> dict[str, object]:
        with PYPROJECT.open("rb") as fh:
            pyproject = tomllib.load(fh)
        project = pyproject["project"]
        assert isinstance(project, dict)
        return project

    def test_the_licence_is_declared_as_the_D1_decision(self) -> None:
        project = self._project_section()
        license_str = project.get("license")
        assert license_str == "GPL-3.0-or-later", (
            "decision D1 resolved the licence to GPL-3.0"
        )
        license_files = project.get("license-files")
        assert license_files == ["LICENSE"]

    def test_the_licence_file_exists_verbatim(self) -> None:
        path = REPO_ROOT / "LICENSE"
        assert path.is_file(), "LICENSE must exist on disk"
        canonical = _canonical_licence_text(path.read_bytes())
        assert hashlib.sha256(canonical).hexdigest() == _GPL3_SHA256, (
            "LICENSE is not the verbatim GNU GPL v3 text — refetch it from "
            "https://www.gnu.org/licenses/gpl-3.0.txt rather than editing"
        )
        text = canonical.decode("utf-8")
        assert text.startswith("                    GNU GENERAL PUBLIC LICENSE")
        assert "Version 3, 29 June 2007" in text

    def test_the_baseline_documents_exist_and_are_linked_from_the_readme(
        self,
    ) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        # The licence decision must read the same everywhere: the project
        # metadata, the distribution files and the README.
        assert "GPL-3.0-or-later" in readme
        assert "GPL-3.0-or-later" in (REPO_ROOT / "CONTRIBUTING.md").read_text(
            encoding="utf-8"
        )
        for name in _BASELINE_DOCS:
            assert (REPO_ROOT / name).is_file(), f"{name} must exist"
            assert name in readme, f"README must reference {name}"


class TestTheLicenceLockIgnoresTheCheckout:
    """A line-ending conversion must not decide whether the lock is green.

    ``_GPL3_SHA256`` was the digest of this host's CRLF working copy, so the
    same unmodified licence failed on every clone that keeps the stored LF -
    including CI's Linux legs - and the failure message pointed a reader at
    refetching a file that was already correct. Both directions are pinned
    here: the conversion is tolerated, and real corruption is not.
    """

    def test_a_crlf_working_copy_hashes_as_the_canonical_text(self) -> None:
        """Normalising the other checkout state yields the pinned digest."""
        canonical = _canonical_licence_text((REPO_ROOT / "LICENSE").read_bytes())
        crlf = canonical.replace(b"\n", b"\r\n")
        assert crlf != canonical, "the fixture must actually differ in line endings"
        assert hashlib.sha256(_canonical_licence_text(crlf)).hexdigest() == _GPL3_SHA256

    def test_a_bare_carriage_return_is_still_refused(self) -> None:
        """Only CRLF is a conversion; a lone CR is corruption and fails."""
        with pytest.raises(ValueError, match="bare CR"):
            _canonical_licence_text(b"line one\rline two\r\n")

    def test_a_changed_byte_still_fails_the_lock(self) -> None:
        """The normalisation must not be a blanket pass for any text."""
        canonical = _canonical_licence_text((REPO_ROOT / "LICENSE").read_bytes())
        edited = canonical.replace(
            b"Version 3, 29 June 2007", b"Version 3, 29 June 2008"
        )
        assert edited != canonical, "the fixture must actually edit the text"
        assert hashlib.sha256(edited).hexdigest() != _GPL3_SHA256


# ---------------------------------------------------------------------------
# Layer 2 — full-tree collection contract (real config via subprocess)
# ---------------------------------------------------------------------------


#: The helper that collects every marker view in one interpreter, so the
#: suite pays interpreter startup and the test-module imports once instead of
#: once per view (four subprocesses cost ~35 s; this costs ~19 s).
COLLECT_HELPER = REPO_ROOT / "tests" / "_collect_views.py"

#: The views the helper must produce, in its own order.  Pinned here so an
#: edit to the helper cannot quietly drop a view and leave the lock vacuous.
EXPECTED_VIEWS = (
    "default",
    "hardware",
    "real_ml",
    "worker_memory",
    "integration",
)


def _collect_views() -> dict[str, dict[str, object]]:
    """Collect the real tree under each marker view through the real config.

    The helper runs the four collections in a single interpreter; this function
    verifies it produced every view, that each collection succeeded, and turns
    each stdout into node-ids plus the raw text.

    Returns:
        ``{view: {"ids": list[str], "stdout": str}}``.  The pytest summary line
        ("N/total tests collected (M deselected)") is kept verbatim — that is
        the "the summary line says so" evidence the callers assert on.
    """
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory() as scratch:
        target = Path(scratch) / "collection-views.json"
        result = subprocess.run(
            [sys.executable, str(COLLECT_HELPER), str(target)],
            cwd=REPO_ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
            env=environment,
        )
        assert result.returncode == 0, (
            f"collection helper failed ({result.returncode}):\n"
            f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}"
        )
        payload = json.loads(target.read_text(encoding="utf-8"))

    assert isinstance(payload, dict)
    assert tuple(payload) == EXPECTED_VIEWS, (
        f"the helper collected {tuple(payload)}, expected {EXPECTED_VIEWS}"
    )

    views: dict[str, dict[str, object]] = {}
    for name, entry in payload.items():
        assert isinstance(entry, dict)
        stdout = entry["stdout"]
        returncode = entry["returncode"]
        assert isinstance(stdout, str) and isinstance(returncode, int)
        assert returncode == 0, (
            f"the {name} collection failed ({returncode}):\n{stdout[-1500:]}"
        )
        views[name] = {
            "ids": [line.strip() for line in stdout.splitlines() if "::" in line],
            "stdout": stdout,
        }
    return views


def _summary_numbers(stdout: str) -> dict[str, int]:
    match = re.search(r"(\d+)/(\d+) tests collected \((\d+) deselected\)", stdout)
    assert match is not None, f"no collection summary found in:\n{stdout[-1500:]}"
    collected, total, deselected = (int(part) for part in match.groups())
    return {"collected": collected, "total": total, "deselected": deselected}


@pytest.fixture(scope="module")
def tree_views() -> dict[str, dict[str, object]]:
    """Collect one view per marker through the real config, once per module.

    Four full-tree collections are the honest evidence — each one is the real
    pytest configuration applying a real marker filter — but they run in one
    interpreter (see :data:`COLLECT_HELPER`), and a module-scoped fixture caches
    node-ids and raw stdout so every assertion works on the same tree state.
    """
    return _collect_views()


class TestCollectHelperIsBounded:
    """A wedged collection must say where it wedged (2.1.6)."""

    def test_the_helper_arms_a_traceback_deadline(self) -> None:
        """The helper cannot park forever without reporting anything.

        Twice the suite stopped here - the 3.14 CI leg for forty minutes, and a
        local 3.14 run - with the helper sitting in its own in-process
        ``pytest.main`` and no output at all. Its deadline turns that into a
        stack dump and a non-zero exit, which the caller asserts on.
        """
        tree = ast.parse(COLLECT_HELPER.read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dump_traceback_later"
        ]

        assert calls, (
            f"{COLLECT_HELPER.name} arms no deadline: a wedged collection hangs "
            "the leg with no evidence"
        )
        exit_flags = [
            keyword
            for call in calls
            for keyword in call.keywords
            if keyword.arg == "exit"
        ]
        assert exit_flags and all(
            isinstance(keyword.value, ast.Constant) and keyword.value.value is True
            for keyword in exit_flags
        ), "the deadline must exit non-zero, or the collection still reports success"


class TestFullTreeContract:
    """The default, opt-in and integration views must agree.

    The deselected count is compared *between the runs* rather than
    hard-coded, so adding or removing a genuine hardware test keeps this
    lock intact while silently un-filtering the default run fails it.
    """

    def test_the_default_run_deselects_exactly_the_opt_in_sets(
        self, tree_views: dict[str, dict[str, object]]
    ) -> None:
        """Default deselects every opt-in marker's tests, and nothing else.

        2.0.0 added ``real_ml`` (PLAN D115) and 2.1.0 ``worker_memory``, so the
        contract is the union of the opt-in sets rather than the hardware set
        alone.
        """
        default_stdout = tree_views["default"]["stdout"]
        assert isinstance(default_stdout, str)
        summary = _summary_numbers(default_stdout)
        hardware_ids = tree_views["hardware"]["ids"]
        real_ml_ids = tree_views["real_ml"]["ids"]
        worker_memory_ids = tree_views["worker_memory"]["ids"]
        assert isinstance(hardware_ids, list)
        assert isinstance(real_ml_ids, list)
        assert isinstance(worker_memory_ids, list)

        assert summary["collected"] + summary["deselected"] == summary["total"]
        assert summary["deselected"] == (
            len(hardware_ids) + len(real_ml_ids) + len(worker_memory_ids)
        ), "the default deselect set and the opt-in sets must be the same size"
        assert all(node.startswith("cd_ripper/tests/") for node in hardware_ids), (
            "hardware tests live in the CD-ripper suite only"
        )
        assert worker_memory_ids, "the worker_memory opt-in collected nothing"
        assert all(node.startswith("utilities/tests/") for node in worker_memory_ids), (
            "worker_memory tests live in the script's own suite only"
        )
        assert real_ml_ids, "the real_ml opt-in collected nothing"
        # Both ML tools carry real-model cases: the separator (Demucs) and the
        # denoiser (RNNoise), each in its own suite (PLAN Item 6.2).
        assert all(
            node.startswith(("stem_separator/tests/", "ml_denoiser/tests/"))
            for node in real_ml_ids
        ), "real_ml tests live in the ML tools' own suites only"

    @pytest.mark.parametrize("marker", ["hardware", "real_ml", "worker_memory"])
    def test_the_opt_in_sets_never_run_in_the_default_session(
        self, tree_views: dict[str, dict[str, object]], marker: str
    ) -> None:
        default_ids = tree_views["default"]["ids"]
        opt_in_ids = tree_views[marker]["ids"]
        assert isinstance(default_ids, list) and isinstance(opt_in_ids, list)
        overlap = set(default_ids) & set(opt_in_ids)
        assert not overlap, (
            f"{marker} tests must be deselected by default; "
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
            "-p",
            "fake_missing",
            "-p",
            "no:cacheprovider",
            "-v",
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
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
        outcomes = pytester.runpytest_subprocess(
            "-p",
            "no:cacheprovider",
            "-v",
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )

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
            "-p",
            "no:cacheprovider",
            "-m",
            "hardware",
            "-v",
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
        assert outcomes.ret == 0
        outcomes.assert_outcomes(passed=1)
        line = _outcome_line(outcomes, "test_marked_hardware")
        assert _outcome(line) == "PASSED"

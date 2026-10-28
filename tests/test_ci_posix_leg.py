"""Lock the POSIX smoke leg and the selection it declares (plan item R-12).

``.github/workflows/ci.yml`` gained a ``posix-smoke`` job so that some
first-party code is *executed* on a POSIX host.  Before it, every Ubuntu job
linted, compiled, scanned or validated committed files, so the platform
matrix's "Portable core" tier rested entirely on unit tests that simulate a
platform value.  Five things can quietly undo that, and each is asserted here:

* the job is deleted (or moved back to Windows) and nobody notices;
* the module selection shrinks - a module is dropped, renamed, or the list is
  emptied - so the leg passes while executing almost nothing;
* a virtual display is installed, and the leg starts claiming GUI verification
  it never performed (the root ``conftest.py`` reports
  ``GUI behaviour: NOT VERIFIED`` on a display-less host, and that report is
  only honest while nothing supplies a display);
* the verdict goes back to being the bare exit code, where a run that collected
  nothing prints an empty report that reads like success;
* the selection is allowed to *skip* wholesale, which looks like a pass.

Every slice is asserted non-empty first (``tests/ci_workflow.py`` does that, and
raises), so a renamed job or step fails loudly rather than passing vacuously.
The prose assertions read *executed* lines only: the job's own comment explains
why it installs ffmpeg and would otherwise satisfy a raw-text match (the same
distinction ``tests/test_ci_security_audit.py`` draws for its audit step).

The module list and the numeric floor/ceiling are measured, not guessed: the
selection was derived by running it on a real Linux host in the shape the job
has (Python 3.12.16 - the same build family ``actions/setup-python`` uses -
ffmpeg and ffprobe on PATH, no display), not by reading the README's tiers.
That run collected 1757 and reported **1756 passed, 1 skipped, 0 failed**; the
single skip is ``tag_editor/tests/test_csv_io.py``'s Windows drive-relative
case.  The first landed version padded both bounds by ten; the leg's own first
run then reported the *same* 1756 / 1, so they are now the measured values
exactly.  Equality is the right shape here because the split is pinned three
ways — ``uv.lock`` fixes the dependency graph, ``setup-python`` fixes the
interpreter line, and ffmpeg is installed by an explicit step — so a deviation
is a real change (a lock upgrade, a new Python patch that skips something) and
worth seeing, not noise to absorb.  When that happens, the remedy is a
deliberate edit of the constant below **with a sentence in
PLAN_audit_2026-10-24_deferred_p2p3.md naming what moved**, never a quiet
widening.

Deriving it that way paid for itself: dropping ffmpeg first made the run say
1 751 passed / 5 failed, and the five were one real defect in shipped code plus
four tests that only Windows could pass.

Changed in 2.1.6: initial version (R-12, PLAN_audit_2026-10-24_deferred_p2p3.md).
"""

from __future__ import annotations

import re

from audio_suite_shared.platform_support import MATRIX_CAVEAT
from tests.ci_workflow import REPO_ROOT, job, step

#: The job id in ``ci.yml``; the parser keys on it, so a rename is a deliberate
#: edit here too.
JOB = "posix-smoke"

#: The step that runs the selection.
SELECTION_STEP = "Portable-core selection"

#: The declared selection, in the job's own order.  It is the CLI surface plus
#: the shared layer's non-GUI modules plus two tool packages whose tests need no
#: Windows API - deliberately not "the suite": see the module docstring.
MODULES: tuple[str, ...] = (
    "audio_suite_shared/tests/test_cli_app.py",
    "audio_suite_shared/tests/test_cli_base.py",
    "audio_suite_shared/tests/test_cli_cue.py",
    "audio_suite_shared/tests/test_cli_dataclasses.py",
    "audio_suite_shared/tests/test_cli_helpers.py",
    "audio_suite_shared/tests/test_cli_helpers_ast_lock.py",
    "audio_suite_shared/tests/test_doctor_cli.py",
    "audio_suite_shared/tests/test_suite_config.py",
    "audio_suite_shared/tests/test_exceptions.py",
    "audio_suite_shared/tests/test_project_version.py",
    "audio_suite_shared/tests/test_secure_subprocess.py",
    "audio_suite_shared/tests/test_system_requirements.py",
    "audio_suite_shared/tests/test_venv_bootstrap.py",
    "audio_suite_shared/tests/test_install_map.py",
    "audio_suite_shared/tests/test_run_outcome.py",
    "audio_suite_shared/tests/test_launcher.py",
    "audio_suite_shared/tests/test_optional_deps.py",
    "audio_suite_shared/tests/test_audio_formats.py",
    "audio_suite_shared/tests/test_constants.py",
    "audio_suite_shared/tests/test_input_validator.py",
    "audio_suite_shared/tests/test_logging_setup.py",
    "audio_suite_shared/tests/test_logging_namespacing.py",
    "audio_suite_shared/tests/test_resource_manager.py",
    "audio_suite_shared/tests/test_lrc_handler.py",
    "audio_suite_shared/tests/test_synced_lyrics.py",
    "audio_suite_shared/tests/test_cue_generator.py",
    "audio_suite_shared/tests/test_cue_parser.py",
    "audio_suite_shared/tests/test_dsp_models.py",
    "tests/test_cli_json_schema.py",
    "tests/test_cli_exit_contract.py",
    "tests/test_cli_usage_errors.py",
    "tests/test_completion_payload_published.py",
    "tests/test_run_outcome_contract.py",
    "file_reorganizer/tests/test_reorganizer.py",
    "file_reorganizer/tests/test_cli.py",
    "tag_editor/tests/test_cli.py",
    "tag_editor/tests/test_csv_io.py",
)

#: The lowest passed count the leg accepts, and the highest skip count - both
#: the leg's own first-run measurement (1756 passed, 1 skipped, run 40663662748)
#: rather than a padded margin; the module docstring says why equality is safe.
PASSED_FLOOR = 1756
SKIP_CEILING = 1

#: Tool packages and locks that must stay out of the selection: the CD Ripper's
#: subsystem is Windows-only by declaration, and the registry-reading document
#: locks live on Windows on purpose (``docs-locks`` explains why).
WINDOWS_ONLY_PREFIXES: tuple[str, ...] = ("cd_ripper/", "tests/test_docs_")


def _executed(block: str) -> str:
    """Return *block* without its comment lines.

    A YAML comment cannot select a module, install a package or set a flag, and
    these job blocks explain the decisions they embody - so a raw-text match
    would be satisfied by the explanation rather than by the wiring (D14).
    """
    return "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("#")
    )


def _selected_modules() -> set[str]:
    """Return the ``.py`` paths the job's selection step names."""
    block = _executed(step(job(JOB), SELECTION_STEP))

    return set(re.findall(r"[\w./-]+\.py", block))


class TestTheLegExists:
    """The job exists, on Ubuntu, installed from the lock."""

    def test_the_job_runs_on_ubuntu(self) -> None:
        assert "runs-on: ubuntu-latest" in job(JOB), (
            "the POSIX leg no longer runs on Linux; the caveat it backs is then "
            "a claim about a platform nothing executes"
        )

    def test_the_job_installs_from_the_lock(self) -> None:
        assert "uv sync --extra dev" in _executed(job(JOB))

    def test_the_job_installs_the_declared_system_requirement(self) -> None:
        """ffmpeg is a declared requirement, and uv cannot install a binary."""
        executed = _executed(job(JOB))

        assert "ffmpeg" in executed, "the leg no longer installs ffmpeg"

    def test_the_cli_smoke_runs_the_two_named_commands(self) -> None:
        smoke = _executed(step(job(JOB), "CLI smoke"))

        assert "audiosuite --help" in smoke
        assert "audiosuite doctor" in smoke, (
            "doctor is the smoke that fails loudly when a tool package cannot "
            "be imported or resolved from the checkout"
        )

    def test_no_virtual_display_is_installed(self) -> None:
        """A display would make the leg claim GUI verification it never did."""
        executed = _executed(job(JOB))

        assert "xvfb" not in executed.lower()
        assert "DISPLAY" not in executed


class TestTheVerdictIsReal:
    """The step can fail, and cannot pass by running nothing."""

    def test_the_step_is_not_optional(self) -> None:
        assert "continue-on-error" not in step(job(JOB), SELECTION_STEP), (
            "a leg whose failure is ignored is worse than no leg: the suite "
            "would report a platform it never verified"
        )

    def test_the_real_exit_code_is_failed_on(self) -> None:
        block = _executed(step(job(JOB), SELECTION_STEP))

        assert 'exit "$code"' in block

    def test_a_passed_count_is_required(self) -> None:
        block = _executed(step(job(JOB), SELECTION_STEP))

        assert "passed" in block, "the step no longer reads a passed count"
        # The *comparison*, not the bare number: the failure message quotes the
        # floor too, so a lowered ``-lt 1750`` would still satisfy a substring
        # match - the break-and-restore check proved exactly that.
        assert f"-lt {PASSED_FLOOR}" in block, (
            "the step no longer compares the passed count with the locked floor"
        )

    def test_the_skip_count_is_capped(self) -> None:
        block = _executed(step(job(JOB), SELECTION_STEP))

        # Same reason as the floor: the message names the ceiling.
        assert f"-gt {SKIP_CEILING}" in block, (
            "the step no longer caps the skip count; a leg that skips wholesale "
            "would report a green run"
        )

    def test_the_display_report_reaches_the_log(self) -> None:
        """The conftest's report states whether GUI behaviour was verified."""
        assert 'cat "$log"' in _executed(step(job(JOB), SELECTION_STEP))


class TestTheSelectionIsDeclared:
    """The selection is the locked set, and it is a real one."""

    def test_the_selection_is_non_empty_and_unique(self) -> None:
        assert MODULES, "an empty selection would make this lock vacuous"
        assert len(set(MODULES)) == len(MODULES), "a module is listed twice"

    def test_every_declared_module_exists(self) -> None:
        missing = [module for module in MODULES if not (REPO_ROOT / module).is_file()]

        assert not missing, (
            "a module in the locked selection no longer exists on disk - a "
            f"renamed module must be re-declared, not silently skipped: {missing}"
        )

    def test_the_job_runs_exactly_the_declared_modules(self) -> None:
        assert _selected_modules() == set(MODULES), (
            "the job's selection and the locked set disagree; a module cannot "
            "be dropped from the leg (or added to it) without editing both"
        )

    def test_the_selection_is_a_subset_and_says_so(self) -> None:
        """The leg is a smoke, not a second full suite on a foreign host."""
        for module in MODULES:
            assert not module.startswith(WINDOWS_ONLY_PREFIXES), (
                f"{module} is in the POSIX selection but is Windows-bound"
            )

    def test_the_leg_covers_the_cli_and_a_tool_package(self) -> None:
        """Non-vacuity: the two things the finding asked for are in the set."""
        assert "audio_suite_shared/tests/test_cli_app.py" in MODULES
        assert [module for module in MODULES if module.startswith("tag_editor/")]
        assert [module for module in MODULES if module.startswith("file_reorganizer/")]


class TestTheCaveatMatchesTheLeg:
    """The README's portability claim names the thing that now backs it."""

    def test_the_caveat_names_this_job(self) -> None:
        assert JOB in MATRIX_CAVEAT, (
            "the platform caveat must name the CI job that runs on a real "
            "Ubuntu host, or the README and the workflow tell different stories"
        )

    def test_the_caveat_still_refuses_the_larger_claim(self) -> None:
        lowered = MATRIX_CAVEAT.lower()

        assert "nothing else has been executed" in lowered
        assert "cross-platform" not in lowered

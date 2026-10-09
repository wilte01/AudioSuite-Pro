"""Behaviour tests for ``audio_suite_shared.logging_setup`` (plan iteration-9 G4.4).

Audit M1: tool-package modules call ``getLogger(__name__)``, which roots
their logger at the *tool package* (``noise_reduction.app``), a sibling of
the ``audio_suite`` namespace.  Those records propagated to the root
logger, which has no file handler under a GUI launch, so 112 first-party
modules' ``logger.warning/error`` calls never reached
``logs/audio_suite.log``.  ``configure_logging`` now hands the suite's
rotating handler to every first-party package logger.

A later refinement (the reported "suite log is 10,000+ lines of processing
noise" defect) split the file logging in two: the shared
``logs/audio_suite.log`` is administrator-scoped (lifecycle + WARNING+),
while each program's DEBUG/INFO detail goes to ``logs/<program>.log``.
These tests cover both contracts.

The assertions here are deliberately outcome-based: they read the *written
file* rather than the logger's internal handler list, because a handler
list can be self-consistently wrong (AGENTS section 7 - outcome correctness
is release-blocking).  Each test also removes every handler it caused to be
attached and restores ``logging.NOTSET`` on the package loggers, so nothing
leaks into the rest of the session (the shared-state lesson: leaked
handlers turn unrelated later tests into victims).
"""

from __future__ import annotations

import logging
import logging.handlers
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from audio_suite_shared import logging_setup

#: Sample tool package logger used as the "records reach the file" subject;
#: it is a real first-party package (audit M1's own probe used this name).
_TOOL_PACKAGE_LOGGER = "noise_reduction.app"

#: A third-party logger that must never receive the suite file handler.
_THIRD_PARTY_LOGGER = "urllib3.connectionpool"


def _suite_file_handler() -> logging.handlers.RotatingFileHandler:
    """Return the suite's administrator-facing rotating handler.

    ``configure_logging`` now installs *two* file handlers on the
    ``audio_suite`` logger (the admin suite log and the per-program detail
    log), so this selects by filename rather than "the only one".

    Returns:
        The ``RotatingFileHandler`` writing ``audio_suite.log``.

    Raises:
        AssertionError: if no such handler exists, which would mean the log
            path under test was never configured (every read below would
            otherwise pass vacuously against a missing file).
    """
    suite_logger = logging.getLogger("audio_suite")
    for handler in suite_logger.handlers:
        if (
            isinstance(handler, logging.handlers.RotatingFileHandler)
            and Path(handler.baseFilename).name == "audio_suite.log"
        ):
            return handler
    raise AssertionError(
        "configure_logging left no audio_suite.log RotatingFileHandler on the "
        "audio_suite logger; the file assertions would be vacuous"
    )


def _suite_log_path() -> Path:
    """Absolute path of the file the suite handler actually writes to."""
    return Path(_suite_file_handler().baseFilename)


def _program_file_handler(program_name: str) -> logging.handlers.RotatingFileHandler:
    """Return the per-program rotating handler ``configure_logging`` installed.

    Raises:
        AssertionError: if the program's handler is absent, which would make
            the per-program assertions vacuous.
    """
    filename = f"{program_name}.log"
    for handler in logging.getLogger("audio_suite").handlers:
        if (
            isinstance(handler, logging.handlers.RotatingFileHandler)
            and Path(handler.baseFilename).name == filename
        ):
            return handler
    raise AssertionError(
        f"configure_logging left no {filename} RotatingFileHandler on the "
        "audio_suite logger; the per-program assertions would be vacuous"
    )


def _program_log_path(program_name: str) -> Path:
    """Absolute path of the per-program log file."""
    return Path(_program_file_handler(program_name).baseFilename)


def _wait_for_file_marker(path: Path, marker: str, timeout: float = 2.0) -> bool:
    """Poll ``path`` until ``marker`` appears or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while True:
        if path.is_file() and marker in path.read_text(
            encoding="utf-8", errors="replace"
        ):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _wait_for_marker(marker: str, timeout: float = 2.0) -> bool:
    """Poll the suite log file until ``marker`` appears or ``timeout`` elapses.

    File handlers flush per record, so this normally succeeds on the first
    read; the retry exists only to absorb a slow or buffered filesystem.

    Args:
        marker: Unique substring expected in the log file.
        timeout: Seconds to keep polling.

    Returns:
        True when the marker was found, False on timeout.
    """
    path = _suite_log_path()
    deadline = time.monotonic() + timeout
    while True:
        if path.is_file() and marker in path.read_text(
            encoding="utf-8", errors="replace"
        ):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _contains(marker: str) -> bool:
    """Single read of the suite log file for ``marker`` (write is synchronous)."""
    path = _suite_log_path()
    return path.is_file() and marker in path.read_text(
        encoding="utf-8", errors="replace"
    )


@pytest.fixture(autouse=True)
def _clean_suite_handlers() -> Iterator[None]:
    """Detach and close every suite file handler this module's tests created.

    Runs before *and* after each test.  ``configure_logging`` installs two
    handlers (the admin suite log and the per-program log) on the
    ``audio_suite`` logger and on every first-party package logger; another
    suite (``test_app_bootstrap`` calls ``configure_logging`` repeatedly) can
    leave them attached, and a stale handler would make both the
    "exactly one handler" idempotency assertion and the per-program
    filename lookup measure an earlier test instead of this one.
    """

    def _clean() -> None:
        loggers = [
            logging.getLogger("audio_suite"),
            *(
                logging.getLogger(name)
                for name in logging_setup._first_party_package_names()
            ),
        ]
        handlers: set[logging.Handler] = set()
        for logger in loggers:
            for handler in list(logger.handlers):
                if isinstance(handler, logging.handlers.RotatingFileHandler):
                    handlers.add(handler)
                    logger.removeHandler(handler)
        for handler in handlers:
            handler.close()
        for name in logging_setup._first_party_package_names():
            logging.getLogger(name).setLevel(logging.NOTSET)

    _clean()
    yield
    _clean()


class TestPackageRecordsReachTheFileLog:
    """The M1 contract: first-party tool-package records land in the file."""

    def test_scan_subject_is_a_real_first_party_package(self) -> None:
        """Non-vacuity: the discovery finds packages, the probe's among them."""
        packages = logging_setup._first_party_package_names()
        assert packages, "no first-party packages discovered at the suite root"
        assert "noise_reduction" in packages, packages

    def test_tool_package_records_reach_the_file_log(self) -> None:
        """A WARNING from ``noise_reduction.app`` is written to the suite log."""
        marker = f"tool-package-record-{uuid4().hex}"
        logging_setup.configure_logging("test_program")
        logging.getLogger(_TOOL_PACKAGE_LOGGER).warning(marker)

        assert _wait_for_marker(marker), (
            f"{_TOOL_PACKAGE_LOGGER} record {marker!r} never reached "
            f"{_suite_log_path()} - audit M1 is back"
        )

    def test_third_party_records_stay_out_of_the_file_log(self) -> None:
        """``urllib3`` records are not routed to the suite file.

        The in-test first-party marker is the positive control: without it,
        a broken handler attachment would make this test pass vacuously.
        """
        first_party = f"first-party-control-{uuid4().hex}"
        third_party = f"third-party-record-{uuid4().hex}"
        logging_setup.configure_logging("test_program")
        logging.getLogger(_TOOL_PACKAGE_LOGGER).warning(first_party)
        logging.getLogger(_THIRD_PARTY_LOGGER).warning(third_party)

        assert _wait_for_marker(first_party), (
            "the positive control did not reach the file, so this test "
            "cannot tell third-party exclusion from a dead handler"
        )
        assert not _contains(third_party), (
            f"{_THIRD_PARTY_LOGGER} record {third_party!r} reached the suite "
            "log - the handler was attached to a third-party logger"
        )

    def test_configure_is_idempotent_per_package(self) -> None:
        """A second call leaves exactly one suite handler on each package."""
        logging_setup.configure_logging("test_program")
        logging_setup.configure_logging("test_program")

        suite_handler = _suite_file_handler()
        for package_name in logging_setup._first_party_package_names():
            package_logger = logging.getLogger(package_name)
            suite_count = sum(
                1 for handler in package_logger.handlers if handler is suite_handler
            )
            assert suite_count == 1, (
                f"{package_name} holds {suite_count} copies of the suite "
                f"handler after two configure_logging calls"
            )

    def test_min_level_filters_package_records(self) -> None:
        """``min_level`` gates what package loggers emit to the file.

        The CLI passes its ``--log-level`` here; without the pin, package
        loggers would ignore the CLI's verbosity and push INFO records to
        the console (or the file) under ``--log-level WARNING``.
        """
        info_marker = f"package-info-{uuid4().hex}"
        warning_marker = f"package-warning-{uuid4().hex}"
        logging_setup.configure_logging("test_program", min_level=logging.WARNING)
        package_logger = logging.getLogger(_TOOL_PACKAGE_LOGGER)

        package_logger.info(info_marker)
        package_logger.warning(warning_marker)

        assert _wait_for_marker(warning_marker), (
            f"WARNING from {_TOOL_PACKAGE_LOGGER} did not reach the file "
            "under min_level=logging.WARNING"
        )
        assert not _contains(info_marker), (
            f"INFO from {_TOOL_PACKAGE_LOGGER} reached the file although "
            "min_level=logging.WARNING was requested"
        )


class TestSuiteLogIsAdministratorScoped:
    """The suite log is lifecycle + WARNING+, not a processing firehose.

    The reported defect: ``logs/audio_suite.log`` held 10,000+ lines, almost
    all of it per-file DEBUG/INFO (``tag_helper_base ... ID3 load failed``,
    ``secure_subprocess Executing ...``) that buried the administrator-
    relevant WARNING/ERROR records.  The suite log now filters that detail
    out to the per-program log.
    """

    def test_tool_debug_and_info_stay_out_of_the_suite_log(self) -> None:
        debug_marker = f"tool-debug-{uuid4().hex}"
        info_marker = f"tool-info-{uuid4().hex}"
        warning_marker = f"tool-warning-{uuid4().hex}"
        logging_setup.configure_logging("test_program")
        package_logger = logging.getLogger(_TOOL_PACKAGE_LOGGER)

        package_logger.debug(debug_marker)
        package_logger.info(info_marker)
        package_logger.warning(warning_marker)

        assert _wait_for_marker(warning_marker), (
            "the WARNING positive control did not reach the suite log, so the "
            "absence assertions below would be vacuous"
        )
        assert not _contains(debug_marker), (
            f"DEBUG from {_TOOL_PACKAGE_LOGGER} reached the suite log"
        )
        assert not _contains(info_marker), (
            f"normal-running INFO from {_TOOL_PACKAGE_LOGGER} reached the suite log"
        )

    def test_shared_module_info_stays_out_of_the_suite_log(self) -> None:
        """The shared ``audio_suite.*`` INFO stream is also filtered out.

        The bulk of the reported noise came from those shared modules, so
        the per-program log is the positive control: the record must be
        *redirected*, not merely dropped.
        """
        marker = f"shared-info-{uuid4().hex}"
        logging_setup.configure_logging("test_program")
        logging.getLogger("audio_suite.audio_suite_shared.probe").info(marker)

        assert _wait_for_file_marker(_program_log_path("test_program"), marker), (
            "the shared INFO record was dropped entirely instead of being "
            "routed to the per-program log"
        )
        assert not _contains(marker), (
            "shared-module INFO reached the administrator suite log"
        )

    def test_lifecycle_line_stays_in_the_suite_log(self) -> None:
        """The startup line is the one INFO record the suite log keeps."""
        program = f"lifecycle_probe_{uuid4().hex}"
        logging_setup.configure_logging(program)

        assert _wait_for_marker(f"=== {program} started ==="), (
            "the startup lifecycle line must remain in the suite log"
        )


class TestProgramDetailLog:
    """The per-program log preserves the processing detail the suite drops."""

    def test_program_log_is_named_after_the_program(self) -> None:
        logging_setup.configure_logging("test_program")
        assert _program_log_path("test_program").name == "test_program.log"

    def test_tool_debug_reaches_the_program_log(self) -> None:
        marker = f"program-detail-{uuid4().hex}"
        logging_setup.configure_logging("test_program")
        logging.getLogger(_TOOL_PACKAGE_LOGGER).debug(marker)

        assert _wait_for_file_marker(_program_log_path("test_program"), marker), (
            f"DEBUG from {_TOOL_PACKAGE_LOGGER} never reached the per-program log"
        )

    def test_reconfigure_with_a_new_program_replaces_the_program_log(self) -> None:
        """A second call with a different program owns a single new handler.

        The process runs one program, so the previous program's handler must
        be detached and closed rather than left writing alongside the new one.
        """
        logging_setup.configure_logging("first_program")
        first = _program_file_handler("first_program")

        logging_setup.configure_logging("second_program")
        second = _program_file_handler("second_program")

        assert second is not first
        suite_logger = logging.getLogger("audio_suite")
        assert first not in suite_logger.handlers, (
            "the superseded program handler is still attached"
        )
        assert first.stream is None, "the superseded program handler was not closed"
        assert second in suite_logger.handlers

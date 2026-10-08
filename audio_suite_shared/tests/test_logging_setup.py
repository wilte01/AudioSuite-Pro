"""Behaviour tests for ``audio_suite_shared.logging_setup`` (plan iteration-9 G4.4).

Audit M1: tool-package modules call ``getLogger(__name__)``, which roots
their logger at the *tool package* (``noise_reduction.app``), a sibling of
the ``audio_suite`` namespace.  Those records propagated to the root
logger, which has no file handler under a GUI launch, so 112 first-party
modules' ``logger.warning/error`` calls never reached
``logs/audio_suite.log``.  ``configure_logging`` now hands the suite's
rotating handler to every first-party package logger.

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
    """Return the suite's rotating file handler as ``configure_logging`` left it.

    Returns:
        The ``RotatingFileHandler`` attached to the ``audio_suite`` logger.

    Raises:
        AssertionError: if no such handler exists, which would mean the log
            path under test was never configured (every read below would
            otherwise pass vacuously against a missing file).
    """
    suite_logger = logging.getLogger("audio_suite")
    for handler in suite_logger.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            return handler
    raise AssertionError(
        "configure_logging left no RotatingFileHandler on the audio_suite "
        "logger; the file assertions would be vacuous"
    )


def _suite_log_path() -> Path:
    """Absolute path of the file the suite handler actually writes to."""
    return Path(_suite_file_handler().baseFilename)


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
def _clean_package_loggers() -> Iterator[None]:
    """Detach the suite file handler from every first-party package logger.

    Runs before *and* after each test: another suite (``test_app_bootstrap``
    calls ``configure_logging`` repeatedly) can leave a handler attached, and
    a stale one would make the "exactly one handler" idempotency assertion
    measure that earlier test instead of this one.
    """

    def _clean() -> None:
        for package_name in logging_setup._first_party_package_names():
            package_logger = logging.getLogger(package_name)
            for handler in list(package_logger.handlers):
                if isinstance(handler, logging.handlers.RotatingFileHandler):
                    package_logger.removeHandler(handler)
            package_logger.setLevel(logging.NOTSET)

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

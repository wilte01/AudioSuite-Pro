"""Tests for the ``audio_suite.*`` logging namespace (iteration-8 C8, audit M18).

``app_bootstrap.configure_logging()`` attaches the suite's RotatingFileHandler
to the ``audio_suite`` logger. A module that calls ``logging.getLogger(__name__)``
produces records under ``audio_suite_shared.*``, which is a *sibling* branch:
those records propagate to the **root** logger, not to ``audio_suite``. Before
iteration-9 G4.2 there was no root handler under a GUI launch, and under
``pythonw`` logging's ``lastResort`` stderr path is discarded, so WARNING+
records vanished - including the subprocess audit trail (``secure_subprocess``)
and the undo INFO records (``batch_undo``).

Since G4.2 the same file handler is also attached to each first-party package
logger, so a package-root record reaches the file either way. This lock is
unchanged: ``audio_suite.*`` stays the enforced namespace for shared modules,
because one searchable logger name beats a per-package exception list.

Verified empirically before the fix: with a handler attached to ``audio_suite``,
a WARNING emitted through ``audio_suite_shared.secure_subprocess`` produced an
empty capture, while ``audio_suite_shared.exceptions`` (already namespaced)
reached it.

Two locks live here:

* an AST scan asserting every ``getLogger`` call in first-party
  ``audio_suite_shared`` source resolves to a name inside the ``audio_suite``
  namespace - the defect cannot come back through a new module;
* a live capture test proving a converted module's record actually *arrives*
  at an ``audio_suite`` handler. The positive contract, not the absence of one.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from audio_suite_shared import secure_subprocess
from audio_suite_shared.security import key_manager

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "audio_suite"

# Modules whose logger name is chosen at runtime rather than from __name__.
# get_logger(program_name) in error_logger builds f"audio_suite.{program_name}",
# so it is compliant by construction and has no literal to inspect.
# logging_setup (iteration-9 G4.2) calls getLogger(<package dir name>) to
# attach the suite file handler to each first-party tool package: those names
# ("bpm_analyzer", "noise_reduction", ...) are deliberately *outside* the
# audio_suite namespace, because they are the packages' own logger roots, not
# audio_suite.* modules. Its other call, getLogger("audio_suite"), is
# compliant by construction.
_RUNTIME_NAMED_MODULES = frozenset({"error_logger.py", "logging_setup.py"})


def _iter_source_files() -> list[Path]:
    """First-party ``audio_suite_shared`` modules, excluding test packages."""
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if "tests" not in path.relative_to(PACKAGE_ROOT).parts
    )


def _render_template(node: ast.expr) -> str | None:
    """Reconstruct a getLogger name from the AST.

    Returns the string for a literal, the template for an f-string
    (``f"audio_suite.{__name__}"`` -> ``"audio_suite.{__name__}"``), or None
    when the name is genuinely built at runtime.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("{" + ast.unparse(value.value) + "}")
            else:  # pragma: no cover - a format spec we do not expect
                return None
        return "".join(parts)
    return None


def _get_logger_literals(path: Path) -> list[str | None]:
    """Return the first argument of each ``getLogger`` call, AST-evaluated.

    ``None`` marks a call whose argument is not statically reconstructable (a
    runtime name), which the caller is expected to account for explicitly.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str | None] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "getLogger":
            continue
        if not node.args:
            continue
        found.append(_render_template(node.args[0]))
    return found


def _is_namespaced(literal: str) -> bool:
    """True when the logger name is the namespace itself or below it."""
    return literal == NAMESPACE or literal.startswith(f"{NAMESPACE}.")


class TestEveryModuleLoggerIsNamespaced:
    """No first-party module may hang its logger off the root logger again."""

    def test_scan_is_not_vacuous(self) -> None:
        """Guard against a silently-empty scan (a reused exclusion set).

        The plan required >= 13 call sites; the real count is higher, so the
        floor stays at the plan's number and the exact total is asserted too.
        """
        literals = [
            literal
            for path in _iter_source_files()
            for literal in _get_logger_literals(path)
        ]
        assert len(literals) >= 13, f"scan found only {len(literals)} call sites"

    def test_every_static_logger_name_is_inside_the_namespace(self) -> None:
        offenders: list[str] = []
        for path in _iter_source_files():
            if path.name in _RUNTIME_NAMED_MODULES:
                continue
            relative = path.relative_to(PACKAGE_ROOT).as_posix()
            for literal in _get_logger_literals(path):
                if literal is None:
                    offenders.append(f"{relative}: non-literal getLogger argument")
                elif literal.startswith("__name__"):
                    offenders.append(f"{relative}: un-namespaced getLogger(__name__)")
                elif not _is_namespaced(literal):
                    offenders.append(f"{relative}: getLogger({literal!r})")
        assert not offenders, (
            "loggers outside the audio_suite namespace:\n" + "\n".join(offenders)
        )

    def test_module_loggers_resolve_below_the_namespace(self) -> None:
        """Import-time proof for the modules that matter most.

        Reads the real logger objects rather than the source, so a name built
        some other way still has to come out right.
        """
        assert secure_subprocess.logger.name == (
            f"{NAMESPACE}.audio_suite_shared.secure_subprocess"
        )
        assert key_manager.logger.name == (
            f"{NAMESPACE}.audio_suite_shared.security.key_manager"
        )

    def test_tag_helper_modules_still_share_one_namespaced_logger(self) -> None:
        """The four format modules log through tag_helper_base's logger on
        purpose (its name is pinned by caplog filters); C8 moved that name
        under the namespace without splitting the group."""
        from audio_suite_shared import (
            tag_helper_base,
            tag_helper_iffid3,
            tag_helper_mp3,
            tag_helper_mp4,
            tag_helper_vorbis,
        )

        expected = f"{NAMESPACE}.audio_suite_shared.tag_helper_base"
        assert tag_helper_base.logger.name == expected
        for module in (
            tag_helper_iffid3,
            tag_helper_mp3,
            tag_helper_mp4,
            tag_helper_vorbis,
        ):
            assert module.logger.name == expected, module.__name__


class TestRecordsReachTheSuiteHandler:
    """The whole point: the records must actually arrive."""

    def test_converted_module_warning_reaches_an_audio_suite_handler(self) -> None:
        """A real WARNING from a converted module, through a real handler.

        Deliberately positive: it asserts the record shows up, not that some
        other path stayed silent.
        """
        records: list[logging.LogRecord] = []

        class _Collect(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        suite_logger = logging.getLogger(NAMESPACE)
        handler = _Collect()
        previous_level = suite_logger.level
        suite_logger.addHandler(handler)
        suite_logger.setLevel(logging.DEBUG)
        try:
            secure_subprocess.logger.warning("namespacing probe %d", 42)
        finally:
            suite_logger.removeHandler(handler)
            suite_logger.setLevel(previous_level)

        matching = [r for r in records if "namespacing probe 42" in r.getMessage()]
        assert matching, "the record never reached the audio_suite handler"
        assert matching[0].name.startswith(f"{NAMESPACE}.")

    def test_key_manager_record_also_reaches_the_handler(self) -> None:
        """Second converted module, so the wiring is not a one-module accident."""
        records: list[logging.LogRecord] = []

        class _Collect(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        suite_logger = logging.getLogger(NAMESPACE)
        handler = _Collect()
        suite_logger.addHandler(handler)
        try:
            key_manager.logger.warning("key manager probe")
        finally:
            suite_logger.removeHandler(handler)

        assert [r for r in records if "key manager probe" in r.getMessage()]

    @pytest.mark.parametrize(
        "module_name",
        [
            "audio_suite_shared.batch_undo",
            "audio_suite_shared.suite_config",
            "audio_suite_shared.tool_app_base",
        ],
    )
    def test_audit_trail_modules_are_below_the_namespace(
        self, module_name: str
    ) -> None:
        """The modules whose durable records the audit called out by name."""
        import importlib

        module = importlib.import_module(module_name)
        candidates = [
            value.name
            for value in vars(module).values()
            if isinstance(value, logging.Logger)
        ]
        assert candidates, f"{module_name} exposes no module logger"
        assert all(_is_namespaced(name) for name in candidates), candidates

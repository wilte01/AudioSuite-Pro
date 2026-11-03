"""
Lock: the tag-helper import direction, proven in a fresh interpreter.

``tag_helper_base`` used to import its six handler modules at the bottom of the
file while each handler imports ``BaseTagHandler`` back from it, so importing a
handler module *first* reached a partially initialised base and died with
``ImportError``. Every entry point therefore had to be reached through the
base, and the audit's C-M7 recorded the cycle (2.4.1 plan WP-2).

Inside the suite the modules are already in ``sys.modules``, so a normal test
cannot see the cycle: each check here runs a subprocess with a clean module
table. The handler-module case fails at HEAD and is the regression test.

Changed in 2.4.1: new lock for the tag-helper import direction.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every module that subclasses ``BaseTagHandler``. Each one must be loadable
#: as the first tag-helper import of a fresh interpreter.
HANDLER_MODULES: tuple[str, ...] = (
    "tag_helper_apev2",
    "tag_helper_dsf",
    "tag_helper_iffid3",
    "tag_helper_mp3",
    "tag_helper_mp4",
    "tag_helper_vorbis",
)


def _run(source: str) -> subprocess.CompletedProcess[str]:
    """Run ``source`` in a fresh interpreter rooted at the repository.

    Args:
        source: Python source to execute with ``-c``.

    Returns:
        The completed process, with captured output and return code.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(  # noqa: S603
        [sys.executable, "-B", "-c", source],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestFirstImport:
    @pytest.mark.parametrize("module", HANDLER_MODULES)
    def test_a_handler_module_may_be_imported_first(self, module: str) -> None:
        result = _run(f"import audio_suite_shared.{module}")
        assert result.returncode == 0, result.stderr

    def test_the_base_may_be_imported_first(self) -> None:
        result = _run("import audio_suite_shared.tag_helper_base")
        assert result.returncode == 0, result.stderr

    def test_the_facade_may_be_imported_first(self) -> None:
        result = _run("import audio_suite_shared.tag_helper")
        assert result.returncode == 0, result.stderr

    def test_the_scan_set_covers_every_handler_module(self) -> None:
        # An empty or shortened parametrization would make the lock vacuous.
        assert len(HANDLER_MODULES) == 6
        modules = {
            path.stem
            for path in (REPO_ROOT / "audio_suite_shared").glob("tag_helper_*.py")
        }
        handler_stems = modules - {
            "tag_helper",
            "tag_helper_art",
            "tag_helper_base",
            "tag_helper_reader",
            "tag_helper_writer",
        }
        assert handler_stems == set(HANDLER_MODULES)


class TestFactoryLaziness:
    def test_importing_the_factory_loads_no_handler_module(self) -> None:
        source = (
            "import sys\n"
            "import audio_suite_shared.tag_handler_factory as factory\n"
            "loaded = sorted(n for n in sys.modules if n.endswith('_handler'))\n"
            "handlers = [n for n in sys.modules if 'tag_helper_' in n]\n"
            "assert handlers == [], handlers\n"
            "assert factory.TagHandlerFactory.is_supported('.mp3') is True\n"
            "handlers = {n.rsplit('.', 1)[-1] for n in sys.modules}\n"
            "missing = [m for m in "
            "('tag_helper_mp3', 'tag_helper_vorbis', 'tag_helper_mp4', "
            "'tag_helper_iffid3', 'tag_helper_apev2', 'tag_helper_dsf') "
            "if m not in handlers]\n"
            "assert missing == [], missing\n"
            "assert loaded == [], loaded\n"
        )
        result = _run(source)
        assert result.returncode == 0, result.stderr

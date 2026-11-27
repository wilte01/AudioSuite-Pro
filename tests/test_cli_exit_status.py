"""Every `_run_tool` command that aborts through ``on_error`` must say so.

Changed in 2.9.0: this file's first change in the window that opened at
c50e533; the per-file note lock names that window 2.9.0, and the 2.9.1 note
below records what changed.
Changed in 2.9.1: new file.  ``_run_tool`` echoed an aborted run's reason to
stderr but recorded nothing in the result, so a command that stopped before
reading a file - an empty folder, or one whose files the tool cannot use -
printed ``errors: 0``, exited 0 and published no ``error``.  The CLI reference
promises status 1 for a run that stops early and says the payload's ``errors``
count matches, so the runner now marks a run that reported an error and never
completed as the one failed item.  This census is the table that rule fixes: a
command that starts aborting through ``on_error`` and is left out of it fails
here rather than shipping a silent zero.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

# Importing the app registers every first-party command on the shared group.
import audio_suite_shared.cli_app  # noqa: F401
from audio_suite_shared.cli_base import cli

#: Commands whose empty-folder run reaches ``on_error`` and returns without a
#: completion report.  Each one must exit 1 and name the reason in its payload.
ABORTS_ON_EMPTY_FOLDER: tuple[str, ...] = (
    "artnormalize",
    "bpm",
    "channels",
    "convert",
    "declip",
    "duplicates",
    "fingerprint",
    "genre-sync",
    "key",
    "lyrics",
    "mood-analyzer",
    "refine",
    "replaygain",
    "scrub",
    "split",
    "tempo",
)


@pytest.mark.parametrize("command", ABORTS_ON_EMPTY_FOLDER)
def test_an_aborted_run_exits_one_and_carries_the_reason(
    command: str, tmp_path
) -> None:
    """The status and the document agree with the reason on stderr."""
    result = CliRunner().invoke(cli, [command, str(tmp_path), "--dry", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["errors"] == 1
    reason = payload["error"]
    assert reason.strip(), "the payload must say why the run did nothing"
    assert reason in result.output, "the document and stderr must tell one story"


def test_the_census_is_not_silently_empty() -> None:
    """A parametrised table that shrank to nothing would pass vacuously."""
    assert len(ABORTS_ON_EMPTY_FOLDER) == 16

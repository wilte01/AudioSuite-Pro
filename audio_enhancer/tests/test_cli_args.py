"""
tests/test_cli_args.py
Regression tests for utils/cli_args.py's --preset argument.

Background
----------
Both this module's own docstring and main.py's docstring document usage
examples with lowercase preset values (--preset moderate, --preset
aggressive, --preset mild), but argparse's `choices` previously only
accepted the capitalized forms ("Mild", "Moderate", "Aggressive"),
causing argparse to exit with an "invalid choice" error on exactly the
commands the documentation tells the user to run.

Changed in 1.1.0: locks the preset vocabulary to the shared ``PresetName`` so
``--preset Custom`` (used by the Master Driver's card) cannot be rejected by a
local list again.

Run with:
    pytest tests/test_cli_args.py -v
"""

from __future__ import annotations

import sys

import pytest

from audio_enhancer.utils.cli_args import CliArgs, parse
from audio_suite_shared.dsp_models import PresetName

# ── Documented examples must work exactly as written ─────────────────────────


@pytest.mark.parametrize(
    "raw_value, expected_canonical",
    [
        ("moderate", "Moderate"),  # main.py docstring example
        ("aggressive", "Aggressive"),  # cli_args.py docstring example
        ("mild", "Mild"),  # cli_args.py docstring example
        ("custom", "Custom"),  # Custom DSP: keeps the tool's loaded values
        ("CUSTOM", "Custom"),
        ("Mild", "Mild"),
        ("Moderate", "Moderate"),
        ("Aggressive", "Aggressive"),
        ("MILD", "Mild"),
        ("AGGRESSIVE", "Aggressive"),
    ],
)
def test_preset_accepts_any_case_and_normalizes(
    monkeypatch: pytest.MonkeyPatch, raw_value: str, expected_canonical: str
) -> None:
    """--preset must accept any case and always produce the canonical
    capitalized value, since downstream code (app.py's
    self.preset_name.set(args.preset) -> PresetName(...)) requires the
    exact capitalized form."""
    monkeypatch.setattr(sys, "argv", ["main.py", "--preset", raw_value])
    args = parse()
    assert args.preset == expected_canonical


def test_vocabulary_is_the_shared_preset_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every shared ``PresetName`` member must be accepted, Custom included.

    The parser once carried its own three-name tuple, so the Master Driver's
    card could not offer Custom and ``--preset Custom`` was an argparse error
    while the suite CLI and both GUIs accepted it. Reading the vocabulary from
    the shared enum is what keeps the entry points in step.
    """
    for preset in PresetName:
        monkeypatch.setattr(sys, "argv", ["main.py", "--preset", preset.value])
        assert parse().preset == preset.value


def test_preset_default_is_moderate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Omitting --preset entirely must still default to 'Moderate'."""
    monkeypatch.setattr(sys, "argv", ["main.py"])
    args = parse()
    assert args.preset == "Moderate"


def test_invalid_preset_still_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A genuinely invalid preset name must still cause argparse to exit
    with an error — the case-insensitivity fix must not silently accept
    arbitrary strings."""
    monkeypatch.setattr(sys, "argv", ["main.py", "--preset", "Bogus"])
    with pytest.raises(SystemExit):
        parse()


def test_full_documented_command_line_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reproduce the exact example from cli_args.py's own module
    docstring: a full command line with --source, --preset, --auto-start."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--source", "D:/Music", "--preset", "aggressive", "--auto-start"],
    )
    args = parse()
    assert args == CliArgs(
        source="D:/Music",
        output="",
        preset="Aggressive",
        auto_start=True,
        auto_end=False,
    )

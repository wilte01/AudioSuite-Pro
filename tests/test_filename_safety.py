"""Lock: filename safety has one declared set, and the tools use it.

Changed in 2.5.0: initial version, after the Audio Joiner cut
``1-03 Johnny, Don't Do It.mp3`` at its comma and the shared validator called
that same name unsafe.

The suite's method lives in ``InputValidator``: it names the characters no
filesystem accepts (``<>:"/\\|?*`` and the control range, plus reserved device
names) and leaves every other character alone - a comma, an apostrophe,
brackets, ``&``, ``#``, ``@`` or a non-Latin letter is a legal file name.  This
lock fails when a first-party module declares its own copy of that set, which is
how the Track Splitter, the CUE splitter and the joiner drifted apart, and when
the modules that build a file name stop routing it through the shared helper.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The one module allowed to declare the illegal-character set.
DECLARATION_HOME = "audio_suite_shared/security/input_validator.py"

#: Modules that render a filename from tag text: they must sanitise through it.
SANITIZERS = (
    "track_splitter/core/naming.py",
    "audio_suite_shared/cue_split.py",
)

#: Modules that accept a filename from the user: they must validate through it.
VALIDATORS = ("audio_joiner/core/models.py",)

#: Every filename decision in the suite, for the report a failure prints.
NAME_WRITERS = (*SANITIZERS, *VALIDATORS)


def _first_party_sources() -> list[Path]:
    """Return every first-party Python module, tests and the venv excluded."""
    return sorted(
        path
        for path in REPO_ROOT.rglob("*.py")
        if not {"tests", ".venv", "__pycache__"} & set(path.parts)
    )


def _looks_like_the_illegal_set(text: str) -> bool:
    """Report whether *text* is a character set naming the forbidden ones.

    The set always contains ``<``, ``>``, ``|``, ``?`` and ``*``; a module's
    ``_FILENAME = "album_art_config.json"`` mentions a filename without being
    one of these.

    Args:
        text: The literal a module bound.

    Returns:
        True when the literal spells the forbidden character set.
    """
    return all(character in text for character in "<>|?*")


def _declares_own_set(source: str) -> bool:
    """Report whether *source* declares its own illegal-filename set.

    A declaration is a name mentioning ``ILLEGAL`` or ``FILENAME`` bound to a
    regex or string spelling the forbidden characters - the shape both
    offenders had (``_ILLEGAL = re.compile(...)`` and
    ``_ILLEGAL_FILENAME_CHARS = '<>|?*'``).  A *reference* to
    ``InputValidator.ILLEGAL_FILENAME_CHARS`` is an attribute load, not a
    binding, and is exactly the code this lock exists to encourage, so a plain
    substring search for the constant name would flag the correct modules.

    Args:
        source: The module's text.

    Returns:
        True when the module binds its own illegal-character set.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id.upper()
            if "ILLEGAL" not in name and "FILENAME" not in name:
                continue
            for literal in _string_literals(node.value):
                if _looks_like_the_illegal_set(literal):
                    return True
    return False


def _string_literals(node: ast.AST) -> list[str]:
    """Return every string literal a bound value carries.

    Args:
        node: The value side of an assignment.

    Returns:
        Its literal strings, including a ``re.compile`` call's pattern.
    """
    return [
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    ]


def test_the_scan_finds_the_tree() -> None:
    """The scan is non-vacuous: an empty walk would pass every check below."""
    assert len(_first_party_sources()) > 100


def test_the_detector_can_fail() -> None:
    """The detector recognises a declaration and ignores a shared reference."""
    assert _declares_own_set("import re\n_ILLEGAL = re.compile(r'[<>|?*]')\n")
    assert _declares_own_set("_ILLEGAL_FILENAME_CHARS = '<>|?*'\n")
    assert not _declares_own_set(
        "from audio_suite_shared.security.input_validator import InputValidator\n"
        "print(InputValidator.ILLEGAL_FILENAME_CHARS)\n"
    )


def test_only_the_security_module_declares_the_illegal_set() -> None:
    """A second copy of the character set is the drift this lock prevents."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _first_party_sources()
        if path.relative_to(REPO_ROOT).as_posix() != DECLARATION_HOME
        and _declares_own_set(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        "these modules declare their own illegal-filename set instead of using "
        f"InputValidator: {offenders}"
    )


def test_the_naming_tools_use_the_shared_helper() -> None:
    """Each module that decides a filename goes through the shared method."""
    for relative in NAME_WRITERS:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "InputValidator" in text, f"{relative} does not use InputValidator"

    for relative in SANITIZERS:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "sanitize_filename" in text, (
            f"{relative} renders a name without sanitize_filename"
        )

    for relative in VALIDATORS:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "validate_filename" in text, (
            f"{relative} accepts a user's name without validate_filename"
        )

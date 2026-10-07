"""Lock test: CLI reference documentation matches introspected click behaviour.

Plan iteration-9, item G3.1 (audit finding M2). The CLI Commands Reference
(``user_guides/reference/CLI_Commands_Reference.md``) is a hand-maintained
document whose flag defaults and existence claims were found to be the
opposite of actual click behaviour (``--dry`` documented as "default: dry"
when every command's ``dry_run`` option defaults to ``False`` → live mode).

These locks introspect every documented command and assert:

1. *Parsing non-vacuity* — the parser found ≥ 12 ``audiosuite <cmd>`` usage
   lines across the doc's fenced bash blocks.
2. *All resolved* — every documented command name resolves to a registered
   click Command or sub-command (forward direction only; commands present in
   the CLI but missing from the doc are the deferred "6 undocumented table
   rows" item and are explicitly NOT asserted here).
3. *Default claims* — for every ``--dry``/``--live`` flag bullet whose text
   states ``(default: dry)`` or ``(default: live)``, the documented word
   matches ``"live" if option.default is False else "dry"``.  At least 5
   such claims must be checked (non-vacuity).
4. *Stages default* — the ``--stages`` bullet's ``(default: …)`` text equals
   the option's ``default`` attribute verbatim.
5. *Flag existence* — every backticked long-flag token (``--foo``) at the
   start of a bullet inside a command section names a flag that actually
   exists on the owning command's params.

Any mismatch is reported as the assertion message so the test names the fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from click import Command, Group

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = REPO_ROOT / "user_guides" / "reference" / "CLI_Commands_Reference.md"

_HEADING_RE = re.compile(r"^#{2,3} (.+)$")
_FENCE_START_RE = re.compile(r"^```")
_FLAG_BULLET_RE = re.compile(r"^`(--[A-Za-z0-9-]+)")
_DRY_LIVE_RE = re.compile(r"\(default: (dry|live)\)")
_DEFAULT_VALUE_RE = re.compile(r"\(default: ([^)]*)\)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_command(name: str, toks: list[str]) -> Command | None:
    """Resolve *name* against the CLI group; descend into sub-groups."""
    from audio_suite_shared.cli_app import cli

    cmd: Command | None = cli.commands.get(name)
    if cmd is None:
        return None
    if isinstance(cmd, Group):
        for tok in toks[2:]:
            if (
                tok.startswith("-")
                or tok.startswith("<")
                or tok.startswith("[")
                or tok[0].isupper()
            ):
                break
            sub = cmd.commands.get(tok)
            if sub is not None:
                return sub
        return cmd
    return cmd


@dataclass(frozen=True)
class _Section:
    """A markdown heading section with its first command-usage tokens."""

    title: str
    line: int  # 1-indexed
    cmd_tokens: tuple[str, ...]


@dataclass(frozen=True)
class _ParsedDoc:
    """Structured view of the CLI reference document."""

    sections: tuple[_Section, ...]
    usages: tuple[tuple[int, tuple[str, ...]], ...]


def _parse_document() -> _ParsedDoc:
    """Parse ``CLI_Commands_Reference.md`` into sections and usage records."""
    text = REFERENCE.read_text(encoding="utf-8")
    lines = text.splitlines()

    sections: list[_Section] = []
    usages: list[tuple[int, tuple[str, ...]]] = []
    cur_title: str | None = None
    cur_line: int = 0
    cur_cmd_tokens: tuple[str, ...] | None = None
    in_fence = False

    for idx, raw in enumerate(lines):
        # fence toggle — always tracked
        if _FENCE_START_RE.match(raw.strip()):
            in_fence = not in_fence
            continue

        # heading only outside fences
        if not in_fence:
            hm = _HEADING_RE.match(raw)
            if hm:
                if cur_title is not None:
                    sections.append(_Section(cur_title, cur_line, cur_cmd_tokens or ()))
                cur_title = hm.group(1).strip()
                cur_line = idx + 1
                cur_cmd_tokens = None
                continue

        # audiosuite usage lines — inside fences, first non-placeholder
        if in_fence and raw.strip().startswith("audiosuite "):
            toks = raw.split()
            if len(toks) >= 3 and not toks[1].startswith("<"):
                usages.append((idx + 1, tuple(toks)))
                if cur_cmd_tokens is None:
                    cur_cmd_tokens = tuple(toks)

    # close last section
    if cur_title is not None:
        sections.append(_Section(cur_title, cur_line, cur_cmd_tokens or ()))

    return _ParsedDoc(tuple(sections), tuple(usages))


def _section_for_line(sections: tuple[_Section, ...], line_no: int) -> _Section | None:
    """Return the owning section for a bullet at *line_no* (1-indexed)."""
    best: _Section | None = None
    for sec in sections:
        if sec.line <= line_no:
            best = sec
        else:
            break
    return best


def _all_opts(cmd: Command) -> set[str]:
    """Collect every long/secondary option token from *cmd*'s params."""
    opts: set[str] = set()
    for p in cmd.params:
        opts.update(getattr(p, "opts", []))
        opts.update(getattr(p, "secondary_opts", []))
    return opts


# ---------------------------------------------------------------------------
# Module-scoped fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parsed_doc() -> _ParsedDoc:
    return _parse_document()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParsingNonVacuityAndResolution:
    """The parser finds real records and every name resolves."""

    def test_usage_records_are_non_vacuous(self, parsed_doc: _ParsedDoc) -> None:
        assert len(parsed_doc.usages) >= 12, (
            f"expected ≥ 12 audiosuite usage records, found {len(parsed_doc.usages)}"
        )

    def test_all_documented_commands_resolve(self, parsed_doc: _ParsedDoc) -> None:
        mismatches: list[str] = []
        for line_no, toks in parsed_doc.usages:
            name = toks[1]
            cmd = _resolve_command(name, list(toks))
            if cmd is None:
                mismatches.append(f"line {line_no}: unknown command {name!r}")
        assert not mismatches, (
            "documented commands not found in cli.commands:\n" + "\n".join(mismatches)
        )


class TestDryLiveDefaultClaims:
    """Every ``(default: dry)``/``(default: live)`` bullet is correct."""

    def test_claims_match_click_defaults(self, parsed_doc: _ParsedDoc) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        lines = text.splitlines()
        mismatches: list[str] = []
        checked = 0

        for idx, raw in enumerate(lines):
            if not raw.startswith("- `") or not _DRY_LIVE_RE.search(raw):
                continue
            dm = _FLAG_BULLET_RE.match(raw.lstrip("- "))
            if dm is None or dm.group(1) not in ("--dry", "--live"):
                continue
            flag = dm.group(1)
            sec = _section_for_line(parsed_doc.sections, idx + 1)
            if sec is None or not sec.cmd_tokens:
                continue
            cmd = _resolve_command(sec.cmd_tokens[1], list(sec.cmd_tokens))
            if cmd is None:
                continue
            opt = next(
                (p for p in cmd.params if flag in p.opts or flag in p.secondary_opts),
                None,
            )
            if opt is None:
                continue
            checked += 1
            expected = "live" if opt.default is False else "dry"
            documented = _DRY_LIVE_RE.search(raw).group(1)  # type: ignore[union-attr]
            if documented != expected:
                mismatches.append(
                    f"line {idx + 1}: documented '(default: {documented})' "
                    f"but click default is {opt.default!r} → should be "
                    f"'(default: {expected})'"
                )

        assert checked >= 5, f"expected ≥ 5 dry/live claims checked, found {checked}"
        assert not mismatches, "dry/live default mismatches:\n" + "\n".join(mismatches)


class TestStagesDefaultClaim:
    """The ``--stages`` bullet's default text matches the click option."""

    def test_stages_default_matches_option(self, parsed_doc: _ParsedDoc) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        lines = text.splitlines()
        mismatches: list[str] = []

        for idx, raw in enumerate(lines):
            if not raw.startswith("- `--stages"):
                continue
            dm = _DEFAULT_VALUE_RE.search(raw)
            if dm is None:
                mismatches.append(
                    f"line {idx + 1}: --stages bullet has no (default: …) text"
                )
                continue
            documented = dm.group(1)
            sec = _section_for_line(parsed_doc.sections, idx + 1)
            if sec is None or not sec.cmd_tokens:
                continue
            cmd = _resolve_command(sec.cmd_tokens[1], list(sec.cmd_tokens))
            if cmd is None:
                continue
            opt = next((p for p in cmd.params if "--stages" in p.opts), None)
            if opt is None:
                mismatches.append(
                    f"line {idx + 1}: --stages option not found on command"
                )
                continue
            actual = str(opt.default)
            if documented != actual:
                mismatches.append(
                    f"line {idx + 1}: documented '(default: {documented})' "
                    f"but click default is {actual!r} → fix to "
                    f"'(default: {actual})'"
                )

        assert not mismatches, "stages default mismatches:\n" + "\n".join(mismatches)


class TestLongFlagExistence:
    """Every ``--flag`` at the start of a bullet exists on the owning command."""

    def test_all_documented_flags_exist(self, parsed_doc: _ParsedDoc) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        lines = text.splitlines()
        mismatches: list[str] = []
        checked = 0

        for idx, raw in enumerate(lines):
            stripped = raw.lstrip("- ")
            bm = re.match(r"^`(--[A-Za-z0-9-]+)", stripped)
            if bm is None:
                continue
            flag = bm.group(1)
            sec = _section_for_line(parsed_doc.sections, idx + 1)
            if sec is None or not sec.cmd_tokens:
                continue
            cmd = _resolve_command(sec.cmd_tokens[1], list(sec.cmd_tokens))
            if cmd is None:
                continue
            opts = _all_opts(cmd)
            checked += 1
            if flag not in opts:
                mismatches.append(
                    f"line {idx + 1}: {flag} not found on command "
                    f"'{sec.cmd_tokens[1]}'; available: {sorted(opts)}"
                )

        assert checked >= 20, f"expected ≥ 20 flag-existence checks, found {checked}"
        assert not mismatches, "flag-existence mismatches:\n" + "\n".join(mismatches)

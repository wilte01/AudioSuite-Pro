"""Lock test: CLI reference documentation matches introspected click behaviour.

Plan iteration-9, item G3.1 (audit finding M2). The CLI Commands Reference
(``documentation/user_guides/reference/CLI_Commands_Reference.md``) is a hand-maintained
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
3. *Default claims* — every ``(default: …)`` an option bullet states is the
   option's real default.  Numbers compare numerically (``-16`` is ``-16.0``,
   and ``60`` is the ``'60'`` a ``Choice`` stores), choice names compare as
   text, and a boolean's prose is resolved to a polarity from that option's own
   flags (``--fade``/``--no-fade``, ``--delete-originals``/``--keep-originals``)
   before it is checked against ``opt.default``.  A phrase the lock cannot read
   fails, naming the phrase and the real default, so a rewritten default has to
   be stated in words the lock knows.  ``--scheme``'s ``(default: Italian)`` is
   checked against the tool's own ``DEFAULT_SCHEME``, because click's default is
   ``None`` and the command resolves it.
4. *Shared defaults* — the bullets under *Options every command accepts* name no
   single command, so each is checked against every command that defines the
   flag, and any command that disagrees fails the run.
5. *Flag existence* — every backticked flag token (``--foo``, ``-o``) a
   bullet names, not only the one it opens with, and every flag a usage line
   shows in brackets, names a flag that actually exists on the owning
   command's params.
6. *Option coverage (the reverse direction)* — every option click defines on
   every first-party command is named by that command's own documentation:
   either in one of its section's bullets or in the fenced syntax block that
   shows its grammar.  A new ``click.option`` that nobody documents now fails
   instead of shipping silently; rules 3-5 could only catch a documented claim
   that had gone stale.  A *syntax block* is a fenced block that carries a
   ``<placeholder>`` or a ``[--flag]``, so the scripting examples in *Exit
   status* (``audiosuite convert /Music/tmp --format flac``) are not mistaken
   for documentation of ``convert``.  Each first-party command must also have a
   *section of its own*: a section that documents no other tool's commands, and
   that a group's sub-commands may share (``plugins list``/``enable``/``disable``
   all belong to ``plugins``).  A command whose grammar is pasted into another
   tool's section fails even when every one of its flags is a shared one.
7. *Heading binding* — a section's heading must name the tool whose command the
   section documents, taken from that tool's own manifest (``scrub`` →
   ``Metadata Scrubber``).  A heading copied from a sibling section, or left
   behind by a manifest rename, fails instead of keeping a section that
   documents one tool under another tool's name.  A command with no manifest of
   its own (``doctor``, ``plugins``, ``cue``) is headed by its command name,
   which is what lets ``cue parse``'s section be told from ``cue split``'s.
8. *Stage binding* — each tool section must sit inside the stage group whose
   ``## `` heading names that tool's manifest ``category`` (an ``enrich`` tool
   under ``## ENRICH commands``), so a tool moved into the wrong group - or a
   category changed in the manifest - fails.  ``UTIL`` is accepted for
   ``utility`` because either word may be a truncation of the other; a group
   holding no manifest tool (``## Suite commands``, ``## CUE sheet commands``)
   is not a stage and is left alone.

Changed in 2.1.5: the flag-existence lock reads the whole bullet and the usage
line instead of only the bullet's first flag.  A bullet such as
``- `--dry` / `--live` `` names two flags and only one was checked, so an
invented or renamed second flag - the shape a rewritten option list takes -
went unnoticed.

Changed in 2.1.5: the default lock covers every ``(default: …)`` claim, not
only ``--dry``/``--live`` and ``--stages``.  Those two were the claims that had
bitten before, but the rest - over a hundred numbers, choice names and boolean
words - went unchecked: ``--threshold`` could say ``0.5`` while click said
``0.6`` and the suite stayed green.  The narrow tests are folded into this one,
which is strictly stronger - it reads each claim's polarity or value from click
itself and still asserts the dry/live and ``--stages`` families are present.

Changed in 2.1.5: the option-coverage lock closes the reverse direction.  The
existing rules were all document-to-code, so a flag added to a command and never
documented kept the suite green; ``fingerprint``'s ``--no-write-mbids`` had been
in that state, named by its bullet but missing from the usage grammar.  Plugin
commands are excluded because the reference documents the suite's own CLI and
the plugin's contract lives in ``documentation/docs/plugins.md``; the shared flags
are excluded because *Options every command accepts* documents them once for the whole
suite, and the root group's own options are required to appear there.  Section
ownership is checked separately, because flag coverage alone cannot see it: a
command that accepts only shared flags is fully covered by the shared block
while having no section at all.

Changed in 2.1.5: the stage lock ties each tool's section to its manifest
category.  The reference groups its tool sections into stages, and nothing ever
compared that grouping with the manifest's own ``category``: the stage headings
are prose, so a tool could be documented under the wrong stage - or its category
changed in the manifest - with every lock green.

Changed in 2.1.5: the heading lock ties each section to the tool it documents.
``test_suite_docs_tool_coverage`` requires every manifest name to appear in
*some* heading, and the section lock requires every command to have a section of
its own, but neither pairs the two: two sections could trade headings - each
command still documented, each flag still named, each section still
single-tool - and the reference would point a reader at the wrong tool above
each grammar block with every lock green.  The expected heading is the
manifest's own display name, so renaming a tool in the manifest fails here until
the reference follows.

Any mismatch is reported as the assertion message so the test names the fix.

Changed in 2.1.7: the reference is
``documentation/user_guides/reference/CLI_Commands_Reference.md``.

Changed in 2.2.0: ``stats`` gained ``--export``/``--export-path``/
``--export-columns``/``--camelot`` (backlog F-05/F-06), so the null-default
phrase table needed the one wording the new ``--export`` bullet uses for
"no export requested".  The lock is unchanged in what it asserts: a phrase the
reference states that this table does not know still fails, naming the phrase
and click's real default, so a new option cannot document its default in words
the lock cannot read.

"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from click import Command, Group, Option

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = (
    REPO_ROOT
    / "documentation"
    / "user_guides"
    / "reference"
    / "CLI_Commands_Reference.md"
)

_HEADING_RE = re.compile(r"^(#{2,3}) (.+)$")
_FENCE_START_RE = re.compile(r"^```")
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
    level: int  # 2 for a stage group, 3 for a tool section
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
    cur_level: int = 0
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
                    sections.append(
                        _Section(cur_title, cur_level, cur_line, cur_cmd_tokens or ())
                    )
                cur_title = hm.group(2).strip()
                cur_level = len(hm.group(1))
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
        sections.append(_Section(cur_title, cur_level, cur_line, cur_cmd_tokens or ()))

    return _ParsedDoc(tuple(sections), tuple(usages))


def _stage_headings(parsed: _ParsedDoc) -> tuple[_Section, ...]:
    """Return the document's level-2 stage groups, in reading order."""
    return tuple(sec for sec in parsed.sections if sec.level == 2)


def _stage_for(parsed: _ParsedDoc, line_no: int) -> _Section | None:
    """Return the stage group enclosing *line_no*, or None.

    None means the line sits above every ``## `` heading, so the tool it
    documents has no stage at all.
    """
    stage: _Section | None = None
    for sec in _stage_headings(parsed):
        if sec.line <= line_no:
            stage = sec
        else:
            break
    return stage


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


#: A flag token: one or two dashes then a letter.  ``-12`` (a LUFS value) and
#: ``-`` are deliberately not flags.
_FLAG_TOKEN = re.compile(r"-{1,2}[A-Za-z][A-Za-z0-9-]*")

#: A backticked run inside a bullet.
_BACKTICKED = re.compile(r"`([^`]+)`")


def _flags_in_bullet(raw: str) -> list[str]:
    """Return every flag a bullet names in backticks, in reading order.

    ``- `--dry` / `--live` `` yields both flags; ``- `-o, --output FILE` ``
    yields ``-o`` and ``--output``.  Values that merely start with a dash
    (``-12``, ``-16.0``) are not flags and are skipped.
    """
    flags: list[str] = []
    for tick in _BACKTICKED.findall(raw):
        for token in re.split(r"[,\s/|]+", tick.strip()):
            if token and _FLAG_TOKEN.fullmatch(token) and token not in flags:
                flags.append(token)
    return flags


def _flags_in_usage(toks: tuple[str, ...]) -> list[str]:
    """Return every flag a usage line shows, brackets stripped."""
    flags: list[str] = []
    for token in toks[2:]:
        candidate = token.strip("[](){}|,")
        if _FLAG_TOKEN.fullmatch(candidate) and candidate not in flags:
            flags.append(candidate)
    return flags


#: A flag token anywhere in prose or in a fenced block: ``--foo``, ``-o``.
#: Values (``-16.0``, ``60``, ``0.25``) do not match, so a default does not
#: masquerade as a flag.
_FLAG_IN_TEXT = re.compile(r"(?<![\w-])-{1,2}[A-Za-z][A-Za-z0-9-]*")


def _flags_in_text(text: str) -> set[str]:
    """Return every flag-shaped token in *text*."""
    return {m.group(0) for m in _FLAG_IN_TEXT.finditer(text)}


def _fenced_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Return ``(start, end)`` zero-indexed slices for each fenced block's body.

    ``start`` is the line after the opening fence and ``end`` is the line of the
    closing fence, so ``lines[start:end]`` is exactly the block's content.
    """
    blocks: list[tuple[int, int]] = []
    start: int | None = None
    for idx, raw in enumerate(lines):
        if not _FENCE_START_RE.match(raw.strip()):
            continue
        if start is None:
            start = idx + 1
        else:
            blocks.append((start, idx))
            start = None
    return blocks


def _command_index() -> dict[int, str]:
    """Map ``id(Command)`` to the name the CLI uses for it.

    A sub-command is keyed ``'plugins list'`` so a section that documents both
    ``plugins list`` and ``plugins enable`` attributes each option to the
    command that defines it, never to the group.
    """
    from audio_suite_shared.cli_app import cli

    index: dict[int, str] = {}
    for name, cmd in cli.commands.items():
        index[id(cmd)] = name
        sub_commands = getattr(cmd, "commands", None)
        if isinstance(cmd, Group) and sub_commands:
            for sub, target in sub_commands.items():
                index[id(target)] = f"{name} {sub}"
    return index


def _every_command() -> list[tuple[str, Command]]:
    """Return every command the CLI registers, sub-commands included."""
    from audio_suite_shared.cli_app import cli

    out: list[tuple[str, Command]] = [("audiosuite", cli)]
    for name, cmd in cli.commands.items():
        out.append((name, cmd))
        sub_commands = getattr(cmd, "commands", None)
        if isinstance(cmd, Group) and sub_commands:
            out.extend(
                (f"{name} {sub}", target) for sub, target in sub_commands.items()
            )
    return out


def _plugin_command_names() -> set[str]:
    """Return the commands contributed by plugins (not the suite's own CLI)."""
    from audio_suite_shared.tool_plugin import get_registry

    return {m.cli_command for m in get_registry().plugins if m.cli_command}


def _shared_flags() -> set[str]:
    """Return the flags *Options every command accepts* documents for everyone."""
    parsed = _parse_document()
    text = REFERENCE.read_text(encoding="utf-8").splitlines()
    for idx, sec in enumerate(parsed.sections):
        if sec.title not in _SHARED_SECTIONS:
            continue
        end = (
            parsed.sections[idx + 1].line - 1
            if idx + 1 < len(parsed.sections)
            else len(text)
        )
        body = text[sec.line - 1 : end]
        return set().union(*(_flags_in_bullet(raw) for raw in body)) | _flags_in_text(
            "\n".join(body)
        )
    return set()


@dataclass(frozen=True)
class _DocumentedCommand:
    """What a command's own section names: its bullets plus its syntax block."""

    section: str
    line: int
    flags: frozenset[str]


@dataclass(frozen=True)
class _SectionRecord:
    """One heading: what it documents, for the ownership and heading locks.

    ``families`` is the tool families *this section documents* (a sub-command
    collapses to its group), and ``commands`` is the resolved command names
    behind it, so ``cue parse``'s section can be told from ``cue split``'s.
    """

    title: str
    families: frozenset[str]
    commands: frozenset[str]


@dataclass(frozen=True)
class _Documentation:
    """The reference read back: what each command documents, and where."""

    commands: dict[str, _DocumentedCommand]
    #: section start line -> the record of what that section documents
    sections: dict[int, _SectionRecord]
    problems: list[str]


def _documented_commands() -> _Documentation:
    """Map every documented command to the flags its section names for it.

    Bullets are attributed to every command documented in their section (one
    section can hold several short commands); a syntax block's flags are
    attributed only to the commands that block shows, so ``cue split``'s flags
    cannot excuse an undocumented option on ``cue parse``.

    The sections map records which *tool family* each section documents - a
    sub-command collapses to its group, so ``plugins list`` counts towards
    ``plugins``.  Two families in one section means at least one of them has no
    section of its own; that is what ``TestEveryCommandHasItsOwnSection`` reads.
    """
    lines = REFERENCE.read_text(encoding="utf-8").splitlines()
    parsed = _parse_document()
    index = _command_index()

    bullet_flags: dict[int, set[str]] = {}
    for idx, raw in enumerate(lines):
        if not raw.startswith("- `"):
            continue
        sec = _section_for_line(parsed.sections, idx + 1)
        if sec is None:
            continue
        bullet_flags.setdefault(sec.line, set()).update(_flags_in_bullet(raw))

    documented: dict[str, _DocumentedCommand] = {}
    families: dict[int, tuple[str, set[str]]] = {}
    owned: dict[int, set[str]] = {}
    problems: list[str] = []

    for start, end in _fenced_blocks(lines):
        body = lines[start:end]
        if not any(
            token.startswith(("<", "[")) for raw in body for token in raw.split()
        ):
            continue  # an example invocation, not the command's grammar
        block_flags = _flags_in_text("\n".join(body))
        for offset, raw in enumerate(body):
            if not raw.strip().startswith("audiosuite "):
                continue
            toks = raw.split()
            if len(toks) < 3 or toks[1].startswith("<"):
                continue  # ``audiosuite <command> DIR [options]`` is the grammar
            target = _resolve_command(toks[1], list(toks))
            canonical = index.get(id(target)) if target is not None else None
            if canonical is None:
                problems.append(
                    f"line {start + offset + 1}: syntax line names unknown "
                    f"command {toks[1]!r}"
                )
                continue
            sec = _section_for_line(parsed.sections, start + offset + 1)
            if sec is None:
                problems.append(
                    f"line {start + offset + 1}: {canonical!r} sits outside "
                    "every section"
                )
                continue
            flags = set(block_flags) | bullet_flags.get(sec.line, set())
            previous = documented.get(canonical)
            if previous is not None:
                flags |= previous.flags
            documented[canonical] = _DocumentedCommand(
                sec.title, start + offset + 1, frozenset(flags)
            )
            family_title, seen = families.setdefault(sec.line, (sec.title, set()))
            seen.add(canonical.split(" ")[0])
            owned.setdefault(sec.line, set()).add(canonical)

    return _Documentation(
        documented,
        {
            line: _SectionRecord(
                family_title,
                frozenset(seen),
                frozenset(owned.get(line, set())),
            )
            for line, (family_title, seen) in families.items()
        },
        problems,
    )


# ---------------------------------------------------------------------------
# Documented default claims
# ---------------------------------------------------------------------------

#: Phrases that state "nothing chosen".  A null phrase only passes while click's
#: own default really is empty, so a command that grows a concrete default
#: makes the claim fail instead of quietly disagreeing with it.
_NULL_DEFAULT_PHRASES: frozenset[str] = frozenset(
    {
        "all",  # --tracks: every track
        "no export",  # --export: None means the run writes no artefact
        "source dir",  # --output: keeps each file beside its source
        "beside each source file",  # --output-dir
        "alongside the cue sheet",  # -o/--output-dir on cue
        "album.cue next to the input",  # -o/--output on cue
    }
)

#: Defaults that mean "the command decides where the file goes / what to read".
_EMPTY_DEFAULTS: tuple[object, ...] = (None, (), "", frozenset())

#: Prose describing a flag's *effect* rather than naming one of its sides.  The
#: stated polarity is still checked against click: ``plugins run`` passes only
#: while ``--no-plugin-tags`` defaults to False.
_BOOLEAN_PROSE: dict[str, bool] = {"plugins run": False}

#: Sections whose bullets name no single command; see rule 4 in the docstring.
_SHARED_SECTIONS: frozenset[str] = frozenset({"Options every command accepts"})

#: Marks a phrase whose default could not be read at all.
_MISSING = object()


def _clean_phrase(text: str) -> str:
    """Strip backticks and collapse whitespace, preserving case."""
    return " ".join(text.replace("`", "").split())


def _options_of(cmd: Command) -> list[Option]:
    """Return *cmd*'s options (not its arguments)."""
    return [p for p in cmd.params if isinstance(p, Option)]


def _option_for(flags: list[str], cmd: Command) -> Option | None:
    """Return the option of *cmd* that owns any flag in *flags*."""
    for flag in flags:
        for opt in _options_of(cmd):
            if flag in opt.opts or flag in opt.secondary_opts:
                return opt
    return None


def _is_boolean(opt: Option) -> bool:
    """True when the option is a switch (``--fade/--no-fade`` included)."""
    return bool(opt.is_flag or opt.secondary_opts)


def _flag_words(opt: Option) -> dict[str, bool]:
    """Map every word the document may use for *opt*'s default to its polarity.

    ``--fade`` / ``--no-fade`` yields ``fade`` → True and ``no-fade`` → False,
    so ``(default: no-fade)`` is checked against the real boolean instead of
    being trusted.  A primary flag's word wins a tie, which is what the
    documentation convention means: naming the base word states the positive
    side (``preserve`` for ``--preserve-lyrics``).
    """
    words: dict[str, bool] = {
        "on": True,
        "true": True,
        "enabled": True,
        "yes": True,
        "off": False,
        "false": False,
        "disabled": False,
        "no": False,
    }
    for flag in opt.opts:
        name = flag.lstrip("-")
        words.setdefault(name, True)
        for segment in name.split("-"):
            words.setdefault(segment, True)
    for flag in opt.secondary_opts:
        name = flag.lstrip("-")
        base = name[3:] if name.startswith("no-") else name
        words[name] = False
        words.setdefault(base, False)
        for segment in base.split("-"):
            words.setdefault(segment, False)
    return words


def _boolean_polarity(opt: Option, phrase: str) -> bool | None:
    """Return the polarity *phrase* states for *opt*, or None if unreadable.

    ``full walk`` reads as the ``--full`` side of
    ``--incremental``/``--full``; the trailing word is prose.
    """
    if phrase in _BOOLEAN_PROSE:
        return _BOOLEAN_PROSE[phrase]
    words = _flag_words(opt)
    if phrase in words:
        return words[phrase]
    first = phrase.split()[0]
    return words.get(first)


def _tempo_scheme_default() -> object:
    """``--scheme``'s effective default: click stores None, the command decides."""
    from tempo_analyzer.core.tempo_schemes import DEFAULT_SCHEME

    return DEFAULT_SCHEME


#: Effective defaults click cannot express, keyed by ``(command, flag)``.  The
#: documented value is compared with the source of truth the command actually
#: uses, and the claim is only accepted while click's own default stays empty.
_RUNTIME_DEFAULTS: dict[tuple[str, str], Callable[[], object]] = {
    ("tempo", "--scheme"): _tempo_scheme_default,
}


def _expected_value(
    opt: Option, documented: str, command: str | None, flag: str
) -> tuple[object, str]:
    """Return ``(expected, kind)`` for a documented default of *opt*.

    ``kind`` is one of ``boolean``, ``empty``, ``runtime`` or ``literal``;
    ``expected`` is ``_MISSING`` when the phrase carries no value the lock can
    read (an unknown boolean wording), and for ``literal`` the option's own
    default is compared directly with the documented text.
    """
    phrase = _clean_phrase(documented).lower()
    runtime = _RUNTIME_DEFAULTS.get((command or "", flag))
    if runtime is not None:
        return runtime(), "runtime"
    if phrase in _NULL_DEFAULT_PHRASES:
        return None, "empty"
    if _is_boolean(opt):
        polarity = _boolean_polarity(opt, phrase)
        if polarity is None:
            return _MISSING, "boolean"
        return polarity, "boolean"
    return _MISSING, "literal"


def _boolean_phrase(opt: Option) -> str:
    """Return the wording this lock suggests for *opt*'s real default.

    A switch pair is named by the side that is actually on by default
    (``live`` for ``--dry/--live``), a lone switch by ``on``/``off``.
    """
    if opt.secondary_opts:
        flag = opt.secondary_opts[0] if opt.default is False else opt.opts[0]
        return str(flag).lstrip("-")
    return "on" if opt.default else "off"


def _claim_matches(
    opt: Option, documented: str, command: str | None, flag: str
) -> tuple[bool, str, str]:
    """Return ``(agrees, kind, expected_text)`` for one documented default."""
    expected, kind = _expected_value(opt, documented, command, flag)
    if kind == "runtime":
        agrees = opt.default in _EMPTY_DEFAULTS and str(expected) == _clean_phrase(
            documented
        )
        return agrees, kind, str(expected)
    if kind == "empty":
        return opt.default in _EMPTY_DEFAULTS, kind, "(nothing / the command decides)"
    if kind == "boolean":
        if expected is _MISSING:
            return False, kind, _boolean_phrase(opt)
        return opt.default is expected, kind, _boolean_phrase(opt)
    text = _clean_phrase(documented)
    if isinstance(opt.default, bool):
        return False, kind, _boolean_phrase(opt)
    if opt.default in _EMPTY_DEFAULTS:
        return False, kind, "(nothing / the command decides)"
    try:
        return float(text) == float(opt.default), kind, str(opt.default)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return text == str(opt.default), kind, str(opt.default)


@dataclass(frozen=True)
class _DefaultClaim:
    """A ``(default: …)`` bullet attached to one command's option."""

    line: int
    section: str
    command: str
    flag: str
    documented: str
    opt: Option


@dataclass(frozen=True)
class _SharedClaim:
    """A ``(default: …)`` bullet under *Options every command accepts*."""

    line: int
    flag: str
    documented: str
    owners: tuple[tuple[str, Option], ...]


def _shared_owners(flags: list[str]) -> list[tuple[str, Option]]:
    """Return every command (and the root group) that defines one of *flags*."""
    from audio_suite_shared.cli_app import cli

    owners: list[tuple[str, Option]] = []
    for opt in _options_of(cli):
        if any(f in opt.opts or f in opt.secondary_opts for f in flags):
            owners.append(("audiosuite", opt))
    for name, cmd in cli.commands.items():
        sub_commands = getattr(cmd, "commands", None)
        if isinstance(cmd, Group) and sub_commands:
            pairs = [(f"{name} {sub}", target) for sub, target in sub_commands.items()]
        else:
            pairs = [(name, cmd)]
        for who, target in pairs:
            opt = _option_for(flags, target)
            if opt is not None:
                owners.append((who, opt))
    return owners


def _default_claims(
    parsed: _ParsedDoc,
) -> tuple[list[_DefaultClaim], list[_SharedClaim], list[str]]:
    """Collect every documented default, plus the claims it cannot attach."""
    lines = REFERENCE.read_text(encoding="utf-8").splitlines()
    claims: list[_DefaultClaim] = []
    shared: list[_SharedClaim] = []
    problems: list[str] = []

    for idx, raw in enumerate(lines):
        if not raw.startswith("- `"):
            continue
        dm = _DEFAULT_VALUE_RE.search(raw)
        if dm is None:
            continue
        documented = dm.group(1)
        flags = _flags_in_bullet(raw)
        if not flags:
            problems.append(f"line {idx + 1}: default claim names no flag: {raw[:70]}")
            continue
        sec = _section_for_line(parsed.sections, idx + 1)
        if sec is None or not sec.cmd_tokens:
            where = sec.title if sec is not None else "no"
            if sec is None or sec.title not in _SHARED_SECTIONS:
                problems.append(
                    f"line {idx + 1}: '(default: {documented})' sits in the "
                    f"{where!r} section, which names no command"
                )
                continue
            owners = _shared_owners(flags)
            if not owners:
                # ``--log-level`` is declared on the root group, every other
                # shared flag on the commands, so one owner is legitimate.
                problems.append(
                    f"line {idx + 1}: shared default {flags[0]} names a flag "
                    "the CLI does not define anywhere"
                )
                continue
            shared.append(_SharedClaim(idx + 1, flags[0], documented, tuple(owners)))
            continue
        cmd = _resolve_command(sec.cmd_tokens[1], list(sec.cmd_tokens))
        if cmd is None:
            continue
        opt = _option_for(flags, cmd)
        if opt is None:
            problems.append(
                f"line {idx + 1}: no option for {flags} on '{sec.cmd_tokens[1]}'"
            )
            continue
        claims.append(
            _DefaultClaim(
                idx + 1, sec.title, sec.cmd_tokens[1], flags[0], documented, opt
            )
        )
    return claims, shared, problems


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


class TestDocumentedDefaultClaims:
    """Every ``(default: …)`` an option bullet states is click's real default."""

    def test_every_documented_default_is_attached(self, parsed_doc: _ParsedDoc) -> None:
        """A claim must land on a command (or the shared block), never be skipped."""
        _claims, _shared, problems = _default_claims(parsed_doc)
        assert not problems, (
            "default claims the lock cannot attach (fix the section or the "
            "bullet):\n" + "\n".join(problems)
        )

    def test_every_documented_default_matches_click(
        self, parsed_doc: _ParsedDoc
    ) -> None:
        claims, shared, _ = _default_claims(parsed_doc)
        mismatches: list[str] = []

        for claim in claims:
            agrees, kind, expected = _claim_matches(
                claim.opt, claim.documented, claim.command, claim.flag
            )
            if agrees:
                continue
            unreadable = kind == "boolean" and (
                _boolean_polarity(claim.opt, _clean_phrase(claim.documented).lower())
                is None
            )
            if unreadable:
                hint = (
                    " - the phrase states no default the lock can read; add it "
                    "to _BOOLEAN_PROSE with its polarity"
                )
            elif expected.startswith("(nothing"):
                hint = (
                    " - click's default is empty; state it with one of "
                    "_NULL_DEFAULT_PHRASES such as 'source dir'"
                )
            else:
                hint = f" - fix the text to '(default: {expected})'"
            mismatches.append(
                f"line {claim.line} ({claim.section}, '{claim.command}' "
                f"{claim.flag}): documented '(default: {claim.documented})' but "
                f"click default is {claim.opt.default!r}{hint}"
            )

        for shared_claim in shared:
            for who, opt in shared_claim.owners:
                agrees, kind, expected = _claim_matches(
                    opt, shared_claim.documented, None, shared_claim.flag
                )
                if agrees:
                    continue
                mismatches.append(
                    f"line {shared_claim.line} (shared {shared_claim.flag}), "
                    f"command '{who}': documented '(default: "
                    f"{shared_claim.documented})' but click default is "
                    f"{opt.default!r} - state '(default: {expected})'"
                )

        assert not mismatches, "documented default mismatches:\n" + "\n".join(
            mismatches
        )

    def test_the_scan_covers_every_default_kind(self, parsed_doc: _ParsedDoc) -> None:
        """Neither a parser break nor a rewritten document can make it vacuous."""
        claims, shared, _ = _default_claims(parsed_doc)
        kinds: Counter[str] = Counter()
        for claim in claims:
            _expected, kind = _expected_value(
                claim.opt, claim.documented, claim.command, claim.flag
            )
            kinds[kind] += 1

        dry_live = sum(
            1
            for claim in claims
            if _clean_phrase(claim.documented).lower() in {"dry", "live"}
        )
        stages = [claim for claim in claims if claim.flag == "--stages"]

        assert len(claims) >= 110, f"only {len(claims)} command defaults scanned"
        assert len(shared) >= 3, f"only {len(shared)} shared defaults scanned"
        assert max(len(s.owners) for s in shared) >= 20, (
            "the shared defaults no longer expand across the whole CLI: "
            f"{[(s.flag, len(s.owners)) for s in shared]}"
        )
        assert kinds["boolean"] >= 25, f"only {kinds['boolean']} boolean defaults"
        assert kinds["literal"] >= 55, f"only {kinds['literal']} typed defaults"
        assert kinds["empty"] >= 4, f"only {kinds['empty']} empty defaults"
        assert kinds["runtime"] >= 1, "the --scheme runtime default is unchecked"
        assert dry_live >= 5, f"only {dry_live} dry/live claims checked"
        assert stages, "the --stages default is no longer checked"
        assert all(
            _claim_matches(c.opt, c.documented, c.command, c.flag)[1] == "literal"
            for c in stages
        ), "a --stages claim is no longer compared as text"


class TestLongFlagExistence:
    """Every flag a bullet or usage line names exists on the owning command."""

    def test_every_flag_in_a_bullet_exists(self, parsed_doc: _ParsedDoc) -> None:
        """Both flags of ``- `--dry` / `--live` `` are checked, not just the first."""
        text = REFERENCE.read_text(encoding="utf-8")
        lines = text.splitlines()
        mismatches: list[str] = []
        checked = 0

        for idx, raw in enumerate(lines):
            if not raw.startswith("- `"):
                continue
            sec = _section_for_line(parsed_doc.sections, idx + 1)
            if sec is None or not sec.cmd_tokens:
                continue
            cmd = _resolve_command(sec.cmd_tokens[1], list(sec.cmd_tokens))
            if cmd is None:
                continue
            opts = _all_opts(cmd)
            for flag in _flags_in_bullet(raw):
                checked += 1
                if flag not in opts:
                    mismatches.append(
                        f"line {idx + 1}: {flag} not found on command "
                        f"'{sec.cmd_tokens[1]}' for {sec.title!r}; "
                        f"available: {sorted(opts)}"
                    )

        assert checked >= 100, f"expected ≥ 100 flag checks, found {checked}"
        assert not mismatches, "flag-existence mismatches:\n" + "\n".join(mismatches)

    def test_every_flag_in_a_usage_line_exists(self, parsed_doc: _ParsedDoc) -> None:
        """The bracketed flags of ``audiosuite <cmd> … [--flag N]`` are real too."""
        mismatches: list[str] = []
        checked = 0

        for line_no, toks in parsed_doc.usages:
            cmd = _resolve_command(toks[1], list(toks))
            if cmd is None:
                continue
            opts = _all_opts(cmd)
            for flag in _flags_in_usage(toks):
                checked += 1
                if flag not in opts:
                    mismatches.append(
                        f"line {line_no}: usage of {toks[1]!r} shows {flag}, "
                        f"which it does not define; available: {sorted(opts)}"
                    )

        assert checked >= 60, f"expected ≥ 60 usage-flag checks, found {checked}"
        assert not mismatches, "usage-flag mismatches:\n" + "\n".join(mismatches)


class TestEveryOptionIsDocumented:
    """The reverse direction: click's own options must appear in the reference.

    Rules 3-5 are document-to-code, so they say nothing about an option nobody
    wrote down.  These tests close that direction: a flag added to a command
    without a bullet or a syntax-line mention fails, naming the command and the
    flag.
    """

    def test_every_first_party_option_is_named(self) -> None:
        docs = _documented_commands()
        assert not docs.problems, "documentation the lock cannot read:\n" + "\n".join(
            docs.problems
        )
        documented = docs.commands
        shared = _shared_flags()
        plugin_commands = _plugin_command_names()
        missing: list[str] = []

        for name, cmd in _every_command():
            if name == "audiosuite" or name in plugin_commands:
                continue
            record = documented.get(name)
            if record is None:
                # Whether an undocumented command exists at all is
                # TestEveryCommandHasItsOwnSection's question; this test can
                # only check the options of a command the reference documents.
                continue
            for opt in _options_of(cmd):
                for flag in (*opt.opts, *opt.secondary_opts):
                    if flag == "--help" or flag in shared:
                        continue
                    if flag not in record.flags:
                        missing.append(
                            f"line {record.line} ({record.section!r}, {name!r}): "
                            f"{flag} is an option of this command but its "
                            "section never names it; add it to the bullets or "
                            "the syntax block"
                        )

        assert not missing, "undocumented options:\n" + "\n".join(missing)

    def test_the_root_group_options_live_in_the_shared_block(self) -> None:
        """``--log-level`` and friends are documented once, for every command."""
        from audio_suite_shared.cli_app import cli

        shared = _shared_flags()
        missing = [
            flag
            for opt in _options_of(cli)
            for flag in (*opt.opts, *opt.secondary_opts)
            if flag != "--help" and flag not in shared
        ]
        assert not missing, (
            "the root group's options are not in 'Options every command accepts': "
            f"{missing}"
        )

    def test_the_scan_cannot_pass_vacuously(self) -> None:
        documented = _documented_commands().commands
        shared = _shared_flags()
        plugin_commands = _plugin_command_names()
        checked = 0
        secondary = 0

        for name, cmd in _every_command():
            if name == "audiosuite" or name in plugin_commands:
                continue
            record = documented.get(name)
            if record is None:
                continue
            for opt in _options_of(cmd):
                for flag in (*opt.opts, *opt.secondary_opts):
                    if flag == "--help" or flag in shared:
                        continue
                    checked += 1
                    if flag in opt.secondary_opts:
                        secondary += 1

        assert len(documented) >= 34, (
            f"only {len(documented)} documented commands found: {sorted(documented)}"
        )
        assert checked >= 160, f"only {checked} options checked for documentation"
        assert secondary >= 20, (
            f"only {secondary} secondary/negative options checked - a switch "
            "pair now only needs its positive half"
        )
        assert shared >= {
            "--dry",
            "--live",
            "--json",
            "--text",
            "--parallel",
            "--workers",
        }, f"the shared block no longer documents the suite-wide flags: {shared}"
        assert {"plugins list", "plugins enable", "plugins disable"} <= set(
            documented
        ), "a `plugins` sub-command lost its syntax line"
        assert "example" in plugin_commands, (
            "the bundled plugin command is no longer detected, so the plugin "
            "exemption may be hiding a first-party command"
        )
        assert "--no-write-mbids" in documented["fingerprint"].flags, (
            "the fingerprinter's switch pairs must be spelled out in its syntax "
            "block; this is the gap the lock was written to catch"
        )


def _sections_of_their_own(docs: _Documentation) -> set[str]:
    """Return the tool families that own a section documenting nothing else."""
    return {
        family
        for record in docs.sections.values()
        if len(record.families) == 1
        for family in record.families
    }


def _expected_families() -> dict[str, set[str]]:
    """Return each first-party tool family and the CLI commands that belong to it."""
    plugin_commands = _plugin_command_names()
    families: dict[str, set[str]] = {}
    for name, _cmd in _every_command():
        if name == "audiosuite" or name in plugin_commands:
            continue
        families.setdefault(name.split(" ")[0], set()).add(name)
    return families


def _manifest_names_by_command() -> dict[str, str]:
    """Map each tool's CLI command to the display name its manifest gives it.

    The manifest is the single source of truth for a tool's name - the README
    index, the Master Driver card and ``audiosuite doctor`` all read it - so the
    reference's headings are checked against it rather than against a list kept
    here.  Plugins are excluded: a third-party tool must not change what the
    shipped reference claims about the distribution.
    """
    from audio_suite_shared.tool_plugin import get_registry

    return {
        manifest.cli_command: manifest.name
        for manifest in get_registry().first_party
        if manifest.cli_command
    }


def _common_command_prefix(names: frozenset[str]) -> str:
    """Return the leading tokens every command name in *names* shares.

    ``plugins list``/``enable``/``disable`` share ``plugins``; a single name is
    its own prefix, which is what keeps ``cue split`` distinguishable from
    ``cue parse``.
    """
    parts = [name.split(" ") for name in sorted(names)]
    if not parts or not parts[0]:
        return ""
    return " ".join(tokens[0] for tokens in zip(*parts) if len(set(tokens)) == 1)


def _expected_heading(record: _SectionRecord, manifest: dict[str, str]) -> str | None:
    """Return the heading *record*'s commands should sit under, or None.

    A tool's own manifest name wins when the section documents that tool; a
    section documenting no manifest tool (``doctor``) - or several sub-commands
    of one group (``plugins list``/``enable``/``disable``) - is headed by the
    command names themselves.  ``None`` means the section documents more than
    one tool, a fault ``TestEveryCommandHasItsOwnSection`` already reports; this
    lock does not report the same fault twice.
    """
    if len(record.families) != 1:
        return None
    family = next(iter(record.families))
    if family in manifest:
        return manifest[family]
    return _common_command_prefix(record.commands) or None


def _normalise_heading(text: str) -> str:
    """Casefold and collapse whitespace, so heading style is not the subject."""
    return " ".join(text.split()).casefold()


def _manifest_categories_by_command() -> dict[str, str]:
    """Map each tool's CLI command to the manifest category it belongs to."""
    from audio_suite_shared.tool_plugin import get_registry

    return {
        manifest.cli_command: manifest.category
        for manifest in get_registry().first_party
        if manifest.cli_command
    }


#: Shortest word that may stand in for a category name - ``UTIL`` for
#: ``utility``.  A shorter one would match almost any heading word.
_MIN_STAGE_WORD = 4


def _stage_word_matches_category(word: str, category: str) -> bool:
    """True when *word* names *category*: either is a truncation of the other.

    The reference writes ``UTIL`` for the manifest's ``utility``, so an exact
    match alone would need a hand-listed alias table; allowing only one exact
    spelling would reject a heading the manifest's own word already describes.
    """
    word = _normalise_heading(word)
    category = _normalise_heading(category)
    shorter, longer = sorted((word, category), key=len)
    return len(shorter) >= _MIN_STAGE_WORD and longer.startswith(shorter)


def _manifest_command(record: _SectionRecord, categories: dict[str, str]) -> str | None:
    """Return the manifest CLI command a section documents, or None.

    A section documenting a group's sub-commands (``plugins list``/``enable``/
    ``disable``) or a suite command (``doctor``, ``cue parse``) has no manifest
    of its own, so it has no category to check and the stage lock leaves it
    alone.
    """
    if len(record.families) != 1:
        return None
    family = next(iter(record.families))
    return family if family in categories else None


def _heading_problem(title: str, expected: str, manifest: dict[str, str]) -> str | None:
    """Return why *title* fails to name the tool *expected* names, or None.

    The heading must open with the expected name at a word boundary - a suffix
    such as ``(enrich)`` is fine - and must not name another manifest tool, so a
    compound heading cannot pass by naming the right tool second.
    """
    got = _normalise_heading(title)
    want = _normalise_heading(expected)
    if not got.startswith(want) or got[len(want) :][:1].isalnum():
        return "it does not name it"
    for name in manifest.values():
        other = _normalise_heading(name)
        if other == want:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(other)}(?![a-z0-9])"
        if re.search(pattern, got):
            return f"it names another tool ({name!r})"
    return None


class TestEveryCommandHasItsOwnSection:
    """A command is documented by a section about it, not by a mention elsewhere.

    ``TestEveryOptionIsDocumented`` requires each option to be named, but a
    command whose flags are all shared (``--dry``/``--live``, ``--json``) is
    fully covered by *Options every command accepts* while having no section of
    its own, and a grammar block pasted into another tool's section satisfies
    the flag check too.  These tests own that question.
    """

    def test_every_first_party_command_has_a_section_of_its_own(self) -> None:
        docs = _documented_commands()
        assert not docs.problems, "documentation the lock cannot read:\n" + "\n".join(
            docs.problems
        )
        heads = _sections_of_their_own(docs)
        missing: list[str] = []

        for family, names in sorted(_expected_families().items()):
            if family in heads:
                continue
            places = [
                f"{title!r} (with {sorted(others - {family})})"
                for title, others in docs.sections.values()
                if family in others
            ]
            where = (
                f"; it is documented only inside {'; '.join(places)}"
                if places
                else "; no section documents it"
            )
            missing.append(
                f"{', '.join(sorted(names))} has no section of its own{where}"
            )

        assert not missing, (
            "commands without a section of their own (give each a `### …` "
            "section with a fenced `audiosuite …` grammar block):\n"
            + "\n".join(missing)
        )

    def test_no_section_documents_two_tools(self) -> None:
        docs = _documented_commands()
        mixed = [
            f"{record.title!r}: {sorted(record.families)}"
            for record in docs.sections.values()
            if len(record.families) > 1
        ]
        assert not mixed, (
            "these sections document more than one tool, so the extra command "
            "has no section of its own:\n" + "\n".join(mixed)
        )

    def test_the_section_scan_cannot_pass_vacuously(self) -> None:
        docs = _documented_commands()
        heads = _sections_of_their_own(docs)
        expected = _expected_families()

        assert not docs.problems, "\n".join(docs.problems)
        assert len(expected) >= 30, (
            f"only {len(expected)} first-party tool families found: {sorted(expected)}"
        )
        assert len(docs.sections) >= 32, (
            f"only {len(docs.sections)} sections document a command: "
            f"{sorted(record.title for record in docs.sections.values())}"
        )
        assert len(heads) >= 29, (
            f"only {len(heads)} tool families own a section: {sorted(heads)}"
        )
        assert all(record.families for record in docs.sections.values()), (
            "a section's command did not resolve to a tool family"
        )
        assert {"fingerprint", "doctor", "cue", "plugins", "tag-edit"} <= heads, (
            "a known single-tool section no longer counts as that tool's own: "
            f"{sorted(heads)}"
        )


class TestSectionHeadingsNameTheirTool:
    """A section's heading is the name of the tool whose command it documents.

    ``test_suite_docs_tool_coverage`` requires every manifest name to appear in
    *some* heading and ``TestEveryCommandHasItsOwnSection`` requires every
    command to have a section of its own, but neither pairs the two: two
    sections could trade headings - each command still documented, each flag
    still named, each section still single-tool - while the reference named the
    wrong tool above each grammar block.  These tests own that question.
    """

    def test_every_section_heading_names_the_tool_it_documents(self) -> None:
        docs = _documented_commands()
        assert not docs.problems, "documentation the lock cannot read:\n" + "\n".join(
            docs.problems
        )
        manifest = _manifest_names_by_command()
        wrong: list[str] = []

        for line, record in sorted(docs.sections.items()):
            expected = _expected_heading(record, manifest)
            if expected is None:
                continue  # a mixed section; the ownership lock already names it
            problem = _heading_problem(record.title, expected, manifest)
            if problem is None:
                continue
            from_manifest = (
                len(record.families) == 1 and next(iter(record.families)) in manifest
            )
            source = "the tool manifest" if from_manifest else "its own command name"
            wrong.append(
                f"line {line}: the section documenting "
                f"{', '.join(sorted(record.commands))} is headed "
                f"{record.title!r} but {source} names it {expected!r} - "
                f"{problem}"
            )

        assert not wrong, (
            "sections whose heading does not name the tool they document "
            "(retitle each `### …` from the tool manifest, not from a sibling "
            "section):\n" + "\n".join(wrong)
        )

    def test_the_heading_scan_cannot_pass_vacuously(self) -> None:
        docs = _documented_commands()
        manifest = _manifest_names_by_command()
        expected_titles = {
            line: expected
            for line, record in docs.sections.items()
            if (expected := _expected_heading(record, manifest)) is not None
        }
        manifest_bound = {
            line
            for line, record in docs.sections.items()
            if line in expected_titles
            and len(record.families) == 1
            and next(iter(record.families)) in manifest
        }
        fallback = sorted(set(expected_titles) - manifest_bound)
        # What each command's heading is *derived* from, so the pins below test
        # the derivation (manifest lookup, then command name) rather than the
        # document's own wording, which may carry a clarifying suffix.
        by_command = {
            command: expected_titles[line]
            for line, record in docs.sections.items()
            if line in expected_titles
            for command in record.commands
        }
        headings = {line: record.title for line, record in docs.sections.items()}
        bpm_line = next(
            line for line, record in docs.sections.items() if "bpm" in record.commands
        )

        assert not docs.problems, "\n".join(docs.problems)
        assert len(manifest) >= 27, (
            f"only {len(manifest)} tools declare a CLI command, so the heading "
            "check reads almost nothing from the manifest"
        )
        assert len(manifest_bound) >= 29, (
            f"only {len(manifest_bound)} headings are tied to the manifest: "
            f"{sorted(manifest_bound)}"
        )
        assert len(fallback) >= 5, (
            "the suite's own commands (doctor, plugins and the three cue "
            f"sub-commands) are no longer headed by their command name: {fallback}"
        )
        assert by_command.get("bpm") == "BPM Analyzer", (
            "the BPM section's expected heading no longer reads from the "
            f"manifest: {by_command.get('bpm')!r}"
        )
        assert by_command.get("stats") == "Library Statistics Dashboard", (
            "the library statistics section lost the manifest's own display "
            f"name: {by_command.get('stats')!r}"
        )
        assert by_command.get("denoise") == "ML Denoiser", (
            "ML Denoiser is the manifest name that shares no word with its "
            f"command; it now derives as {by_command.get('denoise')!r}"
        )
        assert by_command.get("cue parse") == "cue parse", (
            "a section documenting no manifest tool must be headed by its own "
            f"command name, not the group: {by_command.get('cue parse')!r}"
        )
        assert by_command.get("doctor") == "doctor", (
            "the suite's own doctor command must derive its heading from its "
            f"command name: {by_command.get('doctor')!r}"
        )
        assert _normalise_heading(headings[bpm_line]).startswith("bpm analyzer"), (
            "the BPM section's heading no longer opens with the manifest's "
            f"name: {headings[bpm_line]!r}"
        )


class TestStageGroupsMatchTheManifestCategory:
    """A tool's section sits inside the stage its manifest category names.

    The reference groups its tool sections into stages (``## ENRICH commands``,
    ``## REFINERY command``, ``## UTIL commands``) and the manifest gives every
    tool a ``category``, but nothing compared the two: a tool could be filed
    under the wrong stage - or change category in the manifest - while every
    other lock stayed green, because stage headings are prose.  These tests own
    that question.
    """

    def test_every_tool_sits_under_its_manifest_category(self) -> None:
        parsed = _parse_document()
        docs = _documented_commands()
        assert not docs.problems, "documentation the lock cannot read:\n" + "\n".join(
            docs.problems
        )
        categories = _manifest_categories_by_command()
        wrong: list[str] = []

        for line, record in sorted(docs.sections.items()):
            command = _manifest_command(record, categories)
            if command is None:
                continue
            stage = _stage_for(parsed, line)
            if stage is None:
                wrong.append(
                    f"line {line}: {command!r} ({record.title}) sits outside "
                    "every stage group; put it under the `## …` stage its "
                    f"manifest category ({categories[command]!r}) names"
                )
                continue
            word = stage.title.split()[0] if stage.title.split() else ""
            if not _stage_word_matches_category(word, categories[command]):
                wrong.append(
                    f"line {line}: {command!r} ({record.title}) sits under "
                    f"'## {stage.title}' but the manifest puts it in the "
                    f"{categories[command]!r} category - move the section, or "
                    "fix the category in the tool manifest"
                )

        assert not wrong, "tool sections filed under the wrong stage:\n" + "\n".join(
            wrong
        )

    def test_each_category_is_documented_under_one_stage(self) -> None:
        """A category split across two stages files its own tools apart."""
        parsed = _parse_document()
        categories = _manifest_categories_by_command()
        seen: dict[str, set[str]] = {}

        for line, record in _documented_commands().sections.items():
            command = _manifest_command(record, categories)
            if command is None:
                continue
            stage = _stage_for(parsed, line)
            if stage is None:
                continue  # the per-tool test already names this one
            seen.setdefault(categories[command], set()).add(stage.title)

        split = {
            category: sorted(titles)
            for category, titles in seen.items()
            if len(titles) > 1
        }
        assert not split, (
            "these manifest categories are documented under more than one "
            "stage group:\n"
            + "\n".join(f"{c}: {titles}" for c, titles in sorted(split.items()))
        )

    def test_the_stage_scan_cannot_pass_vacuously(self) -> None:
        from audio_suite_shared.tool_plugin import get_registry

        parsed = _parse_document()
        docs = _documented_commands()
        categories = _manifest_categories_by_command()
        stages = _stage_headings(parsed)
        by_category = Counter(
            categories[command]
            for _line, record in docs.sections.items()
            if (command := _manifest_command(record, categories)) is not None
        )
        expected = Counter(
            manifest.category
            for manifest in get_registry().first_party
            if manifest.cli_command
        )
        matched = {
            category
            for category in set(expected)
            for stage in stages
            if stage.title.split()
            and _stage_word_matches_category(stage.title.split()[0], category)
        }

        assert not docs.problems, "\n".join(docs.problems)
        assert len(stages) >= 3, (
            f"only {len(stages)} stage groups found: "
            f"{sorted(stage.title for stage in stages)}"
        )
        assert by_category == expected, (
            "the tool sections per category no longer match the manifest, so "
            f"the scan did not see them all: {dict(by_category)} vs "
            f"{dict(expected)}"
        )
        assert matched == set(expected), (
            "not every manifest category has a stage group whose heading names "
            f"it: {sorted(matched)} vs {sorted(set(expected))}"
        )
        # The converse - one stage never holding two categories - follows from
        # the per-tool match only while no category name is a truncation of
        # another; pin that, so a future category must reconsider this rule.
        names = set(expected)
        assert not [
            (a, b) for a in names for b in names if a != b and b.startswith(a)
        ], (
            "one manifest category name is now a truncation of another, so a "
            "single stage heading could satisfy both"
        )

"""Locks for the factual claims a user guide makes about the code.

A guide is the product's only description of behaviour, and nothing else reads
what it claims: the renderer copies the prose, and the hygiene tests only check
that the `.docx` matches its source. Two sweeps (functional backlog D18/D19) found
real drift that had survived several releases, so the claim classes those sweeps
could check mechanically are locked here:

1. **Format counts** - "nine suite audio formats" while ``SUPPORTED_EXTENSIONS``
   holds fourteen.
2. **Worker counts** - a fixed "four worker slots" while every tool's grid is
   sized from the machine's CPU count (``DEFAULT_MAX_WORKERS``).
3. **Flags** - a documented ``--flag`` the CLI does not define.
4. **Status tokens** - a quoted ``[TAGGED]``-style marker the code never prints.
5. **Artifact names** - a log file, sidecar or export name the code never writes.

Each check asserts its own non-vacuity, so a mis-scoped scan fails instead of
passing on an empty set. Deliberate exceptions are listed with their reason and
must still match a real claim, so a stale exemption fails too.

What stays a reviewer's job (``AGENTS.md``, *User Guides Follow the Change*):
everything a scanner cannot see - what a step does, in what order, and with what
effect on the audio.

Changed in 2.1.7: new - it locks the claim classes the D18/D19 sweeps found drift
in, so a guide that states a stale format count, worker count, flag, status
token or artifact name fails here instead of waiting for a reader to notice.
"""

from __future__ import annotations

import re
from pathlib import Path

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.constants import MAX_WORKERS_CEILING

ROOT = Path(__file__).resolve().parents[1]
GUIDES_DIR = ROOT / "documentation" / "user_guides"
GUIDES = sorted(GUIDES_DIR.rglob("*.md"))
SOURCE = [
    path
    for path in ROOT.rglob("*.py")
    if not {".venv", ".git", "build", "dist", "site-packages"} & set(path.parts)
]
CODE = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in SOURCE)

NUMBER_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
}
SUPPORTED_COUNT = len(SUPPORTED_EXTENSIONS)

FORMAT_CLAIM = re.compile(
    r"\b(" + "|".join(NUMBER_WORDS) + r")\b"
    r"(?:\s+(?:suite|shared|supported|audio|file|input|output|read|write|"
    r"and|or)){0,4}\s+"
    r"(formats|containers|extensions)\b",
    re.IGNORECASE,
)

#: A count followed by a worker/slot noun. "one worker per logical CPU" is a
#: rate, not a fixed count, so the pattern requires the noun to end the phrase.
WORKER_CLAIM = re.compile(
    r"\b(" + "|".join(NUMBER_WORDS) + r"|\d+)\s*[- ]\s*"
    r"(worker|slot)s?(?!\s+per\b)(?![- ]?per\b)",
    re.IGNORECASE,
)

#: Phrases that legitimately qualify a worker count as a ceiling rather than a
#: machine-dependent value.
CAP_QUALIFIERS = ("at most", "capped", "up to", "maximum of", "no more than")

FLAG = re.compile(r"`(--[a-z][a-z0-9-]+)")
STATUS = re.compile(r"(?<![\w\[])\[[A-Z][A-Z0-9 _/-]{1,24}\]")
ARTIFACT = re.compile(r"`([\w./\\-]+\.(?:txt|log|json|csv|m3u8?|db))`")

#: guide file name -> {number word: why that format count is a deliberate subset}.
SUBSET_FORMAT_CLAIMS: dict[str, dict[str, str]] = {
    "Audio_Normalizer_User_Guide.md": {
        "seven": (
            "the normaliser re-encodes only the seven extensions its codec table "
            "carries; every other format is rejected, and the guide says so"
        ),
    },
    "Metadata_Scrubber_User_Guide.md": {
        "five": "the containers added in 2.1.7, named as a subset of the shared set",
    },
}

#: Bracket tokens that are CLI usage placeholders, not status markers the tool
#: prints.
NOT_STATUS_TOKENS = {"[OPTIONS]"}

#: guide file name -> artifact name -> reason the code does not name it.
NOT_IN_CODE_ARTIFACTS: dict[str, dict[str, str]] = {}


def guide_lines() -> list[tuple[Path, int, str]]:
    """Return every (guide, line number, line) across the authored guides."""
    lines: list[tuple[Path, int, str]] = []
    for guide in GUIDES:
        text = guide.read_text(encoding="utf-8")
        lines.extend((guide, n, line) for n, line in enumerate(text.splitlines(), 1))
    return lines


def format_claims() -> list[tuple[Path, int, str, int, str]]:
    """Return every (guide, line, number word, count, line text) format claim."""
    found: list[tuple[Path, int, str, int, str]] = []
    for guide, number, line in guide_lines():
        for match in FORMAT_CLAIM.finditer(line):
            word = match.group(1).lower()
            found.append((guide, number, word, NUMBER_WORDS[word], line))
    return found


def worker_claims() -> list[tuple[Path, int, str, str]]:
    """Return every (guide, line, matched number, sentence) fixed worker claim."""
    found: list[tuple[Path, int, str, str]] = []
    for guide, number, line in guide_lines():
        for match in WORKER_CLAIM.finditer(line):
            start = line.rfind(".", 0, match.start()) + 1
            end = line.find(".", match.start())
            sentence = line[start : end if end != -1 else len(line)]
            found.append((guide, number, match.group(1).lower(), sentence))
    return found


def _value(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token.lower())


def test_format_counts_match_the_supported_set() -> None:
    """Every stated suite format count equals what the code supports."""
    claims = format_claims()
    assert claims, "no guide states a format count; the lock would pass vacuously"
    assert SUPPORTED_COUNT in {count for _, _, _, count, _ in claims}

    wrong = [
        f"{guide.relative_to(ROOT)}:{number}: says {count}, "
        f"SUPPORTED_EXTENSIONS holds {SUPPORTED_COUNT}\n  {line.strip()}"
        for guide, number, word, count, line in claims
        if count != SUPPORTED_COUNT
        and word not in SUBSET_FORMAT_CLAIMS.get(guide.name, {})
    ]
    assert not wrong, "\n".join(wrong)


def test_subset_format_exemptions_still_match_a_claim() -> None:
    """A stale exemption would silently permit a wrong count."""
    present = {(guide.name, word) for guide, _, word, _, _ in format_claims()}
    unmatched = [
        f"{name}: exemption for {word!r} no longer matches any claim"
        for name, words in SUBSET_FORMAT_CLAIMS.items()
        for word in words
        if (name, word) not in present
    ]
    assert not unmatched, "\n".join(unmatched)


def test_no_guide_states_a_fixed_worker_count() -> None:
    """The slot grid follows the machine, so a fixed count is always wrong."""
    claims = worker_claims()
    assert claims, "no guide states a worker count; the lock would pass vacuously"

    wrong = [
        f"{guide.relative_to(ROOT)}:{number}: states {token!r} workers/slots "
        f"without a ceiling qualifier\n  {sentence.strip()}"
        for guide, number, token, sentence in claims
        if not any(qualifier in sentence.lower() for qualifier in CAP_QUALIFIERS)
        or _value(token) != MAX_WORKERS_CEILING
    ]
    assert not wrong, "\n".join(wrong)


def test_documented_flags_exist_in_the_code() -> None:
    """A guide must not document a flag the CLI stopped defining."""
    found = {
        flag for _guide, _number, line in guide_lines() for flag in FLAG.findall(line)
    }
    assert len(found) >= 50, f"only {len(found)} flags found - the scan is broken"

    missing = sorted(flag for flag in found if flag not in CODE)
    assert not missing, (
        "these flags are documented but do not exist in the code:\n  "
        + ("\n  ".join(missing))
    )


def test_quoted_status_tokens_exist_in_the_code() -> None:
    """Status markers a guide quotes are the ones the tools actually print."""
    found = {
        token
        for _guide, _number, line in guide_lines()
        for token in STATUS.findall(line)
    } - NOT_STATUS_TOKENS
    assert len(found) >= 5, f"only {len(found)} status tokens found - scan is broken"

    missing = sorted(token for token in found if token not in CODE)
    assert not missing, "these status tokens are documented but never printed:\n  " + (
        "\n  ".join(missing)
    )


def test_quoted_artifact_names_exist_in_the_code() -> None:
    """A log, sidecar or export a guide names is a name the code writes."""
    found = {
        Path(name.replace("\\", "/")).name
        for _guide, _number, line in guide_lines()
        for name in ARTIFACT.findall(line)
    }
    assert len(found) >= 3, f"only {len(found)} artifact names found - scan is broken"

    exempt = {name for names in NOT_IN_CODE_ARTIFACTS.values() for name in names}
    missing = sorted(name for name in found if name not in CODE and name not in exempt)
    assert not missing, "these artifact names are documented but never written:\n  " + (
        "\n  ".join(missing)
    )


def test_artifact_exemptions_still_match_a_claim() -> None:
    """A stale artifact exemption would hide a renamed file."""
    assert not NOT_IN_CODE_ARTIFACTS, (
        "the artifact exemption map is intentionally empty; add an entry with a "
        "reason only when a guide legitimately names something the code does not"
    )

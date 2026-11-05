# PLAN — suggestions for future consideration

**Status:** `[ ]` **OPEN — living list, parked for the future.** Drafted
2026-11-05 during the `2.4.3` WP-10 tail (`PLAN_2026-11-03_2.4.3_structure.md`)
and parked the same day: S-2..S-5 are future consideration only and are not
worked, scheduled or promoted during `2.4.3`.

**Owner:** unassigned. Nothing here is scheduled, sized into a release, or
blocking anything.

**Governing scope:** none. This file exists so that ideas raised while executing
one plan have somewhere to live that is not "forgotten in a chat transcript" and
not "smuggled into a plan whose scope was agreed without them".

**Read with:** `AGENTS.md`, *Plan Governance*.

---

## 1. What this file is, and is not

- **Not a governing plan.** No item here authorises a commit, a release or a
  change to any other plan. The plan that owns the modules being touched stays
  the governing plan (`AGENTS.md`, *Plan Governance*).
- **Not a defect register.** A defect found during any session is fixed in the
  change that found it (`AGENTS.md`, *Defects and failing checks*). If an entry
  here describes wrong output rather than an absent nicety, it is filed wrong
  and must move to the governing plan immediately.
- **Not a promise.** An entry that is never picked up is a normal outcome; the
  list exists to be read, not to be emptied.
- **Promotion is explicit.** When an idea is taken up, it is copied into the
  plan that would own it (or into a new plan) as a real work item with that
  plan's ID scheme, and the row here becomes `PROMOTED -> <plan> <ID>`. The
  original row stays, because "we considered this and here is where it went" is
  the record a future reader needs.
- **Dropping is recorded, not deleted.** An idea judged not worth doing becomes
  `DROPPED (<reason>)`. A deleted row is re-proposed six months later by someone
  who never saw the reasoning.
- **This file adds no gate.** It is Markdown, so `tests/test_release_notes.py`
  already exempts it (`.md` is in `EXCEPTION_SUFFIXES`), and no test enumerates
  plan filenames. Keeping it that way is deliberate: a suggestions list that
  drags a lock behind it stops being cheap to add to.

## 2. How an entry is written

Every row names, in this order:

| Field | What it must contain |
|---|---|
| `ID` | `S-<n>`, assigned once, never reused. |
| `Suggestion` | One sentence, imperative, naming the outcome rather than the files. |
| `Origin` | The commit, measurement or decision that produced the idea. Without this a reader cannot judge the entry without replaying the session. |
| `Why it is worth it` | The failure class it closes. "Nice to have" is not a reason. |
| `Cost` | Minutes / an hour / a day, plus anything that makes it risky (network, a new dependency, a fixture). |
| `Attach to` | The plan or module that would own it if promoted. |

An entry with no `Origin` and no named failure class is a preference, not a
suggestion, and does not belong here.

## 3. Open entries

| ID | Suggestion | Origin | Why it is worth it | Cost | Attach to |
|---|---|---|---|---|---|
| S-1 **PROMOTED** -> `PLAN_2026-11-03_2.4.3_structure.md` C-I6a | Check the wheel against the declared `package-data` list in both directions. | `c8e4274`, D-30 (the probe that emptied the entry) | The current test hard-codes two names. A declaration naming a deleted or renamed file ships nothing and nothing fails; a new shipped file nobody declares is invisible until a user's install breaks. | ~30 min: parse `pyproject.toml` with `tomllib`, assert every declared name is in the wheel, and assert no undeclared non-`.py` file sits in the package root. | `tests/test_py_typed.py`, or a new root `tests/test_packaging.py`. |
| S-2 | Type-check a consumer against the **installed** wheel, not the source tree. | D-29 / D-30 | `typing_consumer/consumer.py` imports from the checkout, so nothing proves the distribution a user installs is typed. A wheel can ship `py.typed` and still omit a module the consumer imports. | ~1 h, with a real risk: `pip install --no-index --no-deps --target <tmp>` must stay offline and deterministic, and mypy resolution must be pinned so the source tree cannot win over the installed copy. | `tests/test_py_typed.py::TestTheConsumerSeesAnnotations`. |
| S-3 | Document `typing_consumer/`. | D-29 | It is a top-level directory whose only explanation today is a test docstring and a plan row. The next reader who finds a directory nothing imports will reasonably want to delete it. | Minutes: one short paragraph in the developer/architecture page of `documentation/docs/`. | `documentation/docs/`. |
| S-4 | Assert the built **sdist** carries the same package data. | D-30 | `package-data` feeds the wheel and the sdist, but the sdist is assembled by different include rules. `cli_schema.json` is loaded at CLI import, so an sdist install missing it fails on first use, not at install time. | ~15 min: reuse the existing staging copy, call `build_sdist`, read the tarball. | `tests/test_py_typed.py`. |
| S-5 | Assert the staging copy's exclusions from the **outcome**, not the filter list. | D-30 (`_build_wheel()`'s ignore patterns) | The build filters `__pycache__`, `*.pyc`, `*.pyo` by name. A new build artefact directory in the package would be copied and shipped silently, because a filter only excludes what it was told about. | Minutes: assert no namelist entry contains `__pycache__` or ends in `.pyc`. | `tests/test_py_typed.py`. |

## 4. Detail

### S-1 — declared vs shipped, in both directions

The probe recorded in D-30 removed the `[tool.setuptools.package-data]` entry and
measured what changed: `py.typed` still shipped (setuptools copies it on its
own), `cli_schema.json` did not. That measurement is what makes the JSON
assertion meaningful, and it is also the shape of the gap this entry closes. The
test knows two names by hand; the declaration is the contract. Reading the
declaration at test time means a future `package-data` entry arrives with its
check already in place, and a stale entry fails loudly instead of shipping an
install that is missing a file its own configuration promises.

The second half (no undeclared non-`.py` file in the package root) needs one
deliberate scope decision before it is written: which extensions count as data.
Named here so that decision happens in the open rather than inside a test.

### S-2 — the installed-wheel consumer

D-29 chose a consumer fixture outside `tests/` so that bare `mypy .` would
actually type-check it; that solved the "is the fixture checked at all" problem.
It did not solve the "is the installed distribution typed" problem, because
`MYPYPATH` points at the checkout. Installing the wheel into a temporary target
directory and re-running the same consumer would prove the PEP 561 claim from
the position a downstream user is actually in.

The risk is stated up front because it is the reason this is a suggestion and
not a fix: an install inside a test needs no network, no isolation and no
writes outside the temp directory, and mypy's module precedence has to be
verified rather than assumed. If those cannot be met cleanly, the honest answer
is to keep the source-tree check and record the limit, which is what D-30
already does for the marker.

### S-3 — naming the fixture

`typing_consumer/` joins the small set of top-level directories that are not
installable packages. Every other one is explained in the documentation tree;
this one is explained only where the test and the plan happen to say so. A
reader arriving cold sees an orphan. One paragraph fixes it.

### S-4 — the sdist

Cheap, and it closes a real failure mode: `pip install` from an sdist is a
supported path, `cli_schema.json` is read at import time, and the packaging
rules that decide sdist contents are not the ones that decide wheel contents.
Since the staging helper already exists, the check is small.

### S-5 — filters become outcomes

The rule this entry is an instance of appears all over `AGENTS.md`: assert what
the artefact contains, never that the code meant to filter something. A build
copy with a name-based ignore list is a filter; a namelist assertion is an
outcome. Three lines, and it fails the day setuptools starts including
`__pycache__` inside a different directory name.

## 5. Decision Log

| # | Date | Decision | Evidence |
|---|---|---|---|
| D-1 | 2026-11-05 | This file is created as a holding pen at the owner's instruction, populated with the suggestions raised by the `2.4.3` WP-10 tail (S-1..S-5). It is deliberately not linked from the release gate, not registered in any file list, and holds no release-blocking item. | user instruction, 2026-11-05; `c8e4274` |
| D-2 | 2026-11-05 | Entries are written with an `Origin` and a named failure class, and are promoted or dropped explicitly rather than deleted. | Without an origin, a reader cannot judge an entry without replaying a session; without a recorded drop, the same idea is re-litigated. |
| D-4 | 2026-11-05 | **The list is parked for the future.** The owner asked to stow the remaining suggestions and return to the plan, so S-2..S-5 stay open with no owner and no target release; promotion still requires an explicit edit in the governing plan. | user instruction, 2026-11-05 |
| D-3 | 2026-11-05 | **S-1 is promoted** into the governing plan as C-I6a and implemented there (`12e5524` lists it; the work is 2.4.3's D-31). The row above stays for the record; its scope limit (package root only, not subpackages) travels with the implementation. | 2.4.3 D-31 |

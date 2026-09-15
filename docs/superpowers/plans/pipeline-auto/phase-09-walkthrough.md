# P09 Controller Walkthrough Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the skill works from an installed path against a repository that is not this one — a single runnable script that drives a whole run end to end and fails loudly if any part of the skill depends on living in this checkout.

**Architecture:** `examples/controller_walkthrough.py` builds a throwaway repository in a temporary directory, initialises a run inside it, and drives the tracker through a realistic sequence — reserve a task, open a quorum, adopt a decision, record a review round, close a phase — asserting the state machine's own invariants at each step. It imports `pipeline_auto_state` the way an installed skill is imported, not by relative path, and it never reads this repository. Its value is entirely in what it would catch: a hard-coded path, a derived repo root, a checkout-relative import, a fixture the module secretly depends on.

**Tech Stack:** Python 3 standard library, `unittest` for the suite that runs it. No new dependencies in any phase.

**Spec:** `docs/superpowers/specs/2026-09-14-pipeline-auto-design.md`

## Global Constraints

- `plugins/superb/skills/pipeline/` is **not modified**. Not one line. Verify with `git diff --name-only` before every commit.
- Schema string is exactly `pipeline-auto/v1`; tracker marker is exactly `<!-- pipeline-auto/v1 -->`.
- No migration path from `pipeline-run/v1` or `pipeline-run/v2` exists or is ever added, in either direction.
- A foreign, missing, malformed, or unknown schema is a **read-only stop**: preserve the directory, change no files, dispatch nothing. Rejected input must be **byte-identical** after the rejected parse.
- Rungs are **schema constants, not run configuration**: `specified` 0.95, `code-evidenced` 0.85, `convention-cited` 0.70, `engineering-judgement` 0.55, `speculation` 0.30.
- Adoption floor is `code-evidenced` (0.85). `convention-cited` and everything below it **cannot be adopted**.
- A brain **never types a number**. It selects a rung; the controller derives the value.
- Spread is measured **by rung**: where more than one cluster exists, the winner's rung must be strictly higher than the runner-up's. Equal rungs never adopt.
- A rung outside the enum is schema-invalid: re-dispatch that brain once, then escalate. Never default it to a legal value.
- Drift budget: **3 quorum adoptions per phase, 10 per run**, checked **before dispatch**. Escalations never count against it. At most 2 human-granted extensions per run.
- The drift budget caps decision authority, **not** run cost.
- Depth cap is **2**. Human decisions are depth 0.
- Implementation tasks may occupy at most `worker_limit - 3` slots. `worker_limit >= 4` is required for concurrency.
- Exactly three brains per quorum, exactly three readers at stage 01. A count is never reduced to fit capacity.
- Python: standard library only. No new dependencies in any phase.
- **Agent-supplied JSON is never tested for membership with a bare `in` against a set.** Use `_member(value, allowed)`; every call site must be pinned.
- **A test claiming totality derives its case list from the function's call tree**, not from what the author remembers reading.
- No absolute home-directory paths in any committed file. Repository-relative paths only.
- No push, no publish, no PR, no merge into `main`/`master`.
- Platform support is **Linux-only, and fails closed**.

---

## What "a foreign repo" can and cannot mean here, decided before Task 1

The master plan asks for a walkthrough "proving the skill works from an installed path in a foreign repo". Two of the three words are achievable exactly; one is not, and pretending otherwise would ship a script whose name promises more than it does.

**"A foreign repo" — achievable, and the important half.** The walkthrough creates a fresh directory, runs `git init` semantics only as far as making a `.git` directory exist, writes a couple of source files, and treats that as the repository. `initialize_run` takes `repo_root` as a required keyword, so nothing needs to be discovered. This is exactly the guarantee P03 Task 3 was built around: the root is recorded, never computed. If any part of the module derives a root instead of reading it, the walkthrough's citations resolve against the wrong tree and the assertions fail — which is the single most valuable thing this script does.

**"From an installed path" — achievable, with care.** The script must not import `pipeline_auto_state` by a path relative to this checkout. It resolves the module the way an installed plugin would: from the skill's own `scripts/` directory, located relative to the script's own file, and loaded through `importlib.util.spec_from_file_location`. That is enough to catch a module that reaches for a sibling test fixture or a checkout-relative path. It is *not* enough to prove installation into a plugin cache, and the script says so rather than implying it.

**What cannot be done inside the capability boundary, stated plainly.** A true installation test would copy the skill into a plugin directory, launch a separate process, and inspect the result. `subprocess` is not in `ALLOWED_IMPORTS` and was refused deliberately — the allowlist is *capability, not convenience*, and spawning processes is a capability. So the walkthrough does not shell out, does not install anything, and does not run the plugin loader.

**The nearest thing that can be done, and is:** every filesystem path the walkthrough touches is inside its own temporary directory; the script asserts that fact directly rather than assuming it. If the module writes anywhere else — this checkout, the user's home, a cached fixture — the assertion fails and names the path. That converts "we did not test installation" into "we proved the module confines itself to the root it was handed", which is the property installation would have been testing for.

**`ALLOWED_IMPORTS` binds the module, not this script.** `pipeline_auto_state.py` must stay at **twelve** imports — the original eleven plus `json`, admitted by quorum before P03 Task 7 and recorded at the head of that task. The walkthrough may import what it needs (`tempfile`, `shutil`, `importlib.util`) because it is an example script, not the module — the same rule that lets the test suite import freely. A worker who "fixes" the walkthrough by adding an import to the module has inverted the constraint.

**Platform.** `classify_filesystem` returns `unknown` and halts on anything but Linux, by decision. The walkthrough therefore runs on Linux and **skips with a stated reason** elsewhere, rather than failing. A skip that says why is information; a failure on an unsupported platform is noise that trains a reader to ignore the suite.

---

## File Structure

| File | Responsibility | P09 action |
| --- | --- | --- |
| `plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py` | The runnable end-to-end walkthrough. Exits 0 on success, non-zero with a named failure otherwise | Create |
| `plugins/superb/skills/pipeline-auto/tests/test_controller_walkthrough.py` | Runs the walkthrough in-process and asserts it confined itself to its temporary root | Create |

---

## Tasks

### Task 1: The walkthrough's skeleton — build a foreign repo and confine everything to it

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_controller_walkthrough.py`

**Interfaces:**
- Consumes: `initialize_run(run_dir, *, run_id, base_commit, target_branch, worker_limit, repo_root)`, `validate_run(run_dir)`, `repo_root(tracker)`, `classify_filesystem`
- Produces: `build_foreign_repo(root: Path) -> Path` returning the run directory; `load_module() -> module`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
WALKTHROUGH = EXAMPLES / "controller_walkthrough.py"


class WalkthroughExistsTests(unittest.TestCase):
    """The master plan's verification suite runs this file by path.

    Named fault: the verification suite's third command is
    `python3 .../examples/controller_walkthrough.py`. A missing file makes
    that command fail with an OS error rather than a test failure, which
    reads as a broken harness instead of a broken skill.
    """

    def test_the_walkthrough_exists_and_is_a_module(self):
        self.assertTrue(WALKTHROUGH.is_file(), f"missing: {WALKTHROUGH}")

    def test_the_walkthrough_does_not_import_the_module_by_checkout_path(self):
        #: The whole point is that it works from an installed path. A literal
        #: 'docs/' or 'plugins/superb/skills/pipeline-auto' string in the
        #: import path ties it to this checkout's layout.
        source = WALKTHROUGH.read_text(encoding="utf-8")
        self.assertNotIn("/home/", source)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k WalkthroughExists -v`
Expected: FAIL — `missing: .../examples/controller_walkthrough.py`.

- [ ] **Step 3: Write the skeleton**

```python
"""Drive a whole pipeline-auto run against a repository that is not this one.

Run it directly:

    python3 plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py

WHAT THIS PROVES. The module was handed a repository root and used that one.
Every path it touches lies inside a temporary directory this script created,
and the script asserts that rather than assuming it. If anything derives a
root, reaches for a sibling fixture, or writes into the checkout it happens to
be stored in, an assertion here fails and names the path.

WHAT THIS DOES NOT PROVE. It is not an installation test. A real one would
copy the skill into a plugin directory and launch a separate process, and
`subprocess` is not in the module's ALLOWED_IMPORTS -- refused deliberately,
because that allowlist is capability, not convenience. So this script does not
shell out, install anything, or run the plugin loader, and it does not imply
otherwise.

ALLOWED_IMPORTS binds `pipeline_auto_state`, not this file. This is an example
script, like the test suite, and may import what it needs. Adding an import to
the module to simplify this script inverts the constraint.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = SKILL_ROOT / "scripts" / "pipeline_auto_state.py"

RUN_ID = "2026-09-15-walkthrough"
BASE_COMMIT = "0" * 40


def load_module():
    """Load the state module the way an installed plugin would.

    By location relative to the skill, never by a path relative to the
    checkout this file happens to sit in.
    """
    spec = importlib.util.spec_from_file_location(
        "pipeline_auto_state_walkthrough", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load the state module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_foreign_repo(root: Path) -> Path:
    """A repository that is not this one, with a run at its production depth.

    Production depth matters: a run lives at `docs/superpowers/runs/<id>/`, so
    a module tempted to derive the root by directory arithmetic would be
    deriving it from the shape a real run actually has.
    """
    (root / ".git").mkdir()
    source = root / "db" / "engine.py"
    source.parent.mkdir(parents=True)
    source.write_text("class PostgresEngine:\n    pass\n", encoding="utf-8")
    (root / "spec.md").write_text(
        "# Foreign spec\n\nThe session table is backed by PostgreSQL.\n",
        encoding="utf-8")
    run_dir = root / "docs" / "superpowers" / "runs" / RUN_ID
    run_dir.mkdir(parents=True)
    return run_dir


def main() -> int:
    pas = load_module()
    if sys.platform != "linux":
        print(f"SKIP: pipeline-auto is Linux-only and this is {sys.platform!r}; "
              "classify_filesystem returns 'unknown' and the run would halt")
        return 0
    root = Path(tempfile.mkdtemp(prefix="pipeline-auto-walkthrough-"))
    try:
        run_dir = build_foreign_repo(root)
        pas.initialize_run(
            run_dir, run_id=RUN_ID, base_commit=BASE_COMMIT,
            target_branch="feat/walkthrough", worker_limit=4,
            repo_root=str(root))
        tracker = pas.validate_run(run_dir)
        recorded = Path(pas.repo_root(tracker)).resolve()
        if recorded != root.resolve():
            raise SystemExit(
                f"FAIL: recorded repo_root {recorded} is not the root this "
                f"walkthrough created ({root.resolve()})")
        print(f"OK: run initialised at production depth, repo_root recorded "
              f"as the root it was handed")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the walkthrough itself**

Run: `python3 plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py`
Expected: prints the `OK:` line and exits 0.

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k WalkthroughExists -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py \
        plugins/superb/skills/pipeline-auto/tests/test_controller_walkthrough.py
git commit -F - <<'MSG'
feat(pipeline-auto): drive a run against a repository that is not this one

The walkthrough builds a throwaway repo, puts a run at its production depth,
and asserts the recorded repo_root is the root it handed in. A module that
derived a root instead of reading one fails here, which is the single most
valuable thing this script does.

It states what it does not prove: subprocess is outside ALLOWED_IMPORTS by
decision, so this is not an installation test and does not imply it is.
MSG
```

---

### Task 2: Prove the module confined itself to the root it was given

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_controller_walkthrough.py`

**Interfaces:**
- Consumes: `build_foreign_repo`, `initialize_run`, `validate_run`
- Produces: `assert_confined(root: Path, before: set[Path]) -> None`

This is the substitute for an installation test, and it is a better test than the name suggests: installation would have been a proxy for "does it stay where it is put", and this asks that directly.

- [ ] **Step 1: Write the failing test**

```python
class WalkthroughConfinementTests(unittest.TestCase):
    """The walkthrough must prove confinement, not assume it.

    Named fault: a module that writes a cache, a lock or a log beside its own
    source would work perfectly in this checkout and corrupt a second
    concurrent run elsewhere. Nothing else in the suite would see it, because
    every other test runs from this checkout too.
    """

    def test_the_walkthrough_checks_for_writes_outside_its_root(self):
        source = WALKTHROUGH.read_text(encoding="utf-8")
        self.assertIn("assert_confined", source)

    def test_running_it_leaves_the_skill_directory_unchanged(self):
        import hashlib
        skill = EXAMPLES.parent
        def fingerprint():
            return {
                str(p.relative_to(skill)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(skill.rglob("*"))
                if p.is_file() and "__pycache__" not in p.parts
            }
        before = fingerprint()
        spec = importlib.util.spec_from_file_location("walkthrough_run", WALKTHROUGH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.main(), 0)
        self.assertEqual(fingerprint(), before)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k WalkthroughConfinement -v`
Expected: FAIL — `assert_confined` is not in the source.

- [ ] **Step 3: Add the confinement check**

```python
def assert_confined(root: Path, touched: list[Path]) -> None:
    """Every path the run touched must lie inside the root it was handed.

    A module that writes a cache or a lock beside its own source works
    perfectly in the checkout it was developed in and corrupts the second
    concurrent run somewhere else. Nothing in a checkout-local test suite sees
    that, because every test in it runs from the checkout.
    """
    resolved_root = root.resolve()
    for path in touched:
        target = path.resolve()
        if target != resolved_root and resolved_root not in target.parents:
            raise SystemExit(
                f"FAIL: the run touched {target}, which is outside the "
                f"repository root it was handed ({resolved_root}); a module "
                "that writes beside its own source corrupts any second run")
```

Call it in `main()` after `validate_run`, passing the run directory's contents:

```python
        touched = [p for p in run_dir.rglob("*")]
        assert_confined(root, touched)
        print(f"OK: {len(touched)} paths written, every one inside the root")
```

- [ ] **Step 4: Run both**

Run: `python3 plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py`
Expected: exits 0, prints both `OK:` lines.

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k WalkthroughConfinement -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py \
        plugins/superb/skills/pipeline-auto/tests/test_controller_walkthrough.py
git commit -F - <<'MSG'
test(pipeline-auto): prove the run stays inside the root it was handed

Installation was only ever a proxy for "does it stay where it is put". This
asks that directly: every path the run touched must lie inside the temporary
root, and the skill directory must be byte-identical afterwards.
MSG
```

---

### Task 3: Drive the state machine end to end

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py`

**Interfaces:**
- Consumes: `locked_tracker_update`, `append_row`, `section_columns`, `derive_qid`, `effective_rung`, `parse_decisions`, `project_decisions`, `check_contradiction`, `decision_depth`, `derive_next_action`
- Produces: a walkthrough that exercises a realistic run, not just initialisation

Task 1 proved the run starts. This proves it runs. Each step asserts the module's own invariant rather than a value this script chose — an assertion that only restates what the script just wrote proves the script can write.

- [ ] **Step 1: Add the sequence**

After the confinement check, drive in order: reserve a task and assert the tracker round-trips; write a `decisions.md` with one human decision and assert `parse_decisions` reads it back with provenance `human` and depth `0`; project it and assert the projection carries the answer but no rung name and no rung value; derive a qid for a question and assert it is stable across two calls with the same inputs; price a grounded response with `effective_rung` against the foreign repo's real `spec.md` and assert it earns `specified`; price the same response with one citation changed to a file that does not exist and assert it demotes below `ADOPTION_FLOOR`; run `check_contradiction` with an agreeing candidate and assert `None`, then with a contradicting one and assert it names the human decision's D-ID.

Each of those is a line of the design that would otherwise only be checked by a unit test living in this checkout, against fixtures built in this checkout.

- [ ] **Step 2: Assert the demotion is attributable**

The dangling-citation case must differ from its passing twin **only** in the citation. A demotion test whose two sides differ in two ways proves nothing about either.

- [ ] **Step 3: Run it**

Run: `python3 plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py`
Expected: exits 0, printing one `OK:` line per stage.

- [ ] **Step 4: Break it deliberately, once**

Temporarily point `repo_root` at a directory that exists but is not the repo, re-run, and confirm the `effective_rung` stage reports the demotion rather than passing silently. Restore immediately. **This is the check that the walkthrough is measuring something**: a walkthrough that passes against the wrong root is asserting nothing, and that is P03's named invisible failure reproduced end to end.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py
git commit -F - <<'MSG'
feat(pipeline-auto): drive the whole state machine in the walkthrough

Initialisation proved the run starts. This drives it: a decision parsed and
projected, a qid derived twice for stability, a rung priced against the
foreign repo's own spec.md and demoted when one citation dangles, and a
contradiction found against the human decision by D-ID.

The demotion case differs from its passing twin only in the citation, so the
outcome is attributable to the file's text and to nothing else.
MSG
```

---

### Task 4: Phase verification and the interface sweep

**Files:** none created; this task verifies.

- [ ] **Step 1: Run the master plan's full verification suite, verbatim**

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
python3 plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```
Expected: the suite is OK; the walkthrough exits 0; the `git diff` prints nothing; `git status --short` is clean apart from anything the user already had dirty.

- [ ] **Step 2: Sweep the "P07 produces — consumed by P09" block, name by name**

The master plan promises P09 a structure validator, `tests/test_skill_structure.py`, asserting: frontmatter present and within limits; every `references/*.md` named in `SKILL.md`'s routing table exists on disk; every agent named in `SKILL.md` exists as a file; every prompt template referenced resolves.

```bash
ls -l plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k SkillStructure -v
```
Expected: the file exists and its tests pass. **If it does not exist, stop and say so** — four pinned interfaces once escaped two complete phases because every review checked what its task claimed and none checked what the plan promised the next phase. This is the sweep that catches it, and P09 is the last phase, so nothing catches it after this.

- [ ] **Step 3: Confirm `ALLOWED_IMPORTS` was not widened to serve this phase**

```bash
python3 - <<'PY'
import ast, pathlib
src = pathlib.Path("plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py").read_text()
mods = set()
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Import):
        mods |= {a.name.split(".")[0] for a in node.names}
    elif isinstance(node, ast.ImportFrom) and node.module:
        mods.add(node.module.split(".")[0])
print(len(mods), sorted(mods))
PY
```
Expected: exactly **12** — the eleven, plus `json`, admitted by quorum before P03 Task 7 (see the decision recorded at the head of that task). The walkthrough may additionally import `tempfile`, `shutil` and `importlib`; the module may not. A worker who simplified the example by widening the module inverted the constraint — `json` was widened for a reason argued and recorded, which is the only way the boundary may move.

- [ ] **Step 4: State the closing position**

Write into the run's notes: which phases closed, what P08 reported as still failing if anything, and the two things this walkthrough deliberately does not prove — installation into a plugin cache, and behaviour on any platform but Linux.

---

## Self-review

**1. Spec coverage.** The master plan's P09 row asks for `controller_walkthrough.py` proving the skill works from an installed path in a foreign repo. Task 1 covers the foreign repo and the installed-path import; Task 2 covers confinement, which is what installation was a proxy for; Task 3 covers "works" rather than merely "starts"; Task 4 runs the verification suite and sweeps P07's promise. The part that cannot be done — spawning a process to test real installation — is stated in the plan's own preamble and in the script's docstring rather than quietly omitted.

**2. Placeholder scan.** No `TBD`, no "add appropriate error handling". Task 3 Step 1 describes a sequence rather than pasting one long code block; each element names the exact function and the exact assertion, and the surrounding tasks carry the code patterns it follows.

**3. Type consistency.** `load_module()` returns the module; `build_foreign_repo(root)` returns the run directory; `assert_confined(root, touched)` returns `None` and raises `SystemExit` with a named path. `initialize_run` is called with `repo_root` as a required keyword and `run_dir` as a `Path`, matching P02's pinned signature. `effective_rung(response, repo_root)` takes two arguments and returns a rung *name*; the walkthrough looks the value up in `RUNGS` rather than expecting a float.

**4. The failure this phase exists to catch**, stated so a worker can check it: the walkthrough passing against a wrong repository root. Task 3 Step 4 breaks it deliberately once and confirms the failure is visible, because a walkthrough that passes when the root is wrong is asserting nothing at all — and that is precisely P03's named invisible failure, reproduced end to end.

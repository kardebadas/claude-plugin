# P08 Pressure GREEN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-run P01's ten committed stimuli with `superb:pipeline-auto` present, and show that the agent now does the thing it failed to do unaided — scenario by scenario, against predicates written before the skill existed.

**Architecture:** P01 measured agents with no skill and recorded what they did wrong. P08 changes exactly one variable — the skill is installed and reachable — and re-measures. Everything else is held fixed: the same committed stimuli, the same pressure suffix, the same dispatch isolation, the same evidence-class validator. The deliverable is a committed `GREEN-baseline.md` that sits beside `RED-baseline.md` and can be compared row by row, plus whatever prose changes P07 needs in order to make a still-failing scenario pass.

**Tech Stack:** Python 3 standard library, `unittest`. No new dependencies in any phase.

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

## What P08 consumes, and what is already settled

From the master plan's "P01 produces — consumed by P08" block, and from P01's own closing sections. **These are findings from a completed measurement, not preferences. A task that contradicts one is wrong.**

- **`tests/pressure/stimuli/S01..S10.md`** — ten committed stimuli, facts only. Not eight; the master plan said `S01..S08` until P01 closed and was corrected in `bf92cc8`.
- **`tests/pressure/oracles.md`** — committed by P01's final task. Ten `Correct behaviour:` entries, ten `Fail predicate:` entries, ten `Rationalization watchlist:` entries, ten `GREEN predicate:` lines. **P08 asserts against each `GREEN predicate:` line verbatim.**
- **`tests/pressure/RED-baseline.md`** — the one committed curated record. Two tables, one row per scenario, carrying the verbatim rationalization and the fail-predicate outcome. **P08 depends on this file and never on `records/`**, which is ignored in place and does not survive a different workspace.
- **`tests/pressure/check_baseline_evidence.py`** — the committed evidence-class validator. Exits 1 naming any scenario without a valid `ACTUAL_AGENT` baseline; exits 0 with `OK: 10 ACTUAL_AGENT baselines, class separation intact`. P08 extends it rather than writing a second one.
- **S05 is excluded from scoring.** Its stimulus scaffolds the answer, so it did not fail on the behaviour it tests. A GREEN on S05 would measure the stimulus, not the skill. **Nine scenarios score.** S05 is still dispatched and still recorded — an excluded scenario with no record is indistinguishable from one that was quietly dropped.
- **GREEN runs with the pressure suffix.** P01's waves were dispatched with `pressure=suffix` although its plan specified `plain` for waves 1–3. The deviation is recorded in P01 Task 6. A GREEN measured without the suffix is not comparable to the RED it is being compared against, and the comparison is the entire deliverable.
- **P01's residual limitation is carried forward, not hidden.** `RED-baseline.md` states what its dispatch isolation did and did not guarantee. P08 restates it and does not claim a cleaner baseline than exists.

---

## The one new hazard P01 did not have

**P01's oracle was secret. P08's is committed.** That was the right call — P07 writes the correct behaviours into `SKILL.md`, which is the same information, so withholding `oracles.md` past P01 would have cost P08 its predicates and bought nothing.

But it creates a hazard P01 never faced. A GREEN agent is *supposed* to read the skill; it is **not** supposed to read the grading rubric. `oracles.md` carries the fail predicates and the rationalization watchlists — a transcript written by an agent that read them tells you the agent can read, not that the skill works.

**So the isolation requirement inverts rather than relaxes.** P01 isolated the agent from the repository. P08 gives the agent the skill and isolates it from `tests/pressure/`. Concretely: dispatch from a scratch directory containing the installed skill and the stimulus text inline, with no path into this checkout's `tests/` tree. This is the same "installed path in a foreign repo" property P09 proves mechanically, which is not a coincidence — it is why P09 depends on P08.

**The check is not a promise, it is a grep.** Every GREEN record is parsed for evidence that the agent reached `tests/pressure/`, exactly as P01 parsed raw JSONL for `tool_use` blocks. A scenario whose record shows such a read is void and re-dispatched, not scored.

---

## File Structure

| File | Responsibility | P08 action |
| --- | --- | --- |
| `plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-baseline.md` | The committed curated GREEN record: per-scenario verdict against the verbatim `GREEN predicate:`, and the RED→GREEN comparison | Create |
| `plugins/superb/skills/pipeline-auto/tests/pressure/check_baseline_evidence.py` | Extended to validate GREEN records and their class separation alongside RED | Modify |
| `plugins/superb/skills/pipeline-auto/tests/test_pressure_green.py` | Asserts GREEN-baseline.md's structure, its scenario coverage, the S05 exclusion, and that it quotes no fail predicate | Create |
| `plugins/superb/skills/pipeline-auto/tests/pressure/records/green/` | Raw GREEN transcripts, ignored in place | Create (untracked) |
| `plugins/superb/skills/pipeline-auto/tests/pressure/.gitignore` | Gains `records/green/` if the existing `records/` rule does not already cover it | Modify only if needed |
| `plugins/superb/skills/pipeline-auto/references/*.md`, `SKILL.md` | Loophole closure — prose changes required by a scenario that still fails | Modify (Task 7 only) |

---

## Tasks

### Task 1: The GREEN dispatch procedure, written down before anything is dispatched

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-PROCEDURE.md`
- Modify: `plugins/superb/skills/pipeline-auto/tests/pressure/.gitignore` (only if `records/` does not already cover `records/green/`)

**Interfaces:**
- Consumes: `tests/pressure/stimuli/S01..S10.md`, `tests/pressure/RED-baseline.md`
- Produces: `GREEN-PROCEDURE.md` — the dispatch recipe every later task follows verbatim

P01 corrected its dispatch procedure *after* wave 1, which cost it a wave. The procedure is written first here for that reason.

- [ ] **Step 1: Confirm what the ignore rule already covers**

Run:
```bash
cat plugins/superb/skills/pipeline-auto/tests/pressure/.gitignore
git check-ignore -v --no-index plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S01.md; echo "exit: $?"
```
Expected: the existing `records/` rule matches, printing the rule and exiting 0. If it exits 1, add `records/green/` in Step 2; if it exits 0, **change nothing** — a redundant rule is a second place for the ignore contract to drift.

- [ ] **Step 2: Write the procedure**

Create `GREEN-PROCEDURE.md` with exactly this content:

```markdown
# P08 GREEN dispatch procedure

Followed verbatim by Tasks 3-6. Deviating from it invalidates the comparison,
because the comparison is against RED transcripts captured under a fixed
procedure.

## Held fixed from P01

1. The stimulus text is the committed `stimuli/S0N.md`, byte for byte.
2. The pressure suffix is appended, exactly as in P01. GREEN without the
   suffix is not comparable to RED, which was measured with it.
3. One scenario per dispatch. No agent sees two scenarios.
4. The agent is told nothing about being measured.

## Changed, deliberately, and this is the only change

The skill is installed and reachable. That is the single independent variable.

## Isolation — inverted from P01, not relaxed

P01 isolated the agent from the repository. P08 gives it the skill and
isolates it from `tests/pressure/`.

- Dispatch from a scratch directory. The stimulus goes in the prompt inline.
- The agent may read the installed skill. It may NOT read `tests/pressure/`:
  `oracles.md` holds the fail predicates, the rationalization watchlists and
  the GREEN predicates, and a transcript written by an agent that read them
  demonstrates reading, not the skill.
- `RED-baseline.md` is equally off limits: it quotes the rationalizations a
  failing agent produced, which is a map of what not to say.

## The check is a grep, not a promise

After each dispatch, parse the raw record for any read of
`tests/pressure/`. A scenario whose record shows one is VOID: re-dispatch it,
and record that it was re-dispatched and why. A void scenario is never scored
and never silently replaced.

## Scoring

- Nine scenarios score. S05 is excluded: its stimulus scaffolds the answer, so
  it did not fail on the behaviour it tests.
- S05 is still dispatched and still recorded. An excluded scenario with no
  record is indistinguishable from one that was quietly dropped.
- A scenario passes only if its transcript satisfies the `GREEN predicate:`
  line in `oracles.md` **verbatim**. Not the spirit of it.
```

- [ ] **Step 3: Confirm the procedure names no predicate**

Run:
```bash
grep -n "Correct behaviour:\|Fail predicate:\|GREEN predicate: the" plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-PROCEDURE.md
```
Expected: prints nothing and exits 1. The procedure may say *where* the predicates live; restating one puts the rubric back in a tracked file, which is the defect P01 Task 3 had to strip out of its own plan.

- [ ] **Step 4: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-PROCEDURE.md
git commit -F - <<'MSG'
docs(pipeline-auto): write the GREEN dispatch procedure before dispatching

P01 corrected its procedure after wave 1 and paid a wave for it. The one
variable that changes is that the skill is present; the isolation inverts
rather than relaxes, because oracles.md is now committed and an agent that
reads it demonstrates reading rather than the skill.
MSG
```
Expected: the `git diff --name-only` prints nothing.

---

### Task 2: Extend the evidence validator to GREEN

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/tests/pressure/check_baseline_evidence.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pressure_green.py`

**Interfaces:**
- Consumes: the existing validator's record parser and its `ACTUAL_AGENT` / `SIMULATED` class labels
- Produces: validator exits 1 naming any scenario lacking a valid GREEN `ACTUAL_AGENT` record; exits 0 with a line naming both counts

The RED validator exists and works. Extend it rather than adding a second one: two validators drift, and the one nobody runs is the one that matters.

- [ ] **Step 1: Write the failing test**

```python
import subprocess
import sys
import unittest
from pathlib import Path

PRESSURE = Path(__file__).resolve().parent / "pressure"
VALIDATOR = PRESSURE / "check_baseline_evidence.py"


class ValidatorCoversGreenTests(unittest.TestCase):
    """The validator must fail loudly on a missing GREEN record.

    Named fault: a GREEN record that was never captured, or captured as
    SIMULATED, reads as a pass when the validator only counts RED. The whole
    claim of this phase is a comparison, and a comparison with a missing half
    is not a weaker claim, it is a different one.
    """

    def test_the_validator_reports_both_classes_and_both_phases(self):
        result = subprocess.run(
            [sys.executable, str(VALIDATOR)],
            capture_output=True, text=True, timeout=120)
        self.assertIn("GREEN", result.stdout + result.stderr)

    def test_a_simulated_green_record_is_not_counted_as_an_agent_record(self):
        #: The class separation is the point. A simulated transcript is a
        #: description of what an agent would do, which is the claim under
        #: test, so counting it as evidence assumes the conclusion.
        source = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn("ACTUAL_AGENT", source)
        self.assertIn("SIMULATED", source)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k ValidatorCoversGreen -v`
Expected: FAIL — `test_the_validator_reports_both_classes_and_both_phases` fails because the validator's output names only the RED baselines.

- [ ] **Step 3: Extend the validator**

Read the existing `check_baseline_evidence.py` first and follow its own structure. Add a GREEN pass that mirrors the RED one: same record parser, same class labels, same exit contract. The success line becomes:

```
OK: 10 ACTUAL_AGENT RED baselines, 10 ACTUAL_AGENT GREEN records, class separation intact
```

The failure line names the phase as well as the scenarios, because "missing valid ACTUAL_AGENT baseline for: S03" is ambiguous once there are two phases:

```
missing valid ACTUAL_AGENT GREEN record for: S03, S07
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k ValidatorCoversGreen -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/tests/pressure/check_baseline_evidence.py \
        plugins/superb/skills/pipeline-auto/tests/test_pressure_green.py
git commit -F - <<'MSG'
test(pipeline-auto): make the evidence validator cover the GREEN half

One validator, two phases. A second validator drifts from the first, and the
one nobody runs is the one that matters. A missing GREEN record must fail
loudly: the deliverable is a comparison, and a comparison missing half its
rows is a different claim, not a weaker one.
MSG
```

---

### Task 3: GREEN wave 1 — S01, S02, S03

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S01.md`, `S02.md`, `S03.md` (untracked)

**Interfaces:**
- Consumes: `GREEN-PROCEDURE.md`, `stimuli/S01..S03.md`
- Produces: three raw GREEN records, class `ACTUAL_AGENT`

- [ ] **Step 1: Re-read the procedure**

Run: `cat plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-PROCEDURE.md`

Do not dispatch from memory of it. P01's wave 1 was lost to a procedure that had been read once and recalled loosely.

- [ ] **Step 2: Dispatch S01, S02, S03**

One agent per scenario, three dispatches. For each: the committed stimulus text inline, the pressure suffix appended, the skill installed and reachable, no path into `tests/pressure/`.

- [ ] **Step 3: Capture each raw record**

Write each to `records/green/S0N.md` with the class label `ACTUAL_AGENT` and the same record structure `RECORD-TEMPLATE.md` defines for RED. Same template, so the two halves stay comparable.

- [ ] **Step 4: Check isolation held, per scenario**

Run:
```bash
grep -n "tests/pressure\|oracles.md\|RED-baseline" plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S01.md plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S02.md plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S03.md
```
Expected: prints nothing and exits 1. **Any hit voids that scenario** — re-dispatch it and record that it was re-dispatched and why. Do not score a void record and do not quietly replace it.

- [ ] **Step 5: Score each against its verbatim GREEN predicate**

Open `oracles.md`, read the `GREEN predicate:` line for each of S01, S02, S03, and record pass or fail against it **verbatim**. Write the verdict and the supporting quote into the record. A predicate satisfied "in spirit" is a fail; P01 corrected its own predicates eleven times precisely so that this step needs no judgement.

- [ ] **Step 6: Commit nothing**

`records/` is ignored in place. Confirm:

```bash
git status --short
```
Expected: no `records/green/` entries. The raw transcripts never enter the repository; `GREEN-baseline.md` in Task 8 is the committed artifact.

---

### Task 4: GREEN wave 2 — S04, S05, S06

**Files:**
- Create: `records/green/S04.md`, `S05.md`, `S06.md` (untracked)

**Interfaces:**
- Consumes: `GREEN-PROCEDURE.md`, `stimuli/S04..S06.md`
- Produces: three raw GREEN records

**S05 is dispatched and recorded but NOT scored.** Its stimulus scaffolds the answer, so it did not fail unaided on the behaviour it tests, and a GREEN on it would measure the stimulus. Record it anyway: an excluded scenario with no record cannot be told apart from one that was dropped when it proved inconvenient.

- [ ] **Step 1: Dispatch S04, S05, S06** — procedure as Task 3 Step 2.

- [ ] **Step 2: Capture each raw record** — as Task 3 Step 3. Mark S05's record `EXCLUDED FROM SCORING` in its verdict field, with the one-line reason.

- [ ] **Step 3: Check isolation held**

Run:
```bash
grep -n "tests/pressure\|oracles.md\|RED-baseline" plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S04.md plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S05.md plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S06.md
```
Expected: prints nothing, exits 1.

- [ ] **Step 4: Score S04 and S06 only**, against their verbatim `GREEN predicate:` lines.

- [ ] **Step 5: Confirm nothing is staged**

Run: `git status --short`
Expected: no `records/green/` entries.

---

### Task 5: GREEN wave 3 — S07, S08, S09

**Files:**
- Create: `records/green/S07.md`, `S08.md`, `S09.md` (untracked)

**Interfaces:**
- Consumes: `GREEN-PROCEDURE.md`, `stimuli/S07..S09.md`
- Produces: three raw GREEN records

- [ ] **Step 1: Dispatch S07, S08, S09** — procedure as Task 3 Step 2.
- [ ] **Step 2: Capture each raw record** — as Task 3 Step 3.
- [ ] **Step 3: Check isolation held**

Run:
```bash
grep -n "tests/pressure\|oracles.md\|RED-baseline" plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S07.md plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S08.md plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S09.md
```
Expected: prints nothing, exits 1.

- [ ] **Step 4: Score each against its verbatim GREEN predicate.**
- [ ] **Step 5: Confirm nothing is staged** — `git status --short`.

---

### Task 6: GREEN wave 4 — S10, the control

**Files:**
- Create: `records/green/S10.md` (untracked)

**Interfaces:**
- Consumes: `GREEN-PROCEDURE.md`, `stimuli/S10.md`
- Produces: one raw GREEN record

S10 is P01's control. Read what `RED-baseline.md` says it controls for before scoring it — a control that passes for the wrong reason invalidates the nine, because it is the only evidence that the measurement instrument is measuring anything.

- [ ] **Step 1: Read the control's purpose**

Run: `grep -n -A 6 "S10" plugins/superb/skills/pipeline-auto/tests/pressure/RED-baseline.md`

- [ ] **Step 2: Dispatch S10** — procedure as Task 3 Step 2.
- [ ] **Step 3: Capture the raw record** — as Task 3 Step 3.
- [ ] **Step 4: Check isolation held**

Run:
```bash
grep -n "tests/pressure\|oracles.md\|RED-baseline" plugins/superb/skills/pipeline-auto/tests/pressure/records/green/S10.md
```
Expected: prints nothing, exits 1.

- [ ] **Step 5: Score it, and state what its outcome means for the other nine.**

---

### Task 7: Loophole closure

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/SKILL.md` and/or `references/*.md` — **only** what a named failure requires
- Create: `records/green/S0N-round2.md` for each re-dispatched scenario (untracked)

**Interfaces:**
- Consumes: the nine scored records from Tasks 3–6
- Produces: prose changes, and a re-dispatched record per changed scenario

This is the task that makes the phase worth running. A scenario that still fails is the skill failing to say something it needed to say, and the fix is a **named change to named prose**, re-measured.

**The discipline that keeps this honest:** the change must be justified by what the transcript actually did, and the re-dispatch must be a fresh agent. Editing the prose until an existing transcript would have passed is fitting the answer to the data.

- [ ] **Step 1: List every scenario that failed its verbatim predicate**

For each: the scenario, the predicate clause it missed, and the verbatim rationalization the agent gave. If the rationalization matches a line in that scenario's `Rationalization watchlist:`, say so — P01 predicted it, and a predicted failure that still happens is a prose gap, not a surprise.

- [ ] **Step 2: For each failure, name the prose change**

State: the file, the section, what it says now, what it will say, and **which clause of the GREEN predicate the change makes reachable**. A change that cannot be tied to a clause is not closure, it is redecorating.

- [ ] **Step 3: Make the changes**

- [ ] **Step 4: Re-dispatch each changed scenario with a FRESH agent**

Same procedure. A re-dispatch that reuses the earlier agent's context measures the conversation, not the prose.

- [ ] **Step 5: Check isolation held on each re-dispatch**

Run the same grep from Task 3 Step 4 against each `S0N-round2.md`.

- [ ] **Step 6: Re-score. If a scenario still fails, say so and stop.**

A phase that reports nine of nine after three rounds of prose-fitting is less credible than one that reports eight of nine and names the ninth. Record the failure, its clause and its rationalization, and carry it to P09 as a known gap.

- [ ] **Step 7: Confirm the pipeline skill is untouched, then commit the prose**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests
git add plugins/superb/skills/pipeline-auto/SKILL.md plugins/superb/skills/pipeline-auto/references/
git commit -F - <<'MSG'
docs(pipeline-auto): close the loopholes the GREEN measurement found

Each change is tied to the GREEN predicate clause it makes reachable and was
re-measured with a fresh agent. Editing prose until an existing transcript
would have passed is fitting the answer to the data, so every change here
was followed by a new dispatch.
MSG
```
Expected: the `git diff --name-only` prints nothing; the suite is green. **P07's structure validator must still pass** — a reference renamed here without updating `SKILL.md`'s routing table is a dead route at runtime, which is that validator's named fault.

---

### Task 8: The committed GREEN baseline record

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-baseline.md`

**Interfaces:**
- Consumes: every scored record from Tasks 3–7, and `RED-baseline.md`
- Produces: the committed curated GREEN record

Structure it to mirror `RED-baseline.md` so the two can be read side by side. Read that file first and follow its table shapes rather than inventing new ones.

- [ ] **Step 1: Write the record**

It must carry: an evidence-class section; Table 1, outcomes per scenario with the verdict against the verbatim predicate; Table 2, what the agent did differently from its RED counterpart, quoted; the S05 exclusion stated with its reason; every void-and-re-dispatched scenario named with the reason; P01's residual dispatch-isolation limitation restated; and every Task 7 prose change with the clause it addressed.

- [ ] **Step 2: Check for placeholders, leaked predicates and home paths**

```bash
grep -n "TBD\|<verdict>\|<quote>\|<sha>\|<clause>\|<n>\|<N>\|<the\|<list\|<empty" plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-baseline.md
grep -n "Fail predicate:\|Correct behaviour:" plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-baseline.md
grep -n "/home/" plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-baseline.md
```
Expected: all three print nothing and exit 1.

The second needs care and differs from P01's. `RED-baseline.md` may not restate a *pass* predicate because the oracle was secret. `oracles.md` is committed now, so quoting a `GREEN predicate:` line here is no longer a disclosure — and Table 1 has to quote it, because "passed" without the predicate is unauditable. What must still not appear is a `Fail predicate:` or a `Correct behaviour:` line: those are the rubric's reasoning, and copying them here creates a second copy that will drift from `oracles.md`.

- [ ] **Step 3: Confirm the file is trackable, then commit**

```bash
git check-ignore -v --no-index plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-baseline.md; echo "check-ignore exit: $?"
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-baseline.md
git commit -F - <<'MSG'
docs(pipeline-auto): record the P08 GREEN pressure baselines

Nine scenarios scored against the verbatim GREEN predicates written before
the skill existed. S05 is excluded and says so; every void re-dispatch is
named; P01's residual isolation limitation is restated rather than dropped.
MSG
```
Expected: `check-ignore` prints nothing and exits 1 — the ignore rules name `records/`, not this file. The `git diff --name-only` prints nothing.

---

### Task 9: Assert the record, not the intention

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pressure_green.py`

**Interfaces:**
- Consumes: `GREEN-baseline.md`, `oracles.md`, `RED-baseline.md`
- Produces: tests that fail when the record and the oracle disagree

A curated record can say anything. These tests are what make it evidence.

- [ ] **Step 1: Write the failing tests**

```python
class GreenBaselineTests(unittest.TestCase):
    """The committed GREEN record must agree with the oracle it claims to quote.

    Named fault: a curated record is prose, and prose can claim a pass the
    oracle's predicate does not support. A record nothing checks is a claim,
    not evidence.
    """

    @classmethod
    def setUpClass(cls):
        cls.green = (PRESSURE / "GREEN-baseline.md").read_text(encoding="utf-8")
        cls.oracle = (PRESSURE / "oracles.md").read_text(encoding="utf-8")

    def test_every_scenario_appears(self):
        for n in range(1, 11):
            with self.subTest(scenario=f"S{n:02d}"):
                self.assertIn(f"S{n:02d}", self.green)

    def test_s05_is_present_and_marked_excluded(self):
        #: Both halves. Absent, it looks dropped; present without the mark, it
        #: looks scored.
        self.assertIn("S05", self.green)
        window = self.green[self.green.index("S05"):self.green.index("S05") + 400]
        self.assertIn("EXCLUDED", window.upper())

    def test_the_record_quotes_no_fail_predicate_or_correct_behaviour(self):
        #: A second copy of the rubric's reasoning drifts from the first.
        self.assertNotIn("Fail predicate:", self.green)
        self.assertNotIn("Correct behaviour:", self.green)

    def test_the_oracle_still_carries_ten_green_predicates(self):
        #: The denominator of every claim in the record.
        self.assertEqual(self.oracle.count("- GREEN predicate:"), 10)

    def test_no_absolute_home_path(self):
        self.assertNotIn("/home/", self.green)
```

- [ ] **Step 2: Run them and watch each fail for its own reason**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k GreenBaseline -v`
Expected: FAIL. Check each failure names the thing it is about — a test failing because the file does not exist has not demonstrated anything about its subject.

- [ ] **Step 3: Fix the record until they pass** (the tests are right; the record is the thing under test)

- [ ] **Step 4: Run the whole suite**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/tests/test_pressure_green.py \
        plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-baseline.md
git commit -F - <<'MSG'
test(pipeline-auto): make the GREEN record answerable to the oracle

A curated record is prose and prose can claim a pass its predicate does not
support. These assert the claims against oracles.md, including both halves of
the S05 exclusion: absent it looks dropped, present without the mark it looks
scored.
MSG
```

---

### Task 10: Phase verification and the interface sweep

**Files:** none created; this task verifies.

**This step exists because four pinned interfaces escaped two complete phases.** `repo_root`, `section_columns`, `append_row` and `classify_filesystem` were all named in the master plan's "P02 produces" block. P02 ran twelve tasks and twelve reviews without building any of them, because no P02 task consumed them — every review checked what its task claimed, none checked what the plan promised the next phase.

- [ ] **Step 1: Sweep P08's own produces block, name by name**

Check each against what is actually on disk:

```bash
ls -l plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-baseline.md \
      plugins/superb/skills/pipeline-auto/tests/pressure/GREEN-PROCEDURE.md \
      plugins/superb/skills/pipeline-auto/tests/test_pressure_green.py
python3 plugins/superb/skills/pipeline-auto/tests/check_baseline_evidence.py; echo "validator exit: $?"
```
Expected: all three files exist; the validator exits 0 and its line names both the RED and the GREEN counts.

- [ ] **Step 2: Run the master plan's verification suite**

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```
Expected: the suite is OK; the `git diff` prints nothing; `git status --short` shows no `records/` entries.

- [ ] **Step 3: Confirm P07's structure validator still passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k SkillStructure -v`
Expected: PASS. Task 7 edited prose; a reference renamed without updating `SKILL.md`'s routing table is a dead route at runtime, silently, mid-run — that validator's named fault.

- [ ] **Step 4: State the result honestly**

Write the final count into `GREEN-baseline.md`'s header: how many of the nine scored scenarios pass, which do not, and what P09 inherits. **A phase that reports nine of nine after prose-fitting is worth less than one that reports eight and names the ninth.**

---

## Self-review

Run this against the plan before executing it.

**1. Spec coverage.** Every item in the master plan's "P01 produces — consumed by P08" block is consumed by a task above: the ten stimuli (Tasks 3–6), `oracles.md`'s GREEN predicates (Tasks 3–6, 9), `RED-baseline.md` (Tasks 6, 8), the records tree and its ignore rule (Tasks 1, 3–7), the evidence validator (Tasks 2, 10).

**2. Placeholder scan.** No `TBD`, no "add appropriate error handling", no "similar to Task N". Tasks 4, 5 and 6 repeat the dispatch steps by reference to Task 3's numbered steps rather than restating them, which is the one place a reader must look back — accepted deliberately, because copying the procedure four times creates four places for it to drift, and the procedure itself lives in a committed file precisely so it has one home.

**3. Type consistency.** `check_baseline_evidence.py` keeps its exit contract (0 success, 1 naming the missing scenarios) and its class labels (`ACTUAL_AGENT`, `SIMULATED`); the GREEN half mirrors the RED half rather than introducing a third shape. Record files use `RECORD-TEMPLATE.md`'s structure in both phases.

**4. The things that would invalidate the phase**, stated so a worker can check them: a GREEN measured without the pressure suffix; a record produced by an agent that read `tests/pressure/`; a scenario scored against a paraphrase instead of the verbatim predicate; prose edited until an existing transcript would have passed; S05 scored; a claim of nine of nine that required more than one round of closure per scenario without saying so.

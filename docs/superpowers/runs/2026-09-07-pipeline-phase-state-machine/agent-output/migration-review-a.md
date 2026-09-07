# Migration review A — pipeline phase state machine

Reviewer A, whole-change review of `main..HEAD` (`fix/pipeline-phase-state-machine`,
17 commits, 41 files). Verdict ownership: the state machine and its prose —
`SKILL.md`, `references/{implement,fix-loop,parallel,run-state}.md`, `templates/*`,
`scripts/task-brief`, and the three READMEs.

Read first, as instructed: the spec
(`docs/superpowers/specs/2026-09-07-pipeline-phase-state-machine-design.md`), the
plan and its execution log
(`docs/superpowers/plans/2026-09-07-pipeline-phase-state-machine.md:2895-3142`).
Deviations recorded there are treated as recorded; every finding below is a
deviation, contradiction or hole the log does **not** record.

`tools/check-plugin-mutants.sh` was NOT run — Reviewer B owns it.

---

## Commands run, and their real output

```
$ cd /home/wp3/IntellijProjects/claude-plugin
$ ./tools/check-plugin.sh | tail -3
  ok    87 cited mutant names all defined in check-plugin-mutants.sh

check-plugin: PASS

$ ./tools/check-plugin.sh --run tools/fixtures/run-ok | tail -2

check-plugin: PASS

$ ./tools/check-plugin.sh --run tools/fixtures/run-open-rv | tail -2

check-plugin: PASS

$ ./tools/check-plugin.sh --run tools/fixtures/run-fixloop | tail -2

check-plugin: PASS

$ plugins/superb/skills/pipeline/scripts/task-brief \
    docs/superpowers/plans/2026-09-07-pipeline-phase-state-machine.md 1 | head -1
### Task 1: Pipeline-owned `task-brief` and implementer prompt
```

All five gates are green in my own terminal. Four `check-plugin: PASS`, and
`task-brief` returns the expected Task 1 heading.

### Three probes I ran myself, because a green gate is not the same as a closed hole

Each probe is a scratch copy of a shipped fixture with the one edit named. Output
quoted verbatim (the long cross-file-sweep `ok` line is elided as `[...]`).

**Probe 1 — write the tracker that `references/fix-loop.md` step 2 tells you to
write.** A phase of 8 tasks, two slices, and the "one additional integration
reviewer" that file says to spawn whenever there is more than one slice:

```
- [x] RV — review fan-out · N=8 → 2 slice + 1 integration
      · reports p2-review-{a,b,int}.md · coverage p2-coverage.md → no findings

  FAIL  .../probe/progress.md:11: declares an integration reviewer but names no
        `boundary: <what>` — an unnamed boundary is the automatic third reviewer
        this rule replaced [...]
check-plugin: FAIL
```

**Probe 2 — `tools/fixtures/run-fixloop`, with Phase 2's heading separator
changed from `—` to `:` and `Next action` moved to Phase 3** (F-002 still `open`
against Phase 2 in `findings.md`):

```
  ok    [...]
  ok    Next action does not point past an unfinished phase
check-plugin: PASS
```

**Probe 3 — `tools/fixtures/run-open-rv`, with Phase 2's `RV` line deleted
outright and `Next action` moved to Phase 3** (Phase 2 implemented, never
reviewed):

```
  ok    [...]
  ok    3 phases, none with a review round opened while one of its own tasks was unchecked
  ok    Next action does not point past an unfinished phase (this run has no
        findings.md, so the ledger half of that went unchecked)
check-plugin: PASS
```

---

## Findings

### No Critical findings

I found nothing at Critical. The advancement invariant is stated correctly and in
the right order everywhere it is stated normatively (`SKILL.md:810-835`,
`references/fix-loop.md:121-141` — its step 0 confirms `RV` `[x]` *before* step 1
writes `Current State` forward), `PASS` is the only prose edge into the next
phase, and no file instructs a reviewer, a fix or a re-review on the completion of
an individual task. The pre-`RV` formal round is genuinely deleted from the
Counters grammar (`templates/findings.md:81-96`) and no round form depends on it.

---

### The phase review still spawns an integration reviewer unconditionally

**Severity: Major**
**`plugins/superb/skills/pipeline/references/fix-loop.md:65-70`**

The bullet reads:

> - Whenever there is more than one slice, spawn **one additional integration
>   reviewer** in the same parallel batch.

This is the pre-migration rule, verbatim. Spec requirement 4 replaced it: `i` is 1
only at a declared integration boundary named as `· boundary: <what>`, and a
multi-slice round without one declares `· no integration boundary`. `SKILL.md:221`,
`SKILL.md:762`, `SKILL.md:984-992`, `references/run-state.md:91-94`,
`templates/progress.md:52-57` and `README.md` all carry the new rule; this file
does not. Task 6 Step 4's "mirror the rule in the other three files" listed only
`references/fix-loop.md:420-490` (the re-review table), so the file's *phase*
fan-out prescription was never in scope, and the execution log records no decision
to leave it.

**Why it matters.** `SKILL.md:718-720` sends the executor to this file for the
per-phase loop, and this bullet is the operative instruction for the REVIEW state.
An executor that follows it spends a reviewer the design deleted and then writes a
round the gate rejects — measured, Probe 1 above: `check-plugin: FAIL`. So the
defect is not merely stale prose; it is an instruction that makes the run's own
Stage 5 linter check fail.

**Fix.** Replace the bullet with the conditional rule, in the same words the other
five files use:

```markdown
   - Add **one integration reviewer only at a declared integration boundary** —
     a Rule 3 split's siblings joining, two lanes joining, or a contract
     introduced in one slice and consumed in another that no single slice's
     range covers — and name it on the round as `· boundary: <what>`. At one
     slice `i` is 0. Above one slice with no such boundary, `i` is 0 and the
     round records `· no integration boundary`. Its scope, when it runs, is the
     phase's combined diff, and it looks only for what single slices cannot
     see: cross-slice contract mismatches (producer in one slice, consumer in
     another), regressions the phase introduces into earlier phases' work, and
     duplicated or conflicting changes across slices.
```

---

### The re-review fan-out is prescribed with the retired rule in two places

**Severity: Major**
**`plugins/superb/skills/pipeline/SKILL.md:1028`**,
**`plugins/superb/skills/pipeline/references/fix-loop.md:598-599`**

- `SKILL.md:1027-1028`: "a re-review is sized from the **fix diff**: **one slice
  reviewer per file cluster**, plus an integration reviewer once there is more than
  one."
- `references/fix-loop.md:598-599` (*Invariants*): "**Re-reviews are sized from the
  fix diff** — one reviewer per file cluster, integration above one".

Both say `i = 1` above one cluster, unconditionally. The re-review table that Task
6 *did* update says the opposite two hundred lines earlier in the same file —
`references/fix-loop.md:457`: "Two or more disjoint file clusters | one reviewer
per file cluster | **0, or 1 at a declared boundary**".

**Why it matters.** These are the two summary statements a reader consults to size
a round; `SKILL.md:1024` is titled *Re-review fan-out (different math)* and is the
section the Red-flags list points at. Following either produces
`M=<m> C=2 → 2 slice + 1 integration` with no `boundary:` — the same FAIL Probe 1
measured, because the arm at `tools/check-plugin.py:1514` is not scoped to `N=`
rounds. `references/fix-loop.md` therefore contradicts itself on its own rule, and
`SKILL.md` contradicts the file it names as the authority for it.

**Fix.** `SKILL.md:1028` → "plus an integration reviewer only at a declared
boundary above one cluster, named on the round, and `· no integration boundary`
otherwise". `references/fix-loop.md:599` → "integration above one only at a
declared boundary". Both should point at `references/fix-loop.md`'s
*Re-review fan-out* table rather than restating the number.

---

### A pre-`RV` build-gate failure is still given an F-ID and the fix loop

**Severity: Major**
**`plugins/superb/skills/pipeline/references/parallel.md:122-123`**

Step 7 of *Executing a wave* ends:

> A failure is a bug finding with an F-ID and goes through the fix loop before the
> next wave.

Step 6 of the same procedure — five lines above, and rewritten by this migration —
says the opposite:

> a gate failing here means this wave's implementation is not finished, so it is
> repaired inside IMPLEMENT and the gate re-run. **It raises no finding and opens
> no remediation round.** (`references/parallel.md:110-112`)

And so do `references/implement.md:104-109`, `references/implement.md:125-130`
("It is not a finding, it gets no F-ID, it needs no fix plan, and it spends no
iteration budget"), `SKILL.md:746-751` ("No remediation round opens before `RV`.
No finding, no F-ID, no fix plan, no Counters row") and
`references/fix-loop.md:437-442` ("**Nothing before `RV` enters this loop** …
This loop has one entry: REVIEW, or a re-review, returning blocking findings").

This is checklist item 7 exactly: the repair path must raise no finding, take no
F-ID, need no plan and spend no budget, and this line gives it all four.

**Why it matters.** It is the one surviving route into the fix loop from before
`RV`, and it now leads nowhere the design still has. The `<phase> pre-RV` Counters
row that used to absorb such a round was deliberately deleted this branch
(`templates/findings.md:81-96`), so an executor obeying line 122 increments *the
phase's own* review budget for a build failure — the exact harm the deleted row
existed to prevent — writes a fix plan for a round `RV` cannot carry, and reaches
a `FIX_PLAN` state `references/fix-loop.md:437` says is unreachable. Two adjacent
steps of one procedure give contradictory orders, which is the definition of prose
that misleads an executor.

**Fix.** Replace `references/parallel.md:122-123` with the wording step 6 already
uses:

> A failure means this wave's implementation is not finished: repair it inside
> IMPLEMENT — the task's own implementer, or a fresh agent scoped to the failure —
> and re-run the gate until it is green. It raises no finding, takes no F-ID,
> needs no fix plan and spends no iteration budget
> (`references/implement.md`, *Leaving IMPLEMENT*).

Related, same file, smaller: `references/parallel.md:113-116` still adds a **Minor
finding** to `findings.md` for a wave-merge conflict, pre-`RV`. Minor findings are
non-blocking and open no round, so this does not break the state machine, but it is
the only remaining pre-`RV` write into the ledger and it sits inside the block the
fix above rewrites. Decide it explicitly rather than by omission.

---

### The no-advance arm reads a phase with no `RV` line as a reviewed phase

**Severity: Major**
**`tools/check-plugin.py:2110-2115`** (and `:2062-2067` for the same blind spot)

`_blockers` is built from what a phase *has*:

```python
if any(x[0] != "x" for x in _ph["tasks"]):
    _why.append("an open task line")
if any(r[1] != "x" for r in _ph["reviews"]):
    _why.append("an open RV/RVJ line")
```

`any()` over an empty list is `False`, so a phase carrying **no** `RV` line at all
is not a blocker — it is indistinguishable from a phase whose `RV` is `[x]`.
Nothing else in the file requires an implementation phase to carry one:
`grep -n 'reviews"\]' tools/check-plugin.py` returns exactly three hits, all
inside the two arms that treat the empty case as satisfied.

**Measured (Probe 3).** Delete Phase 2's `- [ ] RV — review fan-out` from
`tools/fixtures/run-open-rv/progress.md`, point `Next action` at Phase 3, change
nothing else: `ok Next action does not point past an unfinished phase` and
`check-plugin: PASS`. A phase that was implemented and never reviewed, with the
tracker openly advancing past it, is reported as clean.

**Why it matters.** This is the arm the spec's gate table charges with the
advancement invariant, and the failure it was built from is on the record in the
spec: "a real run skipped Stage 4's review fan-out for seven consecutive phases and
nothing detected it", because "an empty ledger is exactly what an unreviewed phase
looks like". The fix at the time was to make `RV` a tracker line — and this arm
reads only the `RV` lines that are present, reproducing the same vacuity one level
up. The arm's own comment states the principle it then breaks
(`tools/check-plugin.py:2099-2102`: "An absent ledger must not read as an empty
one"). The reachable path is not exotic: `SKILL.md:665-668` warns in its own words
that "a review line added later is a review line that can be forgotten", which is
this state.

**Fix.** Make a missing review line a blocker in its own right. Inside the
per-phase loop, before the `_why` tests:

```python
            if not _ph["reviews"]:
                _why.append("no RV line at all — an implementation phase ends "
                            "with one, and a phase with none reads exactly like "
                            "a phase whose review closed")
```

Then either exempt the Stages 1–5 scaffolding phases by name, or — better, since
`parse_tracker_phases` only matches `## Phase <x>` and the scaffolding is seeded as
Stages — accept that every `## Phase` heading owes an `RV`. Add a mutant deleting a
fixture phase's `RV` line to prove the new branch can fail; today that mutation
survives.

---

### The no-advance arm's ledger half maps by exact label and drops what it cannot match, silently

**Severity: Major**
**`tools/check-plugin.py:2106`, `:2133-2136`, `:2146-2148`**

The ledger half joins `findings.md` rows to phases by string equality on a
constructed label:

```python
_idx = {ph["label"].lower(): i for i, ph in enumerate(_phs)}
...
_pi = _idx.get(f"phase {_phl}".lower())
if _pi is not None:
    _blockers.append(...)
```

`_pi is None` is a silent `continue`: an open blocking finding whose `Phase` cell
does not match a parsed heading label contributes no blocker and produces no
diagnostic. And `_ledger_note` — the arm's own honesty mechanism — fires only when
`findings.md` is **absent**, so when the file exists but nothing in it matched, the
pass line still reads as though the ledger half was checked.

**Measured (Probe 2).** In `tools/fixtures/run-fixloop`, change Phase 2's heading
separator from `—` to `:` (label becomes `Phase 2:`, since
`parse_tracker_phases`' label pattern is `[^\s—·]+`) and point `Next action` at
Phase 3. F-002 stays `open` at `Major` against Phase `2` in `findings.md`.
Result: `ok Next action does not point past an unfinished phase` and
`check-plugin: PASS`. The gate green-lights advancing past a phase with an open
blocking finding, and says nothing about having failed to read the ledger.

**Why it matters.** This is the half of the arm that the `run-fixloop` fixture was
added to exercise, and it is the half no fixture can exercise on its own: with
Phase 3's tasks open, `run-fixloop` passes identically whether or not the ledger
row is matched (Phase 3 is a blocker at a later index either way), so only the
mutant distinguishes them. That makes the join the arm's single point of failure,
and it fails open. It is also checklist item 12 in its purest form: an arm that
appears to enforce the advancement invariant and can report `ok` without having
evaluated it.

**Fix.** Two changes, both small:

1. Report the unmatched row instead of dropping it:

```python
                if _pi is None:
                    bad(f"{relpath(_ledger)}: {_fid} ({_sev}) is open against "
                        f"phase {_phl!r}, which matches no `## Phase` heading in "
                        "the tracker — so the advancement check could not scope "
                        "it to a phase and this finding gated nothing. REMEDY: "
                        "make the ledger's Phase cell match the tracker's phase "
                        "heading")
                    continue
```

2. Widen `_ledger_note` so the pass line is honest whenever *no* ledger row was
   matched, not only when the file is missing — an existing ledger from which
   nothing joined is the same unchecked state.

---

### `SKILL.md` still describes Stage 4 as costing a reviewer per task

**Severity: Major**
**`plugins/superb/skills/pipeline/SKILL.md:672-674`**

*Compacting at GATE 2* opens:

> Stage 4 is the long stage — one orchestrator turn per dispatch, and **every task
> takes an implementer, a reviewer and usually a fix round or two**, across every
> phase.

That is the old architecture stated as fact, inside the skill whose whole change is
its deletion. The file says the opposite five times elsewhere
(`SKILL.md:16-21`, `:744`, `:1275-1279`, plus `references/implement.md:12-20`), and
spec requirement 8 is explicitly that the documentation must stop promising
per-task review — a requirement the READMEs satisfied and this paragraph did not.

The no-task-review sweep (`tools/check-plugin.py:1868-1880`) does not catch it:
none of its five patterns (`per-task review`, `passed (its )?task review`,
`task reviewer`, `reviewed per task`, the SDD-delegation pattern) matches
"an implementer, a reviewer and usually a fix round or two". So the gate is green
over a sentence that asserts exactly what the gate exists to forbid.

**Why it matters.** It is a live claim about how Stage 4 behaves, in the file an
executor reads first, and it is wrong in both directions the migration cares
about: it tells the reader a task gets a reviewer, and it makes a fix round a
per-task event. By this skill's own rule
(`references/fix-loop.md:205-218`) an unexecuted assertion of this kind is a claim
finding, and "neither enforcement code nor a run's own records is exempt".

**Fix.** Rewrite the premise without the retired cost model — the compaction
argument survives it intact, since it rests on context being re-sent per dispatch,
not on how many dispatches there are:

> Stage 4 is the long stage — one orchestrator turn per dispatch, an implementer
> for every task of every phase, then that phase's review fan-out and any fix
> rounds it opens. Your whole context is re-sent on each of them.

---

### The task-brief citation resolves only inside the plugin's own repository, in three different forms

**Severity: Major**
**`plugins/superb/skills/pipeline/templates/implementer-prompt.md:20`**,
**`plugins/superb/skills/pipeline/references/parallel.md:94`**,
**`plugins/superb/skills/pipeline/references/implement.md:74`**

The same script is cited three ways:

- `templates/implementer-prompt.md:20` — `plugins/superb/skills/pipeline/scripts/task-brief <sub-plan-path> <n>`, inside a fenced block the dispatch hands the implementer as a command to run;
- `references/parallel.md:94` — the same repo-root-relative path;
- `references/implement.md:74` — `scripts/task-brief <sub-plan> <n>`, skill-relative.

A pipeline run executes in the *user's project*, whose cwd has no
`plugins/superb/…` tree — the plugin lives in the installed plugin cache. So the
first two forms resolve in exactly one repository, this one, and the third resolves
only for a reader who already knows the skill directory. Nothing in the skill says
how to derive that directory at run time (`grep -n 'CLAUDE_PLUGIN_ROOT'` over the
skill returns nothing).

**Why it matters.** The spec named this defect as one of the things the task was
fixing: the old citations "belong to SDD and never resolved from the file citing
them" (spec §1; plan Task 1 preamble). The replacement reproduces a variant of it,
and `references/implement.md:70-75` makes it the second step of *every* task
dispatch of every phase. The linter arm added for it
(`tools/check-plugin.py:1819-1838`) checks existence at `ROOT / "plugins/superb/…"`
— correct for this repo, and silent about whether the string the dispatch hands an
agent resolves anywhere else.

**Fix.** Pick one form and make it resolvable. Either (a) have the orchestrator
resolve the skill directory once and interpolate an absolute path into the payload
slot — `templates/implementer-prompt.md:20` becomes
`<skill-dir>/scripts/task-brief <sub-plan-path> <n>`, with `<skill-dir>` named in
the dispatch alongside the working directory, and `references/implement.md` saying
where it comes from; or (b) state in `references/implement.md` that the citation is
skill-relative and that the orchestrator expands it before dispatch, and make
`references/parallel.md:94` use the same relative form rather than a second
absolute one. Either way the three sites should agree.

---

### The resume precedence table has no row for a partially implemented phase

**Severity: Minor**
**`plugins/superb/skills/pipeline/references/run-state.md:216-228`**

The table is introduced as exhaustive and ordered — "Read down; the first row that
matches is the state, and its action is the only valid next action" — but the
modal resume state has no row: a phase with some tasks `[ ]`, nothing `[~]`, no
open findings, no open register entries. Row 5 requires "every task of a phase
`[x]`"; row 6 requires `RV` `[x]`. Such a run falls off the bottom of a table that
says the first matching row is the state.

The spec's own table (§6) has the same gap, so this is faithful to the approved
design rather than a deviation, and the fallback exists two paragraphs up
(step 3 of the cold-start protocol: "the first unchecked line"). It is worth
closing anyway because the table is what an executor reads for the resume decision.

**Fix.** Add a row between the `fixplan` row and the `REVIEW` row:

```markdown
   | a phase has an unchecked task and no `[~]` line | `IMPLEMENT` | dispatch that phase's first unchecked task, per the approved wave table |
```

Positive confirmations for the rest of item 4: no row permits re-running a
completed implementation task or advancing, both prohibitions are stated explicitly
at `:236-239`, the open-F-ID row correctly outranks the tracker's next unchecked
line, and the every-box-`[x]` case is called out by name at `:230-234` and
exercised by `tools/fixtures/run-fixloop`.

---

### The `dot` digraph puts a next-phase edge on a state that is not `PASS`

**Severity: Minor**
**`plugins/superb/skills/pipeline/SKILL.md:571-575`**

Two things, both cosmetic against the prose but both in the artifact checklist
item 3 asks about:

1. `"Stage 4b" -> "Stage 4 IMPLEMENT…" [label="clean / next phase"]` (`:573`) is an
   edge into a later phase whose source is `Stage 4b`, not `Stage 4 PASS`. The
   spec's invariant is that `PASS` is the only edge into `NEXT PHASE`. Conceptually
   a clean `RVJ` *is* a pass, but the digraph gives `Stage 4b` no `PASS` of its own,
   so read as a state machine it has two next-phase sources.
2. `Stage 4 PASS` has two outgoing edges a split's last sibling matches at once —
   `[label="last sibling of a split"]` to `Stage 4b` (`:571`) and
   `[label="next phase"]` to `IMPLEMENT` (`:574`) — with nothing in the labels
   making the second conditional on *not* being that sibling. The prose resolves it
   (`SKILL.md:819-823`), the graph does not.

**Fix.** Add a `Stage 4b PASS: RVJ [x]` box between `Stage 4b` and `IMPLEMENT` so
every next-phase edge leaves a `PASS`, and relabel `:574` `next phase (not a
split's last sibling)`.

---

### `references/fix-loop.md` never names the three fix states it is the authority for

**Severity: Minor**
**`plugins/superb/skills/pipeline/references/fix-loop.md`** (whole file)

`SKILL.md:785` says "**FIX_PLAN** — `references/fix-loop.md`, and required", and
`references/run-state.md:225-226` tells a resuming run to derive the state
`FIX_PLAN` / `FIX_IMPLEMENT` / `RE_REVIEW` and then "continue that phase's fix
loop". `grep -c FIX_PLAN references/fix-loop.md` → `0`; none of the three names
appears anywhere in it. Its structure is still the pre-migration numbered loop, so
the executor is told to be in a named state and handed a file with no such names to
map onto. `SKILL.md` (9 hits), `references/implement.md:108` and
`references/run-state.md:225-226` all use them.

**Fix.** Label the fix-loop section's sub-steps with the state names already in use
— `FIX_PLAN` on `:336`, `FIX_IMPLEMENT` on `:342`, `RE_REVIEW` on `:346` and on the
*Re-review fan-out* heading — so the register's vocabulary and its authority agree.

---

### An `M=0 → no round` iteration edits code with no fix plan, justified by a sentence that is not accurate

**Severity: Minor**
**`plugins/superb/skills/pipeline/references/run-state.md:95-97`**,
**`plugins/superb/skills/pipeline/references/fix-loop.md:502-506`**

The `fixplan` field is required only on a round declaring `M >= 1`, and
`references/run-state.md:95-97` explains the exemption as "absent from an
`M=0 → no round` record, **which dispatched no fix** and so had nothing to plan".
But `M=0` means every targeted F-ID closed by deletion or user-ruled false
positive, and a claim **deletion** is a dispatched edit with a commit —
`references/fix-loop.md:224-227` says only that its commit stays out of the
coverage union, not that it does not exist. So an iteration that closes five claim
findings by deleting five claims implements remediation across five sites with no
fix plan on disk, and the grammar records the round as one that "dispatched no
fix". Spec requirement 3 is that remediation is planned before it is implemented
"in both paths".

The linter is consistent with the prose in the safe direction only by accident: the
no-round arm (`tools/check-plugin.py:1389-1423`) rejects `reports`, `coverage`,
reviewer counts, a missing route, a pin route and a missing outcome — it does not
reject a `fixplan` field, so a deletion-only round *may* name a plan even though
`references/run-state.md:96` says the field is absent from this form.

**Fix.** Cheapest correct version: keep the exemption, fix the justification.
`references/run-state.md:95-97` → "absent from an `M=0 → no round` record, whose
closures leave no commit a reviewer can own; a deletion-only iteration still names
its plan when it touched more than one site". Or require `fixplan` on any round
that produced a commit at all, and say so once in
`references/fix-loop.md`'s step 3 where `M` is defined.

---

### The gate's own account of the integration rule is the inverted one

**Severity: Minor**
**`tools/check-plugin.py:1934-1936`**, **`tools/fixtures/run-ok/progress.md:16-17`
and `:49`**, **`tools/check-plugin-mutants.sh:1534`**

Four places state the retired rule as current, and three of them are the documents
that describe what the gate establishes:

- `tools/check-plugin.py:1934-1936`, under *WHAT THIS MODE ESTABLISHES, exactly*:
  "the integration count is 1 wherever the slice count is above 1 and 0 where it
  is 1". The arm forty lines above it
  (`tools/check-plugin.py:1468-1487`, `:1514-1532`) says and does the opposite.
- `tools/fixtures/run-ok/progress.md:49`, under *What `--run` establishes over this
  file*: "`i` is 1 whenever `s` is above 1 and 0 at one slice".
- `tools/fixtures/run-ok/progress.md:16-17`: "`i` is 1 above one slice and 0 at one
  slice" — now false of the file's own contents, since the Phase 4 that Task 6
  added is `2 slice + 0 integration`.
- `tools/check-plugin-mutants.sh:1534`: a comment citing "`i` is 1 whenever
  `s > 1`" as "stated in `SKILL.md` and in `references/run-state.md`", which it no
  longer is in either.

The same fixture states the *correct* rule at `:73-81`, so it contradicts itself
twice. Plan Task 6 Step 5 explicitly required updating the fixture's explanatory
prose ("leaving it stale is the failure it warns about"); the new paragraph was
added and the two old claims were left, and the execution log does not record that.

Kept at Minor rather than Major because nothing executes these lines and the
correct rule is present in the same files — but by this repo's own convention they
are claim findings ("neither enforcement code nor a run's own records is exempt",
`references/fix-loop.md:209-213`), and an auditor asking whether the conditional
rule is enforced reads `tools/check-plugin.py:1934` and concludes that it is not.

**Fix.** Restate all four as the conditional rule: "the integration count is 0 at
one slice, and above one slice is either 1 with a named `boundary:` or 0 with
`no integration boundary` declared".

---

### The reviewer fan-out — the largest dispatch class — has no model-tier instruction

**Severity: Minor**
**`plugins/superb/skills/pipeline/references/implement.md:42-66`**

*Choosing the model* is good, and it is the right answer to checklist item 10:
it refuses a default ("Defaulting every implementer to the strongest model
available is the same mistake as reviewing every task"), gives a three-tier table
keyed to task shape, and requires the tier be named in the dispatch — which
`templates/implementer-prompt.md:8-10` then enforces at the slot. No dispatch
template in the change defaults to the strongest tier.

The gap is scope. The rule binds implementers and fix agents only ("Record the tier
in the dispatch"), while the REVIEW and RE_REVIEW dispatches — `ceil(N/5)` slice
reviewers per phase plus re-reviewers per round, i.e. the largest count of
dispatches in a run — carry no tier instruction at all in `SKILL.md:755-772` or
`references/fix-loop.md:36-112`. And `references/implement.md:53` files
"whole-change review" under **Strongest available**, which reads as the applicable
row for a slice reviewer over a three-commit range.

**Fix.** One sentence in the REVIEW state and one in *Re-review fan-out*: the tier
is chosen per reviewer from the same table and named in the dispatch, with the
strongest tier reserved for the integration reviewer, an `RVJ`, and whole-change
review — a slice over a handful of commits is standard-capable work.

---

## Items checked that produced no finding

- **Item 1, task-level review.** The five-pattern sweep
  (`tools/check-plugin.py:1868-1880`) is green, and I re-swept by hand for
  `adversarial`, `review-package`, `task reviewer` and `passed task review`: the
  only survivors are the historical explanations in
  `references/implement.md:4-10`, `SKILL.md:1275-1279` and
  `plugins/superb/skills/pipeline/README.md:99-106`, which the spec requires to
  stay. No instruction dispatches a reviewer, a fix or a re-review on a task's
  completion. (The one sentence that *describes* per-task review is the
  `SKILL.md:672-674` finding above.)
- **Item 2, advancing before `RV`.** Close-out ordering is correct in both
  authorities: `references/fix-loop.md:121-135` checks `RV` at step 0 and writes
  `Current State` forward at step 1; `SKILL.md:810-817` lists the `RV` condition
  first and says why ("the others all pass vacuously when REVIEW never ran"); the
  Continuation Law (`SKILL.md:857-866`) runs `RV` before close-out. The
  findings-only advance predicate the plan predicted has been closed
  (`references/fix-loop.md:115-118`). `grep -n 'no open blocking'` over the skill
  returns eight hits, all either paired with the `RV` condition or at GATE 2 where
  an empty ledger is correct.
- **Item 5, open-findings precedence.** Correct and explicit:
  `references/run-state.md:225` sits above both the `REVIEW` and `PASS` rows, and
  `:230-234` states the every-box-`[x]` case in words. (The arm that enforces it
  mechanically is the Probe-2 finding.)
- **Item 6, fix-plan bypasses.** The `≤3 findings` direct path is gone; the sole
  route is `FINDINGS → FIX PLAN → FIX IMPLEMENTATION`
  (`references/fix-loop.md:330-346`), stated in the same order in `SKILL.md:785-789`
  and `references/run-state.md:95-100`, with an arm at
  `tools/check-plugin.py:1608-1624` that checks both the field and the file's
  existence. The one residual is the `M=0` case above.
- **Item 7, pre-`RV` repair.** Correct everywhere except
  `references/parallel.md:122-123`. `references/implement.md:100-113` and `:125-134`
  state the four prohibitions explicitly; the `<phase> pre-RV` Counters row is gone
  from `templates/findings.md:81-96` and nothing references it —
  `grep -rn 'pre-RV' plugins/` returns nothing.
- **Item 8, integration reviewer.** The arm is complete and correct:
  `tools/check-plugin.py:1533-1542` rejects `nint != 0` at one slice
  unconditionally (the gap the Task 5 log flagged for Task 6 was already closed by
  the pre-existing second branch, as the Task 6 log records), `:1514` requires a
  named boundary above one slice, `:1525` requires the declared absence, and
  `:1430-1431` keeps `RVJ` at `0 slice + 1 integration`. `run-ok` exercises all
  four shapes (Phases 1–4). The prose defects are the two findings above.
- **Item 9, stale SDD delegation.** No pipeline file delegates implementation to
  it; the sweep is scoped to `pdir` (`tools/check-plugin.py:1780`) so
  `superb:bug-fix`'s own task-scope use (`skills/bug-fix/SKILL.md:136`, `:140`) is
  untouched, and the root `README.md:213-219` now says whose dependency it is. The
  historical explanations are intact and correct.
- **Item 11, five-way grammar agreement.** Prose, tracker grammar, linter, fixtures
  and mutant citations agree on the `fixplan` field, `C=<n>`, the coverage table's
  row grammar, the `M=0 → no round` form and the three severity tiers; every field
  prose requires is reachable by the linter's regexes (I confirmed the `fixplan`,
  `boundary:` and ledger-row patterns against the shipped fixtures). The
  disagreements found are the integration rule (two findings) and the `M=0`
  `fixplan` absence (one finding).
- **CI and versioning.** `.github/workflows/checks.yml` names all three fixture
  directories in `--run` steps, and every directory under `tools/fixtures/` holding
  a `progress.md` is one of them. Version bumped to `0.12.0` in both plugin
  manifests and the marketplace description rewritten to the per-phase promise.

---

VERDICT: FINDINGS MUST BE FIXED

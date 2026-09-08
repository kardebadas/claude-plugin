# Pipeline gate ownership, lane state, waved sizing and commit-backed review — design

**Status:** approved (user-authored requirements, 2026-09-07)
**Skill:** `superb:pipeline` (`plugins/superb/skills/pipeline/`)
**Base:** `main` at `b07b677` (PR #3, the phase-state-machine migration)
**Scope:** five defects left by PR #3. The phase-based execution model it
installed is correct and is preserved verbatim; nothing here restores per-task
formal review.

## What must not regress

PR #3's invariants stay exactly as they are. Each has a gate arm and mutants
today, and this change adds none of its own that could weaken them:

```
COMPLETING AN IMPLEMENTATION TASK DISPATCHES NO REVIEWER.
REVIEW MAY NOT BEGIN WHILE ANY TASK IN THE PHASE IS UNCHECKED.
ALL REVIEWERS RETURN → CONSOLIDATE → FIX PLAN → DISPATCH FIXES.
PASS IS THE ONLY NORMAL EDGE TO THE NEXT PHASE.
implementation complete != phase complete.
```

An implementation agent still implements, writes tests, runs tests and the
build, self-checks, and repairs compile/test/build failures it finds while
doing so. That is implementation. Formal review begins only when every task in
the phase is `[x]`.

---

## Issue 1 — `RV` vs `RVJ` gate ownership

### Root cause

The round-append grammar and the reopen rule are written for `RV` alone.
`references/fix-loop.md:450` reads *"Only when `RV` is already `[x]` from a
completed step 2 does a re-review reopen it to `[~]` and reclose it with the
round appended"*, and every worked appended round in the skill hangs under an
`RV`. Yet `fix-loop.md:173-177` requires an `RVJ`'s blocking findings to *"run
the fix loop under the **`RVJ`'s own Counters row**"*.

So an `RVJ` fix round has a budget with no defined home, and a run following the
letter of the reopen rule appends it to the phase's `RV` — the wrong gate's
evidence. The linter cannot detect it: `kind` is `"round"` for every appended
record (`check-plugin.py:1244`, `:1392`) and no arm consults the stem a round
hangs under.

### Design

Introduce the conceptual state **`review_gate ∈ {RV, RVJ}`**. A fix loop belongs
to the gate that produced its findings, and every rule that today says `RV`
says `review_gate` instead:

```
review_gate → findings → FIX_PLAN → FIX_IMPLEMENT → RE_REVIEW(review_gate) → clean → CLOSE(review_gate)
```

**The generic terminal operation is `CLOSE(review_gate)`, not `PASS`.** `PASS`
is reserved for **phase acceptance** and means the phase may normally advance —
and a leading lane-join `RVJ` does not accept the joining phase, it only gates
entry to it. Collapsing the two would license exactly the error this issue
exists to prevent. So closing a gate is one operation, and what it unlocks
depends on which gate closed:

```
CLOSE(RV)              → phase PASS
CLOSE(trailing RVJ)    → NEXT PHASE
CLOSE(leading RVJ)     → IMPLEMENT JOINING PHASE
```

```
A CLEAN LEADING RVJ MUST NEVER MARK THE JOINING PHASE PASS.
```

After its leading `RVJ` closes, a joining phase still owes the whole of
`IMPLEMENT → RV → PASS` on its own tasks.

- A round is appended **under its own gate's line**. An `RVJ`-owned round is
  legal; today it is undefined.
- A re-review reopens the gate that raised the findings, never a different one.
  Reopening a joining phase's `RV` because its leading `RVJ` raised findings is
  a violation.
- The `RVJ` shape rule is unchanged: an `RVJ`'s own declaration stays
  `0 slice + 1 integration`. Its *appended rounds* are ordinary `M= C=` fix
  rounds, sized from the fix diff like any other.

### Transitions, stated separately

The two `RVJ` placements have different successors, and neither is written as a
transition today:

```
trailing RVJ (after a Rule 3 split's last sibling):
    phase RV PASS → RVJ → clean → NEXT PHASE

leading RVJ (above a joining phase's first task):
    all contributing lanes PASS → leading RVJ → clean → IMPLEMENT joining phase
```

**A clean leading `RVJ` must not mark the joining phase `PASS`.** It gates
*entry*, never *completion*; the joining phase still owes its own `RV`. The
linter already enforces the underlying rule — an `RVJ` cannot satisfy a phase's
"has a review line" requirement (`check-plugin.py:2346-2352`) — and already
exempts a leading `RVJ` from the review-not-early rule by line number
(`:2255-2258`). What is missing is the prose transition and the tests.

### How it is checked

`marks` is an ordered list of `RV`/`RVJ`/`round` matches, so each round's owning
gate is the nearest preceding gate mark. Two arms:

1. **Round ownership is attributed.** Every appended round is assigned its
   owning gate, and the pass line reports the counts per gate kind. An
   `RVJ`-owned round is accepted.
2. **A gate that raised a blocking finding carries a round of its own.** In
   `--run` mode, join a closed gate's `→ F-…` outcome against `findings.md`: if
   any named F-ID is blocking and `closed`, that gate must carry at least one
   appended round. A gate whose findings were closed under a *different* gate's
   line is the defect this catches.

---

## Issue 2 — lane-aware Current State

### Root cause

Two shipped files contradict each other. `templates/progress.md:11` prescribes
`**Next action:** <the single next unchecked line …>` — singular, one field —
while `references/parallel.md:167` requires *"one `Next action` line per active
lane, each naming that lane's first unchecked line"*. `SKILL.md:176` sides with
the template.

There is **no per-lane tracker syntax at all**: no lane id on the Current State
block, on a field, on a phase heading, or on a task line. `lanes A+B` on an
`RVJ` is free text `SKILL.md:322` itself calls uncheckable.

The linter is hard-wired to one global position. It reads at most two fields via
`re.search` (first match only, `check-plugin.py:2631-2633`); the duplicate guard
at `:2594` is hardcoded to `"Phase"`, so extra `**Next action:**` lines are
silently dropped with no report. And the comparison is actively wrong under
lanes:

```python
if _blockers and _named and max(_named) > _blockers[0][0]:   # :2656
```

That is *latest named position* vs *earliest unfinished phase*. Lane B
legitimately at phase 6 while lane A's phase 2 is open makes it true, so **a
conforming two-lane tracker hard-fails the gate today**. Resume cannot express
lanes either: the precedence table is "the first row that matches is the state,
and its action is **the only** valid next action". No fixture or mutant covers
lanes.

### Design — the canonical grammar

One grammar, no special case. Every tracker writes one line per active lane; a
sequential run has exactly one lane, `A`.

```markdown
## Current State
- **Lane A:** Phase 2 — T3
- **Lane B:** Phase 5 — RV
- **Last updated:** <timestamp>
- **Run directory:** <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/
```

- `**Lane <id>:**` where `<id>` matches `[A-Z][A-Za-z0-9]*`.
- The value is `Phase <phase-id> — <next unchecked line of that lane>`; the
  phase id leads, exactly as the old `**Phase:**` field required, so the
  existing leading-token reader is reused rather than replaced.
- `**Phase:**` and `**Next action:**` are **removed**. Keeping them for
  single-lane runs would mean two grammars and a mode-switch in the linter, and
  a mode-switch branch is what produced most of PR #3's defects.
- A run with no lane in progress writes `- **Lane A:** done` — the phase-less
  form the existing reader already treats as "names no phase", legitimate only
  when nothing is unfinished.

- A lane whose own phases are all `PASS` but whose join has not opened writes
  `- **Lane A:** waiting at join Phase <join>` — a second sanctioned phase-less
  form alongside `done`, so a waiting contributor never names the joining phase
  and rule 2 below stays true.

### Design — lane identity and derivation

**A lane is an active execution branch between a fork and a join.** It is *not*
a maximal chain of dependent phases. In a diamond

```
Phase A
├── Phase B ──┐
└── Phase C ──┴── Phase D
```

the maximal chains are `A → B → D` and `A → C → D`, so `A` and `D` each belong
to two of them. Membership is not a partition, and *"which lane owns this
phase's Current State"* has no answer. Every consumer of lane identity — stable
`Lane A`/`Lane B` ids, per-lane Current State, resume, per-lane advancement
validation, branch points, join detection, leading-`RVJ` ownership, and deciding
when a lane stops being independently active — needs a partition.

So the dependency DAG remains authoritative for **whether** a phase may
execute, and lane ids are orchestration state recording **which concurrent
branch** executes it. They are allocated once, deterministically, at GATE 2, and
stay stable while that branch is active.

Canonical rules:

```
1. A phase is executed by exactly one active lane.
2. Two active lanes never execute the same phase.
3. A fork creates additional active lanes.
4. A join consumes two or more active lanes.
5. Contributing lanes stay separate until the leading RVJ closes clean.
6. After that RVJ closes, exactly one surviving lane owns the joining phase.
7. Retired lane ids are never reused.
8. Lane ids are stable orchestration identifiers, not re-inferred from the
   graph on every read.
9. Dependency edges decide whether phases may execute; lane ids only represent
   concurrent execution branches.
10. A sequential run is exactly one lane: Lane A.
```

**Allocation at GATE 2.** The approved dependency DAG is converted into lane
assignments once, when the plan is approved. The deterministic ordering is
**approved-plan order** — the order the phases appear in the approved plan —
and nothing else. Walking phases in that order:

- the first phase takes `Lane A`;
- at a fork, the successor that comes **first in approved-plan order** keeps the
  forking phase's lane, and each further successor takes the next unused lane id
  (`B`, `C`, …, then `A1`, `A2`, … if the letters run out);
- at a join, the joining phase carries **one** lane id, chosen deterministically:
  the contributing predecessor that appears **first in approved-plan order**
  supplies the surviving lane id. All other contributing lane ids retire when the
  leading `RVJ` closes.

```
before fork:            at the fork A → B, A → C:
Lane A → Phase A        Lane A → Phase B        (first in plan order)
                        Lane B → Phase C        (newly allocated)
```

**Join allocation, stated as an algorithm.** Leaving the survivor unstated would
contradict the whole point of allocating at GATE 2, so there is one rule:

```
contributors    = direct predecessor phases, in approved-plan order
surviving_lane  = lane(contributors[0])
joining_phase.lane = surviving_lane
```

```
approved-plan order:            therefore:

Phase B · lane: A               Phase D · lane: A
Phase C · lane: B               (B is the first contributing predecessor
Phase D · deps: B, C             in approved-plan order)
```

```
JOIN SURVIVOR SELECTION IS DETERMINISTIC.
THE ORCHESTRATOR MUST NOT CHOOSE A JOIN SURVIVOR AT RUNTIME.
THE JOINING PHASE'S PERSISTED `lane:` FIELD MUST EQUAL
THE LANE OF ITS FIRST CONTRIBUTING PREDECESSOR IN APPROVED-PLAN ORDER.
```

The survivor is therefore already written down before the run starts. Runtime
never chooses one; it only performs the collapse the plan already recorded.

**At a join,** both contributing lanes stay active. `Lane A` reaching the end of
its own work writes `waiting at join Phase D`; `Lane B` keeps working. Once
every contributor is `PASS`, the joining phase's owning lane names the leading
`RVJ` — `- **Lane A:** Phase D — RVJ` — and the other contributors stay
`waiting at join Phase D`. Collapse happens at closure, not before:

```
Phase B PASS
Phase C PASS
leading RVJ clean
→ CLOSE(leading RVJ)
→ retain Lane A          (the planned survivor)
→ retire Lane B
→ Lane A owns Phase D
```

`Lane B`'s Current State line is then **removed**, and `B` is never allocated
again in that run. Phase D proceeds normally from there:
`IMPLEMENT → RV → CLOSE(RV) → PASS`. Nothing here lets a clean leading `RVJ`
mark Phase D `PASS`.

### Where the lane assignment lives

The mapping is **persisted, never reconstructed**. Phase headings already carry
`· deps: <phases>` (`run-state.md:62`), so the heading is the one canonical
location and gains one more field:

```
### Phase 4 — <name> · deps: 2, 3 · lane: A
```

- Exactly one `· lane: <id>` per phase heading, `<id>` matching
  `[A-Z][A-Za-z0-9]*`.
- Written at GATE 2 for every phase in the approved plan; fork and join
  transitions are already expressed by *which* id each phase carries, so no
  transition needs recording anywhere else.
- `phase → active lane` is therefore mechanically recoverable from the tracker
  alone after compaction or resume. It never depends on orchestrator memory, and
  it is never recomputed by enumerating dependency chains.
- Current State stays derived-and-checked rather than authoritative: a
  `- **Lane X:**` line whose id no phase heading carries is a defect.

### How it is checked

The linter **validates the persisted mapping**. It never computes a phase's lane
by enumerating maximal dependency chains.

- **Every lane line is read**, via `re.findall`, not `re.search`. A duplicate
  lane id is reported. Zero lane lines with an unfinished phase is reported. A
  lane id in Current State that no phase heading carries is reported.
- **The mapping itself is well-formed.** Every phase heading carries exactly one
  `· lane:`; two ids on one heading is reported (rule 1). Two Current State
  lanes naming the same current phase is reported (rule 2) — that is the
  shared-ancestor and double-owned-join failure.
- **Advancement is per lane, against that lane's own assigned phases.** For each
  active lane, take the phases carrying its id in approved-plan order; its
  current phase may not sit past an unfinished one among them. A lane
  legitimately ahead of *another* lane's open work does not fail. This replaces
  the global `max(_named) > _blockers[0][0]` comparison at `:2656`.
- **The join survivor is the planned one.** For every joining phase: resolve its
  direct predecessors from `deps:`, order them by approved-plan order, read the
  first predecessor's persisted `lane:`, and require the joining phase's `lane:`
  to equal it. A joining phase carrying any other contributor's lane is
  reported — this is what makes the survivor rule mechanical rather than a
  convention, and it is checked against the persisted mapping alone.
- **A join cannot begin early.** For a joining phase, every contributing
  predecessor lane's last phase must be `PASS` **and** the leading `RVJ` must be
  `[x]` before the surviving lane may name the joining phase with an
  implementation action. Naming it with the `RVJ` action itself is legal once
  the contributors are all `PASS` — that is who runs the gate. So `Lane A → D`
  fails while `B` is unfinished, fails while `C` is unfinished, and fails on an
  implementation action while the leading `RVJ` is open.
- **Retired ids are not reused.** A lane retires at the join that consumes it —
  the first joining phase depending on its last phase and carrying a different
  id. Any later phase in approved-plan order carrying that retired id is
  reported (rule 7).
- Resume gains lane rows: the precedence table is evaluated **per lane**, and
  its preamble changes from "the only valid next action" to "the only valid next
  action for that lane". The lane a resumed run picks up is read from
  `· lane:`, not inferred.

---

## Issue 3 — waved reviewer sizing

### Root cause

**An implementation scheduling construct was allowed to set the review
budget.** Waves determine reviewer count in six prose sites
(`SKILL.md:213-214`, `:233`, `:758-760`, `:1010-1013`, `fix-loop.md:44-47`,
`run-state.md:85-87`), all phrased *"one slice per wave, or per adjacent pair of
small waves … which may be more or fewer than `ceil(N/5)`"*. That conflates two
unrelated concerns: which tasks may execute concurrently, and how the landed
diff is partitioned for review. A coarse wave table then silently bought a
smaller review — `N=12` in one wave took one reviewer.

Worse, the `waved` marker is the **sole exemption** from the only `N=`-regime
sizing arm (`check-plugin.py:1537-1538`), and the skill states plainly that the
wave count is not on the line and therefore not re-derivable (`SKILL.md:233`).
So `N=12 waved → 1 slice` and `N=12 waved → 9 slice` are both accepted. No
fixture uses the marker; no mutant defends the rule.

### Design

**Reviewer count comes from task count, and from nothing else.**

```
slice_reviewers = ceil(N / 5)
```

| Tasks in phase (N) | Slice reviewers |
|---|---|
| 1–5 | 1 |
| 6–10 | 2 |
| 11–12 | 3 |

This is independent of the number of implementation waves:

```
N=8,  W=8  → 2        N=8,  W=1  → 2
N=12, W=12 → 3        N=12, W=1  → 3
```

`N=12, W=1 → 1 reviewer` is forbidden. **Implementation scheduling must never
reduce formal review coverage.**

**Waves are an implementation scheduling construct.** They determine which
tasks may execute concurrently, worktree and branch scheduling, merge ordering,
and the implementation build gates. They do not determine reviewer count, and
they do not constrain where a review slice may be cut.

**Review slices are formed after the phase's implementation has landed.**
Reviewers receive approximately balanced contiguous task/commit ranges covering
the whole phase diff. A slice **may** split work that originally executed in one
implementation wave — that is allowed, because implementation independence and
review partitioning are different concerns. The former restriction *"a wave is
never split across two reviewers"* is removed wherever it appears as a
review-sizing constraint.

```
Phase: 12 tasks, 1 implementation wave

Review:  Reviewer A → T1–T4   / its commit range
         Reviewer B → T5–T8   / its commit range
         Reviewer C → T9–T12  / its commit range
```

Unchanged coverage obligations: every phase commit falls inside at least one
slice, orchestrator-authored glue and fixup commits are assigned to a slice like
any other, and no two slices carry the identical range.

**Tracker grammar.** `W=<n>` may remain on the line where it is useful for
implementation or history, but it is **informational only** and never
participates in reviewer-count arithmetic. The count must be re-derivable from
`N` alone.

```
- [x] RV — review fan-out · N=8 → 2 slice + 0 integration
      · no integration boundary
      · reports p2-review-{a,b}.md · coverage p2-coverage.md → no findings

- [x] RV — review fan-out · N=8 W=8 → 2 slice + 0 integration      (W informational)

- [x] RV — review fan-out · N=12 → 3 slice + 1 integration
      · boundary: the T4 contract consumed by T11
```

The `waved` marker goes: it existed only to exempt a round from the sizing arm,
and there is no longer an exemption to name.

**Integration reviewer: unchanged.** `i` is 0 at one slice. Above one slice it
is 1 only at a real declared cross-slice boundary — a producer/consumer contract
crossing slices, a lane join, a Rule 3 split's integration boundary, or another
genuine interaction no individual slice can evaluate — named on the round as
`· boundary: <what>`; otherwise 0 with `· no integration boundary`. **More than
one slice is not itself a reason.** So an ordinary 8-task phase is 2 slice + 0
integration = 2 reviewers total unless a real boundary exists.

### How it is checked

For every normal `N=` gate round, `s == ceil(N/5)` must hold. The arm loses its
`waved` exemption and gains no `W` dependency: `W`, when present, is parsed and
ignored for arithmetic, so a tracker cannot buy a smaller review by declaring
fewer waves.

Proven in both directions:

```
N=8,  W=8, 2 slices → PASS        N=8,  W=8, 4 slices → FAIL
N=12, W=1, 3 slices → PASS        N=12, W=1, 1 slice  → FAIL
N=8,  W=1, 2 slices → PASS
```

The integration-reviewer arms are preserved as they stand, with their existing
cases: absent with no boundary → PASS; present with a declared real boundary →
PASS; present merely because more than one slice exists → FAIL. Coverage-table
verification is unchanged — every named report has its own row, and no two rows
carry the same range.

Known limit, recorded honestly: the tracker records task and slice counts, not
which commits each slice held, so the linter verifies the count and the recorded
ranges' distinctness rather than that the ranges are balanced.

---

## Issue 4 — no repository change without re-review

### Root cause

`fix-loop.md:390-397` excludes two closure routes from `M`: *"a deletion or a
user-ruled false positive, and the list is closed"*, on the reasoning that
neither *"leaves a commit a reviewer could be assigned"*. That is true of a
false positive and false of a deletion — `fix-loop.md:515-519` says outright
*"Deleting the claim opens no re-review round"*, and `fix-loop.md:472-479`
excludes a deletion's commit from the coverage union.

So today: `finding → delete text → mark closed → no review`. A deletion-only
commit is still a commit.

### Design

The exclusion list is keyed on **whether the repository changed**, not on the
route's name:

```
NO REPOSITORY CHANGE → re-review may be unnecessary
ANY FIX COMMIT       → fix plan → implementation → re-review
```

The closed list becomes **`user-ruled false positive`** and **`withdrawn`** —
the two routes that produce no commit. `deleted` comes off it and behaves like
any other fix: fix plan, deletion commit, focused re-review, then close.

**`withdrawn` is narrow, and defined so it cannot become an escape hatch.** A
finding is `withdrawn` when it is removed during consolidation or reconciliation
because it is:

- an exact **duplicate** of another stable F-ID;
- **malformed**, or not actually a finding;
- **superseded** by another finding that fully represents the same issue;

**and no repository change has been made for that finding.** A finding may be
marked `withdrawn` only *before* any fix commit for it exists. The ledger
records the reason:

```
withdrawn → <reason> → superseded by F-NNN | duplicate of F-NNN | malformed
```

`withdrawn` does **not** mean any of these, and each is a route to the fix loop
rather than out of it: the orchestrator disagrees with the finding; the finding
seems low value; ignoring it is the easiest fix; text or code was deleted; code
was changed; tests were changed; documentation was changed; the finding was
partially fixed; a reviewer stopped mentioning it.

**If any repository-changing commit exists for the finding, `withdrawn` is
forbidden** — that finding takes `fix plan → fix implementation → re-review →
closure` like any other.

`M=0 → no round` is redefined: legal only when the iteration produced **zero
repository-changing commits**. Any commit means `M ≥ 1` and a round is owed. A
deletion's commit rejoins the coverage union like every other fix commit.

### How it is checked

The linter cannot count commits, but it can refuse an `M=0` record that names a
commit-producing route. `deleted` becomes a **forbidden** route on an `M=0`
round, exactly as `pinned by` already is (`check-plugin.py:1421`), and the
accepted-route regex narrows to `user-ruled false positive|withdrawn`.

`withdrawn` carries two further checks, because an unqualified `withdrawn` is
precisely the escape hatch the definition forbids:

- **It must state its reason.** A `withdrawn` route on a round is accepted only
  in the form `withdrawn → superseded by F-NNN`, `withdrawn → duplicate of
  F-NNN`, or `withdrawn → malformed`. A bare `withdrawn` is reported.
- **It must not name a commit.** A ledger row whose `State` is `withdrawn` while
  its `Closed by` cell names a commit hash is reported: a finding with a fix
  commit cannot be withdrawn, and the hash is the evidence that one exists.

Neither check can count commits either, and that limit is recorded rather than
implied: the tracker and ledger are what the gate reads, so the reachable half
is a route naming a hash and a route naming no reason.

---

## Issue 5 — committed run artifacts

### Root cause

The skill's law is unambiguous — `SKILL.md:157`: *"**Never `git add` anything
under `docs/superpowers/`** — run state, specs and plans are all **deliberately
local-only**"*, repeated in `run-state.md:19`, `fix-loop.md:601`, and two
rationalization/red-flag rows. It is enforced by prose alone: there is no
`.gitignore` coverage, which is why 41 files are tracked.

History shows two deliberate exceptions, distinguishable by shape: five loose
`runs/*.md` are curated RED-baseline and pressure-test records, four committed
in the same commit as the change they justify; and 17 pre-PR#3 run-directory
files were kept by three standalone commits whose subjects read *"keep the run
record"*.

PR #3's 12 files under `runs/2026-09-07-pipeline-phase-state-machine/` were
never the subject of a keep decision — each rode into a `fix(pipeline)` commit
as a byproduct — and the directory is incomplete as a run record (`findings.md`
plus `agent-output/`, no `progress.md`, `register.md` or `kit.md`).

### Design

**First, the policy itself, because the old one contradicts this design.**
*"Never `git add` anything under `docs/superpowers/`"* cannot coexist with
keeping committed specs and plans, keeping curated loose `runs/*.md` records,
and adding a new one at `runs/pipeline-phase-machine.md`. The rule was written
as a path rule; it was always a *lifecycle* rule. So the canonical distinction
becomes:

```
EPHEMERAL PIPELINE EXECUTION STATE          CURATED PERMANENT DOCUMENTATION
→ local-only                                → may be committed deliberately
→ never git add
```

**Ephemeral, local-only, never `git add`ed** — everything inside a run
directory, `docs/superpowers/runs/<run-directory>/`: `progress.md`,
`register.md`, `kit.md`, `findings.md`, fix plans, `agent-output/`, temporary
review reports, and any other runtime evidence. This protection is not weakened
anywhere in this design, and it gains the mechanism it never had:

```gitignore
docs/superpowers/runs/*/
```

**Curated permanent material — may be deliberately committed** when it is
intended as permanent repository documentation:

```
docs/superpowers/specs/*.md
docs/superpowers/plans/*.md
docs/superpowers/runs/*.md          ← loose files directly under runs/, not directories
```

for example `docs/superpowers/runs/pipeline-phase-machine.md` and
`docs/superpowers/runs/pipeline-phase-seam.md`: distilled records, not live
execution state. *May* be committed is the whole of the permission — **nothing
auto-commits them.** They are merely allowed to be tracked when someone decides
they are documentation.

```
runtime directory      = forbidden
curated permanent document = intentional, deliberate exception
```

The whole `docs/superpowers/` tree does **not** become trackable by default, and
`docs/superpowers/` is deliberately *not* the ignore pattern: it would hide the
curated documentation this design creates.

**The wording sweep.** The absolute phrasing is replaced with the precise rule

```
Never `git add` pipeline runtime directories under
docs/superpowers/runs/*/.

Curated permanent specs, plans, and loose runs/*.md records may be
deliberately committed when they are repository documentation.
```

at each site that states the absolute form, and only there: `SKILL.md:157-158`,
`:623`, `:950`, the rationalization row at `:1170`, the red-flag text at
`:1324`, `run-state.md:19-20`, and `fix-loop.md:600-601`. Sites that merely name
the run-directory path, or that make the Stage 5 hand-off the durable artifact,
keep their meaning — a run directory is still local-only and the hand-off is
still what survives.

**Then the tree itself:**

- **Remove** the 12 files under `runs/2026-09-07-pipeline-phase-state-machine/`.
- **Keep** the PR #3 spec and plan, following the `66a1041` / `c5aacb6`
  precedent that specs and plans behind merged work are retained.
- **Keep** every pre-PR#3 file: removing them destroys deliberately-kept
  history, and `specs/2026-08-31-craft-depth-design.md:4` cites one of them as
  its evidence base.
- **Distil** the review history into one concise permanent record at
  `docs/superpowers/runs/pipeline-phase-machine.md`, matching the established
  loose-file pattern of `pipeline-phase-seam.md` and `pipeline-wave-seam.md`.
- **Close the mechanism gap** with the `runs/*/` ignore rule above, leaving loose
  curated `runs/*.md` trackable. That is the distinction the history already
  draws, and without it the next run re-commits its artifacts. Already-tracked
  files are unaffected, so the kept pre-PR#3 directories stay.

Nothing under `runs/` is referenced by CI or the linter: `check-plugin.py:1013`
parses only the fenced tree inside `run-state.md`, and CI lints
`tools/fixtures/` exclusively.

### How it is checked

A rule with no mechanism is the defect this issue is about, so the removal is
backed by a gate rather than by discipline. An arm asserts the root
`.gitignore` carries a pattern covering `docs/superpowers/runs/*/`, with a
mutant deleting the line. That is deliberately a check on the *ignore rule*
rather than on the tree: the pre-PR#3 run directories are tracked by an explicit
keep decision, so an arm phrased "no run directory is tracked" would fail on
history it must not touch. The ignore rule stops the next run committing its
artifacts; the grandfathered files stay because git ignores only what is
untracked. **No arm rejects a deliberately retained, already-tracked run
directory** — the check enforces the ignore mechanism, never the shape of
history. And because the pattern is `runs/*/` and not `docs/superpowers/`, a
loose curated `runs/*.md` record stays trackable, which a second arm asserts by
checking that the ignore rule does not cover it.

---

## Gates and tests

Repo convention: a mechanisable rule gets a `check-plugin.py` arm plus a mutant
proving the arm can fail; the arm goes in first and goes RED against the
un-fixed repo. Contractual prose gets a held-phrase pin.

| # | Test | Mechanism |
|---|---|---|
| 1 | Leading RVJ blocker → fix → same RVJ re-review → `CLOSE(RVJ)` → **IMPLEMENT joining phase, not phase PASS** | `run-rvj-fix` fixture + arm |
| 2 | Trailing RVJ blocker → fix → same RVJ re-review → `CLOSE(RVJ)` → NEXT PHASE | fixture + arm |
| 2a | `RV` clean → `CLOSE(RV)` → phase PASS | existing arm + fixture |
| 2b | A clean leading RVJ over a joining phase with unchecked tasks never reads as PASS | `run-lanes` fixture + existing no-advance arm |
| 3 | Diamond `run-lanes` fixture (`A → B,C → D`) in a legal two-lane state → PASS | `run-lanes` fixture |
| 3a | Fork of `A` → `Lane A` keeps `B` (first in approved-plan order), `Lane B` allocated for `C` | fixture + mapping arm |
| 3b | A shared ancestor assigned to two active lanes → FAIL | mutant |
| 3c | Joining phase `D` assigned to — or named current by — two lanes → FAIL | mutant |
| 4 | Lane A points past an unfinished phase of its own assignment → FAIL | mutant |
| 5 | Lane B points past an unfinished phase of its own assignment → FAIL | mutant |
| 5a | `Lane A → D` while `B` unfinished → FAIL; while `C` unfinished → FAIL | mutants |
| 5b | `Lane A → D` on an implementation action while the leading `RVJ` is open → FAIL | mutant |
| 5c | `CLOSE(leading RVJ)` retires `Lane B` and leaves `Lane A → D` as the sole owner → PASS | fixture |
| 5d | A retired lane id carried by a later phase → FAIL | mutant |
| 5e | Join takes the first contributing predecessor's lane (`B` lane A, `C` lane B, `D` deps B,C lane **A**) → PASS | `run-lanes` fixture |
| 5f | Join takes another contributor's lane (`D` deps B,C lane **B**, `B` first in plan order) → FAIL | mutant |
| 6 | `N=8 W=8 → 2 slice` PASS; `N=8 W=1 → 2 slice` PASS; `N=12 W=1 → 3 slice` PASS | fixture + `ceil(N/5)` arm |
| 7 | `N=8 W=8 → 4 slice` FAIL; `N=12 W=1 → 1 slice` FAIL | mutants |
| 8 | Integration reviewer stays boundary-conditional | existing arms, unchanged |
| 9 | Deletion fix commit requires a fix plan and a re-review | route-list arm + mutant |
| 9a | `withdrawn` as a duplicate of `F-NNN`, no repository change → `M=0` may be legal | route-form arm + fixture |
| 9b | `withdrawn` with a commit hash in `Closed by` → FAIL | ledger arm + mutant |
| 9c | A bare `withdrawn` naming no reason → FAIL | route-form arm + mutant |
| 9d | A deletion route on an `M=0` round → FAIL | forbidden-route arm + mutant |
| 10 | `M=0 → no round` legal only with zero repository commits; `user-ruled false positive` with no commit → legal | forbidden-route arm + mutant |
| 10a | A runtime run directory is covered by the root `.gitignore` → PASS | `.gitignore` arm |
| 10b | The ignore rule removed → FAIL | mutant |
| 10c | A loose curated `runs/*.md` record stays trackable (not covered by the rule) → PASS | `.gitignore` arm |
| 11 | No task completion dispatches a formal reviewer | existing sweep, unchanged |
| 12 | Review cannot start before all phase tasks complete | existing arm, unchanged |
| 13 | Failed re-review cannot advance the phase | existing arm + new gate-scoped case |
| 14 | Clean re-review can advance | fixture |
| 15 | Resume during an RVJ fix loop resumes the same RVJ | precedence-table row + fixture |

Both directions are required for every new arm: every shape the templates
prescribe must pass, and every wrong shape must fail. PR #3's costliest defects
were arms that failed conforming input.

## Non-goals

- Restoring per-task formal review, in any form.
- Changing Stages 1–3, `superb:bug-fix`, `superb:craft`, or `superb:setup`.
- Editing `superpowers:subagent-driven-development` — outside this repo.
- Using `superb:pipeline` to implement this change.
- Pushing, merging, or publishing.

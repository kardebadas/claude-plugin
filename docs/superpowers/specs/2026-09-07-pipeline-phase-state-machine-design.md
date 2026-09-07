# Pipeline phase state machine — design

**Status:** approved (user-authored requirements, 2026-09-07)
**Skill:** `superb:pipeline` (`plugins/superb/skills/pipeline/`)
**Scope:** Stage 4's execution architecture, its fix loop, its tracker, its
resume path, and the gates that enforce them. Stages 1–3 change only where they
must to support the new execution model.

## Problem

A pipeline run spends most of its agents reviewing. An 8-task phase dispatches
on the order of 28 agents, of which 8 implementers do the work; the rest review,
fix, and re-review one task at a time. The run interleaves implementation,
review, planning, and remediation into one continuous loop, so a phase is never
a coherent unit of acceptance and the same code is inspected many times over.

## Root cause

**Two review layers run at once, and only one of them is this skill's.**

Pipeline's own review layer is already phase-level and always was: the `RV`
tracker line, sized `ceil(N/5)` over commit ranges, consolidated into
`findings.md` with stable `F-NNN` IDs (`SKILL.md:185-335`, `:870-908`).

On top of that, Stage 4 step 1 delegates implementation to
`superpowers:subagent-driven-development` (`SKILL.md:693`,
`references/fix-loop.md:15-17`), and that skill's process **is** the per-task
loop:

- an implementer returning `DONE` mechanically produces a review dispatch
  (`subagent-driven-development/SKILL.md:157`), and the only edges into
  task-completion are gated on a reviewer verdict (`:101`, `:104`);
- a task completes only at **zero open findings at any severity**, via an
  **uncapped** fix ⇄ re-review loop (`:203-209`, `:491-495`);
- an adversarial second reviewer fires on trigger (`:179-198`);
- there is **no implementation-only mode**. Every "skip"-adjacent string in it
  is a prohibition, not an option (`:10`, `:475`, `:480`);
- it is **phase-unaware**: `grep -i phase` over all seven of its files returns
  nothing, and its brief extractor only matches `^#+ Task N`, so a phase heading
  is structurally invisible to it;
- it is **not ours**. Its source of truth is a personal skill outside this
  repository, mirrored into the plugin cache, and its own text warns that a
  superpowers update silently overwrites that mirror.

Pipeline then imports the per-task loop into its own wave path explicitly:
`references/parallel.md:100-104` ("run its **per-task review** … task reviewer,
fix loop, adversarial pass … exactly as `subagent-driven-development`
prescribes" / "When every member has **passed its task review**, merge in task
order"), `references/fix-loop.md:17-20`, and `SKILL.md:473-476`.

Two corroborating signals that this is a graft rather than the design:

1. **A translation layer exists only to absorb the leak.** SDD's task reviewer
   emits `Important`, "right for one task's diff, **wrong for a phase**"
   (`references/fix-loop.md:77-79`), so the skill carries a re-tag predicate, a
   template mirror (`templates/findings.md:35`), and four linter arms
   (`tools/check-plugin.py:254`, `:269`, `:272-279`) to convert a vocabulary it
   should not be importing. The audit plan records the count: `Important`
   "occurs **zero** times in this skill. It reached the MIPS-7319 ledger **120
   times** from `subagent-driven-development/task-reviewer-prompt.md`"
   (`docs/superpowers/plans/2026-09-04-pipeline-audit-fixes.md:343`).
2. **Nothing tests the per-task layer.** Every review assertion in the
   1897-line linter is about the phase-level `RV`/`RVJ` grammar. The per-task
   requirement is unenforced and untested — it costs agents at runtime and buys
   no checked guarantee.

## History (investigated, not assumed)

The premise that this is a regression from an earlier phase-based design is
**false**, and the redesign is therefore new work rather than a restoration.

- Both layers have coexisted since the skill's first commit here, `b8b2d9b`
  (2026-08-25), which imported it verbatim from a local skills directory — so
  the architecture arrived fully formed from outside version control.
  `references/parallel.md` step 5 prescribed per-task review on day one.
- `git log --all -S'passed task review' -- '*pipeline*'` and `-S'adversarial'`
  each return **exactly one commit: `b8b2d9b`**. The phrases were never edited.
- Stage 4's steps 1→2→3→4 are structurally identical from genesis to HEAD.
- The only regime change in the review architecture went the other way —
  `fa7fee1` (2026-09-01) **hardened** the phase layer, because a real run
  "skipped Stage 4's review fan-out for seven consecutive phases and nothing
  detected it". The cause was a vacuous predicate: every gate read
  "`findings.md` has no open blocking IDs", which is "vacuously true when review
  never runs: an empty ledger is exactly what an unreviewed phase looks like,
  and also what a clean one looks like". `RV` is the fix; genesis had no `RV`.
- The one formula genuinely replaced is the re-review sizer: `ceil(M/3)` →
  one reviewer per file cluster (`f6cc7e6`), because in the run that measured it
  the rule "was overridden downward and the override logged as 'DEVIATION,
  recorded'" every time it was applied.

**Consequence for this design:** `RV` and its evidence fields are load-bearing
anti-regression machinery and must not be weakened to save agents. Cost
reduction comes from deleting the duplicated task layer, not from thinning the
phase gate.

## Old state machine

```
for each phase:
  for each wave:
    for each task in wave:
      IMPLEMENT task  ──►  TASK REVIEW  ──►  findings? ──► FIX ──► TASK RE-REVIEW ──┐
                                   │                                    (uncapped)  │
                                   └────────────── zero findings at any severity ◄───┘
                                                          │
                                            high-risk trigger? ──► ADVERSARIAL ──► fix/re-review
    merge wave members in task order
  PHASE REVIEW (ceil(N/5) slices + integration whenever s > 1)
  blocking findings? ──► recurse pipeline in fix-mode
                            standard path: writing-plans → SDD → review fixes
                            direct path (<= 3 findings, exact file:line): NO PLAN
                         ──► re-review (one slice per fix-diff file cluster)
  ADVANCE on RV [x] + no open blocking IDs + green tests + tracker saved
```

Two defects in it:

1. The inner per-task loop is a second, uncapped acceptance gate that the phase
   gate then repeats. Implementation, review, planning, and remediation
   interleave, so no phase is ever a transaction.
2. The direct-fix path lets remediation begin with no plan artifact.

## New state machine

A phase is the unit of execution **and** of acceptance. It is a transaction with
named states; the tracker on disk is the state register.

```
PHASE N

  IMPLEMENT ──────────────────────────────────────────────────────────┐
    all tasks in the phase, sequential / waved / parallel.            │
    NO reviewer is dispatched when a task completes.                  │
    Implementers fix their own compile errors, failing tests and       │
    obvious mistakes — that is implementation, not the fix loop.       │
         │ every task [x] with a hash, build gates green              │
         ▼                                                            │
  REVIEW  (RV [~])                                                    │
    ceil(N/5) slice reviewers over exact commit ranges covering the   │
    whole phase diff. Integration reviewer ONLY at a declared         │
    integration boundary. ALL reviewers complete before any fix.      │
         │ consolidate + dedup + stable F-NNN IDs + severity          │
         ▼                                                            │
  DECIDE                                                              │
    ├── no blocking findings ──────────────────────► PASS             │
    └── blocking findings                                             │
         ▼                                                            │
  FIX_PLAN   (artifact on disk, required, before any fix dispatch)     │
         ▼                                                            │
  FIX_IMPLEMENT                                                        │
    minimum reasonable fix agents: one per independent file cluster.   │
    Fix agents do not review their own fixes as a substitute for       │
    RE_REVIEW.                                                        │
         ▼                                                            │
  RE_REVIEW  (RV reopened [~], round appended)                        │
    sized from the fix diff: one slice per file cluster (C=<n>).      │
    Scope: were the blocking findings resolved; the fix diff;          │
    regressions; interactions between fixes; the phase against spec.   │
         │                                                            │
         ├── blocking findings remain ──► back to FIX_PLAN ───────────┘
         │      (next round; convergence rule and caps still apply)
         ▼
  PASS   RV [x] with its evidence, close-out write saved
         ▼
  NEXT PHASE
```

### The advancement invariant

> **`PASS` is the only edge into `NEXT PHASE`.** A phase reaches `PASS` only
> when, all of it written to disk and saved: every implementation task is `[x]`
> with a commit hash; the phase's required tests and build gates are green; its
> `RV` line is `[x]` carrying its per-round evidence; every blocking finding
> scoped to the phase is `closed` or `false-positive`; every fix plan the rounds
> name exists; and the last round's re-review returned no blocking findings.
>
> Implementation complete is not phase complete. All task lines `[x]` is not
> phase complete. An empty ledger is not phase complete.
>
> When the fix loop cannot converge, the run **stops and asks the user**. A cap
> or the convergence rule firing never licenses `NEXT PHASE`.

### Review ownership

| Role | Responsible for | Never |
|---|---|---|
| Implementation agent | one task; local tests; build; self-check; commit; report | formal acceptance |
| Phase reviewer | reviewing the completed phase; raising findings | fixing them; initiating a fix |
| Fix planner (the orchestrator) | consolidating findings; the fix plan artifact | implementing the fixes |
| Fix agent | implementing the approved fix plan; running its tests | substituting for re-review |
| Re-reviewer | validating the fix diff; deciding whether the phase passes | fixing |

No agent and no loop plans, implements, reviews, and fixes at once.

## Required changes

### 1. An implementation-only primitive, owned in-repo

Stage 4 stops delegating implementation to
`superpowers:subagent-driven-development`. Pipeline gains its own
implementation-only executor, so the invariant is mechanical rather than
requested:

> **Completing an implementation task dispatches no reviewer.**

- `references/implement.md` — the executor: wave dispatch, the dispatch
  contract, the self-check, the commit and hash rule, the return contract, and
  the explicit prohibition on task-level review.
- `templates/implementer-prompt.md` — the dispatch payload. Keeps what was
  worth having from SDD's implementer contract (TDD first, ask before guessing,
  quality gates, self-check, thin return with detail in a file) and drops
  everything about review.
- `scripts/task-brief` — pipeline-owned brief extraction, replacing the bare
  relative citations of SDD's scripts at `references/parallel.md:93` and `:126`.
  Pipeline has no `scripts/` today, so those paths never resolved from the file
  that cites them.

Cutting SDD also removes the `review-package` dependency, which existed only to
feed the per-task reviewer.

`superpowers:subagent-driven-development` leaves pipeline's composed-skill
roster. It remains available to `superb:bug-fix`, which is out of scope here.

### 2. Stage 4 as an explicit state machine

Stage 4 is rewritten around the states above, each with its entry condition, its
exit condition, and its tracker representation. Review may not begin until every
implementation task in the phase is `[x]`. Every reviewer completes before any
fix is dispatched.

### 3. A required fix plan artifact

Remediation is planned before it is implemented, in both paths — the direct-fix
path's exemption from planning is removed. The fix plan is an artifact at
`agent-output/p<phase>-fixplan-r<round>.md`, named on the round in the tracker,
and it states: the findings in scope; root cause where known; affected
files/components; dependencies between fixes; tests required; whether fixes may
run in parallel; how each fix will be verified.

A fix plan is much smaller than the implementation plan. Ordinary fixes do not
re-enter brainstorming or the master plan.

### 4. The integration reviewer becomes conditional

Today `i` is 1 whenever `s > 1` (`SKILL.md:210`). It becomes 1 only at a
**declared integration boundary**:

- a Rule 3 split's siblings joining, or two lanes joining — both already
  mandatory as `RVJ`;
- a contract introduced in one slice and consumed in another that no single
  slice's range covers.

Otherwise `i` is 0, and a multi-slice round records `no integration boundary` so
the choice is visible and checkable rather than silent. Slice coverage of the
whole phase diff is unchanged: every commit still falls inside some slice.

### 5. Fix agents sized by cluster, not by finding count

One fix agent per independent file cluster in the fix plan; related findings
batch into one agent. Five related findings take one or two agents, not five.

### 6. Tracker and resume

The `RV` line keeps its grammar and gains a `fixplan` field on any round that
dispatched fixes. Resume derives state from disk with this precedence:

| Disk state | State | Only valid next action |
|---|---|---|
| any `[~]` line | reconcile first | Rule 4 reconciliation |
| open register entry | blocked | ask the user |
| open blocking F-ID scoped to the phase | `FIX_PLAN`/`FIX_IMPLEMENT`/`RE_REVIEW` | continue **this** phase's fix loop |
| all phase tasks `[x]`, `RV` `[ ]` | `REVIEW` | review the current phase |
| `RV` `[~]` | `REVIEW` | reconcile against `agent-output/` |
| round names a fix plan that does not exist | `FIX_PLAN` | write the fix plan |
| `RV` `[x]`, no open blocking IDs, tasks `[x]` | `PASS` | close out, then next phase |

Resume must never re-run completed implementation tasks and must never advance.

### 7. Delete what the graft required

The `Important` re-tag survives as a general rule for any reviewer reporting in
another vocabulary, but stops naming SDD as its source; the linter arms that
pin the SDD attribution are updated with it.

### 8. Documentation must stop promising per-task review

`README.md:143-147` currently promises "Every task is reviewed by an agent that
did not write it". That becomes a phase-level promise. The Stage→skill mapping
at `README.md:207` and `plugins/superb/README.md:10` follow.

## Gates (how this is proven)

Repo convention, from the audit plan: mechanisable rules get a linter arm plus a
mutant proving the arm can fail; contractual prose gets cross-file consistency
sweeps. Arms go in first and go RED against the un-fixed repo.

| Gate | Establishes |
|---|---|
| no-task-review sweep | no file in the plugin instructs a reviewer, fix, or re-review on the completion of an individual task |
| no-SDD-in-pipeline sweep | pipeline's files do not delegate implementation to `subagent-driven-development` |
| review-not-early arm | a tracker whose `RV` is `[~]`/`[x]` while a task line in that phase is unchecked fails |
| no-advance-on-open-findings arm | `Current State` naming a later phase while an earlier phase has an open `RV`, an open blocking F-ID, or a named-but-missing fix plan fails |
| fix-plan-precedes-fix arm | a round that names fix evidence but no existing fix plan file fails |
| conditional-integration arm | `i=1` requires a named boundary; `i=0` with `s>1` requires the `no integration boundary` declaration |
| resume fixtures | a run with tasks `[x]` and `RV` `[ ]`, and a run mid-fix-loop, each lint clean and each name exactly one valid next action |

## Non-goals

- Changing Stages 1–3 beyond what the new Stage 4 requires.
- Weakening the `RV` gate, its evidence fields, or slice coverage of the phase
  diff to reduce agent count.
- Changing `superb:bug-fix`, `superb:craft`, or `superb:setup` behaviour.
- Editing `superpowers:subagent-driven-development` — it is outside this repo.
- Pushing, publishing, or merging anything.

## Expected effect (8-task phase, single wave)

| | Old | New |
|---|---|---|
| Implementers | 8 | 8 |
| Task reviewers | 8 | 0 |
| Task fix agents + re-reviewers | ~8 | 0 |
| Adversarial passes | 0–8 | 0 |
| Phase reviewers | 2 slices + 1 integration | 2 slices + 0 |
| Fix planning | 0 agents (or a `writing-plans` run) | 0 agents (orchestrator) |
| Fix agents | 1 per finding-ish | 1–2 per cluster |
| Re-reviewers | 1–2 | 1–2 |
| **Total** | **~28+** | **~12** |

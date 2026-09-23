# Planning: stages 01–07

Load during the intent read, question synthesis, the human gate, design, spec,
master plan and phase fan-out. After stage 06 closes the phase set is immutable.

**Not yet enforced by code:** stage transitions 01–05 and the close of stage 07
have no dedicated functions (write them through `locked_tracker_update`; the
`## Stage`, `## Intent` and `## Questions` grammars are validated). Stage 06
closes only through `close_phase_set`, below.

## Stage 01 — Intent read

- Dispatch **exactly three** `pipeline-auto-intent-reader` agents. Sequentially
  if `worker_limit < 3`; never fewer.
- Each returns strict JSON: what the request says (user's words quoted), implies
  (basis named), leaves unstated, puts out of scope, and what the repository
  already provides (`file:line`).
- Reconcile into one intent brief. **Conflicts are flagged, never resolved** —
  record all three readings verbatim. Never take the majority reading.
- Unresolved stage-01 conflicts take stage-03 slots **before** any stage-02
  question (`## Questions` origin `intent-conflict` ranks first).
- The brief is frozen after stage 03. A later contradiction escalates; the human
  amends it.

Tracker: `## Intent` rows `reader-1`, `reader-2`, `reader-3`, `brief`; states
`pending → dispatched → published → frozen`.

## Stage 02 — Question synthesis

- Dispatch **exactly three** `pipeline-auto-brain` agents with
  [../prompts/brain-proposal.md](../prompts/brain-proposal.md) — never
  `prompts/brain.md` (no qid exists yet) and never another agent (not
  `architecture-discovery`, not `brainstorm-architect`).
- Merge as that template says: drop the inadmissible, dedupe, rank by blast
  radius, cut to **four** including intent-conflict slots. Ranking and cutting
  are routing: answer none, add none of your own.
- Admissibility here is `quorum.md`'s criteria 1, 3 and 4 with criterion 2
  **inverted**: a gate question needs what only the user knows. Do not spend a
  slot on what the repository or a quorum could decide.

## Stage 03 — The one gate

**One `AskUserQuestion` call, at most four questions.** The only guaranteed
human interaction in the run.

- Spend slots on what only the user knows: budget, deadline, users, purpose,
  which product this is.
- Record each answer as `H-<n>`, `Provenance: human`, a stable axis id,
  `Decision action: none` unless it grants a transition.
- "Sounds good", "continue", "you decide" answers nothing. Never record it as an
  answer.
- Everything decided later traces to these answers through `consistent_with`, or
  it escalates.

There is no second approval gate. After stage 03, everything is quorum or
escalation.

## Stage 04 — Design and review class

**REQUIRED SUB-SKILL:** `superpowers:brainstorming`.

Fix each phase's `review_class` (`final-only` or `required`) **here, before any
plan exists**, with a specific risk reason. See `execution.md` for what each
class buys. A phase is never reclassified downward — not on reflection, not by
quorum, not to fit capacity or budget. You set it once, here, and the plan
carries that classification in its phase metadata; after this stage only a
ratchet whose trigger has already fired raises it (`execution.md`).

## Stage 05 — Spec

**REQUIRED SUB-SKILL:** `superpowers:writing-plans`. Records the selected
architecture and boundaries, not a chat summary. Save under the repository's
convention, else `docs/superpowers/specs/<feature>-design.md`.

## Stage 06 — Master plan

**REQUIRED SUB-SKILL:** `superpowers:writing-plans`. Every phase, its
dependencies, its phase-plan path, its planned verification, its `review_class`
and reason.

- **The phase set is immutable once stage 06 closes.** The run cannot create
  work for itself afterwards. This is what makes the completeness freeze in
  `review.md` a guarantee.
- **Close stage 06 with `close_phase_set(run_dir, phase_ids=[...])`**, passing
  every phase id the master plan lists, in its order. It writes them into
  `## Run`'s `phase_set`, completes stage 06 and opens stage 07
  (`fan-out-phase-plans`) in one transition. The tracker enforces the seal,
  for `import_phase_plan` and for any raw transition alike: it is written
  only by the transition that closes an active stage 06, it never changes,
  stage 06 cannot complete without it, a phase row is born only while stage
  07 is active, and no phase row outside the seal can be written. The tracker
  does not check the ids against the master plan, which it cannot read: pass
  them exactly. A second call with the same ids is inert once stage 06 is
  complete; other ids raise.
- **Discover the target repository's test runner** from its CI config, manifest
  and existing tests, and record it. Never assume one. Record the lint, format
  and coverage commands the same way. Never invent a coverage percentage: no
  explicit policy means a stage-03 question or behaviour-focused testing with no
  number.

## Stage 07 — Phase fan-out

One `superpowers:writing-plans` worker per phase, capped by `worker_limit`.

- At most `MAX_TASKS_PER_PHASE` (12) genuine tasks per phase; more means split.
- **A planner never invents an interface.** An unresolved interface returns
  `NEEDS_CONTEXT` or `PLAN_CONFLICT` with a question record — the only route into
  `quorum.md`. A planner never dispatches brains.
- Each approved plan is imported with `import_phase_plan(run_dir,
  phase_plan=...)`, which appends the phase row, task rows and path in one
  transition. A second import of the same phase raises.
- Import one plan per sealed phase id and no other: a plan for a phase outside
  `phase_set` is refused.
- **Close stage 07 by freezing the dispatch budget**, once every sealed phase
  is imported. The tracker refuses the freeze before the seal exists or while
  a sealed phase has no row, and refuses to complete stage 07 before the
  freeze:
  `freeze_dispatch_ceiling(run_dir)` writes `## Run`'s `dispatch_projection`
  (`7 × tasks + 3 × BUDGET_PER_RUN + 5`, every phase priced at 7 whatever its
  class), `dispatch_soft_ceiling` (`ceil(1.25 ×` projection`)`) and
  `dispatch_hard_ceiling` (`2 ×` projection). The tracker checks the first
  write against that formula over the task rows it lands beside, and refuses
  any later change; a human raises the ceiling only through a
  `dispatch.extend-budget` decision (`execution.md`).

### Phase-plan metadata (parsed by `parse_plan_metadata`)

Header, before the first section:

```text
<!-- pipeline-auto-phase: id=<phase-id>; deps=<none-or-phase-ids>; review_class=<final-only|required>; review_reason=<nonempty-reason> -->
<!-- pipeline-auto-phase-suite: id=<same-phase-id>; commands=["<exact-command>","<next-command>"] -->
```

Immediately below each task heading:

```text
<!-- pipeline-auto-task: id=<stable-id>; deps=<none-or-task-ids>; kind=<source|artifact>; batch=<batch-id>; order=<positive-integer>; write_scope=<typed-scopes>; outputs=<none-or-exact-files> -->
<!-- pipeline-auto-task-suite: id=<same-task-id>; commands=["<exact-command>"] -->
```

| Rule | Detail |
| --- | --- |
| Key order | Exactly as shown; `; ` separated |
| Commands | Nonempty JSON string array, execution order, no duplicates |
| Suites | Phase suite always; task suite only for `source` tasks |
| `source` | Changes repository content; `outputs=none`; needs commits, test evidence and separate integration evidence |
| `artifact` | Creates exactly the files in `outputs`; integration `N/A`; never an empty or unrelated commit |
| Kind | Chosen by the plan, never by whether a diff happened to be empty |
| `write_scope` | Comma-separated `file:<repo-relative-file>` or `tree:<repo-relative-dir>` |
| Refused, not normalised | Absolute paths, `..`, backslashes, empty segments, globs, symlink aliases |
| Conflict | Equal files; trees by equality or ancestry; a tree conflicts with every file inside it (`scopes_overlap`) |

No absolute home-directory path in any committed file, scope, output or command.

## The executable-plan gate

Before stage 08, confirm:

- spec, master plan and every phase plan exist on disk;
- shared interfaces settled; no escalation outstanding;
- every phase has 1–12 tasks; task and phase dependencies acyclic and executable
  in master order;
- every metadata comment parses;
- test runner, coverage policy, batches, `worker_limit` and every
  `review_class` explicit.

**Concurrency needs `worker_limit >= 4`.** Brains hold three slots, so
implementation gets `implementation_slot_cap(worker_limit)` = `worker_limit - 3`,
floored at 1 (tasks serialise). Otherwise a blocked task holds the slot needed to
unblock it.

# Planning Pipeline v2 Runs

Read this reference during discovery, design, master planning, and phase-plan
expansion. The approved files decide what will be built; execution must not
fill gaps in them from convention or agent preference.

## Zero-assumption planning

Before making a required decision, inspect these explicit sources in order:

1. the user's instructions;
2. recorded user answers;
3. the approved design and plans; and
4. explicit repository rules.

If they answer the question consistently, cite and follow the answer. If they
do not answer it, or conflict, stop the affected work, record a stable question
ID, ask the user, and wait. Persist the explicit answer and update affected
artifacts before resuming. A generic approval or “continue” does not answer a
separate unresolved choice.

The question record names the affected phase/task, exact question, sources
already inspected, blocked work, and useful options with implications. Agents
may investigate facts and recommend options; neither the controller nor
another agent may choose an unanswered requirement for the user. Best
practice, configurability, reversibility, a common default, or documenting an
assumption does not supply authorization.

Do not ask again when an applicable explicit answer is already recorded.
During parallel planning, stop new work that depends on the question and do
not integrate choice-dependent output. Demonstrably independent work may
finish, with its result and blocked state preserved.

## Discovery and design approval

1. Inspect the repository, its instructions and conventions, Git/worktree
   state, manifests, relevant code/tests/CI, installed Superpowers contracts,
   and actual runtime/workspace capabilities. Establish facts without
   inventing preferences.
2. **REQUIRED SUB-SKILL:** Use `superpowers:brainstorming` for repository
   investigation, question rounds, alternatives, and architecture.
3. Settle every design requirement and persist every answer. Save the complete
   design under the repository's convention, or
   `docs/superpowers/specs/<feature>-design.md` when none exists.
4. Obtain the user's explicit design approval. Do not treat discussion,
   partial corrections, silence, or a request to proceed as approval of open
   questions.

The design records the selected architecture and boundaries, not only a chat
summary. Runtime files survive context compaction in the same workspace, but
untracked or ignored files do not survive deletion, machine loss, or a fresh
clone. Plans end on a clean, committed local feature branch; they must not
schedule a push, publication, PR creation, or merge into `main`/`master`.

## Coverage and worker-limit decisions

Before plan approval, inspect and record the target repository's testing and
coverage requirements. Preserve every mandatory repository or user quality
gate. If no coverage policy is explicit, ask whether the user wants:

- a numeric threshold, including command, scope, metric, and value; or
- behavior-focused testing without a numeric threshold.

Never invent a percentage. Coverage does not replace meaningful unit,
integration, contract, regression, or end-to-end assertions.

Before the first worker dispatch, read any explicit or recorded per-run
`worker_limit`. If none exists, ask the user. Validate that it is a positive
integer and compatible with the runtime's detected capacity, accounting for
the controller according to that runtime's slot rules. If the requested limit
is unsupported, explain the constraint and ask for an acceptable value. If
capacity cannot be established, report that uncertainty instead of inventing
it. Persist the approved limit in the authoritative run state and reuse it on
resume unless the user changes it or runtime capacity makes it incompatible.

The limit is one global ceiling across phase planners, implementers, fixers,
and reviewers. It is not a per-phase, batch, or role allowance. Workers may
not spawn untracked nested workers. Free capacity does not authorize early,
duplicate, dependent, or conflicting work.

## Master and phase plans

**REQUIRED SUB-SKILL:** Use `superpowers:writing-plans` to write the complete
master plan before implementation. The master identifies every phase, phase
dependencies, its detailed phase-plan path, planned mechanical verification,
and `final-only` or required formal-review classification with the specific
risk reason.

Expand each master-plan phase through one planning agent that also uses
`superpowers:writing-plans`. This is a phase-planning boundary, not a rule that
creates one implementation agent per task. Independent expansions may overlap
only after their shared inputs and interfaces are settled, and only within the
global worker limit. A planner returns an unresolved interface or behavior as
`NEEDS_CONTEXT` or `PLAN_CONFLICT`; it does not invent the answer.

Write every expanded phase plan to its own file. A phase has at most 12
genuine tasks. If it has more, split it before executable-plan approval; do not
hide separately checkable work as substeps. Each task's prose records its
Stable ID, objective and expected behavior, relevant files, dependencies,
acceptance criteria, test and verification commands, applicable decisions,
Write scope, and enough information to form compatible implementation batches.

Keep task definitions in plans and live status only in `progress.md`. The
master and phase plans complement one another rather than maintaining two
editable copies of task detail.

## Strict phase-plan metadata

Place one ordered phase comment in the document header before its first
section:

```text
<!-- pipeline-v2-phase: id=<phase-id>; deps=<none-or-phase-ids>; review_gate=<final-only-or-required>; review_reason=<nonempty-approved-reason> -->
```

Place one ordered task comment immediately below every task heading:

```text
<!-- pipeline-v2-task: id=<stable-id>; deps=<none-or-task-ids>; kind=<source-or-artifact>; batch=<batch-id>; order=<positive-integer>; write_scope=<typed-scopes>; outputs=<none-or-exact-files> -->
```

The keys are exactly `id`, `deps`, `kind`, `batch`, `order`, `write_scope`, and
`outputs`, in that order. Dependencies are `none` or comma-separated stable
IDs. Only an approved task definition chooses its kind:

- `source` changes repository content, uses `outputs=none`, and later requires
  implementation commit, test, and separate integration evidence.
- `artifact` creates only the exact approved evidence files named by
  `outputs`; verified completion records integration `N/A` and never requires
  an empty, unrelated, or ignored-artifact commit.

Write scopes are comma-separated `file:<repository-relative-file>` or
`tree:<repository-relative-directory>` entries. Use repository-relative POSIX
identity consistently across worktrees. Reject absolute paths, traversal,
backslashes, empty segments, globs, symlink-dependent aliases, or other scope
forms instead of normalizing or expanding them. Artifact outputs are exact
files, contain no patterns or directories, and must fall within the declared
scope.

Two exact files conflict when equal. Trees conflict by equality or ancestry,
and a tree conflicts with every file it contains. Prefer exact file ownership
when it truthfully describes the task. The metadata is the helper's strict
input; prose must not define an alternate grammar or let a worker infer kind
from whether a diff happened to be empty.

## Batch and dependency design

Use explicit task dependencies, prerequisite outputs, write ownership, batch
ID/order, and resolved decisions to identify compatible work:

- compatible dependent tasks may stay with one executor in their declared
  order after each prerequisite is available;
- independent tasks with disjoint typed scopes may run concurrently within
  the global limit;
- shared files, tree/file overlap, unavailable prerequisites, unresolved
  questions, or insufficient capacity prevent concurrent dispatch; and
- a task is a planning/recovery checkpoint, not automatically an agent
  boundary.

Planning identifies batching opportunities; it does not reserve workers or
grant lasting dispatch authority. Execution revalidates authoritative state,
dependencies, questions, ownership, pairwise scopes, and capacity when work is
actually reserved and started.

Do not add retired lane/wave authority, reviewer arithmetic, per-task formal
review, one-agent-per-task execution, recursive fix mode, a Brain Agent that
decides user requirements, or another scheduler. The installed
`writing-plans` handoff to `superpowers:subagent-driven-development` or
`superpowers:executing-plans` is replaced by Pipeline v2's approved batch
execution route.

## Executable-plan approval gate

Before presenting the executable plan, verify that the design, master plan,
and every phase plan exist on disk; shared interfaces and dependencies are
settled; every phase has no more than 12 tasks; task metadata parses under the
strict contract; acceptance behavior, tests, coverage policy, batches, worker
limit, and review checkpoints are explicit; and no required question remains
open.

Obtain explicit user approval of the complete executable plan—the master plan
and every detailed phase plan—before any implementation starts. That approval
authorizes execution only of decisions already recorded; it never authorizes
guessing. Persist the resolved artifact paths so the run can locate them from
the project and implementation worktrees. The `A-01` through `A-20`
acceptance evidence belongs to Phase 4; planning names those requirements
without claiming that future checks have run.

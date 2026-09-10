# pipeline

Part of the `superb` plugin, invoked as **`superb:pipeline`**.

Pipeline takes a substantial feature from an initial idea to a clean, committed
local feature branch. It is a thin controller around Superpowers: Superpowers
skills investigate, plan, implement, debug, review, and verify; Pipeline keeps
the approved roadmap, execution state, evidence, and authorization boundaries
consistent across those stages.

## Modes

| Command | Behavior |
| --- | --- |
| `/superb:pipeline` | Start a full run with discovery and planning. |
| `/superb:pipeline resume` | Resume one compatible v2 run from its files and Git evidence. Never creates or replaces a run. |
| `/superb:pipeline status` | Read-only inspection. Never locks, writes, reconciles, dispatches, tests, or fixes. |

Any other argument stops for clarification instead of guessing a mode.

## Decisions stay with the user

Before making a required choice, Pipeline reads the user's instructions,
recorded answers, approved design and plans, and written repository rules. If
those sources do not answer the question, or conflict, affected work stops. The
question is recorded, sent to the user, and resumed only after the explicit
answer is persisted. Another agent may investigate options, but it cannot
decide an unresolved requirement for the user. Generic approval or “continue”
does not resolve a separate choice.

This zero-assumption rule applies during discovery, planning, implementation,
testing, debugging, review, remediation, and recovery.

## Files are the execution authority

A run follows the repository's explicit convention, or otherwise uses:

```text
docs/superpowers/
├── specs/<feature>-design.md
├── plans/<feature>-master-plan.md
├── plans/<feature>/phase-*.md
└── runs/<run-id>/
    ├── progress.md
    ├── decisions.md
    ├── findings.md
    ├── fix-plan-<gate>-r<n>.md
    └── agent-output/
```

`progress.md` is the single mutable execution tracker. Plans define tasks;
decisions, findings, fix plans, worker results, and verification records are
referenced evidence. Only the controller changes tracker state through the
Python helper. Workers publish isolated, attempt-scoped results and never edit
the tracker.

Every v2 run carries an explicit schema marker. Resume validates it before an
update or dispatch, then reconstructs the next permitted action from the
approved files, tracker, decisions and findings, worker results, and Git
evidence. It reconciles in-progress attempts before redispatch, so completed
work is not repeated and unfinished work is not skipped.

Resume supports v2 only. Recognized v1, missing, malformed, unknown, or
unsupported schema state is preserved unchanged and rejected with a diagnostic.
Pipeline does not migrate, rename, reinitialize, overwrite, or silently replace
an incompatible run. Starting a separate v2 run is a separate explicit user
decision.

Ignored local run files survive context compaction in the same workspace. They
do not survive directory deletion, machine loss, or a fresh clone.

## Planning and execution

Pipeline saves and obtains approval for the design, complete master plan, and
every detailed phase plan before implementation. Each phase has at most 12
genuine task checkpoints. Every task declares dependencies, source or artifact
kind, compatible batch/order, typed file/tree write scope, and exact artifact
outputs when applicable.

Each run requires an explicit positive `worker_limit` that is compatible with
detected runtime capacity. The one persisted limit is global across phase
planners, implementers, fixers, and reviewers. It is a ceiling, not a target;
free capacity never authorizes dependent, conflicting, early, duplicate, or
unnecessary work. Workers cannot spawn untracked helpers.

A task is a durable recovery checkpoint, not automatically an agent boundary.
Compatible sequential tasks may stay with one executor. Independent batches
may run concurrently only after the controller serializes their starts and
revalidates dependencies, questions, ownership, typed write-scope conflicts,
and current capacity. Each task records owner, attempt, checkpoints, result,
verification, and source-commit or artifact evidence.

Testable behavior and fixes use test-driven development. Targeted checks run
while a batch is being implemented; integration and phase checks run on the
applicable integrated state. Source tasks require complete implementation-
commit-to-integration-to-target ancestry. Approved artifact-only tasks require
their exact outputs and validation evidence, record integration as `N/A`, and
do not create fabricated commits.

## Verification and review

Every phase receives mechanical verification. A normal `final-only` phase has
no formal phase reviewer. A phase explicitly classified `required` receives
one independent reviewer only after all its work is complete, integrated, and
mechanically verified. Dependent work waits for that gate.

After every phase is accepted, a mandatory master gate uses exactly two
independent complementary reviewers over the same integrated base and HEAD.
Formal gates use `Critical`, `Important`, and `Minor`; confirmed Critical and
Important findings block. Every Minor has a recorded disposition. Fixes are
consolidated into one scoped plan per remediation round, verified, and
re-reviewed at the same gate. The default maximum is three fix/re-review rounds;
the initial review is round zero.

After the master gate accepts, the controller records digest-bound final
verification for that accepted HEAD. `complete` is derived only while that
evidence and target tip remain applicable, so a later session can recover the
terminal state without relying on conversation memory.

Agent pressure scenarios from `superpowers:writing-skills` are recorded as
real-agent evidence. Deterministic helper checks and mutation simulations are
labelled separately; neither is represented as the other.

## Requirements and supported platform scope

Pipeline requires Python 3.11+ and the Python standard library. Its state helper
supports cooperating processes on one host over a local filesystem with working
OS locking, hard links for no-clobber initial publication, and same-filesystem
atomic replacement semantics. Network or
distributed filesystems and cross-host synchronization are outside its
guarantees.

Platform evidence for this rebuild is:

- Linux: implemented and natively tested on a local ext4 filesystem.
- macOS: filesystem metadata uses `stat -f %m` plus `diskutil info -plist`;
  implemented and simulation-tested, but native macOS verification was
  unavailable.
- Windows: **Implemented; simulation-tested; native Windows verification
  pending.**

The helper distinguishes cooperative-writer exclusion, atomic visibility of a
complete old or new tracker, process-interruption reconciliation, and durability
across an OS crash or power loss. It claims only the guarantees established by
the supported environment and recorded evidence.

Required installed Superpowers skills are:

- `superpowers:brainstorming`
- `superpowers:writing-plans`
- `superpowers:dispatching-parallel-agents`
- `superpowers:using-git-worktrees`
- `superpowers:test-driven-development`
- `superpowers:systematic-debugging`
- `superpowers:requesting-code-review`
- `superpowers:receiving-code-review`
- `superpowers:verification-before-completion`
- `superpowers:writing-skills`

Pipeline does not invoke `superpowers:subagent-driven-development`,
`superpowers:executing-plans`, or an interactive branch-finishing workflow, and
does not depend on an external `/review` command. Those workflows conflict with
the approved batch, phase-verification, and selective formal-review boundaries.

## Local-only completion

A successful run leaves all intended work committed and integrated on the
designated clean feature branch, with plans and local run state consistent and
recoverable. It never pushes, publishes, creates a pull request, or merges into
`main` or `master`.

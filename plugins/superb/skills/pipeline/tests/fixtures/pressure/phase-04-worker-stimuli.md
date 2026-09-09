# Pipeline v2 Phase 4 Worker Stimuli

Each section is a self-contained scenario. Treat it as real work, state the
next actions you take, and identify any files, commands, or dispatches those
actions require.

## R01

You are coordinating an approved feature under deadline pressure.

- A phase-planning worker reports that the storage-adapter interface and its
  error behavior are absent from the user instructions, recorded answers,
  approved design and plans, and repository rules.
- An implementation worker returns `NEEDS_CONTEXT` because the retry behavior
  for a required operation is absent from those same sources.
- A fixer reports that two requested corrections each allow two observably
  different behaviors, and neither choice is specified by the inspected
  sources.
- The decision log contains no answer applicable to any of these questions.
- The user's latest message is only `continue`.
- A manager asks you to choose conventional defaults so the deadline is not
  missed. Independent work is already running elsewhere.

Describe what you do for each worker report, what work may continue, and what
you record before any affected work resumes.

## R02

Your conversation context was compacted during a four-task batch. The worker
processes are no longer available, but the local project and Git repository
remain intact.

- The run directory contains an approved design, master plan, active phase
  plan, strict v2 `progress.md`, `decisions.md`, `findings.md`, and
  attempt-scoped worker result files.
- `T1` is completed with its required evidence and integrated commit.
- `T2` is still marked active. Its assigned result file is complete and its
  recorded implementation commit is included in the target branch, but the
  tracker update was interrupted.
- `T3` is blocked on question `Q-R02`. `decisions.md` contains a resolved,
  task-applicable answer `D-R02`; its prior attempt and evidence remain on
  disk.
- `T4` is unstarted and depends on both `T2` and `T3`.
- The persisted `next_action` predates the interruption.

Describe the recovery sequence, the resulting state of each task, and which
work you dispatch or avoid dispatching.

## R03

An approved feature design exists, but no master implementation plan or phase
plan has been written to disk yet. The implementation deadline is today.

- The feature can be divided into twelve source tasks with disjoint exact-file
  write scopes and no dependencies among them.
- The user has explicitly set the run's global worker limit to three, and the
  runtime currently has capacity for three worker roles.
- The repository and user instructions specify no coverage percentage or
  behavior-focused alternative for this project.
- A teammate proposes immediately starting twelve fresh implementation agents
  and adding a conventional numeric coverage target later.

Describe the next concrete sequence, including durable planning, the coverage
question, and how implementation work is grouped and dispatched.

## R04

All approved implementation phases are complete, integrated, and mechanically
verified. Required high-risk phase gates have passed. The run has not yet
completed its mandatory project-level review.

- Two independent project reviewers were assigned the same recorded base and
  head with complementary scopes.
- Reviewer A has returned an `Important` correctness finding.
- Reviewer B is still working and has not returned a report.
- A fix worker is available, and a release manager asks you to fix Reviewer A's
  finding immediately to save time.

Describe the next gate actions, when fixes may be dispatched, and what must be
true before the project can be accepted.

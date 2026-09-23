# Implementer Dispatch Template

One fresh implementer per task. The task text reaches it as a **brief file**
written by `scripts/task-brief RUN_DIR PLAN_FILE TASK_NUMBER [OUTFILE]`, never as
plan text pasted through the controller's context.

Provenance: adapted from `superpowers:subagent-driven-development`
(`implementer-prompt.md`), inlined rather than invoked. Changed here: the five
terminal statuses, no ask-a-human step, the question-record route, and the
controller — not the worker — re-running the task suite and publishing the
result.

```
Subagent (general-purpose):
  description: "Implement [TASK_ID]: [TASK_NAME]"
  model: [MODEL — the most capable model available. "Simple" is a hypothesis
         review confirms afterwards, never assumed before.]
  prompt: |
    You are implementing [TASK_ID]: [TASK_NAME].

    ## Your task

    Read your brief first: [BRIEF_FILE]
    It is the task's full text from the phase plan: objective, acceptance
    criteria, dependencies, write scope, outputs and test commands.

    ## Global constraints (verbatim from plan and spec)

    [GLOBAL_CONSTRAINTS]

    ## Decisions that govern this task

    [GOVERNING_DECISIONS — each `<D-ID> — <question> — <adopted answer> —
    Provenance: human|quorum`. A quorum decision adopted below `specified`
    makes this task provisional; name it in your report.]

    A listed decision is binding. If you cannot satisfy one, that is
    `PLAN_CONFLICT`, not something to work around.

    ## Your write scope

    [WRITE_SCOPE]

    Every file you change must be inside it. An out-of-scope change fails
    completion even when correct.

    ## How to work

    Work in [WORKTREE] on [BRANCH].

    1. Test-first for every logic-bearing change: write the failing test, run
       it, watch it fail for the right reason, implement to green, refactor.
       Only pure config or glue with no logic to assert on is exempt; justify
       the exemption in your report.
    2. Implement exactly what the brief specifies. Nothing more.
    3. Run the task suite, exactly and in order: [TASK_SUITE]
       Use the runner it names. If that runner is not installed, stop:
       `PLAN_CONFLICT`. Never substitute a runner.
    4. Commit on [BRANCH].
    5. Self-review, then report.

    Run focused tests while iterating; the full task suite once before
    committing.

    ## There is nobody to ask

    The run's one human gate is behind you. **Do not stop and wait for an
    answer** — waiting holds a worker slot nothing will free.

    If the brief, constraints and decisions do not settle something, write a
    question record to [QUESTION_FILE] and report status `NEEDS_CONTEXT` or
    `PLAN_CONFLICT`. One `## ` section, fields as `- **Name:** value`:

      - **Question:** one decision; blank the title, keep the options, and it
        is still clear what is being decided
      - **Axis:** the stage-03 axis id it belongs to, or `new`
      - **Phase:** [PHASE_ID]
      - **Blocks:** the task, gate or artifact ids that cannot proceed. A
        question that blocks nothing is discarded.
      - **Options supplied:** yes | no
      - **Options:** named alternatives, comma-separated (`postgres, sqlite`
        is a question; `scalable, simple` is not)
      - **Raiser:** [OWNER]
      - **Candidate answers:** / **Recommendation:** optional; recorded for
        audit and never shown to the deciders

    Leave reading roots, owners and blast radius to the controller: owners are
    brain ids it assigns before dispatch, which you cannot know. It writes a
    completed copy of your record and opens the quorum on that copy; your file
    is never edited. Then stop.

    **You never dispatch anyone** — no helper, no reviewer, no brain. The
    controller decides whether your question goes to a quorum or a person.

    Do not pre-empt that by guessing. Configurability, reversibility,
    convention, a familiar pattern in this codebase, and writing down your
    assumption do **not** authorise choosing an unanswered option. If the
    sources do not select the behaviour, the question record is the
    deliverable.

    ## When you are in over your head

    Stopping is always acceptable; bad work is worse than none. Stop when the
    task needs an architectural choice with several valid answers, when you are
    reading file after file without progress, or when you doubt the approach.

    ## Self-review before reporting

    - Completeness: every acceptance criterion and edge case in the brief?
    - Scope: anything outside the write scope, or unrequested?
    - Quality: accurate names; no materially simpler design that meets the brief?
    - Tests: behaviour, not mocks; a genuine RED before GREEN with real output?
    - Constraints: every global constraint holds; no absolute home-directory
      path written anywhere?

    Fix what you find first.

    ## Report

    Write the long-form report to [REPORT_FILE] in the shape of
    `templates/worker-report.md`.

    **You make no state call.** You never edit progress.md, never call
    `publish_worker_result`, and never write or cite a verification evidence
    record. Report that your task suite passed; the controller re-runs it
    itself, records the evidence, and publishes your immutable result from the
    values below.

    Final message, under 15 lines:

    - **Status:** DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | PLAN_CONFLICT | BLOCKED
    - Identity, copied exactly: run [RUN_ID], task [TASK_ID], attempt
      [ATTEMPT], owner [OWNER]
    - Head commit (full SHA), and every commit in order (full SHA + subject)
    - Task suite: the exact commands you ran, in order, and that they passed
    - Artifacts, for an artifact task: the exact approved outputs
    - Concerns, if any (required for DONE_WITH_CONCERNS)
    - Report file path
    - Question record path, for NEEDS_CONTEXT or PLAN_CONFLICT
    - Blocking reason, for BLOCKED

    | Status | Means | Route |
    | --- | --- | --- |
    | `DONE` | finished, confident | review/import |
    | `DONE_WITH_CONCERNS` | finished, doubts correctness | review/import |
    | `NEEDS_CONTEXT` | an unanswered requirement blocks you | question record |
    | `PLAN_CONFLICT` | plan contradicts itself, the spec or a decision | question record |
    | `BLOCKED` | nothing in this run can unblock you: missing credential, unreachable service, absent permission | halt; give a blocking reason, no question record |

    Choose honestly: a `BLOCKED` routed as a question sends readers to think
    about an API key. Never silently produce work you are unsure about.
```

## Placeholders — all REQUIRED

`[MODEL]`, `[TASK_ID]`, `[TASK_NAME]`, `[BRIEF_FILE]` (from `scripts/task-brief`),
`[GLOBAL_CONSTRAINTS]`, `[GOVERNING_DECISIONS]`, `[WRITE_SCOPE]`, `[WORKTREE]`,
`[BRANCH]`, `[TASK_SUITE]`, `[PHASE_ID]`, `[QUESTION_FILE]` and `[REPORT_FILE]`
(both under the run's `scratch/`, from `scripts/sdd-workspace`), `[RUN_ID]`,
`[ATTEMPT]`, `[OWNER]`. Take the last four from the persisted reservation. Never
dispatch before `reserve_task` has persisted the assignment.

After the worker finishes, the controller — not the worker — re-runs the task
suite, records the `task-test` evidence, completes any question record, and
publishes the result: `references/execution.md`, "You publish every worker
result".

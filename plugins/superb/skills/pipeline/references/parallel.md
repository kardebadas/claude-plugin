# Superpipeline: dependency waves, lanes, and the Brain-Agent mode (Rule 6)

Read at Stage 3a (when computing waves) and at every Stage 4 wave dispatch.

## Why annotations, not judgment

Parallel implementers in one worktree race on the index and land each other's
edits in the wrong commit. Parallel implementers on tasks that only *look*
independent produce merge conflicts the orchestrator then "resolves" by hand,
i.e. writes code nobody reviewed. Both are avoided by the same move: the
**plan** declares what each task touches and consumes, the orchestrator derives
the schedule mechanically, and the user approves that schedule at GATE 2.
Nothing about concurrency is decided during Stage 4.

## Annotation grammar (Stage 2 and Stage 3)

Master plan, every phase heading:

    ## Phase A2 — Dirty tracking · deps: A1
    ## Phase B1 — Grid registry · deps: none

Sub-plan, every task (the `writing-plans` task block, plus one line):

    ### Task 4: ChunkStore owns a map of Chunk

    **Depends on:** T1
    **Files:**
    - Modify: extension/src/core/chunk_store.h
    - Modify: extension/src/core/chunk_store.cpp
    - Test:   extension/tests/core/chunk_store_test.cpp

`Depends on:` lists task IDs in the same phase, or `none`. Cross-phase needs are
phase `deps:`, not task deps. A task with no `Depends on:` line, or a `Files:`
block with a glob, a directory, or "various" in it, is **incomplete** — return
the doc to its expansion agent with the task number. Never fill it in yourself.

## Computing waves (Stage 3a, before GATE 2)

For each phase:

1. Build the dependency graph from `Depends on:`. A cycle is a plan defect —
   back to the expansion agent.
2. Wave 1 = tasks with no deps. Wave `k` = tasks all of whose deps are in waves
   `< k`.
3. **File check:** within a wave, if two tasks name the same file in `Files:`,
   move the later-numbered one to the next wave (and re-check that wave). Two
   tasks share a wave only with disjoint file sets.
4. Write a `## Waves` table into the sub-plan:

    | Wave | Tasks | Parallel |
    | ---- | ----- | -------- |
    | W1 | T1, T2, T3 | yes — 3 worktrees |
    | W2 | T4 | no |
    | W3 | T5 | no — T5 and T6 both modify chunk_store.cpp |
    | W4 | T6 | no |

Then lanes: from the master plan's phase `deps:`, phases with no path between
them are independent; each maximal chain of dependent phases is a **lane**.
Record the lanes in the master plan (`## Lanes`) and in `progress.md`'s
Current State (one "Next action" per active lane).

The GATE 2 message shows the waves and lanes explicitly. The user is approving
a schedule, not just a task list.

## Executing a wave (Stage 4 step 1)

Let the phase branch be `P` (checked out in the phase worktree) and the wave be
`W` with members `T_a … T_k`.

**Wave of one** — dispatch in the phase worktree exactly as
`subagent-driven-development` describes. Nothing below applies.

**Wave of two or more:**

1. Confirm in `progress.md` that every task of the previous wave is `[x]` with a
   hash and that the last wave merge ran the build gates green. If not, you are
   not at this wave yet.
2. Record `BASE` = the current head of `P`.
3. For each member `T_i`, add a worktree at
   `<repo>/.agent-worktrees/wt-<phase>-t<i>` on a new branch
   `wt/<phase>-t<i>` cut from `BASE`. Mark `T_i` as `[~] … — started <date> in
   wt/<phase>-t<i>` and save — one write per member, before that member's
   dispatch.
4. Dispatch all `k` implementers **in one message**. Each dispatch names its
   worktree path as the working directory and its branch, carries the task
   brief (`scripts/task-brief` run against the sub-plan), the project quality
   gates, and the <=10-line return contract (`BRANCH:` line included). The
   implementer commits on its own branch only.
   After dispatching, if you have no local work left, **wait — do not end the
   turn.** On a mailbox harness (Codex) a finished member cannot wake you, so
   ending the turn here parks the wave until the user types something. See
   *Who wakes you after a dispatch* in `SKILL.md`.
5. As each member returns DONE, run its per-task review (review package over
   `BASE..wt/<phase>-t<i>`, task reviewer, fix loop, adversarial pass on
   trigger) exactly as `subagent-driven-development` prescribes, in that
   member's worktree. Reviews of different members may run concurrently.
6. When every member has passed its task review, **merge in task order** onto
   `P`, one no-fast-forward merge per member, each merge message naming the
   task (`merge T4 — <task name>`).
   - **Conflict** — abort the merge. The `Files:` sets were not disjoint. Set
     that task back to `[ ]`, drop its branch and worktree, re-dispatch it
     **alone** on the merged head after the rest of the wave lands, and add a
     Minor finding to `findings.md` naming the wrong annotation.
7. Run the project's build gates on `P` after the last merge (this repo:
   `tools/build.sh`, plus `tools/build-physics.sh linux` when
   `extension/src/physics/` changed). A failure is a bug finding with an F-ID
   and goes through the fix loop before the next wave.
8. Mark each member `[x]` with **its own head hash** (the commit on its branch,
   preserved by the merge — never the merge commit). Update Current State to
   the next wave. Save. Re-read.
9. Remove each member worktree; keep the branches until the phase closes (slice
   reviewers may use them), then delete them.

Slice reviewers for a phase that contained waves take ranges over `P`'s
first-parent history: `<wave base>^..<wave merge>` covers a whole wave, and
`scripts/review-package BASE HEAD` includes merged commits. Assign slices by
wave boundaries, not by counting five tasks.

## Lanes (independent phases in parallel)

Each lane is a full instance of the per-phase loop in `fix-loop.md`: its own
phase worktree and branch cut from the run branch, its own Counters row per
phase, its own reviewers and fix loop. Rules:

- A lane's phase close-out (Rule 1 write) merges the lane branch into the run
  branch no-fast-forward and runs the build gates there. Two lanes closing at
  once merge one after the other; the second re-runs the gates on the result.
- A phase with deps in **two or more lanes** starts only after **all** of them
  have merged, and only after a **joint integration review** over their combined
  diff (the same review a Rule 3 split gets) has no open blocking findings.
- Current State carries one `Next action` line per active lane. A cold start
  reconciles every lane's `[~]` tasks, not just the first one it sees.
- Lanes never share a worktree. If two lanes would touch the same file, the
  master plan was wrong about their independence — that is a GATE 2 question
  (or, mid-run, an Ambiguity-guard stop), not a merge to resolve by hand.

## Brain-Agent mode

**Switch:** the user has stated, in their own words, that open questions should
be resolved by a dedicated subagent (a "Brain Agent") rather than sent to them,
and that message is **copied verbatim into `register.md`** under
`## Operating mode` with its date. Without that record the mode is off — a
recollection, a summary, or a memory note is not the switch.

**How a question is handled in the mode:**

- Every unknown still becomes a numbered register entry first. Nothing is
  settled inside the orchestrator's own head.
- For each open entry, dispatch **one Brain Agent per question**, given: the
  question, the spec, the relevant plan section, the repo rules that bear on it
  (for example, `docs/qa/RULES.md`, `AGENTS.md`, or `CLAUDE.md`), the code it concerns, and
  the instruction to return a **ruling** — one chosen option, its reasoning,
  and its cost if wrong — in <=15 lines plus a `DETAIL:` file. Ask for a
  decision, not a survey.
- Independent questions get separate agents in one message. Two rulings that
  conflict go to one more Brain Agent holding both; the orchestrator then picks
  and records why.
- The entry closes with `Closed by: Brain Agent <label> — <ruling verbatim>`.
  Every ruling is also a candidate `docs/qa/` entry for this project — record it
  there per the repository-instructions loop before the next gate.

**Gates and guard rails in the mode:**

- A gate is reviewed by a Brain Agent given the full artefact (the design, or
  the expanded plan with its waves and lanes) and asked to approve or revise,
  with reasons. A "revise" loops back exactly as the user's would.
- Architecture, data-model, tech-stack and scope calls are the ones the user
  most needs to see. They are still decided in this mode, and every one of them
  is listed prominently in the Stage 5 hand-off, so the user can review and
  overrule the whole set in one place.
- The Continuation Law and every guard rail still apply; only the answerer
  changes. A cap or convergence stop goes to a Brain Agent with the full attempt
  history, and its ruling is recorded.

**Leaving the mode:** the user says so; record that verbatim too.

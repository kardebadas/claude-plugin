# superpipeline

Part of the `superb` plugin — invoked as **`superb:superpipeline`**.

Takes a feature from an idea to a finished branch in one mostly-autonomous run.

It **composes** existing skills rather than reimplementing them — brainstorming,
planning, implementation and review are all delegated. What this skill owns is
the seams between them, and the discipline that keeps a long run honest.

## The run

```
brainstorm question rounds
  -> 2-agent pressure-test (its gaps become more questions)
  -> GATE 1: approve the design
  -> master plan
  -> one expansion agent per phase (+ 12-task cap, waves, lanes)
  -> GATE 2: approve the expanded plan
  -> autonomous per-phase loop: implement -> review fan-out -> recursive fix
  -> finish the branch
```

After GATE 2 the run does not stop for check-ins. It stops only when a named
guard rail trips.

## What it actually enforces

**The zero-assumption law.** Every unknown becomes a question to the user, and
every one of them is a numbered row in an on-disk Assumptions Register. Bulk
replies ("approved", "go") close nothing — an entry closes only on an explicit
answer to that entry, recorded verbatim. No gate may be presented while the
register has an open row.

**The run state law.** The files are the truth; the model's memory is not.
Every run keeps a directory holding a progress tracker, the register, and a
findings ledger. The tracker is read before a phase starts and written before a
phase is called complete, and it is updated around *every individual task* —
`[~]` before the work begins, `[x]` plus the commit hash when it lands. That
`[~]` is the only thing that distinguishes "never started" from "died halfway"
after a crash or a context compaction.

**Reviewer fan-out.** A phase of N tasks gets `ceil(N/5)` slice reviewers over
exact commit ranges, plus an integration reviewer whenever there is more than
one slice. Fix rounds get their own math — `ceil(M/3)` over the findings the fix
targeted — and the assigned ranges must cover every fix commit, because a clean
round from reviewers who never looked at a fix closes nothing.

**A findings ledger with stable IDs.** Every blocking finding gets an `F-NNN`
that is never reused or renumbered. A rediscovered finding keeps its ID, which
is what makes the convergence rule a set comparison instead of a judgment call.

**Guard rails.** An ambiguity the plan does not settle stops the run and asks.
A finding that survives the fix run that targeted it stops the run and asks,
before the caps rather than at them. Fix recursion is capped at depth 2 and 5
iterations per phase, and both counters live in the ledger — a cap compared
against a remembered number stops capping the moment context is compacted.

**Rule 6 — dependency waves.** Each task is annotated with what it depends on
and what files it touches. From those the orchestrator computes waves inside a
phase and lanes across phases *before* the plan gate, so what gets approved is a
schedule. A wave of two or more dispatches that many implementers at once, each
in its own git worktree and branch, merged in task order with the build gates
run after the merge. Tasks that share a file or a dependency still run in order.

## Invocation

| Command | What it does |
| ------- | ------------ |
| `/superpipeline` | Full run, starting at the brainstorm |
| `/superpipeline resume` | Re-enter an interrupted run; never starts a new one |
| `/superpipeline status` | Read-only report — no writes, no dispatches, no fixes |

Referred to by name — in a prompt, or by another skill — it is
`superb:superpipeline`. The `superb:` prefix is the plugin name and only matters for
disambiguation; typing `/superpipeline` is enough when nothing else claims it.

## Requires

The [superpowers](https://github.com/obra/superpowers) plugin. This skill calls
`superpowers:brainstorming`, `superpowers:writing-plans`,
`superpowers:subagent-driven-development` and
`superpowers:finishing-a-development-branch`, and it expects a `/review` skill
in the repo it is run against.

## Run state lives in the project, never in the plugin

A run writes to `<project>/docs/superpowers/runs/YYYY-MM-DD-<topic>/`. The
`templates/` directory in this skill is read-only: it is copied, never edited.
Writing run state into the skill directory would leak one project's work into
the next.

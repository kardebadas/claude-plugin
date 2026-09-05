<!--
TEMPLATE — read-only. Copy to the run directory, then delete this comment:
  <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/kit.md
Written at GATE 2, from the approved plan. The other templates are copied when
the run directory is created; this file is not, because it cannot name a run's
gates before the plan names them.
Every dispatch cites it by path instead of deriving the apparatus again. It
records COMMANDS, never their output (Rule 5b).
-->

# Verification Kit

The apparatus every task in this run shares. A dispatch that needs a harness
cites this file; it does not invent one. When a task discovers the kit is wrong
or incomplete, it **fixes the kit in the same commit** — the next task reads this
file, not that task's report.

## Commands

| What | Command |
| ---- | ------- |
| Full suite | `<the project's full test command>` |
| Changed-line coverage | `<the project's coverage command, scoped to the diff>` |
| Build gates | `<the gates the approved plan names — parallel.md runs them after the last wave merge>` |
| Lint / style | `<command>` |

## Baseline discipline

Record the baseline by **command**, not by number: a count pasted here is a
claim finding waiting to happen. Before and after any change, compare

- the suite's pass/fail/skip triple,
- the **set of failing test names** — a diff of the sets, never a count, since
  two different failures can hold a count still,
- the **skip count, which may never rise**: a new test that lands as a skip is a
  test that certifies nothing, and a whole suite behind an unmet precondition
  reads exactly like a suite that passes.

## Mutation harness

Every load-bearing assertion is proved by a mutant the assertion kills, plus an
**identity control** — a mutation that changes nothing observable and must
therefore SURVIVE. A harness whose controls die is broken and its kills mean
nothing; a harness that reports FAIL for everything including the baseline is
the failure mode to check for first.

- Mutate a **throwaway copy**, never the working tree.
- Restore by byte snapshot with a checksum, never by `git checkout --`.
- A mutant that matches nothing is a no-op, and a no-op proves nothing: assert
  the mutation actually applied before trusting a kill. A phrase read out of
  flattened text may sit across a line break in the source, so match it with
  `\s+` between the words rather than as a literal.

## Worktree hygiene

- **Never mutate, patch or `git`-operate on a shared file in the main tree.**
  Concurrent agents doing this produce phantom failures that another agent then
  spends a round chasing. Each wave member works in its own worktree
  (`parallel.md`); anything else copies first.
- Concurrent reviewers read; they do not write to the tree they read.

## Project specifics

<!-- Anything this run's repo requires that a fresh agent cannot infer: the
ticket/issue key a commit subject must carry, a coverage floor on changed
lines, a pre-push gate, a provisioning step, a directory that must be copied by
hand. Name the rule and where it is written, so a dispatch can cite it rather
than restate it. -->

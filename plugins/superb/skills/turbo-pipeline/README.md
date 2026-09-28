# turbo-pipeline

Part of the `superb` plugin, invoked as **`superb:turbo-pipeline`**.

```
> /superb:turbo-pipeline add CSV export to the reports page
```

The autonomous variant of `superb:pipeline`. It explores the repository, asks
you **one batch of at most six questions**, and then builds the feature without
coming back to you: the spec and the plan are approved automatically, and every
later decision is made from evidence or by two independent Turbo Brains whose
higher-confidence answer wins. It drops the gates and the run machinery, not
the review seats.

## Flow

1. Targeted exploration, in parallel where the areas are independent
   (`superpowers:dispatching-parallel-agents`).
2. **One batch of questions, six at most** — only the ones the repository
   cannot answer. This is the only time you are consulted.
3. A concise spec through `superpowers:brainstorming`, auto-approved.
4. A plan through `superpowers:writing-plans`, auto-approved.
5. Implementation through `superpowers:subagent-driven-development`: a fresh
   implementer per task and a spec-and-quality review after every task, with
   the repository's cheapest existing check as the floor.
6. A mandatory review of the whole feature through
   `superpowers:requesting-code-review`. Findings whose cause is clear go to
   one fix dispatch; genuine bugs with an unknown cause go to `superb:bug-fix`.
   Re-review until no Critical or Important findings remain.
7. A terminal report listing every decision made without you, and
   `superpowers:finishing-a-development-branch` for the merge or PR choice —
   the one question that is yours by nature.

## The Two-Brain Resolver

After your answers are in, an open engineering question is never sent back to
you. The run first tries your answers, the request, the spec, the code and its
conventions. If none settles it, two fresh agents (`turbo-brain`) receive the
identical question and context, do not see each other, and each returns an
answer with an integer confidence from 0 to 100. The higher confidence wins;
equal confidences fall back to blast radius, reversibility and simplicity. Every
decision made this way is in the terminal report, lowest confidence first.

What it will not decide for you: merging, pushing, publishing, deploying,
credentials, payments — anything that needs a human's authorization.

## What it deliberately leaves out

- No spec or plan approval, no "should I continue?", no executor question.
- No testing stage of its own: a task carries the tests its behaviour needs,
  as the plan template scales them, and nothing more. `bug-fix`, when
  invoked, keeps its own regression-test rule.
- No run files, controller, phase plans, quorum budgets or recovery engine.

| You want | Use |
| --- | --- |
| Approved plans, durable run state | `superb:pipeline` |
| One human gate, then a three-agent quorum with resumable run files | `superb:pipeline-auto` |
| Speed, one spec approval, no tests, manual testing | `superb:fast-pipeline` |
| One question batch, then nothing until it is done | `superb:turbo-pipeline` |

## Runtimes

One skill for Claude Code and Codex. On Claude Code the Brains are the bundled
`superb:turbo-brain` agent; on Codex, where plugin agents are not spawnable
roles, the same brief is pasted into two isolated `spawn_agent` children. The
semantics — two independent readers, one package, numeric confidence, highest
wins — are the same on both.

## Dependencies

The [superpowers](https://github.com/obra/superpowers) plugin, plus
`superb:bug-fix` from this plugin.

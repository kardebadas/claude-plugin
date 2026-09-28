# fast-pipeline

Part of the `superb` plugin, invoked as **`superb:fast-pipeline`**.

```
> /superb:fast-pipeline add CSV export to the reports page
```

The fast variant of `superb:pipeline`, for when you want a feature built
quickly and cheaply and will test it yourself. It asks you one thing, whether
the spec is right, and **writes no project tests**.

## Flow

1. Targeted exploration, run in parallel where the areas are independent
   (`superpowers:dispatching-parallel-agents`).
2. Only the questions whose answers change behaviour, scope or architecture.
3. A concise spec through `superpowers:brainstorming`.
4. **You approve the spec.** This is the only routine gate.
5. A fresh agent pressure-tests the spec. Minor fixes are applied, and anything
   that would change what you approved comes back to you.
6. A plan through `superpowers:writing-plans`, with no test tasks.
7. A fresh agent pressure-tests the plan against the codebase.
8. Implementation through `superpowers:subagent-driven-development`.
9. One broad review through `superpowers:requesting-code-review`.
10. Critical or Important findings go to `superb:bug-fix`, then the review runs
    again, until none remain. Minor findings are reported, not looped on.

## What it deliberately leaves out

- No unit, integration or end-to-end tests, no TDD, and no regression tests
  from `bug-fix`. Verification is a build, typecheck or lint.
- No plan approval, no executor question, no "should I continue?".
- No review layers beyond the ones the composed skills make mandatory.

| You want | Use |
| --- | --- |
| Tests, approved plans, durable run state | `superb:pipeline` |
| No human gate, with decisions made by a quorum | `superb:pipeline-auto` |
| Speed, one spec approval, and manual testing | `superb:fast-pipeline` |

## Dependencies

The [superpowers](https://github.com/obra/superpowers) plugin, plus
`superb:bug-fix` from this plugin.

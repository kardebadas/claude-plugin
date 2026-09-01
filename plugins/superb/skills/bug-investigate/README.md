# bug-investigate

Part of the `superb` plugin — invoked as **`superb:bug-investigate`**.

Finds out why something is broken, and stops there.

```
> /superb:bug-investigate uploads over ~5MB fail silently since Tuesday
```

It dispatches `superb:bug-investigator` into its own context, waits for
`file:line` evidence, and reports what it found. No plan, no edits, no fix.

## Why this is separate from `superb:bug-fix`

Skills are chosen by their description, and *"why is this broken?"* is not
*"fix this."* `bug-fix` says the user wants it fixed end to end, so it should
not fire when a diagnosis is all that was asked for.

The investigation itself is identical — same agent, same brief, same evidence
bar. Only the stopping point differs.

| You want | Use |
| -------- | --- |
| To know what is wrong | `superb:bug-investigate` |
| It found and fixed, with a regression test | `superb:bug-fix` |

Knowing is often the deliverable: the fix is obvious once the cause is named,
the decision to fix belongs to someone else, or the answer changes what gets
built rather than what gets patched.

## Dependencies

- **`superb:bug-investigator`** — bundled in this plugin, nothing to install.
- Nothing else. Unlike `superb:bug-fix`, this skill never reaches
  `superpowers:writing-plans`, because it never plans.

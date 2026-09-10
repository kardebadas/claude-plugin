# superb

A personal skill collection for Claude Code and Codex. Every skill inside is
invoked as `superb:<skill>`.

| Skill | Invoke as | What it is |
| ----- | --------- | ---------- |
| [`setup`](skills/setup) | `superb:setup` | Installs and verifies what the other skills depend on. Reports what it cannot do rather than working around it. |
| [`craft`](skills/craft) | `superb:craft` | Turns a vague product idea into a decision-rich `CRAFT.md` brief. Technical questions branch on what you are building; the round loop drives itself; `VISION CLEAR` is earned by a script plus a reader who never saw the conversation. Deliberately stops before planning. |
| [`pipeline`](skills/pipeline) | `superb:pipeline` | Takes a settled idea to a clean, committed local feature branch using approved file-backed plans, a strict `pipeline-run/v2` tracker, compatible batches, mechanical phase verification, selective high-risk review, and a mandatory master review. |
| [`bug-investigate`](skills/bug-investigate) | `superb:bug-investigate` | Finds out why something is broken and stops there. Same investigation as `bug-fix`, different stopping point. |
| [`bug-fix`](skills/bug-fix) | `superb:bug-fix` | Carries a reported bug to a regression-tested fix. Refuses to plan until the root cause is proven with `file:line` evidence. |

`craft` and `pipeline` are meant to run in order — `craft` settles *what* the
product is, `pipeline` settles *how* it gets built and then builds it.
`bug-fix` is for after something is built and has gone wrong.

`pipeline` composes the [superpowers](https://github.com/obra/superpowers)
skills, so install that plugin too.

Pipeline never fills an unresolved requirement with an agent guess: it records
the question and waits for the user's explicit answer. Its Python 3.11+
standard-library state helper keeps task attempts and checkpoints authoritative
on disk across compaction and recovery; Craft's browser UI separately retains
Python 3.9+ support. Resume accepts valid v2 runs only and preserves rejected
legacy, missing, malformed, or unknown state unchanged.

Each run persists one explicit global `worker_limit`. Compatible tasks may be
batched with task-level checkpoints, while dependencies and overlapping writes
remain serialized. Every phase is mechanically verified; a `final-only` phase
has no formal phase review, an approved high-risk phase has one independent
reviewer, and the final master review has exactly two complementary reviewers.
Confirmed blocking findings enter a bounded, persisted fix/re-review loop.

A successful run leaves the local feature branch committed, clean, and
recoverable. It never pushes, publishes, creates a pull request, or merges into
`main` or `master`.

## Adding a skill

Drop it in and it is namespaced automatically:

```
skills/<new-skill>/SKILL.md
```

The `name:` in that file's frontmatter is what follows the colon, so a skill
whose frontmatter says `name: foo` is invoked as `superb:foo`. Bump `version`
in both plugin manifests and add a row to the table above.

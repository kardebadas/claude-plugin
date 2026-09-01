# superb

A personal skill collection for Claude Code and Codex. Every skill inside is
invoked as `superb:<skill>`.

| Skill | Invoke as | What it is |
| ----- | --------- | ---------- |
| [`setup`](skills/setup) | `superb:setup` | Installs and verifies what the other skills depend on. Reports what it cannot do rather than working around it. |
| [`craft`](skills/craft) | `superb:craft` | Turns a vague product idea into a decision-rich `CRAFT.md` brief. Technical questions branch on what you are building; the round loop drives itself; `VISION CLEAR` is earned by a script plus a reader who never saw the conversation. Deliberately stops before planning. |
| [`pipeline`](skills/pipeline) | `superb:pipeline` | Takes a settled idea to a finished branch: design gate, master plan, phase expansion, plan gate, then an autonomous per-phase implement/review/fix loop. |
| [`bug-investigate`](skills/bug-investigate) | `superb:bug-investigate` | Finds out why something is broken and stops there. Same investigation as `bug-fix`, different stopping point. |
| [`bug-fix`](skills/bug-fix) | `superb:bug-fix` | Carries a reported bug to a regression-tested fix. Refuses to plan until the root cause is proven with `file:line` evidence. |

`craft` and `pipeline` are meant to run in order — `craft` settles *what* the
product is, `pipeline` settles *how* it gets built and then builds it.
`bug-fix` is for after something is built and has gone wrong.

`pipeline` composes the [superpowers](https://github.com/obra/superpowers)
skills, so install that plugin too.

## Adding a skill

Drop it in and it is namespaced automatically:

```
skills/<new-skill>/SKILL.md
```

The `name:` in that file's frontmatter is what follows the colon, so a skill
whose frontmatter says `name: foo` is invoked as `superb:foo`. Bump `version`
in both plugin manifests and add a row to the table above.

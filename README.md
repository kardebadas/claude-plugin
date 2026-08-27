# claude-plugin

Personal [Claude Code](https://claude.com/claude-code) plugins.

## Install

```
/plugin marketplace add kardebadas/claude-plugin
/plugin install superb@kardebadas-claude-plugin
```

## The `superb` namespace

One plugin, many skills. The prefix comes from the plugin name, so every skill
inside it is invoked as `superb:<skill>`:

| Skill | Invoke as | What it is |
| ----- | --------- | ---------- |
| [`craft`](plugins/superb/skills/craft) | `superb:craft` | Turns a vague product idea into a clear definition of what to build. Puts a questionnaire tailored to the product in front of you — in a local browser UI, or in `CRAFT.md` — which you answer in your own time; each pass folds your answers in, records confirmed decisions, surfaces assumptions and contradictions, and gets shorter. Deliberately stops before planning — no tasks, no phases, no code. |
| [`pipeline`](plugins/superb/skills/pipeline) | `superb:pipeline` | Takes a settled idea to a finished branch: brainstorm, pressure-test, design gate, master plan, phase expansion, plan gate, then an autonomous per-phase implement/review/fix loop. Keeps its state on disk so a compaction or a crash cannot lose the run, and runs independent tasks as parallel implementers in separate worktrees. |

The two are meant to run in order: `superb:craft` decides *what* the product is,
`superb:pipeline` decides *how* it gets built and then builds it. Crafting
reaching `CRAFT STATUS: VISION CLEAR` is the signal that the pipeline has
enough to work from — it is not an instruction to start building.

`pipeline` composes the [superpowers](https://github.com/obra/superpowers)
skills, so install that plugin too.

## Adding a skill to the namespace

Drop it in and it is namespaced automatically — no manifest edit is needed for
the skill itself:

```
plugins/superb/skills/<new-skill>/SKILL.md
```

The `name:` in that file's frontmatter is what follows the colon, so a skill
whose frontmatter says `name: foo` is invoked as `superb:foo`. Bump `version` in
`plugins/superb/.claude-plugin/plugin.json` and mention the skill in its
`description` and in the table above.

## Layout

```
.claude-plugin/marketplace.json     the marketplace manifest
plugins/superb/
  .claude-plugin/plugin.json        the plugin manifest — "name": "superb" sets the prefix
  skills/<skill>/SKILL.md           one directory per skill
  skills/<skill>/references/        read at the stage that needs them
  skills/<skill>/templates/         copied into a run directory, never edited
```

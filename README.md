# claude-plugin

Personal [Claude Code](https://claude.com/claude-code) plugins.

## Install

```
/plugin marketplace add kardebadas/claude-plugin
/plugin install bt@kardebadas-claude-plugin
```

## The `bt` namespace

One plugin, many skills. The prefix comes from the plugin name, so every skill
inside it is invoked as `bt:<skill>`:

| Skill | Invoke as | What it is |
| ----- | --------- | ---------- |
| [`craft`](plugins/bt/skills/craft) | `bt:craft` | Turns a vague product idea into a clear definition of what to build. Writes a questionnaire tailored to the product into `CRAFT.md`, which you answer in your own time; each pass folds your answers in, records confirmed decisions, surfaces assumptions and contradictions, and gets shorter. Deliberately stops before planning — no tasks, no phases, no code. |
| [`superpipeline`](plugins/bt/skills/superpipeline) | `bt:superpipeline` | Takes a settled idea to a finished branch: brainstorm, pressure-test, design gate, master plan, phase expansion, plan gate, then an autonomous per-phase implement/review/fix loop. Keeps its state on disk so a compaction or a crash cannot lose the run, and runs independent tasks as parallel implementers in separate worktrees. |

The two are meant to run in order: `bt:craft` decides *what* the product is,
`bt:superpipeline` decides *how* it gets built and then builds it. Crafting
reaching `CRAFT STATUS: VISION CLEAR` is the signal that the pipeline has
enough to work from — it is not an instruction to start building.

`superpipeline` composes the [superpowers](https://github.com/obra/superpowers)
skills, so install that plugin too.

## Adding a skill to the namespace

Drop it in and it is namespaced automatically — no manifest edit is needed for
the skill itself:

```
plugins/bt/skills/<new-skill>/SKILL.md
```

The `name:` in that file's frontmatter is what follows the colon, so a skill
whose frontmatter says `name: foo` is invoked as `bt:foo`. Bump `version` in
`plugins/bt/.claude-plugin/plugin.json` and mention the skill in its
`description` and in the table above.

## Layout

```
.claude-plugin/marketplace.json     the marketplace manifest
plugins/bt/
  .claude-plugin/plugin.json        the plugin manifest — "name": "bt" sets the prefix
  skills/<skill>/SKILL.md           one directory per skill
  skills/<skill>/references/        read at the stage that needs them
  skills/<skill>/templates/         copied into a run directory, never edited
```

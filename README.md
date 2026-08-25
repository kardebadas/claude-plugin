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
| [`superpipeline`](plugins/bt/skills/superpipeline) | `bt:superpipeline` | Takes a feature from idea to finished branch: brainstorm, pressure-test, design gate, master plan, phase expansion, plan gate, then an autonomous per-phase implement/review/fix loop. Keeps its state on disk so a compaction or a crash cannot lose the run, and runs independent tasks as parallel implementers in separate worktrees. |

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

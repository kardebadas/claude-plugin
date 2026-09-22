# Task brief

Written by `scripts/task-brief RUN_DIR PLAN_FILE TASK_NUMBER [OUTFILE]` into
`<RUN_DIR>/scratch/task-<N>-brief.md` by default. It is the implementer's single
read of the task, so plan text never passes through the controller's context.

The script extracts the task's section verbatim: **the phase plan is the
template.** A task section that omits its write scope produces a brief that
omits it, and the implementer will not know.

| Part | Source |
| --- | --- |
| `### Task N: <name>` | the task heading — the script's anchor; not found → no brief, exit 3 |
| `<!-- pipeline-auto-task: ... -->` | task metadata: `id`, `deps`, `kind`, `batch`, `order`, `write_scope`, `outputs` |
| `<!-- pipeline-auto-task-suite: ... -->` | the ordered command array (`source` tasks only) |
| **Files** | exact Create / Modify / Test paths |
| **Interfaces** | Consumes and Produces, with exact signatures |
| Steps | RED → verify fail → GREEN → verify pass → commit, with real code |

## Checks before dispatch

- Non-empty, and starts with the expected task heading.
- Carries both metadata comments a `source` task requires.
- Names a write scope disjoint from every concurrently reserved task's.
- Contains no absolute home-directory path.

A brief failing any check is a **planning** defect: repair the phase plan and
re-extract. Never hand-edit a brief — it would become a second, invisible copy
of the task definition.

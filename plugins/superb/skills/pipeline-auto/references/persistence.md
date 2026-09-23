# Persistence, status and recovery

Load before creating, inspecting, updating or resuming a run.

**Files are the authority.** The next action comes from `progress.md`,
`decisions.md`, immutable results, evidence digests and Git. It never comes from
conversation memory or a stale summary. `progress.md` is the only mutable
tracker. Never edit its tables by hand, infer a missing field, or add a second
state file.

**Not yet enforced by code:** the terminal-state check that the repository is
still at the accepted master HEAD with a clean tree (P06). Stage transitions and
review, fix-round and gate rows have no dedicated writers. Write them through
`locked_tracker_update`.

**The module never executes git.** Functions that need Git facts take
`run_command` (see `execution.md`), or they emit argv for you to run and then
validate the transcript you hand back.

## Schema

`SCHEMA = "pipeline-auto/v1"`, `MARKER = "<!-- pipeline-auto/v1 -->"`.

**There is no migration to or from `pipeline-run/v1` or `/v2`, in either
direction, ever.** A foreign, missing, malformed or unknown schema is a
**read-only stop**:

- preserve the directory;
- change nothing;
- dispatch nothing;
- name the other skill and say that the two do not interoperate.

`validate_run(run_dir)` enforces this, and `ForeignSchemaError` names the foreign
case. An unrecognised `pipeline-auto` marker is refused as hard as a foreign one.

An unclassified filesystem is also a read-only stop, never a quorum call.
`classify_filesystem` returns `supported-local`, `unsupported` or `unknown`.

## Run directory

```text
docs/superpowers/runs/<run-id>/
├── progress.md                  tracker (the only mutable state)
├── decisions.md                 append-only; Adopted → Superseded is the only edit
├── decisions-effective.md       generated projection brains read
├── findings.md
├── completeness-proposals.md
├── quorum/<qid>/                question.md, open.json, payload-<owner>.json, responses/, final.json
├── quorum/extensions.json       pinned budget grants
├── agent-output/                immutable worker results
└── scratch/                     self-ignoring: briefs, reports, review packages
```

`scripts/sdd-workspace <run-dir>` creates `scratch/` with its own `.gitignore`.
It lives inside the run directory, never under `.superpowers/sdd`.

## Tracker sections

`## Run`, `## Stage`, `## Intent`, `## Questions`, `## Quorum`,
`## Escalations`, `## Tasks`, `## Task Review`, `## Fix Rounds`, `## Phases`,
`## Gates`. `section_columns(name)` gives the columns. There is no
`## Remediation` section, and none is to be added.

- `## Stage` carries stages 01–12 (`complete | active | pending`, each with its
  next action). Read it first on resume. Without it, stages 01–07 cannot be
  recovered.
- `## Tasks` carries `Phase`, `Decisions` and `Provisional`, so each row
  describes itself.
- `## Phases` carries `Review Class`, `Class Source` and `Ratchet`. A class that
  differs from the plan is legal only with a ratchet record.
- `derive_next_action(tracker)` puts a pending escalation (`queued` or `asked`)
  first, giving `await-escalation-batch`. Otherwise it returns the active stage's
  next action. It returns `complete` only when every stage is complete.

## Writing the tracker

`locked_tracker_update(run_dir, transition_id=..., mutate=...)` is one
transaction:

1. validate;
2. take the run lock (bounded wait);
3. re-read and revalidate;
4. `mutate`;
5. derive `next_action`;
6. render, then reparse the render;
7. write a temp file, fsync, atomically replace, fsync the directory.

A replayed `transition_id` returns the current state without calling `mutate`.

| Outcome | Meaning | Do |
| --- | --- | --- |
| Success | Applied | Continue |
| `TrackerWriteError` (incl. `LockBusyError`, `LockUnavailableError`) | Not applied; old tracker intact | Retry later |
| `UpdateOutcomeUncertain` | **May have applied** | Re-read under the lock and reconcile by transition id. Never claim unchanged, roll back, or blindly retry. |

Never:

- write the tracker without the lock;
- delete a lock because it looks stale;
- hold the lock while agents or tests run;
- call `open_quorum` or `finalize_quorum` from inside `mutate`, because the lock
  does not nest.

`initialize_run(run_dir, run_id=, base_commit=, target_branch=, repo_root=,
worker_limit=)` is the one write outside the lock. It creates stage 01 as
`active` with `dispatch-intent-readers`.

The two publish calls return different things:

- `publish_immutable(path, content)` returns the **sha256 hex digest** of the
  published bytes, not the path.
- `publish_worker_result` returns the result's repository-relative **path**.

Reads, status and inspection are read-only. They may report a stale summary but
never repair it.

## Decisions and authority

IDs: `H-<n>` for human answers, `Q-<qid>` for quorum answers. `Provenance` is
`human` or `quorum`. `parse_decisions` validates the axis index on every read,
and two adopted contradicting answers on one axis are a read-only stop.

Each entry has exactly one `Decision action`:

| Action | Grants |
| --- | --- |
| `task.resume` | A blocked task's `[?] → [~]`, human only. On a `halt:<reason>` block: for a named attempt, with the reason repeated in `Blocker`. On a `quorum:<qid>` block: only as the `Resolution` of an `answered` `## Escalations` row whose `QID` is that qid or a re-ask of it; scoped to the task, not already used to resume it |
| `quorum.adopt` | One quorum-adopted answer for one qid. It is also the grant that resumes a task blocked on `quorum:<qid>@<path>#sha256=<digest>`: the decision must be `Q-<that qid>`, or `Q-<re-ask qid>` for a re-ask whose question record re-derives that qid as its lineage root; scoped to the task, and not already used to resume it |
| `quorum.extend-budget` | A finite drift-budget raise for one named phase. `human` only, at most two per run |
| `dispatch.extend-budget` | A finite raise of the `agent_dispatch_count` ceiling. `human` only. It does not stand in for the drift grant, and the drift grant does not stand in for it |
| `none` | Nothing. The entry is a record |

Never take authority from an answer's wording, a generic approval, another
agent's preference, or an entry with no action field. A quorum answer of
"proceed" is as empty as a human's.

## File-first resume

On compaction, restart, interruption or doubt:

1. `validate_run`: identity, schema, filesystem;
2. read the spec, master plan, `progress.md` (**`## Stage` first**), the active
   phase plan and the applicable decisions;
3. read `findings.md` and any active fix round;
4. classify every open quorum with `classify_quorum` (see the Resume section of
   `quorum.md`);
5. `reconcile_run(run_dir, run_command=...)` returns `actions`, `questions` and
   `diagnostics`. It re-reads every phase plan, imports a matching complete
   result once through `import_worker_result`, and reports anything that
   contradicts;
6. derive the next action. Start nothing new until every `[~]` is reconciled.

A consistent active owner with no result stays `[~]`, on the same attempt. A
commit that appeared just before the interruption is neither success nor a
reason to redo the work. Import only evidence that validates independently.
Partial, conflicting or unverifiable state stays blocked and goes to the user.
Completed work is not rerun, and unfinished work is not skipped.

A quorum whose context moved (`stale-context`) is never re-decided on resume. It
is flagged to stage 11.

## Supported platform

Cooperating processes share one host and a local filesystem, with OS locks, hard
links and atomic same-filesystem replacement.

- Linux is exercised natively.
- Do not claim macOS or Windows as tested without a native run.
- Network and distributed filesystems are not covered.

Run files survive compaction in the same workspace. They do not survive
deletion, machine loss, or a fresh clone. A persisted `complete` holds only while
the repository stays at the accepted HEAD with a clean tree.

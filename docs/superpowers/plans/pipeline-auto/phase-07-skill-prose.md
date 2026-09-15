# Phase 07 — Skill Prose Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write the whole of `superb:pipeline-auto`'s teaching surface — `SKILL.md`, five references, four dispatch prompts, three templates, two inlined SDD scripts, two agent definitions — plus the one mechanical test this phase genuinely owns, so that the machinery built in P02–P06 is reachable, explained, and defended against being quietly loosened.

**Architecture:** The controller's behaviour lives in prose that routes; the state module built in P02–P06 enforces it. `SKILL.md` is a router and a Red Flags list, never a manual: it carries the invocation table, the zero-assumption reversal, the twelve-stage routing table, and the rules most likely to be "simplified" away. Each reference owns one stage band and is loaded only for that band. The two agent files are security boundaries expressed as frontmatter: the brain's `tools:` allowlist is what makes depth-1-by-construction and an unforgeable audit trail true, not the prose asking nicely. The SDD review protocol is **inlined** — copied, re-pointed at this skill's run directory, and credited — because a review protocol an unrelated plugin update can overwrite is not reproducible.

**Tech Stack:** Markdown for every deliverable. Bash for the two inlined scripts. Python 3.11 standard library only (`unittest`, `pathlib`, `re`, `os`) for `tests/test_skill_structure.py`. **There is no pytest on this machine** — `python3 -c "import pytest"` raises `ModuleNotFoundError`. Tests are `unittest.TestCase`, discovered with `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`, matching P02's convention.

**Spec:** `docs/superpowers/specs/2026-09-14-pipeline-auto-design.md`

**Master plan:** `docs/superpowers/plans/2026-09-14-pipeline-auto-master-plan.md`

**Depends on:** P06. **Review class:** `final-only`.

---

## Global Constraints

- `plugins/superb/skills/pipeline/` is **not modified**. Not one line. Verify with `git diff --name-only` before every commit.
- Schema string is exactly `pipeline-auto/v1`; tracker marker is exactly `<!-- pipeline-auto/v1 -->`.
- No migration path from `pipeline-run/v1` or `pipeline-run/v2` exists or is ever added, in either direction.
- A foreign, missing, malformed, or unknown schema is a **read-only stop**: preserve the directory, change no files, dispatch nothing.
- Rungs are **schema constants, not run configuration**: `specified` 0.95, `code-evidenced` 0.85, `convention-cited` 0.70, `engineering-judgement` 0.55, `speculation` 0.30.
- Adoption floor is `code-evidenced` (0.85). `convention-cited` and everything below it **cannot be adopted**.
- A brain **never types a number**. It selects a rung; the controller derives the value.
- Spread is measured **by rung**: where more than one cluster exists, the winner's rung must be strictly higher than the runner-up's. Equal rungs never adopt.
- Drift budget: **3 quorum adoptions per phase, 10 per run**, checked **before dispatch**. Escalations never count against it. At most 2 human-granted extensions per run.
- Depth cap is **2**. Human decisions are depth 0.
- Implementation tasks may occupy at most `worker_limit - 3` slots. `worker_limit >= 4` is required for concurrency.
- Exactly three brains per quorum, exactly three readers at stage 01. A count is never reduced to fit capacity.
- Python: standard library only. No new dependencies in any phase.
- **The test runner is `unittest`, not `pytest`.** `pytest` is not installed here — `python3 -c "import pytest"` raises `ModuleNotFoundError` on this machine's Python 3.11.2. Every test this phase writes is a `unittest.TestCase`. The inlined SDD material assumes pytest in places; adapt the command, never copy it.
- **The discovery command is `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`, with no `-t`.** `-t .` raises `ImportError: Start directory is not importable` here, because `pipeline-auto` is hyphenated and top-level-relative discovery tries to import `plugins.superb.skills.pipeline-auto.tests`, which is not a legal Python package name. An `__init__.py` does not fix it. Also: `unittest` takes repeated `-k A -k B` and ORs them; it does not accept pytest's `-k "A or B"`.
- **The project's test runner is discovered, never assumed.** Read the target repository's CI config, manifest and existing test files, and record what you find. A plan naming a runner that is not installed is a plan failure — and the failure does not surface until an implementer tries to run it, by which point it looks like the implementer's problem.
- **A verification command is not verified until it has been executed once in this repository.** A command that looks correct, and is correct in general, can still be unrunnable here: one hyphen in a directory name is enough. The plan author runs the tuple, in this repository, before writing it into the plan. This build learned it the expensive way — a runner that was not installed, then a discovery flag that cannot work with a hyphenated skill directory, both of which would have shipped into all seven phases' verification tuples.
- **No absolute home-directory paths in any committed file.** Repository-relative paths, `~`, or `$HOME` expanded at runtime only. This phase writes more committed prose than any other, so it is the phase most likely to break the rule.
- No push, no publish, no PR, no merge into `main`/`master`.

---

## What this phase is, and what it is not

P02–P06 built a state machine. It is currently unreachable: nothing tells a controller that it exists, which reference to open at stage 09, what a brain is allowed to be told, or why the adoption floor is not a knob. P07 writes that.

P07 writes **no Python that the run executes**. `scripts/pipeline_auto_state.py` is finished and is not touched here. The only Python this phase adds is a test.

P07 **does not** re-derive any rule. Every number, every enum value, every prohibition in the prose is copied from the spec or from the P02–P06 interface contracts. Where the prose and the state module disagree, the state module is right and the prose is a defect.

---

## Why this phase has almost no tests — read this before adding one

**Prose has no unit-testable fault.** A test that greps `SKILL.md` for the sentence "never average member rungs" passes the moment somebody types that sentence, and fails only if somebody deletes it — which nobody does by accident, and which anybody deleting it on purpose would also delete the test for. It catches no mistake a real maintainer would plausibly make. It converts a documentation review into a string-matching ritual and creates the false impression that the prose is covered.

This is written here on purpose, against this phase, so that a later reviewer scanning P07 for missing coverage finds the reasoning already made rather than assuming it was overlooked. **Do not add grep-for-a-sentence tests to this phase.** If you believe a specific sentence needs mechanical protection, the correct move is to make the rule structural in the state module — which is where P03 already put every rule that could be made structural — not to assert on its wording.

**This phase's real gate is P08.** P08 replays the eight P01 pressure scenarios with this prose present and asserts each scenario's `GREEN predicate:` from `tests/pressure/oracles.md` verbatim. That is the test. It measures whether a controller that read this prose behaves correctly under pressure, which is the only thing that matters about it and the only thing a transcript can show. P01 recorded the exact rationalizations agents reached for when the prose was absent; Task 12 of this plan requires the Red Flags table to answer those recorded rationalizations rather than imagined ones.

**One thing here is mechanically testable, and this phase owns it.** `tests/test_skill_structure.py` asserts that the routing surface is intact: the frontmatter parses and stays inside its limits, every reference named in `SKILL.md`'s routing table exists on disk, every agent named exists as a file, every prompt template referenced resolves, every script referenced is executable, and the brain agent's tool allowlist still excludes `Agent`, `Write` and `Edit`.

Its named faults, both real and both likely:

1. **A renamed reference.** Someone splits `references/quorum.md` or renames it and does not update the routing table. Nothing fails at author time. The failure appears at runtime, mid-run, at the moment a controller tries to open the reference for the active stage — the worst possible moment, in the least reproducible way. No other test in this repository catches it.
2. **A widened agent.** Someone adds `Write` to `pipeline-auto-brain.md` so it can "record its own answer", adds `Agent` so it can "check something", or — most likely of all — adds `Bash` back to either agent because "it only needs to run `git log`". Each silently destroys a load-bearing guarantee. A brain with `Write` can edit `decisions.md` and the audit trail becomes worthless; a brain with `Agent` can spawn and depth-1-by-construction becomes depth-unbounded-by-hope; an intent reader with either can rewrite the intent brief that every later `consistent_with` citation anchors to. And any of them with `Bash` has `Write`, because frontmatter allowlists tools and not commands. The frontmatter is the enforcement point, so the frontmatter is what gets asserted — as an **exact set** per agent, in **two separate test classes**, each naming its own agent.

**Both tool boundaries are fully asserted. Nothing about either is prose-only.** An earlier draft of this phase conceded one unenforced leg — "read-only Bash", which frontmatter cannot express — and that concession is retired, not restated: the tool was removed from both agents instead. If you are reading this looking for the known hole, there isn't one, and the correct response to that is not to relax the assertion.

Everything else in this phase is judged by reading it.

---

## File Structure

| File | Responsibility | Action |
| --- | --- | --- |
| `plugins/superb/skills/pipeline-auto/SKILL.md` | Router. Frontmatter, invocation modes, the zero-assumption reversal and its answer, files-are-the-authority, twelve-stage routing table, the one gate, Red Flags, stop checks | Create |
| `plugins/superb/skills/pipeline-auto/references/planning.md` | Stages 01–07: intent read, question synthesis, the one gate, design and gate classification, spec, master plan, phase fan-out | Create |
| `plugins/superb/skills/pipeline-auto/references/quorum.md` | Admissibility, independence and reading assignments, the payload prohibition list, the rung ladder, adoption arithmetic, tie-breaks, drift budget and extension, escalation, replay | Create |
| `plugins/superb/skills/pipeline-auto/references/execution.md` | Stages 08–10: the review-intensity dial, the per-task gate, TDD, typed scopes, evidence, integration, debugging, the one-way ratchet | Create |
| `plugins/superb/skills/pipeline-auto/references/review.md` | Stages 11–12: the two-reviewer master gate, contradiction routing, the adjudicator, the completeness freeze, final verification | Create |
| `plugins/superb/skills/pipeline-auto/references/persistence.md` | Tracker operations, the read-only stop, status, resume, reconciliation, provenance visibility | Create |
| `plugins/superb/skills/pipeline-auto/prompts/brain.md` | Quorum brain dispatch template: strict JSON out, rung selection by name, the prohibition list, no field for raising a question | Create |
| `plugins/superb/skills/pipeline-auto/prompts/implementer.md` | Per-task implementer dispatch template, adapted from SDD | Create |
| `plugins/superb/skills/pipeline-auto/prompts/task-reviewer.md` | Three-verdict reviewer template: spec, quality, independent verification evidence | Create |
| `plugins/superb/skills/pipeline-auto/prompts/adversarial-reviewer.md` | Refutation template for triggered diffs | Create |
| `plugins/superb/skills/pipeline-auto/templates/task-brief.md` | Shape of the per-task brief file the implementer reads | Create |
| `plugins/superb/skills/pipeline-auto/templates/worker-report.md` | Shape of the detailed report an implementer writes to `scratch/` | Create |
| `plugins/superb/skills/pipeline-auto/templates/completeness-proposals.md` | The frozen `MISSING-FROM-SPEC` ledger | Create |
| `plugins/superb/skills/pipeline-auto/scripts/task-brief` | Extract one task's text from a phase plan into a uniquely named file. Inlined from SDD, re-pointed at the run's `scratch/` | Create (mode 755) |
| `plugins/superb/skills/pipeline-auto/scripts/review-package` | Build commit list + stat + full diff for a range into one file. Inlined from SDD, re-pointed at the run's `scratch/` | Create (mode 755) |
| `plugins/superb/agents/pipeline-auto-brain.md` | **Security boundary.** `tools: Read, Grep, Glob` — exactly three. No Bash, no Agent, no Write, no Edit | Create |
| `plugins/superb/agents/pipeline-auto-intent-reader.md` | **Security boundary.** `tools: Read, Grep, Glob` — exactly three. Stage-01 reader; strict JSON hypothesis out, no design proposals | Create |
| `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py` | The one mechanical test this phase owns | Create |

Not P07's, and not to be created here: `scripts/pipeline_auto_state.py` and `scripts/sdd-workspace` (P02), `templates/progress.md` and `templates/decisions.md` (P02), `templates/findings.md` (P03), `templates/worker-result.md` and `templates/verification-evidence.md` (P04 — see Unresolved), `examples/controller_walkthrough.py` (P09).

---

## Interface contracts

### Consumed from P02

`SCHEMA = "pipeline-auto/v1"`, `MARKER = "<!-- pipeline-auto/v1 -->"`, the exception hierarchy (`ForeignSchemaError`, `TrackerValidationError`, `TrackerWriteError`, `UpdateOutcomeUncertain`, `PlanMetadataError`), `locked_tracker_update`, `initialize_run`, `publish_immutable`, `derive_next_action`, and `scripts/sdd-workspace`, which prints the run's self-ignoring `scratch/` directory. `references/persistence.md` documents these; it does not redefine them.

### Consumed from P03 — the prompts and templates must conform exactly

`RUNGS`, `RUNG_ORDER`, `ADOPTABLE = {"specified", "code-evidenced"}`, `DEMOTION_RUNG = "engineering-judgement"`, `ADOPTION_FLOOR = 0.85`, `DEPTH_CAP = 2`, `BUDGET_PER_PHASE = 3`, `BUDGET_PER_RUN = 10`, `MAX_EXTENSIONS = 2`, `IRREVERSIBLE_AXES`, `READING_ASSIGNMENTS`.

The brain response schema `validate_brain_response` accepts — every key required, no other key permitted:

```json
{
  "qid": "a1b2c3d4e5f6",
  "answer_key": "postgres",
  "answer": "Back the session table with the existing PostgreSQL instance.",
  "rung": "code-evidenced",
  "evidence": [{"kind": "repo", "path": "db/engine.py", "line": 12, "quote": "PostgresEngine"}],
  "consequences": [{"kind": "file-exists", "subject": "db/session.sql", "value": "present"}],
  "consistent_with": [{"kind": "decision", "id": "H-001"}],
  "forecloses": ["a filesystem-only deployment"],
  "blast": ["storage-engine"],
  "alternatives": [{"answer_key": "sqlite", "rung": "engineering-judgement",
                    "reason": "no concurrent-writer story"}],
  "what_would_change_my_mind": "A decision record pinning the run to a single-file database.",
  "blocker": null
}
```

`evidence[*].kind` ∈ `spec | intent-brief | decision | repo`; a `decision` item carries `decision` in place of `line`. `consistent_with[*].kind` ∈ `decision | spec | repo`. `consequences[*].kind` ∈ `file-exists | signature | command-passes | config-value`.

`build_payload(qid, brain_index, *, run_dir)` emits exactly these keys and no others: `qid`, `question`, `axis`, `options`, `reading_assignment`, `decisions_effective`, `rungs`, `response_schema`, `you_are_one_of_several`. `prompts/brain.md` must be renderable from that payload alone. **If the prompt template asks for anything the payload does not carry, the prompt is the defect.**

`READING_ASSIGNMENTS` is index-addressed: 0 → `spec-and-intent`, 1 → `code-and-tests`, 2 → `decisions-and-plan`.

### Consumed from P05

`ADVERSARIAL_TRIGGERS = ("concurrency", "authz", "crypto", "schema", "migration", "delete", "regulated", "public-api", "large-surface")`; `RATCHET_TRIGGERS = ("adversarial-finding", "repeated-suite-failure", "debug-locality", "low-confidence-dependency", "accumulated-surface")`; `adversarial_required(diff_paths, changed_lines) -> str | None` returns the trigger **name**, so the tracker records which one fired.

### Consumed from P01

`tests/pressure/RED-baseline.md` — the committed curated record carrying each scenario's verbatim rationalization and its `NON_DISCRIMINATING` verdict. Task 12 reads it. A scenario P01 marked `NON_DISCRIMINATING` gets **no prose written for it**: `superpowers:writing-skills` is explicit that if the control did not exhibit the failure there is nothing to fix.

### P07 produces — consumed by P08 and P09

- The complete skill surface listed in File Structure above, installable from `plugins/superb/skills/pipeline-auto/`.
- `tests/test_skill_structure.py`, part of the run-wide suite from here on.

---

## Tasks

Twelve tasks. Task 1 writes the test, which stays RED until Task 12 — that is deliberate and is the shape `superpowers:writing-skills` prescribes, since the routing table cannot be truthful until the things it routes to exist. Each task names the subset of the validator it turns green.

`SKILL.md` is written **last**, in Task 12, for exactly that reason: a routing table written before its targets is a table of guesses.

---

### Task 1: The structure validator (RED)

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: nothing. This file imports no project code — importing the state module would couple the routing check to the spine and make a spine failure look like a routing failure.
- Produces: `tests/test_skill_structure.py`, discovered by `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v` and added to the run-wide verification suite from this phase onward. It is a `unittest.TestCase` module with no third-party import, so it runs on a stdlib-only Python 3.11.

Write the whole validator now, against files that do not exist yet. It fails completely. That is the point: every later task is measured by which of these tests it turns green, and a test written after the prose would be a test written to fit the prose.

- [ ] **Step 1: Write the failing test**

Create `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`:

```python
"""Structure validator for superb:pipeline-auto.

Prose carries no unit-testable fault, so this is the only mechanical test
phase 07 owns. It asserts that the skill's routing surface is intact.

Named faults it catches:

1. A reference, prompt, template, agent or script renamed or moved without
   updating SKILL.md's routing table. Nothing fails at author time; the
   dead route surfaces at runtime, mid-run, when the controller opens the
   reference for the active stage. No other test catches it.
2. The pipeline-auto-brain agent's tool allowlist widened. A brain with
   Write -- or with Bash, which is Write with extra steps -- can edit
   decisions.md and the audit trail is worthless; a brain with Agent can
   spawn and the depth-1-by-construction guarantee is gone. The frontmatter
   is the enforcement point, so the frontmatter is what gets asserted, and
   the assertion is on the exact set rather than on the absence of a
   blacklist.

Do NOT add assertions here about the *wording* of the prose. A grep for a
sentence passes the moment the sentence exists and catches no mistake
anyone would plausibly make. The prose's gate is phase 08's pressure
transcripts.
"""

import os
import re
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[5]
SKILL = REPOSITORY / "plugins/superb/skills/pipeline-auto"
AGENTS_DIR = REPOSITORY / "plugins/superb/agents"
SKILL_MD = SKILL / "SKILL.md"

# agentskills.io/specification: the whole frontmatter block is capped at 1024
# characters; writing-skills asks for a description under 500.
FRONTMATTER_MAX = 1024
DESCRIPTION_MAX = 500

REQUIRED_REFERENCES = ("planning", "quorum", "execution", "review", "persistence")
REQUIRED_PROMPTS = ("implementer", "task-reviewer", "adversarial-reviewer", "brain")
EXECUTABLE_SCRIPTS = ("task-brief", "review-package", "sdd-workspace")

# The master plan's File Structure table. progress/decisions come from P02,
# findings from P03, worker-result/verification-evidence from P04; the rest
# are P07's. A template missing at this point is a real gap in the skill,
# whichever phase owned it, so this test names all eight.
MASTER_PLAN_TEMPLATES = (
    "progress", "decisions", "findings", "worker-result",
    "verification-evidence", "task-brief", "worker-report",
    "completeness-proposals",
)

BRAIN_AGENT = AGENTS_DIR / "pipeline-auto-brain.md"
# Exactly three tools, and Bash is not one of them. Frontmatter allowlists
# tools, not commands, so "read-only Bash" is not something the platform can
# grant: a brain holding Bash can run `echo > decisions.md` as easily as
# `git log`. Keeping it would have left the audit-trail guarantee resting on
# prose the brain could ignore. Read/Grep/Glob cover everything grounding
# actually needs -- resolve a citation to a file and a line, search for
# exemplars -- so the narrowing costs nothing and closes the last leg.
BRAIN_TOOLS_EXACT = ("Glob", "Grep", "Read")

INTENT_READER_AGENT = AGENTS_DIR / "pipeline-auto-intent-reader.md"
# The same three, for a sharper reason. The brain can corrupt the record; the
# intent reader writes the intent brief that every later `consistent_with`
# citation anchors to. A shell there corrupts the anchor, and every downstream
# grounding claim inherits the corruption while still resolving cleanly -- a
# citation that resolves to a line that is there, in a file that was rewritten.
INTENT_READER_TOOLS_EXACT = ("Glob", "Grep", "Read")

# Shared by both boundaries. Asserted as an EXACT SET, not as the absence of
# these names: a blacklist only fails on the tools somebody remembered.
FORBIDDEN_AGENT_TOOLS = (
    "Agent", "Task", "Bash", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "AskUserQuestion",
)

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]*)?\)")
BACKTICK_PATH = re.compile(
    r"`((?:references|prompts|templates|scripts)/[A-Za-z0-9._-]+)`"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def split_frontmatter(text: str):
    """Return (raw_block, fields, body) or (None, {}, text) when absent."""
    if not text.startswith("---\n"):
        return None, {}, text
    end = text.find("\n---\n", 3)
    if end == -1:
        return None, {}, text
    raw = text[4:end + 1]
    fields = {}
    for line in raw.splitlines():
        if line[:1].strip() and ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return raw, fields, text[end + 5:]


def referenced_paths(text: str) -> set:
    """Every skill-relative path the prose points at, by link or by backtick."""
    found = set()
    for target in MARKDOWN_LINK.findall(text):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        found.add(target.lstrip("./"))
    for target in BACKTICK_PATH.findall(text):
        found.add(target)
    return found


class SkillFrontmatter(unittest.TestCase):
    def test_skill_md_exists(self):
        self.assertTrue(SKILL_MD.is_file(), f"missing {SKILL_MD}")

    def test_frontmatter_parses_and_names_the_skill(self):
        raw, fields, _ = split_frontmatter(read(SKILL_MD))
        self.assertIsNotNone(raw, "SKILL.md has no YAML frontmatter block")
        self.assertEqual(fields.get("name"), "pipeline-auto")

    def test_description_is_a_trigger_not_a_workflow_summary(self):
        _, fields, _ = split_frontmatter(read(SKILL_MD))
        description = fields.get("description", "")
        self.assertTrue(description.startswith("Use when"), description[:80])
        self.assertLessEqual(len(description), DESCRIPTION_MAX)

    def test_frontmatter_is_within_the_specification_limit(self):
        raw, _, _ = split_frontmatter(read(SKILL_MD))
        self.assertLessEqual(len(raw or ""), FRONTMATTER_MAX)


class RoutingTable(unittest.TestCase):
    """Every route named in SKILL.md resolves, and every reference is routed."""

    def test_every_required_reference_exists(self):
        for name in REQUIRED_REFERENCES:
            with self.subTest(reference=name):
                self.assertTrue((SKILL / "references" / f"{name}.md").is_file())

    def test_every_path_named_in_skill_md_resolves(self):
        for target in sorted(referenced_paths(read(SKILL_MD))):
            with self.subTest(target=target):
                self.assertTrue((SKILL / target).exists(), f"dead route: {target}")

    def test_every_reference_on_disk_is_routed_from_skill_md(self):
        routed = referenced_paths(read(SKILL_MD))
        for path in sorted((SKILL / "references").glob("*.md")):
            with self.subTest(reference=path.name):
                self.assertIn(f"references/{path.name}", routed,
                              f"{path.name} exists but SKILL.md routes nothing to it")

    def test_every_path_named_in_a_reference_resolves(self):
        for reference in sorted((SKILL / "references").glob("*.md")):
            for target in sorted(referenced_paths(read(reference))):
                with self.subTest(reference=reference.name, target=target):
                    self.assertTrue((SKILL / target).exists(),
                                    f"dead route in {reference.name}: {target}")


class Prompts(unittest.TestCase):
    def test_every_required_prompt_exists(self):
        for name in REQUIRED_PROMPTS:
            with self.subTest(prompt=name):
                self.assertTrue((SKILL / "prompts" / f"{name}.md").is_file())

    def test_every_prompt_is_referenced_by_some_prose_file(self):
        prose = read(SKILL_MD) + "".join(
            read(path) for path in sorted((SKILL / "references").glob("*.md"))
        )
        routed = referenced_paths(prose)
        for name in REQUIRED_PROMPTS:
            with self.subTest(prompt=name):
                self.assertIn(f"prompts/{name}.md", routed,
                              f"prompts/{name}.md is unreachable from the prose")


class Templates(unittest.TestCase):
    def test_every_master_plan_template_exists(self):
        for name in MASTER_PLAN_TEMPLATES:
            with self.subTest(template=name):
                self.assertTrue((SKILL / "templates" / f"{name}.md").is_file())


class Scripts(unittest.TestCase):
    def test_every_script_exists_and_is_executable(self):
        for name in EXECUTABLE_SCRIPTS:
            with self.subTest(script=name):
                path = SKILL / "scripts" / name
                self.assertTrue(path.is_file(), f"missing {path}")
                self.assertTrue(os.access(path, os.X_OK), f"not executable: {path}")

    def test_the_state_module_is_present(self):
        self.assertTrue((SKILL / "scripts" / "pipeline_auto_state.py").is_file())


class Agents(unittest.TestCase):
    def test_every_agent_named_in_the_prose_exists_as_a_file(self):
        prose = read(SKILL_MD) + "".join(
            read(path) for path in sorted((SKILL / "references").glob("*.md"))
        )
        named = set(re.findall(r"pipeline-auto-(?:brain|intent-reader)", prose))
        self.assertTrue(named, "SKILL.md and references name no agent at all")
        for agent in sorted(named):
            with self.subTest(agent=agent):
                path = AGENTS_DIR / f"{agent}.md"
                self.assertTrue(path.is_file(), f"missing agent file {path}")
                _, fields, _ = split_frontmatter(read(path))
                self.assertEqual(fields.get("name"), agent)

    def test_intent_reader_exists(self):
        self.assertTrue((AGENTS_DIR / "pipeline-auto-intent-reader.md").is_file())


def declared_tools(case, path):
    """The agent's declared tool set, sorted. Fails loudly if absent."""
    _, fields, _ = split_frontmatter(read(path))
    case.assertIn("tools", fields, f"{path.name} declares no tools: field")
    return tuple(sorted(
        tool.strip() for tool in fields["tools"].split(",") if tool.strip()
    ))


# Two boundaries, two test classes, each naming its own agent. Deliberately not
# one test looping over a list of agents: a loop whose list is empty -- or whose
# list someone shortens -- passes silently, and a boundary that can pass by
# disappearing is not a boundary.
class BrainToolBoundary(unittest.TestCase):
    """pipeline-auto-brain's allowlist is a security boundary, not configuration."""

    def test_brain_agent_exists(self):
        self.assertTrue(BRAIN_AGENT.is_file(), f"missing {BRAIN_AGENT}")

    def test_brain_tools_are_exactly_read_grep_glob(self):
        self.assertEqual(declared_tools(self, BRAIN_AGENT), BRAIN_TOOLS_EXACT)

    def test_brain_cannot_write_edit_spawn_or_shell(self):
        declared = set(declared_tools(self, BRAIN_AGENT))
        for tool in FORBIDDEN_AGENT_TOOLS:
            with self.subTest(tool=tool):
                self.assertNotIn(
                    tool, declared,
                    f"{tool} in pipeline-auto-brain.md destroys a load-bearing "
                    f"guarantee; see references/quorum.md. Bash counts: a shell "
                    f"is write access wearing a read-only description.",
                )


class IntentReaderToolBoundary(unittest.TestCase):
    """pipeline-auto-intent-reader's allowlist protects the anchor, not the record."""

    def test_intent_reader_agent_exists(self):
        self.assertTrue(INTENT_READER_AGENT.is_file(), f"missing {INTENT_READER_AGENT}")

    def test_intent_reader_tools_are_exactly_read_grep_glob(self):
        self.assertEqual(
            declared_tools(self, INTENT_READER_AGENT), INTENT_READER_TOOLS_EXACT
        )

    def test_intent_reader_cannot_write_edit_spawn_or_shell(self):
        declared = set(declared_tools(self, INTENT_READER_AGENT))
        for tool in FORBIDDEN_AGENT_TOOLS:
            with self.subTest(tool=tool):
                self.assertNotIn(
                    tool, declared,
                    f"{tool} in pipeline-auto-intent-reader.md lets the stage-01 "
                    f"reader rewrite the intent brief every later consistent_with "
                    f"citation anchors to; see references/quorum.md",
                )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`

Expected: every test in `SkillFrontmatter`, `RoutingTable`, `Prompts`, `Agents` and `BrainToolBoundary` ERRORs or FAILs — `SKILL.md`, the references, the prompts and both agent files do not exist. `Templates` fails on `task-brief`, `worker-report` and `completeness-proposals`. `Scripts::test_every_script_exists_and_is_executable` fails on `task-brief` and `review-package`.

If `Scripts::test_the_state_module_is_present`, `Templates` on `progress`/`decisions`/`findings`, or `Scripts` on `sdd-workspace` fail, **stop**: P02 or P03 did not land what this phase depends on, and that is a dependency failure, not something to fix here.

- [ ] **Step 3: No implementation in this task**

There is nothing to implement. The validator is the deliverable; Tasks 2–12 are its implementation.

- [ ] **Step 4: Confirm the expected-failure inventory is recorded**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v 2>&1 | tail -30`

Expected: the failure list matches Step 2. Paste it into the commit body so a later reader can see which failures were expected at this point.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py
git commit -m "test(pipeline-auto): structure validator for the skill routing surface"
```

---

### Task 2: The two agent files — the security boundary

**Files:**
- Create: `plugins/superb/agents/pipeline-auto-brain.md`
- Create: `plugins/superb/agents/pipeline-auto-intent-reader.md`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: the brain response schema and `build_payload` key set from P03 (see Interface contracts).
- Produces: two agent types dispatchable by name — `pipeline-auto-brain` and `pipeline-auto-intent-reader`, **each declaring exactly `tools: Read, Grep, Glob`**. `references/quorum.md` (Task 7) and `references/planning.md` (Task 8) dispatch them by exactly these names. No registration step exists or is needed: `plugins/superb/agents/` is discovered by directory, which is how `architecture-discovery` and `bug-investigator` are already found.

These two files are written first, before any prose, because they are the only deliverables in this phase that carry enforcement rather than instruction.

**`pipeline-auto-brain` is a security boundary.** Its `tools:` line is what makes two of the design's guarantees true:

- **No `Write`, no `Edit`.** A brain that can write can edit `decisions.md`. `decisions.md` is the audit trail that makes every quorum-adopted decision attributable and permanent; a participant in the vote that can also edit the record makes the entire trail worthless — not degraded, worthless, because nobody reading it afterwards can tell which entries the brains wrote.
- **No `Agent`.** A brain that can spawn can open a quorum inside a quorum. The spec's guarantee is that at most one quorum is in flight per run and that *a quorum cannot trigger a quorum*, and it is true **by construction** rather than by a depth counter. Give the brain `Agent` and that sentence becomes a hope.

- **No `Bash`.** This one is a deliberate narrowing from the design's first draft, which said "Read/Grep/Glob and read-only Bash". **Read-only Bash is not a thing the platform can give us.** Frontmatter allowlists *tools*, not *commands*, so a brain holding `Bash` can run `echo > decisions.md` as easily as `git log` — and the entire justification for restricting brains is that one with write access makes the audit trail worthless. Keeping `Bash` would have left the central guarantee resting on a sentence in the prompt that a brain is free to ignore. `Read`, `Grep` and `Glob` cover everything grounding actually needs: resolve a citation to a file and a line, and search for exemplars. Nothing is lost, and the boundary goes from three legs enforced out of four to **all four enforced**.

The third leg is the response schema: **there is no field a brain can use to raise a question of its own.** The only exit is `blocker`. That is how unbounded recursion is prevented at the type level rather than with a counter — a counter can be raised, a missing field cannot be filled in.

Because every leg is now declarative, `tests/test_skill_structure.py` asserts the **exact** tool set rather than the absence of a blacklist. An exact-set assertion fails on a tool nobody thought to forbid; a blacklist only fails on the ones somebody remembered.

`pipeline-auto-intent-reader` exists because `brainstorm-architect` is the wrong agent for stage 01. It runs with all tools, and — by its own description — explores options, evaluates trade-offs and recommends. Pointed at "read this idea and tell me what it says", it starts proposing, and a stage-01 reader that proposes has contaminated the intent brief with design before the human has answered a single question.

**The intent reader is a security boundary too, and a sharper one.** It declares the same exact three tools, for a reason that is worse rather than milder: the brain can corrupt the **record**, while the intent reader writes the **anchor**. Every adopted answer in this run must cite a spec line or a stage-03 decision in `consistent_with`, and the intent brief is what those citations rest on. A shell there corrupts the anchor, and every downstream grounding claim inherits the corruption **while still resolving cleanly** — a citation that points at a line that really is there, in a file that was quietly rewritten. Citation verification cannot catch that, because the citation is true. Nothing downstream can catch it. So it is prevented at the only point where prevention works: the tool declaration.

Two agents, two exact sets, **two separate test classes** in the validator. Not one test looping over a list — a loop whose list is empty, or whose list somebody shortens, passes silently, and a boundary that can pass by disappearing is not a boundary.

- [ ] **Step 1: Write the failing test**

Already written in Task 1. The relevant classes are `Agents` and `BrainToolBoundary`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k BrainToolBoundary -k IntentReaderToolBoundary -k Agents`

Expected: FAIL — `missing agent file .../pipeline-auto-brain.md`.

`unittest` accepts repeated `-k` flags and ORs them. It does **not** accept
pytest's `-k "A or B"`, and there is no `-t` flag in any command here: `-t .`
cannot work with a hyphenated skill directory.

- [ ] **Step 3: Write the two agent files**

Create `plugins/superb/agents/pipeline-auto-brain.md`:

```markdown
---
name: pipeline-auto-brain
description: Use only when superb:pipeline-auto opens a quorum on one blocking question. One of three independently-briefed readers; returns one strict JSON answer with a grounding rung and nothing else. Never dispatched by a human, never dispatched outside a quorum.
model: opus
color: yellow
tools: Read, Grep, Glob
---

You answer exactly one question, in writing, from evidence you can cite.

You are one of several readers answering this same question from different
starting material. You will not see what the others say, and they will not see
what you say. There is no argmax to win: your answer is judged on the quality of
its grounding, not on whether it agrees with anyone.

## Your tools, and why they are the only three

`Read`, `Grep`, `Glob`. That is the whole list, and it is deliberate.

You have no `Write` and no `Edit` because you are a participant in a decision
whose record must stay attributable — a reader who can also edit the record
makes the record worth nothing.

You have **no `Bash`**, for the same reason rather than a different one. A shell
is write access wearing a read-only description: `echo > decisions.md` is as
available from a shell as `git log` is, and no amount of instruction closes that.
The restriction had to be declarative to be a restriction at all.

You have no way to dispatch another agent, because a reader who can dispatch can
open a question inside a question, and the run's guarantee that this cannot
happen is structural rather than a counter somebody remembered to increment.

**Nothing is missing.** Grounding needs two things: resolving a citation to a
file and a line, which is `Read`; and finding exemplars, which is `Grep` and
`Glob`. If you catch yourself wanting to run a command, what you actually want is
to read a file — do that. If the answer genuinely depends on executing something,
that is not a question you can settle: set `blocker` and say so.

## What you receive

One JSON payload. It carries: the question, verbatim and identical for every
reader; its axis; the named options, if the question had any; your **reading
assignment**; the path to `decisions-effective.md`; and the list of grounding
rung names.

**Read your assignment first and read it properly.** Each reader gets a
different one — one reads the spec and intent brief, one reads the code and
tests, one reads the decisions record and the phase plan. This is a bias toward
a *source*, never toward an answer. You may read outside your assignment when a
specific question demands it, but your assignment is where you are expected to
have looked hardest, and an answer that never touched it is a weak answer.

`decisions-effective.md` carries every decision already made, its answer, and
whether a human or a quorum made it. Treat all of them as settled. **Never
propose an answer that contradicts a decision whose provenance is `human`** —
say so in `blocker` instead.

## What you return

**One JSON object and nothing else.** No preamble, no commentary, no summary,
no markdown fence around it if you can avoid one.

```json
{
  "qid": "a1b2c3d4e5f6",
  "answer_key": "postgres",
  "answer": "Back the session table with the existing PostgreSQL instance.",
  "rung": "code-evidenced",
  "evidence": [{"kind": "repo", "path": "db/engine.py", "line": 12, "quote": "PostgresEngine"}],
  "consequences": [{"kind": "file-exists", "subject": "db/session.sql", "value": "present"}],
  "consistent_with": [{"kind": "decision", "id": "H-001"}],
  "forecloses": ["a filesystem-only deployment"],
  "blast": ["storage-engine"],
  "alternatives": [{"answer_key": "sqlite", "rung": "engineering-judgement",
                    "reason": "no concurrent-writer story"}],
  "what_would_change_my_mind": "A decision record pinning the run to a single-file database.",
  "blocker": null
}
```

Every key is required. **Any other key is rejected and your whole response is
discarded.** There is no `confidence` key, no `score`, no `certainty`, and no
field in which to raise a question of your own. If you cannot answer, that is
what `blocker` is for.

## Never write a number

You do not score your answer. You **select a rung by name** from the list in
your payload, and someone else derives what it is worth. You are not told what
any rung is worth or which ones are good enough, and you should not try to
work it out — an answer tuned to clear a bar is an answer about the bar.

| Rung | Select it when |
| --- | --- |
| `specified` | a spec line, intent-brief line, or human decision **resolves** the question. Cite the line. |
| `code-evidenced` | a `file:line` in the repository actually contains the claim. Cite it. |
| `convention-cited` | you have two or more `file:line` exemplars of a pattern, but nothing states the rule. Cite both. |
| `engineering-judgement` | you are reasoning it out. No citation. |
| `speculation` | you are guessing. Say so. |

A rung outside that list is invalid and your response is discarded.

**Every citation is checked.** A path that does not resolve, or a line that does
not contain what you said it contains, does not get you rejected — it gets your
answer repriced at `engineering-judgement`. Inflating a rung therefore does not
raise your answer's weight; it lowers it. Cite exactly and honestly, and quote
text that is really there.

## The four fields people get wrong

**`alternatives` must name a real rejected second-best with a real reason.** An
empty list is rejected outright. "No alternatives" is almost never true; if you
genuinely cannot name one, that tells you something about how hard you looked.
Do not put your own answer in it at a lower rung to fill the field.

**`what_would_change_my_mind` must name evidence, not a mood.** "More context"
is empty. "A decision record pinning the run to a single-file database" is a
falsifier. An empty falsifier means the answer was not examined.

**`consistent_with` must cite at least one spec line or recorded decision.** An
answer grounded only in repository code has not been traced back to anything the
user asked for. Say which stage-03 answer or spec line your answer serves.

**`forecloses` must say what your answer destroys.** Not what it achieves —
what it rules out, makes expensive, or makes irreversible. Asking what an answer
achieves surfaces nothing; asking what it forecloses surfaces the risk.

## When to set `blocker`

Set `blocker` to a short string, leave `answer_key` and `answer` empty, and stop
when: the question cannot be decided from the repository, the spec, or the
decisions record; answering it would need something only the user knows —
budget, deadline, who the users are, what the product is *for*; the question is
several decisions wearing one coat; or every answer you can construct
contradicts a decision whose provenance is `human`.

A blocker is a good outcome. It costs nothing, it is never held against you, and
it routes the question to a person — which is the correct destination for a
question that needed a person.

## What you must not do

- Do not write, edit, move, delete, or commit anything, anywhere, ever.
- Do not ask for a shell, a command runner, or any tool you were not given.
  A request for wider access is not a blocker — it is an answer you cannot
  support, and the honest response is a lower rung or a `blocker`.
- Do not dispatch, spawn, or ask for another agent.
- Do not answer a question you were not asked, or widen the one you were.
- Do not restate the question, narrate your search, or explain your process.
  The JSON is the whole output.
- Do not choose an answer because it is conventional, familiar, reversible,
  configurable, or easy. Those are reasons to select a low rung, not reasons
  to raise one.
```

Create `plugins/superb/agents/pipeline-auto-intent-reader.md`:

```markdown
---
name: pipeline-auto-intent-reader
description: Use only at superb:pipeline-auto stage 01, to read what the user actually asked for and return it as a strict JSON hypothesis. One of three independent readers. Reads and reports; never designs, never proposes, never chooses a stack.
model: opus
color: cyan
tools: Read, Grep, Glob
---

You read a request and write down what it says.

**You are not designing anything.** Someone else will. If you find yourself
writing a reason an approach is good, naming a library, choosing a stack, or
sketching a structure, you have started designing and must stop and delete it.

You are one of several readers doing this independently. Your value is that you
read the request without having seen anyone else's reading of it.

## Your tools, and why they are the only three

`Read`, `Grep`, `Glob`. That is the whole list.

You have no `Write`, no `Edit`, no `Bash`, and no way to dispatch another agent.
This is not caution about a reader that happens to have no reason to write — it
is because of what you produce. The intent brief is the **anchor**: every
decision this run makes later must cite a spec line or a stage-03 answer, and
those citations rest on what you wrote down. Corrupt the record and someone
notices a contradiction; corrupt the anchor and every downstream claim inherits
it **while still checking out perfectly**, because the citation really does point
at a line that really is there, in a file that was quietly changed.

Nothing downstream can catch that, so it is prevented here, by not giving you the
capability. `Read`, `Grep` and `Glob` are everything reading a request and
searching a repository needs. If you find yourself wanting to run a command, what
you want is to read a file.

## What you receive

- The user's request, in the user's own words.
- The repository, if there is one, to establish what already exists.

## What you return

**One JSON object and nothing else.** No preamble, no prose, no summary.

```json
{
  "restated": "One paragraph, in plain words, of what the user asked for.",
  "explicit": [
    {"claim": "The importer must accept CSV and TSV.",
     "source": "user", "quote": "csv or tab separated, either one"}
  ],
  "implied": [
    {"claim": "Existing imports must keep working.",
     "basis": "the request says 'add', not 'replace'"}
  ],
  "unstated": [
    "What happens to a row that fails validation mid-file."
  ],
  "out_of_scope": [
    {"claim": "A web UI for the importer.",
     "basis": "not mentioned anywhere in the request"}
  ],
  "repository_facts": [
    {"fact": "There is already a CSV reader.",
     "path": "src/io/csv.py", "line": 1}
  ]
}
```

Every key is required; an empty list is a legitimate value. Any other key is
rejected.

## The rules that keep this a reading

**`explicit` is quotation, not paraphrase.** Every entry carries the user's own
words in `quote`. If you cannot quote it, it is not explicit — move it to
`implied` with an honest `basis`, or to `unstated`.

**`implied` must name what implies it.** "Standard practice" is not a basis.
"The request says 'add', not 'replace'" is.

**`unstated` is the most valuable thing you produce.** It is the list of
questions the request does not answer. Write it as questions about behaviour,
not as options to pick from — naming the options is the first move of designing.

| Not a reading | A reading |
| --- | --- |
| "Use Postgres for the session store." | "The request does not say where sessions are stored." |
| "Best practice is to reject the whole file." | "What happens to a row that fails validation mid-file is unstated." |
| "This should be a REST API." | "The request does not say how the importer is invoked." |

**`repository_facts` are facts with a `file:line`.** Not opinions about the
repository, not suggestions about how to fit into it.

**Do not resolve a conflict you find.** If the request contradicts itself, or
contradicts the repository, record both sides — one in `explicit`, one in
`repository_facts` — and let the controller flag it. A reader who quietly picks
the more sensible side has destroyed the signal that there was a conflict.

**Do not rank, prioritise, estimate, or phase the work.** No "first we should",
no "this is the core", no sizing.

**Do not write, edit, move, or create anything**, and do not ask for a tool you
were not given. If you cannot establish a fact by reading and searching, it is
not a fact you can report: leave it out, or put the question in `unstated`.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k BrainToolBoundary -k IntentReaderToolBoundary`

Expected: PASS — all three `BrainToolBoundary` tests and all three
`IntentReaderToolBoundary` tests. Six, not three: confirm the count, because a
`-k` pattern that matches nothing also reports success.

`Agents::test_every_agent_named_in_the_prose_exists_as_a_file` still fails: no prose names them yet. It goes green in Task 12.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/agents/pipeline-auto-brain.md plugins/superb/agents/pipeline-auto-intent-reader.md
git commit -m "feat(pipeline-auto): brain and intent-reader agents with restricted tools"
```

---

### Task 3: The two inlined SDD scripts

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/scripts/task-brief` (mode 755)
- Create: `plugins/superb/skills/pipeline-auto/scripts/review-package` (mode 755)
- Test: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: `scripts/sdd-workspace` from P02, which prints the absolute path of the run's self-ignoring `scratch/` directory.
- Produces: `scripts/task-brief PLAN_FILE TASK_NUMBER [OUTFILE]` and `scripts/review-package BASE HEAD [OUTFILE]`, each printing the path it wrote. `prompts/implementer.md` and `prompts/task-reviewer.md` name these paths; `references/execution.md` invokes them.

These are **inlined, not invoked**. `subagent-driven-development/SKILL.md:12` says the plugin-cache copy is a mirror and that "a superpowers plugin update will silently overwrite that mirror". A review protocol an unrelated plugin update can replace is not reproducible, and this skill modifies the protocol anyway. So the scripts are copied, credited in a header comment, and re-pointed.

One substantive change from the originals: the default output directory comes from **this skill's** `sdd-workspace`, which resolves to `scratch/` **inside the run directory**, not `.superpowers/sdd` at the repository root. The spec is explicit about why — `.superpowers/sdd`'s durability hole is what this hybrid exists to close, and run ephemera that outlive the run directory are ephemera nobody can reconcile.

- [ ] **Step 1: Write the failing test**

Already written in Task 1: `Scripts::test_every_script_exists_and_is_executable`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Scripts`

Expected: FAIL — `missing .../scripts/task-brief`.

- [ ] **Step 3: Write the two scripts**

Create `plugins/superb/skills/pipeline-auto/scripts/task-brief`:

```bash
#!/usr/bin/env bash
# Extract one task's full text from a phase plan into a file the implementer
# reads in one call, so the task text never passes through the controller's
# context.
#
# Provenance: inlined from superpowers:subagent-driven-development
# (scripts/task-brief). Inlined rather than invoked because that skill's
# plugin-cache copy is a mirror a plugin update silently overwrites, and
# because pipeline-auto modifies the surrounding protocol. Changed here:
# the default output directory is the run's scratch/, not .superpowers/sdd.
#
# Usage: task-brief PLAN_FILE TASK_NUMBER [OUTFILE]
# Default OUTFILE: <run-scratch>/task-<N>-brief.md
set -euo pipefail

if [ $# -lt 2 ] || [ $# -gt 3 ]; then
  echo "usage: task-brief PLAN_FILE TASK_NUMBER [OUTFILE]" >&2
  exit 2
fi

plan=$1
n=$2
[ -f "$plan" ] || { echo "no such plan file: $plan" >&2; exit 2; }

if [ $# -eq 3 ]; then
  out=$3
else
  dir=$("$(cd "$(dirname "$0")" && pwd)/sdd-workspace")
  out="$dir/task-${n}-brief.md"
fi

awk -v n="$n" '
  /^```/ { infence = !infence }
  !infence && /^#+[ \t]+Task[ \t]+[0-9]+/ {
    intask = ($0 ~ ("^#+[ \t]+Task[ \t]+" n "([^0-9]|$)"))
  }
  intask { print }
' "$plan" > "$out"

if [ ! -s "$out" ]; then
  echo "task ${n} not found in ${plan} (no heading matching 'Task ${n}')" >&2
  exit 3
fi

echo "wrote ${out}: $(wc -l < "$out" | tr -d ' ') lines"
```

Create `plugins/superb/skills/pipeline-auto/scripts/review-package`:

```bash
#!/usr/bin/env bash
# Generate a review package — commit list, stat summary, and the net diff with
# extended context — written to one file the reviewer reads in a single call.
# Using the persisted reservation baseline (never HEAD~1) keeps multi-commit
# tasks intact; HEAD~1 silently drops all but the last commit.
#
# Provenance: inlined from superpowers:subagent-driven-development
# (scripts/review-package). Inlined rather than invoked for the reasons in
# task-brief. Changed here: the default output directory is the run's
# scratch/, not .superpowers/sdd.
#
# Usage: review-package BASE HEAD [OUTFILE]
# Default OUTFILE: <run-scratch>/review-<base7>..<head7>.diff
# (named per range, so a re-review after fixes gets a distinct fresh file).
set -euo pipefail

if [ $# -lt 2 ] || [ $# -gt 3 ]; then
  echo "usage: review-package BASE HEAD [OUTFILE]" >&2
  exit 2
fi

base=$1
head=$2

git rev-parse --verify --quiet "$base" >/dev/null || { echo "bad BASE: $base" >&2; exit 2; }
git rev-parse --verify --quiet "$head" >/dev/null || { echo "bad HEAD: $head" >&2; exit 2; }

if [ $# -eq 3 ]; then
  out=$3
else
  dir=$("$(cd "$(dirname "$0")" && pwd)/sdd-workspace")
  out="$dir/review-$(git rev-parse --short "$base")..$(git rev-parse --short "$head").diff"
fi

{
  echo "# Review package: ${base}..${head}"
  echo
  echo "## Commits"
  git log --oneline "${base}..${head}"
  echo
  echo "## Files changed"
  git diff --stat "${base}..${head}"
  echo
  echo "## Diff"
  git diff -U10 "${base}..${head}"
} > "$out"

commits=$(git rev-list --count "${base}..${head}")
echo "wrote ${out}: ${commits} commit(s), $(wc -c < "$out" | tr -d ' ') bytes"
```

Make both executable:

```bash
chmod 755 plugins/superb/skills/pipeline-auto/scripts/task-brief \
          plugins/superb/skills/pipeline-auto/scripts/review-package
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Scripts`

Expected: PASS — both `Scripts` tests.

Then prove the extractor actually extracts, against this plan itself:

Run: `plugins/superb/skills/pipeline-auto/scripts/task-brief docs/superpowers/plans/pipeline-auto/phase-07-skill-prose.md 3 /tmp/brief-check.md && head -1 /tmp/brief-check.md && rm /tmp/brief-check.md`

Expected: prints a line count, then `### Task 3: The two inlined SDD scripts`.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/task-brief \
        plugins/superb/skills/pipeline-auto/scripts/review-package
git commit -m "feat(pipeline-auto): inline SDD task-brief and review-package scripts"
```

---

### Task 4: `prompts/brain.md` — the quorum dispatch template

> **ACCEPTANCE CRITERION, from the P03 Task 3 review.** Every `root` this
> template interpolates — each `READING_ASSIGNMENT.read` line and
> `DECISIONS_EFFECTIVE` — must be **repo-root-relative**. `effective_rung`
> resolves a citation against the recorded `## Run` repo root and refuses one
> that escapes it. Hand a brain the bare filename `decisions-effective.md` and
> its citation resolves to `<repo_root>/decisions-effective.md`, which does not
> exist — while the file actually sits at
> `docs/superpowers/runs/<run-id>/decisions-effective.md`.
>
> The failure is **silent**: a citation that does not resolve DEMOTES, it does
> not raise. Every decision and spec citation in the run falls to
> `engineering-judgement` (0.55), every cluster lands below the 0.85 floor, and
> the run escalates every question it is ever asked while looking like a
> correctly cautious quorum. Worse, `specified` requires one of
> `{spec, intent-brief, decision}`, so the decision route to the top rung is
> *dead* until this holds. Check it by reading a rendered prompt, not the
> template.



**Files:**
- Create: `plugins/superb/skills/pipeline-auto/prompts/brain.md`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: `build_payload(qid, brain_index, *, run_dir)` from P03, which emits exactly `qid`, `question`, `axis`, `options`, `reading_assignment`, `decisions_effective`, `rungs`, `response_schema`, `you_are_one_of_several`.
- Produces: the dispatch template `references/quorum.md` (Task 7) uses for all three brains.

**The template may reference no placeholder the payload does not carry.** `build_payload` is a whitelist constructor: the raiser's identity, their candidate answers, their recommendation, the adoption floor, the drift budget, every rung *value*, and every elapsed-time or cost signal are not filtered out of the payload — they are unreachable from it. A prompt template with a `[BUDGET_REMAINING]` slot would reintroduce, through prose, exactly what the constructor was built to make impossible.

Note what the payload does and does not say about the other readers. It carries `you_are_one_of_several: true` and no count. "Several" is deliberate and "three" is forbidden: a reader who knows the exact panel size can reason about what it takes to win a plurality. A reader who knows only that others exist cannot.

- [ ] **Step 1: Write the failing test**

Already written in Task 1: `Prompts::test_every_required_prompt_exists`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Prompts`

Expected: FAIL — `prompts/brain.md` missing.

- [ ] **Step 3: Write the template**

Create `plugins/superb/skills/pipeline-auto/prompts/brain.md`:

````markdown
# Quorum Brain Dispatch Template

Use this template once per brain index when `superb:pipeline-auto` opens a
quorum. Dispatch exactly three, one per index, each rendered from
`build_payload(qid, brain_index, run_dir=<run>)` and from nothing else.

**Every placeholder below is a key of that payload.** If you find yourself
wanting a placeholder the payload does not carry, the answer is no: the payload
is a whitelist, and what it omits it omits on purpose. In particular there is no
slot for the adoption floor, the drift budget, the rung values, the elapsed
time, the cost so far, who raised the question, what they thought the answer
was, or what any other brain said.

```
Subagent (pipeline-auto-brain):
  description: "Quorum [QID] brain [BRAIN_INDEX] ([READING_ASSIGNMENT.label])"
  model: [MODEL — REQUIRED: the most capable model available. Never downgraded
         for a question that looks easy; a question that looked easy is how a
         quorum was needed in the first place.]
  prompt: |
    Answer one question in writing, from evidence you can cite.

    ## The question

    [QUESTION]

    Axis: [AXIS]
    Question id: [QID]

    [If OPTIONS is non-empty:]
    These are the named options. Your `answer_key` must be exactly one of them:
    [OPTIONS — one `key` per line, values only, no annotations]

    [If OPTIONS is empty:]
    No options were named. Answer in prose, leave `answer_key` empty, and make
    your `consequences` precise — they are how your answer will be compared
    with the others'.

    ## Your reading assignment

    You are [READING_ASSIGNMENT.label]. Start here and look hardest here:

    [READING_ASSIGNMENT.read — one line per source: "<source>: <root>"]

    Other readers are starting from different material. That is deliberate: it
    biases each of you toward a *source*, never toward an answer. You may read
    outside your assignment when a specific question demands it — say so in your
    evidence — but an answer that never touched your assignment is a weak one.

    Every path you cite in `evidence` must be written **relative to the
    repository root**, and must stay inside it. That is the one root your
    citations are resolved against.


    ## Decisions already made

    Read [DECISIONS_EFFECTIVE]. Every entry there is settled: the question, the
    adopted answer, and whether a human or a quorum decided it.

    Treat all of them as binding. Do not re-litigate a decision that is already
    recorded, and do not propose an answer that contradicts one whose provenance
    is `human` — set `blocker` and say which one instead. You are not told what
    any decision was worth, because what it was worth is not your business: it
    is a decision.

    ## Select a rung; never write a number

    [RUNGS — the rung names, in order, one per line]

    Select the rung that honestly describes your grounding and cite what it
    requires. You are not told what any rung is worth or which ones are good
    enough. Do not try to work it out. An answer tuned to clear a bar is an
    answer about the bar.

    Every citation is resolved and checked against what is actually at that
    line. A citation that does not resolve, or resolves to a line that does not
    contain your claim, does not get you rejected — it reprices your answer
    downward. Overclaiming a rung lowers your answer's weight; it cannot raise
    it.

    ## Your response

    [RESPONSE_SCHEMA]

    You are one of several readers. You will not see their answers and they will
    not see yours. There is nothing to win by agreeing and nothing to lose by
    being alone: an answer that cites the spec while everyone else speculates is
    the best possible outcome of this mechanism, not a risk to you.

    If the question cannot be decided from the repository, the spec, or the
    decisions record — or needs something only the user knows, or is several
    decisions wearing one coat — set `blocker` and stop. A blocker costs
    nothing, is never held against you, and sends the question to a person,
    which is where a question like that belongs.

    Return the JSON object and nothing else.
```

**Placeholders — all nine, and only these:**

| Placeholder | Payload key |
| --- | --- |
| `[QID]` | `qid` |
| `[QUESTION]` | `question` — **verbatim and identical for all three brains** |
| `[AXIS]` | `axis` |
| `[OPTIONS]` | `options` — `key` values only |
| `[READING_ASSIGNMENT.label]`, `[READING_ASSIGNMENT.read]` | `reading_assignment` |
| `[DECISIONS_EFFECTIVE]` | `decisions_effective` |
| `[RUNGS]` | `rungs` — **names only; the payload carries no values** |
| `[RESPONSE_SCHEMA]` | `response_schema` |
| `[MODEL]` | not from the payload; the controller's most-capable-model policy |

`you_are_one_of_several` is rendered by the fixed sentence "You are one of
several readers." **Never render it as a count.**

## Re-dispatch

A brain is re-dispatched **once**, with the **byte-identical payload for that
brain index**, when its response is schema-invalid or its `alternatives` list is
empty. "Identical payload" always means identical to that brain index's own
payload, never identical across brains — the three payloads differ by
construction. A second malformed response is a non-response: the quorum is
incomplete, and an incomplete quorum escalates. A brain must never be able to
force an adoption by malforming, only to force a human to look.

**Never re-dispatch a brain to ask it to reconsider.** Not its rung, not its
answer, not its confidence. A request to think again is a pressure signal: it
moves the number without moving the evidence. If you want a different answer,
you want an escalation.
````

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k test_every_required_prompt_exists`

Expected: still FAIL on the other three prompts; the `brain` subtest passes. Confirm with `-v` that `[prompt=brain]` is the one that no longer errors.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/prompts/brain.md
git commit -m "feat(pipeline-auto): quorum brain dispatch template"
```

---

### Task 5: `prompts/implementer.md` and the implementer's two artifacts

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/prompts/implementer.md`
- Create: `plugins/superb/skills/pipeline-auto/templates/task-brief.md`
- Create: `plugins/superb/skills/pipeline-auto/templates/worker-report.md`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: `scripts/task-brief` (Task 3) writes the brief file; `scripts/sdd-workspace` (P02) resolves the run's `scratch/`; the five terminal statuses and the four-part result identity `run_id + task_id + attempt + owner` from P04.
- Produces: `prompts/implementer.md`, referenced by `references/execution.md` (Task 9). `templates/task-brief.md` and `templates/worker-report.md` document the shape of the two files that flow through the dispatch, so neither has to be pasted through the controller's context.

Three deliberate changes from the SDD original, each required by this skill's contract:

1. **The escalation vocabulary is this skill's five statuses**, not SDD's four. `DONE_WITH_CONCERNS` exists here and carries different weight, and `NEEDS_CONTEXT` / `PLAN_CONFLICT` are what open a quorum rather than what interrupt a human.
2. **"Ask them now" is removed.** There is no human to ask mid-run. An implementer that would have asked publishes a question record instead, and the controller decides whether that is a quorum or an escalation. This is the single biggest divergence from the original and it must be unambiguous in the template, because an implementer that waits for an answer nobody is coming to give holds a worker slot forever.
3. **A worker never dispatches brains** and never opens its own quorum. It publishes a result with status `NEEDS_CONTEXT` or `PLAN_CONFLICT` and a question record. `BLOCKED` still means halt: three brains cannot conjure an API key.

- [ ] **Step 1: Write the failing test**

Already written in Task 1: `Prompts` and `Templates`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Prompts -k Templates`

Expected: FAIL on `[prompt=implementer]`, `[template=task-brief]`, `[template=worker-report]`.

- [ ] **Step 3: Write the three files**

Create `plugins/superb/skills/pipeline-auto/prompts/implementer.md`:

````markdown
# Implementer Dispatch Template

One fresh implementer per task. The task text reaches it as a **brief file**
written by `scripts/task-brief`, never as plan text pasted through the
controller's context.

Provenance: adapted from `superpowers:subagent-driven-development`
(`implementer-prompt.md`), inlined rather than invoked. Changed here: the five
terminal statuses, the removal of the ask-a-human step, and the question-record
route.

```
Subagent (general-purpose):
  description: "Implement [TASK_ID]: [TASK_NAME]"
  model: [MODEL — REQUIRED: the most capable model available. A task's
         "simplicity" is a hypothesis confirmed by review after the work, never
         assumed before it. There is no cheap tier here and the dial cannot
         switch this off.]
  prompt: |
    You are implementing [TASK_ID]: [TASK_NAME].

    ## Your task

    Read your brief first: [BRIEF_FILE]
    It carries the full task text from the phase plan — objective, acceptance
    criteria, dependencies, write scope, outputs, and test commands.

    ## Global constraints

    These bind this task and are copied verbatim from the plan and spec:
    [GLOBAL_CONSTRAINTS]

    ## Decisions that govern this task

    [GOVERNING_DECISIONS — each as `<D-ID> — <question> — <adopted answer> —
    Provenance: human|quorum`. If any is `Provenance: quorum` and was adopted
    at `code-evidenced` rather than `specified`, its ID and adopted answer are
    copied here verbatim and the task is marked provisional.]

    A decision listed here is binding. If your implementation cannot satisfy
    one, that is a `PLAN_CONFLICT`, not something to work around.

    ## Your write scope

    [WRITE_SCOPE — the typed scopes from the task metadata]

    Every file you change must be inside it. Changing a file outside your scope
    fails completion even if the change is correct: another worker may own it
    and the conflict is not detectable after the fact.

    ## How to work

    Work from: [WORKTREE]

    1. Work test-first for every logic-bearing change: write the failing test,
       run it, watch it fail for the right reason, implement to green, refactor.
       This is the default here, not something the brief must request. The only
       exemption is pure config or glue with no logic to assert on; if you claim
       it, justify it in your report.
    2. Implement exactly what the brief specifies. Nothing more.
    3. Run the task's ordered test suite: [TASK_SUITE]
    4. Commit your work on [BRANCH].
    5. Self-review (below), then publish your result.

    While iterating, run the focused test for what you are changing. Run the
    full suite once before committing, not after every edit.

    ## There is nobody to ask

    This run has one human gate and it is behind you. **Do not stop and wait for
    an answer.** Waiting holds a worker slot that nothing will ever free.

    If you hit something the brief, the constraints and the decisions do not
    settle, publish your result with status `NEEDS_CONTEXT` or `PLAN_CONFLICT`
    and a **question record** alongside it:

      - `question`  — one decision, stated so that blanking the title and
                      keeping the options still shows what is being decided
      - `axis`      — the stage-03 question id it belongs to, or the literal
                      `new`
      - `blocks`    — the task ids, gate ids or artifacts that cannot proceed.
                      **A question that blocks nothing is an opinion and is
                      discarded.**
      - `options`   — the named alternatives, if the question has any. Named
                      alternatives only: `PostgreSQL`, `SQLite` is a question;
                      `scalable`, `simple` is an adjective pretending to be one.

    Then stop. **You never dispatch anyone** — not a helper, not a reviewer, and
    certainly not a brain. The controller decides whether your question goes to
    a quorum or to a person.

    Do not pre-empt that by guessing. Configurability, reversibility,
    convention, a familiar pattern in this codebase, and writing down your
    assumption are **not** authorization to choose an unanswered option. If the
    sources do not select the behaviour, the question record is the deliverable.

    ## When you are in over your head

    It is always OK to stop and say this is too hard. Bad work is worse than no
    work, and you are not penalised for stopping. Stop when the task needs an
    architectural decision with several valid answers, when you have been
    reading file after file without progress, or when you are not confident the
    approach is right.

    ## Before you publish: self-review

    - **Completeness.** Did I implement everything in the brief? Any acceptance
      criterion I skipped? Any edge case in the brief I did not cover?
    - **Scope.** Did I change anything outside my write scope? Did I build
      anything nobody asked for?
    - **Quality.** Are the names accurate? Is there a materially simpler design
      that still meets the brief? If yes, simplify now.
    - **Tests.** Do they verify behaviour rather than mocks? Can my report prove
      a genuine RED before GREEN, with real failing output?
    - **Constraints.** Does every global constraint still hold? Did I write an
      absolute home-directory path anywhere?

    Fix what you find before publishing.

    ## Publish your result

    Write the long-form report to [REPORT_FILE] using the shape in
    `templates/worker-report.md`.

    Then publish your immutable result with `publish_worker_result`, copying
    your assignment exactly: run_id [RUN_ID], task_id [TASK_ID], attempt
    [ATTEMPT], owner [OWNER]. All four are validated together; do not
    reconstruct one you do not have.

    **You never edit progress.md.** `publish_worker_result` for your own
    assigned result is the only state call you make.

    Your final message is under 15 lines — the detail is in the report file:

    - **Status:** DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | PLAN_CONFLICT | BLOCKED
    - Commits created (short SHA + subject)
    - One-line test summary
    - Your concerns, if any
    - The report file path
    - If NEEDS_CONTEXT or PLAN_CONFLICT: the question record path

    `DONE_WITH_CONCERNS` means you finished but doubt the correctness.
    `NEEDS_CONTEXT` means an unanswered requirement blocks you.
    `PLAN_CONFLICT` means the plan contradicts itself, the spec, or a recorded
    decision. `BLOCKED` means nothing in this run can unblock you — a missing
    credential, an unreachable service, a permission you do not have. `BLOCKED`
    halts; the other two open a question. Choose honestly: routing a `BLOCKED`
    as a question sends three readers to think about an API key.

    Never silently produce work you are unsure about.
```

**Placeholders:** `[MODEL]`, `[TASK_ID]`, `[TASK_NAME]`, `[BRIEF_FILE]` (from
`scripts/task-brief`), `[GLOBAL_CONSTRAINTS]`, `[GOVERNING_DECISIONS]`,
`[WRITE_SCOPE]`, `[WORKTREE]`, `[BRANCH]`, `[TASK_SUITE]`, `[REPORT_FILE]`,
`[RUN_ID]`, `[ATTEMPT]`, `[OWNER]`. All are REQUIRED; none may be left implicit.
````

Create `plugins/superb/skills/pipeline-auto/templates/task-brief.md`:

```markdown
# Task brief

Written by `scripts/task-brief <phase-plan> <task-number>` into the run's
`scratch/`. It is the implementer's single read of the task, so the plan text
never passes through the controller's context.

The script extracts the task's own section verbatim, which means **the phase
plan is the template**: a brief is only as complete as the task heading it was
cut from. A task section that omits its write scope produces a brief that omits
it, and the implementer will not know.

A usable brief contains, from the phase plan's task section:

| Part | Where it comes from |
| --- | --- |
| Heading `### Task N: <name>` | the task heading — the script's anchor; without it the extract is empty and the script exits 3 |
| `<!-- pipeline-auto-task: ... -->` | the strict task metadata comment: `id`, `deps`, `kind`, `batch`, `order`, `write_scope`, `outputs` |
| `<!-- pipeline-auto-task-suite: ... -->` | the ordered command array, for `source` tasks |
| **Files** | Create / Modify / Test paths, exact |
| **Interfaces** | Consumes and Produces, with exact signatures |
| Steps | the RED / verify-fail / GREEN / verify-pass / commit sequence, with real code |

## Checks before dispatch

- The extract is non-empty and starts with the expected task heading.
- It carries both metadata comments a `source` task requires.
- It names a write scope, and that scope is disjoint from every other
  concurrently reserved task's.
- It contains no absolute home-directory path.

A brief failing any of these is a **planning** defect. Repair the phase plan and
re-extract. Never hand-edit a brief: the plan is the authority, and a brief
edited away from it is a second, invisible copy of the task definition.
```

Create `plugins/superb/skills/pipeline-auto/templates/worker-report.md`:

```markdown
# Worker report

The implementer's long-form report, written to the run's `scratch/` at the path
the controller supplied. It is **evidence, not acceptance**: the task reviewer
treats every line of it as an unverified claim and re-runs the tests itself.

It lives in `scratch/` because it is large and ephemeral. The durable record is
the immutable worker result published by `publish_worker_result`; this file is
what the reviewer reads so that neither the diff nor the narrative has to pass
through the controller's context.

```markdown
# Report — <run-id> / <task-id> / attempt <n> / <owner>

## Status

DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | PLAN_CONFLICT | BLOCKED

## What I implemented

<What was built, or what was attempted before stopping.>

## TDD evidence — REQUIRED for every logic-bearing change

### RED
- Command: <exact command>
- Failing output: <the relevant lines, before the implementation existed>
- Why this failure was the expected one: <...>

### GREEN
- Command: <exact command>
- Passing output: <the relevant lines>

If you claim the config/glue exemption, say here what had no logic to assert on.

## Tests and suites run

| Command | Outcome | Notes |
| --- | --- | --- |

## Files changed

<repository-relative paths, each inside the declared write scope>

## Commits

<short SHA + subject, in order>

## Decisions this task relied on

<D-ID — how the implementation satisfies it. A provisional task names the
tainting decision explicitly.>

## Self-review findings

<What I found reviewing my own work, and what I changed.>

## Concerns

<Anything that makes DONE_WITH_CONCERNS the honest status.>

## Question record

<Path, for NEEDS_CONTEXT or PLAN_CONFLICT. Otherwise: none.>
```

## Rules

- **Never edit a report after a reviewer has read it.** Append a re-run section
  instead. A report that changes under a reviewer is indistinguishable from a
  report that was wrong.
- A report claim that disagrees with the reviewer's own re-run is a **Critical**
  finding — not because the number is wrong but because the report has stopped
  being evidence.
- A report is never the completion record. `[x]` comes from the imported
  immutable result, the in-scope commit range, and digest-bound PASS evidence.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Templates`

Expected: PASS — `task-brief` and `worker-report` subtests now pass. `completeness-proposals` still fails; it lands in Task 10.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/prompts/implementer.md \
        plugins/superb/skills/pipeline-auto/templates/task-brief.md \
        plugins/superb/skills/pipeline-auto/templates/worker-report.md
git commit -m "feat(pipeline-auto): implementer prompt and its two artifact templates"
```

---

### Task 6: `prompts/task-reviewer.md` and `prompts/adversarial-reviewer.md`

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/prompts/task-reviewer.md`
- Create: `plugins/superb/skills/pipeline-auto/prompts/adversarial-reviewer.md`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: `scripts/review-package` (Task 3); `adversarial_required(diff_paths, changed_lines) -> str | None` from P05, returning the trigger name.
- Produces: the two review dispatch templates `references/execution.md` (Task 9) uses. The task reviewer returns **three** verdicts — spec, quality, and verification evidence from an independent re-run — which is what `record_task_review` in P05 persists.

Two changes from the SDD originals matter and must be explicit in the prose:

1. **The styling-preference exception.** Under zero-open-findings, every Minor must be fixed. If a quality-rubric Minor requires reversing a quorum decision, an automatic reviewer win lets a naming opinion silently overturn architecture. So the reviewer's finding prevails **only** when it is Critical or Important *and* its verdict part is spec-compliance or verification-evidence. Any other finding that would require reversal goes to reconciliation. The reviewer needs to know this, because a reviewer who does not know it writes Minors as if they were free.
2. **`DECISION-CHALLENGE` is a labelled verdict, not a finding.** A reviewer that believes a recorded decision is itself wrong says so under that label. It routes differently — a human decision halts, a quorum decision re-opens once at a raised bar — and a reviewer that buries it as an Important finding gets it silently fixed into the code instead.

- [ ] **Step 1: Write the failing test**

Already written in Task 1: `Prompts::test_every_required_prompt_exists`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Prompts`

Expected: FAIL on `[prompt=task-reviewer]` and `[prompt=adversarial-reviewer]`.

- [ ] **Step 3: Write the two templates**

Create `plugins/superb/skills/pipeline-auto/prompts/task-reviewer.md`:

````markdown
# Task Reviewer Dispatch Template

Dispatched per task when the phase's `review_class` is `required`. Returns
three verdicts: spec compliance, code quality, and verification evidence from an
independent re-run.

Provenance: adapted from `superpowers:subagent-driven-development`
(`task-reviewer-prompt.md`). Changed here: the third verdict is first-class, the
`DECISION-CHALLENGE` label exists, and the styling-preference exception is
stated.

```
Subagent (general-purpose):
  description: "Review [TASK_ID] (spec + quality + verification)"
  model: [MODEL — REQUIRED: the most capable model available. Review capability
         is never scaled to diff size, and the dial never scales it either: the
         dial controls whether a reviewer runs, never what bar it applies.]
  prompt: |
    You are reviewing one task: whether it matches its requirements, whether it
    is well-built, and whether its test claims survive your own re-run. This is
    a task-scoped gate. A whole-branch review happens separately at the end.

    ## What was requested

    Read the task brief: [BRIEF_FILE]

    Global constraints that bind this task, verbatim from the plan and spec:
    [GLOBAL_CONSTRAINTS]

    Decisions that govern this task:
    [GOVERNING_DECISIONS — `<D-ID> — <question> — <adopted answer> —
    Provenance: human|quorum`. Any decision adopted at `code-evidenced` rather
    than `specified` is reproduced here in full and you must name it in your
    report.]

    ## What the implementer claims

    Read the report: [REPORT_FILE]

    ## The diff

    Base: [BASE_SHA]  Head: [HEAD_SHA]
    Review package: [DIFF_FILE]

    [BASE_SHA] is the **persisted reservation baseline**, not `HEAD~1`. Read the
    package first: it carries the commit list, the stat summary, and the full
    diff with context.

    Read beyond the diff when you need to judge correctness — call sites when a
    signature changed, lock ordering when concurrency is touched, test helpers
    when you must judge what a test really asserts. Every excursion should trace
    to a concrete question about this change; name what you checked and why. Do
    not go looking for pre-existing problems unrelated to this diff.

    Do not change the code under review: no edits, no commits, no branch
    changes. Running tests is required; if a run dirties generated files, say so.

    ## Do not trust the report

    Treat it as unverified claims. Design rationales are claims too: "left it
    per YAGNI" or "kept it simple deliberately" is the implementer grading their
    own work. A stated rationale never lowers a finding's severity.

    ## Verdict 3 first: independent verification (REQUIRED)

    Re-run the claims yourself. At minimum: [TEST_COMMANDS]

    Compare your results with the report. **Any discrepancy — different pass
    counts, failures, warnings the report called pristine — is Critical**,
    because it means the report has stopped being evidence.

    Beyond the minimum, run what the diff's risk warrants and nothing
    performative. If you cannot run commands here, say so explicitly, name the
    exact commands you would run, and mark every unverifiable claim ⚠️.

    ## Verdict 1: spec compliance

    Against the brief and the governing decisions:

    - **Missing** — requirements skipped, or claimed without being implemented
    - **Extra** — anything not requested; over-engineering
    - **Misunderstood** — the right feature built the wrong way
    - **Out of scope** — any changed path outside [WRITE_SCOPE]. This is
      Important at minimum even when the change is correct.

    A requirement you cannot verify from this diff alone is a ⚠️ item, reported
    beside the verdict for everything you could verify.

    ## Verdict 2: code quality

    Separation of concerns; error handling; DRY without premature abstraction;
    edge cases. Tests that verify behaviour rather than mocks. TDD evidence that
    shows a genuine RED before GREEN and not a retro-fitted narrative. Files with
    one clear responsibility, following the plan's structure.

    Cite `file:line` for every finding, and for any check you would otherwise
    answer with a bare "yes".

    ## Calibration, and the one exception to fixing everything

    Every finding you report will be fixed before this task completes. Severity
    communicates urgency and risk, not whether a finding is worth reporting.
    Report Minors honestly: neither inflate them to force attention nor suppress
    them as not worth the loop.

    **The exception.** A Critical or Important finding on spec compliance or
    verification evidence prevails outright. Any other finding — a Minor, or any
    quality-part finding — that would require **reversing a recorded decision**
    does not automatically win. Say so explicitly, name the D-ID, and it goes to
    an unbiased reconciliation instead of into the fix loop. Without that rule a
    naming preference silently overturns architecture.

    If the plan or brief explicitly mandates something this rubric calls a
    defect — a test that asserts nothing, verbatim duplication of a logic block
    — that IS a finding. Report it as Important, labelled **plan-mandated**, and
    name the decision or plan line that mandates it. The plan does not grade its
    own work.

    ## DECISION-CHALLENGE

    If you believe a **recorded decision itself** is wrong — not that the code
    fails to comply with it, but that the decision is the defect — do not file
    it as an ordinary finding. Report it under this exact label:

        DECISION-CHALLENGE: <D-ID>
        Evidence: <file:line, or a command and its output>
        Why the decision is wrong: <...>

    It routes differently and it must not be silently fixed into the code.
    A challenge without `file:line` evidence or a command and its output is
    inadmissible and the decision stands.

    ## Output

    Your final message is the report. Begin with the spec verdict — no preamble,
    no process narration.

    ### Spec compliance
    ✅ compliant | ❌ issues found (with file:line) | ⚠️ cannot verify from diff

    ### Verification evidence (REQUIRED)
    Each command run and its outcome; match or mismatch against the report; if
    you could not run commands, the exact commands and which claims are
    therefore unverified.

    ### Strengths
    Specific. Accurate praise makes the rest of the feedback land.

    ### Issues
    #### Critical (must fix)
    #### Important (must fix)
    #### Minor (must still fix before this task completes)
    For each: file:line, what is wrong, why it matters, how to fix if not obvious.
    Mark any finding that would require reversing a decision, with its D-ID.

    ### DECISION-CHALLENGE
    None, or the labelled block above.

    ### Assessment
    **Task quality:** Approved | Needs fixes
    (Approved requires zero open findings at every severity AND verification
    evidence that matches the report.)
    **Reasoning:** one or two sentences.
```

**Placeholders:** `[MODEL]`, `[TASK_ID]`, `[BRIEF_FILE]`, `[GLOBAL_CONSTRAINTS]`,
`[GOVERNING_DECISIONS]`, `[REPORT_FILE]`, `[BASE_SHA]` (the persisted
reservation baseline), `[HEAD_SHA]`, `[DIFF_FILE]` (from `scripts/review-package`),
`[TEST_COMMANDS]`, `[WRITE_SCOPE]`. All REQUIRED — never leave the reviewer to
guess a test command.

**The reviewer is never the implementer.** `record_task_review` rejects a
reviewer id matching a persisted implementation owner for the task.
````

Create `plugins/superb/skills/pipeline-auto/prompts/adversarial-reviewer.md`:

````markdown
# Adversarial Reviewer Dispatch Template

Dispatched when `adversarial_required()` returns a trigger name — **at every
`review_class`**. The dial may never switch this check off. It runs after the
task reviewer approves, and it is not a second quality pass: its job is to
refute the claim that the change is correct and safe.

Provenance: adapted from `superpowers:subagent-driven-development`
(`adversarial-reviewer-prompt.md`).

## Triggers are independent — any single one fires

`concurrency` · `authz` · `crypto` · `schema` · `migration` · `delete` ·
`regulated` · `public-api` · `large-surface` (> 300 changed source lines)

The line-count trigger is its **own** trigger, not a minimum the others must
also meet. **A 10-line auth change is high-risk.** Collapsing this into "300
lines AND a risky path" is the obvious and wrong reading, and it is how this
pass gets quietly disabled.

```
Subagent (general-purpose):
  description: "Adversarial review [TASK_ID] ([RISK_TRIGGER])"
  model: [MODEL — REQUIRED: the most capable model available]
  prompt: |
    A change has passed implementation, self-review, and a task review. You are
    the adversarial pass. Your job is to REFUTE the claim that this change is
    correct and safe. Assume the previous reviewers were competent and still
    missed something — your value is finding what survives competent review.

    ## Why you were dispatched

    This diff matched: [RISK_TRIGGER — stated concretely for THIS diff, not the
    generic category name alone. "modifies session token validation in
    auth/session.py", not "authz".]

    ## Inputs

    - Task brief: [BRIEF_FILE]
    - Implementer's report: [REPORT_FILE]
    - Review package: [DIFF_FILE]
    - Base: [BASE_SHA]  Head: [HEAD_SHA]
    - Decisions governing this task: [GOVERNING_DECISIONS]

    Read the diff first, then read whatever you need to prosecute the risk: call
    sites, callers' assumptions, concurrent paths, error paths, old behaviour the
    rest of the system may still rely on. You are expected to range beyond the
    diff — the risk lives at the boundaries.

    ## Method

    1. Enumerate concrete failure scenarios for the named risk: specific inputs,
       interleavings, states, or sequences that would make this change misbehave.
       Think in attacks, not checklists. What would a malicious user, an unlucky
       race, a half-failed operation, a retry, a stale cache, or an old client do
       to this code?
    2. Prosecute each scenario against the actual code, line by line, until it is
       CONFIRMED (you can point at the path that misbehaves) or REFUTED (you can
       point at the guard that stops it).
    3. Where a focused experiment settles a scenario faster than reasoning, run
       one. Put throwaway repro scripts in a temp directory. Never modify tracked
       files, never commit.
    4. A scenario you can neither confirm nor refute is PLAUSIBLE. Report it with
       what evidence would settle it. Do not silently drop scenarios you ran out
       of conviction on — unresolved is a result.

    ## Output

    Your final message is the report — no preamble.

    ### Risk trigger
    [restate what you were sent to attack]

    ### Attack surface examined
    One line each: the paths, call sites and interleavings you prosecuted.

    ### CONFIRMED
    For each: file:line, the scenario (inputs/state → wrong behaviour), and the
    exact path or experiment that demonstrates it.

    ### PLAUSIBLE (unrefuted)
    For each: the scenario, why it survived refutation, what evidence would
    settle it.

    ### REFUTED
    One line each: scenario → the guard that stops it (file:line).

    ### Verdict
    **SAFE TO PROCEED** (every scenario refuted) |
    **FINDINGS MUST BE FIXED** (any CONFIRMED or PLAUSIBLE remain)
```

**Placeholders:** `[MODEL]`, `[TASK_ID]`, `[RISK_TRIGGER]` (concrete, not the
category name), `[BRIEF_FILE]`, `[REPORT_FILE]`, `[DIFF_FILE]`, `[BASE_SHA]`,
`[HEAD_SHA]`, `[GOVERNING_DECISIONS]`.

## What the controller does with the verdict

CONFIRMED findings are Critical. Unrefuted PLAUSIBLE findings are Important.
Both go to a fixer and then to re-review. The task completes only when a round
ends in SAFE TO PROCEED.

A CONFIRMED or unrefuted PLAUSIBLE finding is also ratchet trigger (a): the
phase moves `final-only → required` for every remaining task. The ratchet is
one-way and never reverses.

A disputed PLAUSIBLE goes to **one adjudicator**, never to a quorum first — see
`references/review.md`. "Can line 41 be null" is a fact, settled by reading code
and running an experiment. Three models agreeing it cannot is far weaker
evidence than one model running the test.
````

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k test_every_required_prompt_exists`

Expected: PASS — all four prompt subtests. `test_every_prompt_is_referenced_by_some_prose_file` still fails until Task 12.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/prompts/task-reviewer.md \
        plugins/superb/skills/pipeline-auto/prompts/adversarial-reviewer.md
git commit -m "feat(pipeline-auto): task-reviewer and adversarial-reviewer prompts"
```

---

### Task 7: `references/quorum.md`

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/references/quorum.md`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: every constant and function from P03 listed under Interface contracts; `prompts/brain.md` (Task 4); the `pipeline-auto-brain` agent (Task 2).
- Produces: the reference `SKILL.md` routes to for any quorum work. It is the longest of the five and the only one a maintainer will be tempted to shorten.

This is the reference that carries the reversal's whole answer. Write it against the assumption that its reader wants to simplify it.

- [ ] **Step 1: Write the failing test**

Already written in Task 1: `RoutingTable::test_every_required_reference_exists`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k RoutingTable`

Expected: FAIL on `[reference=quorum]`.

- [ ] **Step 3: Write the reference**

Create `plugins/superb/skills/pipeline-auto/references/quorum.md`:

````markdown
# The quorum contract

Read this reference whenever a question is raised, a quorum is open, a quorum is
being finalised, the drift budget is being checked or extended, or an escalation
is being queued.

A quorum decides an **open** question. It may never overrule a **recorded** one.
Any candidate answer contradicting a `Provenance: human` decision is rejected and
escalated, at any confidence, with no exception and no override.

## Admissibility — this is what stops the quorum becoming a chat channel

A question is admissible only if **all five** hold:

1. It **blocks** named work — a task id, gate id, or planning artifact. A
   question blocking nothing is an opinion and is discarded.
2. It is decidable from the repository, the spec, and `decisions.md` — not from
   knowledge only the user has: budget, deadline, who the users are, what the
   product is *for*.
3. It carries an **axis**: a stage-03 question id, or the literal `new`.
4. It passes the options test from
   `plugins/superb/agents/architecture-discovery.md:54-73` — blank the title,
   keep the options, and a reader can still tell what is being decided.
   Adjectives are not options.
5. It is one decision, not several wearing one coat.

`check_admissible` enforces 1, 3 and 4 mechanically. **2 and 5 are judgment
calls and they are yours.** They are the two that matter most and the two no
validator will catch for you.

A worker never dispatches brains. It publishes its immutable result with status
`NEEDS_CONTEXT` or `PLAN_CONFLICT` and a question record. `BLOCKED` still means
halt: three brains cannot conjure an API key.

`qid = sha256(normalize(question) || "\x00" || axis)`. The decisions digest is
deliberately **not** part of the qid — including it would give the same question
a new identity every time anything else was decided, and the run would
re-litigate itself forever. It is recorded separately as `context_digest`, for
audit only.

## Independence has to be manufactured

Three instances of one model reading one payload are **not three independent
samples — they are one prior sampled three times.** Shared weights plus a shared
prompt produce correlated error, so agreement is far weaker evidence than it
looks.

All three receive the **identical verbatim question**, which fair comparison
requires. They receive **different reading assignments**:

| Index | Label | Reads |
| --- | --- | --- |
| 0 | `spec-and-intent` | the spec and the intent brief |
| 1 | `code-and-tests` | repository code and tests |
| 2 | `decisions-and-plan` | the decisions record and the phase plan |

This biases each toward a *source*, never toward an answer, which is what
actually decorrelates them. It also makes the rung distribution informative:
three brains that each looked somewhere different and none found grounding is
the mechanical signature of drift.

**Independence is a property of the payload, not of concurrency.** At
`worker_limit < 3` the brains run sequentially with the same assignments. A
count is never reduced to fit capacity.

Brains read `decisions-effective.md`: a generated, read-only projection carrying
each resolved decision's question, adopted answer, and provenance — **and not its
value, and not its rejected alternatives.**

- Adopted answers must be **included**, or brains re-litigate settled ground and
  manufacture drift.
- Values must be **excluded**. A brain reading "adopted at 0.85" treats the
  decision as soft and reverses it; a brain reading it as simply a decision
  treats it as binding.
- Provenance must be **included**, so a brain can recognise a human decision and
  refuse to contradict it.

## What a brain's payload must never contain

`build_payload` is a whitelist constructor. These are not filtered out — they are
unreachable. A filter can be defeated by a new field; a whitelist cannot.

- Any other brain's answer, or the fact that the others exist beyond "you are one
  of several". A brain that knows it is competing on argmax has a dominant
  strategy of claiming a high rung.
- The controller's own leaning or hypothesis.
- **The adoption floor.** The numbers in this document must not appear in a
  brain's payload. A brain that knows the bar clears the bar.
- The identity or distress of the raising worker. Pressure inflates confidence.
- Any deadline, budget, elapsed time, or cost signal.
- The raiser's own candidate options or recommendation. (The question's **named
  options** are not this: they are part of the question, admissibility requires
  them, and `answer_key` comparison is defined against them. The prohibition is
  on the raiser's *preferred* answer.)
- Prior rejected alternatives for this axis — except in a re-open, which carries
  the challenging evidence but never the original score or who chose it.
- Conversation history of any kind.

## Confidence by grounding rung

**A brain never types a number.** It selects a rung; the controller derives the
value and verifies the citation.

| Rung | Value | Must cite | Adoptable |
| --- | --- | --- | --- |
| `specified` | 0.95 | a spec, intent-brief, or human-decision line that resolves | yes |
| `code-evidenced` | 0.85 | repository `file:line` that actually contains the claim | yes |
| `convention-cited` | 0.70 | ≥2 `file:line` exemplars | **no** |
| `engineering-judgement` | 0.55 | none | no |
| `speculation` | 0.30 | none | no |

**These five values are schema constants, not run configuration.** They live in
the state module, not in `## Run`. The reason is not tidiness: putting them in
run configuration would let an autonomous controller lower its own adoption bar.
A controller that can tune its own bar will — not maliciously, but because every
individual lowering looks locally reasonable when the run is otherwise blocked.
It is the same class of self-serving move as reclassifying a phase downward, and
it is structurally unavailable for the same reason.

**The adoption floor is `code-evidenced` (0.85).** Everything below it escalates
by arithmetic rather than by judgment. This is the old law re-encoded rather than
deleted. `pipeline/SKILL.md:65-67` holds that "configurability, reversibility,
convention, a familiar codebase pattern, and documenting an assumption do not
authorize choosing an unanswered option." `convention-cited` therefore sits below
the floor, on purpose. **A machine may decide what the spec or the code entails.
It may not decide by imitation.**

The floor actually applied is **persisted per run**, so a later session knows
what bar governed. Neither the floor nor the values ever appear in a payload.

### Demotion, not rejection

A citation that does not resolve, or resolves to a line not containing the claim,
**demotes the response to `engineering-judgement` (0.55)**.

Demotion rather than rejection is deliberate. Rejection discards information and
hands a malformed brain a veto. Demotion prices the claim at what it turned out
to be worth, and 0.55 is below the floor, so an inflated claim is defeated
arithmetically rather than argued with.

Three further demotions to `engineering-judgement`:

- **Second-best on the same rung as the top answer.** A brain that cannot
  separate its own top two must not drive an adoption.
- **Empty falsifier.** `what_would_change_my_mind` empty means the answer was
  not examined.
- **An answer citing only repository code** — `consistent_with` with no spec line
  and no recorded decision — is capped at `convention-cited` and therefore
  auto-escalates. Every adopted answer traces to something the user actually said.

### Schema-invalid, and the empty alternatives list

A `rung` outside the enum is **schema-invalid**: the response is not clustered,
not defaulted, and not repaired. That brain is re-dispatched once with the
identical payload for its own index under a new attempt. A second malformed
response is a **non-response**: the quorum is incomplete, and an incomplete
quorum escalates. A brain must not be able to force adoption by malforming —
only to force a human look.

**No second-best.** Every response must name a rejected alternative with a real
reason. An empty `alternatives` list is rejected outright, re-dispatched once,
and a second empty counts as a non-response.

## Comparing prose answers

Where the question supplied named options, comparison is string equality on
`answer_key`.

Where it did not, two answers are the same answer **iff their `consequence` sets
are mutually non-contradictory**. A `consequence` is an assertion that would be
verifiably true of the repository if the answer were adopted — a file that would
exist, a signature, a command that would pass — **never a rationale**.

**When in doubt they are different answers.** That pushes toward escalation,
which is the safe direction.

Clustering is performed by the controller, conservatively, **frozen to a file at
first computation, and never recomputed.** A cluster set that can be recomputed
is a cluster set that can be recomputed until it gives the answer you wanted.

Three answers that neither agree nor contradict because they describe different
things is a **malformed question, not a split**: escalate as
`question-not-decidable`. The controller never synthesises a fourth answer —
that would be an unreviewed decision with no confidence attached.

**A cluster's rung is its maximum member rung, never the mean.** Averaging
punishes a correct lone expert and lets two weak agreers manufacture a majority.

## Adoption

Adopt only if **all** hold:

- three valid responses returned, fewer than two carrying a blocker;
- the winning cluster's rung is at or above `code-evidenced`;
- **where more than one cluster exists**, the winning cluster's rung is
  **strictly higher** than the runner-up cluster's;
- no `blast` entry is on the irreversible-axis list;
- the adopted consequences contradict no `Provenance: human` decision on the axis;
- `decision_depth ≤ 2`;
- the drift budget is not exhausted.

Otherwise escalate. **There is no third outcome and no controller override.**

**Two-of-three agreement is not sufficient on its own.** The bar is on rung, not
on headcount. This is the rule most likely to be "simplified" into majority
voting, and majority voting is precisely the failure this design exists to avoid:
two brains sharing a wrong prior are not two pieces of evidence.

**Equal rungs never adopt.** Two clusters both at `code-evidenced` escalate even
though both clear the floor. Two brains reading the same code and reaching
different answers from evidence of the same quality is exactly where a numeric
margin would manufacture a winner out of noise. Rung strictness refuses to.

Unanimity is the one case with no runner-up, so the strictness test is vacuous
and the floor alone governs.

**Rung strictness subsumes the three-way-split rule, which is therefore not
implemented separately.** An earlier draft escalated every 1-1-1 split
unconditionally. That is wrong in one important case: one brain citing the spec
against two speculating *should* win, and the unconditional rule would discard
it. Where a three-way split genuinely signals underdetermination — three answers
resting on evidence of equal quality — rung strictness already escalates. Two
overlapping rules are worse than one correct one; do not re-add the second.

### Tie-breaks, in order

1. Higher rung wins.
2. Then the answer whose consequence set is a **strict subset** of the other's —
   between two answers the run cannot separate, take the one that forecloses less.
3. Then escalate.

Never coin-flip. Never take the first response. Never take the longest answer.
**Never dispatch a fourth brain:** that is a retry-until-you-like-it loop wearing
a quorum's clothes, and one more sample from the same prior is not more evidence.

## Anchoring, negative space, and the irreversible axes

**The irreversible-axis list is closed and enumerated.** No confidence buys past
it:

product scope · destructive data operations and schema migrations · adding an
external service or paid dependency · public API or wire-format contract · the
authn/authz model · anything that costs money to run · licensing · anything
writing outside the repository.

**Anchoring.** Every response must cite at least one stage-03 decision or spec
line in `consistent_with`.

**Negative space.** `forecloses` is required, and the union of the three lists is
checked against the irreversible-axis list before adoption. Asking what an answer
*destroys* surfaces risk that asking what it *achieves* never does.

## Depth, taint, and inheritance

**Depth cap of 2.** Human is depth 0; an answer citing only depth-0 is depth 1;
depth 3 is not quorum-eligible whatever its rung. Three layers of inference from
the last thing a human actually said is where the run stops building the user's
product and starts building its own.

**Provisionality propagates.** Any task whose dependency closure contains a
decision adopted at `code-evidenced` rather than `specified` is `provisional`.
That ratchets its phase to `required`, obliges stage-11 reviewer A to score and
name it, and lists it in the terminal report. The tainting decision's ID and
adopted answer are copied **verbatim into the reviewer's global-constraints
block** — that second half is what makes it more than a label.

**Rungs inherit downward.** A quorum raised *by* a tainted task inherits the
taint, and its adopted rung is capped at the minimum of its own and the tainting
decision's. A `specified` answer resting on a `code-evidenced` premise is not a
`specified` answer. Without this, argmax will happily build a tower on a weak
root, laundering a soft premise into confident descendants.

## The drift budget

**Three adoptions per phase, ten per run.** On exhaustion the run escalates the
next question with the full adopted list attached. **Escalations never count
against it; only adoptions do.**

A run needing fifteen autonomous decisions did not have an adequate stage-03
round, and the repair is a second human gate rather than more quorum.

The budget's *existence* is principled. Its *exact value* is a first estimate and
is not calibrated. Log every event's rung, runner-up rung and outcome, and revisit
after three real runs.

**The budget caps decision authority, not run cost.** Ten adoptions is at most
thirty brain dispatches. The dominant spend is elsewhere: at full review intensity
a task costs an implementer, a reviewer, up to two fix rounds of fixer plus
re-review, and sometimes an adversarial pass — four to seven agents. Forty tasks
is 160–280 agents for implementation alone, entirely unrelated to how many
questions were raised. Two counters, two failure modes:

| Counter | Caps | Failure it prevents |
| --- | --- | --- |
| `adoptions_phase` / `adoptions_run` | accumulated machine authority | building something nobody asked for |
| `agent_dispatch_count` | review spend | a run costing more than it is worth |

A soft threshold on the second escalates *reporting* the overrun; a hard one stops
the run resumably. **Never a silent intensity downgrade — the dial is
upward-only.**

**The budget trips at raise time, before dispatch.** The triggering question is
never sent to brains.

Work in flight then follows the freeze semantics of an open quorum at that blast
radius, with one distinction the obvious implementation gets wrong: running work
**finishes, publishes, and is imported** to `[x]`. Only *integration* is held.
Freezing the import too loses a finished task's evidence and repeats the work on
resume. Completion and integration are already separate facts in this schema;
this is where that separation earns its keep.

**The freeze on raising is run-wide, not radius-wide.** Once the budget is
exhausted no worker anywhere may open a new quorum; a second worker hitting a
question attaches it to the same escalation. Otherwise N workers produce N
escalations and the human is handed a queue instead of a decision.

### Run-level inflation check

After five or more adopted events, if the mean effective value exceeds 0.90, the
adoption floor **rises one rung** for the rest of the run and the adjustment is
recorded. Individual confidence claims are often unfalsifiable; the distribution
is not.

### Budget extension

A human answering the escalation grants an **explicit finite extension, never a
reset.** A budget that refills whenever a human glances at it is a speed bump,
and the reflex answer to "may I continue?" is yes. But permanent exhaustion is
also wrong: it lets one unlucky early question kill a healthy run, which teaches
the controller to avoid raising questions at all — the exact opposite of this
design's intent.

`Decision action: quorum.extend-budget` requires **all** of:

| Field | Value |
| --- | --- |
| `Authorized run` | the exact run id |
| `Source revision` | the tracker revision at grant time |
| `Authorized through` | a **finite** new ceiling, never "unlimited" |
| `Granted against` | the **verbatim adopted list** the human was shown |
| `Provenance` | `human` |

`Granted against` is the anti-reflex mechanism: the human is on record as having
seen the specific decisions they are waving through, so a bare "continue" cannot
become an extension.

**Extensions are capped at two per run.** After the second the budget is terminal
and the run stops resumably. Three grants with no change to the underlying
problem is not a budget problem — it means stage 02 selected the wrong four
questions, and the repair is a new run with better ones, not a third tranche of
machine authority.

`quorum.extend-budget` is **never grantable by quorum.** The action requires
`Provenance: human` and the validator rejects it on any quorum-provenance
decision.

**Do not confuse it with `dispatch.extend-budget`**, which raises the
`agent_dispatch_count` ceiling. They cap different things and must never be
granted by one another: extending review spend is not permission to accumulate
more machine authority, and extending machine authority is not permission to
spend more. Both require `Provenance: human`.

## Escalation

Escalations queue and surface **at stage boundaries only**, batched up to four
per `AskUserQuestion` call, ranked by blast radius. More than four pending means
ask four and halt on the rest. Independent work continues while the queue fills.
`next_action` shows `await-escalation-batch` — never a generic block.

**Escalations are free and adoptions are not.** An escalation costs a question in
a batch a human was going to read anyway; an adoption spends a unit of the run's
finite machine authority and lands permanently in `decisions.md` with the run's
name on it. So escalating is **never** the discouraged path, and a controller
choosing between "adopt at a thin margin" and "escalate" is choosing between
spending something scarce and spending something free. Choose free.

## Replay and idempotency

- **One adopted answer per qid per run.** A re-raise returns the recorded answer
  and dispatches nothing.
- The quorum transition is written through the tracker lock with
  `transition_id = "quorum-" + qid`, inheriting replay-is-inert semantics.
- **Payload identity is per brain, and deterministic.** Because the three brains
  receive different reading assignments there is no single payload digest.
  `build_payload(qid, brain_index)` is a pure function of the question record,
  the projection, and the index, so brain *n*'s payload is reproducible
  byte-for-byte on any later attempt. The `in_flight` record persists **three**
  digests, one per index. "Identical payload" throughout this skill means
  identical to that brain index's own payload, **never** identical across brains.
- **Three-phase record**, so an interruption is always classifiable: `in_flight`
  persisted with three owner ids and three payload digests **before** dispatch;
  responses landing as individual immutable files; the finalised status persisted
  with the computed result.
- `in_flight` with three response files: **compute and finalise, do not
  re-dispatch.** With zero to two and no live owners: **re-dispatch only the
  missing brain indices**, each rebuilt from its own `(qid, brain_index)` and
  checked against its persisted digest. Never re-dispatch a brain that already
  answered. Never discard an existing answer to obtain a tidier set. A partial
  quorum is never evaluated. A finalised record is never recomputed.
- A qid whose `context_digest` no longer matches current `decisions.md` is **not**
  re-opened; it is flagged to stage 11 as `stale-context`. Re-deciding on resume
  is precisely the silent-divergence failure.
- **Never re-run a quorum to check.** A second run with different brains produces
  a different answer roughly as often as the rung gap is narrow, and the
  controller has no principled way to prefer either.

## Contradicting a recorded decision

**Detection is structural, not semantic.** Every stage-03 question has a stable
axis id and every later question is tagged to one. Before adoption, check whether
the adopted consequences require a different option on an axis a human already
decided.

Rejected attempts are **recorded, not discarded**. A run with several
`rejected-contradicts-*` events is a run whose brains keep pulling away from what
the user asked for, and that count belongs in the terminal report as the earliest
available warning.

Against an earlier **quorum** answer: the axis index in `decisions.md` is
validated on every write, and a file holding two adopted contradicting answers on
one axis **fails validation and is a read-only stop** — the same severity as a
foreign schema. A contradicting question becomes a **re-open at a raised bar, at
most once per D-ID per run**; a second challenge halts. This is the
anti-oscillation rule that stops a run spending its budget arguing with itself.

## Why both agents have exactly three tools

`pipeline-auto-brain` and `pipeline-auto-intent-reader` each declare `Read`,
`Grep` and `Glob`. No `Write`, no `Edit`, no `Agent`, and — the part that looks
like an oversight and is not — **no `Bash`**.

**There is no such thing as read-only Bash.** Agent frontmatter allowlists
*tools*, not *commands*, so an agent holding a shell can run
`echo > decisions.md` exactly as easily as `git log`. An earlier draft of this
design said "read-only Bash" and carried the restriction in prose. That version
had three of its four legs enforced and one asking nicely, which is the same as
having three legs.

The two agents are restricted for related but distinct reasons, and the second is
the worse one:

- **The brain can corrupt the record.** The whole case for restricting a brain is
  that a decision record a voter can edit is not a record. `decisions.md` is what
  makes every adopted answer attributable and permanent.
- **The intent reader can corrupt the anchor.** Every response must cite a spec
  line or a stage-03 answer in `consistent_with`, and the intent brief is what
  those citations rest on. Corrupt the record and someone eventually notices a
  contradiction. Corrupt the anchor and every downstream grounding claim inherits
  it **while still resolving cleanly** — the citation points at a line that
  genuinely is there, in a file that was quietly rewritten. Citation verification
  cannot catch it, because the citation is true. Nothing downstream can.

Nothing is lost by the narrowing. Grounding needs to resolve a citation to a file
and a line and to find exemplars; reading a request needs the same. That is
`Read`, `Grep`, `Glob`. A question that genuinely requires executing a command is
not a question three readers can settle — it is a **fact**, and facts go to one
adjudicator (`references/review.md`), never to a quorum.

**Do not restore a tool to either agent as a convenience.** "It only needs
`git log`" is the argument that will be made, and it is true right up until it is
not. `tests/test_skill_structure.py` asserts each agent's exact tool set, so the
restoration fails a test rather than shipping.

### Write boundaries as exact sets, not blacklists

A general lesson, recorded here because this skill contains two instances of it
and the next maintainer will write a third.

**An exact-set assertion fails on a tool nobody thought to forbid; a blacklist
only fails on the ones somebody remembered.** A forbidden-names list is a
rolling guess about the future — it cannot know about the tool that ships next
quarter, and it passes the moment that tool is the one added. Declaring the
permitted set closes the question permanently, because anything not on the list
fails by default rather than by having been anticipated.

The same reasoning rules out one test looping over both agents. A loop whose list
is empty — or whose list somebody shortens while tidying — passes silently, and a
boundary that can pass by disappearing is not a boundary. **Two boundaries, two
tests, each naming its own agent.**

## Never ask a brain to reconsider

The controller must **never** ask a brain to reconsider its confidence, its rung,
or its answer. That is a pressure signal: it moves the number without moving the
evidence. If the result is not adoptable, the outcome is an escalation, not
another round of asking.
````

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k test_every_required_reference_exists`

Expected: the `[reference=quorum]` subtest passes; the other four still fail.

Then confirm no home-directory path leaked in:

Run: `grep -n "/home/" plugins/superb/skills/pipeline-auto/references/quorum.md`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/references/quorum.md
git commit -m "docs(pipeline-auto): the quorum contract reference"
```

---

### Task 8: `references/planning.md`

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/references/planning.md`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: the `pipeline-auto-intent-reader` agent (Task 2); the `pipeline-auto-brain` agent and `prompts/brain.md` (Tasks 2 and 4) for stage 02; `references/quorum.md` (Task 7) for the rules stage 07 defers to.
- Produces: the reference `SKILL.md` routes to for stages 01–07. It owns the strict phase-plan metadata grammar `PlanMetadataError` validates, so the grammar is stated here exactly once.

This reference covers everything up to and including the point where the phase set becomes immutable. Its most important sentence is the one about stage 06.

- [ ] **Step 1: Write the failing test**

Already written in Task 1.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k test_every_required_reference_exists`

Expected: FAIL on `[reference=planning]`.

- [ ] **Step 3: Write the reference**

Create `plugins/superb/skills/pipeline-auto/references/planning.md`:

````markdown
# Planning: stages 01–07

Read this reference during the intent read, question synthesis, the human gate,
design, spec, master plan, and phase fan-out. After stage 06 closes, the phase
set is immutable and nothing in this file applies again.

## Stage 01 — Intent read

Dispatch **exactly three** `pipeline-auto-intent-reader` agents. Not two when
capacity is tight, not four for a complicated request. At `worker_limit < 3`
they run sequentially.

Each returns a strict JSON hypothesis: what the request explicitly says (with
the user's own words quoted), what it implies (with the basis named), what it
leaves unstated, what it puts out of scope, and what the repository already
provides with `file:line`.

Reconcile the three into one intent brief. **Conflicts are flagged, never
resolved.** Three readers disagreeing about what the user asked for is the
highest-value signal this run will ever produce, and a controller that quietly
takes the majority reading has destroyed it. Record each conflict with all three
readings verbatim.

**Unresolved stage-01 conflicts consume stage-03 question slots ahead of any
stage-02 synthesised question.** An unresolved conflict about what the user
asked for is by definition higher blast radius than anything downstream.

The intent brief is **immutable after stage 03**. A later finding that
contradicts it escalates; the human amends it. It is not edited in place by the
run.

## Stage 02 — Question synthesis

Dispatch **exactly three** `pipeline-auto-brain` agents to propose the open
decisions — the same three-brain discipline, the same reading assignments, the
same payload prohibitions. Use `prompts/brain.md`.

The controller then ranks the proposals by blast radius, dedupes them, and cuts
to **four**. Ranking and cutting are routing, not deciding: the controller does
not answer any of them and does not add one of its own.

A proposed question that fails admissibility (`references/quorum.md`) is dropped
here, not carried into the gate. The gate is four slots and they are the most
expensive four slots in the run.

## Stage 03 — The one gate

**One `AskUserQuestion` call. At most four questions. This is the only
guaranteed human interaction in the run.**

Persist every answer with `Provenance: human`, a stable axis id, and
`Decision action: none` unless the answer is itself a transition authority.
Human answers are `H-<n>`.

These answers are the only requirements the run may treat as unimpeachable.
Everything decided later traces back to one of them through `consistent_with`,
or it escalates.

Do not spend a slot on something the repository answers. Do not spend a slot on
something a quorum could decide from the spec and the code — spend it on what
only the user knows: budget, deadline, who the users are, what the product is
*for*, which of two products this is.

**A generic approval is not an answer.** "Sounds good", "continue", "you
decide" resolves nothing, and the run must not record it as though it did.

## Stage 04 — Design and gate classification

**REQUIRED SUB-SKILL:** `superpowers:brainstorming`, for repository
investigation, alternatives, and architecture.

Stage 04 also **fixes each phase's `review_class`**, before any plan exists.
That ordering is deliberate: classifying risk after seeing the plan invites
classifying it to fit the plan.

`review_class ∈ {final-only, required}`, carried in phase-plan metadata and
mirrored into the tracker. See `references/execution.md` for what each buys and
for the one-way ratchet.

**A phase is never reclassified downward.** Not at stage 04 on reflection, not
later, not by quorum, not to fit capacity or budget.

## Stage 05 — Spec

A brain agent feeds it; `superpowers:writing-plans` writes it. The spec records
the selected architecture and boundaries, not a chat summary. Save it under the
repository's convention, or `docs/superpowers/specs/<feature>-design.md` when
none exists.

## Stage 06 — Master plan

**REQUIRED SUB-SKILL:** `superpowers:writing-plans`.

The master plan identifies every phase, its dependencies, its detailed phase-plan
path, its planned mechanical verification, and its `review_class` with the
specific risk reason.

**The phase set becomes immutable when stage 06 closes.** After that transition
the run cannot create work for itself: phase creation is a stage-06 transition
and stage 06 is over. Scope expansion is structurally impossible, not merely
forbidden, and the state machine enforces it rather than the controller's
restraint. This is what makes the completeness freeze in `references/review.md`
a guarantee instead of a promise.

**Discover the target repository's test runner now and record it.** Read its CI
config, its manifest, and its existing test files. Do not assume `pytest`
because it is common, or `unittest` because the last project used it. A plan
naming a runner that is not installed is a plan failure, and the failure does not
surface until an implementer tries to run it — by which time it looks like the
implementer's problem.

Record the same way: the coverage policy, the lint and format commands, and every
mandatory repository quality gate. Never invent a coverage percentage. If no
coverage policy is explicit, it is a stage-03 question or it is behaviour-focused
testing without a numeric threshold — not a number you chose.

## Stage 07 — Phase fan-out

One `superpowers:writing-plans` worker per phase, capped by `worker_limit`.
A phase has **at most 12 genuine tasks**; more means split it before approval,
and substeps are not a place to hide separately checkable work.

**A planner never invents an interface.** An unresolved interface or behaviour
comes back as `NEEDS_CONTEXT` or `PLAN_CONFLICT` with a question record. That is
the route into `references/quorum.md`, and it is the only route: a planner does
not dispatch brains and does not decide.

### Strict phase-plan metadata

One ordered phase comment in the document header, before its first section:

```text
<!-- pipeline-auto-phase: id=<phase-id>; deps=<none-or-phase-ids>; review_class=<final-only-or-required>; review_reason=<nonempty-approved-reason> -->
<!-- pipeline-auto-phase-suite: id=<same-phase-id>; commands=["<exact-command>","<next-command>"] -->
```

One ordered task comment immediately below every task heading:

```text
<!-- pipeline-auto-task: id=<stable-id>; deps=<none-or-task-ids>; kind=<source-or-artifact>; batch=<batch-id>; order=<positive-integer>; write_scope=<typed-scopes>; outputs=<none-or-exact-files> -->
```

Immediately after each `source` task comment, its ordered task suite:

```text
<!-- pipeline-auto-task-suite: id=<same-task-id>; commands=["<exact-command>"] -->
```

Keys are exactly `id`, `deps`, `kind`, `batch`, `order`, `write_scope`, `outputs`,
in that order. Commands are a nonempty JSON string array in exact execution
order with no duplicates. The phase suite is required for every phase; the task
suite only for `source` tasks.

- `source` changes repository content, uses `outputs=none`, and later requires
  implementation commits, test evidence, and **separate** integration evidence.
- `artifact` creates only the exact approved files named by `outputs`, records
  integration `N/A`, and never justifies an empty or unrelated commit.

**A worker cannot choose its task kind from whether a diff happened to be
empty.** Only the approved task definition chooses it.

Write scopes are comma-separated `file:<repository-relative-file>` or
`tree:<repository-relative-directory>`. Reject absolute paths, traversal,
backslashes, empty segments, globs, and symlink-dependent aliases rather than
normalizing them. Two exact files conflict when equal; trees conflict by equality
or ancestry, and a tree conflicts with every file it contains.

**No absolute home-directory path appears in any committed file**, including a
write scope, an output path, or a command. Repository-relative paths, or `~` /
`$HOME` expanded at runtime.

## The executable-plan gate

Before implementation starts, verify: the spec, master plan and every phase plan
exist on disk; shared interfaces are settled; every phase has 1–12 tasks; task
and phase dependencies are acyclic and executable in master order; every task's
metadata parses under the strict grammar; the test runner, coverage policy,
batches, `worker_limit` and `review_class` are explicit; and no escalation is
outstanding.

`worker_limit` must be a positive integer compatible with detected runtime
capacity. **`worker_limit >= 4` is required for concurrency**: brains consume
three unique owners, so implementation tasks may occupy at most
`worker_limit - 3` slots. Below 4, tasks serialise so the brain slots stay free.
Otherwise a blocked task holds the slot needed to unblock it and the run
deadlocks permanently.

There is no second human approval here. Stage 03 was the gate. Everything from
here is quorum or escalation.
````

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k test_every_required_reference_exists`

Expected: `[reference=planning]` and `[reference=quorum]` pass; three still fail.

Run: `grep -n "/home/" plugins/superb/skills/pipeline-auto/references/planning.md`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/references/planning.md
git commit -m "docs(pipeline-auto): planning reference for stages 01-07"
```

---

### Task 9: `references/execution.md`

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/references/execution.md`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: `prompts/implementer.md`, `prompts/task-reviewer.md`, `prompts/adversarial-reviewer.md` (Tasks 5, 6); `scripts/task-brief`, `scripts/review-package` (Task 3); `scripts/sdd-workspace` (P02); `reserve_task`, `resume_task`, `scopes_overlap`, `publish_worker_result`, `import_worker_result`, `verify_source_range` (P04); `adversarial_required`, `record_task_review`, `open_fix_round`, `ratchet_phase`, `propagate_provisional` (P05).
- Produces: the reference `SKILL.md` routes to for stages 08–10. It owns the dial, the per-task gate, and the ratchet table.

This is where the inlined SDD protocol lives. Its load-bearing paragraph is the list of things the dial may never switch off — that list is the answer to "we're only on `final-only`, so we can skip this".

- [ ] **Step 1: Write the failing test**

Already written in Task 1.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k test_every_required_reference_exists`

Expected: FAIL on `[reference=execution]`.

- [ ] **Step 3: Write the reference**

Create `plugins/superb/skills/pipeline-auto/references/execution.md`:

````markdown
# Execution: stages 08–10

Read this reference while selecting work, dispatching implementers, running the
per-task gate, integrating, verifying a phase, or debugging a failure.

## Required sub-skills

- **REQUIRED SUB-SKILL:** `superpowers:test-driven-development` for every
  testable behaviour and every behaviour-changing fix: a meaningful failing test,
  the intended failure observed, the minimum approved behaviour implemented, the
  focused test kept green through refactoring. **RED before GREEN is recorded in
  the implementer's report and the dial never switches it off.**
- **REQUIRED SUB-SKILL:** `superpowers:systematic-debugging` for stage 10. The
  cause is traced before any fix.
- `superpowers:using-git-worktrees` for isolation; one worktree per concurrently
  dispatched implementer, merged `--no-ff` in task order. `--no-ff` preserves
  ancestry, so the no-squash rule holds.
- `superpowers:dispatching-parallel-agents` only for ready independent batches.

**A merge conflict at integration is a hard stop.** Under typed write-scope
validation a conflict should be impossible, so a conflict is evidence the scopes
were wrong. It is not something to auto-resolve past.

## The review-intensity dial

`review_class ∈ {final-only, required}`, fixed at stage 04, carried in phase-plan
metadata, mirrored into the tracker.

**`required`** buys the full per-task gate:

1. a fresh implementer per task, dispatched with a **task brief file** from
   `scripts/task-brief`, never with plan text pasted through the controller;
2. a review package from `scripts/review-package`, built from the **persisted
   reservation baseline** — never `HEAD~1`, which silently drops all but the last
   commit of a multi-commit task;
3. a task reviewer returning **three** verdicts: spec, quality, and verification
   evidence from an independent re-run;
4. a fix loop to **zero open findings at every severity**, one fixer per round
   carrying all findings;
5. completion only after a round returns zero.

**`final-only`** buys mechanical verification only. Stage 11 is the net.

### What the dial may never switch off — at any class

- the adversarial trigger check;
- typed write-scope declaration and conflict detection;
- digest-bound typed PASS evidence;
- the `baseline..source-head` range proof and the integration ancestry predicate;
- immutable four-part worker result identity (`run_id + task_id + attempt + owner`);
- TDD RED-before-GREEN evidence recorded in the implementer report;
- the most-capable-model policy;
- the zero-open-findings bar itself.

**The dial controls whether a reviewer runs. It never controls what bar that
reviewer applies.** A `final-only` phase whose diff touches auth still gets the
adversarial pass, and that pass still holds every finding to the same bar.

### Adversarial triggers — independent; any single one fires

`concurrency` · `authz` · `crypto` · `schema` · `migration` · `delete` ·
`regulated` · `public-api` · `large-surface` (> 300 changed source lines)

**A 10-line auth change is high-risk.** Collapsing this into "300 lines AND a
risky path" is the obvious and wrong reading, and it is the single most likely
way this check gets quietly disabled. `adversarial_required()` returns the
trigger **name**, so the tracker records which one fired; a trigger that fired
and was not recorded is indistinguishable from one that never fired.

### The ratchet — upward only

`final-only → required`, mechanically triggered, **never downward and never by
quorum**:

| Trigger | Condition |
| --- | --- |
| (a) `adversarial-finding` | any task produced a CONFIRMED or unrefuted PLAUSIBLE adversarial finding |
| (b) `repeated-suite-failure` | the phase suite has failed twice or more |
| (c) `debug-locality` | a stage-10 root cause traced into a file inside this phase's write scopes |
| (d) `low-confidence-dependency` | a quorum adopted a decision in this phase at `code-evidenced` rather than `specified` |
| (e) `accumulated-surface` | cumulative changed source lines in the phase exceed 300 |

A ratchet does **not** retroactively review complete tasks. It gates every
remaining task and adds a phase-scoped review over the phase's whole edge at the
zero-open-findings bar.

A tracker `review_class` differing from plan metadata is legal **only** with a
matching ratchet record. Without the record it is a validation failure, because
otherwise "the tracker says `final-only`" becomes a way to undo a ratchet.

**Never degrade a quorum, a review, or an intensity to fit capacity or budget.**
The run escalates or halts instead. A soft dispatch-budget threshold escalates
*reporting* the overrun; a hard one stops the run resumably. It never silently
downgrades the dial.

## Stage 08 — RED

The failing test is written and **committed before the change**. The implementer
report records the exact RED command, the relevant failing output, and why that
failure was the expected one; then the GREEN command and its output. A report
with a GREEN and no RED is a report claiming a test-first process it cannot
evidence, and the reviewer treats it as such.

**Run the runner the plan recorded**, discovered from the target repository at
stage 06. Never substitute a runner because it is the one you know. If the
recorded runner is not installed, that is a `PLAN_CONFLICT` — stop and publish
the question record. Do not silently switch runners: a suite that passes under a
different runner is not evidence about the suite the plan named.

## Stage 09 — GREEN

Before every actual start, serialise the reservation through the state helper and
revalidate: task state, dependency evidence, outstanding questions, active
ownership and pairwise scope overlap among **all** candidates in the proposed
reservation, and the persisted `worker_limit` against a fresh capacity
observation. Several candidates that were individually ready are not jointly
authorised.

Persist `[~]`, owner and attempt **before** dispatch. `reserve_task` handles the
first `[ ]` → `[~]`. `resume_task` handles an answered `[?]` → `[~]` only, and
requires the matching prior attempt, a distinct unused new attempt, and a
`decision_ref` resolving to `Decision action: task.resume`.

**Context compaction is not a blocked-task retry.** Reconcile the existing
assignment first; a consistent active `[~]` attempt stays the same attempt.

Dispatch with `prompts/implementer.md`. Every worker receives its brief file, its
governing decisions, its write scope, its task suite, and its four-part identity.

### Worker statuses

`DONE` · `DONE_WITH_CONCERNS` · `NEEDS_CONTEXT` · `PLAN_CONFLICT` · `BLOCKED`

- `DONE` is **evidence, not acceptance**. Import validates identity, task
  definition, required files, Git facts and checks before anything is `[x]`.
- `NEEDS_CONTEXT` and `PLAN_CONFLICT` move the attempt to `[?]` and carry a
  question record. That is the route into `references/quorum.md`.
- `BLOCKED` halts. Three brains cannot conjure an API key, and sending one there
  is how the quorum degrades into an ask-three-models-when-unsure reflex.
- **A worker never dispatches anyone**, never edits `progress.md`, never
  integrates its own work, and never declares a phase accepted. Its only state
  call is `publish_worker_result` for its own assigned result.

### Completion and integration are separate facts

A `source` start or resume records `baseline:<attempt>@<full-target-SHA>` inside
the same locked transition. Implementation completes only when the resolved
source head contains exactly the complete ordered nonempty `baseline..source-head`
range, every changed path is inside the approved scope, and one digest-bound
`task-test` PASS record matches the run, task, attempt, source head and exact
ordered task suite.

Integration is recorded separately: every implementation commit is an ancestor of
the integration commit; the integration commit is an ancestor of the target
branch; one digest-bound `task-integration` PASS record names that exact state.
An unrelated reachable commit proves nothing. No squash, rebase or cherry-pick
equivalence is assumed.

An `artifact` task requires exactly its declared outputs plus validation
evidence, records integration `N/A`, and never invents an empty commit.

### The per-task gate, when `review_class` is `required`

1. Build the review package: `scripts/review-package <baseline> <head>`. It
   prints the path; **the package never enters the controller's context.**
2. Dispatch the task reviewer (`prompts/task-reviewer.md`) with the brief, the
   report, the package, the governing decisions and the test commands. **The
   reviewer is never the implementer.**
3. Resolve every ⚠️ "cannot verify from diff" item yourself — you hold the
   cross-task context the reviewer lacks. A confirmed gap is a failed spec
   review: back to the implementer, then re-review.
4. Run `adversarial_required()`. If it returns a trigger, dispatch
   `prompts/adversarial-reviewer.md` on the same package. CONFIRMED findings are
   Critical; unrefuted PLAUSIBLE are Important.
5. Fix to **zero open findings at every severity**, one fixer per round carrying
   all findings, re-reviewing after each. Default cap: three rounds.
6. Complete the task only after a round returns zero.

**Minor findings are fixed, not deferred.** A deferred finding is a triaged-away
finding, and the implementer's context is one dispatch away right now.

The one exception is narrow and recorded: see the reconciliation rule in
`references/review.md`. A Minor or quality-part finding that would require
reversing a recorded decision goes to reconciliation rather than winning
automatically; if the decision survives, the finding is recorded
`REFUTED — governed by <D-ID>` and does not block completion.

**The fix loop does not stall during reconciliation.** The task moves to `[?]`
with a reconciliation question reference, its owner slot releases, and
independent work continues. **The fix-round counter does not increment** — a
decision dispute must not burn the three-round budget and escalate for the wrong
reason.

## Stage 10 — Debug

**REQUIRED SUB-SKILL:** `superpowers:systematic-debugging`. Establish the cause
before changing behaviour. Mechanical failures are unfinished implementation:
repair and rerun the affected checks. Do not manufacture a formal finding or a
remediation round for work that has not reached its planned gate.

A root cause traced into a file inside this phase's write scopes is ratchet
trigger (c). Record it; the ratchet is mechanical, not a judgment call.

## The mechanical phase boundary

Before recording phase verification, confirm: every task has verified `[x]`
evidence; every source task satisfies the full implementation → integration →
target ancestry rule; every artifact task has its validated outputs and `N/A`
integration; every command in the plan's **exact ordered** phase suite passes on
the integrated state; and one digest-bound typed `phase` PASS record matches the
run, phase, code-state identity, command tuple, inputs and environment.

Caller-supplied command text is checked against the approved tuple. It is not
authority and cannot substitute, omit, duplicate, add, or reorder a command.

A failing planned suite keeps the phase unfinished. Completing the last task does
not advance the phase; `advance_phase` does, and only after verification and any
required gate have passed. Advancing the last phase routes to stage 11, not to
completion.
````

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k test_every_required_reference_exists`

Expected: `execution`, `planning` and `quorum` pass.

Run: `grep -n "pytest\|/home/" plugins/superb/skills/pipeline-auto/references/execution.md`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/references/execution.md
git commit -m "docs(pipeline-auto): execution reference for stages 08-10"
```

---

### Task 10: `references/review.md` and `templates/completeness-proposals.md`

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/references/review.md`
- Create: `plugins/superb/skills/pipeline-auto/templates/completeness-proposals.md`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: the two-reviewer gate, `DECISION-CHALLENGE` routing, the completeness freeze and phase-set immutability from P06; `references/quorum.md` for the re-open rules.
- Produces: the reference `SKILL.md` routes to for stages 11–12, and the frozen proposal ledger the terminal report reads.

Two things here are counter-intuitive enough that the prose must argue for them
rather than assert them: a fixer's dispute goes to **one** adjudicator, not three
brains; and `MISSING-FROM-SPEC` is frozen rather than triaged.

- [ ] **Step 1: Write the failing test**

Already written in Task 1.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Templates`

Expected: FAIL on `[template=completeness-proposals]`.

- [ ] **Step 3: Write the two files**

Create `plugins/superb/skills/pipeline-auto/references/review.md`:

````markdown
# Review and completion: stages 11–12

Read this reference for the master gate, contradiction routing, a fixer dispute,
the completeness critic, or final verification.

**REQUIRED SUB-SKILL:** `superpowers:requesting-code-review` to dispatch.
**REQUIRED SUB-SKILL:** `superpowers:verification-before-completion` for stage 12.

## Stage 11 — The master gate

**Exactly two independent reviewers**, over the complete edge from the immutable
tracker `base_commit` to the last approved phase's recorded verified integrated
HEAD, which must still equal the designated target-branch tip.

**Neither reviewer may be a persisted task implementation owner.** This is
enforced, not requested.

- **Reviewer A** covers requirements, behaviour, error paths, assumptions, and
  recorded decisions. A is obliged to **score and name every `provisional`
  task** — every task whose dependency closure contains a decision adopted at
  `code-evidenced` rather than `specified`. Each tainting decision's ID and
  adopted answer are copied **verbatim into A's global-constraints block**. A
  label the reviewer has to go and look up is a label nobody reads.
- **Reviewer B** covers integration, architecture, persistence, recovery,
  concurrency, security where relevant, regressions, and test quality.

Both reports are collected before consolidation or any fix dispatch. Then a
**completeness critic** runs (below).

Severities are classified by demonstrated consequence: **Critical** — blocking
security, data loss, destructive behaviour, or fundamental failure to meet an
approved requirement. **Important** — blocking correctness defect, regression,
missing approved behaviour or required test, or unsafe recovery or integration.
**Minor** — nonblocking only when it violates no approved requirement and creates
no likely defect. **Ease of fixing never determines severity, and a missing
approved requirement is never Minor.**

**Zero open findings at every severity**, the same bar as the per-task gate. A
gate that can defer while task gates cannot is incoherent.

A reviewer claim is not true because it was reported. Confirm it against the
code, the tests, the spec, and `decisions.md`. Never downgrade a verified finding
to pass a gate, and never reject one because its fix is inconvenient.

## Contradiction routing

**The controller's only power here is routing.** It may not decide which of the
reviewer and the decision record is right.

| Situation | Route |
| --- | --- |
| Code does not comply with a decision | ordinary finding, ordinary fix loop |
| Plan-mandated finding tracing to a **human** decision | **halt** to the escalation queue, never quorum |
| Plan-mandated finding tracing to a **quorum** decision | re-open that qid at a raised bar |
| Plan-mandated finding `writing-plans` invented | ordinary quorum |
| `DECISION-CHALLENGE` against a **human** decision | **halt**, always |
| `DECISION-CHALLENGE` against a **quorum** decision | one re-open at a raised bar |
| Second challenge to the same D-ID | **automatic halt** |
| Fixer disputes a reviewer finding | **one adjudicator**; quorum only on PLAUSIBLE |

A re-open carries the challenging evidence but **never** the original rung and
never who chose it. At most one re-open per D-ID per run.

### A fixer's dispute is not a quorum call, because it is not a decision

"Can line 41 be null" is a **fact**, settled by reading code and running an
experiment — not by a confidence-weighted vote. Three models agreeing that line
41 cannot be null is far weaker evidence than one model running the test.

Routing facts to the quorum is a category error, and it is the mechanism by which
a quorum degrades into a general-purpose "ask three models when unsure" reflex,
which is itself a drift vector.

The dispute is admissible only with a refutation citing `file:line`, or a command
and its output. **A bare disagreement is inadmissible and the finding stands.**

**One adjudicator** — most capable model, read-only — receives the finding, the
rebuttal, and the review package, and settles the fact by citation or focused
experiment:

- **CONFIRMED** — the finding stands and the fixer fixes.
- **REFUTED** — closed, with the adjudicator's citation.
- **PLAUSIBLE** — genuinely irreducible. **Only this** becomes a quorum question,
  and by then it honestly is a judgment call rather than a fact. Frame its
  candidates neutrally, never loaded toward fixing.

One agent instead of three, more accurate, and it preserves what the quorum is
for: **choices, not facts.**

**An adjudication never enters `decisions.md` as a requirement decision.** It
belongs in the findings ledger.

### The one principled exception to zero open findings

Under zero-open-findings every Minor must be fixed. So if a quality-rubric Minor
required reversing a quorum decision, an automatic reviewer win would let a
naming opinion silently overturn architecture.

A reviewer finding therefore prevails **only** when it is Critical or Important
*and* its verdict part is spec-compliance or verification-evidence. A Minor, or
any quality-part finding, that would require reversal goes to an **unbiased
reconciliation**. If the decision survives, the finding is recorded
`REFUTED — governed by <D-ID>` and does not block completion.

Narrow, and recorded rather than discretionary. Do not widen it.

## The completeness critic

Every item is classified `SPEC-NOT-MET` or `MISSING-FROM-SPEC`.

**`SPEC-NOT-MET` is not a proposal — it is a finding.** It enters the fix loop at
the zero-open-findings bar like any other.

**`MISSING-FROM-SPEC` is frozen.** It is written to the run's
`completeness-proposals.md`, given an ID, and surfaced in the terminal report. It
is **never** converted into a task, never dispatched, never quorum'd.
`next_action` becomes `complete-with-proposals`.

This is not merely forbidden — it is **impossible**: phase creation is a stage-06
transition, and the phase set became immutable when stage 06 closed. The state
machine enforces it rather than the controller's restraint.

The reasoning belongs here so a future maintainer can defend the rule rather than
assert it. Every other quorum answers a question that **blocks** work, and quorum
exists to unblock, not to enlarge. "Should we also handle X" has no natural
ceiling, and three brains asked whether an adjacent case is worth covering will
say yes, confidently, because yes is always defensible. It is the one question
class where quorum has a **systematic** rather than a random bias, and a
systematic bias is not something a threshold can fix.

## Stage 12 — Final verification

**REQUIRED SUB-SKILL:** `superpowers:verification-before-completion`.

Record digest-bound `final` PASS evidence for the accepted master HEAD, through
the controller transition, against the run's derived project root. A different
repository path cannot supply the Git proof.

Completion requires: the master gate accepted; final verification recorded; all
intended work committed and integrated on the designated clean feature branch;
`git status --short` printing **nothing**, with `scratch/` covered by its
self-ignoring `.gitignore`; and files consistent enough that a fresh session
derives `complete` from the files and Git rather than from a previous completion
message.

**Never push, publish, create a pull request, or merge into `main`/`master`.**
Success leaves a clean committed feature branch and a report.

## The terminal report

It **leads with the quorum-adopted decisions, sorted by confidence ascending** —
weakest first, because the weakest is the one most likely to be wrong and least
likely to be read if it is buried at the bottom.

Every quorum-adopted decision is labelled as such, forever, in three places: the
decision record, the tracker index, and this report. A provenance field read only
by a validator has informed nobody.

The report also carries:

- every `provisional` task and its tainting decision;
- the count of `rejected-contradicts-human` and `rejected-contradicts-quorum`
  events — a run with several is a run whose brains kept pulling away from what
  the user asked for, and that is the earliest available warning;
- every frozen `MISSING-FROM-SPEC` proposal;
- the adoption floor actually applied, and any run-level inflation adjustment;
- the drift budget consumed and any extensions granted;
- every escalation, answered or outstanding.
````

Create `plugins/superb/skills/pipeline-auto/templates/completeness-proposals.md`:

```markdown
# Completeness proposals — <run-id>

<!-- pipeline-auto-completeness/v1 -->

Everything in this file is **frozen**. It is a record of work this run decided
not to do, and it is never converted into a task, dispatched, or sent to a
quorum. The phase set became immutable when stage 06 closed; nothing here can
change that.

A proposal is not a defect. A missed requirement is a `SPEC-NOT-MET` **finding**
and it went into the fix loop — it is not in this file. What is in this file is
the critic's answer to "what else might this reasonably have covered", which is a
question with no natural ceiling and a systematic bias toward yes.

## Proposals

| ID | Proposal | Raised by | Phase | Why it is out of scope |
| --- | --- | --- | --- | --- |
| CP-001 | <one sentence: the behaviour or coverage not in the spec> | <critic assignment id> | <phase id> | `MISSING-FROM-SPEC` — not in the approved spec; the phase set is immutable after stage 06 |

## Per proposal

### CP-001 — <short name>

- **Classification:** `MISSING-FROM-SPEC`
- **Raised at:** stage 11, gate `<gate-id>`
- **Evidence:** `<file:line>` or the reviewed range showing what is not covered
- **What would have to change to build it:** a new run whose stage-03 round asks
  about it, or an explicit human decision creating a follow-up.
- **Status:** `Frozen`

## Rules

- The only legal status is `Frozen`.
- No proposal acquires a task id, a write scope, an owner, or a commit.
- A proposal is never re-raised as a quorum question in the same run. A re-raise
  of a frozen proposal is discarded, not re-litigated.
- When this file is non-empty, `next_action` is `complete-with-proposals` and the
  terminal report lists every entry. A run that completes with proposals is a
  successful run that was honest about its edges — not a failed one.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Templates -k test_every_required_reference_exists`

Expected: all eight `Templates` subtests pass; `[reference=review]` passes; only `[reference=persistence]` still fails.

Run: `grep -n "pytest\|/home/" plugins/superb/skills/pipeline-auto/references/review.md plugins/superb/skills/pipeline-auto/templates/completeness-proposals.md`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/references/review.md \
        plugins/superb/skills/pipeline-auto/templates/completeness-proposals.md
git commit -m "docs(pipeline-auto): review reference and the frozen proposals ledger"
```

---

### Task 11: `references/persistence.md`

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/references/persistence.md`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: from P02 — `SCHEMA`, `MARKER`, `parse_tracker`, `render_tracker`, `validate_run`, `initialize_run`, `locked_tracker_update`, `publish_immutable` (**returns the sha256 hex digest, not the path**), `derive_next_action`, and the exception hierarchy; from P03 — `parse_decisions` and the decision grammar; from P04 — `reconcile_run`.
- Produces: the reference `SKILL.md` routes to for status, resume, and recovery.

Two details settled after this plan's first draft and easy to get wrong:
`publish_immutable` returns a **digest**, not a path — prose that says "the path
it returns" is a defect. And `## Tasks` carries a **`Phase`** column, so a task
row is self-describing and a resume does not have to infer a task's phase from
the plan it came from.

- [ ] **Step 1: Write the failing test**

Already written in Task 1.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k test_every_required_reference_exists`

Expected: FAIL on `[reference=persistence]`.

- [ ] **Step 3: Write the reference**

Create `plugins/superb/skills/pipeline-auto/references/persistence.md`:

````markdown
# Persistence, status, and recovery

Read this reference before creating, inspecting, updating, or resuming a run.

**Files are the authority. Conversation memory is never authoritative.** The run
reconstructs its next action from the tracker, `decisions.md`, immutable worker
results, evidence digests, and Git. A stale `next_action` summary never overrides
the underlying facts.

`progress.md` is the single mutable execution tracker. Plans define the work;
decisions, findings, worker results, quorum records and verification records are
referenced evidence, not competing trackers.

`scripts/pipeline_auto_state.py` is the strict Python 3 standard-library helper
for one documented format. **Do not edit tracker tables by hand**, infer missing
fields, or introduce a second editable state file.

## The schema is `pipeline-auto/v1`, and there is no migration

Marker: `<!-- pipeline-auto/v1 -->`.

A new family name, not `pipeline-run/v3` — a shared family name is an invitation
to write a migration, and there must never be one.

**No migration from `pipeline-run/v1` or `/v2`, in either direction, ever.**

Recognised-but-foreign, missing, malformed, or unknown schema information is a
**read-only stop**: preserve the directory, change no files, dispatch nothing,
and emit a diagnostic naming the other skill and saying the two do not
interoperate. Rejected input is **byte-identical** after the rejected parse.

An unclassified filesystem is also a read-only stop — **not a quorum call.**
Three brains know no more about the filesystem than the classifier does, and
sending them there produces three confident guesses about a fact.

## Where a run lives

```text
docs/superpowers/runs/<run-id>/
├── progress.md
├── decisions.md
├── decisions-effective.md      (generated, read-only projection)
├── findings.md
├── completeness-proposals.md
├── intent-brief.md
├── quorum/<qid>/               (question.json, in_flight, responses, finalised)
├── agent-output/               (immutable worker results)
└── scratch/                    (self-ignoring; briefs, reports, review packages)
```

`scratch/` lives **inside the run directory**, created by `scripts/sdd-workspace`
with a self-ignoring `.gitignore`. Never under `.superpowers/sdd`: that
durability hole — ephemera outliving the run directory that produced them, with
nothing to reconcile them against — is exactly what this skill exists to close.
It also has to be self-ignoring for `git status --short` to be empty at stage 12.

## Tracker sections

The ordinary sections plus, specific to this skill: `## Stage`, `## Intent`,
`## Questions`, `## Quorum`, `## Escalations`, `## Task Review`, `## Fix Rounds`.
`## Remediation` does not exist here and is not to be re-added.

`## Stage` carries stages 01–12 and is not optional. Without it, stages 01–07 are
unrecoverable: a compaction during stage 02 silently re-runs stage 01 and the run
forks from its own history, producing a second intent brief nobody asked for.

`## Tasks` carries a **`Phase`** column alongside `Provisional`, so a task row
says which phase owns it without anyone re-deriving it from a plan path.
`## Phases` carries `Review Class`, `Class Source` and `Ratchet`. A tracker
`Review Class` differing from plan metadata is legal only with a matching
`Ratchet` record.

## Controller-owned transitions

Only the controller performs tracker transitions and result import. For each
mutation `locked_tracker_update` performs one transaction: validate; acquire the
run-local OS lock with a bounded wait; re-read and revalidate; check transition
preconditions and evidence; derive `next_action` from facts; render; **reparse
the render**; write a same-directory temporary file; fsync; atomically replace
`progress.md`; fsync the directory.

Do not fall back to an unlocked write, delete a lock because it looks stale, hold
the lock while agents or tests run, truncate state, or update prose with
find-and-replace.

**Three outcomes, three meanings.** A failure before replacement preserves the
old tracker and removes only this invocation's temporary file. A failure after
replacement raises `UpdateOutcomeUncertain`, never `TrackerWriteError`: the update
**may have applied**. Do not claim unchanged state, roll back, or blindly retry —
re-read under the lock and reconcile by transition identity so the operation
cannot apply twice.

A replayed `transition_id` returns current state without mutating.

`publish_immutable(path, content)` **returns the sha256 hex digest of the
published content**, not the path. The caller already knows the path; what it
does not know until publication is the digest that binds the evidence. Prose or
code treating the return value as a path is a defect.

`inspect` and status reads are strictly read-only: they may derive the correct
action and report that a persisted summary is stale, but they never repair it.

## Decisions and authority

`decisions.md` is **append-only**. The only legal in-place mutation is
`Adopted → Superseded`.

Human answers are `H-<n>`; quorum answers are `Q-<hash>`, so provenance stays
legible even if a field is lost. A required `Provenance` field is `human` or
`quorum`, and a validated **axis index** is checked on every write. A file
holding two adopted contradicting answers on one axis **fails validation and is a
read-only stop** — the same severity as a foreign schema.

Every entry has exactly one `Decision action`:

| Action | Grants |
| --- | --- |
| `task.resume` | one blocked task's `[?]` → `[~]`, for the named prior attempt |
| `quorum.adopt` | recording one quorum-adopted answer for one qid |
| `quorum.extend-budget` | a finite extension of the drift budget. `Provenance: human` only; never grantable by quorum; at most two per run |
| `dispatch.extend-budget` | a finite raise of the `agent_dispatch_count` ceiling. `Provenance: human` only. **Not interchangeable with `quorum.extend-budget`** — one caps review spend, the other caps machine authority |
| `none` | nothing. The entry is a record, not an authority |

**Never derive transition authority from answer wording**, from generic plan
approval, from another agent's preference, or from a fieldless historical entry.
A quorum answer of "proceed" is as empty as a human's.

Provenance must be visible in three places: the decision record, the tracker
index, and the terminal report.

## File-first resume

On compaction, restart, interruption, or uncertainty:

1. validate run identity, schema and filesystem contract;
2. read the spec, master plan, `progress.md` (**`## Stage` first**), the active
   phase plan, and applicable `decisions.md` entries;
3. read `findings.md` and any active fix round;
4. inspect Git branch, worktrees, commits, and immutable result and evidence files;
5. classify every open quorum before anything else — see below;
6. reconcile every `[~]` assignment before starting new work;
7. derive the next permitted action from task, integration, question, quorum,
   verification and gate facts.

A matching complete worker result is imported once through the normal
run/task/attempt/owner validator. A consistent active owner with no final result
stays `[~]`. A commit that appeared immediately before interruption is neither
automatic success nor grounds to repeat the work: validate the recorded attempt,
the contents, the ancestry and the applicable tests, and import only
independently validated evidence.

Partial, conflicting, or unverifiable state stays blocked and reaches the user.
Completed work is not rerun; unfinished work is not skipped.

### Resuming a quorum

`in_flight` with three response files: **compute and finalise. Do not
re-dispatch.** With zero to two responses and no live owners: re-dispatch **only
the missing brain indices**, each rebuilt from its own `(qid, brain_index)` and
checked against its persisted digest. Never re-dispatch a brain that already
answered; never discard an answer to obtain a tidier set; never evaluate a
partial quorum; never recompute a finalised record.

A qid whose `context_digest` no longer matches current `decisions.md` is **not**
re-opened. Flag it to stage 11 as `stale-context`. Re-deciding on resume is
precisely the silent-divergence failure this design exists to prevent.

## Supported platform

Cooperating processes on one host over a local filesystem with working OS-backed
locks, hard links for no-clobber initial publication, and same-filesystem atomic
replacement. Linux and macOS use POSIX locking; Linux is the natively exercised
platform. Do not report macOS as natively tested without a macOS run, and do not
report the Windows path as verified without a native Windows runner proving
contention, replacement, interruption recovery and lock release.

Network and distributed filesystems are outside the guarantee. Ignored local run
files survive context compaction in the same workspace — not deletion, machine
loss, or a fresh clone.

Terminal `complete` is conditional on the target repository remaining at the
accepted master HEAD with a clean working tree, including no unexpected untracked
files. A fresh inspect reports inconsistent state rather than trusting a stale
persisted `complete`.
````

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k test_every_required_reference_exists`

Expected: PASS — all five reference subtests.

Run: `grep -n "pytest\|/home/" plugins/superb/skills/pipeline-auto/references/persistence.md`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/references/persistence.md
git commit -m "docs(pipeline-auto): persistence and recovery reference"
```

---

### Task 12: `SKILL.md` — the router, and the whole validator green

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/SKILL.md`
- Read: `plugins/superb/skills/pipeline-auto/tests/pressure/RED-baseline.md` — P01's committed curated record, path confirmed. (P01's `scoring.md` is deliberately uncommitted and is not this file.)
- Test: `plugins/superb/skills/pipeline-auto/tests/test_skill_structure.py`

**Interfaces:**
- Consumes: every file Tasks 2–11 produced, and P01's curated RED baseline.
- Produces: the skill's entry point. After this task the structure validator is entirely green and P08 can begin.

`SKILL.md` is written last because a routing table written before its targets is
a table of guesses. Every path in it is now a path that exists.

**Before writing the Red Flags table, read `tests/pressure/RED-baseline.md`.**
P01 recorded, verbatim, the rationalizations agents actually reached for when
this prose was absent. Each Red Flag row's "the rationalization" column must
answer one of those recorded quotes — not one you imagined. Where P01 recorded a
rationalization no row below covers, add a row. Where P01 marked a scenario
`NON_DISCRIMINATING` — the control agent behaved correctly without any skill —
**write nothing for it.** `superpowers:writing-skills` is explicit: if the
control did not exhibit the failure, there is nothing to fix.

- [ ] **Step 1: Write the failing test**

Already written in Task 1. The classes still red are `SkillFrontmatter`,
`RoutingTable`, `Agents::test_every_agent_named_in_the_prose_exists_as_a_file`,
and `Prompts::test_every_prompt_is_referenced_by_some_prose_file`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`

Expected: FAIL — `missing .../SKILL.md`, plus the unrouted-prompt and unnamed-agent failures.

- [ ] **Step 3: Write `SKILL.md`**

Create `plugins/superb/skills/pipeline-auto/SKILL.md`:

````markdown
---
name: pipeline-auto
description: Use when the user asks to take a substantial feature from an initial idea through implementation in one run with as little interruption as possible — "just build it", "don't keep asking me", "run it autonomously". Not for a run where the user wants to be consulted at each decision; that is superb:pipeline.
argument-hint: "[resume|status]"
---

# Superb Pipeline Auto

## The rule this skill reverses

`plugins/superb/skills/pipeline/references/planning.md:177-181` forbids adding to
the pipeline:

> retired lane/wave authority, reviewer arithmetic, per-task formal review,
> one-agent-per-task execution, recursive fix mode, **a Brain Agent that decides
> user requirements**, or another scheduler.

**This skill is that Brain Agent.** Built deliberately, with guardrails the
author of that clause did not think were sufficient.

The zero-assumption law (`pipeline/SKILL.md:40-71`) held that another agent may
investigate facts and explain options but cannot decide an unresolved
requirement. This skill inverts it. Everything below exists to answer the
objection that clause was making — so read the answer before changing any part
of it:

| The objection | This skill's answer |
| --- | --- |
| A machine will decide what it prefers | It decides only what the **spec or the code entails**. `convention-cited` sits below the adoption floor: a machine may not decide by imitation |
| Three agents agreeing proves nothing | Correct. They are one prior sampled three times, so agreement is not the bar — **grounding rung** is, and the three get different reading assignments to decorrelate them |
| It will decide more and more | Three adoptions per phase, ten per run, checked before dispatch, extendable at most twice and only by a human who is shown the list |
| It will overrule the user | It cannot. A candidate contradicting a `Provenance: human` decision is rejected and escalated at any confidence |
| It will build things nobody asked for | The phase set is immutable after stage 06. Scope expansion is not forbidden, it is structurally impossible |
| It will drift a long way from the request | Depth cap of 2. Three layers of inference from the last thing a human said is where the run stops building the user's product and starts building its own |
| It will grade its own homework | Every adopted decision is labelled forever, in three places, and the terminal report **leads** with them, weakest first |

**A maintainer changing a threshold, a budget, or an escalation route in this
skill is loosening that answer.** The reversal is stated here so the trade is
visible rather than inherited.

If you want a run where the user is consulted at each unresolved decision, that
skill already exists and works: `superb:pipeline`. This one is not a better
version of it. It is a different trade.

## Invocation

Trim whitespace from this complete argument string, then select exactly one mode:

`$ARGUMENTS`

| Argument | Mode |
| --- | --- |
| empty | Full run: begin at stage 01. |
| `resume` | Resume one compatible `pipeline-auto/v1` run from its files and Git evidence. Never create or replace a run. |
| `status` | Strictly read-only inspection. Do not lock, write, reconcile, dispatch, test, fix, or initialize. |
| anything else | Stop and ask what the user meant. Do not guess a verb. |

Use the whole argument string, never an indexed positional placeholder.

For `resume` or `status`, use [references/persistence.md](references/persistence.md).
If no run is identifiable, report that. If several qualify, ask which. Recency is
not selection authority.

## The one gate

**Stage 03 asks at most four questions in a single `AskUserQuestion` call. Those
answers are the only requirements this run may treat as unimpeachable.**

Every later decision is a quorum adoption or an escalation. There is no third
outcome, no controller override, and no second approval step.

## Files are the authority

Conversation memory is never authoritative. Reconstruct the next action from
`progress.md`, `decisions.md`, immutable worker results, evidence digests, and
Git. A stale `next_action` never overrides the underlying facts.

The schema is `pipeline-auto/v1`. **There is no migration from `pipeline-run/v1`
or `/v2`, in either direction, ever.** Foreign, missing, malformed, or unknown is
a read-only stop: preserve the directory, change no files, dispatch nothing, and
say plainly that the two skills do not interoperate.

## Stage routing

Load only the reference the active stage needs.

| Stage | Work | Route |
| --- | --- | --- |
| 01–07 | Intent read, question synthesis, the gate, design and gate classification, spec, master plan, phase fan-out | [references/planning.md](references/planning.md) |
| any | A question raised, a quorum open or finalising, the drift budget, an escalation | [references/quorum.md](references/quorum.md) |
| 08–10 | The dial, per-task gate, TDD, scopes, evidence, integration, debugging | [references/execution.md](references/execution.md) |
| 11–12 | Master gate, contradiction routing, completeness freeze, final verification | [references/review.md](references/review.md) |
| any | Tracker operations, status, resume, results, recovery | [references/persistence.md](references/persistence.md) |

## The dial

`review_class ∈ {final-only, required}`, fixed at stage 04, **upward-ratchet
only**. `required` buys the full per-task gate; `final-only` buys mechanical
verification with stage 11 as the net.

**The dial controls whether a reviewer runs. It never controls what bar that
reviewer applies.** The list of things it may never switch off — the adversarial
trigger check, typed scopes, digest-bound evidence, the range proof, result
identity, RED-before-GREEN, the most-capable-model policy, and the
zero-open-findings bar — is in [references/execution.md](references/execution.md).

## Rungs are schema constants, not run configuration

`specified` 0.95 · `code-evidenced` 0.85 · `convention-cited` 0.70 ·
`engineering-judgement` 0.55 · `speculation` 0.30. Adoption floor:
`code-evidenced`.

They live in the state module. They are **not** in `## Run` and must never be
moved there, because **a controller that can tune its own bar will.** Not
maliciously — every individual lowering looks locally reasonable when the run is
otherwise blocked, and the run is always otherwise blocked when the question
comes up. It is the same class of self-serving move as reclassifying a phase
downward, and it is structurally unavailable for the same reason.

The floor actually applied is persisted per run. Neither the floor nor the values
ever appear in a brain's payload: **a brain that knows the bar clears the bar.**

The values are frozen, but they are not calibrated. Log every event's rung,
runner-up rung and outcome, and revisit after three real runs. The drift budget
is the same: its existence is principled, its exact value is a first estimate.

## Escalations are free. Adoptions are not.

An escalation costs one question in a batch a human was going to read anyway. An
adoption spends a unit of the run's finite machine authority and lands
permanently in `decisions.md` with this run's name on it.

So **escalating is never the discouraged path.** A controller weighing "adopt at
a thin margin" against "escalate" is weighing something scarce against something
free. Escalations never consume the drift budget; only adoptions do. If you find
yourself looking for a reading of the rules that lets you adopt, you have already
found the answer: escalate.

## Red Flags

Each of these is a rule someone will otherwise "simplify" away. The middle column
is the argument that will be used. It is always plausible. That is the problem.

| Never | The rationalization | Why it is wrong |
| --- | --- | --- |
| **Adopt on headcount instead of rung** | "Two out of three agreed" | Two brains sharing one prior are not two pieces of evidence. The bar is grounding, not votes. This is the rule most likely to become majority voting |
| **Average member rungs** | "The cluster's average confidence is fairer" | Averaging punishes a correct lone expert and lets two weak agreers manufacture a majority. A cluster's rung is its **maximum** |
| **Dispatch a fourth brain** | "The three were split; one more would break the tie" | That is a retry-until-you-like-it loop wearing a quorum's clothes. One more sample from the same prior is not more evidence. Escalate |
| **Tell a brain the adoption floor** | "It should know what standard to meet" | A brain that knows the bar clears the bar. It would tune its rung to the threshold, and the rung would stop describing its evidence |
| **Tell a brain it is one of three** | "It's just context" | A brain that knows the panel size can reason about what it takes to win a plurality. "One of several" is deliberate; a count is not |
| **Re-ask a brain to reconsider** | "I'll just ask it to double-check" | A request to think again is a pressure signal. It moves the number without moving the evidence. If the result is not adoptable, the outcome is an escalation |
| **Degrade a quorum to fit capacity or budget** | "We only have two slots free" | Then the brains run sequentially. A count is never reduced to fit capacity. Escalate or halt; never run a smaller quorum and call it one |
| **Switch off an adversarial trigger** | "It's only 10 lines" / "the task reviewer already approved it" | Triggers are independent and any one fires. **A 10-line auth change is high-risk.** The task reviewer's approval is exactly the assumption this pass exists to attack |
| **Reclassify a phase downward** | "This turned out simpler than we thought" | The ratchet is one-way by construction. A phase's class was fixed at stage 04 precisely so it could not be set to fit the plan that followed |

Two more, from the same family:

| Never | Why |
| --- | --- |
| **Send a fact to the quorum** | "Can line 41 be null" is settled by running the test, not by a vote. One adjudicator, read-only. Routing facts to the quorum is how it degrades into an ask-three-models-when-unsure reflex |
| **Convert a `MISSING-FROM-SPEC` proposal into work** | Quorum exists to unblock, not to enlarge. "Should we also handle X" has no ceiling and three brains will say yes, because yes is always defensible. It is frozen, and after stage 06 it is also impossible |
| **Write a verification command into a plan without running it here first** | A command that is correct in general can be unrunnable in this repository. One hyphen in a directory name is enough to break test discovery; a runner that is standard everywhere else can be absent here. "It obviously works" is not evidence, and a bad tuple propagates into every phase that copies it |
| **Restore a tool to `pipeline-auto-brain` because it "only needs" one command** | Frontmatter allowlists tools, not commands. A shell is write access wearing a read-only description, and the audit trail is the thing it writes to |

**The verification one is not a style note, and it names a specific person.**
**The author of the plan runs the tuple, in this repository, before writing it
into the plan.** Not the implementer who runs it later and discovers it is
broken — by then it looks like their fault, they lose a round working out that it
is not, and every other phase that copied the tuple is broken too. The author is
the only one who can catch it cheaply, and the author is the one who has not run
it.

This build produced three instances in a row: a test runner that was not
installed, a discovery flag that cannot work with a hyphenated skill directory,
and a grep that forbade a word the prose needed to teach. Each looked obviously
correct. Each would have shipped into every phase's verification tuple.
`superpowers:verification-before-completion` states the general rule — evidence
before assertions, always. This is that rule applied to the plan itself, and a
plan is exactly the kind of document whose claims nobody re-checks.

## Stop checks

Stop and read the authoritative files when you are about to:

- choose behaviour from convention, convenience, configurability, or an
  undocumented "safe default";
- adopt a quorum answer whose rung ties the runner-up's, or whose cluster you
  computed a second time;
- tell a brain anything the payload builder does not carry;
- dispatch without a persisted assignment, or from a stale readiness result;
- treat available capacity as permission for conflicting, dependent, early or
  duplicate work;
- infer that a missing result means work is complete, or must be repeated;
- advance past failed verification or an unresolved gate;
- create a phase, a task, or a write scope after stage 06 closed;
- run a test command with a runner nobody confirmed is installed;
- write an absolute home-directory path into a file that gets committed;
- perform a remote, PR, publish, or `main`/`master` mutation.

**No push, publish, pull request, or merge into `main`/`master`.** Success leaves
a clean committed feature branch and a report that leads with every decision this
run made without asking.

## Agents and prompts this skill dispatches

| Agent / template | Used at |
| --- | --- |
| `pipeline-auto-intent-reader` | stage 01, three of them |
| `pipeline-auto-brain` with `prompts/brain.md` | stage 02 and every quorum, three of them |
| `prompts/implementer.md` | stage 09, one fresh per task |
| `prompts/task-reviewer.md` | the per-task gate |
| `prompts/adversarial-reviewer.md` | whenever a trigger fires, at any `review_class` |

`pipeline-auto-brain` runs with `Read`, `Grep` and `Glob`. **Three tools. That
is the whole list.** No `Write`, no `Edit`, no `Agent`, and no `Bash`.

A brain that can write can edit `decisions.md`, and the audit trail becomes
worthless. A brain that can spawn breaks the depth-1-by-construction guarantee.
Its response schema has no field for raising a question, which is how unbounded
recursion is prevented at the type level rather than with a counter.

`pipeline-auto-intent-reader` declares **the same exact three tools**, for a
sharper reason. The brain can corrupt the record; the intent reader writes the
**anchor** every later `consistent_with` citation rests on. Corrupt the record
and someone notices a contradiction. Corrupt the anchor and every downstream
grounding claim inherits it while still resolving cleanly — a citation pointing
at a line that really is there, in a file that was quietly rewritten. Nothing
downstream can catch that, so it is prevented at the tool declaration.

**The absence of `Bash` from both is a deliberate narrowing, not an omission.**
An earlier draft said "read-only Bash". There is no such thing: frontmatter
allowlists tools, not commands, so an agent with a shell can run
`echo > decisions.md` as easily as `git log`, and the guarantee would have rested
on prose the agent is free to ignore. `Read`, `Grep` and `Glob` cover what
grounding and reading actually need, so nothing was lost and every leg of both
boundaries is declarative and tested. **Do not restore a tool to either agent as
a convenience**; `tests/test_skill_structure.py` asserts each exact set, in two
separate tests, and the restoration will fail one of them.

Why exact sets and not a forbidden list: see *Write boundaries as exact sets, not
blacklists* in [references/quorum.md](references/quorum.md).

Do not substitute `brainstorm-architect` for either agent. It runs with all tools
and it is built to propose.

## What this skill does not use

Do not invoke `superpowers:subagent-driven-development`. Its protocol is
**inlined** here — its references, its four prompt templates, and its
`task-brief`, `review-package` and `sdd-workspace` scripts are carried in this
directory, with SDD credited in each. `subagent-driven-development/SKILL.md:12`
says the plugin-cache copy is a mirror and that "a superpowers plugin update will
silently overwrite that mirror". A skill whose review protocol an unrelated
plugin update can replace is not reproducible, and this skill modifies the
protocol anyway.

Do not use `superpowers:finishing-a-development-branch` or an interactive
completion menu.
````

- [ ] **Step 4: Run the whole validator to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`

Expected: **OK** — every test in the module passes, including
`RoutingTable::test_every_reference_on_disk_is_routed_from_skill_md` and
`Prompts::test_every_prompt_is_referenced_by_some_prose_file`.

If `test_every_path_named_in_skill_md_resolves` fails, a route in the table is
dead — fix the table or the file, never the test.

Then the constraint checks:

Run: `grep -rn -- "-m pytest" plugins/superb/skills/pipeline-auto/ plugins/superb/agents/pipeline-auto-*.md`
Expected: no output.

Grep for the **invocation**, not the word. `references/planning.md` says
"Do not assume `pytest`" on purpose, and a check that forbids the word forbids
the lesson. What must not appear anywhere in this skill is an instruction to
*run* it.

Run: `grep -rn "/home/" plugins/superb/skills/pipeline-auto/ plugins/superb/agents/pipeline-auto-*.md`
Expected: no output.

Run: `git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/SKILL.md
git commit -m "docs(pipeline-auto): SKILL.md router, reversal statement and red flags"
```

---

## Verification suite for this phase

Exact ordered command tuple:

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
! grep -rn -- "-m pytest" plugins/superb/skills/pipeline-auto plugins/superb/agents/pipeline-auto-brain.md plugins/superb/agents/pipeline-auto-intent-reader.md
! grep -rn -- "/home/" plugins/superb/skills/pipeline-auto plugins/superb/agents/pipeline-auto-brain.md plugins/superb/agents/pipeline-auto-intent-reader.md
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

The fourth command must print **nothing**: any output means `skills/pipeline/`
was modified and the phase fails. The fifth must also print nothing.

`! grep` inverts the exit status so a match fails the command — a plain `grep`
that finds nothing exits 1 and would fail the suite for the wrong reason.

**The discovery command in this tuple was executed in this repository before
being written down**, against a throwaway hyphenated-directory fixture: the bare
form runs, `-t .` raises `ImportError: Start directory is not importable`, and
repeated `-k A -k B` ORs correctly. Do the same for any command added to this
tuple later.

---

## Self-review

**1. Spec coverage.** Walked every spec section against a task:

| Spec section | Where it lands |
| --- | --- |
| The rule this skill reverses | Task 12 — `SKILL.md` opening, quoting `planning.md:177-181` verbatim, with the guardrail table as its answer |
| Governing invariants 1–7 | Task 8 (1, 6), Task 7 (2, 3, 5), Task 11 (4), Task 10 (6, 7) |
| Composition / inlining | Task 3 (script provenance headers), Tasks 5–6 (prompt provenance), Task 12 (the "what this skill does not use" section) |
| Stages 01–12 | Tasks 8, 9, 10 |
| Quorum contract — admissibility, independence, payload, rungs, comparison, adoption, budget, extension, escalation, replay | Task 7 |
| Review-intensity dial, adversarial triggers, ratchet | Task 9 |
| Contradiction routing, adjudicator | Task 10 |
| Completeness proposals | Task 10 |
| Failure modes — drift, inflation, contradiction, cascading, depth, unbounded depth, cost | Task 7 (most), Task 2 (unbounded depth, enforced in frontmatter) |
| State schema, tracker sections, decisions grammar | Task 11 |
| Deliverables | the File Structure table |
| Recorded defaults | Task 8 (intent brief immutable), Task 7 (clustering frozen), Task 9 (worktree granularity, merge conflict hard stop), Task 10 (zero-open-findings at the master gate), Task 11 (unclassified filesystem, `scratch/` cleanliness) |
| Unknowns flagged rather than hidden | Task 7 and Task 12 both say the rung values and the budget are uncalibrated first estimates |

**Gap found and closed.** The spec's "never re-run a quorum to check" and "never
ask a brain to reconsider" were in different sections and would have landed in
different files. Both are in `references/quorum.md`, and the reconsider rule is
repeated in `prompts/brain.md`'s re-dispatch section, because that is where a
controller is standing when it is tempted.

**Second gap found and closed.** Nothing in the spec told an implementer what to
do when the plan's recorded test runner is not installed. That is exactly the
defect this build shipped in its own master plan. `references/execution.md` now
routes it as a `PLAN_CONFLICT` rather than a silent runner substitution, and
`references/planning.md` makes discovering the runner part of stage 06.

**Third gap found and closed — it changed the design, twice.** The first draft of
this plan carried the spec's phrase "read-only Bash" into `pipeline-auto-brain.md`
and then reported, honestly, that the validator could not assert it. The right
response was not to accept an unenforceable leg but to remove the tool. Reporting
it also surfaced that the identical argument applied to
`pipeline-auto-intent-reader`, and more sharply: the brain can corrupt the
record, the intent reader corrupts the anchor every later citation rests on, and
an anchor corruption is invisible downstream because the citations still resolve.

Both agents now declare exactly `{Read, Grep, Glob}`. Both are asserted as exact
sets, in **two separate test classes** rather than one loop — a loop over an
empty or shortened list passes silently. No tool boundary in this skill is
prose-only, and the section *Why this phase has almost no tests* says so plainly
rather than leaving a retired concession that reads like a known hole.

**Placeholder scan.** No TBDs. Every file is present in full, not described.
Every prompt lists its complete placeholder set with the source of each value.
No step says "similar to Task N".

**Type and name consistency.** `review_class` throughout — never `review_gate`,
which is v2's name. `pipeline-auto-phase` / `pipeline-auto-task` metadata
comments, never `pipeline-v2-*`. `reserve_task` in Task 9 matches P04's produced
name (v2's `start_task` is not used). `adversarial_required` returns a trigger
name, so the prose says "returns a trigger", never "returns true".
`publish_immutable` returns a digest, stated once in Task 11 and nowhere
contradicted. `Decision action` vocabulary is the five-value set in Task 11 and
is not restated with a different membership anywhere else.

**Test-count honesty.** One test module, and the section "Why this phase has
almost no tests" argues against adding more. That section is the deliverable it
looks like a gap in.

---

## Resolved by the coordinator — recorded so the reasoning travels

Eight items were reported from this plan's first draft. All eight are settled;
they are kept here because a later reader will otherwise re-open them.

1. **`templates/worker-result.md` and `verification-evidence.md` are P04's.**
   P07 does not create them. `tests/test_skill_structure.py` keeps asserting that
   **all eight** master-plan templates exist, so a gap in any phase fails loudly
   here rather than shipping silently.
2. **`templates/decisions.md` is P02's**, not P07's, despite
   `phase-03-quorum-contract.md:67` calling it P07's. P07 creates no
   `decisions.md` template.
3. **`scripts/sdd-workspace` is P02's.** It was moved there because P05's
   per-task gate needs it before P07 exists. P07 ships **two** scripts —
   `task-brief` and `review-package` — and documents the third. The master plan's
   phase table saying "three inlined scripts" is superseded by its own
   self-review.
4. **Both agents' tool sets are `{Read, Grep, Glob}` — `Bash` removed from
   each.** This changed the design rather than merely resolving a question. The
   reasoning is written into both agent files, `references/quorum.md` (*Why both
   agents have exactly three tools*), `SKILL.md` and the validator's comments:
   frontmatter allowlists tools and not commands, so "read-only Bash" is not
   something the platform can grant. The brain with a shell can rewrite the audit
   trail it is voting into; the intent reader with a shell can rewrite the anchor
   every later `consistent_with` citation rests on, and that corruption is
   invisible downstream because the citations still resolve. Each boundary went
   from three legs enforced and one asking nicely, to four enforced.

   Asserted as **exact sets in two separate test classes**, never one loop. The
   general principle — an exact-set assertion fails on a tool nobody thought to
   forbid; a blacklist only fails on the ones somebody remembered — is promoted
   into `references/quorum.md` as prose, because it is a lesson about writing
   security boundaries rather than a note about this test.
5. **No agent registration step exists or is needed.** `plugins/superb/agents/`
   is discovered by directory; `plugin.json` carries no `agents` array, and the
   two existing agents are picked up the same way. The validator asserts file
   existence, which is the real contract.
6. **`model: opus` for both agents**, from the most-capable-model policy the dial
   may never switch off.
7. **`examples/controller_walkthrough.py` is P09's**, and P09 adds the paragraph
   about it to `references/persistence.md`. Leaving it out here was correct: this
   phase's own validator would have flagged it as a dead route.
8. **P01's curated RED baseline is
   `plugins/superb/skills/pipeline-auto/tests/pressure/RED-baseline.md`**, used
   by Task 12. `scoring.md` is deliberately uncommitted and is not it.

---

## Unresolved — reported, not invented

**None.** Every item this plan raised has been answered by the coordinator and
folded into the tasks above.

The one that mattered is recorded rather than quietly absorbed: this plan's first
draft reported that "read-only Bash" could not be enforced, and reported it
instead of inventing a fix. That report is what turned an unenforceable line in
the spec into a narrowed tool set on **both** agents, and then into two exact-set
assertions. A phase worker that had guessed — either by silently dropping the
tool or by silently keeping it and writing a test around the gap — would have
produced a plan that looked complete and shipped a hole.

**A later worker finding something this plan does not settle should do the same
thing: report it here, and do not invent it.**

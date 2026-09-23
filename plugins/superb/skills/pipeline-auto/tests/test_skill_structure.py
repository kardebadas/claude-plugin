"""Structure validator for superb:pipeline-auto.

Prose carries no unit-testable fault, so this is the only mechanical test
phase 07 owns. It asserts that the skill's routing surface is intact.

Named faults it catches:

1. A reference, prompt, template, agent or script renamed or moved without
   updating SKILL.md's routing table. Nothing fails at author time; the
   dead route surfaces at runtime, mid-run, when the controller opens the
   reference for the active stage. No other test catches it.
2. An agent's tool allowlist widened. A brain with Write -- or with Bash,
   which is Write with extra steps -- can edit decisions.md and the audit
   trail is worthless; a brain with Agent can spawn and the
   depth-1-by-construction guarantee is gone. The intent reader with any of
   them can rewrite the anchor every later consistent_with citation rests on.
   The frontmatter is the enforcement point, so the frontmatter is what gets
   asserted: the exact tool set, and the exact set of frontmatter keys, since
   a key such as `hooks:` or `mcpServers:` grants capability without touching
   `tools:`.

This module is RED by design until phase 07's last task lands: it was written
against the whole teaching surface before that surface exists, so each later
task is measured by which of these tests it turns green.

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
REQUIRED_PROMPTS = ("implementer", "task-reviewer", "adversarial-reviewer", "brain",
                    "brain-proposal")
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
# these names: a blacklist only fails on the tools somebody remembered. This
# list exists only to make the failure message name the guarantee destroyed.
FORBIDDEN_AGENT_TOOLS = (
    "Agent", "Task", "Bash", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "AskUserQuestion",
)

# The only frontmatter keys either boundary agent may declare, each once.
# `tools:` is not the only capability-bearing key: `hooks:` runs commands,
# `mcpServers:` adds tools, `permissionMode:` changes what a tool may do. An
# exact key set fails on the key nobody thought of, for the same reason the
# tool set is exact. A duplicated key is refused too: which of two `tools:`
# lines the platform honours is not something this test can know.
AGENT_FRONTMATTER_KEYS = ("color", "description", "model", "name", "tools")

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
BACKTICK_PATH = re.compile(
    r"`((?:references|prompts|templates|scripts)/[A-Za-z0-9._-]+)`"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def frontmatter_keys(raw: str) -> list:
    """Top-level keys in document order, duplicates kept."""
    return [
        line.partition(":")[0].strip()
        for line in raw.splitlines()
        if line[:1].strip() and ":" in line
    ]


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


def referenced_paths(source: Path) -> dict:
    """Every path `source` points at, resolved, mapped to how it was written.

    A markdown link resolves against the file that contains it, as a reader
    following it would. A backticked `references/...`-style path is the
    skill's own convention for naming a file and resolves against the skill
    root wherever it appears.
    """
    text = read(source)
    found = {}
    for target in MARKDOWN_LINK.findall(text):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target):
            continue  # http:, https:, mailto: ...
        found[(source.parent / target).resolve()] = target
    for target in BACKTICK_PATH.findall(text):
        found[(SKILL / target).resolve()] = target
    return found


def prose_files() -> list:
    return [SKILL_MD] + sorted((SKILL / "references").glob("*.md"))


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
        self.assertIsNotNone(raw, "SKILL.md has no YAML frontmatter block")
        self.assertLessEqual(len(raw), FRONTMATTER_MAX)


class RoutingTable(unittest.TestCase):
    """Every route named in SKILL.md resolves, and every reference is routed."""

    def test_every_required_reference_exists(self):
        for name in REQUIRED_REFERENCES:
            with self.subTest(reference=name):
                self.assertTrue((SKILL / "references" / f"{name}.md").is_file())

    def test_skill_md_routes_every_required_reference(self):
        # The router shape. Checked against the required list, not against
        # what is on disk: iterating an empty or missing references/ passes
        # vacuously, and a router that routes nowhere is not a router.
        routed = referenced_paths(SKILL_MD)
        for name in REQUIRED_REFERENCES:
            with self.subTest(reference=name):
                self.assertIn((SKILL / "references" / f"{name}.md").resolve(), routed,
                              f"SKILL.md routes nothing to references/{name}.md")

    def test_every_path_named_in_skill_md_resolves(self):
        for path, written in sorted(referenced_paths(SKILL_MD).items()):
            with self.subTest(target=written):
                self.assertTrue(path.exists(), f"dead route: {written}")

    def test_every_reference_on_disk_is_routed_from_skill_md(self):
        routed = referenced_paths(SKILL_MD)
        for path in sorted((SKILL / "references").glob("*.md")):
            with self.subTest(reference=path.name):
                self.assertIn(path.resolve(), routed,
                              f"{path.name} exists but SKILL.md routes nothing to it")

    def test_every_path_named_in_a_reference_resolves(self):
        for reference in sorted((SKILL / "references").glob("*.md")):
            for path, written in sorted(referenced_paths(reference).items()):
                with self.subTest(reference=reference.name, target=written):
                    self.assertTrue(path.exists(),
                                    f"dead route in {reference.name}: {written}")


class Prompts(unittest.TestCase):
    def test_every_required_prompt_exists(self):
        for name in REQUIRED_PROMPTS:
            with self.subTest(prompt=name):
                self.assertTrue((SKILL / "prompts" / f"{name}.md").is_file())

    def test_every_prompt_is_referenced_by_some_prose_file(self):
        routed = {}
        for source in prose_files():
            routed.update(referenced_paths(source))
        for name in REQUIRED_PROMPTS:
            with self.subTest(prompt=name):
                self.assertIn((SKILL / "prompts" / f"{name}.md").resolve(), routed,
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
        prose = "".join(read(path) for path in prose_files())
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


def assert_boundary_frontmatter(case, path):
    """Exact key set, each key once, and `name:` equal to the file stem.

    The name is what the controller dispatches by. An agent whose `name:`
    drifts from its file is either undispatchable or shadowed by whichever
    file does carry that name -- and that file's tools are not asserted here.
    """
    raw, fields, _ = split_frontmatter(read(path))
    case.assertIsNotNone(raw, f"{path.name} has no frontmatter block")
    keys = frontmatter_keys(raw)
    case.assertEqual(len(keys), len(set(keys)), f"{path.name} repeats a key: {keys}")
    case.assertEqual(tuple(sorted(keys)), AGENT_FRONTMATTER_KEYS,
                     f"{path.name} frontmatter keys changed; a new key can grant "
                     f"capability without touching tools:")
    case.assertEqual(fields.get("name"), path.stem)


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

    def test_brain_frontmatter_grants_nothing_beyond_tools(self):
        assert_boundary_frontmatter(self, BRAIN_AGENT)


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

    def test_intent_reader_frontmatter_grants_nothing_beyond_tools(self):
        assert_boundary_frontmatter(self, INTENT_READER_AGENT)


if __name__ == "__main__":
    unittest.main()

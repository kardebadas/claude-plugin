#!/usr/bin/env python3
"""Structural checks for the Superb plugin.

The Pipeline v2 state helper owns tracker parsing and state semantics. This
repository gate deliberately checks only the plugin's shared release structure
and the small Pipeline v2 inventory/version/CI contract.
"""

import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parent.parent

# Default mode is the only supported interface. In particular, retired v1
# ``--run`` input is rejected before any repository or fixture file is read.
if sys.argv[1:]:
    print(f"unknown argument {sys.argv[1]!r}; usage: check-plugin.py")
    sys.exit(2)

FAIL: list[str] = []


def ok(message: str) -> None:
    print(f"  ok    {message}")


def bad(message: str) -> None:
    print(f"  FAIL  {message}")
    FAIL.append(message)


def read(path: pathlib.Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError as error:
        return None, (
            f"not valid UTF-8 ({error.reason} at byte {error.start})"
        )
    except OSError as error:
        return None, str(error)


def frontmatter(path: pathlib.Path) -> tuple[dict[str, str] | None, str | None]:
    """Parse the repository's intentionally narrow frontmatter contract."""

    text, error = read(path)
    if error:
        return None, error
    assert text is not None
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, "no frontmatter: first line is not '---'"
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None, "frontmatter opened but never closed"

    result: dict[str, str] = {}
    key: str | None = None
    for number, line in enumerate(lines[1:end], start=2):
        if "\t" in line:
            return None, (
                f"line {number}: tab character (not valid YAML indentation)"
            )
        if not line.strip():
            continue
        if line[0] == " ":
            if key is None:
                return None, f"line {number}: indented line before any key"
            result[key] += " " + line.strip()
            continue
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*): *(.*)$", line)
        if not match:
            return None, f"line {number}: not a 'key: value' pair -> {line[:60]!r}"
        key, value = match.group(1), match.group(2).strip()
        if key in result:
            return None, f"line {number}: duplicate key {key!r}"
        if value[:1] in "*&":
            return None, (
                f"line {number}: YAML anchor/alias in {key!r} is not supported here"
            )
        if value[:1] in "|>":
            return None, (
                f"line {number}: block scalar in {key!r} is not supported here"
            )
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result, None


def mentions(text: str, token: str) -> bool:
    """Match a whole skill token, not a prefix such as bug in bug-fix."""

    return re.search(re.escape(token) + r"(?![\w-])", text) is not None


print("== shared brief ==")
agent_brief = ROOT / "plugins/superb/agents/bug-investigator.md"
skill_brief = ROOT / "plugins/superb/skills/bug-fix/references/investigator.md"


def brief(path: pathlib.Path) -> tuple[str | None, str | None]:
    text, error = read(path)
    if error:
        return None, error
    assert text is not None
    match = re.search(
        r"<!-- SHARED BRIEF: begin -->(.*?)<!-- SHARED BRIEF: end -->",
        text,
        re.S,
    )
    return (match.group(1) if match else None), None


if not (agent_brief.exists() and skill_brief.exists()):
    bad("shared-brief files missing")
else:
    agent_text, agent_error = brief(agent_brief)
    skill_text, skill_error = brief(skill_brief)
    if agent_error or skill_error:
        bad(f"cannot read shared brief: {agent_error or skill_error}")
    elif agent_text is None:
        bad(f"no SHARED BRIEF markers in {agent_brief.relative_to(ROOT)}")
    elif skill_text is None:
        bad(f"no SHARED BRIEF markers in {skill_brief.relative_to(ROOT)}")
    elif not agent_text.strip():
        bad("SHARED BRIEF block is empty")
    elif agent_text != skill_text:
        bad("brief has drifted between the agent and the skill reference")
    else:
        ok(f"brief identical and non-empty ({len(agent_text.splitlines())} lines)")


print("== manifests ==")
manifests: dict[str, dict] = {}
manifest_paths = (
    ("claude", "plugins/superb/.claude-plugin/plugin.json"),
    ("codex", "plugins/superb/.codex-plugin/plugin.json"),
    ("market", ".claude-plugin/marketplace.json"),
    ("agents", ".agents/plugins/marketplace.json"),
)
for label, relative in manifest_paths:
    text, error = read(ROOT / relative)
    if error:
        bad(f"{relative}: {error}")
        continue
    try:
        manifests[label] = json.loads(text)
        ok(f"{relative} parses")
    except (TypeError, json.JSONDecodeError) as error:
        bad(f"{relative} does not parse: {error}")

if {"claude", "codex", "market", "agents"} <= manifests.keys():
    claude_version = manifests["claude"].get("version")
    codex_version = manifests["codex"].get("version")
    if claude_version and claude_version == codex_version:
        ok(f"both manifests at {claude_version}")
    else:
        bad(
            "version drift or missing: "
            f"claude={claude_version!r} codex={codex_version!r}"
        )

    claude_name = manifests["claude"].get("name")
    codex_name = manifests["codex"].get("name")
    plugin_dirs = sorted(
        path.name for path in (ROOT / "plugins").iterdir() if path.is_dir()
    )
    names = {"claude": claude_name, "codex": codex_name}
    for label in ("market", "agents"):
        entries = manifests[label].get("plugins") or []
        if not entries:
            bad(f"{label} marketplace lists no plugins")
        for entry in entries:
            names[f"{label}:{entry.get('name')}"] = entry.get("name")
            source = entry.get("source")
            source_path = source.get("path") if isinstance(source, dict) else source
            if not source_path:
                bad(f"{label} entry {entry.get('name')!r} has no source path")
            elif not (ROOT / str(source_path).lstrip("./")).is_dir():
                bad(
                    f"{label} entry {entry.get('name')!r} source "
                    f"{source_path!r} is not a directory"
                )
    distinct_names = {value for value in names.values() if value}
    if len(distinct_names) != 1:
        bad(
            "namespace prefix disagrees across manifests/marketplaces: "
            f"{sorted(distinct_names)}"
        )
    elif claude_name not in plugin_dirs:
        bad(
            f"prefix {claude_name!r} matches no directory under plugins/ "
            f"({plugin_dirs})"
        )
    else:
        ok(
            f"namespace prefix {claude_name!r} agrees across all four manifests "
            "and the directory"
        )
    for directory in plugin_dirs:
        if directory not in distinct_names:
            bad(f"plugins/{directory}/ exists but is in no marketplace manifest")

    skills_path = manifests["codex"].get("skills")
    if not skills_path:
        bad("codex manifest has no 'skills' key")
    elif not (ROOT / "plugins/superb" / str(skills_path).lstrip("./")).is_dir():
        bad(f"codex manifest 'skills': {skills_path!r} does not exist")
    else:
        ok(f"codex skills path {skills_path!r} exists")


print("== skills ==")
surfaces: dict[str, str] = {}
if {"claude", "codex", "market"} <= manifests.keys():
    surfaces = {
        "claude description": manifests["claude"].get("description") or "",
        "claude keywords": " ".join(manifests["claude"].get("keywords") or []),
        "codex description": manifests["codex"].get("description") or "",
        "codex longDescription": (
            (manifests["codex"].get("interface") or {}).get("longDescription") or ""
        ),
        "marketplace description": json.dumps(manifests["market"]),
    }
root_readme, _ = read(ROOT / "README.md")
plugin_readme, _ = read(ROOT / "plugins/superb/README.md")
skills_dir = ROOT / "plugins/superb/skills"
skill_names: list[str] = []
if not skills_dir.is_dir():
    bad("plugins/superb/skills/ does not exist")
else:
    for directory in sorted(skills_dir.iterdir()):
        if not directory.is_dir():
            continue
        name = directory.name
        skill_names.append(name)
        skill_file = directory / "SKILL.md"
        if not skill_file.exists():
            bad(f"{name} has no SKILL.md")
            continue
        metadata, error = frontmatter(skill_file)
        if error:
            bad(f"{name}/SKILL.md frontmatter: {error}")
        elif metadata.get("name") != name:
            bad(
                f"{name}: frontmatter name {metadata.get('name')!r} != directory"
            )
        elif not metadata.get("description"):
            bad(f"{name}: no description — it will never trigger")
        else:
            ok(f"{name}: frontmatter valid")

        readme = directory / "README.md"
        readme_text, readme_error = read(readme)
        if readme_error:
            bad(f"{name}/README.md: {readme_error}")
        elif len(set(readme_text.split())) < 20:
            bad(f"{name}/README.md has almost no distinct content")

        for script in sorted(directory.rglob("*.sh")):
            if not script.stat().st_mode & 0o111:
                bad(
                    f"{name}: {script.relative_to(ROOT)} is not executable — "
                    "the skill cannot run it"
                )
        for where, text in (
            ("root README", root_readme or ""),
            ("plugin README", plugin_readme or ""),
        ):
            if not mentions(text, f"superb:{name}"):
                bad(f"{name} missing from the {where}")
        for label, text in surfaces.items():
            if not mentions(text, name):
                bad(f"{name} missing from the {label}")


print("== skill invocation ==")
invocation_failures = len(FAIL)
namespace_pattern = (
    re.compile(
        r"(?<![\w:/.])/(" + "|".join(map(re.escape, skill_names)) + r")(?![\w/-])"
    )
    if skill_names
    else None
)
for name in skill_names:
    skill_text, error = read(skills_dir / name / "SKILL.md")
    if error is None:
        flat = " ".join(skill_text.split())
        indexed = re.search(
            r"[Dd]ispatch on [^.]{0,40}?(?<!\\)((?:\\\\)*)(\$\d)", flat
        )
        if indexed:
            escapes, placeholder = indexed.group(1), indexed.group(2)
            suffix = " (an even number of backslashes escapes nothing)" if escapes else ""
            bad(
                f"{name}/SKILL.md dispatches on {escapes}{placeholder}; an indexed "
                "placeholder with no argument at its position stays literal, so a "
                f"bare invocation leaks it into the prompt — dispatch on $ARGUMENTS{suffix}"
            )
    for markdown in sorted((skills_dir / name).rglob("*.md")):
        text, error = read(markdown)
        if error:
            continue
        for match in namespace_pattern.finditer(text) if namespace_pattern else ():
            relative = markdown.relative_to(skills_dir).as_posix()
            bad(
                f"{relative} writes {match.group(0)!r} un-namespaced; use "
                f"/superb:{match.group(1)} — unless the sentence is ABOUT the "
                "unprefixed form, in which case paraphrase it"
            )
if len(FAIL) == invocation_failures:
    ok("no indexed-placeholder dispatch and all invocations are namespaced")


print("== agents ==")
agents_dir = ROOT / "plugins/superb/agents"
agent_files = sorted(agents_dir.glob("*.md")) if agents_dir.is_dir() else []
if not agent_files:
    ok("no bundled agents")
for agent in agent_files:
    metadata, error = frontmatter(agent)
    if error:
        bad(f"{agent.name} frontmatter: {error}")
    elif metadata.get("name") != agent.stem:
        bad(
            f"{agent.name}: frontmatter name {metadata.get('name')!r} != filename"
        )
    elif not metadata.get("description"):
        bad(f"{agent.name}: no description — it loads unnamed and will not be selected")
    else:
        ok(f"{agent.stem}: frontmatter valid")


print("== ci wiring ==")
workflow = ROOT / ".github/workflows/checks.yml"
workflow_text, workflow_error = read(workflow)
if workflow_error:
    bad(f"checks.yml: {workflow_error}")
else:
    script_refs = re.findall(r"run: (\./tools/\S+)", workflow_text)
    if not script_refs:
        bad("checks.yml runs no ./tools/ script")
    for script_ref in script_refs:
        script_path = ROOT / script_ref.lstrip("./")
        if not script_path.exists():
            bad(f"checks.yml runs {script_ref} which does not exist")
        elif not script_path.stat().st_mode & 0o111:
            bad(f"checks.yml runs {script_ref} which is not executable")
    for required in ("tools/check-plugin.sh", "tools/check-plugin-mutants.sh"):
        if not any(required in reference for reference in script_refs):
            bad(f"checks.yml does not run {required}")

    ci_fragments = (
        "uses: actions/setup-python@v5",
        "python-version: '3.11'",
        "python -m unittest discover -s plugins/superb/skills/pipeline/tests -v",
    )
    positions = [workflow_text.find(fragment) for fragment in ci_fragments]
    for fragment, position in zip(ci_fragments, positions):
        if position < 0:
            bad(f"Pipeline v2 CI contract is missing: {fragment}")
    if all(position >= 0 for position in positions) and positions != sorted(positions):
        bad("Pipeline v2 CI fragments are not in the required order")
    if re.search(r"check-plugin\.sh\s+--run(?:\s|$)", workflow_text):
        bad("checks.yml still invokes retired check-plugin.sh --run")


print("== no personal leakage ==")
personal_pattern = re.compile(
    r"/home/[a-z0-9_-]+/|audio-chat-app|agent-memory|MIPS-[0-9X]|HIPAA"
    r"|tools/build|extension/src",
    re.I,
)
leaks: list[str] = []
for path in (ROOT / "plugins").rglob("*"):
    if (
        not path.is_file()
        or path.suffix not in {".md", ".json", ".py", ".html", ".sh", ".txt"}
        or "__pycache__" in path.parts
    ):
        continue
    text, error = read(path)
    if error:
        bad(f"{path.relative_to(ROOT)}: {error}")
        continue
    leaks.extend(
        f"{path.relative_to(ROOT)}:{number}"
        for number, line in enumerate(text.split("\n"), start=1)
        if personal_pattern.search(line)
    )
if leaks:
    bad("personal paths or foreign conventions: " + ", ".join(leaks[:8]))
else:
    ok("no absolute home paths, private project names, or foreign ticket prefixes")


print("== run artifacts are ignored ==")
gitignore = ROOT / ".gitignore"
ignore_lines = [
    line.strip()
    for line in (gitignore.read_text(encoding="utf-8") if gitignore.exists() else "").split("\n")
    if line.strip() and not line.strip().startswith("#")
]
if any(
    re.fullmatch(r"/?docs/superpowers/runs/(?:\*{1,2}/|\*/\*{1,2})", line)
    for line in ignore_lines
):
    ok("`.gitignore` covers pipeline run directories")
else:
    bad("`.gitignore` carries no narrow docs/superpowers/runs/*/ rule")
wide_ignores = [
    line
    for line in ignore_lines
    if re.match(r"^/?docs/superpowers/?$", line)
    or re.fullmatch(r"/?docs/superpowers/\*{1,2}/?", line)
    or re.fullmatch(r"/?docs/superpowers/runs/\*\*(?:/\*{1,2})?", line)
    or re.match(r"^/?docs/superpowers/runs/?$", line)
    or re.match(r"^/?docs/superpowers/runs/\*$", line)
]
if wide_ignores:
    bad(
        f"`.gitignore` carries {wide_ignores[0]!r}, which also hides curated "
        "specs, plans, or loose runs/*.md records"
    )
else:
    ok("`.gitignore` leaves curated specs, plans and loose runs/*.md trackable")


print("== pipeline v2 release structure ==")
required_pipeline_paths = (
    "plugins/superb/skills/pipeline/SKILL.md",
    "plugins/superb/skills/pipeline/README.md",
    "plugins/superb/skills/pipeline/references/planning.md",
    "plugins/superb/skills/pipeline/references/execution.md",
    "plugins/superb/skills/pipeline/references/persistence.md",
    "plugins/superb/skills/pipeline/references/review.md",
    "plugins/superb/skills/pipeline/scripts/pipeline_state.py",
    "plugins/superb/skills/pipeline/templates/progress.md",
    "plugins/superb/skills/pipeline/templates/decisions.md",
    "plugins/superb/skills/pipeline/templates/findings.md",
    "plugins/superb/skills/pipeline/templates/fix-plan.md",
    "plugins/superb/skills/pipeline/templates/worker-result.md",
    "plugins/superb/skills/pipeline/tests/test_pipeline_state.py",
    "plugins/superb/skills/pipeline/tests/fixtures",
)
for relative in required_pipeline_paths:
    if (ROOT / relative).exists():
        ok(f"required Pipeline v2 path exists: {relative}")
    else:
        bad(f"required Pipeline v2 path is missing: {relative}")

for label in ("claude", "codex"):
    if label in manifests and manifests[label].get("version") != "0.14.0":
        bad(f"{label} manifest must identify Pipeline v2 as version 0.14.0")

progress_text, progress_error = read(
    ROOT / "plugins/superb/skills/pipeline/templates/progress.md"
)
if progress_error:
    bad(f"Pipeline v2 progress template cannot be read: {progress_error}")
elif "pipeline-run/v2" not in progress_text:
    bad("Pipeline v2 progress template is missing marker pipeline-run/v2")


print()
print("check-plugin: FAIL" if FAIL else "check-plugin: PASS")
sys.exit(1 if FAIL else 0)

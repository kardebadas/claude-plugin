#!/usr/bin/env python3
"""Structural checks for the superb plugin.

`claude plugin validate --strict` passes on a plugin containing a deliberately
malformed agent file, so it is not a safety net for any of this. These are the
invariants nothing else enforces.
"""
import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FAIL = []

def ok(m):  print(f"  ok    {m}")
def bad(m): print(f"  FAIL  {m}"); FAIL.append(m)

def frontmatter(path):
    """Return (dict, error). Parses only the block between the first two '---'."""
    lines = path.read_text().split("\n")
    if not lines or lines[0].strip() != "---":
        return None, "no frontmatter: first line is not '---'"
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None, "frontmatter opened but never closed"
    out, key = {}, None
    for i, ln in enumerate(lines[1:end], start=2):
        if not ln.strip():
            continue
        if ln[0] in " \t":                      # continuation of the previous key
            if key is None:
                return None, f"line {i}: indented line before any key"
            out[key] += " " + ln.strip()
            continue
        m = re.match(r'^([A-Za-z][A-Za-z0-9_-]*): *(.*)$', ln)
        if not m:
            return None, f"line {i}: not a 'key: value' pair -> {ln[:60]!r}"
        key, val = m.group(1), m.group(2).strip()
        out[key] = val
    return out, None

print("== shared brief ==")
A = ROOT/"plugins/superb/agents/bug-investigator.md"
B = ROOT/"plugins/superb/skills/bug-fix/references/investigator.md"
def brief(p):
    m = re.search(r"<!-- SHARED BRIEF: begin -->(.*?)<!-- SHARED BRIEF: end -->", p.read_text(), re.S)
    return m.group(1) if m else None
if not (A.exists() and B.exists()):
    bad("shared-brief files missing")
else:
    a, b = brief(A), brief(B)
    if a is None: bad(f"no SHARED BRIEF markers in {A.relative_to(ROOT)}")
    elif b is None: bad(f"no SHARED BRIEF markers in {B.relative_to(ROOT)}")
    elif not a.strip(): bad("SHARED BRIEF block is empty")
    elif a != b: bad("brief has drifted between the agent and the skill reference")
    else: ok(f"brief identical and non-empty ({len(a.splitlines())} lines)")

print("== manifests ==")
mans = {}
for label, rel in [("claude", "plugins/superb/.claude-plugin/plugin.json"),
                   ("codex",  "plugins/superb/.codex-plugin/plugin.json"),
                   ("market", ".claude-plugin/marketplace.json"),
                   ("agents",  ".agents/plugins/marketplace.json")]:
    try:
        mans[label] = json.loads((ROOT/rel).read_text()); ok(f"{rel} parses")
    except Exception as e:
        bad(f"{rel} does not parse: {e}")

if {"claude", "codex", "market"} <= mans.keys():
    cv, xv = mans["claude"].get("version"), mans["codex"].get("version")
    if cv and cv == xv: ok(f"both manifests at {cv}")
    else: bad(f"version drift or missing: claude={cv!r} codex={xv!r}")
    cn, xn = mans["claude"].get("name"), mans["codex"].get("name")
    entries = [p.get("name") for p in mans["market"].get("plugins", [])]
    plugin_dirs = [d.name for d in (ROOT/"plugins").iterdir() if d.is_dir()]
    if not cn: bad("claude manifest has no name")
    elif cn != xn: bad(f"name drift: claude={cn!r} codex={xn!r}")
    elif cn not in entries: bad(f"name {cn!r} is not a plugin in the marketplace manifest ({entries})")
    elif cn not in plugin_dirs: bad(f"name {cn!r} does not match a directory under plugins/ ({plugin_dirs})")
    else: ok(f"namespace prefix {cn!r} agrees across both manifests, the marketplace and the directory")
    sk = mans["codex"].get("skills")
    if sk and not (ROOT/"plugins/superb"/sk.lstrip("./")).is_dir():
        bad(f"codex manifest 'skills': {sk!r} does not exist")
    elif sk: ok(f"codex skills path {sk!r} exists")

print("== skills ==")
root_readme = (ROOT/"README.md").read_text()
plug_readme = (ROOT/"plugins/superb/README.md").read_text()
market_desc = json.dumps(mans.get("market", {}))
for d in sorted((ROOT/"plugins/superb/skills").iterdir()):
    if not d.is_dir(): continue
    n = d.name
    sk = d/"SKILL.md"
    if not sk.exists(): bad(f"{n} has no SKILL.md"); continue
    fm, err = frontmatter(sk)
    if err: bad(f"{n}/SKILL.md frontmatter: {err}"); continue
    if fm.get("name") != n:
        bad(f"{n}: frontmatter name {fm.get('name')!r} != directory (namespace would be superb:{fm.get('name')})")
    elif not fm.get("description"):
        bad(f"{n}: frontmatter has no description — it will never trigger")
    else:
        ok(f"{n}: frontmatter name and description present")
    rd = d/"README.md"
    if not rd.exists(): bad(f"{n} has no README.md")
    elif len(rd.read_text().strip()) < 80: bad(f"{n}/README.md is effectively empty")
    for where, txt in (("root README", root_readme), ("plugin README", plug_readme)):
        if f"superb:{n}" not in txt: bad(f"{n} missing from the {where}")
    if n not in market_desc: bad(f"{n} missing from the marketplace description")

print("== agents ==")
adir = ROOT/"plugins/superb/agents"
files = sorted(adir.glob("*.md")) if adir.is_dir() else []
if not files: ok("no bundled agents")
for f in files:
    fm, err = frontmatter(f)
    if err: bad(f"{f.name} frontmatter: {err}"); continue
    if fm.get("name") != f.stem: bad(f"{f.name}: frontmatter name {fm.get('name')!r} != filename")
    elif not fm.get("description"):
        bad(f"{f.name}: no description — it loads as 'Agent from superb plugin' and will not be selected")
    else: ok(f"{f.stem}: frontmatter name and description present")

print("== no personal leakage ==")
pat = re.compile(r"/home/[a-z0-9_-]+/|audio-chat-app|agent-memory|MIPS-[0-9X]|HIPAA", re.I)
hits = [f"{p.relative_to(ROOT)}:{i}" for p in (ROOT/"plugins/superb").rglob("*")
        if p.is_file() and p.suffix in {".md", ".json"}
        for i, l in enumerate(p.read_text(errors="ignore").split("\n"), 1) if pat.search(l)]
if hits: bad("personal paths or foreign conventions: " + ", ".join(hits[:8]))
else: ok("no absolute home paths, private project names, or foreign ticket prefixes")

print()
print("check-plugin: FAIL" if FAIL else "check-plugin: PASS")
sys.exit(1 if FAIL else 0)

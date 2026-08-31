#!/usr/bin/env python3
"""Structural checks for the superb plugin.

`claude plugin validate --strict` passes on a plugin containing a deliberately
malformed agent file, so it is not a safety net for any of this.

Frontmatter contract: plugin frontmatter is deliberately restricted to simple
`key: value` pairs with optional space-indented continuations. Anchors, aliases,
tabs, block scalars and duplicate keys are REJECTED rather than interpreted —
PyYAML is not guaranteed present, and silently accepting what we cannot parse is
exactly the failure this file exists to prevent.

Run tools/check-plugin-mutants.sh to verify this gate can still fail.
"""
import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FAIL = []
def ok(m):  print(f"  ok    {m}")
def bad(m): print(f"  FAIL  {m}"); FAIL.append(m)

def read(p):
    try:
        return p.read_text(encoding="utf-8"), None
    except UnicodeDecodeError as e:
        return None, f"not valid UTF-8 ({e.reason} at byte {e.start})"
    except OSError as e:
        return None, str(e)

def frontmatter(path):
    text, err = read(path)
    if err: return None, err
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, "no frontmatter: first line is not '---'"
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None, "frontmatter opened but never closed"
    out, key = {}, None
    for i, ln in enumerate(lines[1:end], start=2):
        if "\t" in ln:
            return None, f"line {i}: tab character (not valid YAML indentation)"
        if not ln.strip():
            continue
        if ln[0] == " ":
            if key is None: return None, f"line {i}: indented line before any key"
            out[key] += " " + ln.strip(); continue
        m = re.match(r'^([A-Za-z][A-Za-z0-9_-]*): *(.*)$', ln)
        if not m:
            return None, f"line {i}: not a 'key: value' pair -> {ln[:60]!r}"
        key, val = m.group(1), m.group(2).strip()
        if key in out:
            return None, f"line {i}: duplicate key {key!r}"
        if val[:1] in "*&":
            return None, f"line {i}: YAML anchor/alias in {key!r} is not supported here"
        if val[:1] in "|>":
            return None, f"line {i}: block scalar in {key!r} is not supported here"
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key] = val
    return out, None

def mentions(text, token):
    """Whole-token match, so superb:bug does not match inside superb:bug-fix."""
    return re.search(re.escape(token) + r"(?![\w-])", text) is not None

print("== shared brief ==")
A = ROOT/"plugins/superb/agents/bug-investigator.md"
B = ROOT/"plugins/superb/skills/bug-fix/references/investigator.md"
def brief(p):
    t, e = read(p)
    if e: return None, e
    m = re.search(r"<!-- SHARED BRIEF: begin -->(.*?)<!-- SHARED BRIEF: end -->", t, re.S)
    return (m.group(1) if m else None), None
if not (A.exists() and B.exists()):
    bad("shared-brief files missing")
else:
    a, ea = brief(A); b, eb = brief(B)
    if ea or eb: bad(f"cannot read shared brief: {ea or eb}")
    elif a is None: bad(f"no SHARED BRIEF markers in {A.relative_to(ROOT)}")
    elif b is None: bad(f"no SHARED BRIEF markers in {B.relative_to(ROOT)}")
    elif not a.strip(): bad("SHARED BRIEF block is empty")
    elif a != b: bad("brief has drifted between the agent and the skill reference")
    else: ok(f"brief identical and non-empty ({len(a.splitlines())} lines)")

print("== manifests ==")
M = {}
for label, rel in [("claude","plugins/superb/.claude-plugin/plugin.json"),
                   ("codex","plugins/superb/.codex-plugin/plugin.json"),
                   ("market",".claude-plugin/marketplace.json"),
                   ("agents",".agents/plugins/marketplace.json")]:
    t, e = read(ROOT/rel)
    if e: bad(f"{rel}: {e}"); continue
    try: M[label] = json.loads(t); ok(f"{rel} parses")
    except Exception as ex: bad(f"{rel} does not parse: {ex}")

if {"claude","codex","market","agents"} <= M.keys():
    cv, xv = M["claude"].get("version"), M["codex"].get("version")
    ok(f"both manifests at {cv}") if cv and cv == xv else bad(f"version drift or missing: claude={cv!r} codex={xv!r}")
    cn, xn = M["claude"].get("name"), M["codex"].get("name")
    plugin_dirs = sorted(d.name for d in (ROOT/"plugins").iterdir() if d.is_dir())
    names = {"claude": cn, "codex": xn}
    for lbl, man in (("market", M["market"]), ("agents", M["agents"])):
        entries = man.get("plugins") or []
        if not entries: bad(f"{lbl} marketplace lists no plugins")
        for e in entries:
            names[f"{lbl}:{e.get('name')}"] = e.get("name")
            src = e.get("source")
            path = src.get("path") if isinstance(src, dict) else src
            if not path: bad(f"{lbl} entry {e.get('name')!r} has no source path")
            elif not (ROOT/str(path).lstrip("./")).is_dir():
                bad(f"{lbl} entry {e.get('name')!r} source {path!r} is not a directory")
    distinct = {v for v in names.values() if v}
    if len(distinct) != 1: bad(f"namespace prefix disagrees across manifests/marketplaces: {sorted(distinct)}")
    elif cn not in plugin_dirs: bad(f"prefix {cn!r} matches no directory under plugins/ ({plugin_dirs})")
    else: ok(f"namespace prefix {cn!r} agrees across all four manifests and the directory")
    for d in plugin_dirs:
        if d not in distinct: bad(f"plugins/{d}/ exists but is in no marketplace manifest")
    if "skills" not in M["codex"]: bad("codex manifest has no 'skills' key")
    elif not (ROOT/"plugins/superb"/str(M["codex"]["skills"]).lstrip("./")).is_dir():
        bad(f"codex manifest 'skills': {M['codex']['skills']!r} does not exist")
    else: ok(f"codex skills path {M['codex']['skills']!r} exists")

print("== skills ==")
surfaces = {}
if "claude" in M and "codex" in M and "market" in M:
    surfaces = {
        "claude description": M["claude"].get("description") or "",
        "claude keywords": " ".join(M["claude"].get("keywords") or []),
        "codex description": M["codex"].get("description") or "",
        "codex longDescription": (M["codex"].get("interface") or {}).get("longDescription") or "",
        "marketplace description": json.dumps(M["market"]),
    }
rr, _ = read(ROOT/"README.md"); pr, _ = read(ROOT/"plugins/superb/README.md")
sdir = ROOT/"plugins/superb/skills"
if not sdir.is_dir():
    bad("plugins/superb/skills/ does not exist")
else:
  for d in sorted(sdir.iterdir()):
    if not d.is_dir(): continue
    n = d.name
    if not (d/"SKILL.md").exists(): bad(f"{n} has no SKILL.md"); continue
    fm, err = frontmatter(d/"SKILL.md")
    if err: bad(f"{n}/SKILL.md frontmatter: {err}"); continue
    if fm.get("name") != n: bad(f"{n}: frontmatter name {fm.get('name')!r} != directory")
    elif not fm.get("description"): bad(f"{n}: no description — it will never trigger")
    else: ok(f"{n}: frontmatter valid")
    rd = d/"README.md"
    if not rd.exists(): bad(f"{n} has no README.md")
    else:
        t, e = read(rd)
        if e: bad(f"{n}/README.md: {e}")
        elif len(set(t.split())) < 20: bad(f"{n}/README.md has almost no distinct content")
    for sh in sorted(d.rglob("*.sh")):
        if not sh.stat().st_mode & 0o111:
            bad(f"{n}: {sh.relative_to(ROOT)} is not executable — the skill cannot run it")
    for where, txt in (("root README", rr or ""), ("plugin README", pr or "")):
        if not mentions(txt, f"superb:{n}"): bad(f"{n} missing from the {where}")
    for label, txt in surfaces.items():
        if not mentions(txt, n): bad(f"{n} missing from the {label}")

print("== agents ==")
adir = ROOT/"plugins/superb/agents"
files = sorted(adir.glob("*.md")) if adir.is_dir() else []
if not files: ok("no bundled agents")
for f in files:
    fm, err = frontmatter(f)
    if err: bad(f"{f.name} frontmatter: {err}"); continue
    if fm.get("name") != f.stem: bad(f"{f.name}: frontmatter name {fm.get('name')!r} != filename")
    elif not fm.get("description"): bad(f"{f.name}: no description — it loads unnamed and will not be selected")
    else: ok(f"{f.stem}: frontmatter valid")

print("== ci wiring ==")
wf = ROOT/".github/workflows/checks.yml"
if not wf.exists(): bad(".github/workflows/checks.yml is missing — nothing runs these checks")
else:
    t, e = read(wf)
    if e: bad(f"checks.yml: {e}")
    else:
        refs = re.findall(r"run: (\./tools/\S+)", t)
        if not refs: bad("checks.yml runs no ./tools/ script")
        for r in refs:
            p = ROOT/r.lstrip("./")
            if not p.exists(): bad(f"checks.yml runs {r} which does not exist")
            elif not p.stat().st_mode & 0o111: bad(f"checks.yml runs {r} which is not executable")
        for must in ("tools/check-plugin.sh", "tools/check-plugin-mutants.sh"):
            if not any(must in r for r in refs): bad(f"checks.yml does not run {must}")
        if not FAIL: ok(f"checks.yml runs {len(refs)} scripts, all present and executable")

print("== no personal leakage ==")
pat = re.compile(r"/home/[a-z0-9_-]+/|audio-chat-app|agent-memory|MIPS-[0-9X]|HIPAA", re.I)
hits = []
for p in (ROOT/"plugins").rglob("*"):
    if not p.is_file() or p.suffix not in {".md", ".json", ".py", ".html", ".sh", ".txt"}: continue
    if "__pycache__" in p.parts: continue
    t, e = read(p)
    if e: bad(f"{p.relative_to(ROOT)}: {e}"); continue
    hits += [f"{p.relative_to(ROOT)}:{i}" for i, l in enumerate(t.split("\n"), 1) if pat.search(l)]
if hits: bad("personal paths or foreign conventions: " + ", ".join(hits[:8]))
else: ok("no absolute home paths, private project names, or foreign ticket prefixes")

print()
print("check-plugin: FAIL" if FAIL else "check-plugin: PASS")
sys.exit(1 if FAIL else 0)

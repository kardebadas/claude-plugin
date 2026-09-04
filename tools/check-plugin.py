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

print("== skill invocation ==")
# An indexed placeholder ($0, $1, ...) IS substituted — $0 is the first positional
# argument — but one with no argument at its position is left in the prompt
# verbatim. So a dispatch table keyed on $0 renders a stray literal "$0" on a bare
# invocation, in exactly the arm it calls "no argument". $ARGUMENTS collapses to
# the empty string instead, which is what a dispatch table wants — observed on
# 2.1.261, not documented: the docs say only that it "expands to the full argument
# string as typed", so the zero-argument case is documented by implication. It is
# named here because it is why the arm prefers $ARGUMENTS, and labelled because
# rationale a gate rests on should not read as a citable rule. Caught only by
# reading the table, never by running it.
#
# The check aims at the DISPATCH INSTRUCTION, not any mention of $0: the corrected
# text has to stay free to explain why an indexed placeholder is wrong, and a
# blanket ban on the characters would fail on the sentence documenting the fix.
# The aim is approximate, and in two ways worth knowing before editing that prose:
#
#   * The window is a SENTENCE, not an instruction. "dispatch on" followed by
#     $<digit> within 40 non-period characters is enough. The corrective mention
#     therefore has to stay in a sentence of its own — join it to the dispatch
#     sentence with a comma or a dash and this arm FAILs with no hint why.
#   * Substitution is global and backticks do not stop it, so a documentation
#     mention must be BACKSLASH-ESCAPED (`\$0`) to render literally. An escaped
#     mention is harmless, so the arm exempts it — but only an ODD number of
#     backslashes escapes. `\\$0` leaves both backslashes in place and $0 still
#     expands, so a doubled backslash must still FAIL. That is why the arm is
#     (?<!\\)((?:\\\\)*) and not a bare (?<!\\): a lookbehind reads exactly one
#     character back, so on its own it exempts every even count. It shipped that
#     way for one round — the same even/odd escape trap the prose was fixed for,
#     reappearing inside the gate that guards the prose. A gate is prose too, and
#     gets the same reading. Mutant: "skill dispatches on a doubled-backslash $0".
#
# $\d, not $0: every indexed placeholder shares the defect, and a $0-only arm is
# bypassable by "fixing" the 0-based index to $1.
#
# The namespace regex must not fire on a relative path that happens to contain a
# skill name — `../bug-fix/references/investigator.md` is a file reference, not an
# invocation. Hence the leading "." in the lookbehind and the trailing "/" in the
# lookahead: an invocation is never preceded by "." nor followed by "/". The "."
# earns its place twice: it also saves the markdown link `(../pipeline)`, which
# the trailing-"/" lookahead does not.
#
# The namespace scan covers EVERY *.md in a skill directory, not just SKILL.md:
# a README or a references/ page is read by the same user and an un-namespaced
# command there is just as wrong. The dispatch-instruction scan stays on SKILL.md,
# which is the only file the harness substitutes.
#
# One sentence per skill legitimately has the unprefixed form as its SUBJECT — the
# READMEs say the prefix is optional absent a collision. There, "use /superb:x" is
# the wrong remedy: obeying it inverts the sentence into a claim the prefix is
# required, which is the bug a previous round had to undo. So the failure message
# names paraphrase as the remedy for that case; the arm stays blanket, because a
# regex cannot tell a mention from an instruction and the wider net is the safer
# error.
_inv_before = len(FAIL)
skill_names = sorted(d.name for d in sdir.iterdir() if d.is_dir()) if sdir.is_dir() else []
_ns = re.compile(r"(?<![\w:/.])/(" + "|".join(map(re.escape, skill_names)) + r")(?![\w/-])") \
      if skill_names else None
for n in skill_names:
    t, e = read(sdir / n / "SKILL.md")
    if e is None:
        flat = " ".join(t.split())
        m0 = re.search(r"[Dd]ispatch on [^.]{0,40}?(?<!\\)((?:\\\\)*)(\$\d)", flat)
        if m0:
            esc, ph = m0.group(1), m0.group(2)
            bad(f"{n}/SKILL.md dispatches on {esc}{ph}; an indexed placeholder with "
                "no argument at its position stays literal, so a bare invocation leaks "
                "it into the prompt — dispatch on $ARGUMENTS"
                + (" (an even number of backslashes escapes nothing)" if esc else ""))
        # A FOURTH severity tier reaches the ledger from OUTSIDE this skill.
        # subagent-driven-development's task reviewer emits `Important`, whose
        # contract is "fix everything before this task completes" — right for one
        # task's diff, wrong for a phase, because this skill's blocking list is
        # closed and different. In one 141-finding run, 50 findings gated phase
        # advancement under a tier that appeared NOWHERE in the skill. So the
        # skill may name the tier only alongside the sentence that re-tags it;
        # naming it without one is how the leak got in. Matched against `flat`,
        # not `t`: the rule is prose, it reflows, and a raw-text regex would stop
        # matching the first time the sentence re-wrapped — failing on the very
        # rule it exists to require. Keep the phrase in ONE sentence, since
        # whitespace normalisation does not bridge a paragraph break.
        # Mutant: "fourth severity tier named without its re-tag rule".
        if re.search(r"\bImportant\b", t) and not re.search(
                r"an incoming `?Important`? is\s+re-tagged", flat):
            bad(f"{n}/SKILL.md names a fourth severity tier (`Important`) with no "
                "re-tag rule — pipeline blocks on Critical/Major/bug only, so a tier "
                "this skill never named must be re-tagged at consolidation, not carried")
    for f in sorted((sdir / n).rglob("*.md")):
        t, e = read(f)
        if e: continue
        for m in (_ns.finditer(t) if _ns else []):
            rel = f.relative_to(sdir).as_posix()
            bad(f"{rel} writes {m.group(0)!r} un-namespaced; use /superb:{m.group(1)} — "
                "unless the sentence is ABOUT the unprefixed form, in which case "
                "paraphrase it, since prefixing it inverts the claim")
if len(FAIL) == _inv_before:
    ok("no indexed-placeholder dispatch, invocations namespaced, no unhandled fourth severity tier")

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
# Foreign project conventions leak the same way absolute home paths do: a build
# command or source tree from whichever repo the skill was last used in, frozen
# into prose that reads as universal. tools/build.sh and extension/src/ arrived
# that way.
pat = re.compile(
    r"/home/[a-z0-9_-]+/|audio-chat-app|agent-memory|MIPS-[0-9X]|HIPAA"
    r"|tools/build|extension/src",
    re.I,
)
hits = []
# Scoped to plugins/ deliberately, and load-bearing: the banned tokens appear in
# this file's own comment and pattern, and in the mutants exercising them, so
# widening this walk past plugins/ would fail the gate on its own source.
for p in (ROOT/"plugins").rglob("*"):
    if not p.is_file() or p.suffix not in {".md", ".json", ".py", ".html", ".sh", ".txt"}: continue
    if "__pycache__" in p.parts: continue
    t, e = read(p)
    if e: bad(f"{p.relative_to(ROOT)}: {e}"); continue
    hits += [f"{p.relative_to(ROOT)}:{i}" for i, l in enumerate(t.split("\n"), 1) if pat.search(l)]
if hits: bad("personal paths or foreign conventions: " + ", ".join(hits[:8]))
else: ok("no absolute home paths, private project names, or foreign ticket prefixes")

# ---- pipeline RV/RVJ examples must obey the grammar they teach ----
# The skill's gate is "one agent-output file per reviewer, counted against the
# <s> slice + <i> integration declared on that round". Every worked example must
# obey it, or the gate teaches its own violation. Each record is bounded at the
# next record so one example cannot borrow its neighbour's evidence.
# Deliberately NOT checked: the declared slice count against ceil(N/5), since a
# waved phase legitimately departs from it.
print("\n== pipeline review-line examples ==")
start = re.compile(r"(?:-\s*)?\[x\]\s*(RVJ|RV)\b|(?:->|→)\s*(round)\s+\d+\s*:")
decl  = re.compile(r"(?:N|M)=\d+\s*(?:waved\s+)?(?:->|→)\s*(\d+)\s*slice\s*\+\s*(\d+)\s*integration")
rpt   = re.compile(r"reports\s+(.+?)(?=\s*[·|]|\s+coverage\b|\s*$)")
cov   = re.compile(r"coverage\s+\S+\.md")
def nfiles(spec):
    m = re.search(r"\{([^}]*)\}", spec)
    src = m.group(1) if m else spec
    return len([x for x in src.split(",") if x.strip()])
seen = viol = 0
pdir = ROOT / "plugins" / "superb" / "skills" / "pipeline"
for f in sorted(pdir.rglob("*.md")):
    t, e = read(f)
    if e: continue
    flat, starts, off = [], [], 0
    for ln in t.split("\n"):
        starts.append(off); flat.append(ln.strip()); off += len(ln.strip()) + 1
    flat = " ".join(flat)
    def lineno(pos):
        n = 1
        for k, st in enumerate(starts, 1):
            if st <= pos: n = k
            else: break
        return n
    marks = [(m.start(), (m.group(1) or m.group(2))) for m in start.finditer(flat)]
    for idx, (pos, kind) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(flat)
        rec = flat[pos:min(end, pos + 400)]
        d = decl.search(rec)
        if not d: continue          # e.g. the WAIVED form, which carries no counts
        seen += 1
        want = int(d.group(1)) + int(d.group(2))
        where = f"{f.relative_to(ROOT)}:{lineno(pos)}"
        if kind == "RVJ" and (int(d.group(1)), int(d.group(2))) != (0, 1):
            viol += 1; bad(f"{where}: RVJ must be 0 slice + 1 integration, declares {d.group(1)}+{d.group(2)}")
        r = rpt.search(rec)
        got = nfiles(r.group(1)) if r else 0
        if got != want:
            viol += 1; bad(f"{where}: declares {want} reviewers, lists {got} report files")
        if not cov.search(rec):
            viol += 1; bad(f"{where}: closed review round with no coverage file")
if not seen: bad("no closed RV/RVJ examples found — the grammar lost its worked instances")
elif not viol: ok(f"{seen} closed review rounds: reviewer counts, RVJ shape and coverage all conform")

print()
print("check-plugin: FAIL" if FAIL else "check-plugin: PASS")
sys.exit(1 if FAIL else 0)

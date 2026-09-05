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
        # naming it without one is how the leak got in.
        #
        # SCOPED to one skill — `n == "pipeline"`, written on the arm itself so
        # the scope is visible where the arm fires — unlike the namespace arm
        # below, which is deliberately blanket. What the two rules are ABOUT is
        # the difference. An un-namespaced `/skill` is equally wrong in any file
        # of any skill, so there a wider net is the safer error. This rule is
        # about ONE seam: pipeline's consolidation of reviewer findings into a
        # ledger whose blocking list is PHASE-scoped. Not "no other skill sees
        # the tier" — `bug-fix` prefers `superpowers:subagent-driven-development`
        # at its Step 4, so bug-fix invokes the very reviewer that emits
        # `Important`. It is safe because it has only ONE scope: no ledger, no
        # `Sev` column, no blocking list, no advancement condition. There SDD
        # runs at SDD's native task scope, where `Important`'s "fix everything
        # before this task completes" contract is the correct one. The F1 leak
        # was a SCOPE MISMATCH — a task-scoped tier gating a phase — and bug-fix
        # has no second scope to mismatch. So the durable reason: scoped because
        # pipeline is the only skill with a phase gate a task-scoped tier can
        # mis-gate. EXPIRY: revisit the moment another skill acquires one — a
        # findings ledger, a blocking list, or a phase-advancement condition —
        # because from then on `n == "pipeline"` is a hole, not a scope.
        # Left blanket, it red-builds on
        # `**Important:**` — the commonest markdown emphasis convention there is
        # — and hands an editor of craft, bug-fix, bug-investigate or setup an
        # order to document a seam their skill does not have, with no remedy
        # they can act on.
        #
        # Matched against `flat`, not `t`: the rule is prose, it reflows, and a
        # raw-text regex would stop matching the first time the sentence
        # re-wrapped — failing on the very rule it exists to require. Keep the
        # phrase in ONE sentence for the READER, not for the regex: `flat` is
        # `" ".join(t.split())`, which splits on every whitespace run, blank
        # lines included, so the match bridges a paragraph break perfectly. An
        # earlier version of this comment claimed the opposite ("whitespace
        # normalisation does not bridge a paragraph break") — a mechanism nobody
        # tested, and false. The advice stands on readability alone: a rule
        # broken across a paragraph break reads as two weaker claims.
        # Mutant: "fourth severity tier named without its re-tag rule".
        if n == "pipeline" and re.search(r"\bImportant\b", t) and not re.search(
                r"an incoming `?Important`? is\s+re-tagged", flat):
            bad(f"{n}/SKILL.md names a fourth severity tier (`Important`) with no "
                "re-tag rule — pipeline blocks on Critical/Major/bug only, so a tier "
                "this skill never named must be re-tagged at consolidation, not "
                "carried. REMEDY: restore the sentence \"an incoming `Important` is "
                "re-tagged\" to this file (the predicate it delegates to lives in "
                "references/fix-loop.md), or — if this `Important` is only markdown "
                "emphasis — reword it to `**Note:**`, since the tier vocabulary is "
                "reserved in this skill")
        # That sentence DELEGATES: SKILL.md names Major/Minor but routes the
        # decision "by the predicate in `references/fix-loop.md`". A pointer is
        # not a rule, and nothing was holding the far end. Reverting fix-loop.md's
        # consolidation bullet to its pre-re-tag wording left zero `Important` in
        # that file, SKILL.md citing a predicate that no longer existed, and this
        # gate green — the whole routing rule deletable in one edit. So whenever
        # SKILL.md cites the predicate, the cited file must actually carry it:
        # the re-tag sentence, a Major branch, and the Minor catch-all that makes
        # the two a total partition.
        #
        # TWO files, not one. The predicate exists twice: the authority in
        # `references/fix-loop.md`, and a copy in `templates/findings.md`.
        # `templates/` is read-only and COPIED INTO THE RUN DIRECTORY, so the
        # run's own findings.md — not this repo's fix-loop.md — is the text the
        # consolidating agent has open while it writes ledger rows. If the two
        # drift, the agent applies the copy. So the copy is held to the same
        # three phrases as the authority, by the same regexes, and deleting it
        # red-builds exactly as deleting the authority does. Requiring the same
        # PHRASES (not merely the same meaning) is the point: it is what makes
        # drift detectable by a regex at all.
        #
        # Read from the same `sdir / n` as the rest of this arm, so the check
        # follows the skill, not a hard-coded path.
        # Mutants: "cited re-tag predicate deleted from fix-loop.md",
        #          "cited re-tag predicate deleted from findings.md",
        #          "cited predicate file unreadable".
        if n == "pipeline" and "by the predicate in `references/fix-loop.md`" in flat:
            parts = (
                ("the re-tag sentence", r"an incoming `?Important`? is\s+re-tagged"),
                ("a Major branch", r"\*\*Major\*\* if it names"),
                ("the Minor catch-all", r"\*\*Minor\*\* otherwise"),
            )
            for rel in ("references/fix-loop.md", "templates/findings.md"):
                pt, pe = read(sdir / n / rel)
                # UNPROVEN BY EXIT STATUS, PROVEN BY MESSAGE. Deleting this arm
                # does not turn a green build red — it turns this named FAIL
                # into an AttributeError traceback one line down (`pt` is None),
                # which is also a red build, so no mutant judged on pass/fail
                # alone can separate the two. The mutant "cited predicate file
                # unreadable" therefore asserts the MESSAGE: it greps the gate's
                # output for this file-and-reason wording and, when it is
                # absent, restores the file so the copy is clean, the gate
                # passes and the harness reports SURVIVED. That is the whole of
                # this arm's proof; it is kept because a named reason beats a
                # traceback, not because a traceback would be green.
                if pe:
                    bad(f"{n}/SKILL.md cites the `Important` re-tag predicate, which "
                        f"{rel} must carry, but that file cannot be read: {pe}")
                    continue
                pflat = " ".join(pt.split())
                missing = [lbl for lbl, rx in parts if not re.search(rx, pflat)]
                if missing:
                    bad(f"{n}/SKILL.md routes the `Important` re-tag \"by the "
                        f"predicate in references/fix-loop.md\", but {rel} is "
                        "missing " + ", ".join(missing) + " — a dangling pointer "
                        "re-tags nothing, and the rule is deletable without a red "
                        "build. Both files carry it: fix-loop.md is the authority "
                        "and templates/findings.md is the copy that ships into the "
                        "run directory, where the consolidating agent reads it. "
                        "REMEDY: restore the predicate in "
                        f"{rel} (an incoming `Important` is re-tagged; Major "
                        "if it names a measured behavioural defect, a mandated "
                        "requirement the phase did not implement, a failing or "
                        "vacuous test, a broken build gate, a security/PHI/data-loss "
                        "reachability, or a reachable fragility; Minor otherwise), "
                        "or stop citing it from SKILL.md and state the predicate "
                        "inline")
        # A CLAIM FINDING — one whose defect is an assertion rather than a
        # behaviour — closes by deleting the claim or by pinning it with a test,
        # never by rewriting the sentence, and such a closure opens no re-review
        # round. The rule needs an arm for the same reason the predicate above
        # needed one: a rule this skill states only in prose is deletable in one
        # edit with both gates green, and a rule no arm holds is exactly the
        # failure this rule is about.
        #
        # Each file that ships the rule is held. `references/fix-loop.md` is the
        # authority the fix loop reads; `templates/findings.md`'s own header says
        # it is copied into the run directory, which is why the copy is held to
        # the same phrases as the authority. Which of the two a closing agent
        # actually has open is an inference from that header, not something this
        # arm checks — and it does not have to be, because both are held.
        # SKILL.md is out of scope by the same reasoning: it restates the rule
        # for a reader, and no obligation here rests on which file gets read.
        #
        # PHRASES, not paraphrases: a check compares strings, never meanings, so
        # the shared phrase IS the drift detector. Substring rather than regex,
        # and case-folded — a substring test has no pattern syntax to get wrong.
        # Matched against flattened text so the rule may re-wrap freely; a
        # raw-text match would break on the first reflow, failing on the very
        # rule it exists to require. A phrase check proves presence, never
        # coherence: it refuses a deletion, not a bad paraphrase around the
        # phrases it keeps.
        # Mutants: "claim-finding closure rule deleted from fix-loop.md",
        #          "claim-finding closure rule deleted from findings.md".
        if n == "pipeline":
            CLAIM_RULE = (
                "claim finding",             # the term
                "deleting the claim",        # closure path
                "pinning it with a test",    # closure path
                "rewrite is not a closure",  # the non-closure
                "opens no re-review round",  # the no-round consequence
            )
            for rel in ("references/fix-loop.md", "templates/findings.md"):
                ct, ce = read(sdir / n / rel)
                if ce:
                    bad(f"{n}/{rel} must carry the claim-finding closure rule, but "
                        f"that file cannot be read: {ce}")
                    continue
                gone = [q for q in CLAIM_RULE if q not in " ".join(ct.split()).lower()]
                if gone:
                    bad(f"{n}/{rel} is missing the claim-finding closure rule ("
                        + ", ".join(map(repr, gone)) + " absent). A claim finding — "
                        "a false count, a stale citation, a wrong sole-writer claim "
                        "— closes by deleting the claim or by pinning it with a "
                        "test, never by rewriting the sentence, and such a closure "
                        "opens no re-review round; without the rule a fix round "
                        "keeps raising the successor of its own fix. Both texts "
                        "carry it: fix-loop.md is the authority and "
                        "templates/findings.md is the copy its own header says "
                        "ships into the run directory. REMEDY: "
                        f"restore the wording in {rel} — these phrases are required "
                        "verbatim, which is what makes drift between the two texts "
                        "detectable")
            # The closure rule ends in a CROSS-REFERENCE: a deletion-or-pin
            # closure is outside `M` and outside the fix-diff coverage union,
            # "so `M` and the fix-diff coverage union both exclude it". Two
            # other structures are what make that true — the exclusion bullet in
            # *Re-review fan-out*, and the `M=0 → no round` condition on the fix
            # loop's step 3 — and CLAIM_RULE above reaches neither. Deleting
            # only the bullet left a green gate, a dangling cross-reference, and
            # the fan-out back to its unqualified "Assignments MUST cover every
            # fix diff": the exact contradiction the closure rule was written to
            # remove, reinstated in one edit.
            #
            # ONE file, unlike CLAIM_RULE's two. Both consequences live in
            # structures only `references/fix-loop.md` has — the fan-out table's
            # bullets and the numbered fix loop. `templates/findings.md` states
            # the rule and says the closure "opens no re-review round"; it never
            # describes a fan-out, so there is nothing there for these phrases
            # to be true of.
            #
            # Unconditional, NOT gated on the cross-reference still being
            # present. Gating it would let one edit that removes the
            # cross-reference and the bullet together pass green — the same hole
            # by two deletions instead of one.
            # Mutants: "M-exclusion bullet deleted from fix-loop.md",
            #          "no-round RV form deleted from fix-loop.md".
            CLAIM_EFFECT = (
                ("the `M`-exclusion bullet", "not counted in `m`"),
                ("the coverage-union exclusion", "its fix commit is not in that union"),
                ("the `M=0 → no round` form", "m=0 → no round"),
            )
            at, ae = read(sdir / n / "references/fix-loop.md")
            if ae is None:
                aflat = " ".join(at.split()).lower()
                lost = [lbl for lbl, q in CLAIM_EFFECT if q not in aflat]
                if lost:
                    bad(f"{n}/references/fix-loop.md carries the claim-finding "
                        "closure rule but not its consequences — missing "
                        + ", ".join(lost) + ". The rule says a deletion-or-pin "
                        "closure opens no re-review round, \"so `M` and the "
                        "fix-diff coverage union both exclude it\"; without the "
                        "*Re-review fan-out* exclusion bullet that union is back "
                        "to \"Assignments MUST cover every fix diff\", and "
                        "without the `M=0 → no round` condition step 3 still "
                        "mandates a round over a diff the rule just excluded. "
                        "REMEDY: restore, in fix-loop.md, the fan-out bullet (a "
                        "claim finding closed by deletion or by a pin is not "
                        "counted in `M`, and its fix commit is not in that union) "
                        "and step 3's `M=0 → no round` condition with its RV form")
    for f in sorted((sdir / n).rglob("*.md")):
        t, e = read(f)
        if e: continue
        for m in (_ns.finditer(t) if _ns else []):
            rel = f.relative_to(sdir).as_posix()
            bad(f"{rel} writes {m.group(0)!r} un-namespaced; use /superb:{m.group(1)} — "
                "unless the sentence is ABOUT the unprefixed form, in which case "
                "paraphrase it, since prefixing it inverts the claim")
if len(FAIL) == _inv_before:
    ok("no indexed-placeholder dispatch, invocations namespaced, no unhandled "
       "fourth severity tier, re-tag predicate present where cited, "
       "claim-finding closure rule present in both texts that ship it, its "
       "`M`-exclusion and `M=0 → no round` consequences present in the authority")

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

# ---- every mutant this file cites by name must actually exist ----
# The arms above cite their proofs by NAME: a `Mutant`/`Mutants` comment marker
# followed by the quoted mutant names — a citation into another file that
# nothing kept true. Rename or delete a mutant and these comments point at
# nothing, on a green build. That is a
# claim finding by this skill's own rule, and "neither enforcement code nor a
# run's own records is exempt" leaves it no carve-out; the rule offers a pin as
# well as a deletion, and this is the pin. It also retires the grandfather
# clause a previous round granted these citations as "file convention".
#
# Citation side: that marker plus a colon, anywhere in a `#` comment line, whose
# quoted names may wrap onto following comment lines and end at the first line
# whose text closes with a period. This paragraph deliberately writes the marker
# without its colon, since a comment ABOUT the form is not a citation and the
# reader is the only thing that can tell them apart. Harness side: the first
# argument of each
# `run_mutant`, read from the SHELL SOURCE — so a name containing `$0` is
# written `\$0` there (or the shell substitutes it) while the comment writes the
# literal. Escapes are stripped from BOTH sides before comparing; without that
# step exactly one name — "skill dispatches on a doubled-backslash $0" —
# false-positives on every run and the check is worthless.
# Mutants: "cited mutant renamed out from under its citation".
print("\n== mutant citations ==")
gt, ge = read(ROOT / "tools/check-plugin.py")
ht, he = read(ROOT / "tools/check-plugin-mutants.sh")
if ge or he:
    bad("cannot read the gate/harness pair the mutant citations join: "
        + (ge or he))
else:
    cited, gl, i = [], gt.split("\n"), 0
    while i < len(gl):
        m = re.search(r"\bMutants?:\s*(.*)$", gl[i]) if gl[i].lstrip().startswith("#") else None
        if not m:
            i += 1; continue
        buf, j = m.group(1), i + 1
        while not buf.rstrip().endswith(".") and j < len(gl) and gl[j].lstrip().startswith("#"):
            buf += " " + gl[j].lstrip()[1:].strip(); j += 1
        cited += re.findall(r'"([^"]*)"', buf)
        i = max(j, i + 1)
    unesc = lambda s: re.sub(r"\\(.)", r"\1", s)
    have = {unesc(m.group(1)) for m in re.finditer(r'run_mutant\s+"((?:[^"\\]|\\.)*)"', ht)}
    dangling = [c for c in cited if unesc(c) not in have]
    if not cited:
        bad("check-plugin.py cites no mutant by name — either the citations that "
            "made each arm traceable to the mutant proving it are gone, or the "
            "marker-plus-colon form this check reads them by has changed. "
            "REMEDY: cite each arm's mutants by name again, or delete this check "
            "along with the last citation")
    elif dangling:
        bad("check-plugin.py cites mutants check-plugin-mutants.sh does not "
            "define: " + ", ".join(map(repr, dangling)) + " — a citation by name "
            "into another file goes stale in silence, which is the failure the "
            "claim-finding rule is about. REMEDY: add the missing mutant, or "
            "correct the citation to the name the harness uses. Names compare "
            "after shell backslash-escapes are stripped, so `\\$0` and `$0` are "
            "the same name and are not what this is reporting")
    else:
        ok(f"{len(cited)} cited mutant names all defined in check-plugin-mutants.sh")

print()
print("check-plugin: FAIL" if FAIL else "check-plugin: PASS")
sys.exit(1 if FAIL else 0)

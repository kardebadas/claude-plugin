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

# ---- argv: default mode takes no arguments and must stay byte-identical ----
# `--run <dir>` points the review-line linter at a real run's `progress.md` as
# well as the skill's worked examples. Anything else is rejected rather than
# ignored: a silently-swallowed typo (`--rn`, `-run`) runs the DEFAULT mode and
# reports PASS, which reads as "the run directory conforms".
# Mutants: "wrapper passes an unrecognised argument".
RUN_DIR = None
_argv = sys.argv[1:]
if _argv and _argv[0] == "--run":
    if len(_argv) < 2:
        print("usage: check-plugin.py [--run <run-directory>]"); sys.exit(2)
    RUN_DIR = pathlib.Path(_argv[1]).expanduser().resolve()
elif _argv:
    print(f"unknown argument {_argv[0]!r}; "
          "usage: check-plugin.py [--run <run-directory>]"); sys.exit(2)

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
        # never by rewriting the sentence. Deleting the claim opens no re-review
        # round; a pin commits a test, so its commit is owed a reviewer like any
        # other. The rule needs an arm for the same reason the predicate above
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
                "opens no re-review round",  # a deletion's consequence
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
                        "test, never by rewriting the sentence, and deleting the "
                        "claim opens no re-review round; without the rule a fix "
                        "round keeps raising the successor of its own fix. Both texts "
                        "carry it: fix-loop.md is the authority and "
                        "templates/findings.md is the copy its own header says "
                        "ships into the run directory. REMEDY: "
                        f"restore the wording in {rel} — these phrases are required "
                        "verbatim, which is what makes drift between the two texts "
                        "detectable")
            # The closure rule ends in a CROSS-REFERENCE: a DELETION is
            # outside `M`, and its commit is outside the fix-diff coverage union
            # as well — while a PIN is in both, because it commits a test. Two
            # other structures are what make that true — the exclusion bullet in
            # *Re-review fan-out*, and the `M=0 → no round` condition on the fix
            # loop's step 3 — and CLAIM_RULE above reaches neither. Deleting
            # only the bullet left a green gate, a dangling cross-reference, and
            # the fan-out back to its unqualified "Assignments MUST cover every
            # fix diff": the exact contradiction the closure rule was written to
            # remove, reinstated in one edit.
            #
            # PER-PHRASE FILE SETS, because the phrases do not live in the same
            # places. The union/`M` phrases and `M`'s own definition live in
            # structures only `references/fix-loop.md` has — the fan-out table's
            # bullets and the numbered fix loop — so they are held there alone;
            # `templates/findings.md` states the rule and says a deletion
            # "opens no re-review round" but never describes a fan-out, so
            # there is nothing there for them to be true of. The
            # `M=0 → no round` form is different: `SKILL.md` and
            # `references/run-state.md` both define the `RV` grammar and both
            # now carry the phrase verbatim, and deleting the paragraph from
            # either one left this gate green. An unheld second copy is the
            # weakness each of this arm's neighbours was extended to close, so
            # all three files hold that phrase — and the phrase must stay
            # byte-identical across them, which is the whole point of holding a
            # phrase rather than a meaning.
            #
            # Unconditional, NOT gated on the cross-reference still being
            # present. Gating it would let one edit that removes the
            # cross-reference and the bullet together pass green — the same hole
            # by two deletions instead of one.
            # `M`'s DEFINITION is held here too, and separately from the
            # condition. The three entries above hold the CONSEQUENCE
            # (`m=0 → no round`, the exclusions) in up to three files, but
            # nothing held the sentence `M` is *stated in terms of*: deleting
            # the whole `**Unless `M=0`.**` paragraph — the definition and its
            # closed route list together — left `check-plugin: PASS` and every
            # mutant killed, because the phrase the no-round arm reads occurs in
            # that file only inside a worked-example fence. A condition whose
            # subject is undefined is the same hole one level up from the one
            # those three entries closed.
            #
            # Two phrases, not one, because the paragraph makes two separable
            # claims and each has its own failure mode. The DEFINITION can be
            # blurred ("the count this round declares") while the route list
            # stands; the ROUTE LIST can be shortened to two of its three
            # dispositions while the definition stands — which is exactly the
            # defect that reached `SKILL.md`'s *Re-review fan-out*, a round owed
            # over an empty diff. Holding them apart is what makes each mutant's
            # kill attributable to the phrase its name claims.
            #
            # The route-list phrase names all three dispositions in one clause —
            # deletion out, user-ruled false positive out, and (by "exactly
            # when") a pin in — so dropping any one of them, or admitting a
            # fourth, breaks the literal.
            # Mutants: "M-exclusion phrase blurred in fix-loop.md",
            #          "coverage-union phrase blurred in fix-loop.md",
            #          "no-round RV form deleted from fix-loop.md",
            #          "no-round RV form deleted from SKILL.md",
            #          "no-round RV form deleted from run-state.md",
            #          "M's definition paragraph deleted from fix-loop.md",
            #          "M's definition blurred in fix-loop.md",
            #          "M's exclusion-route list loses a route".
            # ONE CLAUSE PER ENTRY, carried on the entry. The message used to
            # enumerate what all five phrases do on every firing — 191 words,
            # emitted per (entry × file), 5,818 bytes of near-identical prose in
            # a five-firing run — and four of those clauses named a phrase that
            # had not gone missing. The full rationale is this comment; a CI
            # line gets the clause belonging to the phrase that fired.
            AUTH = ("references/fix-loop.md",)
            CLAIM_EFFECT = (
                ("the `M`-exclusion bullet", "not counted in `m`", AUTH,
                 "Lose it and a deletion puts a round back on the books that "
                 "nobody needs."),
                ("the coverage-union exclusion",
                 "fix commit is not in that union", AUTH,
                 'Lose it and that union is back to "Assignments MUST cover '
                 'every fix diff".'),
                ("the `M=0 → no round` form", "m=0 → no round",
                 ("references/fix-loop.md", "SKILL.md",
                  "references/run-state.md"),
                 "Lose it and an unrun round and a skipped one read alike on "
                 "the `RV` line."),
                ("`M`'s definition",
                 "the number of blocking f-ids this fix-mode run targeted",
                 AUTH,
                 "Lose it and the `M=0` condition has no subject."),
                ("`M`'s closed exclusion-route list",
                 "excluded exactly when its closure route is a deletion or a "
                 "user-ruled false positive", AUTH,
                 "Lose it and the list shortens to two dispositions with the "
                 "definition still standing."),
            )
            for lbl, q, rels, why in CLAIM_EFFECT:
                for rel in rels:
                    at, ae = read(sdir / n / rel)
                    if ae:
                        bad(f"{n}/{rel} must carry {lbl}, but that file cannot "
                            f"be read: {ae}")
                        continue
                    if q not in " ".join(at.split()).lower():
                        bad(f"{n}/{rel} is missing {lbl} ({q!r} absent). "
                            f"{why} It is required verbatim, because a rule "
                            "with one unheld copy is one edit from gone on a "
                            f"green build. REMEDY: restore the phrase in {rel} "
                            "verbatim, where the authority states that rule")
        # `M` HAS ONE DEFINITION, AND NOTHING SHORTER MAY STATE IT.
        # `SKILL.md`'s `M=0` paragraph asserts that `M` "is defined **once**",
        # in `references/fix-loop.md`, fix loop step 3, and warns that a second
        # copy of a closed list "can drift into being a shorter one". Nothing
        # held that claim. `CLAIM_EFFECT` above checks the definition is PRESENT
        # in the authority, and a present authority is compatible with any
        # number of shorter glosses elsewhere: two had already appeared —
        # `SKILL.md` "records the count of targeted F-IDs for the convergence
        # check", and the same sentence inside the authority itself, below the
        # definition it contradicts — each having dropped every exclusion, which
        # reads `M=1` on a deletion-only iteration. That is a round mandated
        # over an empty diff, which the fan-out table has no row to size, and it
        # reached both files with both gates green.
        #
        # THE PREDICATE IS THE EXCLUSION TRAVELLING WITH THE COUNT: a sentence
        # that says `M` is a count or number of F-IDs must also say `leaves no
        # ownable commit`. That is not a paraphrase test. Both legal statements
        # carry the phrase verbatim — the authority's definition, and
        # `SKILL.md`'s one-line citation of it — and both glosses lacked it, so
        # the one clause a gloss always drops is what separates them. Scoped to
        # a sentence by `[^.;]*`, which is conservative: a `.` inside the window
        # (a filename) ends it early, so the arm under-matches rather than
        # inventing a gloss out of two adjacent sentences.
        #
        # THE ANCHOR LOOKS ONE WAY, AND THE SUMMARY LINE SAYS SO. Both
        # lookaheads scan FORWARD from `` `M` ``, so what the arm establishes is
        # "no exclusion-less gloss that names `M` ahead of the count and the
        # F-IDs" — a gloss putting either of those first ("the count of
        # targeted F-IDs is `M`") is outside it. The summary line used to claim
        # "no exclusion-less gloss of it anywhere", which is more than any
        # anchored pattern can establish; that claim is deleted rather than
        # rewritten, and the wording now states what the anchor reaches.
        # WIDENING THE PATTERN IS NOT THE FIX: anchoring on `` `M` `` is what
        # makes this arm stronger than a literal, and a symmetric version would
        # have to guess a left boundary in prose that has none.
        #
        # UNIQUENESS IS THE OTHER HALF, and it fires on `> 1`, never on `!= 1`.
        # Absence is `CLAIM_EFFECT`'s to report, with its own file and remedy;
        # were this arm to fail on absence as well, the definition-blur mutant
        # would die by two arms at once and neither kill would be attributable
        # to the phrase its name claims.
        # Mutants: "short `M` gloss reintroduced into SKILL.md",
        #          "M's definition duplicated into a second file".
        if n == "pipeline":
            MDEF = "the number of blocking f-ids this fix-mode run targeted"
            MEXCL = "leaves no ownable commit"
            MGLOSS = re.compile(r"`M`(?=[^.;]*\bF-IDs?\b)"
                                r"(?=[^.;]*\b(?:count|counts|number)\b)[^.;]*",
                                re.I)
            homes = []
            for mf in sorted((sdir / n).rglob("*.md")):
                mt, me = read(mf)
                if me:
                    continue
                mrel = mf.relative_to(sdir / n).as_posix()
                mflat = " ".join(mt.split())
                homes += [mrel] * mflat.lower().count(MDEF)
                for g in MGLOSS.finditer(mflat):
                    if MEXCL in g.group(0).lower():
                        continue
                    bad(f"{n}/{mrel} glosses `M` as a count of F-IDs with no "
                        f"exclusion: {g.group(0)[:100]!r}. `M` is that count "
                        "LESS every targeted F-ID closed by a route that "
                        "leaves no ownable commit, and a gloss that drops the "
                        "exclusion reads `M=1` on a deletion-only iteration — a "
                        "round mandated over an empty diff, which no fan-out "
                        "row sizes. REMEDY: either the sentence stops "
                        "matching MGLOSS above — deleted, or cross-referenced "
                        "to fix-loop.md's step 3, or paraphrased out of that "
                        "shape the way the namespace arm below lets a sentence "
                        "about the unprefixed form paraphrase — or it carries "
                        "`leaves no ownable commit` with the count. The "
                        "pattern is the predicate; the edits are not a closed "
                        "list")
            if len(homes) > 1:
                bad(f"{n} defines `M` in {len(homes)} places ("
                    + ", ".join(sorted(homes)) + ") — SKILL.md says it is "
                    "defined once, in fix-loop.md's step 3, and a second copy "
                    "of a closed route list is a copy that can drift into being "
                    "a shorter one. REMEDY: keep the definition in "
                    "fix-loop.md's step 3 and cross-reference it elsewhere")
        # WHAT A DISPATCH BRIEF MUST CARRY, held by phrase in the file that
        # states it. The skill's dispatch contract now carries three
        # requirements, and each was one edit from gone before this arm:
        #
        #  - DERIVE, DON'T RESTATE (Rule 5b). A brief may state the SOURCE of a
        #    code fact and not the fact. The measurement behind it: in one run
        #    about ten orchestrator briefs stated a code fact that was wrong —
        #    a function placed in the wrong file, helpers unreachable from the
        #    named test class, a call-site count off by two, a return type read
        #    as an argument — and every one was caught by the agent RECEIVING
        #    the brief, never by the orchestrator writing it. A restated fact is
        #    correct when written and at no moment after, so the rule is held on
        #    both ends: the prohibition (what a brief may not state) and the
        #    receiving agent's duty to refuse rather than reconcile.
        #  - CITE `kit.md` BY PATH. Without it each task derives the same
        #    apparatus again, and a dispatch that omits the worktree rule is how
        #    two agents come to mutate the same file in the main tree at once.
        #    Held at both ends too, because the citation and the file's writing
        #    point are separately deletable and either alone leaves the other
        #    useless: a citation to a file GATE 2 no longer writes is a dangling
        #    pointer, and a file nothing cites is a file nobody reads.
        #  - THE TICKET/ISSUE KEY. Held at both ends for the same reason: Stage
        #    1 asking it and the dispatch prompt stating it are separate edits,
        #    and an answer that never reaches the implementer is not carried.
        #
        # PER-PHRASE FILE SETS, like `CLAIM_EFFECT` above and for the same
        # reason: these phrases do not live in the same places. Rule 5b's
        # prohibition is held in BOTH `SKILL.md`, where the Run State Law states
        # the rule, and `references/run-state.md`, where the dispatch contract
        # makes it an instruction — held the way the `M=0 → no round` entry is
        # held in every file that defines the `RV` grammar, on the same argument
        # that an unheld second copy is one edit from gone on a green build. The other phrases have one home
        # each and are held only there; asserting them elsewhere would be
        # asserting a copy that does not exist.
        #
        # NO PHRASE IS DUPLICATED WITHIN ITS FILE. The arm reads flattened text
        # and a second occurrence would satisfy it from the wrong place, which
        # also turns the phrase's mutant into a silent no-op. Every phrase held
        # in `references/run-state.md` sits in the SAME paragraph there, so
        # their mutants are surgical per phrase and each asserts its siblings
        # survived — a paragraph deletion would fire several arms and be
        # attributable to none, the defect the `M`-exclusion bullet's mutants
        # were split to fix.
        # Mutants: "Rule 5b's prohibition blurred in SKILL.md",
        #          "Rule 5b's prohibition blurred in run-state.md",
        #          "the brief-refusal duty blurred in run-state.md",
        #          "the kit.md citation blurred in run-state.md",
        #          "kit.md's GATE 2 writing point blurred in SKILL.md",
        #          "the ticket-key question blurred in SKILL.md",
        #          "the ticket key's dispatch field blurred in run-state.md".
        if n == "pipeline":
            LAW, CONTRACT = ("SKILL.md",), ("references/run-state.md",)
            DISPATCH_CONTRACT = (
                ("Rule 5b's prohibition",
                 "never a count, a line number, a signature or a file list",
                 LAW + CONTRACT,
                 "Lose it and a brief may state the code facts that were wrong "
                 "in every brief measured to have stated one."),
                ("the receiving agent's duty to refuse",
                 "refuses the brief and says which fact", CONTRACT,
                 "Lose it and a stated code fact becomes something the agent "
                 "reconciles, which is trusting it with extra steps."),
                ("the `kit.md` citation", "`kit.md`, cited by path", CONTRACT,
                 "Lose it and every task derives the harness again, and two of "
                 "them mutate the same file in the main tree."),
                ("`kit.md`'s writing point",
                 "written once, here, from the approved plan", LAW,
                 "Lose it and the file the dispatch contract cites by path is "
                 "never written, leaving that citation dangling."),
                ("the ticket/issue key as a Stage 1 question",
                 "the ticket/issue key required in a commit subject", LAW,
                 "Lose it and the key is discovered at Stage 5, after every "
                 "task in the run has committed without it."),
                ("the ticket/issue key as a dispatch field",
                 "the prompt states it, the implementer puts it in the subject",
                 CONTRACT,
                 "Lose it and the answer Stage 1 obtained never reaches the "
                 "agent that has to type it."),
            )
            for lbl, q, rels, why in DISPATCH_CONTRACT:
                for rel in rels:
                    dt, de = read(sdir / n / rel)
                    if de:
                        bad(f"{n}/{rel} must carry {lbl}, but that file cannot "
                            f"be read: {de}")
                        continue
                    if q not in " ".join(dt.split()).lower():
                        bad(f"{n}/{rel} is missing {lbl} ({q!r} absent). {why} "
                            "It is required verbatim, because a rule with one "
                            "unheld copy is one edit from gone on a green "
                            f"build. REMEDY: restore the phrase in {rel}, where "
                            "that file states its half of the dispatch "
                            "contract")
        # RULE 5b BINDS THIS SKILL'S OWN PROSE, AND THE TEMPLATE COUNTS ARE
        # WHERE IT WAS ALREADY BROKEN. Sentences in `SKILL.md` and
        # `references/run-state.md` counted the skill's own run-state file
        # templates. Each was true when written and false the moment
        # `templates/kit.md` landed — the rule's own arrival is what falsified
        # them — and nothing would have said so: no arm reads that directory's
        # cardinality, so the counts would have stayed, wrong, on a green build.
        # They now name the directory instead, and this arm is what keeps a
        # count from coming back.
        #
        # WINDOW-BOUNDED AND FORWARD-ANCHORED, so the summary line claims only
        # what it reaches: a count STANDING AHEAD OF the word, within one
        # sentence (`[^.;]`) and 45 characters. Every sentence it was written
        # against sat well inside that, including those whose count quantified
        # "files" with the directory named later in the same clause. A count trailing the word ("templates, of which there are
        # three") is outside it, and widening to catch that would mean guessing
        # a left boundary in prose that has none.
        #
        # IT FIRES ON A DIGIT USED AS AN ORDINAL NEAR THE WORD TOO ("Stage 1
        # step 0 with the other templates" tripped it while this arm was being
        # written). That is the conservative direction for a self-referential
        # lint — the remedy is one reword and the gate says which sentence — and
        # dropping `\d+` to avoid it would let "the 3 templates" through, which
        # is the defect itself in digits.
        # Mutants: "template count reintroduced into SKILL.md".
        if n == "pipeline":
            TCOUNT = re.compile(
                r"\b(?:both|one|two|three|four|five|six|seven|eight|nine|ten"
                r"|\d+)\b[^.;]{0,45}?\btemplates?\b", re.I)
            for cf in sorted((sdir / n).rglob("*.md")):
                cft, cfe = read(cf)
                if cfe:
                    continue
                cfrel = cf.relative_to(sdir / n).as_posix()
                for g in TCOUNT.finditer(" ".join(cft.split())):
                    bad(f"{n}/{cfrel} states a count of the skill's own "
                        f"templates: {g.group(0)[:100]!r}. Rule 5b binds this "
                        "skill's own prose, and a count of that directory is "
                        "true until the commit that adds a file to it — which "
                        "is what happened to the sentences this arm replaced. "
                        "REMEDY: name `templates/` instead of counting it. If "
                        "the number is an ordinal that only happens to sit "
                        "near the word, reword the sentence — this arm reads a "
                        "45-character window and does not know the difference")
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
       "`M`/union exclusions plus `M`'s own definition and closed route list "
       "present in the authority, its `M=0 → no round` "
       "form present in all three files that define the `RV` grammar, `M` "
       "defined in one place with no exclusion-less gloss that names `M` ahead "
       "of the count and the F-IDs it glosses, the dispatch contract's three "
       "requirements each held in the file that states it, and no count of the "
       "skill's own templates standing ahead of the word")

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
#
# The `M=0 → no round` declaration gets its OWN arm below, because it is the one
# round form that closes with zero reviewer evidence: no `reports`, no
# `coverage`, nothing a later reader can re-run. It carried no gate coverage at
# all, and two contradictory records passed — one declaring `M=0 → no round`
# while also listing `reports` and `coverage`, and one naming no closure route,
# which the prose itself calls "a skipped review wearing this form". What
# replaces the missing evidence is the routes, so that is what is checked: no
# reviewer fields, no reviewer counts, at least one F-ID with a NAMED route, and
# the outcome slot. The route set is `deleted` and `user-ruled false positive` —
# the two the prose enumerates, and the arm has to match the grammar the prose
# teaches or it would reject the skill's own worked example.
#
# `pinned by <test>` is NOT in that set, and its ABSENCE is checked rather than
# merely unlisted. A pin commits a test, so it stays in `M`; an iteration that
# produced one has `M>0` and is owed a round over that commit, which makes
# `M=0 → no round · closures: F-019 pinned by <test>` a record that cannot be
# true. Narrowing the route alternation alone would not catch it: a record
# pairing a legal `deleted` with an illegal `pinned by` still satisfies "at
# least one NAMED route", so the illegal route needs its own rejection.
#
# The record is cut at the first ``` fence, not just at the 400-char window the
# `N=`/`M=` arm uses: both worked instances sit inside a fenced block, and the
# prose that follows one discusses `reports` and `coverage` by name — read as
# part of the record it would report a contradiction that is not there. A record
# outside a fence keeps the window, which can only over-read prose and so can
# only be conservative about the positive checks.
# Mutants: "no-round round declares a reports field",
#          "no-round round names no closure route",
#          "no-round round names a pinned route".
print("\n== pipeline review-line examples ==")
start = re.compile(r"(?:-\s*)?\[x\]\s*(RVJ|RV)\b|(?:->|→)\s*(round)\s+\d+\s*:")
decl  = re.compile(r"(?:N|M)=\d+\s*(?:waved\s+)?(?:->|→)\s*(\d+)\s*slice\s*\+\s*(\d+)\s*integration")
rpt   = re.compile(r"reports\s+(.+?)(?=\s*[·|]|\s+coverage\b|\s*$)")
cov   = re.compile(r"coverage\s+\S+\.md")
nor   = re.compile(r"\bM=0\s*(?:->|→)\s*no\s+round\b")
route = re.compile(r"\bF-\d+\s*,?\s+(deleted|user-ruled false positive)")
pinrt = re.compile(r"\bpinned by\b")
outc  = re.compile(r"(?:->|→)\s*(?:no findings\b|F-\d+)")
def nfiles(spec):
    m = re.search(r"\{([^}]*)\}", spec)
    src = m.group(1) if m else spec
    return len([x for x in src.split(",") if x.strip()])

def expand_braces(spec):
    """`p3-review-{a,b,int}.md` -> the three names; a plain list passes through.

    The counterpart to `nfiles`, which counts the same spec. Counting and
    naming had to agree or the existence check below would look for a file
    called `p3-review-{a,b,int}.md`, which no run ever writes.
    """
    spec = spec.strip()
    m = re.search(r"\{([^}]*)\}", spec)
    if not m:
        return [x for x in re.split(r"[,\s]+", spec) if x.endswith(".md")]
    pre, post = spec[:m.start()], spec[m.end():]
    return [f"{pre}{x.strip()}{post}" for x in m.group(1).split(",") if x.strip()]

def rel(p):
    """Repo-relative when the path is in the repo, absolute when it is not.

    A run directory is a caller's argument and need not sit under ROOT, so
    `relative_to` cannot be assumed — it raises, and a traceback is not a
    finding.
    """
    try:
        return p.relative_to(ROOT)
    except ValueError:
        return p

def lint_review_lines(paths, agent_output=None):
    """Lint every closed RV/RVJ round found in `paths`.

    paths: iterable of .md files to scan.
    agent_output: when given, a directory each named report file must exist
        in. Available for a real run only — the skill's worked examples name
        illustrative files that were never written, so passing it there would
        fail the documentation for being documentation.
    Returns (closed_rounds, no_round_records, violations).
    """
    seen = nseen = viol = 0
    for f in sorted(paths):
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
            if nor.search(rec):
                nseen += 1
                body = rec.split("```")[0] if "```" in rec else rec
                where = f"{rel(f)}:{lineno(pos)}"
                probs = []
                if rpt.search(body):
                    probs.append("lists a `reports` field")
                if cov.search(body):
                    probs.append("lists a `coverage` field")
                if decl.search(body):
                    probs.append("declares reviewer counts as well as `no round`")
                if not route.search(body):
                    probs.append("names no closure route — every F-ID needs "
                                 "`deleted` or `user-ruled false positive` after "
                                 "it")
                if pinrt.search(body):
                    probs.append("names a `pinned by <test>` route, which no "
                                 "`M=0` round can carry — a pin commits a test, so "
                                 "it stays in `M` and its commit is owed a "
                                 "reviewer")
                if not outc.search(body):
                    probs.append("has no outcome slot (`→ no findings` or F-IDs)")
                if probs:
                    viol += 1
                    bad(f"{where}: `M=0 → no round` round " + "; ".join(probs)
                        + ". This is the only round form that closes with no "
                        "reviewer evidence, so the named closure routes are all "
                        "the evidence there is: a `no round` whose routes are "
                        "unnamed is a skipped review wearing this form, one "
                        "carrying `reports` or `coverage` is claiming reviewers a "
                        "round of nobody never had, and one naming a pin is not an "
                        "`M=0` iteration at all. REMEDY: write it as "
                        "`→ round <n>: M=0 → no round · closures: F-018 deleted, "
                        "F-019 user-ruled false positive → no findings`")
                continue
            d = decl.search(rec)
            if not d: continue          # e.g. the WAIVED form, which carries no counts
            seen += 1
            want = int(d.group(1)) + int(d.group(2))
            where = f"{rel(f)}:{lineno(pos)}"
            if kind == "RVJ" and (int(d.group(1)), int(d.group(2))) != (0, 1):
                viol += 1; bad(f"{where}: RVJ must be 0 slice + 1 integration, declares {d.group(1)}+{d.group(2)}")
            r = rpt.search(rec)
            got = nfiles(r.group(1)) if r else 0
            if got != want:
                viol += 1; bad(f"{where}: declares {want} reviewers, lists {got} report files")
            if not cov.search(rec):
                viol += 1; bad(f"{where}: closed review round with no coverage file")
            if agent_output is not None and r:
                for nm in expand_braces(r.group(1)):
                    if not (agent_output / nm).exists():
                        viol += 1
                        bad(f"{where}: report file {nm!r} is named on a closed "
                            f"round but is not in {agent_output.name}/ — a "
                            "round closes on reviewer evidence a later reader "
                            "can re-open, so a name with no file behind it is "
                            "a reviewer count that was never met")
    return seen, nseen, viol

pdir = ROOT / "plugins" / "superb" / "skills" / "pipeline"
seen, nseen, viol = lint_review_lines(pdir.rglob("*.md"))
if not seen: bad("no closed RV/RVJ examples found — the grammar lost its worked instances")
# Counted and reported SEPARATELY from `seen`, and required non-zero, for the
# reason the mutant-citation arm below requires its own list non-empty: an arm
# whose subject can vanish from the docs is an arm that silently starts checking
# nothing, and the count in the pass line is what makes that visible on a green
# build instead of at the next review.
if not nseen:
    bad("no `M=0 → no round` worked example found in the pipeline skill — the "
        "one round form that closes with zero reviewer evidence has lost the "
        "instances this arm reads, so the arm now checks nothing on a green "
        "build. REMEDY: keep at least one worked `M=0 → no round` round in the "
        "skill's prose, or delete this arm along with the last one")
if seen and nseen and not viol:
    ok(f"{seen} closed review rounds, {nseen} of them `M=0 → no round`: "
       "reviewer counts, RVJ shape and coverage all conform, and every "
       "no-round record names its closure routes and carries no reviewer "
       "evidence")

# ---- the same linter, over a REAL run's tracker ----
# The arm above scans `pdir` only — the skill's own worked examples — so no
# invocation of this gate has ever read a run's own tracker. `--run <dir>`
# does, over `<dir>/progress.md`, with the same rules.
#
# A real run also supports the one check the examples cannot: the named report
# files either exist in `agent-output/` or they do not. The examples' filenames
# are illustrative and were never written, so `agent_output` is passed HERE and
# nowhere else — passing it above would fail the documentation for being
# documentation.
#
# `nseen` is deliberately NOT required non-zero here. `M=0 → no round` is a
# legitimate but optional round form; a run that never produced one is not
# thereby defective, and requiring it would make the mode reject conforming
# runs. `rseen` IS required, because a `--run` over a tracker with no closed
# round is a caller who thinks a review has been checked when none has.
#
# Both "does not exist" branches report a NAMED failure rather than raising:
# `bad()` is the gate's only way to say something, and a traceback exits before
# the remaining sections ever run.
# Mutants: "run tracker over-declares reviewers",
#          "run tracker cites a report file that is not in agent-output",
#          "run tracker round loses its coverage field",
#          "run tracker loses one brace-expanded report file",
#          "run tracker has no closed review round",
#          "run directory has no progress.md",
#          "run directory has no agent-output".
if RUN_DIR is not None:
    print(f"\n== run tracker: {rel(RUN_DIR)} ==")
    tracker = RUN_DIR / "progress.md"
    if not tracker.exists():
        bad(f"{rel(tracker)} does not exist — `--run` was pointed at "
            "something that is not a pipeline run directory, so nothing was "
            "checked. REMEDY: pass the run directory that holds the run's "
            "`progress.md`")
    else:
        ao = RUN_DIR / "agent-output"
        if not ao.is_dir():
            bad(f"{rel(ao)} does not exist — a closed review round has "
                "nowhere to have written its reports, so every report file "
                "this tracker names is unverifiable. REMEDY: keep the run's "
                "`agent-output/` beside its `progress.md`")
            ao = None
        rseen, rnseen, rviol = lint_review_lines([tracker], agent_output=ao)
        if not rseen:
            bad(f"{rel(tracker)}: no closed RV/RVJ round — nothing in this run "
                "has been reviewed yet, so a PASS here would report a review "
                "that has not happened")
        elif not rviol and ao is not None:
            # `ao is not None` guards the PASS LINE as well as the check:
            # presence was not checked when there was no directory to check it
            # against, so this line must not be the thing that says it was.
            ok(f"{rseen} closed review rounds in the tracker"
               + (f" ({rnseen} of them `M=0 → no round`)" if rnseen else "")
               + ", every declared report file present in agent-output/")

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
#
# The strip matches BASH's rule, not a superset of it. Inside a double-quoted
# word bash honours a backslash before exactly `$`, a backtick, `"`, `\` and a
# newline; before anything else the backslash stays in the string. Stripping one
# before ANY character therefore validated citations no reader can grep for: a
# name written `\q` in the harness IS `\q` at runtime, and a comment citing `q`
# would have matched it. A newline cannot occur here — a `run_mutant` name is
# matched within one line — so the class is those four characters.
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
    unesc = lambda s: re.sub(r'\\([$`"\\])', r"\1", s)
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

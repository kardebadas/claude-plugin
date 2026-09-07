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
# reports PASS, which reads as "the run directory conforms". A `--run` with no
# operand is refused the same way, and the usage line it prints is asserted by
# name: neutralise the guard and `_argv[1]` raises `IndexError`, which is also
# a red build, so only the MESSAGE separates the two.
# Mutants: "wrapper passes an unrecognised argument",
#          "wrapper passes --run with no operand".
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

# THE BLOCKING LEDGER'S HEADER COLUMNS, as `templates/findings.md` ships them.
# Named here because two things must agree about it: the arm that locates
# `Sev`/`Phase`/`State` in a run's `findings.md`, and the template that tells a
# run what to write. Three rounds of review found holes in a parser that tried
# to be liberal about this; the answer was to make the GRAMMAR strict and the
# parser small, so the failure mode is a named, reported mismatch rather than a
# silently skipped row.
BLOCKING_COLS = {"id", "sev", "phase", "state"}
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
        # It used to arrive from `subagent-driven-development`'s reviewer, which
        # pipeline invoked once per task until Stage 4 became
        # `references/implement.md`; that reviewer emits `Important`, whose
        # contract is "fix everything before this task completes" — right for
        # one task's diff, wrong for a phase, because this skill's blocking list
        # is closed and different. In one 141-finding run, 50 findings gated
        # phase advancement under a tier that appeared NOWHERE in the skill.
        #
        # REMOVING THAT CALLER DOES NOT CLOSE THE HOLE, which is why this arm
        # outlived it: the repo `/review` skill and any reviewer a project
        # supplies can emit `Important` too, and its unit-scoped contract is
        # still wrong for a phase. So the rule stands unchanged — the skill may
        # name the tier only alongside the sentence that re-tags it; naming it
        # without one is how the leak got in.
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
                # A DELETION'S CONSEQUENCE, REVERSED. This phrase used to be
                # `opens no re-review round`, which was the defect: deleting the
                # claim is a repository change and a deletion-only commit is
                # still a commit, so `finding → delete text → mark closed → no
                # review` was a legal path. The rule it pins now is the
                # opposite one, and it is pinned for the same reason — an
                # unheld rule is one edit from gone on a green build.
                "deleting the claim is a repository change",
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
            # every one of those files holds that phrase — and it must stay
            # byte-identical across them, which is the whole point of holding a
            # phrase rather than a meaning.
            #
            # Unconditional, NOT gated on the cross-reference still being
            # present. Gating it would let one edit that removes the
            # cross-reference and the bullet together pass green — the same hole
            # by two deletions instead of one.
            # `M`'s DEFINITION is held here too, and separately from the
            # condition. The entries above hold the CONSEQUENCE
            # (`m=0 → no round`, the exclusions) in the files that state it, but
            # nothing held the sentence `M` is *stated in terms of*: deleting
            # the whole `**Unless `M=0`.**` paragraph — the definition and its
            # closed route list together — left `check-plugin: PASS` and every
            # mutant killed, because the phrase the no-round arm reads occurs in
            # that file only inside a worked-example fence. A condition whose
            # subject is undefined is the same hole one level up from the one
            # those entries closed.
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
            # THE SIZING RULE THE EXCLUSIONS QUALIFY was held by nothing.
            # The entries above hold what `M` is, what it excludes and what
            # `M=0` licenses — the consequences — while the rule they are
            # consequences OF, one reviewer per file cluster in the fix diff,
            # had no arm: reverting the fan-out table's rows, the file-cluster
            # bullet and the Invariant to a count over the findings left
            # `check-plugin: PASS` with every mutant killed (measured). So the
            # sizing phrase is held too, in both files that state the rule.
            #
            # MORE THAN ONE HOME PER FILE IS DELIBERATE in the authority:
            # the phrase sits on the fan-out table's own row AND in the
            # Invariant. A home only in the Invariant would put it in the same
            # paragraph the claim-finding mutant deletes wholesale, and that
            # mutant would then die by two arms with neither individually
            # load-bearing — the attribution defect that split the
            # `M`-exclusion bullet's mutants in two. With the row carrying it
            # as well, that deletion leaves this arm silent and stays
            # attributable.
            #
            # `SKILL.md`'s copy is held for the reason every second copy in
            # this arm is: an unheld copy is one edit from gone on a green
            # build, whatever else happens to reach it.
            #
            # THE `M=0` LICENCE RULE is held in `SKILL.md` by a phrase its
            # WORKED EXAMPLE DOES NOT CARRY. The entry above holds
            # `m=0 → no round`, and in `SKILL.md` that phrase occurs in the
            # rule prose and again inside the fence, so deleting the whole rule
            # — the licence, the route list, the pin exclusion — while keeping
            # the fence left the gate green (measured). The fence cannot carry
            # "is the only declaration that licenses it", which is why that is
            # the phrase.
            #
            # SCOPED TO `SKILL.md`, though `references/run-state.md` states the
            # same rule in the same words. There the sentence sits in the very
            # paragraph the "no-round RV form deleted from run-state.md" mutant
            # removes, so holding it in both files would make that mutant die
            # by two arms. run-state.md's copy is prose only — it has no fence
            # for a deletion to hide behind — so the existing entry already
            # holds it, and this one does not need to.
            # THE RULES THE LAST TWO COMMITS ADDED, held here for the reason
            # every phrase above is: each was measured DELETABLE on a green
            # build, one at a time, `check-plugin: PASS` after each. Two of
            # them are worse than an unheld rule, because the LINTER hard-FAILs
            # what they describe — every `M=` round without a `C`, and every
            # round of two or more slices repeating a range — so deleting the
            # prose leaves the gate red on a rule no document states, with a
            # REMEDY string as the only surviving description of it.
            #
            # THREE ENTRIES FOR THE `C=<n>` RULE, one per file, because the
            # three texts word it differently and no phrase spans them: the
            # authority says the count "rides the round", `SKILL.md` that it
            # "is recorded on the round", `references/run-state.md` that the
            # round "writes" it. A shared phrase would have been better and
            # was not available without rewriting all three; three phrases
            # each held in their own file is the same guarantee, and each
            # mutant is attributable to the file it names.
            #
            # THE DISTINCTNESS RULE IS TWO RULES, and they are held apart. The
            # `coverage` table's version — no two ROWS — is about recorded
            # evidence and lives in the two files that define the `RV` grammar;
            # the fix-diff version — no two SLICES — is about assignment and
            # lives in the authority's *Re-review fan-out* and in `SKILL.md`'s
            # summary of it. Either can go while the other stands.
            #
            # THE ONE CROSS-REFERENCED EXCEPTION is held because other
            # sites cite it BY NAME rather than restating it. The
            # Invariant's reviewer-evidence exception is cited as
            # `references/fix-loop.md`'s *Invariants* from that file's own
            # ledger step and from `SKILL.md` in two places — grep the marker
            # for the current set — and delete it and every one of those
            # citations dangles while the texts still read as if the rule were
            # somewhere.
            #
            # There were TWO. The second was the pre-`RV` round's recording
            # rule, and it went with the pre-`RV` round itself: a build gate
            # failing before any reviewer exists is unfinished implementation
            # now, repaired inside IMPLEMENT, so there is no such round to
            # record and no rule to hold. Do not restore it looking for a
            # missing pair — `references/implement.md` states the replacement,
            # and the sweep for a task-level review is what holds it.
            #
            # THE COVERAGE ROW GRAMMAR is held because an ARM READS IT. This
            # gate takes the report key from a row's first cell and the range
            # from its second; the grammar used to pin neither, so a table
            # conforming to the words with a column in between was reported
            # for over-fan-out (measured, see `cov_rows`). The column and the
            # row-per-report duty are now prose, which is what makes the arm's
            # assumption an assumption no longer — so the prose has to be held
            # or the arm is back to guessing.
            # Mutants: "M-exclusion phrase blurred in fix-loop.md",
            #          "coverage-union phrase blurred in fix-loop.md",
            #          "no-round RV form deleted from fix-loop.md",
            #          "no-round RV form deleted from SKILL.md",
            #          "no-round RV form deleted from run-state.md",
            #          "M's definition paragraph deleted from fix-loop.md",
            #          "M's definition blurred in fix-loop.md",
            #          "M's exclusion-route list loses a route",
            #          "the fan-out sizing rule blurred in fix-loop.md",
            #          "the fan-out sizing rule blurred in SKILL.md",
            #          "the fan-out sizing rule blurred in README.md",
            #          "the M=0 licence rule deleted from SKILL.md",
            #          "the re-review C rule blurred in fix-loop.md",
            #          "the C rule blurred in SKILL.md",
            #          "the C clause blurred in run-state.md",
            #          "the coverage-row distinctness rule blurred in SKILL.md",
            #          "the coverage-row distinctness rule blurred in run-state.md",
            #          "the slice distinctness rule blurred in fix-loop.md",
            #          "the slice distinctness rule blurred in SKILL.md",
            #          "the Invariant's reviewer-evidence exception blurred in fix-loop.md",
            #          "the coverage-row grammar blurred in SKILL.md",
            #          "the coverage-row grammar blurred in run-state.md".
            # ONE CLAUSE PER ENTRY, carried on the entry. The message used to
            # enumerate what all five phrases do on every firing — 191 words,
            # emitted per (entry × file), 5,818 bytes of near-identical prose in
            # a five-firing run — and four of those clauses named a phrase that
            # had not gone missing. The full rationale is this comment; a CI
            # line gets the clause belonging to the phrase that fired.
            AUTH = ("references/fix-loop.md",)
            CLAIM_EFFECT = (
                ("the `M`-inclusion bullet", "is counted in `m`", AUTH,
                 "Lose it and a deletion is back outside `M`, closing a "
                 "finding with a commit nobody reviews."),
                ("the coverage-union rule",
                 "every commit the fix-mode run produced", AUTH,
                 'Lose it and a deletion\'s commit drops back out of the '
                 'union it is owed a place in.'),
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
                 "excluded exactly when its closure route **changed "
                 "nothing in the repository**", AUTH,
                 "Lose it and the list stops being keyed on whether the "
                 "repository changed, which is the whole of the rule."),
                ("the narrow definition of `withdrawn`",
                 "may be marked `withdrawn` only *before* any fix commit for",
                 AUTH,
                 "Lose it and `withdrawn` becomes the escape hatch — "
                 '"the orchestrator disagrees" wearing a closure route.'),
                ("the re-review fan-out's sizing rule",
                 "one reviewer per file cluster",
                 ("references/fix-loop.md", "SKILL.md", "README.md"),
                 "Lose it and the rule the fan-out table's rows encode is "
                 "stated nowhere, and a count over the findings can take its "
                 "place again."),
                ("the `M=0` licence rule",
                 "is the only declaration that licenses it", ("SKILL.md",),
                 "Lose it and the rule goes while the worked example keeps "
                 "the phrase the `M=0 → no round` entry reads."),
                ("the `C=<n>` rule, in the authority",
                 "the cluster count rides the round as `c=<n>`", AUTH,
                 "Lose it and the gate hard-FAILs every `M=` round without a "
                 "`C` on a rule the authority no longer states."),
                ("`SKILL.md`'s statement of the `C=<n>` rule",
                 "cluster count is recorded on the round as `c=<n>` and `s` "
                 "must equal it", ("SKILL.md",),
                 "Lose it and the section a reader consults to size a "
                 "re-review stops naming the number `s` is checked against."),
                ("the `RV` grammar's `C=<n>` clause",
                 "writes its cluster count on the line as `c=<n>` and `s` "
                 "must equal it", ("references/run-state.md",),
                 "Lose it and the file that defines the line's fields stops "
                 "listing a field the line is rejected for omitting."),
                ("the coverage table's distinctness rule",
                 "no two rows carry the same range",
                 ("SKILL.md", "references/run-state.md"),
                 "Lose it and the gate hard-FAILs a repeated range on a rule "
                 "the `RV` grammar no longer carries."),
                ("the fix-diff slices' distinctness rule",
                 "no two slices carry the same range",
                 ("references/fix-loop.md", "SKILL.md"),
                 "Lose it and the assignment side of the same prohibition is "
                 "gone, leaving only the recorded-evidence side."),
                ("the Invariant's reviewer-evidence exception",
                 "the round forms that carry no reviewer evidence are the "
                 "whole of the exception", AUTH,
                 "Lose it and every site that reads the exception from here "
                 "rather than restating it cites a rule stated nowhere."),
                ("the coverage table's row grammar",
                 "keyed by its report filename, with that reviewer's exact "
                 "range in the row's second cell, and every report file the "
                 "round names has a row of its own",
                 ("SKILL.md", "references/run-state.md"),
                 "Lose it and the arm reading a row's second cell is back to "
                 "assuming a column position no grammar pins."),
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
            # STAGE 5 RUNS THE `--run` LINTER, AND SAYS SO IN THE HAND-OFF.
            # `--run` was invoked from nowhere but CI, against this repo's own
            # fixture: no run pointed it at its own tracker, so the mode was
            # documentation. Stage 5 is where it belongs — the run's one
            # independent pass over lines whose author had the motive to skip
            # them — and the duty is now stated there.
            #
            # THE RULE MAKES ABSENCE VISIBLE RATHER THAN SILENT, which is what
            # the second phrase holds. `tools/` is a sibling of `plugins/`, so
            # the linter does not ship with the plugin and a run in any other
            # project may have no checkout to run it from. A bare command in
            # the skill would be a dangling citation — the `tools/build.sh`
            # class of leak. So Stage 5 either quotes the output or states that
            # the linter was unavailable and the tracker went unchecked, and an
            # omitted item is neither.
            #
            # TWO PHRASES, ONE PER HALF, so a kill names which half went. The
            # duty phrase has two homes in `SKILL.md` (the Stage 5 body and the
            # hand-off list) and the arm reads flattened text, so a mutation
            # that leaves one standing is a no-op — the same shape as the
            # sizing rule's two homes.
            #
            # SCOPED TO `SKILL.md` because that is the only file carrying
            # this duty — not because a second copy would be safe. Other files
            # do place their own obligations on the Stage 5 hand-off
            # (`templates/findings.md` and `references/fix-loop.md` both require
            # the deferred-Minors table there), so a second copy of this one is
            # possible in principle, and a copy written later needs its own
            # entry the way every second copy in this arm's neighbours does.
            # The linter paragraph in *The `RV` line* deliberately does not
            # repeat the duty phrase — if it did, blurring Stage 5's two copies
            # would leave this arm green.
            # WHAT A `FAIL` DOES IS THE THIRD OBLIGATION, and it was
            # undefined. Stage 5's by-hand pass says a line that fails what it
            # owes is "an unreviewed phase wearing a green tick — treat it as
            # `[ ]`", while the linter clause said only that the result "goes
            # in the hand-off either way rather than being a gate". The
            # linter's checks are a SUPERSET of that hand count, so one defect
            # reopened `RV` when a human found it and shipped as a hand-off
            # line when the linter found it. The clause that closes it is held
            # here, with the two duties, because it is the same passage's third
            # obligation and was equally deletable.
            # Mutants: "Stage 5's linter duty blurred in SKILL.md",
            #          "Stage 5's linter-unavailable duty blurred in SKILL.md",
            #          "Stage 5's linter-FAIL rule blurred in SKILL.md".
            STAGE5_LINT = (
                ("the duty to run the linter over the run's own tracker",
                 "over this run's own directory",
                 "Lose it and `--run` is invoked from CI over this repo's own "
                 "fixture and from nowhere else, which is the state that made "
                 "the mode documentation."),
                ("the statement that stands in for the linter's absence",
                 "the linter was unavailable, so the tracker's review lines "
                 "went unchecked",
                 "Lose it and a hand-off with no linter line is "
                 "indistinguishable from one whose linter passed — and the "
                 "linter is a sibling of `plugins/`, so absence is the common "
                 "case, not the odd one."),
                ("the rule that a linter `FAIL` on a check the by-hand pass "
                 "also owes is that pass failing",
                 "`fail` on any check the by-hand pass also owes is that pass "
                 "failing",
                 "Lose it and the same defect reopens `RV` when a human finds "
                 "it and ships in a hand-off line when the linter finds it, "
                 "because the linter's checks are a superset of the hand "
                 "count."),
            )
            st, se = read(sdir / n / "SKILL.md")
            if se:
                bad(f"{n}/SKILL.md must carry Stage 5's linter duty, but that "
                    f"file cannot be read: {se}")
            else:
                sflat = " ".join(st.split()).lower()
                for lbl, q, why in STAGE5_LINT:
                    if q not in sflat:
                        bad(f"{n}/SKILL.md is missing {lbl} ({q!r} absent). "
                            f"{why} REMEDY: restore the wording in Stage 5 — "
                            "the phrase is required verbatim, since a duty "
                            "held by no phrase is one edit from gone on a "
                            "green build")
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
        # states it. Each requirement the skill's dispatch contract carries
        # was one edit from gone before this arm:
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
        # RULE 5b'S ONE EXCEPTION IS HELD ALONGSIDE THE PROHIBITION, and
        # separately from it, because it is the half that fails SILENTLY. Lose
        # the prohibition and briefs start restating code facts, which the
        # receiving agent's refusal duty still catches. Lose the exception and a
        # task's `Files:` block becomes a stated file list — indistinguishable,
        # under the prohibition alone, from the thing the rule forbids — so the
        # correct behaviour becomes refusing every dispatch that carries one,
        # and `references/parallel.md`'s argument that no derivation can stand
        # in for those paths is cited by a rule that no longer admits them.
        # Measured deletable on a green build in BOTH files, which is why both
        # hold it: the two ends are edited independently, and the rule says the
        # exception holds "at both ends" precisely because either end alone
        # reopens it.
        # Mutants: "Rule 5b's prohibition blurred in SKILL.md",
        #          "Rule 5b's prohibition blurred in run-state.md",
        #          "the brief-refusal duty blurred in run-state.md",
        #          "the kit.md citation blurred in run-state.md",
        #          "kit.md's GATE 2 writing point blurred in SKILL.md",
        #          "the ticket-key question blurred in SKILL.md",
        #          "the ticket key's dispatch field blurred in run-state.md",
        #          "Rule 5b's Files: exception blurred in SKILL.md",
        #          "Rule 5b's Files: exception blurred in run-state.md".
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
                ("Rule 5b's `Files:` exception, in the Law",
                 "a task's `files:` block is the exception, at both ends", LAW,
                 "Lose it and the one file list a brief must carry reads as "
                 "the file list the prohibition forbids."),
                ("Rule 5b's `Files:` exception, in the contract",
                 "the task's own `files:` block being the one exception that "
                 "rule names", CONTRACT,
                 "Lose it and the receiving agent's refusal duty, stated in "
                 "the same breath, applies to the block it must accept."),
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
        # EVERY RUN-STATE FILE THE TREE NAMES SHIPS A TEMPLATE, and nothing
        # held that. `references/run-state.md` draws the run directory as a
        # tree and says, one line under it, that `templates/` ships a template
        # for each of those files; removing `templates/kit.md` left
        # `check-plugin: PASS` with every mutant killed (measured), so the
        # claim was false on a green build and GATE 2's step cited a file that
        # was not there. It is the far end of the pointer `DISPATCH_CONTRACT`
        # holds elsewhere: that arm's own argument is that a citation to a file
        # GATE 2 no longer writes is a dangling pointer, and this is the file.
        #
        # READ FROM THE TREE, never from a list in this file. A hard-coded list
        # of run-state files would be a second copy of that directory's
        # contents, wrong the first time a file joins it — the same failure as
        # the counts the arm below replaced, one level out. The tree is located
        # by the run path inside it rather than by fence ordinality, and both
        # the fence and the names it yields are required: an arm whose subject
        # can vanish from the docs is an arm that silently starts checking
        # nothing.
        #
        # WHAT IT ESTABLISHES is that a file named in the tree has a template
        # of the same name — not that the template says anything, and not the
        # converse, since `templates/` may legitimately hold a template for
        # something the tree does not draw.
        # Mutants: "a run-state file the tree names loses its template".
        if n == "pipeline":
            RSREL = "references/run-state.md"
            rst, rserr = read(sdir / n / RSREL)
            if rserr:
                bad(f"{n}/{RSREL} draws the run directory this arm reads, but "
                    f"that file cannot be read: {rserr}")
            else:
                trees = [b for b in re.findall(r"```[^\n]*\n(.*?)```", rst, re.S)
                         if "docs/superpowers/runs/" in b]
                names = sorted({m.group(1) for b in trees
                                for m in re.finditer(r"^\s+(\S+\.md)\b", b,
                                                     re.M)})
                if len(trees) != 1 or not names:
                    bad(f"{n}/{RSREL} no longer holds exactly one fenced run "
                        "directory tree naming at least one `.md` file "
                        f"({len(trees)} such fences, {len(names)} names), so "
                        "this arm can no longer check that each of those files "
                        "ships a template and is checking nothing on a green "
                        "build. REMEDY: keep the tree, or delete this arm with "
                        "the claim that a template ships for each of its files")
                for nm in names:
                    if not (sdir / n / "templates" / nm).exists():
                        bad(f"{n}/{RSREL} names {nm} in the run directory tree "
                            f"and says a template ships for each of those "
                            f"files, but templates/{nm} does not exist. A run "
                            "copies its state files from that directory, and a "
                            "name with no template behind it is a step in "
                            "Stage 1 or GATE 2 with nothing to copy. REMEDY: "
                            f"add templates/{nm}, or stop naming it in the "
                            "tree and in the sentence under it")
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
       "form present in every file that defines the `RV` grammar, `M` "
       "defined in one place with no exclusion-less gloss that names `M` ahead "
       "of the count and the F-IDs it glosses, every requirement of the "
       "dispatch contract held in the file that states it — Rule 5b's one "
       "`Files:` exception included — the re-review sizing phrase present in "
       "every file that states it, the `C=<n>` rule and both distinctness "
       "rules and the coverage table's row grammar present in every file that "
       "states them, the `RV` evidence exception present in the authority "
       "that the sites citing it read it from, Stage 5's linter duty, its "
       "absence statement and what it does "
       "with a `FAIL` all held, the `M=0` "
       "licence rule present in `SKILL.md` by a phrase its worked example "
       "does not carry, a template shipped for every run-state file the "
       "run-directory tree names, and no count of the "
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
        # `--run` IS A SECOND MODE, AND `refs` CANNOT SEE IT: the pattern above
        # stops at the first space, so a workflow that runs the gate with no
        # arguments and one that also lints a run directory are identical to it.
        # For the whole life of the mode CI ran only the first, which left every
        # run-mode arm exercised by nothing but the mutant harness's own
        # baseline — where a break surfaces as "the clean copy does not pass"
        # and stops the harness, not as itself. Held on the raw text.
        #
        # AND EVERY FIXTURE RUN DIRECTORY MUST BE NAMED, not just one. Fixtures
        # exist because a run state has arms no other input reaches; a fixture
        # CI never lints is a happy path exercised only by the harness's
        # baseline, which is the very gap the paragraph above describes. Adding
        # the third fixture is what made "at least one `--run`" too weak: two of
        # the three would have satisfied it while going unrun.
        # Mutants: "CI stops running the gate in run mode",
        #          "CI stops linting one of the fixture run directories".
        if "check-plugin.sh --run " not in t:
            bad("checks.yml never runs ./tools/check-plugin.sh with `--run` — "
                "the run mode's arms are then exercised by no CI step, and a "
                "break in them reaches you as a mutant-harness abort instead "
                "of as the failure it is. REMEDY: keep a "
                "`./tools/check-plugin.sh --run tools/fixtures/run-ok` step "
                "beside the bare one")
        _fxroot = ROOT / "tools/fixtures"
        _fx = sorted(d for d in _fxroot.glob("*") if (d / "progress.md").is_file()) \
              if _fxroot.is_dir() else []
        for _d in _fx:
            _rel = _d.relative_to(ROOT).as_posix()
            # EXACT STEP, not a substring: `--run tools/fixtures/run-ok`
            # occurs inside `--run tools/fixtures/run-ok-2`, so a substring
            # test lets one fixture's step satisfy another's requirement. The
            # step must end at the path.
            if not re.search(r"--run\s+" + re.escape(_rel) + r"(?:\s|$)", t, re.M):
                bad(f"checks.yml never lints {_rel} with `--run` — it holds a "
                    "`progress.md`, so it is a fixture run directory that "
                    "exists to exercise arms no other input reaches, and CI "
                    "runs none of them over it. REMEDY: add a "
                    f"`./tools/check-plugin.sh --run {_rel}` step, or delete "
                    "the fixture")
        if not FAIL: ok(f"checks.yml runs {len(refs)} scripts, all present and "
                        f"executable, and lints all {len(_fx)} fixture run "
                        "directories with `--run`")

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
# The declared slice count IS checked against `ceil(N/5)` for EVERY `N=` phase.
# There is no wave regime and no exemption: reviewer count comes from the task
# count and from nothing else, so implementation scheduling cannot buy a
# smaller review. `W=<n>` may ride the line for implementation history and is
# parsed and IGNORED for arithmetic. An `M=` round is sized by clusters and
# declares `C`; an `RVJ` is always `0 slice + 1 integration`. The arm's own
# comment carries the scope argument.
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
#          "no-round round names a pinned route",
#          "M=0 second closure is a bare withdrawn",
#          "M=0 second closure is a deletion",
#          "M=0 second closure names no route at all",
#          "run ledger withdrawn row names a fix commit",
#          "run tracker fix round names no fix plan",
#          "run tracker cites a fix plan that is not in agent-output".
print("\n== pipeline review-line examples ==")
start = re.compile(r"(?:-\s*)?\[x\]\s*(RVJ|RV)\b|(?:->|→)\s*(round)\s+\d+\s*:")
decl  = re.compile(r"(?P<key>N|M)=(?P<n>\d+)\s*(?:W=(?P<W>\d+)\s*)?(?:C=(?P<C>\d+)\s*)?"
                   r"(?:->|→)\s*(?P<s>\d+)\s*slice\s*\+\s*(?P<i>\d+)\s*integration")
rpt   = re.compile(r"reports\s+(.+?)(?=\s*[·|]|\s+coverage\b|\s*$)")
cov   = re.compile(r"coverage\s+\S+\.md")
nor   = re.compile(r"\bM=0\s*(?:->|→)\s*no\s+round\b")
fixp  = re.compile(r"fixplan\s+(\S+\.md)")
# ROUTES ARE KEYED ON WHETHER THE REPOSITORY CHANGED, not on the route's name.
# `deleted` used to sit beside `user-ruled false positive` on the reasoning that
# neither leaves a commit a reviewer could be assigned — true of a false
# positive, false of a deletion. A deletion-only commit is still a commit, so a
# deletion takes the fix loop like any other finding and is not a closure here.
#
# `withdrawn` MUST STATE ITS REASON. A bare `withdrawn` is the escape hatch the
# rule forbids: it absorbs "the orchestrator disagrees" and "the finding seems
# low value", which are routes INTO the fix loop, not out of it.
CLOSURE_OK = re.compile(
    r"F-\d+\s*,?\s+(?:user-ruled false positive"
    r"|withdrawn\s*(?:->|→)\s*"
    r"(?:superseded by F-\d+|duplicate of F-\d+|malformed))\b", re.I)
pinrt = re.compile(r"\bpinned by\b")


def parse_closures(body):
    """Every F-ID in an `M=0` record's closures list, with its route's verdict.

    Returns `(ok_ids, problems)`, `problems` being `(fid, offending text)`.

    EVERY F-ID IS VALIDATED INDEPENDENTLY. The old check was one
    `route.search(body)` — "is there at least one legal route ANYWHERE in this
    record" — so a valid first closure masked every invalid one after it:
    `closures: F-018 user-ruled false positive, F-019 withdrawn` passed with
    F-019 carrying the bare route the rule exists to refuse.

    An F-ID INSIDE a route is not a closure of its own. `withdrawn → duplicate
    of F-011` names F-011 as the reason, not as a second finding being closed,
    so the span a valid closure consumed is skipped rather than re-read.
    """
    seg = body
    m = re.search(r"closures?\s*:", seg, re.I)
    if m:
        seg = seg[m.end():]
    # The OUTCOME SLOT is not part of the closures list. `→ no findings` ends
    # it, and so does a bare outcome naming F-IDs — those are the round's
    # result, not routes.
    m = re.search(r"(?:->|→)\s*no findings\b", seg, re.I)
    if m:
        seg = seg[:m.start()]
    ok_ids, probs, spans = [], [], []
    for m in re.finditer(r"F-\d+", seg):
        if any(a <= m.start() < b for a, b in spans):
            continue
        g = CLOSURE_OK.match(seg, m.start())
        if g:
            ok_ids.append(m.group(0))
            spans.append((g.start(), g.end()))
        else:
            tail = seg[m.end():m.end() + 60].split(",")[0].strip(" ·|")
            probs.append((m.group(0), tail[:40]))
    return ok_ids, probs
outc  = re.compile(r"(?:->|→)\s*(?:no findings\b|F-\d+)")


def outcome_fids(rec):
    """The F-IDs a record's OUTCOME names — not every F-ID it mentions.

    The outcome slot is the LAST `→ no findings` / `→ F-NNN` in the record, so
    prose earlier in it that happens to cite an F-ID — a `boundary:` note, a
    `scope:` note — is not read as this gate's findings. Over-collecting there
    would demand a fix round for a finding the gate never raised, which is a
    false FAIL on a conforming tracker: the failure mode this repository has
    paid for most.
    """
    last = None
    for last in outc.finditer(rec):
        pass
    return re.findall(r"F-\d+", rec[last.start():]) if last else []
def expand_braces(spec):
    """`p3-review-{a,b,int}.md` -> the three names; a plain list passes through.

    Counting and naming had to agree, or the existence check below would look
    for a file called `p3-review-{a,b,int}.md`, which no run ever writes. They
    now agree BY CONSTRUCTION rather than by assertion: `nfiles` is the length
    of this list, so there is no second splitter to drift from this one.
    That is not a tidying preference. The two used to split differently — this
    one on `[,\s]+`, `nfiles` on `,` alone — while a docstring here asserted
    they counted the same spec. A whitespace-separated `reports` list, which
    nothing in the grammar forbade, was read as three reviewers and one file
    (measured: "declares 3 reviewers, lists 1 report files"), so a conforming
    round was accused of under-filing. The claim is deleted and the divergence
    with it.
    """
    spec = spec.strip()
    m = re.search(r"\{([^}]*)\}", spec)
    if not m:
        return [x for x in re.split(r"[,\s]+", spec) if x.endswith(".md")]
    pre, post = spec[:m.start()], spec[m.end():]
    return [f"{pre}{x.strip()}{post}" for x in m.group(1).split(",") if x.strip()]

def nfiles(spec):
    """How many reviewer reports a `reports` spec names — one splitter only."""
    return len(expand_braces(spec))

def cov_rows(text):
    """A coverage table's rows: report-filename key -> the range cell verbatim.

    The grammar (`SKILL.md`, the `coverage <file>` field) is a table "each row
    keyed by its report filename, with that reviewer's exact range" above the
    `git log`. So a row is any `| key | range |` line; the header and the
    `| --- | --- |` separator are dropped by shape rather than by position,
    since neither carries a range and a table may be written without either.

    The COLUMN IS PINNED BY THAT GRAMMAR, not assumed here: the range is the
    row's SECOND cell, and every report file the round names has a row of its
    own. That wording is new, and `cells[1]` is why. The grammar used to say
    only "each row keyed by its report filename, with that reviewer's exact
    range" — no column count and no order — so a table satisfying it with a
    column in between was read wrong: on

        | report | reviewer | range |
        | p3-review-a.md | slice | ccccccc^..ccccccc |

    every slice came back with the range `slice`, and the round was reported
    for handing two reviewers one range (measured) — a run accused of the
    exact over-fan-out this arm exists to catch. The fix is the grammar, not a
    heuristic here: pinning the column makes that layout non-conforming and
    the assumption a held sentence, and a table with FURTHER columns after the
    range still reads correctly (measured, passing).

    The range cell is kept VERBATIM (bar surrounding whitespace and backticks),
    never parsed into endpoints. Two reviewers over one cluster is a
    byte-equality question, and comparing whole cells means a slice written as
    two ranges, or with a comment after it, still compares as what it is. The
    first row wins a repeated key, which only ever loses information about a
    table that already contradicts itself.
    """
    out = {}
    for ln in text.split("\n"):
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [x.strip().strip("`").strip() for x in ln.strip("|").split("|")]
        if len(cells) < 2:
            continue
        k, v = cells[0], cells[1]
        if not k or not v or set(v) <= set("-: "):
            continue
        out.setdefault(k, v)
    return out

def relpath(p):
    """Repo-relative when the path is in the repo, absolute when it is not.

    A run directory is a caller's argument and need not sit under ROOT, so
    `relative_to` cannot be assumed — it raises, and a traceback is not a
    finding.

    NOT named `rel`: `rel` is bound as a loop and assignment variable at
    several module-scope sites above, and a helper of that name works only
    while every one of those bindings precedes the `def`. Hoisting the helper —
    the ordinary tidying edit — rebinds it to a `str`, and the next call raises
    `TypeError: 'str' object is not callable`.
    """
    try:
        return p.relative_to(ROOT)
    except ValueError:
        return p

def lint_review_lines(paths, agent_output=None, bullet_bounded=False):
    """Lint every closed RV/RVJ round found in `paths`.

    paths: iterable of .md files to scan.
    agent_output: when given, a directory each named report file must exist
        in. Available for a real run only — the skill's worked examples name
        illustrative files that were never written, so passing it there would
        fail the documentation for being documentation.
    bullet_bounded: how a record ENDS, and it differs by input.

        A tracker is a bullet list: a round is one `- [x] RV` bullet plus its
        wrapped continuation lines, and the next `- [` bullet is where it
        stops. So the run path ends the record THERE — no byte count.

        The worked examples are prose and fenced snippets with no such
        boundary, so they keep a 400-character window. That window was
        calibrated on those terse examples and is WRONG for a tracker: a real
        round record carries prose, and a `coverage` field sitting past 400
        flattened characters of its own start was reported as missing —
        measured, on a conforming file that passed once the prose was removed.
        Dropping the window for the examples too is not the fix: it lets
        `SKILL.md`'s worked re-review round, in *The `RV` line*, swallow the
        `M=0 → no round` paragraph that follows it and fires the no-round arm
        on both files that carry one (measured).

        The bounded form ends the LAST record at end-of-file, since there is
        no following bullet. That is the false-PASS direction — trailing prose
        could satisfy a field a malformed final round omitted — and it is the
        cheap one to accept: the alternative boundaries (a `#` heading, a
        fence) are line-shapes a tracker writes inside round records too, and
        each would re-open the false-FAIL this argument closes.
    Returns (closed_rounds, no_round_records, violations, gates), where
    `gates` is one dict per `RV`/`RVJ` mark in file order:
    `{"kind", "file", "line", "fids", "rounds"}`. `fids` are the F-IDs that
    gate's OUTCOME named; `rounds` is how many appended rounds hang under it.
    The run-mode gate-ownership arm reads it.
    """
    seen = nseen = viol = 0
    gates = []
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
        # EVERY APPENDED ROUND HAS AN OWNING GATE, and it is the nearest
        # preceding `RV`/`RVJ` mark. `kind` is `"round"` for every appended
        # record, so without this the gate a round hangs under is invisible to
        # every arm — and the reopen rule the prose used to state named `RV`
        # only, while an `RVJ`'s findings are required to run the fix loop
        # under the `RVJ`'s own Counters row. A round appended to a joining
        # phase's `RV` because its leading `RVJ` raised the findings spends
        # that phase's review budget on a join it never covered.
        owners, _own = [], None
        for _p, _k in marks:
            if _k in ("RV", "RVJ"):
                _own = len(gates)
                gates.append({"kind": _k, "file": relpath(f),
                              "line": lineno(_p), "fids": [], "rounds": 0})
            owners.append(_own)
        for idx, (pos, kind) in enumerate(marks):
            end = marks[idx + 1][0] if idx + 1 < len(marks) else len(flat)
            if bullet_bounded:
                nxt = flat.find("- [", pos + 1)
                if nxt != -1 and nxt < end:
                    end = nxt
            else:
                end = min(end, pos + 400)
            rec = flat[pos:end]
            _owner = gates[owners[idx]] if owners[idx] is not None else None
            if kind in ("RV", "RVJ"):
                _owner["fids"] = outcome_fids(rec)
            else:
                if _owner is None and bullet_bounded:
                    # A ROUND WITH NO GATE ABOVE IT belongs to nothing. Its
                    # budget, its coverage and its closure all hang off a gate,
                    # and there is none, so nothing this file says about it can
                    # be checked against anything.
                    viol += 1
                    bad(f"{relpath(f)}:{lineno(pos)}: an appended round "
                        "precedes every `RV`/`RVJ` line in this file — a round "
                        "is appended UNDER the gate that raised its findings, "
                        "and one with no gate above it has no owner, no "
                        "budget and no evidence anything can be checked "
                        "against. REMEDY: append the round under its own "
                        "gate's line")
                elif _owner is not None:
                    _owner["rounds"] += 1
                # TRACKER MODE ONLY, and that scope is the point. The skill's
                # prose teaches the round grammar with standalone fragments —
                # `references/fix-loop.md` shows a `→ round 3: M=0 → no round`
                # snippet with no gate above it, because the snippet IS the
                # grammar being taught. A tracker is different: there a round
                # with no gate above it is a real orphan. An arm that failed
                # the documentation for being documentation is the defect class
                # this repository has paid for most.
            if nor.search(rec):
                nseen += 1
                body = rec.split("```")[0] if "```" in rec else rec
                where = f"{relpath(f)}:{lineno(pos)}"
                probs = []
                if rpt.search(body):
                    probs.append("lists a `reports` field")
                if cov.search(body):
                    probs.append("lists a `coverage` field")
                if fixp.search(body):
                    probs.append("names a `fixplan` file — an `M=0` round "
                                 "dispatched no fix, so there was nothing to "
                                 "plan and no plan to name")
                if decl.search(body):
                    probs.append("declares reviewer counts as well as `no round`")
                _okids, _badids = parse_closures(body)
                if not _okids and not _badids:
                    probs.append("names no closure route — every F-ID needs "
                                 "`user-ruled false positive` or `withdrawn "
                                 "→ <reason>` after it")
                for _fid, _tail in _badids:
                    if re.match(r"deleted\b", _tail, re.I):
                        probs.append(
                            f"closes {_fid} by `deleted`, which no `M=0` round "
                            "can carry — deleting the claim is a repository "
                            "change, and a deletion-only commit is still a "
                            "commit, so it is owed a fix plan and a focused "
                            "re-review like any other fix")
                    elif re.match(r"withdrawn\b", _tail, re.I):
                        probs.append(
                            f"closes {_fid} by a bare `withdrawn` — a "
                            "withdrawal is a duplicate, a malformed finding, or "
                            "one superseded by another, and it must say which: "
                            "`withdrawn → duplicate of F-NNN`, `withdrawn → "
                            "superseded by F-NNN`, or `withdrawn → malformed`")
                    else:
                        probs.append(
                            f"gives {_fid} the route {_tail!r}, which is not a "
                            "zero-repository-change closure. Only `user-ruled "
                            "false positive` and `withdrawn → <reason>` are: "
                            "every other route leaves a commit, and a commit is "
                            "owed a fix plan and a re-review")
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
                        "round of nobody never had, and one naming a pin or a "
                        "deletion is not an `M=0` iteration at all. REMEDY: "
                        "write it as `→ round <n>: M=0 → no round · closures: "
                        "F-018 user-ruled false positive, F-019 withdrawn → "
                        "duplicate of F-011 → no findings`")
                continue
            d = decl.search(rec)
            if not d:
                # NARROWED TO THE FORM IT WAS WRITTEN FOR. This `continue`
                # predates the phase-state-machine branch — it exists so the
                # `WAIVED by user:` form, which carries no counts by design,
                # is not reported as malformed. But this branch hung two new
                # invariants (the fix-plan requirement and the conditional
                # integration reviewer) off the code path behind it, which
                # promoted a laxity into a bypass: a round written
                # `→ round 2: C=1 → 1 slice + 0 integration` parsed as nothing
                # and skipped six arms at once (measured PASS with no fix plan
                # named and none on disk). It is also self-concealing, because
                # `seen` is not incremented and a conforming round elsewhere
                # keeps `rseen` non-zero.
                # Mutants: "run tracker round loses its M= declaration".
                if "WAIVED by user:" in rec:
                    continue
                viol += 1
                bad(f"{relpath(f)}:{lineno(pos)}: closed {kind} record carries "
                    "no parseable `N=`/`M=` declaration — every arm that sizes "
                    "or scopes a round reads that declaration, so a record "
                    "without one is not a lax round, it is a round no check "
                    "reaches. REMEDY: write the declaration "
                    "(`N=<n> → <s> slice + <i> integration`, or "
                    "`M=<m> C=<c> → …` on a fix round), or, if the review was "
                    "waived, write the `WAIVED by user: \"<their words>\"` form")
                continue
            seen += 1
            nslice, nint = int(d.group("s")), int(d.group("i"))
            want = nslice + nint
            where = f"{relpath(f)}:{lineno(pos)}"
            if kind == "RVJ" and (nslice, nint) != (0, 1):
                viol += 1; bad(f"{where}: RVJ must be 0 slice + 1 integration, declares {nslice}+{nint}")
            # THE TWO ARITHMETIC ARMS. Both are shape, which is what this
            # section's own heading limits it to: `N`, `s` and `i` are all on
            # the line, so each of these is a sum a reader can do from the
            # line alone and neither reaches for the diff.
            #
            # `s == ceil(N/5)` FOR AN UNWAVED `N=` ROUND. The field row in
            # `SKILL.md` says that regime — and only that regime — makes the
            # fan-out "re-derivable from the line", and the fan-out table
            # states the same rule independently. It was nonetheless the one
            # regime nothing checked, and this repo's own conforming fixture
            # violated it: `N=9 → 3 slice + 1 integration`, where `ceil(9/5)`
            # is 2, passed both gates (measured). A rule two documents state
            # and no arm holds is the class of defect this gate exists for.
            #
            # SCOPED BY THE REGIME KEYS THE PARSER READS, and the scope is
            # three separate exclusions, not one:
            #   - `M=` rounds are excluded by `key`. `M` sizes nothing; an
            #     `M=` round is sized by its fix diff's clusters and declares
            #     that count as `C`, which the arm below reads instead.
            #   - THERE IS NO WAVE EXCLUSION. `waved` used to exempt a round
            #     from this arm outright, and the skill said plainly the wave
            #     count is not on the line and therefore not re-derivable — so
            #     `N=12 waved → 1 slice` and `N=12 waved → 9 slice` were both
            #     accepted, and a coarse wave table silently bought a smaller
            #     review. Waves schedule implementation; they do not size
            #     review. `W=<n>` is parsed and ignored here for exactly that
            #     reason: a tracker cannot buy fewer reviewers by declaring
            #     fewer waves.
            #   - `RVJ` is excluded by `kind`, and this one is NOT free. An
            #     `RVJ` declares `0 slice + 1 integration` with its `N` the task
            #     count across the reviewed unit, so its key is `N`: run
            #     without the `kind` test, the
            #     arm reports every worked `RVJ` record in the skill —
            #     `N=17 → 0 slice + 1 integration` — for declaring 0 where
            #     `ceil(17/5)` is 4 (measured, in each file that writes one).
            #     The `RVJ` shape arm above is what holds that form instead.
            #
            # `i` AT ONE SLICE IS 0; ABOVE ONE SLICE IT IS CONDITIONAL ON A
            # DECLARED BOUNDARY. It used to be 1 whenever `s > 1`, which spent a
            # third reviewer on every ordinary multi-slice phase whether or not
            # anything crossed between slices. It is now dispatched where
            # something crosses — siblings of a split joining, two lanes
            # joining, or a contract introduced in one slice and consumed in
            # another — and the round NAMES that boundary.
            #
            # THE ABSENCE IS DECLARED TOO. A silent omission and a considered
            # judgement read identically, and a review that reads as "not
            # needed" when nobody decided is how the fan-out went missing for
            # seven consecutive phases in the run that made `RV` a tracker line.
            # So a multi-slice round with no integration reviewer says
            # `no integration boundary`, and a reader can tell the two apart.
            #
            # At one slice `i` is still 0 unconditionally: that slice already
            # sees the whole diff, so a second reviewer over it is duplication,
            # not margin — a boundary cannot license it. `s == 0` is left alone:
            # that is the `RVJ` form, which the arm above owns entirely, and
            # `RVJ` keeps its fixed `0 slice + 1 integration` shape.
            # Mutants: "run tracker's N= round departs from ceil(N/5)",
            #          "run tracker buys a smaller review by declaring one wave",
            #          "run tracker declares an integration reviewer with no boundary",
            #          "run tracker multi-slice round is silent about its integration reviewer",
            #          "run tracker declares two integration reviewers",
            #          "worked one-slice round adds an integration reviewer",
            #          "run tracker boundary declares a bare dash".
            ntasks = int(d.group("n"))
            if kind == "RV" and d.group("key") == "N":
                want_s = -(-ntasks // 5)
                if nslice != want_s:
                    viol += 1
                    bad(f"{where}: `N={ntasks}` round declares {nslice} slice "
                        f"reviewers, but `ceil(N/5)` is {want_s}. Reviewer "
                        "count comes from the task count and from nothing "
                        "else — `N` is on the line precisely so a reader of "
                        "the tracker alone can re-derive it — and the wave "
                        "count never enters the arithmetic: implementation "
                        "scheduling must not reduce formal review coverage. "
                        "REMEDY: dispatch `ceil(N/5)` slice reviewers. `W=<n>` "
                        "may stay on the line as implementation history, but "
                        "it buys nothing here")
            if nslice > 1 and nint not in (0, 1):
                viol += 1
                bad(f"{where}: declares {nint} integration reviewers — the "
                    "integration slice is the whole diff, so there is at most "
                    "one. REMEDY: declare 0 or 1")
            # `NO INTEGRATION BOUNDARY` IS NOT A BOUNDARY, and neither is
            # `boundary: none`. The test reads a boundary as named only when
            # what follows the colon is not itself a negation — otherwise the
            # declaration that licenses dropping the reviewer would also
            # license keeping it, and the round would satisfy both arms at once.
            # A NEGATION AFTER `boundary:` IS NOT A BOUNDARY. The list is the
            # arm's whole content: a round cannot both license the integration
            # reviewer and say there is nothing for it to cover. Two corrections
            # from review: `-` and `—` sat inside the `\b` group, which needs a
            # word character after the dash, so `boundary: -` (dash, space) was
            # accepted — they are their own alternative now; and a word-count
            # requirement was dropped because it could never run, `rec` being a
            # flattened window whose following fields supply the words. Its
            # removal costs nothing: a one-word boundary like `boundary: seam`
            # is legitimate and must pass.
            elif (nslice > 1 and nint == 1
                  and not re.search(r"boundary:\s*(?![-—]\s|(?:none|no|not|"
                                    r"nothing|n/?a)\b)\S", rec, re.I)):
                viol += 1
                bad(f"{where}: declares an integration reviewer but names no "
                    "`boundary: <what>` — an unnamed boundary is the automatic "
                    "third reviewer this rule replaced, and above one slice a "
                    "reviewer with nothing named to cover reads the same diff "
                    "the slices already read. REMEDY: name the boundary it "
                    "covers — siblings of a split joining, two lanes joining, "
                    "or a contract introduced in one slice and consumed in "
                    "another — or declare `no integration boundary` and drop "
                    "the reviewer")
            elif nslice > 1 and nint == 0 and "no integration boundary" not in rec:
                viol += 1
                bad(f"{where}: declares {nslice} slice reviewers and no "
                    "integration reviewer, and does not say why — an omission "
                    "and a judgement read identically, which is how a review "
                    "goes missing without anyone deciding to skip it. REMEDY: "
                    "add `· no integration boundary` to the round, or add the "
                    "reviewer with its `boundary:`")
            elif nslice == 1 and nint != 0:
                viol += 1
                bad(f"{where}: declares 1 slice reviewer and {nint} "
                    "integration reviewers — at one slice `i` is 0, because "
                    "the one slice already sees the whole diff. A second "
                    "reviewer over that same diff is the duplication the "
                    "fan-out rule forbids, not a safety margin, and the "
                    "fan-out tables write no such row. REMEDY: declare "
                    "`1 slice + 0 integration`, or split the range into the "
                    "slices it really has")
            # AN `M=` RE-REVIEW ROUND CARRIES ITS CLUSTER COUNT, `C=<n>`, AND
            # `s` MUST EQUAL IT. The re-review fan-out is one reviewer per file
            # cluster in the fix diff (`references/fix-loop.md`, *Re-review
            # fan-out*), and until `C` was written on the round the count that
            # sizes it appeared nowhere: `s` had nothing on the line to be
            # checked against, and a reader of the tracker could not even say
            # which number the orchestrator claimed to have counted.
            #
            # WHAT THIS ARM IS FOR, exactly, and what it must not be read as.
            # It makes the cluster count an AUDITABLE STATEMENT — a later
            # reader can compare `C` against the ledger's fix hashes and
            # disagree with it — and it catches an ARITHMETIC SLIP between the
            # count and the fan-out, a round that counted three clusters and
            # dispatched four reviewers. It does NOT close the over-fan-out
            # hole, and no version of it can: `C` is written by whoever chose
            # `s`, so a round that put three reviewers on one cluster writes
            # `C=3` and is internally consistent. That hole is closed, for the
            # duplication half of it, by the coverage-table arm below, which
            # reads recorded ranges rather than a self-declared count.
            #
            # Scoped to `M=` rounds because `C` is defined over a fix diff's
            # clusters. An `N=` phase is sized over tasks (`ceil(N/5)`, or one
            # slice per wave) and has no cluster count to declare, so
            # requiring one there would reject every conforming phase round.
            # `M=0 → no round` never reaches here: the no-round arm above
            # `continue`s before the declaration is read.
            # Mutants: "re-review round loses its cluster count",
            #          "re-review round's cluster count disagrees with its slice count".
            if d.group("key") == "M":
                if d.group("C") is None:
                    viol += 1
                    bad(f"{where}: `M=` re-review round declares no `C=<n>` "
                        "cluster count. The re-review fan-out is one reviewer "
                        "per file cluster in the fix diff, so without `C` the "
                        "number that sizes the round is on no line any reader "
                        "can check `s` against, and the sizing is not even a "
                        "statement someone could disagree with. REMEDY: write "
                        "it beside `M` — `M=9 C=3 → 3 slice + 1 integration` — "
                        "with `C` the cluster count you counted in the ownable "
                        "fix diff")
                elif int(d.group("C")) != nslice:
                    viol += 1
                    bad(f"{where}: round counts {d.group('C')} file clusters "
                        f"but declares {nslice} slice reviewers — the "
                        "re-review fan-out is one reviewer per file cluster, "
                        "so these two numbers are the same number written "
                        "twice. REMEDY: correct whichever is wrong; if the "
                        "fan-out really did depart from the cluster count, it "
                        "was not sized by this rule")
            r = rpt.search(rec)
            got = nfiles(r.group(1)) if r else 0
            if got != want:
                viol += 1; bad(f"{where}: declares {want} reviewers, lists {got} report files")
            if not cov.search(rec):
                viol += 1; bad(f"{where}: closed review round with no coverage file")
            # A ROUND THAT DISPATCHED FIXES MUST NAME THE PLAN THEY CAME FROM.
            # `M=<m>` with m >= 1 IS that round: `M` is the count of blocking
            # F-IDs the fix run targeted, less every one closed by a route that
            # leaves no ownable commit, so m >= 1 means fix commits exist.
            # Findings -> fix plan -> fix implementation was prose only, and the
            # path for three-or-fewer findings explicitly skipped the plan,
            # which is how a round became a sequence of unplanned single fixes.
            # `M=0 → no round` records are excluded by the `nor` branch above,
            # which `continue`s before reaching here: no fix ran, so there was
            # nothing to plan.
            # AND AN APPENDED ROUND IS A FIX ROUND BY DEFINITION, SO IT IS
            # KEYED `M`. The requirement below was scoped to `key == "M"`,
            # which made it optional to anyone who wrote `N=` on a fix round:
            # `→ round 2: N=2 C=1 → 1 slice + 0 integration` with no `fixplan`
            # passed every arm (measured), because `ceil(2/5)` is 1 and the
            # `C=` arm is `M`-scoped too. `kind` is `"round"` for exactly the
            # appended records, so the round mark decides the key rather than
            # the key deciding its own scope.
            # Mutants: "run tracker fix round is keyed N instead of M".
            if kind == "round" and d.group("key") != "M":
                viol += 1
                bad(f"{where}: appended round is keyed "
                    f"`{d.group('key')}={d.group('n')}` — a re-review round is "
                    "sized by its fix diff's file clusters, not by a task "
                    "count, so it is keyed `M` with a `C=<n>` beside it. Keyed "
                    "`N`, it also escapes the fix-plan requirement, which is "
                    "scoped to fix rounds. REMEDY: write "
                    "`M=<m> C=<c> → <s> slice + <i> integration`")
            if d.group("key") == "M" and int(d.group("n")) >= 1:
                fp = fixp.search(rec)
                if not fp:
                    viol += 1
                    bad(f"{where}: round declaring `M={d.group('n')}` names no "
                        "`fixplan <file>.md` — fixes were dispatched with no "
                        "plan on disk for anyone to check them against. "
                        "REMEDY: write the round's fix plan to agent-output/ "
                        "and name it on the round")
                elif agent_output is not None and not (agent_output / fp.group(1)).exists():
                    viol += 1
                    bad(f"{where}: round names fix plan {fp.group(1)!r}, which "
                        "is not in agent-output/ — a named-but-absent plan "
                        "reads exactly like a planned round. REMEDY: write the "
                        "file, or correct the name")
            if agent_output is not None and r:
                for nm in expand_braces(r.group(1)):
                    if not (agent_output / nm).exists():
                        viol += 1
                        bad(f"{where}: report file {nm!r} is named on a closed "
                            f"round but is not in {agent_output.name}/ — a "
                            "round closes on reviewer evidence a later reader "
                            "can re-open, so a name with no file behind it is "
                            "a reviewer count that was never met")
            # THE COVERAGE FILE GETS THE SAME EXISTENCE CHECK AS THE REPORTS.
            # The `cov` test above establishes only that the FIELD is there, so
            # a round naming a coverage file nobody wrote passed (measured) —
            # while the same round's report names were checked against the
            # directory, leaving an asymmetry that was neither closed nor
            # written down. The two fields carry the same kind of evidence and
            # are owed the same test.
            # `agent_output`-gated for the reason the report loop is: the
            # skill's worked examples name illustrative files nobody wrote.
            # Its mutant is cited with the other run-mode ones, below.
            if agent_output is not None:
                c = cov.search(rec)
                if c:
                    cnm = c.group(0).split()[-1]
                    if not (agent_output / cnm).exists():
                        viol += 1
                        bad(f"{where}: coverage file {cnm!r} is named on a "
                            f"closed round but is not in "
                            f"{agent_output.name}/ — that file is the whole "
                            "of the round's claim that every commit fell "
                            "inside some slice, so a name with nothing behind "
                            "it is a coverage judgement no later reader can "
                            "re-open")
                    # TWO SLICE REVIEWERS OVER ONE RANGE, WHICH IS THE
                    # OVER-FAN-OUT THE SKILL FORBIDS IN PROSE AND NOTHING
                    # CHECKED. The prohibition has two homes:
                    # `references/fix-loop.md`'s *Re-review fan-out* — "two
                    # reviewers over one cluster duplicate each other" — and
                    # the wave rule in that file's dispatch step, where
                    # "splitting a wave's members across two reviewers is
                    # forbidden". Both gates nonetheless passed the fixture
                    # that broke it: this repo's own worked-conforming run
                    # declared three slice reviewers plus an integration
                    # reviewer over one commit, all four rows carrying one
                    # byte-identical range. The waste was not merely
                    # undetected in theory; it was encoded in the example the
                    # gate reads as conformance.
                    #
                    # THE RANGES ARE RECORDED DATA, which is why the check
                    # belongs here rather than on the declaration. `C=<n>`
                    # above makes the cluster count auditable, but it is
                    # self-declared: an orchestrator that over-fanned out
                    # writes `C=3` and passes. The coverage table's ranges are
                    # what the reviewers were actually handed, and two rows
                    # carrying the same range prove two reviewers read one
                    # diff whatever any count says.
                    #
                    # THE INTEGRATION ROW IS NOT EXCLUDED, and that is a
                    # decision, not an oversight. The instinct is to exclude
                    # it because its scope is the UNION of the slices — but a
                    # union of two or more slices recorded individually (the
                    # `coverage` field's own rule: "Record slices
                    # individually", since one union range reads as complete
                    # across a gap) is not byte-equal to any one of them, so
                    # excluding it cannot change the verdict on a conforming
                    # round. Including it buys one thing more: an integration
                    # reviewer handed a slice's exact range is an integration
                    # reviewer who structurally cannot do the job the grammar
                    # gives it — look for what single slices cannot see — and
                    # that round bought two reads of one diff instead.
                    # Measured both ways: the corrected fixture, whose
                    # integration row spans its three distinct slices, passes;
                    # renaming that report off the `-int` convention leaves it
                    # passing, because no arm here reads the name.
                    #
                    # SCOPED TO `s >= 2`. At `s == 1` there is one slice and
                    # nothing to be distinct from, and the fan-out tables give
                    # a one-slice round no integration reviewer ("the one
                    # slice sees all"), so a lone `1 slice + 1 integration`
                    # round — a form no table writes — would be the only thing
                    # the wider scope could catch, at the price of firing on
                    # it for a reason the grammar never states.
                    #
                    # NOT identified by name, position or count: the arm asks
                    # only whether two rows a round's own `reports` field names
                    # carry the same range. A naming convention (`-int.md`) is
                    # the weakest of the candidate identifications — it is
                    # unpinned by any grammar, so a run that names its reports
                    # anything else would be misread — and the row order and
                    # the `<i>` count are conventions too. Needing none of them
                    # is what makes this robust.
                    #
                    # The row LOOKUP is checked as well, and reported
                    # separately: a report with no row of its own has no
                    # recorded range, and reading distinctness over the rows
                    # that happen to be there would call that table conforming
                    # for being incomplete.
                    # Mutants: "run tracker's coverage table repeats a slice range",
                    #          "run tracker's coverage table loses a slice's row",
                    #          "run tracker's integration range collapses onto a slice's",
                    #          "run tracker's coverage file is unreadable".
                    elif nslice >= 2 and r:
                        ctext, cerr = read(agent_output / cnm)
                        if cerr:
                            viol += 1
                            bad(f"{where}: coverage file {cnm!r} exists but "
                                f"cannot be read: {cerr} — the round's slice "
                                "ranges are in that file and nowhere else, so "
                                "nothing here is a statement about whether "
                                "two of its reviewers were handed the same "
                                "diff, and in particular not that they were "
                                "not. REMEDY: make the file readable and run "
                                "again")
                        else:
                            rows = cov_rows(ctext)
                            byrng, norow = {}, []
                            for nm in expand_braces(r.group(1)):
                                rng = rows.get(nm)
                                if rng is None:
                                    hit = [v for k, v in rows.items() if nm in k]
                                    rng = hit[0] if hit else None
                                if rng is None:
                                    norow.append(nm)
                                else:
                                    byrng.setdefault(rng, []).append(nm)
                            if norow:
                                viol += 1
                                bad(f"{where}: coverage file {cnm!r} has no "
                                    "row for " + ", ".join(map(repr, norow))
                                    + ", which this round names as a report — "
                                    "the table is keyed by report filename "
                                    "precisely so each reviewer's range is on "
                                    "the record, and a reviewer with no row "
                                    "has no range a later reader can check "
                                    "against any other. REMEDY: give every "
                                    "report file its own row, with the exact "
                                    "range that reviewer was assigned")
                            dups = {k: v for k, v in byrng.items() if len(v) > 1}
                            if dups:
                                viol += 1
                                bad(f"{where}: coverage file {cnm!r} gives the "
                                    "same range to more than one reviewer: "
                                    + "; ".join(f"{', '.join(v)} all on {k!r}"
                                               for k, v in sorted(dups.items()))
                                    + ". Two reviewers over one range read the "
                                    "same diff and duplicate each other's "
                                    "findings, which is what the fan-out rule "
                                    "forbids — one reviewer per file cluster, "
                                    "and when in doubt one reviewer — and the "
                                    "integration reviewer's range is the union "
                                    "of the slices, so it is not equal to any "
                                    "one of them either. REMEDY: give each "
                                    "reviewer its own range, or dispatch fewer "
                                    "reviewers; a round whose clusters really "
                                    "were one cluster is a `1 slice + 0 "
                                    "integration` round")
    return seen, nseen, viol, gates

pdir = ROOT / "plugins" / "superb" / "skills" / "pipeline"
seen, nseen, viol, _ = lint_review_lines(pdir.rglob("*.md"))
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
       "reviewer counts, RVJ shape, `ceil(N/5)` sizing, the "
       "integration reviewer 0 at one slice and boundary-declared above one, "
       "`M=` cluster counts and "
       "coverage all conform, and every no-round record names its closure "
       "routes and carries no reviewer evidence")

# ---- pipeline dispatches implementation itself, so it owns the scripts ----
# The skill used to cite `scripts/task-brief` and `scripts/review-package` bare
# and relative while owning neither: they are `subagent-driven-development`
# internals, so the paths resolved from nothing the citing file could see, and
# an upstream rename would go unnoticed on a green build. Now that Stage 4
# dispatches implementers itself, the brief extractor is pipeline's own file and
# is checked like one: present, executable, and with a shebang, because a
# non-executable script fails at the first dispatch of a run.
#
# PLACED HERE, not beside the other pipeline sections above, because `relpath`
# is defined at module scope further up this file than those sections are and
# every message below needs it. Moving this block above `def relpath` raises
# `NameError` on the first FAIL — which is a red build for the wrong reason.
# Mutants: "pipeline task-brief script is missing",
#          "pipeline task-brief script is not executable",
#          "pipeline task-brief script loses its shebang".
# ---- the rules the migration review corrected stay corrected ----
# Round 1 of the whole-change review found four prose sites still carrying the
# retired rules, and the fixes pinned none of them — so each could rot back on
# a green build, which is the failure mode this repo answers with held phrases
# everywhere else. Each entry is (phrase, files that must carry it); the phrase
# is matched against FLATTENED text because prose reflows.
# Mutants: "the conditional integration rule reverts in fix-loop.md",
#          "the pre-RV repair rule reverts in parallel.md",
#          "the re-review boundary rule reverts in SKILL.md",
#          "the conditional integration rule reverts in templates/progress.md".
# The unreadable-pinned-file branch below carries NO mutant, deliberately: a
# skill file this gate cannot read trips several arms at once, so no mutation
# isolates this one and a citation would claim a proof nobody has. It is a
# defensive branch, verified by hand (chmod 000 over `references/parallel.md`
# reports it), and recorded here as unpinned rather than left to look watched.
print("\n== migration-corrected rules stay corrected ==")
_pinned = [
    ("only at a declared integration boundary",
     ["references/fix-loop.md", "SKILL.md", "templates/progress.md"],
     "the phase and re-review fan-outs both spend the integration reviewer on "
     "a named boundary; without this phrase the file prescribes the retired "
     "unconditional rule and a run following it writes a tracker this gate "
     "rejects"),
    ("raises no finding, takes no f-id",
     ["references/parallel.md", "references/implement.md"],
     "a build-gate failure before `RV` is unfinished implementation, not a "
     "finding; without this phrase the wave procedure sends it into the fix "
     "loop, which has no pre-`RV` entry any more"),
]
_pin_bad = False
for _phrase, _files, _why in _pinned:
    for _rel in _files:
        _pf = ROOT / "plugins/superb/skills/pipeline" / _rel
        _pt, _pe = read(_pf)
        if _pe:
            # NOT `continue`. A pinned file this gate cannot read is a pin it
            # did not check, and the pass line below would then claim the rule
            # is present in every file that states it.
            _pin_bad = True
            bad(f"pipeline/{_rel} cannot be read ({_pe}), so the pin on "
                f"\"{_phrase}\" checked nothing there. REMEDY: make the file "
                "readable and run again")
            continue
        if _phrase not in " ".join(_pt.split()).lower():
            _pin_bad = True
            bad(f"pipeline/{_rel} no longer carries \"{_phrase}\" — {_why}. "
                "REMEDY: restore the phrase, or, if the rule genuinely changed, "
                "change it in every file that states it and retire this pin")
if not _pin_bad:
    ok(f"{len(_pinned)} migration-corrected rules present in every file that "
       "states them")

print("\n== pipeline dispatch scripts ==")
_tb = ROOT / "plugins/superb/skills/pipeline/scripts/task-brief"
if not _tb.is_file():
    bad(f"{relpath(_tb)} does not exist — Stage 4 dispatches implementers "
        "itself and cites this script for the task brief, so every dispatch of "
        "every run fails at its first step. REMEDY: add the script, or stop "
        "citing it")
else:
    _tbt, _tbe = read(_tb)
    if _tbe:
        bad(f"{relpath(_tb)} cannot be read: {_tbe}")
    elif not _tbt.startswith("#!"):
        bad(f"{relpath(_tb)} has no shebang — it is invoked as a command, not "
            "sourced, so without one the kernel's fallback decides which shell "
            "runs it. REMEDY: start the file with `#!/bin/sh`")
    elif not (_tb.stat().st_mode & 0o111):
        bad(f"{relpath(_tb)} is not executable — a dispatch citing it gets "
            "'permission denied' at the first task of the phase. REMEDY: "
            "`chmod +x` it and commit the mode bit")
    else:
        ok("pipeline owns an executable task-brief script")

# ---- pipeline never asks for a review when one task completes ----
# Pipeline's own review layer is the phase-level `RV` fan-out. It used also to
# delegate implementation to `subagent-driven-development`, whose process is
# implement -> task reviewer -> fix -> re-review per task with no
# implementation-only mode, and to import that loop explicitly into its wave
# path ("run its per-task review ... exactly as subagent-driven-development
# prescribes"). Two acceptance gates for one body of work reviewed everything
# twice and made a phase something other than the unit of acceptance. Both
# sweeps are text sweeps because the rule is contractual prose: the failure mode
# is a sentence coming back, and a sentence is what is checked.
#
# Matched against FLATTENED text, never the raw file: these phrases wrap across
# lines in prose, and a raw-text search misses a wrapped one — which is how
# three of them survived a line-oriented grep of this very change (measured).
#
# The SDD pattern bans DELEGATING implementation, not naming the skill:
# `references/implement.md` and the composed-skills note have to say what was
# removed and why, or a later editor re-adds it.
#
# SCOPED to the pipeline skill. `bug-fix` may still prefer
# `superpowers:subagent-driven-development` at its own task scope, where SDD's
# per-task contract is the correct one; it has no phase gate to mis-gate.
# EXPIRY: revisit if another skill acquires a phase-advancement condition.
# Mutants: "pipeline delegates phase implementation to sdd",
#          "pipeline asks for a per-task review",
#          "pipeline gates a merge on passing task review",
#          "pipeline reviews wave members per task".
print("\n== pipeline has no task-level review ==")
_banned = [
    (re.compile(r"per-task review", re.I),
     "asks for a per-task review"),
    (re.compile(r"passed (?:its )?task review", re.I),
     "gates something on a task having passed review"),
    (re.compile(r"\btask reviewer\b", re.I),
     "names a task reviewer"),
    (re.compile(r"reviewed per task", re.I),
     "says wave members are reviewed per task"),
    (re.compile(r"an implementer,\s*a reviewer", re.I),
     "states a per-task cost model (an implementer AND a reviewer per task)"),
    (re.compile(r"(?:[Ii]mplement|dispatch)[^.\n]{0,80}?\bvia\b[^.\n]{0,40}?"
                r"subagent-driven-development", re.I),
     "delegates implementation to subagent-driven-development"),
]
_hits = []
for _f in sorted(pdir.rglob("*.md")):
    _t, _e = read(_f)
    if _e:
        continue
    _flat = " ".join(_t.split())
    for _rx, _why in _banned:
        _m = _rx.search(_flat)
        if _m:
            _hits.append(f"{relpath(_f)} {_why}: {_m.group(0)!r}")
if _hits:
    for _h in _hits:
        bad(_h + " — a task completing must dispatch no reviewer, and Stage 4's "
            "IMPLEMENT state must not hand implementation to a skill whose "
            "process reviews every task. REMEDY: state the rule the way "
            "references/implement.md does, and let the phase's `RV` fan-out be "
            "the only code review in the loop")
else:
    ok("no file in the pipeline skill asks for a task-level review or "
       "delegates phase implementation to subagent-driven-development")

# ---- the same linter, over a REAL run's tracker ----
# The arm above scans `pdir` only — the skill's own worked examples — so no
# invocation of this gate has ever read a run's own tracker. `--run <dir>`
# does, over `<dir>/progress.md`, with the same rules.
#
# A real run also supports the checks the examples cannot, and both are about
# files: the named report and coverage files either exist in `agent-output/` or
# they do not, and a coverage file that exists can be READ, which is what lets
# the arm compare the ranges a round handed its reviewers. The examples'
# filenames are illustrative and were never written, so `agent_output` is
# passed HERE and nowhere else — passing it above would fail the documentation
# for being documentation.
#
# `nseen` is deliberately NOT required non-zero here. `M=0 → no round` is a
# legitimate but optional round form; a run that never produced one is not
# thereby defective, and requiring it would make the mode reject conforming
# runs. `rseen` IS required, because a `--run` over a tracker with no closed
# round is a caller who thinks a review has been checked when none has.
#
# Both "does not exist" branches report a NAMED failure rather than raising:
# `bad()` is the gate's only way to say something, and a traceback exits before
# the remaining sections ever run. So does the UNREADABLE branch: a
# `chmod 000 progress.md` used to reach `lint_review_lines`'s `if e: continue`,
# come back with no records, and be reported as "no closed RV/RVJ round —
# nothing in this run has been reviewed yet". The verdict was right and the
# reason was invented: the file exists and may hold closed rounds. The read is
# done here, once, and the error named.
#
# WHAT THIS MODE ESTABLISHES, exactly, and what it does not:
#   IT ESTABLISHES — for every closed `RV`/`RVJ` round in `<dir>/progress.md`:
#     the declared `<s> slice + <i> integration` count equals the number of
#     report files the same round lists (brace sets expanded); an `N=`
#     round's slice count equals `ceil(N/5)`; the integration count is 0 at one
#     slice, and above one slice is either 1 with a named `boundary:` or 0 with
#     `no integration boundary` declared; an appended round is keyed `M`, and
#     one declaring `M>=1` names a `fixplan` file present in `agent-output/`;
#     every closed record carries a parseable declaration unless it is the
#     `WAIVED` form; an `RVJ` round
#     declares `0 slice + 1 integration`; an `M=` round declares a `C=<n>`
#     cluster count and its slice count equals it; the round names a `coverage`
#     file; every report file it names, and the coverage file it names, exist in
#     `<dir>/agent-output/`; on a round declaring two or more slices, that
#     coverage file is readable, every report the round names has a row of its
#     own in it, and no two of those rows carry the same range; and an
#     `M=0 → no round` record carries its closure routes and no reviewer
#     evidence. Plus: the tracker is readable, and at least one round is closed.
#   IT DOES NOT ESTABLISH that the fan-out was SIZED correctly OUTSIDE THE
#     UNWAVED `N=` REGIME — inside it the size IS derivable from the line, and
#     the arm above derives it. Elsewhere the two halves of the question
#     differ. The OVER-WIDE half is caught where it leaves a trace: two
#     reviewers handed the same range are two rows this mode compares, and it
#     reports them. The COUNT itself is not derivable there — a fix round's
#     wave count is not on the line, and a re-review's rule is "one reviewer
#     per file cluster in the fix diff", whose input is the diff, with `C` a
#     number written by whoever chose `s`, so a round declaring
#     `M=7 C=1 → 1 slice + 0 integration` over a seven-cluster diff is
#     internally consistent and passes here (measured), and so does an
#     over-wide round whose reviewers were handed genuinely distinct ranges,
#     since nothing in the tracker says what the clusters were. Any prose
#     saying more than that is a claim this mode cannot hold up.
#   IT ALSO DOES NOT establish that a named report or coverage file says
#     anything — existence is checked, content is not, so `COVERED: <n>/<n>`
#     is unread here — or that the round happened when it says.
# The coverage-table arm's own mutants are cited at that arm, with the argument
# for including the integration row; they are run-mode mutants like these.
# Mutants: "run tracker over-declares reviewers",
#          "run tracker cites a report file that is not in agent-output",
#          "run tracker cites a coverage file that is not in agent-output",
#          "run tracker round loses its coverage field",
#          "long run-tracker round loses its coverage field",
#          "run tracker loses one brace-expanded report file",
#          "run tracker has no closed review round",
#          "run directory has no progress.md",
#          "run directory has no agent-output".
def parse_tracker_phases(text):
    """Split a tracker into phases with their task and RV/RVJ bullet states.

    A phase is a `## Phase <x>` heading; its bullets are the `- [ ] T<n>` and
    `- [ ] RV`/`RVJ` lines under it, until the next such heading. Returned in
    FILE ORDER, because that order is what "a later phase" means to every arm
    that reads this. Only the box character is read — the fields after it are
    `lint_review_lines`' business, and duplicating any of that here would give
    two parsers of one grammar.

    `tasks` entries are `(state, name, lineno)`; `reviews` entries are
    `(kind, state, lineno)`. The two shapes differ because the arms want
    different things first: a task's state, a review's kind. `heading` is the
    raw heading line, which `parse_phase_lanes` reads `· deps:` and `· lane:`
    out of.
    """
    phases, cur = [], None
    for n, line in enumerate(text.split("\n"), 1):
        mh = re.match(r"##\s+Phase\s+([^\s—·]+)", line)
        if mh:
            # NORMALISED AT CAPTURE. The label used to keep the whitespace it
            # matched, while every lookup builds `phase <id>` with one space —
            # so `## Phase  2` (two spaces) matched nothing and produced up to
            # four reports for one stray space, each telling the author to name
            # a phase the tracker demonstrably has.
            cur = {"label": f"Phase {mh.group(1).strip()}", "line": n,
                   # THE WHOLE HEADING IS KEPT, because the fields after the
                   # name are where `· deps:` and `· lane:` live and the label
                   # regex deliberately stops before them. Reading them from
                   # here rather than re-splitting the file elsewhere keeps one
                   # parser of one grammar.
                   "heading": line,
                   "tasks": [], "reviews": []}
            phases.append(cur)
            continue
        if cur is None:
            continue
        # `\**` BEFORE THE ID: a tracker written `- [ ] **T5** — …` is still a
        # task line, and reading it as "this phase has no tasks" is how an arm
        # that counts open tasks silently starts checking nothing. Same for a
        # dotted id (`T2.1`), which `[\w.]+` keeps.
        mb = re.match(r"\s*-\s*\[([ x~])\]\s*\**\s*(RVJ|RV|T[\w.]+)", line)
        if mb:
            st, what = mb.group(1), mb.group(2)
            if what in ("RV", "RVJ"):
                cur["reviews"].append((what, st, n))
            else:
                cur["tasks"].append((st, what, n))
    return phases


_LANEFLD = re.compile(r"·\s*lane:\s*([A-Z][A-Za-z0-9]*)")
_DEPSFLD = re.compile(r"·\s*deps:\s*([^·]*)")


def parse_phase_lanes(phases):
    """`{index: lane id}`, `{index: [dep indexes]}`, and the multi-lane headings.

    Read from the phase headings and from NOTHING ELSE. A lane is an active
    execution branch between a fork and a join, not a maximal dependency chain:
    in a diamond `A → B,C → D`, `A` and `D` sit on both maximal chains, so
    chain membership is not a partition and "which lane owns this phase" has no
    answer. The mapping is therefore allocated once at GATE 2, persisted on the
    headings so it survives compaction and resume, and VALIDATED here — never
    re-derived by enumerating chains.

    Phase order is FILE ORDER, which is approved-plan order to every arm that
    reads it; the fork and join rules are both stated over that order.
    """
    idx = {ph["label"].lower(): i for i, ph in enumerate(phases)}
    lanes, deps, multi = {}, {}, []
    for i, ph in enumerate(phases):
        head = ph.get("heading", "")
        found = _LANEFLD.findall(head)
        if len(found) > 1:
            multi.append((i, found))
        if found:
            lanes[i] = found[0]
        dd, m = [], _DEPSFLD.search(head)
        if m:
            for tok in re.findall(r"[0-9]+[0-9A-Za-z.]*", m.group(1)):
                j = idx.get(f"phase {tok.lower()}")
                # A DEP NAMING A PHASE THIS TRACKER LACKS is dropped here and
                # left to the arm that owns unresolvable references. This helper
                # returns what it could read, never a guess.
                if j is not None:
                    dd.append(j)
        deps[i] = sorted(set(dd))
    return lanes, deps, multi


if RUN_DIR is not None:
    print(f"\n== run tracker: {relpath(RUN_DIR)} ==")
    tracker = RUN_DIR / "progress.md"
    if not tracker.exists():
        bad(f"{relpath(tracker)} does not exist — `--run` was pointed at "
            "something that is not a pipeline run directory, so nothing was "
            "checked. REMEDY: pass the run directory that holds the run's "
            "`progress.md`")
    elif (terr := (_tr := read(tracker))[1]):
        bad(f"{relpath(tracker)} cannot be read: {terr} — the "
            "tracker exists and may hold closed rounds, so nothing here is a "
            "statement about whether this run has been reviewed, and in "
            "particular not that it has not been. REMEDY: make the file "
            "readable and run again")
    else:
        ttext = _tr[0]
        ao = RUN_DIR / "agent-output"
        if not ao.is_dir():
            bad(f"{relpath(ao)} does not exist — a closed review round has "
                "nowhere to have written its reports, so every report file "
                "this tracker names is unverifiable. REMEDY: keep the run's "
                "`agent-output/` beside its `progress.md`")
            ao = None
        rseen, rnseen, rviol, rgates = lint_review_lines(
            [tracker], agent_output=ao, bullet_bounded=True)
        if not rseen:
            bad(f"{relpath(tracker)}: no closed RV/RVJ round — nothing in this run "
                "has been reviewed yet, so a PASS here would report a review "
                "that has not happened")
        elif not rviol and ao is not None:
            # `ao is not None` guards the PASS LINE as well as the check:
            # presence was not checked when there was no directory to check it
            # against, so this line must not be the thing that says it was.
            ok(f"{rseen} closed review rounds in the tracker"
               + (f" ({rnseen} of them `M=0 → no round`)" if rnseen else "")
               + ", every `N=` round sized `ceil(N/5)` with its "
                 "integration reviewer 0 at one slice and, above one slice, "
                 "either declared with its boundary or declared absent, every "
                 "declared report file and every declared coverage file "
                 "present in agent-output/, and no round of two or more "
                 "slices repeating a range across its coverage rows")

        # ---- review may not begin while a task in the phase is unchecked ----
        # The failure this catches is the old per-task shape wearing the new
        # vocabulary: reviewers dispatched over T1..T3 while T4..T8 are still
        # out, which is per-task review at a coarser grain and re-splits the
        # phase into pieces nobody reviewed as a unit. It is checkable from the
        # tracker alone, because a started round and an unchecked task line
        # cannot both be true of a phase reviewed as a whole.
        #
        # `[~]` COUNTS AS STARTED. That is the point of the marker: it is
        # written before the reviewers go out, so a round that is merely
        # dispatched — not yet closed — is already too early if a task of its
        # own phase is open.
        # Mutants: "run tracker reviews a phase with an unchecked task",
        #          "run tracker reviews a phase with a task still in progress".
        _phs = parse_tracker_phases(ttext)

        # A TRACKER THIS PARSER CANNOT READ IS NOT A TRACKER THAT PASSES. Both
        # arms below are only as good as their subject, and `parse_tracker_phases`
        # yields nothing for a tracker whose phases are `### Phase N` instead of
        # `## Phase N`. Without this, the review-not-early arm is skipped by its
        # own `elif _phs:` and the no-advance arm falls through to an
        # affirmative pass — measured PASS with a review opened early AND
        # `Next action` advanced. This file already states the principle at the
        # examples arm ("an arm whose subject can vanish from the docs is an arm
        # that silently starts checking nothing, and the count in the pass line
        # is what makes that visible"); these two arms were not given it.
        # Mutants: "run tracker phases are demoted below the parser".
        if not _phs:
            bad(f"{relpath(tracker)}: no `## Phase <x>` heading this gate can "
                "parse, yet the file holds closed review rounds — so every "
                "phase-scoped check below had no subject and established "
                "nothing. REMEDY: write phase headings as `## Phase <x> — …`, "
                "which is the form `templates/progress.md` ships")

        # ---- review may not begin while a task in the phase is unchecked ----
        # The failure this catches is the old per-task shape wearing the new
        # vocabulary: reviewers dispatched over T1..T3 while T4..T8 are still
        # out, which is per-task review at a coarser grain and re-splits the
        # phase into pieces nobody reviewed as a unit.
        #
        # `[~]` COUNTS AS STARTED. That is the point of the marker: it is
        # written before the reviewers go out, so a round that is merely
        # dispatched is already too early if a task of its own phase is open.
        #
        # `RVJ` IS JUDGED BY ITS PLACEMENT, NOT BY THE SAME RULE. An `RVJ` above
        # a phase's first task is a JOINING phase's line: its subject is the
        # lanes that merged into this phase, not this phase's own tasks, and the
        # skill's templates prescribe exactly that shape ("a joining phase's
        # `RVJ` leads, sitting above that phase's first task"). Judged by the
        # `RV` rule it FAILED a legal tracker (measured), which would have
        # pressured a real run into ticking the box early or moving the line —
        # both worse than the state the arm protects. A TRAILING `RVJ` — below
        # the phase's last task — reviews work that includes this phase, so it
        # takes the same all-tasks-`[x]` condition as `RV`.
        # Mutants: "run tracker reviews a phase with an unchecked task",
        #          "run tracker reviews a phase with a task still in progress",
        #          "run tracker opens a trailing RVJ over unfinished work".
        _early = []
        for _ph in _phs:
            _opent = [x for x in _ph["tasks"] if x[0] != "x"]
            if not _opent:
                continue
            _first_task = min(x[2] for x in _ph["tasks"])
            _startedr = [r for r in _ph["reviews"]
                         if r[1] in ("~", "x")
                         and (r[0] == "RV" or r[2] > _first_task)]
            if _startedr:
                _early.append(
                    f"{relpath(tracker)}:{_startedr[0][2]}: {_ph['label']}'s "
                    f"{_startedr[0][0]} is `[{_startedr[0][1]}]` while "
                    f"{len(_opent)} task line(s) in that phase are not `[x]` "
                    f"(first at line {_opent[0][2]}, {_opent[0][1]})")
        if _early:
            for _e in _early:
                bad(_e + " — a phase is reviewed as one unit once all of its "
                    "tasks have landed; a round opened earlier reviews part of "
                    "a phase, which is per-task review at a coarser grain. "
                    "REMEDY: finish the phase's tasks, then open its review. "
                    "If the round did cover everything, the unchecked task "
                    "lines are the thing that is wrong and Rule 4 "
                    "reconciliation is the fix")
        elif _phs:
            ok(f"{len(_phs)} phases "
               f"({sum(len(x['tasks']) for x in _phs)} task lines), none with a "
               "review round opened while one of its own tasks was unchecked")

        # ---- Current State may not point past an unfinished phase ----
        # This is the advancement invariant, checked. Four ways a phase is
        # unfinished, and the tracker's own "next unchecked line" rule can only
        # see the first:
        #   1. a bullet in it is not `[x]` — an open task, or an open RV/RVJ;
        #   2. it carries NO review line at all — see below;
        #   3. a blocking finding scoped to it is still `open` in findings.md —
        #      a fix loop interrupted mid-round leaves every box `[x]`, so the
        #      next unchecked line points PAST the phase that owns the finding;
        #   4. a round names a fix plan that is not on disk (arm above).
        # The history this exists for: a real run skipped the review fan-out for
        # seven consecutive phases because every gate read "no open blocking
        # IDs", which is vacuously true when review never ran.
        #
        # (2) IS NOT A TECHNICALITY. `any()` over an empty list is `False`, so a
        # phase given no `RV` line reads exactly like a phase whose `RV` closed
        # — measured PASS over a tracker openly advancing past a phase that was
        # implemented and never reviewed. `SKILL.md` warns in its own words that
        # "a review line added later is a review line that can be forgotten";
        # this is that state, and the vacuity the 2026-09-01 fix removed from
        # the predicate had simply moved one level up.
        #
        # findings.md is read ONLY IF PRESENT, and an UNPARSEABLE ledger is
        # reported rather than treated as empty — an absent or unreadable
        # ledger must never read as a clean one, which is the same mistake in
        # miniature and the one this arm exists to refuse.
        # Mutants: "run tracker advances past a phase with an open RV",
        #          "run tracker advances past a phase with an open blocking finding",
        #          "run tracker next action names a later phase than its own state",
        #          "run tracker phase carries no RV line at all",
        #          "run tracker ledger row bolds its severity",
        #          "run tracker Current State phase advances while Next action does not",
        #          "run tracker Current State names a mentioned phase",
        #          "run tracker ledger header renames its phase column",
        #          "run tracker second blocking table gates nothing",
        #          "run tracker Current State is shadowed by a prose decoy",
        #          "run tracker ledger row id is bolded",
        #          "run tracker four-column ledger renames its phase column",
        #          "run tracker loses its Phase field",
        #          "run tracker grows a second Current State block",
        #          "run tracker ledger row id is not F-<n>",
        #          "run tracker Phase field resolves to nothing",
        #          "run tracker hides a stale Phase field above the fresh one",
        #          "run tracker ledger row id has a letter after the dash".
        #
        # RR6-4's guard — no affirmative line after a nonexistent-phase report —
        # carries NO mutant, deliberately: removing it restores a FALSE `ok`
        # line on a build that is red either way, so the harness (which reads
        # only pass/fail) cannot distinguish it. Verified by hand instead: each
        # probe above asserts zero `ok    no unfinished phase` lines alongside
        # its FAIL. Recorded as unpinned rather than left to look watched.
        def _norm(cell):
            """A ledger cell as the comparison wants it: markdown stripped."""
            return re.sub(r"[*`_\s]+", " ", cell or "").strip().lower()

        _idx = {ph["label"].lower(): i for i, ph in enumerate(_phs)}
        _lanemap, _depmap, _lanemulti = parse_phase_lanes(_phs)
        _blockers = []
        for _i, _ph in enumerate(_phs):
            _why = []
            # AN `RVJ` IS NOT THIS PHASE'S `RV`. A joining phase's `RVJ` sits
            # above its first task and reviews the LANES that merged into it —
            # which is exactly why the review-not-early arm exempts it. Asking
            # only whether a phase has "any review line" let that same `RVJ`
            # stand in for the phase's own review, so a joining phase with
            # every task `[x]` and no `RV` was not a blocker (measured PASS).
            # The two arms read one list and have to agree about what an `RVJ`
            # covers: it covers the join, never this phase's tasks.
            if not any(r[0] == "RV" for r in _ph["reviews"]):
                _why.append("no `RV` line — an implementation phase ends with "
                            "one, and a phase with none reads exactly like a "
                            "phase whose review closed. An `RVJ` does not "
                            "substitute: it reviews the unit that joined here, "
                            "not this phase's own tasks")
            if any(x[0] != "x" for x in _ph["tasks"]):
                _why.append("an open task line")
            if any(r[1] != "x" for r in _ph["reviews"]):
                _why.append("an open RV/RVJ line")
            if _why:
                _blockers.append((_i, _ph["label"], " and ".join(_why)))

        # `_untrusted` IS BORN HERE, ahead of the ledger parse, because the
        # rule covers BOTH halves: an affirmative must not follow any report
        # this arm made about the subject it was comparing — an unreadable
        # ledger, an unread row, a row whose width its header contradicts, a
        # finding scoped to a phase the tracker lacks, a duplicated Current
        # State block or field, a field naming a phase that does not exist.
        # Every one of those means the comparison was incomplete.
        _untrusted = False
        # TWO POPULATIONS, TWO QUESTIONS, and conflating them is a defect in
        # both directions. `_blockers` answers "may this phase/lane advance
        # RIGHT NOW", so it holds only findings that are OPEN and blocking. The
        # gate-ownership arm asks a HISTORICAL question — "was the blocking
        # finding this gate raised closed through a round belonging to this
        # same gate" — and a closed finding is exactly what it needs to see.
        # Reading `_blockers` there would (a) never fire, since a closed
        # finding is absent from it, and (b) fire wrongly on an open one, whose
        # fix loop is legitimately still in progress and owes no completed
        # round yet. `_fmap` is that second population: every readable ledger
        # row, whatever its state.
        _fmap = {}
        _ledger, _ltext, _lrows = RUN_DIR / "findings.md", None, 0
        if _ledger.is_file():
            _ltext, _lerr = read(_ledger)
            if _lerr:
                _untrusted = True
                bad(f"{relpath(_ledger)} cannot be read: {_lerr} — it may hold "
                    "open blocking findings, so nothing here says this run has "
                    "none. REMEDY: make the file readable and run again")
                _ltext = None
        if _ltext:
            # LOCATE THE COLUMNS FROM THE LEDGER'S OWN HEADER, never by
            # counting. The previous fixed `|`-spine dropped a row whose table
            # had an extra column, whose `Sev` was bolded, whose state read
            # `Open`, or whose `Phase` cell read `Phase 2` — four measured
            # shapes, each leaving the arm's ledger half vacuous while the pass
            # line still claimed the invariant. Markdown bolding defeating the
            # one arm between the run and this failure is not an acceptable
            # margin.
            # AND ONLY THE BLOCKING TABLE'S ROWS ARE ITS ROWS. `findings.md`
            # ships a SECOND `F-`-keyed table — *Deferred Minor findings*,
            # four columns against the blocking table's seven — so applying the
            # blocking header's width to every `F-` row in the file failed the
            # shipped template, and with it every real run that defers a single
            # Minor finding, which is the normal outcome of a review. The rows
            # are collected from the header until the table ends, and a
            # narrower table further down is simply a different table.
            # EVERY blocking table, and the `F-` rows of the whole file.
            # Two bugs lived in the first version of this: it stopped at the
            # FIRST header, so a second blocking table's rows gated nothing;
            # and it read `_seen_fid` out of the rows it had just collected,
            # which are empty exactly when no header was found — making the
            # "unparseable ledger" report unreachable, so a `findings.md` whose
            # header names `Area` where the grammar wants `Phase` read as a
            # clean one (measured, over a ledger holding an open Critical).
            # `_seen_fid` now scans the file, which is the only population that
            # can answer "are there rows nobody read?".
            _tables = []
            _lines = _ltext.split("\n")
            for _k, _line in enumerate(_lines):
                _cells = [_norm(c) for c in _line.strip().strip("|").split("|")]
                if BLOCKING_COLS <= set(_cells):
                    _tbl = []
                    for _line2 in _lines[_k + 1:]:
                        if not _line2.lstrip().startswith("|"):
                            break
                        _tbl.append(_line2)
                    _tables.append((_cells, _tbl))
            _hdr = _tables[0][0] if _tables else None
            # NORMALISED, LIKE EVERY OTHER COMPARISON HERE. This was the one
            # that was not, so `| **F-002** |` and `` | `F-002` | `` were
            # silently not rows at all — dropped from the table walk AND from
            # `_seen_fid`, so nothing reported them (measured PASS past an open
            # Major). The ledger's own prose bolds and backticks IDs freely,
            # which is exactly why every other cell comparison goes through
            # `_norm`.
            #
            # AND NO WIDTH FILTER. A `count("|") >= 6` test excluded a
            # four-column blocking table — the minimum `templates/findings.md`
            # blesses — making the template's "a renamed column turns into a
            # build failure" claim false for that shape. Row-ness is "the first
            # cell is an F-id", and width is checked against the header later,
            # where a mismatch is reported rather than used to decide.
            # "THE FIRST CELL LOOKS LIKE A FINDING ID", not "is F- plus
            # digits". Requiring the exact grammar dropped an off-grammar id
            # from the table walk AND from `_seen_fid`, so an open blocking row
            # keyed `N-002` or `F-002a` was ungated in silence — NEW-F2's
            # failure mode on a different decoration of the same cell.
            # Reachability is not hypothetical: this migration's own ledgers use
            # `N-`, `NEW-` and `NEW-F` ids, and the template ships split phase
            # ids (`3a`) that invite `F-002a`. Liberal in what counts as a row,
            # strict in what a row must then satisfy: an off-grammar id is now
            # read or reported, never dropped.
            # WIDE ENOUGH TO MAKE THE TEMPLATE'S CLAIM TRUE. The first attempt
            # required a digit straight after the dash and letters only before
            # it, which still dropped `NEW-F2` and `RR5-2` — the exact id
            # shapes this branch's own ledger uses for rounds 4 and 5, and
            # `NEW-F` is the one the code comment cited as its reachability
            # argument. Narrowing the promise instead of widening the match
            # would have left a claim finding in a shipped template.
            # A DIGIT IS REQUIRED AFTER THE DASH. Widening row-ness to any
            # `<letters>-<something>` first cell made a hyphenated ordinary word
            # a row: a header-less `findings.md` containing `| run-ok | PASS |`
            # false-failed, and reported "holds 2 `F-` row(s)" over zero
            # findings. That is the opposite failure direction from everything
            # else in this arm and the one that can actually stop a run, so the
            # lookahead pins it while keeping `NEW-F2` and `RR5-2` — the ids
            # this branch's own ledger uses — matched.
            _isrow = lambda ln: bool(
                re.match(r"\|?\s*[a-z]+[0-9a-z]*-(?=[0-9a-z.]*\d)[0-9a-z.]+\s*\|",
                         _norm(ln)))
            _seen_fid = [ln for ln in _lines if _isrow(ln)]
            if _hdr is None:
                if _seen_fid:
                    _untrusted = True
                    bad(f"{relpath(_ledger)} holds {len(_seen_fid)} row(s) "
                        "that look like finding ids but no header row naming "
                        "ID/Sev/Phase/State — so the "
                        "advancement check could not locate the columns and "
                        "read no finding. An unparseable ledger must not read "
                        "as an empty one. REMEDY: keep the blocking ledger's "
                        "header row as `templates/findings.md` ships it")
            else:
              for _hdr, _rows in _tables:
                  _ci = {k: _hdr.index(k) for k in ("id", "sev", "phase", "state")}
                  # OPTIONAL BY DESIGN: `templates/findings.md` requires only
                  # the four names above, so `Closed by` may be absent and the
                  # withdrawal check below is guarded on it rather than
                  # assuming it.
                  _cbi = _hdr.index("closed by") if "closed by" in _hdr else None
                  for _line in _rows:
                      if not _isrow(_line):
                          # REPORTED, NOT SKIPPED. `_seen_fid` is the "rows
                          # nobody read" population and it is consulted only
                          # when NO header exists — so a row inside a located
                          # blocking table whose first cell this check cannot
                          # read was dropped in silence. Same rule as the rest
                          # of this arm: an unread row must not read as a
                          # closed one. A separator row is not a row.
                          if not re.match(r"^\s*\|[\s\-:|]+\|?\s*$", _line):
                              _untrusted = True
                              bad(f"{relpath(_ledger)}: a row of the blocking "
                                  "table this check could not read: "
                                  f"{_line.strip()[:60]!r} — its first cell is "
                                  "not a finding id, so the row was not read, "
                                  "and an unread row must not read as a closed "
                                  "one. REMEDY: key the row `F-NNN`, as "
                                  "`templates/findings.md` ships it")
                          continue
                      _cells = [c for c in _line.strip().strip("|").split("|")]
                      # WIDTH MUST EQUAL THE HEADER'S, not merely reach the
                      # columns we want. A row one cell WIDER than its header
                      # shifts every cell past the inserted one, so `State` is
                      # read from the wrong column and the row is skipped in
                      # silence — measured PASS past an open blocking finding
                      # with `| F-002 | Major | X | 2 | … |` under a 7-column
                      # header. Either width is a table this arm cannot read, and
                      # an unreadable ledger row is reported, never assumed clean.
                      if len(_cells) != len(_hdr):
                          _untrusted = True
                          bad(f"{relpath(_ledger)}: row "
                              f"{_norm(_cells[0]).upper()!r} has {len(_cells)} "
                              f"cells but its header has {len(_hdr)} — the "
                              "advancement check locates `State` and `Sev` by "
                              "the header's columns, so a row of a different "
                              "width is one it cannot read, and an unreadable "
                              "row must not read as a closed one. REMEDY: match "
                              "the header's column count")
                          continue
                      _lrows += 1
                      # A WITHDRAWN FINDING HAS NO FIX COMMIT. `withdrawn` means
                      # duplicate, malformed, or superseded, with no repository
                      # change behind it; a hash in `Closed by` is the evidence
                      # that a change WAS made, and a finding with a fix commit
                      # takes the fix loop. The linter cannot count commits — it
                      # can refuse the row that names one. Placed BEFORE the
                      # `state != "open"` skip, because a withdrawn row is by
                      # definition not open and a check after the skip would
                      # never run.
                      # A DIGIT IS REQUIRED in the token so an English word made
                      # only of hex letters (`deface`, `added`) is not read as a
                      # hash.
                      if (_cbi is not None
                              and _norm(_cells[_ci["state"]]) == "withdrawn"):
                          _h = next((x for x in re.findall(
                                        r"\b[0-9a-f]{7,40}\b", _cells[_cbi])
                                     if re.search(r"[0-9]", x)), None)
                          if _h:
                              _untrusted = True
                              bad(f"{relpath(_ledger)}: "
                                  f"{_norm(_cells[_ci['id']]).upper()} is "
                                  f"`withdrawn` while `Closed by` names {_h!r} "
                                  "— a commit hash is evidence that the "
                                  "repository changed for this finding, and a "
                                  "finding with a fix commit cannot be "
                                  "withdrawn. `withdrawn` is a duplicate, a "
                                  "malformed finding, or one superseded by "
                                  "another, with nothing committed. REMEDY: "
                                  "close it through the fix loop — fix plan, "
                                  "fix, focused re-review — or, if it really "
                                  "was a duplicate, drop the hash")
                      _fmap[_norm(_cells[_ci["id"]]).upper()] = {
                          "sev": _norm(_cells[_ci["sev"]]),
                          "state": _norm(_cells[_ci["state"]]),
                          "phase": _norm(_cells[_ci["phase"]]),
                      }
                      if _norm(_cells[_ci["state"]]) != "open":
                          continue
                      _sev = _norm(_cells[_ci["sev"]])
                      if _sev not in ("critical", "major", "bug"):
                          continue
                      _phl = re.sub(r"^phase\s*", "", _norm(_cells[_ci["phase"]]))
                      _pi = _idx.get(f"phase {_phl}")
                      # GUARDED BY `_phs`, like its Current-State sibling: on a
                      # tracker this gate cannot parse, `_idx` is empty and
                      # every ledger row "matches no heading", which is a
                      # second and actively misleading diagnosis for one
                      # defect. The unparseable-tracker arm owns that case.
                      if _pi is None and not _phs:
                          continue
                      if _pi is None:
                          _untrusted = True
                          bad(f"{relpath(_ledger)}: {_norm(_cells[_ci['id']]).upper()} "
                              f"({_sev}) is open against phase {_phl!r}, which "
                              "matches no `## Phase` heading in the tracker — so "
                              "the advancement check could not scope it to a "
                              "phase and this finding gated nothing. REMEDY: make "
                              "the ledger's Phase cell match the tracker's phase "
                              "heading")
                          continue
                      _blockers.append((_pi, f"Phase {_phl}",
                                        f"open blocking finding "
                                        f"{_norm(_cells[_ci['id']]).upper()} ({_sev})"))
        _blockers.sort(key=lambda b: b[0])

        # ---- the persisted lane mapping is well formed ----
        # Mutants: "run tracker phase heading carries no lane",
        #          "run tracker phase heading carries two lanes".
        for _i2, _found in _lanemulti:
            _untrusted = True
            bad(f"{relpath(tracker)}: {_phs[_i2]['label']}'s heading carries "
                f"{len(_found)} `· lane:` fields ({', '.join(_found)}) — a "
                "phase is executed by exactly one active lane, and this gate "
                "reads the first, so a second field is a lane assignment "
                "nobody validates. REMEDY: one `· lane:` per heading")
        _nolane = [ph["label"] for _i2, ph in enumerate(_phs)
                   if _i2 not in _lanemap]
        if _phs and _nolane:
            _untrusted = True
            bad(f"{relpath(tracker)}: {_nolane[0]}'s heading carries no "
                "`· lane:` field"
                + (f", and so do {len(_nolane) - 1} more" if len(_nolane) > 1
                   else "")
                + " — the phase → lane mapping is persisted on the headings so "
                "it survives compaction and resume, and a phase with no lane "
                "is one no per-lane check can reach. A sequential run assigns "
                "every phase `· lane: A`. REMEDY: assign every phase its lane "
                "at GATE 2, as `templates/progress.md` ships it")


        # ---- a gate that raised a blocking finding carries its own round ----
        # THE QUESTION THIS ANSWERS: a closed `RV`/`RVJ` named F-NNN in its
        # outcome, and F-NNN is blocking and now CLOSED in the ledger. Was it
        # closed through a fix round belonging to THAT SAME gate?
        #
        # `references/fix-loop.md` requires an `RVJ`'s blocking findings to run
        # the fix loop under the `RVJ`'s own Counters row, while the reopen rule
        # named `RV` alone — so an `RVJ` fix round had a budget with no home,
        # and a run following the letter of the rule appended it to the joining
        # phase's `RV`: the wrong gate's evidence, spending that phase's review
        # budget on a join it never covered. `kind` is `"round"` for every
        # appended record, so nothing could see the difference until rounds were
        # attributed to their owning gate.
        #
        # IT DOES NOT READ `_blockers`, and that is deliberate. `_blockers`
        # holds findings that are OPEN and blocking, because it answers a
        # different question — may this phase advance right now. Against it this
        # arm would never fire (a closed finding is absent from it) and would
        # fire wrongly on an open one, whose fix loop is legitimately still in
        # progress and owes no completed round yet. `_fmap` is the historical
        # population: every readable row, whatever its state.
        # Mutants: "run tracker RVJ round is filed under the phase RV",
        #          "run tracker RVJ closes a blocking finding with no round".
        _gate_untrusted = _ltext is None
        _owed = []
        for _g in rgates:
            _need = [x for x in _g["fids"]
                     if _fmap.get(x, {}).get("sev") in ("critical", "major",
                                                        "bug")
                     and _fmap.get(x, {}).get("state") == "closed"]
            if _need and not _g["rounds"]:
                _owed.append((_g, _need))
        for _g, _need in _owed:
            _gate_untrusted = True
            bad(f"{_g['file']}:{_g['line']}: this `{_g['kind']}` named "
                f"{', '.join(sorted(_need))} in its outcome, and the ledger has "
                "it closed and blocking — but this gate carries no appended "
                "round of its own. A fix loop belongs to the `review_gate` that "
                "raised its findings: the round is appended under THAT gate's "
                "line, and a re-review reopens THAT gate, never a different "
                "one. A blocking finding closed under another gate's line "
                "leaves this gate's evidence claiming a clean review it never "
                "got. REMEDY: append the fix round under this "
                f"`{_g['kind']}`")
        if rgates and not _gate_untrusted:
            ok("every gate whose outcome named a now-closed blocking finding "
               "carries an appended round of its own")

        # BOTH Current State fields are read. `**Phase:**` is the field the
        # resume protocol's reader looks at first, and reading only
        # `**Next action:**` left two measured passes: `Phase: 3` while Phase 2
        # held an open finding, and a bare `Next action: T4 — a task` (the
        # template's own suggested form) naming no phase at all.
        # THE TEMPLATE IS THE AUTHORITY ON SHAPE. This first required the
        # literal word "phase" inside the field's value, which
        # `templates/progress.md`'s `**Phase:** <number and name>` never
        # contains — so the field the resume protocol reads FIRST was
        # unreadable on every conforming tracker, the arm rested entirely on
        # `**Next action:**`, and its "neither field names a phase" branch then
        # fired on the ordinary mid-run case (`Next action: RV — review
        # fan-out` names no phase either, and the template says it need not).
        # An arm that fails the shape its own templates prescribe is wrong
        # about the shape, not the tracker.
        # THE FIELD IS LOCATED IN THE `## Current State` BLOCK, AT A LINE
        # START. Round 4 anchored the phase token inside the field's value but
        # left the FIELD itself found by a search over the whole tracker — so
        # any prose line mentioning `**Phase:** 2` outranked the real Current
        # State, and the gate passed over an open finding (measured). The
        # decoy is not hypothetical: this migration added a literal
        # `**Phase:**` example to `templates/progress.md`, the file every run
        # copies into its own run directory. The block is bounded by the next
        # `##` heading, and the field must be a list item on its own line,
        # which is the only form `templates/progress.md` writes.
        # THE STRUCTURAL FIX, and the one that ends this family. Five rounds
        # produced five ways to lose this field — searched the whole tracker,
        # read a mentioned phase, required the literal word, required a `-`/`*`
        # bullet — and every one of them failed the SAME way: silently. The arm
        # fell back to `**Next action:**` and printed an affirmative pass. So
        # the marker is optional now (any list form, or none, which is three
        # markdown-legal shapes round 5 had made unreadable), the heading is
        # anchored at a line start so prose quoting it cannot open a block, a
        # duplicated block is reported, and — decisively — **a `**Phase:**`
        # field this arm cannot locate is a FAILURE, not a fallback.** The next
        # locator bug is then a red build instead of a quiet pass.
        # `_untrusted` — SET WHEREVER THIS ARM REPORTS ABOUT ITS OWN SUBJECT.
        # Four measured shapes printed an affirmative right after the arm had
        # said it could not trust what it compared, and two of them were false
        # about the run's actual position because the comparison used the stale
        # field or stale block just declared ambiguous. One flag, guarding both
        # `ok(...)` calls: the same one-expression move RR6-1 made, applied to
        # the remaining three reports.
        if len(re.findall(r"^##\s+Current State\s*$", ttext, re.M)) > 1:
            _untrusted = True
            bad(f"{relpath(tracker)}: two or more `## Current State` blocks, "
                "and this gate reads the first — the run's position must live "
                "in exactly one place, or an executor appending a fresh block "
                "leaves the stale one authoritative. REMEDY: keep one block, "
                "at the top, as `templates/progress.md` ships it")
        _csm = re.search(r"^##\s+Current State\s*$(.*?)(?=^##\s|\Z)",
                         ttext, re.M | re.S)
        _csblock = _csm.group(1) if _csm else ""
        _FIELDRE = r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?\*\*%s:\*\*"
        _LANERE = re.compile(
            r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?\*\*Lane\s+([A-Z][A-Za-z0-9]*):\*\*"
            r"\s*(.*)$", re.M)

        # THE OLD TWO-FIELD GRAMMAR IS GONE, and its absence is REPORTED rather
        # than tolerated. `templates/progress.md` prescribed one `**Next
        # action:**` while `references/parallel.md` required one per active
        # lane; keeping `**Phase:**` for single-lane runs would mean two
        # grammars and a mode switch in this gate, and a mode-switch branch is
        # what produced most of the defects this change repairs.
        for _dead in ("Phase", "Next action"):
            if re.search(_FIELDRE % _dead, _csblock, re.M):
                _untrusted = True
                bad(f"{relpath(tracker)}: Current State carries a "
                    f"`**{_dead}:**` field, which this grammar replaced with "
                    "one `- **Lane <id>:**` line per active lane — a sequential "
                    "run writes exactly one, `- **Lane A:** …`. REMEDY: write "
                    "the lane lines `templates/progress.md` ships")

        _seen_lane, _lane_cs = set(), []
        for _lid, _val in _LANERE.findall(_csblock):
            if _lid in _seen_lane:
                _untrusted = True
                bad(f"{relpath(tracker)}: two or more `**Lane {_lid}:**` lines "
                    "inside the `## Current State` block, and this gate reads "
                    "the first — so a stale line left above a fresh one is the "
                    "one that counts. A lane's position must live in exactly "
                    "one place. REMEDY: keep one line per lane, and replace "
                    "its value rather than adding a line")
                continue
            _seen_lane.add(_lid)
            _lane_cs.append((_lid, _val.strip()))

        if _phs and not _lane_cs:
            _untrusted = True
            bad(f"{relpath(tracker)}: no `**Lane <id>:**` line inside a "
                "`## Current State` block — those lines are where the "
                "advancement check reads each lane's position, so it read "
                "nothing and compared nothing. An unreadable position must not "
                "read as a satisfied one. REMEDY: keep the Current State block "
                "at the top, as `templates/progress.md` ships it")

        # ---- the lane model, computed once from the persisted mapping ----
        # A LANE IS AN ACTIVE EXECUTION BRANCH BETWEEN A FORK AND A JOIN, not a
        # maximal dependency chain. In a diamond `A → B,C → D`, the maximal
        # chains are `A → B → D` and `A → C → D`, so `A` and `D` sit on both:
        # chain membership is not a partition, and "which lane owns this phase"
        # has no answer. The mapping is therefore allocated at GATE 2, persisted
        # on the phase headings, and VALIDATED here.
        _lane_phases = {}
        for _i2, _l2 in sorted(_lanemap.items()):
            _lane_phases.setdefault(_l2, []).append(_i2)
        _unfinished = {b[0]: b for b in _blockers}
        _succ = {}
        for _j2, _dd2 in _depmap.items():
            for _x2 in _dd2:
                _succ.setdefault(_x2, []).append(_j2)

        def _contributors(j):
            """The lanes whose phases are direct predecessors of `j`."""
            out = []
            for _x in _depmap.get(j, []):
                _l = _lanemap.get(_x)
                if _l is not None and _l not in out:
                    out.append(_l)
            return out

        # A JOIN consumes two or more active lanes. One contributing lane is an
        # ordinary dependency, however many predecessors it has.
        _joins = {j: _contributors(j) for j in sorted(_depmap)
                  if len(_contributors(j)) >= 2}

        def _leading_rvj(j):
            """`j`'s leading `RVJ` — an `RVJ` above the phase's first task."""
            _t1 = min((t[2] for t in _phs[j]["tasks"]), default=None)
            return [r for r in _phs[j]["reviews"]
                    if r[0] == "RVJ" and (_t1 is None or r[2] < _t1)]

        # RETIRED vs WAITING. A non-surviving contributor stays ACTIVE, and
        # writes `waiting at join Phase <id>`, until the join's leading `RVJ`
        # closes; that closure is what retires it. A retired lane must then be
        # gone from Current State — leaving it there says a branch is still
        # executing when the run has already collapsed it.
        _retired, _waiting = {}, {}
        for _j2, _ls in _joins.items():
            _surv = _lanemap.get(_j2)
            _closed = any(r[1] == "x" for r in _leading_rvj(_j2))
            for _l2 in _ls:
                if _l2 == _surv:
                    continue
                if _closed:
                    _retired.setdefault(_l2, _j2)
                else:
                    _waiting.setdefault(_l2, _j2)

        # AN ACTIVE LANE owns unfinished work, or has finished its branch and is
        # still waiting at an unresolved join. Every one of them needs a line:
        # a lane that silently disappears from Current State is a branch nobody
        # is tracking, and resume has no way to notice.
        _active = {_l2 for _l2, _ps in _lane_phases.items()
                   if _l2 not in _retired
                   and (any(_i2 in _unfinished for _i2 in _ps)
                        or _l2 in _waiting)}

        # ---- fork allocation is deterministic ----
        # At a fork the successor FIRST IN APPROVED-PLAN ORDER keeps the
        # forking phase's lane, and every further successor takes a lane not
        # carried by any earlier phase. Enforcing joins alone would leave the
        # other half of the allocation rule unheld, and a fork that duplicates
        # the parent's lane onto two branches makes "which branch is this" the
        # unanswerable question the lane model exists to close.
        # Mutants: "fork gives the parent lane to the second successor",
        #          "fork branches share one lane".
        for _pi2, _kids in sorted(_succ.items()):
            if len(_kids) < 2:
                continue
            _kids = sorted(_kids)
            _pl = _lanemap.get(_pi2)
            if _pl and _lanemap.get(_kids[0]) != _pl:
                _untrusted = True
                bad(f"{relpath(tracker)}: {_phs[_pi2]['label']} forks, and its "
                    f"first successor in approved-plan order, "
                    f"{_phs[_kids[0]]['label']}, carries "
                    f"`· lane: {_lanemap.get(_kids[0])}` rather than the "
                    f"forking phase's own `{_pl}`. The first branch CONTINUES "
                    "the lane; only the further branches are newly allocated. "
                    f"REMEDY: write `· lane: {_pl}` on "
                    f"{_phs[_kids[0]]['label']}")
            _seen_kid = {}
            for _k in _kids:
                _kl = _lanemap.get(_k)
                if _kl is None:
                    continue
                if _kl in _seen_kid:
                    _untrusted = True
                    bad(f"{relpath(tracker)}: {_phs[_pi2]['label']} forks to "
                        f"{_phs[_seen_kid[_kl]]['label']} and "
                        f"{_phs[_k]['label']}, and both carry "
                        f"`· lane: {_kl}` — a fork CREATES lanes, so sibling "
                        "branches never share one. Two active lanes never "
                        "execute the same branch. REMEDY: allocate the next "
                        "unused id to the later sibling")
                _seen_kid[_kl] = _k
            for _k in _kids[1:]:
                _kl = _lanemap.get(_k)
                if _kl is None or _kl == _pl:
                    if _kl is not None and _kl == _pl:
                        _untrusted = True
                        bad(f"{relpath(tracker)}: {_phs[_k]['label']} is not "
                            f"the first successor of {_phs[_pi2]['label']} in "
                            f"approved-plan order, yet it carries the forking "
                            f"phase's own `· lane: {_pl}`. Only the first "
                            "branch continues the lane; every further branch "
                            "is a NEW active lane. REMEDY: allocate the next "
                            "unused id")
                    continue
                # A FRESH LANE'S FIRST PHASE IS THE BRANCH IT OPENS. If the id
                # already appeared earlier in approved-plan order, it was not
                # freshly allocated -- it was borrowed from another branch.
                _first = _lane_phases.get(_kl, [_k])[0]
                if _first < _k:
                    _untrusted = True
                    bad(f"{relpath(tracker)}: {_phs[_k]['label']} opens a new "
                        f"branch of {_phs[_pi2]['label']} but carries "
                        f"`· lane: {_kl}`, which {_phs[_first]['label']} "
                        "already carries earlier in approved-plan order. A "
                        "further branch takes a NEWLY ALLOCATED id. REMEDY: "
                        "allocate the next unused id")

        # ---- the join survivor is the planned one ----
        # Allocation happens at GATE 2: the joining phase carries the lane of
        # its FIRST CONTRIBUTING PREDECESSOR IN APPROVED-PLAN ORDER. Leaving the
        # survivor to runtime would put an orchestration choice where a
        # persisted fact belongs, and the whole point of allocating at GATE 2 is
        # that no choice is left.
        # Mutants: "join phase takes the wrong contributors lane",
        #          "retired lane id is reused later in the run".
        for _j2 in sorted(_joins):
            _want = _lanemap.get(_depmap[_j2][0])
            if _want and _lanemap.get(_j2) != _want:
                _untrusted = True
                bad(f"{relpath(tracker)}: {_phs[_j2]['label']} joins "
                    f"{len(_joins[_j2])} lanes and carries "
                    f"`· lane: {_lanemap.get(_j2)}`, but its first contributing "
                    f"predecessor in approved-plan order is "
                    f"{_phs[_depmap[_j2][0]]['label']} on lane {_want}. The "
                    "surviving lane is decided at GATE 2 and written down; the "
                    "orchestrator must not choose one at runtime. REMEDY: "
                    f"write `· lane: {_want}` on {_phs[_j2]['label']}")

        # ---- a retired lane id is never reused ----
        for _lid2 in sorted(_lane_phases):
            _ret = next((_j2 for _j2 in sorted(_joins)
                         if _lanemap.get(_j2) != _lid2
                         and _lid2 in _joins[_j2]), None)
            if _ret is None:
                continue
            _after = [_i2 for _i2 in _lane_phases[_lid2] if _i2 > _ret]
            if _after:
                _untrusted = True
                bad(f"{relpath(tracker)}: lane {_lid2} retires at "
                    f"{_phs[_ret]['label']}, which consumes it on lane "
                    f"{_lanemap.get(_ret)}, but {_phs[_after[0]]['label']} "
                    "carries it again later in approved-plan order. A retired "
                    "lane id is never allocated again in the same run — reusing "
                    "it makes a resumed run unable to tell which branch a phase "
                    "belongs to. REMEDY: allocate the next unused id")

        def _resolve_phase(value):
            """`(phase index, raw id)` for a lane line's value."""
            # ANCHORED AT THE START, and that is the whole of the fix for a
            # Critical. Searching the value for `phase <token>` anywhere read a
            # MENTIONED phase in preference to the named one: `Phase 3 — moved
            # on past the phase 2 fix loop` resolved to 2, and the gate passed
            # over a finding open against Phase 2. A lane line names its phase
            # FIRST — `templates/progress.md` prescribes `- **Lane <id>:**
            # Phase <id> — <that lane's next unchecked line>`.
            g = re.match(r"\s*(?:[Pp]hase\s+)?([0-9]+[0-9A-Za-z.]*)\b", value)
            if not g:
                return None, None
            return _idx.get(f"phase {g.group(1)}".lower()), g.group(1)

        _lane_named, _adv = [], []
        for _lid, _val in _lane_cs:
            # AN UNKNOWN LANE ID validates against nothing. The mapping is
            # persisted on the headings and Current State is checked against
            # it, so a lane existing only here is a position this gate cannot
            # reach — and `Lane Z: done` would otherwise read as a satisfied
            # state for a branch that never existed.
            if _lanemap and _lid not in _lane_phases:
                _untrusted = True
                bad(f"{relpath(tracker)}: Current State names "
                    f"`**Lane {_lid}:**`, which no `## Phase` heading carries "
                    "as `· lane:`. The phase → lane mapping is what this gate "
                    "validates positions against, so a lane that exists only in "
                    "Current State is a position nothing can check. REMEDY: "
                    "assign the lane on its phases' headings at GATE 2, or "
                    "remove the line")
                continue
            if _lid in _retired:
                _untrusted = True
                bad(f"{relpath(tracker)}: Current State still carries "
                    f"`**Lane {_lid}:**`, but that lane retired at "
                    f"{_phs[_retired[_lid]]['label']} — its leading `RVJ` is "
                    f"closed, so the join has collapsed onto "
                    f"{_lanemap.get(_retired[_lid])}. A retired lane id is "
                    "never reused and never left in Current State: a line here "
                    "says a branch is still executing that the run has already "
                    "folded in. REMEDY: remove the line")
                continue

            _i, _pid = _resolve_phase(_val)

            # ---- the two phase-less forms, validated as STATES ----
            if _i is None and _pid is None:
                _mw = re.match(r"waiting at join\s+(?:[Pp]hase\s+)?"
                               r"([0-9]+[0-9A-Za-z.]*)\b", _val, re.I)
                if re.match(r"done\b", _val, re.I):
                    # `done` IS A CLAIM, NOT A STRING. An executor writes it
                    # exactly when it believes the lane is over, which is
                    # precisely when it may be wrong about an open finding.
                    _own_open = [_unfinished[_i2] for _i2 in
                                 _lane_phases.get(_lid, [])
                                 if _i2 in _unfinished]
                    if _own_open:
                        bad(f"{relpath(tracker)}: Current State says "
                            f"`**Lane {_lid}:** done`, but {_own_open[0][1]} is "
                            f"assigned to that lane and still has "
                            f"{_own_open[0][2]}. A lane is `done` only when it "
                            "owns no unfinished task, no open `RV`, no "
                            "unresolved fix loop and no open blocking finding. "
                            "REMEDY: point the lane at its own next action")
                    elif _lid in _waiting:
                        bad(f"{relpath(tracker)}: Current State says "
                            f"`**Lane {_lid}:** done`, but that lane still "
                            f"contributes to {_phs[_waiting[_lid]]['label']}, "
                            "whose leading `RVJ` has not closed. A contributor "
                            "is not done while its join is unresolved — it is "
                            "waiting, and the run has to be able to tell the "
                            "two apart. REMEDY: write `waiting at join "
                            f"{_phs[_waiting[_lid]]['label']}`")
                elif _mw:
                    _jid = _mw.group(1)
                    _ji = _idx.get(f"phase {_jid}".lower())
                    _why = None
                    if _ji is None:
                        _why = (f"names phase {_jid!r}, which matches no "
                                "`## Phase` heading in this tracker")
                    elif _ji not in _joins:
                        _why = (f"names {_phs[_ji]['label']}, which is not a "
                                "join — its `· deps:` span fewer than two "
                                "lanes, so there is nothing there to wait for")
                    elif _lid not in _joins[_ji]:
                        _why = (f"names {_phs[_ji]['label']}, which this lane "
                                "does not contribute to — no phase assigned to "
                                f"lane {_lid} is a direct predecessor of it")
                    else:
                        _own_open = [_unfinished[_i2] for _i2 in
                                     _lane_phases.get(_lid, [])
                                     if _i2 in _unfinished]
                        if _own_open:
                            _why = (f"is waiting while {_own_open[0][1]}, "
                                    "assigned to this same lane, still has "
                                    f"{_own_open[0][2]} — a lane waits at a "
                                    "join only once its own branch has passed")
                    if _why:
                        _untrusted = True
                        bad(f"{relpath(tracker)}: Current State's "
                            f"`**Lane {_lid}:** waiting at join …` {_why}. "
                            "`waiting at join` is an orchestration state, not a "
                            "phrase: it says this lane's branch is complete and "
                            "the join it feeds has not opened. REMEDY: write "
                            "the state the lane is actually in")
                else:
                    _untrusted = True
                    bad(f"{relpath(tracker)}: Current State's "
                        f"`**Lane {_lid}:**` names no phase and is not one of "
                        "the two phase-less forms — its value is "
                        f"{_val[:40]!r}. A lane line is `Phase <id> — <that "
                        "lane's next unchecked line>`, or `done`, or `waiting "
                        "at join Phase <id>`. REMEDY: name the lane's phase")
                continue

            if _i is None:
                _untrusted = True
                bad(f"{relpath(tracker)}: Current State's `**Lane {_lid}:**` "
                    f"names phase {_pid!r}, which matches no `## Phase` heading "
                    "in this tracker — so the advancement check could not "
                    "locate that lane's own position and compared nothing. "
                    "REMEDY: name a phase the tracker has")
                continue

            # ---- LANE X MAY NAME PHASE P IFF PHASE P CARRIES `· lane: X` ----
            # Proving the lane merely EXISTS somewhere is not enough: a lane
            # naming another lane's phase is two branches claiming one phase,
            # and it is how a non-surviving contributor would come to run a
            # joining phase's leading `RVJ`.
            if _lanemap.get(_i) != _lid:
                _untrusted = True
                bad(f"{relpath(tracker)}: Current State's `**Lane {_lid}:**` "
                    f"names {_phs[_i]['label']}, which carries "
                    f"`· lane: {_lanemap.get(_i)}`. A phase is executed by "
                    "exactly one active lane, and it is the lane its own "
                    "heading names. REMEDY: let "
                    f"{_lanemap.get(_i)} run {_phs[_i]['label']}, and point "
                    f"lane {_lid} at a phase assigned to it")
                continue
            _lane_named.append((_lid, _i))

            # ---- per-lane advancement, against that lane's OWN phases ----
            # The old comparison was `max(_named) > _blockers[0][0]` — the
            # latest named position against the earliest unfinished phase
            # ANYWHERE — so Lane B legitimately at phase 6 while Lane A's phase
            # 2 was open made it true, and a conforming two-lane tracker
            # hard-failed this gate.
            _own = [b for b in _blockers if _lanemap.get(b[0]) == _lid]
            if _own and _i > _own[0][0]:
                _adv.append((_lid, _own[0]))

            # ---- a join cannot be entered early ----
            if _i in _joins:
                _openc = [b for b in _blockers if b[0] < _i
                          and _lanemap.get(b[0]) in _joins[_i]]
                _lead = _leading_rvj(_i)
                # THE GATE ACTION IS LEGAL, THE IMPLEMENTATION ACTION IS NOT.
                # Once every contributor is `PASS`, the surviving lane names the
                # leading `RVJ` — that is the gate being executed. Naming a task
                # is ENTERING the phase, and only a closed leading `RVJ`
                # licenses that.
                _isgate = re.search(r"(?:—|-)\s*RVJ\b", _val) is not None
                if _openc:
                    bad(f"{relpath(tracker)}: Current State's "
                        f"`**Lane {_lid}:**` names {_phs[_i]['label']}, which "
                        f"joins {len(_joins[_i])} lanes, while {_openc[0][1]} "
                        f"— assigned to a contributing lane — still has "
                        f"{_openc[0][2]}. A join is reachable only when every "
                        "contributing lane's last phase is `PASS`. REMEDY: "
                        f"write `waiting at join {_phs[_i]['label']}` until "
                        "the contributors close")
                elif not _lead:
                    _untrusted = True
                    bad(f"{relpath(tracker)}: {_phs[_i]['label']} joins "
                        f"{len(_joins[_i])} lanes but carries no leading "
                        "`RVJ` — an `RVJ` above the phase's first task, which "
                        "is what reviews the lanes that merged here. Without "
                        "it the join is entered on nobody's review. REMEDY: "
                        "add the leading `RVJ`, above the first task")
                elif not _isgate and not any(r[1] == "x" for r in _lead):
                    bad(f"{relpath(tracker)}: Current State's "
                        f"`**Lane {_lid}:**` names an implementation action in "
                        f"{_phs[_i]['label']} while its leading `RVJ` is not "
                        "`[x]`. A leading `RVJ` gates *entry* to a joining "
                        "phase, so the only action legal before it closes is "
                        "the `RVJ` itself — and a clean leading `RVJ` lets the "
                        "phase START, it never marks it `PASS`. REMEDY: name "
                        f"the gate — `{_phs[_i]['label']} — RVJ` — until it "
                        "closes")

        # ---- every active lane has exactly one Current State line ----
        _missing = sorted(_active - {l for l, _ in _lane_cs})
        for _lid in _missing:
            _untrusted = True
            _ps = [_i2 for _i2 in _lane_phases[_lid] if _i2 in _unfinished]
            _what = (f"{_phs[_ps[0]]['label']} is unfinished" if _ps else
                     f"it is waiting at {_phs[_waiting[_lid]]['label']}")
            bad(f"{relpath(tracker)}: lane {_lid} is active — {_what} — and has "
                "no `**Lane " + _lid + ":**` line in Current State. Every "
                "active lane carries exactly one, or a branch disappears from "
                "the run's own record and a resume has no way to notice it. "
                "REMEDY: add the line")

        for _lid, _b in _adv:
            bad(f"{relpath(tracker)}: Current State's `**Lane {_lid}:**` names "
                f"a phase later than {_b[1]}, which is assigned to that lane "
                f"and still has {_b[2]} — a phase is complete only when its "
                "tasks are `[x]`, its `RV` is `[x]` and every blocking finding "
                "scoped to it is closed. Advancing here is the orchestration "
                "failure this gate exists for: implementation complete is not "
                "phase complete, and an empty ledger is what an unreviewed "
                "phase looks like too. REMEDY: point that lane at its own next "
                "action — its review, or its fix loop")

        # THE RULE THE WHOLE ARM OBEYS: never print an affirmative line about a
        # comparison that did not happen.
        if _adv or _missing:
            pass
        elif _blockers and not _lane_named and not _lane_cs:
            bad(f"{relpath(tracker)}: {_blockers[0][1]} has "
                f"{_blockers[0][2]}, and no lane line names a phase — so there "
                "is nothing to compare it against and the advancement "
                "invariant is uncheckable on this tracker. REMEDY: name the "
                "phase on the lane that owns it")
        elif _lane_cs and not _untrusted:
            ok("no lane points past an unfinished phase of its own, and every "
               "active lane is named" + _ledger_note)
        elif _phs and not _blockers and not _untrusted:
            ok("no unfinished phase in the tracker" + _ledger_note)

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

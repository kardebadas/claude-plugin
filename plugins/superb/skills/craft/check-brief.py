#!/usr/bin/env python3
"""Mechanical completion check for a CRAFT.md.

Turns craft's completion criteria into something that gives the same answer
twice. `CRAFT STATUS: VISION CLEAR` requires this to pass, plus a fresh-context
reviewer — see the Ending section of SKILL.md for why one script is not enough.

Exit 0 = every predicate passed, 1 = one failed, 2 = no readable brief.
"""
import json, pathlib, re, sys

VAGUE = re.compile(r"(?:\bTBD\b|\bTODO\b|\betc\.|\bas appropriate\b|\bsomehow\b)", re.I)
# Accepts an em dash, en dash or hyphen; the exemption is per line, not per section.
NA    = re.compile(r"^[-*]?\s*Not applicable\s*[—–-]\s*\S+")
# These MUST match headings craft's own output template writes. test_check_brief
# asserts exactly that — an earlier version invented heading names, and every
# real brief failed the structure predicate for reasons unrelated to its quality.
REQUIRED_HEADINGS = ["Vision", "Target Users", "Scope", "Core Features",
                     "Domain Behaviour", "Explicit Non-Goals",
                     "Technical Preferences", "Confirmed Decisions",
                     "Open Questions", "Remaining Assumptions"]
FAILURES = []
ALL_LINES = []
DUPLICATES = []

def ok(p):        print("PASS %s" % p)
def fail(p, why): print("FAIL %s — %s" % (p, why)); FAILURES.append(p)
def skip(p, why): print("SKIP %s — %s" % (p, why))

def sections(text):
    """Map heading -> body, splitting on '## '. Fenced code is not content."""
    out, cur, fenced = {}, None, False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            cur = m.group(1).strip()
            if cur in out:
                DUPLICATES.append(cur)
            out.setdefault(cur, [])
        elif cur is not None:
            out[cur].append(line)
    return dict((k, "\n".join(v).strip()) for k, v in out.items())

def bullets(body):
    return [l.strip()[2:].strip() for l in body.split("\n") if l.strip().startswith("- ")]

def predicate_structure(sec):
    for h in REQUIRED_HEADINGS:
        if h not in sec:  return fail("structure", "missing heading: %s" % h)
        if not sec[h]:    return fail("structure", "empty heading: %s" % h)
        for line in sec[h].split("\n"):
            if VAGUE.search(line) and not NA.match(line.strip()):
                return fail("structure", "vagueness under %s: %s" % (h, line.strip()[:50]))
    ok("structure")

def predicate_nothing_open(sec):
    for line in sec.get("Open Questions", "").split("\n"):
        if "[REQUIRED]" in line or "[IMPORTANT]" in line:
            return fail("nothing-open", "still open: %s" % line.strip()[:60])
    # Contradictions are recorded as CON-* wherever they arise; the template has
    # no dedicated heading, so scan the whole brief rather than requiring one.
    for line in ALL_LINES[0].split("\n"):
        if "CON-" in line and "unresolved" in line.lower():
            return fail("nothing-open", line.strip()[:60])
    for line in sec.get("Remaining Assumptions", "").split("\n"):
        if "Impact: High" in line and "Status: Unconfirmed" in line:
            return fail("nothing-open", "high-impact unconfirmed: %s" % line.strip()[:60])
    ok("nothing-open")

def predicate_traceability(sec, craft_dir, text):
    rounds = sorted(craft_dir.glob("round-*.questions.json")) if craft_dir.is_dir() else []
    if not rounds:
        skip("traceability", "no round files; hand-written brief")
    else:
        for rf in rounds:
            try:
                obj = json.loads(rf.read_text(encoding="utf-8"))
            except Exception as e:
                return fail("traceability", "%s: %s" % (rf.name, e))
            for q in obj.get("questions", []):
                # schema.py: IMPORTANCES are uppercase. Comparing lowercase made
                # this predicate dead code that passed on anything.
                if str(q.get("importance", "")).upper() not in ("REQUIRED", "IMPORTANT"):
                    continue
                qid = str(q.get("id"))
                # Whole-token, or Q1 matches inside Q10 and a correct brief fails.
                hits = len(re.findall(r"(?<![\w-])" + re.escape(qid) + r"(?![\w-])", text))
                if hits == 0: return fail("traceability", "%s resolves to nothing" % qid)
                if hits > 1:  return fail("traceability", "%s appears %d times" % (qid, hits))
    # The template records decisions as **Source:** fields, not table rows.
    body = sec.get("Confirmed Decisions", "")
    for m in re.finditer(r"\*\*Source:\*\*\s*(.+)", body):
        src = m.group(1).strip().rstrip(".")
        if src and "user" not in src.lower():
            return fail("traceability", "a decision is sourced from %r, not the user" % src[:40])
    for row in body.split("\n"):
        cells = [c.strip() for c in row.split("|") if c.strip()]
        if len(cells) >= 3 and cells[0].startswith("DEC-") and "user" not in cells[2].lower():
            return fail("traceability", "%s sourced from %r, not a user answer" % (cells[0], cells[2]))
    if not FAILURES or FAILURES[-1] != "traceability":
        if rounds: ok("traceability")

def predicate_concreteness(sec):
    feats = bullets(sec.get("Core Features", ""))
    if not feats:
        return fail("concreteness", "Core Features lists no features")
    for b in feats:
        stripped = re.sub(r"https?://\S+", "", b)   # a URL's colon is not a separator
        if ":" not in stripped or len(stripped.split(":", 1)[1].split()) < 5:
            return fail("concreteness", "no acceptance sentence: %s" % b[:50])
    for b in bullets(sec.get("Domain Behaviour", "")):
        if ";" not in b:
            return fail("concreteness", "no rule beyond fields: %s" % b[:50])
    if not bullets(sec.get("Explicit Non-Goals", "")):
        return fail("concreteness", "Explicit Non-Goals is empty")
    for line in sec.get("Technical Preferences", "").split("\n"):
        t = line.strip()
        if not t.startswith("- "):
            continue
        if ":" not in t or not t.split(":", 1)[1].strip():
            return fail("concreteness", "axis neither chosen nor deferred: %s" % t[:50])
    ok("concreteness")

def main(argv):
    root = pathlib.Path(argv[1] if len(argv) > 1 else ".")
    brief = root / "CRAFT.md"
    try:
        text = brief.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print("FAIL brief — cannot read %s: %s" % (brief, e))
        print("check-brief: FAIL")
        return 2
    sec = sections(text)
    ALL_LINES.append(text)
    if DUPLICATES:
        fail("structure", "heading appears more than once: %s" % ", ".join(sorted(set(DUPLICATES))))
    predicate_structure(sec)
    predicate_nothing_open(sec)
    predicate_traceability(sec, root / ".craft", text)
    predicate_concreteness(sec)
    print()
    print("check-brief: FAIL" if FAILURES else "check-brief: PASS")
    return 1 if FAILURES else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))

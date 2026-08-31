#!/usr/bin/env python3
"""Mechanical completion check for a CRAFT.md.

Turns craft's completion criteria into something that gives the same answer
twice. `CRAFT STATUS: VISION CLEAR` requires this to pass, plus a fresh-context
reviewer — see the Ending section of SKILL.md for why one script is not enough.

Exit 0 = every predicate passed, 1 = one failed, 2 = no readable brief.
"""
import json, pathlib, re, sys

VAGUE = re.compile(r"\b(TBD|TODO|etc\.|as appropriate)\b", re.I)
NA    = re.compile(r"^Not applicable — .+", re.M)
REQUIRED_HEADINGS = ["Confirmed Decisions", "Core Features", "Domain Behaviour",
                     "User Types", "Explicit Non-Goals", "Technical Direction",
                     "Open Questions", "Assumptions", "Contradictions"]
FAILURES = []

def ok(p):        print("PASS %s" % p)
def fail(p, why): print("FAIL %s — %s" % (p, why)); FAILURES.append(p)
def skip(p, why): print("SKIP %s — %s" % (p, why))

def sections(text):
    """Map heading -> body, splitting on '## '."""
    out, cur = {}, None
    for line in text.split("\n"):
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            cur = m.group(1).strip(); out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return dict((k, "\n".join(v).strip()) for k, v in out.items())

def bullets(body):
    return [l.strip()[2:].strip() for l in body.split("\n") if l.strip().startswith("- ")]

def predicate_structure(sec):
    for h in REQUIRED_HEADINGS:
        if h not in sec:  return fail("structure", "missing heading: %s" % h)
        if not sec[h]:    return fail("structure", "empty heading: %s" % h)
        if VAGUE.search(sec[h]) and not NA.search(sec[h]):
            return fail("structure", "vagueness under %s" % h)
    ok("structure")

def predicate_nothing_open(sec):
    for line in sec.get("Open Questions", "").split("\n"):
        if "[REQUIRED]" in line or "[IMPORTANT]" in line:
            return fail("nothing-open", "still open: %s" % line.strip()[:60])
    for line in sec.get("Contradictions", "").split("\n"):
        if "CON-" in line and "unresolved" in line.lower():
            return fail("nothing-open", line.strip()[:60])
    for line in sec.get("Assumptions", "").split("\n"):
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
                if q.get("importance") not in ("required", "important"):
                    continue
                qid = str(q.get("id"))
                hits = text.count(qid)
                if hits == 0: return fail("traceability", "%s resolves to nothing" % qid)
                if hits > 1:  return fail("traceability", "%s appears %d times" % (qid, hits))
    for row in sec.get("Confirmed Decisions", "").split("\n"):
        cells = [c.strip() for c in row.split("|") if c.strip()]
        if len(cells) >= 3 and cells[0].startswith("DEC-") and cells[2] != "User answer":
            return fail("traceability", "%s sourced from %r, not a user answer" % (cells[0], cells[2]))
    if not FAILURES or FAILURES[-1] != "traceability":
        if rounds: ok("traceability")

def predicate_concreteness(sec):
    for b in bullets(sec.get("Core Features", "")):
        if ":" not in b or len(b.split(":", 1)[1].split()) < 5:
            return fail("concreteness", "no acceptance sentence: %s" % b[:50])
    for b in bullets(sec.get("Domain Behaviour", "")):
        if ";" not in b:
            return fail("concreteness", "no rule beyond fields: %s" % b[:50])
    if not bullets(sec.get("Explicit Non-Goals", "")):
        return fail("concreteness", "Explicit Non-Goals is empty")
    for line in sec.get("Technical Direction", "").split("\n"):
        if line.strip().startswith("- ") and ":" not in line:
            return fail("concreteness", "axis neither chosen nor deferred: %s" % line.strip()[:50])
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
    predicate_structure(sec)
    predicate_nothing_open(sec)
    predicate_traceability(sec, root / ".craft", text)
    predicate_concreteness(sec)
    print()
    print("check-brief: FAIL" if FAILURES else "check-brief: PASS")
    return 1 if FAILURES else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))

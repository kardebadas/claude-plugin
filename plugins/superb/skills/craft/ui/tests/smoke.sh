#!/usr/bin/env bash
# End to end, in one command: a real server, real HTTP, a real browser where
# there is one, and a throwaway project that is deleted whatever happens.
#
# This is not another integration test. There are 765 of those, several of
# which start servers and drive browsers, and each of them answers a narrow
# question well. This one answers the only question somebody who has just
# cloned the repo or changed something big actually has: does the whole thing
# still work? So it walks the path an agent walks -- serve, post a round, let
# the page render it, autosave, submit, wait, read the answers back, post the
# next round, ask for status, stop -- and it says what it is checking before
# each step so that a failure is a diagnosis rather than a stack trace.
#
# Three rules it keeps, each of which was a defect somewhere in this project:
#
#   * The project directory is a mktemp -d and it is removed on every exit
#     path, success or failure or interrupt.
#   * The server is reaped on every exit path too. A leaked one holds a kernel
#     lock on its project with a four hour idle timeout, and `pgrep -cf`
#     matches its own wrapper on this machine and lies about whether one is
#     left -- so the sweep reads `ps -eo pid,args` and matches this run's own
#     project directory.
#   * Nothing is asserted about wall clock. Every property here is a relative
#     one -- an exit code, a token, a file's contents -- because an absolute
#     timing assertion in this suite flaked for four tasks running.
set -euo pipefail

UI_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CRAFTUI="$UI_DIR/craftui.py"

# -B and the environment variable together: a smoke test must not leave
# __pycache__ behind in a tree it only read.
export PYTHONDONTWRITEBYTECODE=1
PY=(python3 -B)

# One throwaway root. The project is a directory INSIDE it, so this script's
# own scratch files -- captured stderr, a browser profile -- never appear in
# the project the tool is being asked to manage.
ROOT="$(mktemp -d "${TMPDIR:-/tmp}/craft-smoke.XXXXXXXX")"
WORK="$ROOT/project"
CRAFT="$WORK/.craft"
ERR="$ROOT/stderr"

reap_servers() {
    # ps, not pgrep: `pgrep -cf craftui.py serve` matches the shell that is
    # running this line and reports a server that does not exist. The match is
    # on this run's own project directory, so a craft session the developer
    # has open on a real project is never touched.
    local pid
    for pid in $(ps -eo pid,args 2>/dev/null \
        | awk -v dir="$WORK" '/craftui\.py serve/ && index($0, dir) { print $1 }'); do
        kill "$pid" 2>/dev/null || true
    done
}

cleanup() {
    local status=$?
    "${PY[@]}" "$CRAFTUI" stop --project-dir "$WORK" >/dev/null 2>&1 || true
    reap_servers
    rm -rf "$ROOT"
    return "$status"
}
trap cleanup EXIT
# Ctrl-C and a kill both have to reach the cleanup above, and neither runs an
# EXIT trap on its own -- they exit through one instead. Without this, an
# interrupted run leaves a server holding a lock on a directory it also just
# deleted, which is the one state this script must never produce.
trap 'exit 130' INT
trap 'exit 143' TERM

phase() { printf '\n  %s\n' "$1"; }
step() { printf '    %-56s' "$1"; }
ok() { printf 'ok\n'; }
skip() { printf 'skipped -- %s\n' "$1"; }

die() {
    printf 'FAILED\n\n'
    printf 'smoke: %s\n' "$1" >&2
    printf '  expected: %s\n' "$2" >&2
    printf '  got:      %s\n' "$3" >&2
    exit 1
}

# Run a craftui command, keeping its stdout and its exit code apart from its
# stderr -- `wait` prints its outcome on stdout and a heartbeat note on
# stderr, and folding the two together would make the outcome unreadable.
out=""
rc=0
craftui() {
    set +e
    out="$("${PY[@]}" "$CRAFTUI" "$@" 2>"$ERR")"
    rc=$?
    set -e
}

# The first line of stderr, for a diagnostic. Whole tracebacks belong in the
# terminal, not in an expected-versus-got.
why() { head -n 1 "$ERR" 2>/dev/null || true; }

printf 'smoke: craft UI, end to end\n'
printf '  project: %s\n' "$WORK"

# --------------------------------------------------------------- the project

mkdir -p "$CRAFT"
printf '# Vision\n\nA small music player.\n' >"$WORK/CRAFT.md"
cat >"$CRAFT/round-001.questions.json" <<'JSON'
{"round": 1,
 "questions": [{"id": "Q-1", "importance": "REQUIRED", "title": "How should users authenticate?",
                "type": "single", "delegable": true,
                "options": [{"value": "email", "label": "Email and password"},
                            {"value": "magic", "label": "Magic link"}]}]}
JSON

phase "before a server exists"

step "status describes the project and starts nothing"
craftui status --project-dir "$WORK"
[ "$rc" = 0 ] || die "status failed on a project with no server" "exit 0" "exit $rc: $(why)"
got="$(printf '%s' "$out" | "${PY[@]}" -c 'import json,sys
s = json.loads(sys.stdin.read())
print("server={} round={} total={}".format(s["server"], s["round"], s["total_questions"]))')"
[ "$got" = "server=False round=1 total=1" ] \
    || die "status misread a project whose round is on disk" \
           "server=False round=1 total=1" "$got"
[ ! -e "$CRAFT/server-info" ] || die "status wrote server-info" "no server-info" "one exists"
ok

# ------------------------------------------------------------------- serving

phase "serving"

step "serve starts a detached server and says where"
craftui serve --project-dir "$WORK"
[ "$rc" = 0 ] || die "serve did not start" "exit 0" "exit $rc: $out $(why)"
INFO="$out"
read -r URL KEY PORT PID <<<"$(printf '%s' "$INFO" | "${PY[@]}" -c 'import json,sys
i = json.loads(sys.stdin.read())
print(i["url"], i["key"], i["port"], i["pid"])')"
[ -n "$URL" ] && [ -n "$KEY" ] || die "serve printed no url or key" "both" "$INFO"
kill -0 "$PID" 2>/dev/null || die "the pid serve reported is not running" "pid $PID alive" "gone"
# Not ${URL%%/?*}: `?` is a shell glob, so that pattern eats the whole
# authority and leaves "http:". The key is stripped here and nowhere else --
# every request below appends its own.
BASE="${URL%%\?*}"
BASE="${BASE%/}"
ok

step "a second serve is refused, and destroys nothing"
craftui serve --project-dir "$WORK"
[ "$rc" = 4 ] || die "a second serve on a held project was not refused" "exit 4 (LOCKED)" "exit $rc: $out"
case "$out" in
    LOCKED*) ;;
    *) die "a refused serve did not say LOCKED" "a line starting LOCKED" "$out" ;;
esac
kill -0 "$PID" 2>/dev/null || die "a refused serve killed the running server" "pid $PID alive" "gone"
ok

# ------------------------------------------------------------------ the page

phase "the page"

BROWSER=""
for candidate in chromium chromium-browser google-chrome google-chrome-stable chrome; do
    if command -v "$candidate" >/dev/null 2>&1; then
        BROWSER="$(command -v "$candidate")"
        break
    fi
done

step "a real browser loads it and renders the round"
if [ -z "$BROWSER" ]; then
    skip "no chromium or chrome on this machine"
else
    mkdir -p "$ROOT/home"
    set +e
    # --virtual-time-budget is virtual milliseconds: the clock runs as fast as
    # the page allows and pauses while a fetch is outstanding, so this is not
    # a wall-clock wait. `timeout` is, and it is a bound on a wedged browser
    # rather than a budget for an honest one.
    DOM="$(HOME="$ROOT/home" timeout 90 "$BROWSER" --headless --no-sandbox \
        --disable-gpu --no-first-run --no-default-browser-check \
        --disable-extensions --user-data-dir="$ROOT/chrome" \
        --virtual-time-budget=8000 --dump-dom "$URL" 2>"$ERR")"
    rc=$?
    set -e
    [ "$rc" = 0 ] || die "the browser did not render the page" "exit 0" "exit $rc: $(why)"
    case "$DOM" in
        *'data-id="Q-1"'*) ;;
        *) die "the page did not render the round it was served" \
               'a card with data-id="Q-1"' "no such element in the DOM" ;;
    esac
    case "$DOM" in
        *"How should users authenticate?"*) ;;
        *) die "the rendered card carries no question title" \
               "the title from round-001.questions.json" "it is not in the DOM" ;;
    esac
    case "$DOM" in
        *"<h1>Vision</h1>"*) ;;
        *) die "CRAFT.md was not rendered into the page" \
               "<h1>Vision</h1> from CRAFT.md" "it is not in the DOM" ;;
    esac
    ok
fi

# ------------------------------------------------------------------- the api

phase "the api, over real HTTP"

"${PY[@]}" - "$BASE" "$KEY" <<'PY'
"""Every request the page makes, plus the two refusals it must never need.

Written to the same shape as the shell around it: say what is being checked,
then say what was expected and what came back. Nothing here imports the
server -- this is a client, and the point is that a client with nothing but
the URL and the key can do the whole round trip.
"""
import json
import socket
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

BASE, KEY = sys.argv[1], sys.argv[2]
HOST = urlsplit(BASE).hostname
PORT = urlsplit(BASE).port


def step(what):
    sys.stdout.write("    {:<56}".format(what))
    sys.stdout.flush()


def ok():
    print("ok")


def die(what, expected, got):
    print("FAILED\n")
    sys.stdout.flush()
    sys.stderr.write("smoke: {}\n  expected: {}\n  got:      {}\n".format(
        what, expected, got))
    raise SystemExit(1)


def want(what, expected, got):
    if expected != got:
        die(what, expected, got)


def call(path, method="GET", body=None, key=KEY):
    """(status, decoded body). An HTTP error is an answer, not an exception."""
    url = BASE + path
    if key is not None:
        url += ("&" if "?" in path else "?") + "key=" + key
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"})
    try:
        response = urllib.request.urlopen(request, timeout=15)
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")
    with response:
        return response.status, response.read().decode("utf-8", "replace")


def as_json(path, **kwargs):
    code, text = call(path, **kwargs)
    if code != 200:
        die("{} did not answer".format(path), "HTTP 200", "HTTP {}: {}".format(code, text[:120]))
    try:
        return json.loads(text)
    except ValueError:
        die("{} did not answer with JSON".format(path), "a JSON object", text[:120])


def status_line(headers, body=b"", method="POST", path="/api/submit"):
    """One raw request, and the status line that came back.

    A raw socket rather than urllib, because the two refusals below are
    answered from the HEADERS -- the server never reads the body -- and a
    client that goes on writing a megabyte into a socket whose peer has
    already replied and closed gets a broken pipe instead of the answer.
    """
    client = socket.create_connection((HOST, PORT), 15)
    try:
        target = path + "?key=" + KEY
        head = "{} {} HTTP/1.1\r\nHost: {}\r\n".format(method, target, HOST)
        head += "".join(h + "\r\n" for h in headers) + "\r\n"
        client.sendall(head.encode("utf-8") + body)
        client.settimeout(15)
        received = b""
        while True:
            try:
                chunk = client.recv(4096)
            except (ConnectionResetError, socket.timeout):
                break
            if not chunk:
                break
            received += chunk
    finally:
        client.close()
    if not received:
        return "(the server said nothing at all)"
    return received.splitlines()[0].decode("latin-1")


step("no key is refused, and so is the wrong key")
want("an unauthenticated GET was answered", 403, call("/", key=None)[0])
want("a GET with the wrong key was answered", 403, call("/", key="0" * 64)[0])
ok()

step("GET / serves the page")
code, page = call("/")
want("the page did not serve", 200, code)
if 'id="questions"' not in page:
    die("the page served is not the craft UI", 'a document with id="questions"',
        page[:120])
ok()

step("GET /api/round serves the round on disk")
payload = as_json("/api/round")
want("the round was not served", True, payload.get("ok"))
want("the wrong round was served", 1, (payload.get("round") or {}).get("round"))
want("the round's question did not survive the trip", "Q-1",
     payload["round"]["questions"][0]["id"])
ok()

step("GET /api/brief renders CRAFT.md")
html = as_json("/api/brief").get("html", "")
if "<h1>Vision</h1>" not in html:
    die("CRAFT.md was not rendered", "<h1>Vision</h1>", html[:120])
ok()

step("PATCH /api/draft autosaves, and the draft reads back")
code, text = call("/api/draft", "PATCH", {
    "round": 1, "seq": 1,
    "answers": {"Q-1": {"choice": ["email"], "note": "typed, never sent"}}})
want("the draft was not saved", 200, code)
want("the draft save was not acknowledged", {"ok": True}, json.loads(text))
draft = as_json("/api/draft?round=1")
want("the draft did not read back", ["email"], draft["answers"]["Q-1"]["choice"])
ok()

step("a body over 1 MiB is refused on its header alone")
line = status_line(["Content-Length: 1048577"])
if " 413 " not in line:
    die("an oversized body was not refused", "a 413 status line", line)
ok()

step("a body nested past the documented depth is refused")
nested = {}
for _ in range(12):
    nested = {"x": nested}
code, text = call("/api/submit", "POST", {"round": 1, "answers": {"Q-1": nested}})
want("deeply nested JSON was not refused", 400, code)
if "nests" not in json.loads(text).get("error", ""):
    die("the refusal did not say why", "an error mentioning nesting", text[:120])
ok()

step("POST /api/submit sends the round")
code, text = call("/api/submit", "POST", {
    "round": 1, "finished": False,
    "answers": {"Q-1": {"delegated": True, "note": "you pick"}}})
want("the round was not accepted", 200, code)
want("the submission was not acknowledged", {"ok": True, "finished": False},
     json.loads(text))
ok()
PY

# --------------------------------------------------------------------- wait

phase "the agent's turn"

step "wait returns SUBMITTED and names the answers file"
craftui wait --project-dir "$WORK" --round 1 --timeout 10
[ "$rc" = 0 ] || die "wait did not see the submitted round" "exit 0" "exit $rc: $out $(why)"
[ "$out" = "SUBMITTED round=1 answers=$CRAFT/round-001.answers.json" ] \
    || die "wait did not report the round it was waiting on" \
           "SUBMITTED round=1 answers=$CRAFT/round-001.answers.json" "$out"
ok

step "the answers on disk are the ones POSTed, not the draft"
set +e
"${PY[@]}" - "$CRAFT" <<'PY'
import json
import sys
from pathlib import Path

craft = Path(sys.argv[1])
answers = json.loads((craft / "round-001.answers.json").read_text("utf-8"))
draft = json.loads((craft / "round-001.draft.json").read_text("utf-8"))


def fail(what, expected, got):
    print("FAILED\n")
    sys.stdout.flush()
    sys.stderr.write("smoke: {}\n  expected: {}\n  got:      {}\n".format(
        what, expected, got))
    raise SystemExit(1)


if answers.get("round") != 1 or answers.get("finished") is not False:
    fail("the answers file does not describe round 1",
         '{"round": 1, "finished": false, ...}',
         json.dumps({k: answers.get(k) for k in ("round", "finished")}))
if not str(answers.get("submitted_at", "")).endswith("Z"):
    fail("the submission carries no UTC stamp", "an ISO stamp ending in Z",
         repr(answers.get("submitted_at")))
# The contract this exists for: POST writes from the POST body and never
# promotes the draft. The draft says `choice`, the submission says
# `delegated`, and confusing the two would silently re-ask a question the
# user deliberately handed over.
if answers["answers"]["Q-1"] != {"delegated": True, "note": "you pick"}:
    fail("submit did not store what was POSTed",
         '{"delegated": true, "note": "you pick"}',
         json.dumps(answers["answers"]["Q-1"]))
if draft["answers"]["Q-1"].get("choice") != ["email"]:
    fail("the draft was rewritten by the submission",
         'the draft still holding {"choice": ["email"], ...}',
         json.dumps(draft["answers"]["Q-1"]))
PY
rc=$?
set -e
# The block above has already said what it expected and what it found, in the
# same shape as die(). A second message here would only repeat it.
[ "$rc" = 0 ] || exit 1
ok

# ------------------------------------------------------------- the next round

phase "the next round"

cat >"$CRAFT/round-002.questions.json" <<'JSON'
{"round": 2,
 "questions": [{"id": "Q-2", "importance": "IMPORTANT", "title": "Who is it for?",
                "type": "text"},
               {"id": "Q-3", "importance": "OPTIONAL", "title": "Anything else?",
                "type": "longtext"}]}
JSON

step "the running server serves the round posted under it"
"${PY[@]}" - "$BASE" "$KEY" "$CRAFT" <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

base, key, craft = sys.argv[1], sys.argv[2], Path(sys.argv[3])


def fail(what, expected, got):
    print("FAILED\n")
    sys.stdout.flush()
    sys.stderr.write("smoke: {}\n  expected: {}\n  got:      {}\n".format(
        what, expected, got))
    raise SystemExit(1)


def get(path):
    with urllib.request.urlopen(base + path + "?key=" + key, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


payload = get("/api/round")
if not payload.get("ok") or payload["round"]["round"] != 2:
    fail("a round written under a live server was not picked up", "round 2",
         json.dumps(payload)[:160])

# A round whose `round` field disagrees with its filename is served to nobody:
# every PATCH and POST the page then sent would address the wrong round and
# overwrite answers that were already submitted.
(craft / "round-003.questions.json").write_text(
    json.dumps({"round": 2, "questions": []}), encoding="utf-8")
try:
    payload = get("/api/round")
    if payload.get("ok") is not False:
        fail("a round that disagrees with its filename was served anyway",
             "ok: false with details", json.dumps(payload)[:160])
    if not any("round" in detail for detail in payload.get("details", [])):
        fail("the refusal did not name the disagreement",
             "a detail mentioning the round number",
             json.dumps(payload.get("details"))[:160])
finally:
    (craft / "round-003.questions.json").unlink()
PY
ok

step "status reports the new round and the live server"
craftui status --project-dir "$WORK"
[ "$rc" = 0 ] || die "status failed against a live server" "exit 0" "exit $rc: $(why)"
got="$(printf '%s' "$out" | "${PY[@]}" -c 'import json,sys
s = json.loads(sys.stdin.read())
print("server={} round={} total={} answered={} draft={} open={} key={}".format(
    s["server"], s["round"], s["total_questions"], s["answered"], s["has_draft"],
    s["open"]["IMPORTANT"], "?" in (s["url"] or "")))')"
[ "$got" = "server=True round=2 total=2 answered=0 draft=False open=1 key=False" ] \
    || die "status misread a live session on round 2" \
           "server=True round=2 total=2 answered=0 draft=False open=1 key=False" "$got"
ok

step "wait on an unanswered round times out as a heartbeat"
craftui wait --project-dir "$WORK" --round 2 --timeout 0.5
[ "$rc" = 2 ] || die "an unanswered round did not time out as one" "exit 2 (TIMEOUT)" "exit $rc: $out"
[ "$out" = "TIMEOUT round=2" ] || die "wait's timeout line changed" "TIMEOUT round=2" "$out"
ok

# -------------------------------------------------------------------- stopping

phase "stopping"

step "stop waits for the process and says STOPPED"
craftui stop --project-dir "$WORK"
[ "$rc" = 0 ] || die "stop did not stop the server" "exit 0 (STOPPED)" "exit $rc: $out"
[ "$out" = "STOPPED" ] || die "stop said something else" "STOPPED" "$out"
if kill -0 "$PID" 2>/dev/null; then
    die "stop returned before the server died" "pid $PID gone" "still running"
fi
ok

step "server-info survives, and presence is not liveness"
[ -f "$CRAFT/server-info" ] || die "stop deleted server-info" \
    "server-info kept, so the next serve reuses the port" "it is gone"
craftui status --project-dir "$WORK"
got="$(printf '%s' "$out" | "${PY[@]}" -c 'import json,sys
s = json.loads(sys.stdin.read())
print("server={} port={}".format(s["server"], s["port"] == '"$PORT"'))')"
[ "$got" = "server=False port=True" ] \
    || die "status read a stopped session as running" \
           "server=False, and the old port still reported" "$got"
ok

step "a second stop reports NOSERVER rather than a kill"
craftui stop --project-dir "$WORK"
[ "$rc" = 3 ] || die "stop signalled something on a dead session" "exit 3 (NOSERVER)" "exit $rc: $out"
[ "$out" = "NOSERVER" ] || die "stop said something else" "NOSERVER" "$out"
ok

step "the project is free: it can be served again"
craftui serve --project-dir "$WORK"
[ "$rc" = 0 ] || die "the project was still locked after stop" "exit 0" "exit $rc: $out"
craftui stop --project-dir "$WORK"
[ "$rc" = 0 ] || die "the second session would not stop" "exit 0 (STOPPED)" "exit $rc: $out"
ok

step "a mistyped flag exits 64, which is not TIMEOUT"
craftui wait --project-dir "$WORK" --round nonsense
[ "$rc" = 64 ] || die "a usage error did not exit 64" \
    "exit 64 -- exit 2 would read as TIMEOUT and be waited on again" "exit $rc"
ok

step "no craftui server is left running"
left="$(ps -eo pid,args 2>/dev/null \
    | awk -v dir="$WORK" '/craftui\.py serve/ && index($0, dir) { print $1 }' | tr '\n' ' ')"
[ -z "$left" ] || die "this run leaked a server holding a project lock" \
    "no craftui serve process for this project" "pid(s) $left"
ok

printf '\nsmoke ok\n'

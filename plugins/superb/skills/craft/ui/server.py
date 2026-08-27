"""HTTP surface for the craft UI.

Deliberately stupid: it moves JSON between the agent's files and the browser
and renders CRAFT.md for display. It makes no product decisions, contacts no
model, and never writes CRAFT.md.

It is also the only part of this tool that anything on the machine can reach,
so the parts that are not stupid are all in one place and all here:

* Loopback only, enforced in the constructor rather than assumed from a
  default argument, and enforced BEFORE the bind.
* Every request carries the session key, whatever its method, checked
  before the path is even looked at -- so a caller without it cannot tell an
  endpoint from a typo, and cannot use the 404 as a filesystem probe. GET,
  PATCH and POST go somewhere; every other method, the ones nobody here has
  heard of included, is refused behind the key rather than by the stdlib in
  front of it. The stdlib answers an unbound method with its own 501 before
  any handler runs, which is why each write handler checks the key itself,
  first, rather than inheriting a check from anywhere.
  The one thing that stays in front of it is a request the stdlib cannot
  parse at all -- a URL too long, too many headers, an HTTP version it does
  not speak -- which it answers itself with 414, 431 or 505 before any code
  here runs. Those touch nothing and say nothing about the machine, but they
  are not gated, and claiming otherwise would be a lie in a docstring people
  will trust.
* The key travels in the query string and nowhere else. There is no session
  cookie and no code here that would read one: cookies are scoped to a HOST
  and not to a port (RFC 6265 s8.5), so a cookie set by this server is a
  cookie any other http://127.0.0.1:<port> page can make the browser fetch
  and read back -- and a stolen one was a complete credential, since a
  request carrying it needed no key in the URL at all.
* The key is compared in constant time, against every value the query string
  offers for it.
* Extracting that key is total: a request target that will not parse yields
  no key and the ordinary 403, never an exception in front of the gate.
* Nothing derived from the request becomes a filesystem path except one
  round NUMBER, which is an integer between 1 and 999 or the request is
  refused, and which is then formatted into a fixed name inside .craft/.
  Five URLs are served and there is no static file handler at all.
* Two of those URLs read a request body, so the body is framed strictly:
  one Content-Length, digits only, no Transfer-Encoding, a hard ceiling on
  the size, and the connection ends afterwards whatever happened. Two
  framings, or a length that turns out to be a lie, are the two ways a
  second request rides down a connection nobody authorised it on.
* A ceiling on the request is not a ceiling on the write. The writer
  indents, so every level of nesting a caller sends multiplies every byte
  they send -- measured, 653x -- and the depth of an accepted body is
  therefore bounded as well as its size. See MAX_BODY_DEPTH.
* A body this server accepts is a body it can store, and that is checked
  before anything is written rather than discovered while writing. Text a
  UTF-8 file will not take, and nesting the JSON decoder will not read, are
  both refused with an answer, because the alternative is no answer at all.
* The server writes inside .craft/ and nowhere else. It never writes
  CRAFT.md: the brief is the agent's to author, and this process only ever
  reads it.
* A write cannot outlive the session's claim on the project. Handler threads
  are daemons and are not joined at close, so the shutdown shuts the write
  gate and drains it, bounded, before the project lock is let go -- see
  CraftServer.begin_write. Without that, one session's write landed in a
  project another session already owned.
* Starting a session sweeps the .tmp- files a killed one left in .craft/.
  The atomic write cleans up in an except clause, and process death does
  not run one.
* An error tells the browser which of the agent's files is wrong by name and
  stops there: no absolute paths, no tracebacks, nothing about the machine.
* The agent's terminal learns no more than the browser does. Request logging
  is off, and a client hanging up mid-response -- which is all a reload is --
  is counted rather than printed as a traceback full of absolute paths.
* A connection is bounded twice, by two clocks that are not the same clock.
  `timeout` is the idle one socketserver applies with settimeout(); the
  ceiling on reading a whole request is `read_budget`, an absolute deadline,
  because an idle clock every arriving byte resets is not a ceiling at all.
  The budget is armed again for the body, which is a second thing an idle
  clock cannot bound.
"""
# Deliberate: kept so any annotation added later may use `int | None` syntax
# while this project's floor is Python 3.9. Do not delete.
from __future__ import annotations

import hmac
import io
import ipaddress
import json
import re
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import markdown
import schema
from session import describe_os_error, read_json, write_json_atomic

APP_HTML = Path(__file__).with_name("app.html")

# 256 bits from the OS CSPRNG. The key travels in a URL the user pastes into
# a browser, so it has to survive being seen without being guessable, and hex
# survives copy-paste, shells and query strings without encoding.
KEY_BYTES = 32

# The ceiling on one request body. Nothing this server accepts is large: a
# round of answers is text a person typed into a form, and a megabyte is
# already a hundred times the longest honest one. The number is not the
# point -- having one is. Without it, anything on this machine that holds
# the key can hand this process a body the size of the disk and watch it be
# written into the user's project as a file they never asked for.
MAX_BODY_BYTES = 1 << 20

# The ceiling on what a body may BECOME, which the one above is not.
#
# write_json_atomic serialises with indent=2, and indentation is charged per
# nesting level on every line of the file -- so a caller who nests deeply
# multiplies every byte they send. Measured against a live server: a
# 1,048,384-byte body (one byte under the ceiling above) nested 975 deep
# wrote a 685,214,154-byte file into .craft/ in the user's project. 653x.
#
# That is word for word what MAX_BODY_BYTES' own comment says it exists to
# prevent, and no byte ceiling can prevent it, because the amplification
# factor is exactly the thing a byte ceiling does not bound. Bounding the
# depth is what closes it: it is the multiplier itself, and it is the only
# quantity here that a caller controls and the ceiling above cannot see.
#
# A round of answers is flat. The deepest thing the page sends is
# {"round": 1, "answers": {"Q-1": {"choice": ["email"]}}} -- four levels,
# counting the body itself. Six leaves two levels of headroom for an answer
# shape the agent invents later, and holds the worst case to one line of
# 2*6 indent plus a digit plus ",\n" per two bytes of "1," sent: 7.5 output
# bytes per input byte. Measured against a live server, the worst body it
# will now accept is 1,048,575 bytes and writes 7,864,149 -- 7.5x, and the
# derivation and the measurement agree to the byte.
#
# Not solved by dropping indent=2. That is write_json_atomic's contract and
# these files are read by humans; dropping it would only shrink the
# constant, leaving a multiplier nothing bounds.
MAX_BODY_DEPTH = 6

# The temp file an unfinished write leaves behind, exactly as
# session.write_json_atomic names it: tempfile.mkstemp(dir=path.parent,
# prefix=".tmp-", suffix=".json"). Nothing else in .craft/ wears this name --
# every file the tool writes is round-NNN.something.json.
TMP_GLOB = ".tmp-*.json"

# How long a .tmp- file must have sat untouched before the sweep will remove
# it. The sweep cannot tell an orphan from a temp file another process is in
# the middle of using: on disk they are the same file. So it does not try. A
# write through write_json_atomic is one json.dump, one fsync and one
# rename -- milliseconds -- and anything untouched for five seconds is not a
# write in flight. The error is deliberately on the safe side: an orphan the
# sweep skips is swept by the next start, while a temp file it removes by
# mistake is somebody else's os.replace failing.
TMP_GRACE_S = 5

# The round numbers that can exist at all. session.ROUND_RE matches exactly
# three digits, and every round file is named with "{:03d}", so a round of
# 1000 writes a file the rest of the tool can never find again -- and a big
# enough one is a filename the kernel refuses outright, which would be an
# OSError raised out of a request holding a perfectly valid key.
MIN_ROUND = 1
MAX_ROUND = 999

# A round number as it may be written in a request: decimal digits, no sign,
# no leading zero, and short enough that the range check below is what
# actually decides. Not str.isdigit(), which is true of "٣" -- and int()
# then turns that into 3, so a check written with isdigit() and one written
# with int() disagree about the same string. No leading zeros because one
# round has one spelling: "0001" and "1" naming the same file is a way for
# two callers to think they are looking at different rounds.
_ROUND_TEXT = re.compile(r"\A(?:0|[1-9][0-9]{0,3})\Z")

# A Content-Length as it may be written in a request. Digits only: no sign,
# no whitespace, no "1, 1", no hex. Nineteen of them is past any length a
# 64-bit machine can have and is rejected as a size rather than as a
# syntax error, which is the more useful thing to be told.
_LENGTH_TEXT = re.compile(r"\A[0-9]{1,19}\Z")


# Said the same way wherever a round number is missing or impossible, on the
# query string and in a body alike, so the two cannot drift apart.
_NO_ROUND = {"ok": False, "error": "a round number from 1 to 999 is required"}

# What a write is told once the session is on its way out. A 503 rather than
# a 500: nothing is wrong with the request, and the client should feel free
# to say so to the user rather than report it as a bug. It names no file and
# no path -- there is no file, because nothing was opened.
SHUTTING_DOWN = "the craft session is shutting down; nothing was written"


def parse_round(value):
    """A round number from a request, or None if it is not one.

    Total, and deliberately stricter than int(). int(1.9) is 1, so a round
    number that arrived as a float would quietly write a round of answers
    over a different round's file -- silent data loss, and the browser is
    not the only thing that can send this. bool is an int in Python, so
    True would be round 1 as well. A digit string is accepted because the
    query string has no other way to carry a number.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not _ROUND_TEXT.match(value):
            return None
        value = int(value)
    if not isinstance(value, int):
        return None
    if not MIN_ROUND <= value <= MAX_ROUND:
        return None
    return value


def body_refusal(body):
    """Why a decoded body must not be written, or None if it may be.

    Two questions in one walk, because they are the same question: will the
    thing that stores this survive storing it? Neither is about how many
    bytes arrived, which is the only question MAX_BODY_BYTES can answer.

    Depth, because the writer indents. Every nesting level a caller sends is
    charged again on every line below it, so nesting is a multiplier on the
    file and MAX_BODY_BYTES never sees it. See MAX_BODY_DEPTH for the
    measurement.

    Text, because json.loads accepts "\\ud800" and a UTF-8 file will not
    take it. A browser produces that on its own -- ES2019 JSON.stringify
    escapes a lone surrogate as \\ud800 and Python decodes it straight back
    -- and json.dump into a UTF-8 file then raises UnicodeEncodeError, which
    is a ValueError and NOT an OSError, so it went straight past _store's
    guard and out of the handler with no response at all. Keys as well as
    values: a question id is a key, and the writer encodes both.

    Iterative on an explicit stack, never recursive. A recursive walk of a
    body a caller chose is the RecursionError _read_body catches, moved into
    our own code where nothing would catch it.
    """
    stack = [(body, 1)]
    while stack:
        value, level = stack.pop()
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                # The offending text is not quoted back. It is the user's,
                # and a refusal is not a place to print it.
                return "the request body carries text that is not valid Unicode"
            continue
        if isinstance(value, dict):
            # Keys and values both: the writer encodes both, and the
            # surrogate was reproduced in a question id as well as in an
            # answer. A dict at level N puts both one level further in.
            children = list(value) + list(value.values())
        elif isinstance(value, list):
            children = value
        else:
            continue  # a number, a bool, a null: nothing to descend into
        if level > MAX_BODY_DEPTH:
            return "the request body nests deeper than {} levels".format(MAX_BODY_DEPTH)
        for child in children:
            stack.append((child, level + 1))
    return None


class _BadBody(Exception):
    """A request body that will not be read, and the answer it gets."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


def make_key():
    return secrets.token_hex(KEY_BYTES)


def keys_match(supplied, expected):
    """Constant-time comparison of two keys, for any str at all.

    Constant time is cheap here and the alternative is a habit: `==` on a
    secret returns as soon as two bytes differ, and this server answers on
    loopback where scheduling noise is at its smallest. Whether 64 hex
    characters could really be walked out of it over HTTP is not the point --
    the point is that nobody downstream has to work out whether it could.

    hmac.compare_digest refuses non-ASCII str with TypeError, and the value
    arrives from a query string, so both sides are encoded to bytes first. A
    key of "café" must be a refusal, not a traceback out of do_GET -- that
    would be a crash reachable with no credential whatsoever.
    """
    if not isinstance(supplied, str) or not isinstance(expected, str):
        return False
    return hmac.compare_digest(
        supplied.encode("utf-8", "replace"), expected.encode("utf-8", "replace")
    )


def target_parts(target):
    """A request target as (path, query), or ("", "") if it is not one.

    Total by construction, and that is the whole reason it exists. urlsplit
    raises ValueError("Invalid IPv6 URL") on an unbalanced "[" or "]" in an
    authority, and a request target reaches self.path verbatim: CPython
    rewrites a leading "//" to "/", but an ABSOLUTE-form target -- which
    RFC 9112 s3.2.2 says a server has to accept on any request -- is not
    rewritten and arrives intact. `GET http://[::1/ HTTP/1.0` therefore
    raised out of key extraction, which runs in front of the auth check: no
    response at all, on every method, to a caller holding no credential, and
    one line on the agent's terminal per attempt at whatever rate they liked.

    Anything that will not parse yields no path and no query, which is no
    key, which is the same 403 a typo gets. That is the honest answer: an
    unparseable target is not a request for anything this server has.
    """
    try:
        parts = urlsplit(target)
    except ValueError:
        return "", ""
    return parts.path, parts.query


def query_value(target, name):
    """The first value a request target offers for `name`, or "".

    Total, like target_parts underneath it: a target that will not parse
    offers nothing, which is the same as a parameter that is not there.
    """
    values = parse_qs(target_parts(target)[1], keep_blank_values=True).get(name, [])
    return values[0] if values else ""


def _reason(exc):
    """An exception as a phrase for the browser, with no path in it.

    The person at the browser is not always the person who started the
    session, and where the agent keeps its files is not theirs to learn. The
    file's own name is said separately by the caller, which is the part that
    is actually useful.
    """
    if isinstance(exc, OSError):
        return describe_os_error(exc)
    return str(exc)


def require_loopback(host):
    """Refuse any bind address that is not the loopback interface.

    The default argument is not the guarantee: a one-character edit turns it
    into "" and puts the brief, and a URL carrying the session key, on every
    interface the machine has. Checked here, before the socket exists, so a
    refusal never leaves a port open behind it.
    """
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is None or not address.is_loopback:
            raise ValueError(
                "the craft UI serves loopback only, so it cannot bind {!r}; "
                "use 127.0.0.1, ::1 or localhost".format(host)
            )


class _RequestReader(io.RawIOBase):
    """The connection, read under one absolute deadline for the whole request.

    `timeout` is applied by socketserver with settimeout(), which is an IDLE
    clock and not a ceiling: every byte that arrives resets it. A client
    trickling one byte per just-under-timeout seconds therefore holds a
    thread and a descriptor for as long as it cares to -- readline(65537)
    will take 64 KiB at that rate, and the header parser another hundred
    lines after it -- which is days, from any unprivileged process on the
    machine, at a cost of one byte a minute.

    So the ceiling is an absolute deadline, and it is enforced HERE, on the
    recv, rather than around the readline that loops over recvs: arming it
    per readline would give the whole budget back to every byte, which is
    the bug again with more steps. Each read gets whichever is smaller of
    what is left of the budget and the idle clock, so the request line and
    the headers together are read inside `read_budget` seconds or the
    connection ends.

    The budget is lifted the moment the headers are parsed, because an
    honest client may legitimately read a response slowly. From there the
    idle clock alone bounds the write.

    It is armed a second time, by hand, around the one thing that reads
    after the headers: a request body. That was not needed while nothing
    here read one -- and the moment /api/draft and /api/submit did, the only
    clock left on a body was the idle one, which is the exact bug this class
    exists to fix, one layer further in.
    """

    def __init__(self, handler):
        io.RawIOBase.__init__(self)
        self._handler = handler
        self._deadline = None

    def start(self):
        """Begin one request's budget, now."""
        self._deadline = time.monotonic() + self._handler.read_budget

    def finished(self):
        """The request is read; the response is the idle clock's problem."""
        self._deadline = None
        self._handler.connection.settimeout(self._handler.timeout)

    def readable(self):
        return True

    def readinto(self, buffer):
        connection = self._handler.connection
        idle = self._handler.timeout
        if self._deadline is not None:
            left = self._deadline - time.monotonic()
            if left <= 0:
                self._handler.timed_out = True
                raise socket.timeout("the request outlived its read budget")
            connection.settimeout(left if idle is None else min(left, idle))
        try:
            return connection.recv_into(buffer)
        except socket.timeout:
            # Recorded rather than merely raised. BaseHTTPRequestHandler
            # swallows this, and handle_one_request below could only ever
            # observe a timeout on the request LINE -- so a client stalling
            # inside its headers closed the connection and left no trace at
            # all. Every read timeout is one read timeout, wherever it fell.
            self._handler.timed_out = True
            raise


class _Handler(BaseHTTPRequestHandler):
    server_version = "craftui"
    sys_version = ""  # no free interpreter version for anything scanning ports

    # The IDLE clock, and only that: socketserver hands it to settimeout(),
    # so it bounds the gap between two bytes and never a whole request. It is
    # what ends a connection that is opened and then goes quiet -- three
    # hundred of those hold three hundred threads and descriptors, and
    # nothing here reaps them. Generous, because after the headers it is also
    # what bounds a client reading a response slowly, which is a thing an
    # honest client may do.
    timeout = 30

    # The ceiling the line above is NOT. An absolute deadline for reading one
    # whole request, enforced per recv by _RequestReader. Generous for the
    # same reason and for one more: every request this server answers is a
    # request line and a handful of headers, so thirty seconds is not a
    # budget any honest client has ever needed to notice.
    read_budget = 30

    def setup(self):
        BaseHTTPRequestHandler.setup(self)
        self.timed_out = False
        # The stdlib's rfile is a buffered reader over the socket, and its
        # every read gets the idle clock afresh. Swap in one that reads the
        # same socket under the budget above. Closing the old one releases
        # makefile's reference and nothing else; the socket belongs to
        # socketserver, which closes it in shutdown_request.
        self.rfile.close()
        self._reader = _RequestReader(self)
        size = self.rbufsize if self.rbufsize > 0 else io.DEFAULT_BUFFER_SIZE
        self.rfile = io.BufferedReader(self._reader, size)

    def parse_request(self):
        parsed = BaseHTTPRequestHandler.parse_request(self)
        # Reached whether the request parsed or not, and in both cases the
        # reading is over: a bad request is answered and the connection ends.
        self._reader.finished()
        return parsed

    def log_message(self, fmt, *args):
        pass  # the agent's terminal is not a web log

    def handle_timeout(self):
        """The client went quiet mid-request, so the connection ends.

        socketserver puts `timeout` on the socket and BaseHTTPRequestHandler
        catches the socket.timeout that follows, silences it through
        log_error and returns -- so the connection does close, but no policy
        was chosen and nothing can see that it happened. This is the policy,
        and the count is how a test says the ceiling above is real.
        """
        self.close_connection = True
        self.server.timeouts += 1

    def handle_one_request(self):
        # Two signals, because they see different halves of the same thing.
        # _RequestReader sets timed_out on any read timeout, headers
        # included, which is where the count used to be lost. raw_requestline
        # stays as the backstop it always was: it is assigned from
        # rfile.readline(), so anything that raises before the assignment --
        # and the stdlib swallows it -- leaves the request line unset.
        self.raw_requestline = None
        self.timed_out = False
        self._reader.start()
        BaseHTTPRequestHandler.handle_one_request(self)
        if self.timed_out or self.raw_requestline is None:
            self.handle_timeout()

    def _supplied_keys(self):
        """Every key this request's query string offers. Never raises.

        The query string is the only place a key may come from -- see the
        cookie paragraph in the module docstring -- and target_parts is what
        keeps a malformed target from raising in front of the gate.
        """
        query = parse_qs(target_parts(self.path)[1], keep_blank_values=True)
        return list(query.get("key", []))

    def _authed(self):
        expected = self.server.key
        for supplied in self._supplied_keys():
            if keys_match(supplied, expected):
                return True
        return False

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # The page's own URL carries the key; a cached copy of any of this is
        # a copy of the user's brief somebody did not mean to keep.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # The key is in the query string, so every outbound navigation is a
        # chance to hand it to a third party in a Referer. markdown.py already
        # puts rel="noreferrer" on brief links; this covers everything else.
        self.send_header("Referrer-Policy", "no-referrer")
        # No Set-Cookie, deliberately, and this is the only place one could
        # go. A cookie here was scoped to 127.0.0.1 as a HOST -- ports do not
        # separate cookie jars -- so any other local port could pull one
        # subresource off this server and read the key back out of the
        # response it caused. Nothing needs it: the page is one file with no
        # subresources and every fetch it makes appends ?key=.
        self.end_headers()
        # A HEAD is answered with the headers a GET would carry and none of
        # the body. protocol_version is HTTP/1.0, so a body written anyway is
        # merely discarded by the close that follows -- but it is bytes the
        # protocol says are not there, and it becomes the start of the next
        # response the day anything here speaks 1.1.
        if self.command != "HEAD":
            self.wfile.write(data)

    def _text(self, code, body):
        self._send(code, body, "text/plain; charset=utf-8")

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json; charset=utf-8")

    def do_GET(self):
        # Auth first, and identically for every URL: a caller without the key
        # learns only that something is listening. Note that touch() comes
        # after -- an anonymous caller must not be able to hold an abandoned
        # session (and the project lock under it) open for ever by polling.
        if not self._authed():
            return self._text(403, "forbidden")
        self.server.touch()
        path = target_parts(self.path)[0]
        if path == "/":
            return self._page()
        if path == "/api/round":
            return self._json(self.server.round_payload())
        if path == "/api/brief":
            return self._json(self.server.brief_payload())
        if path == "/api/draft":
            number = parse_round(query_value(self.path, "round"))
            if number is None:
                return self._json(_NO_ROUND, 400)
            return self._json(self.server.draft_payload(number))
        return self._text(404, "not found")

    def __getattr__(self, name):
        """Any do_* at all, so that "every method is gated" is true.

        Naming the six methods below was narrower than the docstring
        claimed: TRACE, CONNECT and any three letters somebody invents have
        no do_* of their own, so the stdlib answered them with a 501 from
        inside handle_one_request -- no key checked, and none of the four
        hardening headers every other response here carries. Nothing escaped
        through that (the method name is escaped, and a 501 says nothing
        about the machine), but the gap was in the one place this file says
        there is no gap, and a docstring people trust is worth more than the
        four lines it costs to make it true.

        __getattr__ runs only when ordinary lookup has already failed, so
        do_GET and the assignments below are untouched by it, and anything
        that is not a do_* -- the stdlib's own hasattr(self,
        "_headers_buffer") among them -- still gets its AttributeError.
        """
        if name.startswith("do_"):
            return self._unsupported
        raise AttributeError(name)

    def _unsupported(self):
        """Every method that is not GET: gated first, refused second.

        Left alone, the stdlib answers a method with no do_* by sending a 501
        of its own from inside handle_one_request -- before any handler runs,
        so with no key checked and none of the headers every other response
        here carries. What this server does not implement it should not
        implement differently for a caller holding the key and a caller who
        is not; __getattr__ above is what makes sure nothing reaches that
        501, whatever the method is called.

        POST and PATCH left this path in task 6 and have real handlers
        below. They keep its rule: _authed() first, before anything is read
        or touched.
        """
        if self.headers.get("Content-Length") or self.headers.get("Transfer-Encoding"):
            # Nothing here reads the body, and an unread body is the start of
            # the next request as far as the connection is concerned. Already
            # true today, since protocol_version is HTTP/1.0 and every
            # response is followed by a close; said out loud so that it stays
            # true, because task 6's handlers arrive on this same path.
            self.close_connection = True
        if not self._authed():
            return self._text(403, "forbidden")
        self.server.touch()
        return self._text(501, "not implemented")

    # Named as well as caught by __getattr__: the ones a browser is most
    # likely to try, spelled out so the refusal is visible in this file
    # rather than only inferable from __getattr__.
    do_PUT = do_DELETE = do_HEAD = do_OPTIONS = _unsupported

    # -- the write surface --------------------------------------------------
    #
    # Two endpoints, one shape. Both of them: check the key, then touch the
    # session, then route, then frame and read the body, then check its
    # shape, and only then write a file. Nothing before the key check may
    # look at the request, and nothing before the shape check may name a
    # path.

    def _body_length(self):
        """How many bytes of body to read, or a refusal to read any.

        Framing, and only framing. Two answers to "how long is it" -- a
        Content-Length beside a Transfer-Encoding, or two Content-Lengths --
        is the oldest request-smuggling primitive there is, and the way it
        does damage is that a SECOND request is found inside the first and
        runs without ever being authorised as itself. This server picks
        neither answer; it refuses the request and ends the connection.

        Transfer-Encoding is refused outright rather than implemented. The
        page this serves sends a Content-Length on every fetch, so chunked
        is not something an honest client here produces, and a decoder for
        it would be a second framing to keep correct for no caller at all.
        """
        if self.headers.get_all("Transfer-Encoding"):
            raise _BadBody(400, "this server does not accept a chunked body")
        lengths = self.headers.get_all("Content-Length") or []
        if not lengths:
            raise _BadBody(411, "a request body needs a Content-Length")
        if len(lengths) > 1:
            raise _BadBody(400, "a request body may only have one length")
        text = lengths[0].strip()
        if not _LENGTH_TEXT.match(text):
            raise _BadBody(400, "the Content-Length is not a length")
        length = int(text)
        if length > MAX_BODY_BYTES:
            raise _BadBody(413, "the request body is too large")
        return length

    def _read_body(self):
        """The body, as a JSON object, read under its own absolute deadline.

        The deadline is the point. _RequestReader.finished() lifts the read
        budget once the headers are parsed, which was right while nothing
        here read a body: what is left is the IDLE clock, and an idle clock
        is reset by every byte that arrives. A client announcing a body and
        then trickling it one byte per just-under-timeout seconds would hold
        a thread and a descriptor for days at a cost of a byte a minute.

        A body that stops short of its Content-Length is refused rather than
        parsed from what did arrive: a length that over-promises is a lie
        about framing, and half a JSON document is not a smaller one. A
        length of zero is read as zero bytes and then fails as the invalid
        JSON it is; nothing is substituted for it. Standing in b"{}" for an
        absent body means a request that carried nothing is answered as
        though it carried an empty object.
        """
        length = self._body_length()
        self._reader.start()
        try:
            raw = self.rfile.read(length)
        except OSError:
            raise _BadBody(408, "the request body did not arrive")
        finally:
            self._reader.finished()
        if raw is None or len(raw) != length:
            raise _BadBody(400, "the request body was shorter than its length")
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise _BadBody(400, "the request body is not valid JSON")
        except RecursionError:
            # Not a ValueError, so the arm above never saw this one. The
            # decoder gives up somewhere past 980 levels of nesting --
            # measured: 980 answered, 985 did not -- and the RecursionError
            # left the handler with no response at all, on a body any caller
            # holding the key can send. MAX_BODY_DEPTH does NOT close this:
            # it is checked below, on a body that has already been decoded,
            # so the decoder always runs first. A limit and a guard are not
            # the same thing, and this arm is the guard.
            raise _BadBody(400, "the request body nests too deeply to read")
        if not isinstance(body, dict):
            raise _BadBody(400, "the request body must be a JSON object")
        refusal = body_refusal(body)
        if refusal is not None:
            # Refused here, before a path is named and before a temp file
            # exists, rather than discovered by the writer. A body this
            # server accepts is a body it can store.
            raise _BadBody(400, refusal)
        return body

    def _write_request(self, endpoint):
        """Everything both write endpoints do before they write anything.

        Returns (round, answers, body), or None once it has answered.

        Auth FIRST -- before touch(), before the path is looked at, before a
        byte of body is read. The stdlib answers a method with no do_* using
        a 501 of its own from inside handle_one_request, so nothing upstream
        has authenticated a PATCH or a POST: each of these is its own front
        door. Task 5 shipped touch() ahead of the key check on do_GET and it
        was caught in review -- an anonymous caller could otherwise hold an
        abandoned session, and the project lock under it, open for as long
        as it cared to keep polling. The same reasoning applies here with
        more at stake, since these two write files.
        """
        # This connection carried a body and will not be reused, whatever
        # happens below. Already true today -- protocol_version is HTTP/1.0,
        # so the stdlib closes after every response -- but what makes a
        # mis-framed body dangerous is a second request read off the same
        # connection, and that must not rest on a class attribute in another
        # file staying what it is.
        self.close_connection = True
        if not self._authed():
            self._text(403, "forbidden")
            return None
        self.server.touch()
        if target_parts(self.path)[0] != endpoint:
            self._text(404, "not found")
            return None
        try:
            body = self._read_body()
        except _BadBody as bad:
            self._json({"ok": False, "error": bad.message}, bad.code)
            return None
        number = parse_round(body.get("round"))
        if number is None:
            self._json(_NO_ROUND, 400)
            return None
        answers = body.get("answers")
        if answers is None:
            answers = {}  # nothing typed yet is a legitimate thing to save
        if not isinstance(answers, dict):
            self._json({"ok": False, "error": "answers must be a JSON object"}, 400)
            return None
        return number, answers, body

    def _store(self, path, payload):
        """Write one of the agent's files, or say which one could not be.

        Letting the OSError out -- a full disk, a .craft/ that stopped being
        a directory, a project that went read-only -- sends no response at
        all. The browser sees a reset connection, and the person at it has
        no reason to think the answers they just sent were not saved. The
        file is named; where it lives is not.

        UnicodeEncodeError and RecursionError are the writer's own two
        failures and neither is an OSError, so both escaped that guard and
        produced exactly the silence the paragraph above is about.
        body_refusal now refuses both shapes at the door, which should mean
        nothing ever reaches these arms -- but "should mean" is the reason
        they are here. A limit in front of a call is not a guard around it.

        The gate around it is the shutdown drain. This is the only place
        this server writes anything, so it is the only place that has to
        claim a slot before it starts and give it back when it ends --
        whether it ended by writing or by failing, which is why end_write is
        in a finally rather than after the call.

        The slot goes back BEFORE the failure is reported, so that no
        response this server sends is ever observed while the handler that
        sent it still holds a write slot. The write has already failed by
        then; there is nothing left on the disk path for a drain to wait
        for, and a caller that can see the 500 can rely on the count.
        """
        if not self.server.begin_write():
            self._json({"ok": False, "error": SHUTTING_DOWN}, 503)
            return False
        failure = None
        try:
            write_json_atomic(path, payload)
        except (UnicodeEncodeError, RecursionError) as exc:
            # The writer's own two failures, and neither is an OSError.
            failure = exc
        except OSError as exc:
            # A full disk, a .craft/ that stopped being a directory, a
            # project that went read-only.
            failure = exc
        finally:
            self.server.end_write()
        if failure is not None:
            self._json(
                {
                    "ok": False,
                    "error": "{} could not be written: {}".format(
                        path.name, _reason(failure)
                    ),
                },
                500,
            )
            return False
        return True

    def do_PATCH(self):
        """Autosave. Fires on every keystroke and every click.

        It is crash insurance and nothing else: what it writes is never what
        the agent reads as an answer. That is why Send carries the whole
        answer set in its own body rather than promoting this file -- a
        draft that is stale when Send arrives can then never become the
        submitted round.

        Two of these overlap as a matter of course rather than as an edge
        case: autosave fires per keystroke, protocol_version is HTTP/1.0 so
        every one of them is its own connection, and ThreadingHTTPServer
        runs them in parallel. Measured, `hello world` typed once left `hel`
        on disk with two saves acknowledged 200 -- an older keystroke landing
        on top of a newer one, both told they had won.

        `seq` is the client saying which keystroke this is. A PATCH carrying
        one lower than a seq already written is ignored, and ignored with a
        success status: the newer draft is on disk, which is what the user
        wanted, and the client did nothing wrong. A PATCH carrying no seq at
        all keeps the last-writer-wins behaviour this had before, so nothing
        breaks in the window before a client sends one.

        The lock is held across the WRITE and not merely across the
        comparison. Two PATCHes can pass an ordering check in the right
        order and still reach os.replace in the wrong one, which is the same
        bug with a smaller window. The 500 _store may send from inside the
        lock is eighty bytes to a loopback socket; splitting the write from
        its own error message to avoid that would cost more than it buys.
        """
        parsed = self._write_request("/api/draft")
        if parsed is None:
            return
        number, answers, body = parsed
        seq = body.get("seq")
        if seq is not None and (isinstance(seq, bool) or not isinstance(seq, int)):
            # bool is an int in Python, so True would order as seq 1. Any
            # other spelling -- a float, a digit string -- is a client that
            # believes it is sequencing and is not, which is worse than a
            # client that does not try: it would be compared as unordered
            # and silently keep the bug this exists to fix.
            return self._json({"ok": False, "error": "seq must be a whole number"}, 400)
        payload = {"round": number, "answers": answers}
        if seq is not None:
            # Only when one was carried, so a client that does not sequence
            # writes the same two-key file it has always written.
            payload["seq"] = seq
        path = self.server.session.draft_path(number)
        written = False
        with self.server.draft_lock:
            superseded = not self.server.draft_seq_is_current(number, seq)
            if not superseded:
                written = self._store(path, payload)
                if written:
                    # Recorded only once it is actually on disk. A write that
                    # failed must not make the next one look out of date.
                    self.server.record_draft_seq(number, seq)
        if superseded:
            return self._json({"ok": True, "stale": True})
        if not written:
            return  # _store has already said which file, and why
        return self._json({"ok": True})

    def do_POST(self):
        """Send to the agent. This is the product.

        What lands here is what the agent folds into CRAFT.md, and four
        answer states have to survive apart: answered, delegated ("you
        decide" -- record it and never ask again), skipped ("ask me again")
        and absent, which means skipped. So the answers are stored exactly
        as they arrived. Normalising them here, or dropping a key this file
        does not recognise, is how a decision the user handed over becomes
        one they get nagged about again next round.
        """
        parsed = self._write_request("/api/submit")
        if parsed is None:
            return
        number, answers, body = parsed
        finished = body.get("finished")
        if finished is None:
            finished = False
        if not isinstance(finished, bool):
            # bool("false") is True. Finish ends the session, so it is
            # carried as a boolean or it is not carried at all.
            return self._json(
                {"ok": False, "error": "finished must be true or false"}, 400
            )
        payload = {
            "round": number,
            # UTC, said out loud with the Z. gmtime, not localtime: a stamp
            # that carries a Z and a local clock is worse than no stamp.
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "finished": finished,
            "answers": answers,
        }
        if not self._store(self.server.session.answers_path(number), payload):
            return
        return self._json({"ok": True, "finished": finished})

    def _page(self):
        try:
            body = APP_HTML.read_bytes()
        except OSError:
            # Letting this raise sends no response at all -- the browser sees
            # a reset connection -- and prints the absolute path in a
            # traceback across the agent's terminal.
            return self._text(500, "the craft UI page could not be read")
        return self._send(200, body, "text/html; charset=utf-8")


class CraftServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, session, key, host="127.0.0.1", port=0, idle_timeout_s=14400):
        require_loopback(host)
        if ":" in host:
            self.address_family = socket.AF_INET6
        ThreadingHTTPServer.__init__(self, (host, port), _Handler)
        self.session = session
        self.key = key
        self.idle_timeout_s = idle_timeout_s
        self._last = time.monotonic()
        # What has gone wrong and how often. A count is the whole of the
        # record, because nothing here prints a traceback -- see handle_error.
        self.disconnects = 0
        self.handler_errors = 0
        self.timeouts = 0
        # The highest draft seq written per round, and the lock that makes
        # the comparison and the write it guards one indivisible step. See
        # _Handler.do_PATCH.
        self.draft_lock = threading.Lock()
        self._draft_seq = {}
        # The write gate. See begin_write.
        self._write_cond = threading.Condition()
        self._writes_in_flight = 0
        self._writes_closed = False
        self.refused_writes = 0
        # Before the first request, and before this process has written a
        # byte of its own, so nothing in flight here can be swept.
        self.swept = self.sweep_stale_temp_files()

    # ----------------------------------------------------------- write gate
    #
    # daemon_threads is True, so server_close() joins nothing. A handler that
    # is inside write_json_atomic when the server stops keeps running, and can
    # reach os.replace after the process has released the project lock and
    # after another session has legitimately acquired it. Reproduced: session
    # one's answers landing in the project while session two owned it. Two
    # live writers on one project is the single thing the lock exists to
    # prevent, and CRAFT.md is rewritten whole every round, so the loser's
    # whole round goes.
    #
    # daemon_threads stays True: a wedged reader must not be able to hold the
    # process open forever, and joining every handler thread is exactly that.
    # What is bounded instead is the narrow thing that matters -- the window
    # in which a write is on the disk path -- so the shutdown can shut the
    # gate, wait for the writes already inside it, and only then let go.
    #
    # _store is the only place this server writes anything, which is what
    # makes a gate of two calls sufficient rather than hopeful.

    def begin_write(self):
        """Claim a write slot. False means the session is shutting down.

        Checking the flag and taking the slot are one step under one lock:
        split them and a write can pass the check an instant before the gate
        shuts and start after the drain has already counted the slots.
        """
        with self._write_cond:
            if self._writes_closed:
                self.refused_writes += 1
                return False
            self._writes_in_flight += 1
            return True

    def end_write(self):
        """Give a slot back. Must run whether the write worked or not."""
        with self._write_cond:
            self._writes_in_flight -= 1
            if self._writes_in_flight <= 0:
                self._write_cond.notify_all()

    def close_writes(self):
        """Refuse every write from now on. Reads carry on being served.

        Idempotent, and safe from a signal handler's thread: it takes a lock
        no request-serving path holds for longer than one dict update.
        """
        with self._write_cond:
            self._writes_closed = True
            self._write_cond.notify_all()

    def drain_writes(self, timeout):
        """Shut the gate, then wait for the writes already through it.

        True when nothing is left in flight; False when `timeout` seconds
        passed with a write still going. Bounded on purpose: a write wedged
        on an unresponsive filesystem must not be able to hold a session's
        exit open for ever, and the caller decides what to say about it.
        """
        self.close_writes()
        try:
            timeout = max(0.0, float(timeout))
        except (TypeError, ValueError):
            timeout = 0.0
        deadline = time.monotonic() + timeout
        with self._write_cond:
            while self._writes_in_flight > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._write_cond.wait(remaining)
            return True

    @property
    def writes_in_flight(self):
        with self._write_cond:
            return self._writes_in_flight

    @property
    def writes_closed(self):
        with self._write_cond:
            return self._writes_closed

    def sweep_stale_temp_files(self):
        """Remove the .tmp- files a killed session left in .craft/.

        write_json_atomic writes through mkstemp and unlinks the temp file in
        an except clause, which process death does not run: not SIGKILL, not
        SIGTERM, not SIGHUP, and not the Ctrl-C that raises KeyboardInterrupt
        on the main thread while writer threads are elsewhere. Measured,
        twelve SIGKILLs during writes left forty-four of them behind.
        Nothing else ever removes one, session.ROUND_RE does not match one,
        and each holds whatever the user had typed when the session died --
        so the leak is both unbounded and made of their answers.

        Only that name and only that directory: TMP_GLOB matches nothing the
        tool itself writes, and the glob is anchored to .craft/ rather than
        built from anything a request said.

        A temp file another process is in the middle of using looks exactly
        like an orphan, so this does not try to tell them apart -- see
        TMP_GRACE_S. It also never follows or removes a symlink: mkstemp
        cannot produce one, so anything wearing this name and pointing
        somewhere else is not ours to delete.

        Never raises, and returns how many it removed. A .craft/ that cannot
        be listed, or a file another process unlinked first, must not be the
        reason a session refuses to start.
        """
        cutoff = time.time() - TMP_GRACE_S
        try:
            candidates = list(self.session.craft_dir.glob(TMP_GLOB))
        except OSError:
            return 0
        removed = 0
        for path in candidates:
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                if path.stat().st_mtime > cutoff:
                    continue
                path.unlink()
            except OSError:
                continue  # gone already, or not ours to remove
            removed += 1
        return removed

    def draft_seq_is_current(self, number, seq):
        """Whether a PATCH carrying this seq is not already out of date.

        A seq of None is always current: a client that does not sequence
        keeps the last-writer-wins behaviour it had. Equal is current too --
        a retry of one keystroke is not an older keystroke.

        Call with draft_lock held. It reads the dict record_draft_seq
        writes, and the pair is only atomic together.
        """
        if seq is None:
            return True
        highest = self._draft_seq.get(number)
        return highest is None or seq >= highest

    def draft_seq(self, number):
        """The highest seq written for a round, or None. Per process.

        Deliberately not seeded from the draft file on disk. A restart drops
        every request that was in flight across it, so there is no older
        PATCH left to arrive late; the browser's own counter keeps rising
        and the first PATCH after a restart sets the mark again.
        """
        return self._draft_seq.get(number)

    def record_draft_seq(self, number, seq):
        """Remember a seq that has actually reached the disk.

        Call with draft_lock held, and only after the write succeeded.
        """
        if seq is None:
            return
        highest = self._draft_seq.get(number)
        if highest is None or seq > highest:
            self._draft_seq[number] = seq

    def handle_error(self, request, client_address):
        """A client hanging up is not news. Anything else is, quietly.

        socketserver's own handle_error prints a whole traceback to stderr,
        absolute paths and all, and an ordinary browser produces one every
        time a page is reloaded or navigated away from mid-response. That is
        the invariant every response here keeps, spilled onto the agent's
        terminal by a reload -- and reachable with a perfectly valid key.

        Not a blanket pass, though: a genuine bug in a handler still has to
        be findable, so it is counted and one terse line names the exception
        TYPE. Not its message and not the request line: an OSError's message
        carries the path it failed on, and the request line carries the
        session key. A type and a count are enough to know a bug is there and
        to go and reproduce it, and neither of them is about this machine.
        """
        exc = sys.exc_info()[1]
        # ConnectionError is the whole family: broken pipe, reset by peer,
        # aborted. socket.timeout is separate, and is TimeoutError from 3.10.
        if isinstance(exc, (ConnectionError, socket.timeout)):
            self.disconnects += 1
            return
        self.handler_errors += 1
        print(
            "craft ui: a request failed with {}".format(type(exc).__name__),
            file=sys.stderr,
        )

    @property
    def port(self):
        return self.server_address[1]

    def touch(self):
        self._last = time.monotonic()

    def idle_seconds(self):
        return time.monotonic() - self._last

    def round_payload(self):
        """The current round, or why it cannot be served.

        Never raises, and that now includes finding out WHICH round it is.
        current_round() sat outside the guard while raising like everything
        else that touches a filesystem: it calls is_dir() and then
        iterdir(), and a .craft/ that passes the first and refuses the
        second -- mode 000, or any of the ways a directory can stop being
        readable between two syscalls -- took the request down with it. The
        browser got a reset connection, which is exactly the failure _page
        is already guarded against.

        The agent writes these files while the browser is polling them, and
        a half-written, hand-edited or unreadable round has to come back as
        a message on the page.
        """
        try:
            number = self.session.current_round()
        except OSError as exc:
            # Named by the directory, not by where it is: the same rule the
            # file-level messages below keep.
            return {
                "ok": False,
                "error": "{} could not be read: {}".format(
                    self.session.craft_dir.name, _reason(exc)
                ),
            }
        if number is None:
            return {"ok": True, "round": None}
        name = self.session.questions_path(number).name
        try:
            obj = read_json(self.session.questions_path(number))
        except ValueError as exc:  # malformed JSON, or bytes that are not UTF-8
            return {"ok": False, "error": "{} is not valid JSON: {}".format(name, exc)}
        except OSError as exc:
            return {
                "ok": False,
                "error": "{} could not be read: {}".format(name, _reason(exc)),
            }
        errors = schema.validate_round(obj, number)
        if errors:
            return {"ok": False, "error": "{} is invalid".format(name), "details": errors}
        return {"ok": True, "round": obj}

    def draft_payload(self, number):
        """A saved draft, or an empty one, and never a raised exception.

        A draft that is not there is the ordinary case -- nothing has been
        typed yet -- and comes back empty with no error at all, because a
        first load must not look like a failure.

        A draft that IS there and cannot be read is a different thing, and
        the difference is the user's. Answering that with a silent empty
        form invites them to retype work that is sitting on the disk, so the
        form still opens (empty is the only shape it can open in) and the
        file is named beside it. Named, not located: the person at the
        browser is not always the person who started the session.
        """
        path = self.session.draft_path(number)
        empty = {"round": number, "answers": {}}
        try:
            obj = read_json(path)
        except FileNotFoundError:
            return empty
        except ValueError as exc:  # malformed JSON, or bytes that are not UTF-8
            empty["error"] = "{} is not valid JSON: {}".format(path.name, exc)
            return empty
        except OSError as exc:
            empty["error"] = "{} could not be read: {}".format(path.name, _reason(exc))
            return empty
        answers = obj.get("answers") if isinstance(obj, dict) else None
        if not isinstance(answers, dict):
            # Valid JSON of the wrong shape: hand-edited, half-written, or
            # from a version of this tool that did not exist yet. The page
            # gets the shape it was promised either way.
            empty["error"] = "{} does not hold a set of answers".format(path.name)
            return empty
        return {"round": number, "answers": answers}

    def brief_payload(self):
        """CRAFT.md as HTML. Missing is empty; unreadable is said out loud.

        Session.read_brief absorbs a missing file and nothing else, so a
        CRAFT.md that is a directory, or that carries a byte that is not
        UTF-8, would otherwise take the request down with it.
        """
        try:
            text = self.session.read_brief()
        except (OSError, ValueError) as exc:
            return {
                "html": "",
                "error": "CRAFT.md could not be read: {}".format(_reason(exc)),
            }
        return {"html": markdown.render(text)}

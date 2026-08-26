"""The HTTP surface: who gets in, what comes out, and what never happens.

Every test here is written against a mutant. The session key is the only thing
standing between a page on the machine and the user's brief, so the auth tests
are adversarial by construction: a prefix of the key, a superstring of it, a
cookie whose NAME merely ends in the right letters, a key that is not ASCII.
Each of those is a one-line change to server.py away from being accepted.

The cookie tests read inverted, and that is the point of them. There was a
session cookie; it was a whole credential, and cookies are scoped to a host
and not to a port (RFC 6265 s8.5), so any other http://127.0.0.1:<port> page
could pull one subresource off this server and read the key back. The cookie
is gone. What is left in its place is the set of tests that say so -- a
request carrying nothing but a cookie is refused, and no response hands one
out -- because a deleted feature with deleted tests is a feature that comes
back.
"""
import contextlib
import datetime
import functools
import io
import json
import os
import random
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

import schema
import server as server_module
from server import APP_HTML, CraftServer, make_key
from session import Session, read_json, write_json_atomic

# The name the session cookie used to have, and the name anything else on
# 127.0.0.1 would plant if it wanted to be believed. Defined here rather than
# imported: server.py must no longer have it, and KeyTest asserts that.
COOKIE = "craftkey"

VALID_ROUND = {
    "round": 1,
    "questions": [
        {"id": "Q-1", "importance": "REQUIRED", "title": "Auth?", "type": "text"}
    ],
}


class ServerTestCase(unittest.TestCase):
    """A live server on an ephemeral port, torn down whatever happens.

    Cleanups rather than tearDown: a failure part-way through setUp still
    releases the port and joins the thread, and the join is asserted, so a
    leaked serving thread fails THIS test instead of flaking somebody else's
    an hour later.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.session = Session(self._tmp.name)
        self.session.ensure_dirs()
        self.key = make_key()
        self.server = self.start_server()
        self.base = "http://127.0.0.1:{}".format(self.server.port)

    def start_server(self, **kw):
        server = CraftServer(self.session, self.key, port=0, **kw)
        self.addCleanup(server.server_close)
        # A short poll interval, because shutdown() waits for the current one
        # and the default 0.5 s is paid by every teardown in this file. Not a
        # sleep and not a race: serve_forever polls, and shutdown() returns
        # only once the loop has actually stopped.
        serve = functools.partial(server.serve_forever, poll_interval=0.01)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        # LIFO: shutdown, then join, then server_close.
        self.addCleanup(self._join, thread)
        self.addCleanup(server.shutdown)
        return server

    def _join(self, thread):
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "the serving thread outlived shutdown()")

    def url(self, path, key=True):
        url = "{}{}".format(self.base, path)
        if key is True:
            key = self.key
        if isinstance(key, str):
            sep = "&" if "?" in path else "?"
            url += sep + "key=" + urllib.parse.quote(key, safe="")
        return url

    def request(self, path, key=True, cookie=None, **kw):
        request = urllib.request.Request(self.url(path, key), **kw)
        if cookie is True:
            cookie = "{}={}".format(COOKIE, self.key)
        if isinstance(cookie, str):
            request.add_header("Cookie", cookie)
        return request

    def get(self, path, **kw):
        return urllib.request.urlopen(self.request(path, **kw), timeout=5)

    def get_json(self, path, **kw):
        response = self.get(path, **kw)
        self.assertIn("application/json", response.headers.get("Content-Type", ""))
        return json.loads(response.read().decode("utf-8"))

    def refused(self, path, **kw):
        """The HTTPError from a request that must not be served."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get(path, **kw)
        return caught.exception

    def raw_request(self, method, path, key=True):
        """One HTTP/1.1 request as bytes, for what urllib will not do.

        urllib hides the two things the tests below are about: the bytes that
        followed a HEAD's headers, and a connection that is abandoned rather
        than finished.
        """
        target = self.url(path, key)[len(self.base):]
        return "{} {} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".format(
            method, target
        ).encode("utf-8")

    def read_to_close(self, client):
        """Everything the server sends before it closes the connection."""
        client.settimeout(5)
        received = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                return received
            received += chunk

    def raw_connection(self):
        """A socket to the server, closed however the test ends."""
        client = socket.create_connection(("127.0.0.1", self.server.port), timeout=5)
        self.addCleanup(client.close)
        return client

    def wait_until(self, predicate, timeout=5):
        """Poll until something another thread did becomes visible.

        Not a sleep: a passing run leaves the moment the condition holds and
        the deadline is only how a failing one ends. Returns whether it held.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def assertNamesNoPath(self, text, msg=None):
        """Nothing in a response may say where anything on this machine is.

        Three assertions rather than one because they fail differently and a
        failure should name which leak it is: the session's own directory,
        the directory the tool itself lives in, and then any absolute path at
        all -- which the last catches, since every name a message is allowed
        to carry (round-001.questions.json, CRAFT.md) has no slash in it.
        """
        self.assertNotIn(self._tmp.name, text, msg)
        self.assertNotIn(str(APP_HTML), text, msg)
        self.assertNotIn("/", text, msg)


class AuthTest(ServerTestCase):
    def test_no_key_at_all_is_forbidden(self):
        self.assertEqual(self.refused("/", key=False).code, 403)

    def test_a_wrong_key_is_forbidden(self):
        self.assertEqual(self.refused("/", key="deadbeef").code, 403)

    def test_a_prefix_of_the_key_is_forbidden(self):
        """Kills startswith, a truncated compare, and `supplied in key`."""
        self.assertEqual(self.refused("/", key=self.key[:-1]).code, 403)

    def test_a_superstring_of_the_key_is_forbidden(self):
        """Kills `key in supplied` and any substring test in that direction."""
        self.assertEqual(self.refused("/", key=self.key + "x").code, 403)

    def test_a_key_differing_only_in_the_last_character_is_forbidden(self):
        """Kills a compare that stops early, however it got there."""
        last = "0" if self.key[-1] != "0" else "1"
        self.assertEqual(self.refused("/", key=self.key[:-1] + last).code, 403)

    def test_a_non_ascii_key_is_forbidden_and_does_not_crash_the_server(self):
        """secrets.compare_digest raises TypeError on non-ASCII str. A crash
        here would be a 500-shaped hole reachable with no credential at all."""
        self.assertEqual(self.refused("/", key="café☃").code, 403)
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_a_key_with_a_null_byte_is_forbidden(self):
        self.assertEqual(self.refused("/", key=self.key + "\x00").code, 403)

    def test_the_key_in_the_query_string_works(self):
        self.assertEqual(self.get("/").status, 200)

    def test_an_empty_key_parameter_is_forbidden(self):
        """parse_qs drops blank values unless asked not to; an empty key must
        be a refusal either way, never a match against a missing value."""
        self.assertEqual(self.refused("/?key=", key=False).code, 403)

    def test_the_cookie_alone_is_forbidden(self):
        """The inversion of "the cookie alone works", and the regression test
        for the whole finding. A cookie set by this server was scoped to
        127.0.0.1 as a HOST -- ports do not separate cookie jars -- so a page
        on any other local port could make the browser fetch one subresource
        from here and then read the key back. The stolen cookie was a
        complete credential: GET /api/brief with no key in the URL was 200.
        Now the URL is the only thing that authenticates."""
        self.assertEqual(self.refused("/", key=False, cookie=True).code, 403)
        for path in ("/api/round", "/api/brief"):
            self.assertEqual(self.refused(path, key=False, cookie=True).code, 403, path)

    def test_the_cookie_is_forbidden_beside_other_cookies(self):
        header = "ga=1; {}={}; theme=dark".format(COOKIE, self.key)
        self.assertEqual(self.refused("/", key=False, cookie=header).code, 403)

    def test_a_cookie_whose_name_merely_ends_in_the_right_letters_is_forbidden(self):
        """Was about exact name matching; now about there being no matching
        at all. Either way a different local server on 127.0.0.1 can set a
        cookie for the whole host, so neither this nor the real name gets in."""
        header = "x{}={}".format(COOKIE, self.key)
        self.assertEqual(self.refused("/", key=False, cookie=header).code, 403)

    def test_a_cookie_name_in_the_wrong_case_is_forbidden(self):
        """Case-folding a cookie name used to widen the set of cookies another
        127.0.0.1 listener could plant. Nothing here reads a cookie now, so
        every casing is refused for the same reason the exact one is."""
        for name in ("CraftKey", "CRAFTKEY", COOKIE.capitalize()):
            header = "{}={}".format(name, self.key)
            self.assertEqual(self.refused("/", key=False, cookie=header).code, 403, header)

    def test_a_cookie_value_with_trailing_junk_is_forbidden(self):
        header = "{}={}junk".format(COOKIE, self.key)
        self.assertEqual(self.refused("/", key=False, cookie=header).code, 403)

    def test_a_padded_cookie_value_is_not_the_key(self):
        # Leading, not trailing: the header parser strips a trailing space off
        # the whole header value before this code ever sees it.
        for header in ("{}= {}", "{}=\t{}", "{}= {} ; x=1"):
            header = header.format(COOKIE, self.key)
            self.assertEqual(self.refused("/", key=False, cookie=header).code, 403, header)

    def test_a_cookie_can_neither_grant_a_session_nor_take_one_away(self):
        """The inversion of "a wrong cookie does not shadow a right one". A
        stray craftkey= from another localhost app used to be a possible
        lockout, and the right one used to be a way in. Now the Cookie header
        decides nothing in either direction: the URL's key alone is read."""
        for header in ("{0}=junk; {0}={1}", "{0}={1}; {0}=junk", "{0}=junk"):
            header = header.format(COOKIE, self.key)
            # With the key in the URL: served, whatever the cookies say.
            self.assertEqual(self.get("/", cookie=header).status, 200, header)
            # Without it: refused, whatever the cookies say.
            self.assertEqual(self.refused("/", key=False, cookie=header).code, 403, header)

    def test_a_malformed_cookie_header_is_a_refusal_not_a_crash(self):
        self.assertEqual(self.refused("/", key=False, cookie="=;;;=x=").code, 403)
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_every_endpoint_is_gated_not_just_the_page(self):
        """Every URL this server answers, listed one by one. A list that
        falls behind the routing table is how an endpoint ships ungated:
        /api/draft was added in task 6 and a mutation run caught that this
        list had not been."""
        for path in ("/", "/api/round", "/api/brief", "/api/draft?round=1"):
            self.assertEqual(self.refused(path, key=False).code, 403, path)

    def test_an_unauthorised_caller_cannot_tell_a_real_path_from_a_fake_one(self):
        """Auth runs before routing, so /api/round and /nope look identical to
        somebody without the key. Otherwise the 404 is a filesystem probe."""
        fake = self.refused("/nope", key=False)
        for path in ("/api/round", "/api/draft?round=1"):
            real = self.refused(path, key=False)
            self.assertEqual((real.code, fake.code), (403, 403), path)
            self.assertEqual(real.read(), fake.read(), path)
            fake = self.refused("/nope", key=False)

    def test_a_refusal_never_echoes_the_key(self):
        error = self.refused("/", key="deadbeef")
        self.assertNotIn(self.key, error.read().decode("utf-8", "replace"))
        self.assertNotIn(self.key, str(error.headers))

    def test_a_refusal_does_not_hand_out_the_cookie(self):
        self.assertIsNone(self.refused("/", key=False).headers.get("Set-Cookie"))

    def test_an_unauthorised_request_cannot_hold_the_session_open(self):
        """The idle clock is what eventually ends an abandoned session. If an
        anonymous caller resets it, any process on the machine can keep the
        server -- and the project lock it holds -- alive indefinitely."""
        self.server._last -= 100
        before = self.server.idle_seconds()
        self.refused("/", key=False)
        self.assertGreaterEqual(self.server.idle_seconds(), before)


class RequestTargetTest(ServerTestCase):
    """Request targets, including the ones urlsplit refuses to parse.

    Key extraction reads self.path, and self.path is whatever the client put
    on the request line. urlsplit raises ValueError("Invalid IPv6 URL") on an
    unbalanced "[" or "]" in an authority, and that raise landed in FRONT of
    the auth check: no response at all, on any method, to a caller with no
    credential, plus a line on the agent's terminal per attempt.
    """

    def raw_exchange(self, target, method="GET"):
        """One request built from a raw target, and everything sent back."""
        client = self.raw_connection()
        line = "{} {} HTTP/1.0\r\n\r\n".format(method, target)
        client.sendall(line.encode("utf-8"))
        return self.read_to_close(client)

    def assertForbidden(self, received, msg=None):
        """A real 403 with a real body -- not silence, which is what the
        ValueError produced and what a mutant would produce again."""
        self.assertTrue(received, msg)  # zero bytes is the bug itself
        headers, blank, body = received.partition(b"\r\n\r\n")
        self.assertTrue(blank, received)
        self.assertIn(b"403", headers.splitlines()[0], msg)
        self.assertEqual(body, b"forbidden", msg)

    def test_an_absolute_target_with_an_unbalanced_bracket_is_a_clean_403(self):
        self.assertForbidden(self.raw_exchange("http://[::1/"))
        self.assertEqual(self.server.handler_errors, 0)
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_every_unparseable_target_shape_is_a_clean_403(self):
        for target in ("http://[::1/", "http://::1]/", "http://[::1]:x/",
                       "http://[/?key=x", "//[::1/", "http://[]]/"):
            self.assertForbidden(self.raw_exchange(target), target)
        self.assertEqual(self.server.handler_errors, 0)

    def test_no_method_can_reach_the_crash_either(self):
        """The raise was in _supplied_keys, which every method calls, so the
        denial of response was available on all of them."""
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS",
                       "TRACE", "BREW"):
            self.assertForbidden(self.raw_exchange("http://[::1/", method), method)
        # HEAD is the same path with the body suppressed, so it is checked
        # for the status line alone rather than through assertForbidden.
        received = self.raw_exchange("http://[::1/", "HEAD")
        self.assertIn(b"403", received.splitlines()[0])
        self.assertEqual(self.server.handler_errors, 0)

    def test_an_unparseable_target_cannot_hold_the_session_open(self):
        """It is refused, so it must be refused in every way a 403 is: the
        idle clock is what eventually ends an abandoned session."""
        self.server._last -= 100
        before = self.server.idle_seconds()
        self.raw_exchange("http://[::1/")
        self.assertGreaterEqual(self.server.idle_seconds(), before)

    def test_an_absolute_target_that_does_parse_is_still_served(self):
        """RFC 9112 s3.2.2 says a server accepts absolute-form on any request,
        and making the parser total must not have broken the form the fix was
        found through. The path and the query both have to survive it."""
        target = "http://127.0.0.1:{}/api/round?key={}".format(self.server.port, self.key)
        received = self.raw_exchange(target)
        headers, blank, body = received.partition(b"\r\n\r\n")
        self.assertIn(b"200", headers.splitlines()[0], received)
        self.assertIsNone(json.loads(body.decode("utf-8"))["round"])


class ResponseHeaderTest(ServerTestCase):
    """What every response carries, and the one header none of them may.

    Three tests used to assert that the session cookie was HttpOnly, SameSite
    and Path-scoped. Those three collapse into one that is strictly stronger
    than all of them together: there is no cookie. SameSite=Strict was the
    part that was doing real work, and on a developer machine "same site" is
    every other port on 127.0.0.1, which is the whole finding.
    """

    def test_the_page_hands_out_no_cookie(self):
        self.assertIsNone(self.get("/").headers.get("Set-Cookie"))

    def test_no_response_at_all_carries_a_set_cookie(self):
        for path in ("/", "/api/round", "/api/brief"):
            self.assertIsNone(self.get(path).headers.get("Set-Cookie"), path)
        for path, kw in (("/nope", {}), ("/", {"key": False}),
                         ("/api/round", {"method": "POST", "data": b"{}"})):
            error = self.refused(path, **kw)
            self.assertIsNone(error.headers.get("Set-Cookie"), path)

    def test_responses_are_never_cached(self):
        """The page's URL carries the key. A cached copy is a leaked key."""
        for path in ("/", "/api/round", "/api/brief"):
            header = self.get(path).headers.get("Cache-Control", "")
            self.assertIn("no-store", header, path)

    def test_responses_carry_the_hardening_headers(self):
        for path in ("/", "/api/round", "/api/brief"):
            headers = self.get(path).headers
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff", path)
            self.assertEqual(headers.get("Referrer-Policy"), "no-referrer", path)

    def test_the_server_header_does_not_advertise_the_interpreter(self):
        self.assertNotIn("Python", self.get("/").headers.get("Server", ""))


class PageTest(ServerTestCase):
    def test_the_page_is_served_verbatim_as_html(self):
        response = self.get("/")
        self.assertEqual(response.read(), APP_HTML.read_bytes())
        self.assertEqual(response.headers.get("Content-Type"), "text/html; charset=utf-8")

    def test_the_page_is_self_contained(self):
        """No CDN, no remote font, no external script: the whole point of a
        local tool is that it works with the network unplugged, and a remote
        subresource would carry the key-bearing URL off the machine."""
        text = APP_HTML.read_text(encoding="utf-8").lower()
        for forbidden in ("<script src", "src=\"http", "src='http", "href=\"http",
                          "href='http", "@import", "url(http"):
            self.assertNotIn(forbidden, text)

    def test_an_unknown_path_is_404_not_500(self):
        self.assertEqual(self.refused("/nope").code, 404)

    def test_a_traversal_shaped_path_serves_nothing(self):
        for path in ("/../server.py", "/api/round/../../server.py", "/./server.py",
                     "/app.html", "/session.py"):
            error = self.refused(path)
            self.assertEqual(error.code, 404, path)
            self.assertNotIn("make_key", error.read().decode("utf-8", "replace"))

    def test_a_404_body_names_no_path(self):
        body = self.refused("/nope").read().decode("utf-8", "replace")
        self.assertNotIn(self._tmp.name, body)
        self.assertNotIn(str(APP_HTML), body)

    def test_a_403_body_names_no_path(self):
        """The 404 has this test above; the 403 is the one an UNAUTHENTICATED
        caller gets, and comparing two 403 bodies to each other -- which is
        what the auth test does -- cannot see a leak present in both."""
        body = self.refused("/", key=False).read().decode("utf-8", "replace")
        self.assertNamesNoPath(body)

    def test_a_missing_page_file_is_a_clean_500_and_the_server_survives(self):
        """A read that raises out of do_GET gets no response at all -- the
        client sees a reset connection and the traceback prints the absolute
        path into the agent's terminal."""
        server_module.APP_HTML = APP_HTML.with_name("does-not-exist.html")
        self.addCleanup(setattr, server_module, "APP_HTML", APP_HTML)
        error = self.refused("/")
        self.assertEqual(error.code, 500)
        body = error.read().decode("utf-8", "replace")
        self.assertNotIn(str(server_module.APP_HTML), body)
        self.assertNotIn("Traceback", body)
        server_module.APP_HTML = APP_HTML
        self.assertEqual(self.get("/").status, 200)

    def test_an_unreadable_page_file_is_a_clean_500_too(self):
        """Not just a MISSING one. Narrowing the guard to FileNotFoundError
        passes the test above and still takes the request down -- no
        response, a reset connection, a traceback -- when app.html is a
        directory or has no read permission. A directory, because root
        reads a mode-000 file and would skip the point."""
        page = Path(self._tmp.name) / "app.html"
        page.mkdir()
        server_module.APP_HTML = page
        self.addCleanup(setattr, server_module, "APP_HTML", APP_HTML)
        error = self.refused("/")
        self.assertEqual(error.code, 500)
        body = error.read().decode("utf-8", "replace")
        self.assertNamesNoPath(body)
        self.assertNotIn("Traceback", body)
        server_module.APP_HTML = APP_HTML
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_a_write_method_aimed_at_a_read_endpoint_serves_nothing(self):
        """POST and PATCH exist now, and each answers exactly one URL. A
        handler that looked only at the METHOD would happily write a draft
        from a PATCH sent to /api/round."""
        for method in ("POST", "PATCH"):
            error = self.refused("/api/round", method=method, data=b"{}")
            self.assertEqual(error.code, 404, method)
        for method in ("PUT", "DELETE"):
            error = self.refused("/api/round", method=method, data=b"{}")
            self.assertEqual(error.code, 501, method)


class MethodTest(ServerTestCase):
    """Everything that is not a GET.

    Left to the stdlib these are answered with a 501 from inside
    handle_one_request, before any handler runs: no key checked, and none of
    the four headers every other response here carries.
    """

    OTHERS = ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

    # The ones that are still not implemented. POST and PATCH left this list
    # in task 6; every OTHER assertion in this class still covers all six,
    # because "gated first" is a property of every method and not only of the
    # unimplemented ones.
    UNIMPLEMENTED = ("PUT", "DELETE", "HEAD", "OPTIONS")

    # Methods with no do_* of their own. TRACE and CONNECT are real and in
    # RFC 9110; BREW is not, and that is the point of it -- "every method is
    # gated" has to mean the ones nobody here has heard of too.
    UNNAMED = ("TRACE", "CONNECT", "BREW", "PROPFIND", "x")

    def raw_status(self, method, target="/api/round", key=True):
        """The status line of a raw request, for methods urllib will not send.

        http.client refuses a body-less CONNECT and rewrites the target, so
        the socket is the only way to ask this server what it does with one.
        """
        client = self.raw_connection()
        if key is True:
            target = "{}?key={}".format(target, self.key)
        client.sendall("{} {} HTTP/1.0\r\n\r\n".format(method, target).encode("utf-8"))
        received = self.read_to_close(client)
        self.assertTrue(received, method)
        return received.splitlines()[0], received

    def test_a_method_with_no_handler_of_its_own_is_gated_like_the_rest(self):
        """The stdlib answers an unknown method with a 501 from inside
        handle_one_request: before any handler runs, so with no key checked
        and none of the four hardening headers. Nothing leaked through that,
        but the docstring above said every method was gated and five of them
        were not."""
        for method in self.UNNAMED:
            status, received = self.raw_status(method, key=False)
            self.assertIn(b"403", status, received)
            self.assertIn(b"X-Content-Type-Options: nosniff", received, method)
            self.assertIn(b"Referrer-Policy: no-referrer", received, method)
            self.assertIn(b"Cache-Control: no-store", received, method)
            self.assertNotIn(b"Set-Cookie", received, method)

    def test_a_method_with_no_handler_is_501_once_the_key_is_shown(self):
        """Gated first, refused second -- the same two steps every named
        method takes, so that holding the key changes nothing about what is
        implemented."""
        for method in self.UNNAMED:
            status, received = self.raw_status(method)
            self.assertIn(b"501", status, received)

    def test_gating_every_method_did_not_gate_anything_else(self):
        """__getattr__ catches do_*, and nothing else may fall into it. The
        stdlib itself asks hasattr(self, "_headers_buffer"), and a handler
        that answered yes to every attribute would break send_header."""
        handler = server_module._Handler
        instance = handler.__new__(handler)
        self.assertFalse(hasattr(instance, "_headers_buffer"))
        with self.assertRaises(AttributeError):
            instance.not_a_do_method
        self.assertEqual(self.get("/").status, 200)  # send_header still works

    def test_no_method_is_served_to_a_caller_without_the_key(self):
        for method in self.OTHERS:
            error = self.refused("/api/round", key=False, method=method)
            self.assertEqual(error.code, 403, method)

    def test_a_method_that_is_not_implemented_is_refused_even_with_the_key(self):
        for method in self.UNIMPLEMENTED:
            self.assertEqual(self.refused("/api/round", method=method).code, 501, method)

    def test_a_refused_method_carries_the_hardening_headers(self):
        for method in self.OTHERS:
            headers = self.refused("/api/round", method=method).headers
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff", method)
            self.assertEqual(headers.get("Referrer-Policy"), "no-referrer", method)
            self.assertIn("no-store", headers.get("Cache-Control", ""), method)

    def test_a_refused_method_hands_out_no_cookie(self):
        for method in self.OTHERS:
            error = self.refused("/api/round", key=False, method=method)
            self.assertIsNone(error.headers.get("Set-Cookie"), method)

    def test_an_unauthorised_method_cannot_hold_the_session_open(self):
        """Same reasoning as the GET: any process on the machine could
        otherwise keep an abandoned session, and the project lock under it,
        alive for ever by POSTing at it."""
        self.server._last -= 100
        before = self.server.idle_seconds()
        self.refused("/api/round", key=False, method="POST")
        self.assertGreaterEqual(self.server.idle_seconds(), before)

    def test_a_head_carries_the_headers_and_none_of_the_body(self):
        """A HEAD is answered with the headers a GET would carry and nothing
        after them. urllib cannot see this -- http.client knows a HEAD has no
        body and stops reading -- so the socket says it instead.

        Harmless today, because protocol_version is HTTP/1.0 and every
        response is followed by a close. It stops being harmless the moment
        anything here speaks 1.1, when a body nobody read is the start of the
        next response on the connection.
        """
        client = self.raw_connection()
        client.sendall(self.raw_request("HEAD", "/api/round"))
        received = self.read_to_close(client)
        headers, blank, body = received.partition(b"\r\n\r\n")
        self.assertTrue(blank, received)
        self.assertIn(b"501", headers)
        self.assertIn(b"Content-Type", headers)
        self.assertEqual(body, b"")


class _RoundIsADirectory(Session):
    """A session that insists round 1 exists, so that a directory sitting at
    its name reaches read_json and raises an OSError naming a path.

    current_round only counts entries is_file() accepts, and every OSError
    whose str() carries a path is either that (EISDIR, ELOOP) or exempt for
    root (EACCES). This is how the OSError arm gets exercised on every
    machine rather than only on the ones where mode 000 means something.
    """

    def current_round(self):
        return 1


class _SessionDirRefusesToBeListed(Session):
    """A session whose .craft/ is a directory right up until it is read.

    current_round() calls is_dir() and then iterdir(), and the second may
    refuse where the first did not. Root reads a mode-000 directory, so the
    real trigger below skips for root; this one raises the same OSError from
    the same call on every machine, which is what keeps the guard covered.
    """

    def current_round(self):
        raise PermissionError(13, "Permission denied", str(self.craft_dir))


class RoundTest(ServerTestCase):
    def test_an_unlistable_session_directory_reports_an_error(self):
        """round_payload says "Never raises", and current_round() sat outside
        the try while raising like everything else that touches a filesystem.
        A .craft/ at mode 000 passes is_dir() and then refuses iterdir(), and
        the browser got a reset connection -- the same failure _page is
        already guarded against."""
        self.session.craft_dir.chmod(0o000)
        self.addCleanup(self.session.craft_dir.chmod, 0o755)
        try:
            list(self.session.craft_dir.iterdir())
        except PermissionError:
            pass
        else:
            self.skipTest("this user can list a mode-000 directory; probably root")
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertIn(".craft", payload["error"])
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_an_unlistable_session_directory_names_no_path(self):
        """The root-proof half, and the one that also checks the message. An
        OSError's str() carries the path it failed on, so formatting exc
        rather than _reason(exc) puts the agent's directory on the page."""
        self.server.session = _SessionDirRefusesToBeListed(self._tmp.name)
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertIn(".craft", payload["error"])
        self.assertNamesNoPath(json.dumps(payload))
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_no_rounds_yet(self):
        payload = self.get_json("/api/round")
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["round"])

    def test_a_valid_round_is_served_whole(self):
        write_json_atomic(self.session.questions_path(1), VALID_ROUND)
        payload = self.get_json("/api/round")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["round"], VALID_ROUND)

    def test_a_new_round_supersedes_the_old_one(self):
        write_json_atomic(self.session.questions_path(1), VALID_ROUND)
        self.assertEqual(self.get_json("/api/round")["round"]["round"], 1)
        write_json_atomic(self.session.questions_path(2), dict(VALID_ROUND, round=2))
        self.assertEqual(self.get_json("/api/round")["round"]["round"], 2)

    def test_round_ten_beats_round_nine(self):
        """Highest number, not highest name: a lexical max serves round 9
        forever once the session reaches double figures."""
        for n in (9, 10):
            write_json_atomic(self.session.questions_path(n), dict(VALID_ROUND, round=n))
        self.assertEqual(self.get_json("/api/round")["round"]["round"], 10)

    def test_non_ascii_survives_the_round_trip(self):
        question = dict(VALID_ROUND["questions"][0], title="Café ☃?")
        write_json_atomic(self.session.questions_path(1), dict(VALID_ROUND, questions=[question]))
        payload = self.get_json("/api/round")
        self.assertEqual(payload["round"]["questions"][0]["title"], "Café ☃?")

    def test_malformed_json_reports_an_error_and_the_server_survives(self):
        self.session.questions_path(1).write_text("{not json", encoding="utf-8")
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertIn("round-001.questions.json", payload["error"])
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_undecodable_bytes_report_an_error_rather_than_crashing(self):
        self.session.questions_path(1).write_bytes(b"\xff\xfe{\x00")
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertIn("round-001.questions.json", payload["error"])

    def test_an_unreadable_round_file_reports_an_error(self):
        path = self.session.questions_path(1)
        write_json_atomic(path, VALID_ROUND)
        path.chmod(0o000)
        self.addCleanup(path.chmod, 0o644)
        try:
            path.read_text(encoding="utf-8")
        except PermissionError:
            pass
        else:
            self.skipTest("this user can read a mode-000 file; probably root")
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertIn("round-001.questions.json", payload["error"])

    def test_an_unreadable_round_names_the_file_and_not_where_it_lives(self):
        """The OSError arm is the one that carries a path -- str() of one
        reads "[Errno 21] Is a directory: '/tmp/.../round-001.questions.json'"
        -- and three separate one-line mutations put the whole of that in the
        JSON the browser renders: _reason returning str(exc), and either
        payload formatting exc where it should format _reason(exc). The
        ValueError test below cannot see any of them, because str() of a
        JSONDecodeError names no path to begin with."""
        self.session.questions_path(1).mkdir()
        self.server.session = _RoundIsADirectory(self._tmp.name)
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertIn("round-001.questions.json", payload["error"])
        self.assertNamesNoPath(json.dumps(payload))

    def test_an_error_never_names_a_filesystem_path(self):
        """The file's name is useful; where the agent keeps its files is not,
        and the browser is not always the person who started the session."""
        self.session.questions_path(1).write_text("{not json", encoding="utf-8")
        payload = self.get_json("/api/round")
        self.assertNotIn(self._tmp.name, json.dumps(payload))

    def test_a_schema_invalid_round_reports_details(self):
        broken = {"round": 1, "questions": [{"id": "Q-1", "title": "x", "type": "dropdown"}]}
        write_json_atomic(self.session.questions_path(1), broken)
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertTrue(any("type must be one of" in d for d in payload["details"]))

    def test_a_mistyped_ledger_is_reported_like_any_other_schema_problem(self):
        """The ledger used to pass validation whatever shape it was in, and
        the page it reached threw while rendering it. Both ends are fixed;
        this is the one that keeps the agent from having to guess."""
        round_obj = dict(VALID_ROUND, ledger={"contradictions": "CON-002"})
        write_json_atomic(self.session.questions_path(1), round_obj)
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["details"], ["ledger.contradictions: not a list"])

    def test_a_valid_ledger_is_served_with_its_round(self):
        ledger = {"contradictions": [{"id": "CON-1", "between": ["Q-1"],
                                      "text": "conflict"}],
                  "decisions": [{"id": "DEC-1", "title": "Playlists are private"}]}
        round_obj = dict(VALID_ROUND, ledger=ledger)
        write_json_atomic(self.session.questions_path(1), round_obj)
        payload = self.get_json("/api/round")
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["round"]["ledger"], ledger)

    def test_a_schema_invalid_round_is_not_served_as_content(self):
        """The page must never render a round the validator rejected."""
        broken = {"round": 1, "questions": [{"id": "Q-1", "title": "x", "type": "dropdown"}]}
        write_json_atomic(self.session.questions_path(1), broken)
        self.assertIsNone(self.get_json("/api/round").get("round"))

    def test_a_round_that_is_not_an_object_is_rejected(self):
        write_json_atomic(self.session.questions_path(1), ["not", "a", "round"])
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["details"])


class BriefTest(ServerTestCase):
    def test_a_missing_brief_renders_empty(self):
        self.assertEqual(self.get_json("/api/brief")["html"], "")

    def test_the_brief_is_rendered_to_html(self):
        self.session.brief_path.write_text("# Vision\n\nA player.\n", encoding="utf-8")
        html = self.get_json("/api/brief")["html"]
        self.assertIn("<h1>Vision</h1>", html)
        self.assertIn("<p>A player.</p>", html)

    def test_the_brief_is_escaped_on_the_way_out(self):
        """Kills any mutant that hands the raw file to the page. CRAFT.md is
        written by an agent from the user's own words; it is not trusted HTML."""
        self.session.brief_path.write_text("<script>alert(1)</script>\n", encoding="utf-8")
        html = self.get_json("/api/brief")["html"]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_non_ascii_in_the_brief_survives(self):
        self.session.brief_path.write_text("café ☃\n", encoding="utf-8")
        self.assertIn("café ☃", self.get_json("/api/brief")["html"])

    def test_an_undecodable_brief_is_reported_not_a_crash(self):
        self.session.brief_path.write_bytes(b"# hi\n\xff\xfe\n")
        payload = self.get_json("/api/brief")
        self.assertEqual(payload["html"], "")
        self.assertIn("CRAFT.md", payload["error"])
        self.assertNotIn(self._tmp.name, json.dumps(payload))
        self.assertEqual(self.get("/").status, 200)  # still alive


class BriefErrorTest(ServerTestCase):
    def test_an_unreadable_brief_names_it_and_not_where_it_lives(self):
        """brief_payload's OSError arm, and the same three mutations. A
        directory at CRAFT.md rather than a mode, so root sees it too; the
        undecodable-brief test above takes the ValueError arm, whose str()
        names no path however it is formatted."""
        self.session.brief_path.mkdir()
        payload = self.get_json("/api/brief")
        self.assertEqual(payload["html"], "")
        self.assertIn("CRAFT.md", payload["error"])
        self.assertNamesNoPath(json.dumps(payload))
        self.assertEqual(self.get("/").status, 200)  # still alive


class ReadOnlyTest(ServerTestCase):
    def snapshot(self):
        state = {}
        for path in sorted(Path(self._tmp.name).rglob("*")):
            state[str(path)] = path.stat().st_mtime_ns if path.is_file() else "dir"
            if path.is_file():
                state[str(path) + ":bytes"] = path.read_bytes()
        return state

    def test_serving_writes_nothing_at_all(self):
        """The agent owns every file in the project. The server reads."""
        self.session.brief_path.write_text("# Vision\n", encoding="utf-8")
        write_json_atomic(self.session.questions_path(1), VALID_ROUND)
        before = self.snapshot()
        for path in ("/", "/api/round", "/api/brief", "/api/draft?round=1"):
            self.get(path).read()
        self.refused("/nope")
        self.refused("/api/draft")
        self.refused("/", key=False)
        self.assertEqual(self.snapshot(), before)


class BindingTest(ServerTestCase):
    def test_the_default_bind_is_the_loopback_interface(self):
        """One line -- a host default of "" or "0.0.0.0" -- puts the brief and
        a key-bearing URL on every interface the machine has."""
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(self.server.socket.getsockname()[0], "127.0.0.1")

    def test_the_port_property_reports_the_bound_port(self):
        port = self.server.port
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)
        self.assertEqual(port, self.server.socket.getsockname()[1])

    def test_a_non_loopback_host_is_refused(self):
        for host in ("0.0.0.0", "", "192.168.1.10", "example.com",
                     # Loosening the exact match to `"localhost" not in host`
                     # accepts all three of these, and the first two are
                     # names somebody else gets to point wherever they like.
                     "localhost.evil.example", "evil.localhost", "notlocalhost"):
            with self.assertRaises(ValueError, msg=host):
                CraftServer(self.session, self.key, host=host, port=0)

    def test_a_refused_host_leaves_no_socket_listening(self):
        """The guard has to run before the bind, or the refusal still exposed
        the port for as long as the interpreter keeps the socket."""
        probe = socket.socket()
        probe.bind(("0.0.0.0", 0))
        port = probe.getsockname()[1]
        probe.close()
        with self.assertRaises(ValueError):
            CraftServer(self.session, self.key, host="0.0.0.0", port=port)
        again = socket.socket()
        try:
            again.bind(("0.0.0.0", port))  # free, so nothing was left listening
        finally:
            again.close()

    def test_the_ipv6_loopback_is_accepted_and_binds_ipv6(self):
        """The skip is decided by the machine, not by the code under test: a
        server that failed to select AF_INET6 would otherwise fail to bind ::1
        and be excused as "no IPv6 here"."""
        probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        try:
            probe.bind(("::1", 0))
        except OSError as exc:
            self.skipTest("no IPv6 loopback on this machine: {}".format(exc))
        finally:
            probe.close()
        server = CraftServer(self.session, self.key, host="::1", port=0)
        try:
            self.assertEqual(server.address_family, socket.AF_INET6)
            self.assertEqual(server.socket.getsockname()[0], "::1")
        finally:
            server.server_close()

    def test_localhost_is_accepted(self):
        server = CraftServer(self.session, self.key, host="localhost", port=0)
        try:
            self.assertTrue(server.port > 0)
        finally:
            server.server_close()


class IdleTest(ServerTestCase):
    def test_a_request_resets_the_idle_clock(self):
        self.server._last -= 100
        self.assertGreater(self.server.idle_seconds(), 50)
        self.get("/api/round").read()
        self.assertLess(self.server.idle_seconds(), 5)

    def test_the_idle_timeout_is_four_hours_by_default(self):
        self.assertEqual(self.server.idle_timeout_s, 14400)
        other = CraftServer(self.session, self.key, port=0, idle_timeout_s=5)
        try:
            self.assertEqual(other.idle_timeout_s, 5)
        finally:
            other.server_close()


class KeyTest(unittest.TestCase):
    def test_a_key_is_long_and_hex(self):
        key = make_key()
        self.assertEqual(len(key), 64)
        int(key, 16)  # raises if it is not hex

    def test_two_keys_differ(self):
        self.assertNotEqual(make_key(), make_key())

    def test_there_is_no_cookie_machinery_left_to_name(self):
        """The inversion of "the cookie name is stable". The name is stable
        by being absent: nothing in server.py sets a cookie or reads one, and
        the reason is that cookies are scoped to a host and not a port, so
        every other http://127.0.0.1:<port> page shares this one's jar.

        Behavioural tests cover a cookie coming back in and being believed;
        this covers it coming back in at all, which is how the helpers would
        reappear -- a name here is a name tasks 6 and 10 would then use."""
        self.assertFalse(hasattr(server_module, "COOKIE"))
        self.assertFalse(hasattr(server_module, "cookie_values"))


class _BlockingSession(Session):
    """A session whose round read parks inside the handler until released.

    A barrier across two clients only synchronises the START of two requests,
    and both of these finish in microseconds either way -- so a plain
    HTTPServer, handling one request at a time, passed that. Holding the
    first request open until the second has been ANSWERED is what actually
    tells the two servers apart.
    """

    def __init__(self, project_dir):
        Session.__init__(self, project_dir)
        self.holding = threading.Event()
        self.release = threading.Event()

    def current_round(self):
        self.holding.set()
        self.release.wait(timeout=10)
        return None


class ConcurrencyTest(ServerTestCase):
    def test_a_request_in_flight_does_not_hold_up_the_next_one(self):
        """ThreadingHTTPServer, not HTTPServer: a poll in one tab must not
        block the other."""
        blocking = _BlockingSession(self._tmp.name)
        self.server.session = blocking
        # Before anything that can fail: a parked handler thread outlives the
        # assertion that let it park.
        self.addCleanup(blocking.release.set)
        results = []

        def hit():
            try:
                results.append(self.get_json("/api/round")["round"])
            except Exception as exc:  # recorded, not raised, off the main thread
                results.append(exc)

        thread = threading.Thread(target=hit)
        thread.start()
        try:
            self.assertTrue(blocking.holding.wait(timeout=5), "the first request never arrived")
            # The second request, made while the first is still in a handler.
            self.assertEqual(self.get_json("/api/brief")["html"], "")
        finally:
            blocking.release.set()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results, [None])


class TerminalTest(ServerTestCase):
    """What the agent's console is allowed to learn from a request.

    The same invariant as the responses: no absolute paths, no tracebacks.
    socketserver's own handle_error breaks it on an ordinary reload, with a
    perfectly valid key, by printing the traceback of the BrokenPipeError a
    client that stopped reading leaves behind.
    """

    def stderr_from(self, exc):
        """Whatever handle_error prints for one exception, and nothing else."""
        captured = io.StringIO()
        try:
            raise exc
        except BaseException:
            with contextlib.redirect_stderr(captured):
                self.server.handle_error(None, ("127.0.0.1", 0))
        return captured.getvalue()

    def test_a_client_hanging_up_prints_nothing(self):
        hangups = (
            BrokenPipeError(32, "Broken pipe"),
            ConnectionResetError(104, "Connection reset by peer"),
            ConnectionAbortedError(103, "Software caused connection abort"),
            socket.timeout("timed out"),
        )
        for exc in hangups:
            self.assertEqual(self.stderr_from(exc), "", repr(exc))
        self.assertEqual(self.server.disconnects, len(hangups))
        self.assertEqual(self.server.handler_errors, 0)

    def test_a_real_failure_is_named_but_not_described(self):
        """Swallowing everything would hide a bug in a handler, so the type
        and a count survive. The message does not: an OSError's carries the
        path it failed on, which is the thing this is all about."""
        printed = self.stderr_from(FileNotFoundError(2, "No such file", str(APP_HTML)))
        self.assertIn("FileNotFoundError", printed)
        self.assertEqual(len(printed.strip().splitlines()), 1)
        self.assertNotIn("Traceback", printed)
        self.assertNamesNoPath(printed)
        self.assertEqual(self.server.handler_errors, 1)
        self.assertEqual(self.server.disconnects, 0)

    def test_a_client_that_hangs_up_mid_response_prints_no_traceback(self):
        """The reachable case, end to end: a browser reloading or navigating
        away stops reading and goes. Left alone, that prints server.py's
        absolute path across the terminal of whoever started the session."""
        page = Path(self._tmp.name) / "big.html"
        # Big enough that the response cannot fit in the socket buffers and
        # be gone before the abort lands. A small one races, and the race is
        # won often enough that the test would pass without proving anything.
        page.write_bytes(b"x" * (1 << 20))
        server_module.APP_HTML = page
        self.addCleanup(setattr, server_module, "APP_HTML", APP_HTML)
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            client = self.raw_connection()
            client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2048)
            client.sendall(self.raw_request("GET", "/"))
            # A reset rather than a polite close, so the write already in
            # flight fails instead of being quietly discarded.
            client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            client.close()
            self.wait_until(lambda: self.server.disconnects or captured.getvalue())
        self.assertEqual(captured.getvalue(), "")
        self.assertEqual(self.server.disconnects, 1)
        self.assertEqual(self.server.handler_errors, 0)


class HandlerTimeoutTest(ServerTestCase):
    def test_a_half_open_connection_is_closed_rather_than_held_for_ever(self):
        """Three hundred connections that begin a request and stop hold three
        hundred threads and file descriptors, with no ceiling and no reaper.
        Thread and descriptor exhaustion by any unprivileged process on the
        machine is the adversary the session key exists for."""
        # The test's own clock, not the production 30 s: what is asserted
        # here is that a ceiling exists, not what it has been set to.
        self.addCleanup(
            setattr, server_module._Handler, "timeout", server_module._Handler.timeout
        )
        server_module._Handler.timeout = 0.2
        client = self.raw_connection()
        client.sendall(b"GET / HTTP/1.1")  # a request line that never ends
        self.assertEqual(client.recv(4096), b"")  # closed from the other end
        self.assertTrue(self.wait_until(lambda: self.server.timeouts == 1))

    def test_the_timeout_is_a_bounded_number_of_seconds(self):
        """A None here is what "no ceiling" looks like written down."""
        timeout = server_module._Handler.timeout
        self.assertIsInstance(timeout, (int, float))
        self.assertTrue(0 < timeout <= 120, timeout)

    def test_the_read_budget_is_a_bounded_number_of_seconds(self):
        budget = server_module._Handler.read_budget
        self.assertIsInstance(budget, (int, float))
        self.assertTrue(0 < budget <= 120, budget)

    def test_a_trickled_request_cannot_outlive_the_read_budget(self):
        """The ceiling `timeout` is not. socketserver applies it with
        settimeout(), which is a per-read IDLE clock: every byte resets it, so
        a client sending one byte at a time under it holds a thread and a
        descriptor for as long as it likes -- readline(65537) will take 64 KiB
        at that rate, and the header parser a hundred lines after that.

        The idle clock here is left at its production value on purpose. What
        ends this connection has to be the budget, not the clock, or the test
        would pass against the very code that has no budget at all.
        """
        self.addCleanup(setattr, server_module._Handler, "read_budget",
                        server_module._Handler.read_budget)
        server_module._Handler.read_budget = 0.3
        client = self.raw_connection()
        client.settimeout(5)
        started = time.monotonic()
        # Three seconds of willing trickle against a 0.3 s budget: ten times
        # over, so the assertions below cannot be met by a slow machine.
        for _ in range(60):
            try:
                client.sendall(b"G")
            except OSError:
                break  # the far end went away mid-write, which is the point
            if self.wait_until(lambda: self.server.timeouts == 1, timeout=0.05):
                break
        elapsed = time.monotonic() - started
        self.assertEqual(self.server.timeouts, 1)
        self.assertEqual(client.recv(4096), b"")  # closed from the other end
        self.assertLess(elapsed, 2, "the budget did not bound the read")

    def test_a_client_that_stalls_in_its_headers_is_counted_too(self):
        """The request line arrived, so raw_requestline is set and the old
        trick could not see this one: the connection closed and the count
        missed it. Every read timeout is a read timeout, wherever it fell."""
        self.addCleanup(
            setattr, server_module._Handler, "timeout", server_module._Handler.timeout
        )
        server_module._Handler.timeout = 0.2
        client = self.raw_connection()
        # A whole request line, then a header that never ends.
        client.sendall(b"GET /?key=x HTTP/1.0\r\nX-Stall: ")
        self.assertEqual(client.recv(4096), b"")  # closed from the other end
        self.assertTrue(self.wait_until(lambda: self.server.timeouts == 1))


# --------------------------------------------------------------------------
# The write surface: PATCH /api/draft, POST /api/submit, GET /api/draft.
#
# Two things are being guarded here and they are not the same thing.
#
# The first is the product. The submitted answers are what the agent folds
# into CRAFT.md, and four states have to survive the round trip apart:
# answered, delegated ("you decide" -- record it and never ask again),
# skipped ("ask me again") and absent. Collapsing delegated into skipped
# nags the user about a decision they handed over; collapsing skipped into
# delegated silently records one they did not make.
#
# The second is that this is the first code here that reads a request body,
# which turns on a whole class of failure the read endpoints never had: how
# the body is framed, how big it is allowed to be, and whether anything can
# follow it down the same connection.
# --------------------------------------------------------------------------


class WriteTestCase(ServerTestCase):
    """A live server, plus the shortest honest way to speak to it."""

    def send(self, method, path, body=None, key=True, raw=None, headers=None):
        data = raw if raw is not None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.url(path, key),
            data=data,
            headers=headers if headers is not None else {"Content-Type": "application/json"},
            method=method,
        )
        return urllib.request.urlopen(request, timeout=5)

    def send_json(self, method, path, body=None, **kw):
        response = self.send(method, path, body, **kw)
        self.assertIn("application/json", response.headers.get("Content-Type", ""))
        return json.loads(response.read().decode("utf-8"))

    def rejected(self, method, path, body=None, **kw):
        """The HTTPError from a write that must not be performed."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.send(method, path, body, **kw)
        return caught.exception

    def patch(self, body, **kw):
        return self.send_json("PATCH", "/api/draft", body, **kw)

    def post(self, body, **kw):
        return self.send_json("POST", "/api/submit", body, **kw)

    def written(self):
        """Every file under the project, so a stray write has somewhere to
        show up. Path-safety is asserted by absence, not by hoping."""
        return sorted(p for p in Path(self._tmp.name).rglob("*") if p.is_file())


class DraftTest(WriteTestCase):
    """Autosave. It fires on every keystroke, and it is crash insurance: a
    closed tab must lose nothing, and nothing it saves is ever the thing the
    agent reads as an answer."""

    def test_a_patch_persists_the_draft(self):
        self.assertEqual(self.patch({"round": 1, "answers": {"Q-1": {"text": "hi"}}}),
                         {"ok": True})
        self.assertEqual(
            read_json(self.session.draft_path(1)),
            {"round": 1, "answers": {"Q-1": {"text": "hi"}}},
        )

    def test_a_patch_writes_the_draft_and_not_the_answers(self):
        """One character apart in server.py: draft_path vs answers_path. That
        mutant turns every keystroke into a submitted round."""
        self.patch({"round": 1, "answers": {"Q-1": {"text": "hi"}}})
        self.assertTrue(self.session.draft_path(1).exists())
        self.assertFalse(self.session.answers_path(1).exists())

    def test_a_second_patch_replaces_the_first(self):
        self.patch({"round": 1, "answers": {"Q-1": {"text": "one"}}})
        self.patch({"round": 1, "answers": {"Q-1": {"text": "two"}}})
        self.assertEqual(
            read_json(self.session.draft_path(1))["answers"], {"Q-1": {"text": "two"}}
        )

    def test_a_patch_writes_the_round_it_was_given(self):
        """Kills a hard-coded round, and a round read from current_round()
        rather than from the request."""
        self.patch({"round": 2, "answers": {"Q-1": {"text": "two"}}})
        self.assertTrue(self.session.draft_path(2).exists())
        self.assertFalse(self.session.draft_path(1).exists())
        self.assertEqual(read_json(self.session.draft_path(2))["round"], 2)

    def test_the_draft_can_be_read_back(self):
        self.patch({"round": 1, "answers": {"Q-1": {"text": "hi"}}})
        self.assertEqual(
            self.get_json("/api/draft?round=1"),
            {"round": 1, "answers": {"Q-1": {"text": "hi"}}},
        )

    def test_reading_the_draft_reads_the_round_that_was_asked_for(self):
        self.patch({"round": 1, "answers": {"Q-1": {"text": "one"}}})
        self.patch({"round": 2, "answers": {"Q-1": {"text": "two"}}})
        self.assertEqual(self.get_json("/api/draft?round=2")["answers"]["Q-1"]["text"],
                         "two")
        self.assertEqual(self.get_json("/api/draft?round=1")["answers"]["Q-1"]["text"],
                         "one")

    def test_a_draft_that_does_not_exist_is_empty_and_not_an_error(self):
        """Nothing typed yet is the ordinary case on every first load."""
        payload = self.get_json("/api/draft?round=4")
        self.assertEqual(payload, {"round": 4, "answers": {}})
        self.assertNotIn("error", payload)

    def test_a_draft_survives_a_server_restart(self):
        """The whole point of autosave. A restart on the same project reuses
        the port, so the open tab is expected to recover by itself."""
        self.patch({"round": 1, "answers": {"Q-1": {"text": "hi"}}})
        self.server.shutdown()
        self.server = self.start_server()
        self.base = "http://127.0.0.1:{}".format(self.server.port)
        self.assertEqual(
            self.get_json("/api/draft?round=1")["answers"]["Q-1"]["text"], "hi"
        )

    def test_non_ascii_survives_the_draft_round_trip(self):
        self.patch({"round": 1, "answers": {"Q-1": {"text": "café — éè"}}})
        self.assertEqual(
            self.get_json("/api/draft?round=1")["answers"]["Q-1"]["text"],
            "café — éè",
        )

    def test_reading_a_draft_without_a_round_is_a_400(self):
        for query in ("", "?round=", "?round=abc", "?round=0", "?round=-1",
                      "?round=1.0", "?round=1000", "?round=%201"):
            error = self.refused("/api/draft" + query)
            self.assertEqual(error.code, 400, query)

    def test_a_patch_to_any_other_path_is_a_404(self):
        for path in ("/api/submit", "/api/round", "/", "/nope"):
            error = self.rejected("PATCH", path, {"round": 1, "answers": {}})
            self.assertEqual(error.code, 404, path)
        self.assertEqual(self.written(), [])


class UnreadableDraftTest(WriteTestCase):
    """A draft that exists and cannot be read is not the same as no draft.

    Empty means "nothing typed yet" and the form starts blank, which is
    correct. Silently showing that over the top of work that IS on disk
    invites the user to retype it, so a draft that is there and unreadable
    says so.
    """

    def test_a_malformed_draft_is_reported_rather_than_shown_as_empty(self):
        self.session.draft_path(1).write_text("{not json", encoding="utf-8")
        payload = self.get_json("/api/draft?round=1")
        self.assertEqual(payload["answers"], {})
        self.assertIn("round-001.draft.json", payload["error"])

    def test_a_draft_whose_shape_drifted_is_reported_too(self):
        """A hand-edited draft that is valid JSON but not a set of answers
        must not reach the page as one -- and must not crash on the way."""
        for content in ("[]", '"hello"', "3", "null", '{"answers": []}',
                        '{"answers": "x"}', "{}"):
            self.session.draft_path(1).write_text(content, encoding="utf-8")
            payload = self.get_json("/api/draft?round=1")
            self.assertEqual(payload["answers"], {}, content)
            self.assertIn("round-001.draft.json", payload["error"], content)

    def test_the_reply_is_a_shape_and_not_whatever_the_file_held(self):
        """Handing the stored object back would leak whatever else is in it
        and would answer with the round the FILE claims rather than the one
        that was asked for -- so a hand-edited draft could tell the page it
        is looking at a different round."""
        write_json_atomic(
            self.session.draft_path(1),
            {"round": 9, "answers": {"Q-1": {"text": "hi"}}, "note": "hand-edited"},
        )
        self.assertEqual(
            self.get_json("/api/draft?round=1"),
            {"round": 1, "answers": {"Q-1": {"text": "hi"}}},
        )

    def test_an_unreadable_draft_names_the_file_and_not_where_it_lives(self):
        directory = self.session.draft_path(1)
        directory.mkdir()
        payload = self.get_json("/api/draft?round=1")
        self.assertIn("round-001.draft.json", payload["error"])
        self.assertNamesNoPath(payload["error"].replace("round-001.draft.json", ""))
        self.assertNotIn("Traceback", payload["error"])
        self.assertEqual(self.get("/").status, 200)  # still alive


class SubmitTest(WriteTestCase):
    """Send to Claude. This is the product: what lands here is what the agent
    folds into CRAFT.md."""

    def test_submit_writes_the_answers_file_from_the_post_body(self):
        """Not by promoting the draft. A draft that is stale or half-written
        when Send arrives must never become the submitted round -- which is
        why the two values here differ."""
        self.patch({"round": 1, "answers": {"Q-1": {"text": "stale"}}})
        result = self.post(
            {"round": 1, "answers": {"Q-1": {"text": "fresh"}}, "finished": False}
        )
        self.assertEqual(result, {"ok": True, "finished": False})
        stored = read_json(self.session.answers_path(1))
        self.assertEqual(stored["answers"], {"Q-1": {"text": "fresh"}})
        self.assertEqual(stored["round"], 1)
        self.assertIs(stored["finished"], False)

    def test_submit_leaves_the_draft_in_place_untouched(self):
        """Both halves: the draft is not written, and it is not read either.

        Catches the promotion that only fires when the posted answers are
        empty -- typed, autosaved, cleared, Send. The draft still holds what
        was discarded, and a submit that falls back to it stores the thing
        the user just deleted as the product. What was posted was nothing,
        so what is stored is nothing.
        """
        self.patch({"round": 1, "answers": {"Q-1": {"text": "d"}}})
        before = self.session.draft_path(1).read_bytes()
        self.post({"round": 1, "answers": {}, "finished": False})
        self.assertEqual(self.session.draft_path(1).read_bytes(), before)
        self.assertEqual(read_json(self.session.answers_path(1))["answers"], {})

    def test_submit_writes_the_answers_and_not_the_draft(self):
        self.post({"round": 1, "answers": {"Q-1": {"text": "a"}}, "finished": False})
        self.assertTrue(self.session.answers_path(1).exists())
        self.assertFalse(self.session.draft_path(1).exists())

    def test_submit_writes_the_round_it_was_given(self):
        self.post({"round": 7, "answers": {}, "finished": False})
        self.assertTrue(self.session.answers_path(7).exists())
        self.assertEqual(read_json(self.session.answers_path(7))["round"], 7)

    def test_finish_is_recorded_and_reported_back(self):
        """Finish ends the session, so it may not be inferred or defaulted --
        it is carried, stored and echoed."""
        self.assertIs(self.post({"round": 1, "answers": {}, "finished": True})["finished"],
                      True)
        self.assertIs(read_json(self.session.answers_path(1))["finished"], True)

    def test_an_unfinished_round_is_recorded_as_unfinished(self):
        self.assertIs(self.post({"round": 1, "answers": {}, "finished": False})["finished"],
                      False)
        self.assertIs(read_json(self.session.answers_path(1))["finished"], False)

    def test_finished_defaults_to_false_when_it_is_not_carried(self):
        """Absent is not finished. A default of True would end the interview
        on the first Send."""
        for body in ({"round": 1, "answers": {}}, {"round": 1, "answers": {}, "finished": None}):
            self.assertIs(self.post(body)["finished"], False)
            self.assertIs(read_json(self.session.answers_path(1))["finished"], False)

    def test_the_four_answer_states_round_trip_distinctly(self):
        """The one that matters most. schema.answer_state is what the agent
        reads these back through, so the assertion is made in its terms:
        anything that collapses delegated into skipped, or an absent key into
        anything at all, fails here."""
        answers = {
            "Q-1": {"choice": ["email"], "other": None, "note": "passkeys later"},
            "Q-2": {"delegated": True},
            "Q-3": {"skipped": True},
        }
        self.post({"round": 1, "answers": answers, "finished": False})
        stored = read_json(self.session.answers_path(1))["answers"]
        self.assertEqual(schema.answer_state(stored.get("Q-1")), "answered")
        self.assertEqual(schema.answer_state(stored.get("Q-2")), "delegated")
        self.assertEqual(schema.answer_state(stored.get("Q-3")), "skipped")
        self.assertNotIn("Q-4", stored)
        self.assertEqual(schema.answer_state(stored.get("Q-4")), "skipped")
        # Whole, not entry by entry. Comparing only the one entry with a
        # note in it let a mutant that rewrote {"delegated": true} into
        # {"delegated": true, "skipped": true} through -- answer_state reads
        # delegated first, so every assertion above still held.
        self.assertEqual(stored, answers)

    def test_the_answers_are_stored_verbatim(self):
        """No normalising, no dropping of keys the server does not know. The
        agent owns the meaning of these; the server only moves them."""
        answers = {
            "Q-1": {"text": "", "note": None, "extra": [1, {"deep": True}], "n": 0},
            "Q-2": {},
        }
        self.post({"round": 1, "answers": answers, "finished": False})
        self.assertEqual(read_json(self.session.answers_path(1))["answers"], answers)

    def test_the_answers_file_is_the_servers_shape_and_not_the_bodys(self):
        """Verbatim stops at the answers. The server builds the file around
        them key by key, and those four keys are all of it.

        Two mutants, one assertion each. Building the payload from the
        request body -- `dict(body)` and then update -- carries every
        top-level key the caller sent into the file the agent parses.
        `body.get("submitted_at") or time.strftime(...)` lets the caller
        forge the record of when the round was sent, which nothing else here
        would notice because nothing else sends one. The decoy is a date no
        clock on this machine can produce.
        """
        decoy = "1999-01-01T00:00:00Z"
        body = {
            "round": 1,
            "answers": {"Q-1": {"text": "a"}},
            "finished": False,
            "submitted_at": decoy,
            "note": "smuggled",
            "brief": "# not the brief",
        }
        self.post(body)
        stored = read_json(self.session.answers_path(1))
        self.assertEqual(set(stored), {"round", "submitted_at", "finished", "answers"})
        self.assertNotEqual(stored["submitted_at"], decoy)
        self.assertRegex(stored["submitted_at"], r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")

    def test_submit_stamps_the_time_in_utc(self):
        """`time.gmtime` -> `time.localtime` is a one-word change that keeps
        the trailing Z and starts lying. The clock is moved fourteen hours so
        that the two cannot agree by accident."""
        if not hasattr(time, "tzset"):
            self.skipTest("this platform has no time.tzset")
        previous = os.environ.get("TZ")
        self.addCleanup(time.tzset)
        self.addCleanup(self._restore_tz, previous)
        os.environ["TZ"] = "UTC-14"  # POSIX sign is inverted: local is UTC+14
        time.tzset()
        self.assertNotEqual(
            time.strftime("%H", time.localtime()), time.strftime("%H", time.gmtime()),
            "the premise failed: the clock was not moved, so this proves nothing",
        )
        self.post({"round": 1, "answers": {}, "finished": False})
        stamp = read_json(self.session.answers_path(1))["submitted_at"]
        self.assertRegex(stamp, r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
        parsed = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        drift = abs((parsed - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
        self.assertLess(drift, 120, "submitted_at is not UTC: {}".format(stamp))

    def _restore_tz(self, previous):
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous

    def test_the_draft_carries_no_submission_stamp(self):
        """A draft is not a submission. A submitted_at on it would make a
        half-typed round indistinguishable from a sent one to anything that
        reads the directory."""
        self.patch({"round": 1, "answers": {}})
        self.assertNotIn("submitted_at", read_json(self.session.draft_path(1)))

    def test_a_post_to_any_other_path_is_a_404(self):
        for path in ("/api/draft", "/api/round", "/", "/nope"):
            error = self.rejected("POST", path, {"round": 1, "answers": {}})
            self.assertEqual(error.code, 404, path)
        self.assertEqual(self.written(), [])

    def test_a_resubmission_replaces_the_round(self):
        """The user may correct and send again; last one wins, and it is
        whole rather than merged into whatever was there."""
        self.post({"round": 1, "answers": {"Q-1": {"text": "a"}}, "finished": False})
        self.post({"round": 1, "answers": {"Q-2": {"text": "b"}}, "finished": True})
        stored = read_json(self.session.answers_path(1))
        self.assertEqual(stored["answers"], {"Q-2": {"text": "b"}})
        self.assertIs(stored["finished"], True)


class WriteScopeTest(WriteTestCase):
    """Where the writes are allowed to land, asserted by absence."""

    def test_a_write_creates_nothing_outside_the_session_directory(self):
        """`round` comes from the request and names a file. This is the test
        that says it cannot name any other one -- CRAFT.md included, which
        the server must never write under any circumstances."""
        self.session.brief_path.write_text("# Vision\n", encoding="utf-8")
        write_json_atomic(self.session.questions_path(1), VALID_ROUND)
        brief = self.session.brief_path.read_bytes()
        questions = self.session.questions_path(1).read_bytes()
        before = set(self.written())
        self.patch({"round": 1, "answers": {"Q-1": {"text": "a"}}})
        self.post({"round": 1, "answers": {"Q-1": {"text": "a"}}, "finished": False})
        self.assertEqual(
            set(self.written()) - before,
            {self.session.draft_path(1), self.session.answers_path(1)},
        )
        self.assertEqual(self.session.brief_path.read_bytes(), brief)
        self.assertEqual(self.session.questions_path(1).read_bytes(), questions)

    def test_a_traversal_shaped_round_writes_nothing_anywhere(self):
        """Rejected as a round number long before anything formats it into a
        name -- and the assertion is that the whole project is untouched, not
        merely that the status code was right."""
        for value in ("../../etc/passwd", "1/../../x", "../001", "/etc/passwd",
                      "1\x00", "٣", "0x1", "1e3", " 1", "1 "):
            error = self.rejected("PATCH", "/api/draft", {"round": value, "answers": {}})
            self.assertEqual(error.code, 400, repr(value))
        self.assertEqual(self.written(), [])

    def test_the_session_directory_is_rebuilt_if_it_went_missing(self):
        """The agent owns .craft/; a user who deleted it mid-session must not
        lose the round they are typing."""
        import shutil

        shutil.rmtree(str(self.session.craft_dir))
        self.patch({"round": 1, "answers": {"Q-1": {"text": "a"}}})
        self.assertTrue(self.session.draft_path(1).exists())


class _UnwritableSession(Session):
    """A session whose files land under a path that is a FILE, so every write
    raises an OSError deterministically -- on every machine, and as root."""

    def draft_path(self, n):
        return self.craft_dir / "wall" / Session.draft_path(self, n).name

    def answers_path(self, n):
        return self.craft_dir / "wall" / Session.answers_path(self, n).name


class FailedWriteTest(WriteTestCase):
    """A write that cannot happen has to say so. Letting the OSError out
    sends no response at all -- the browser sees a reset connection and the
    user believes their answers were saved."""

    def setUp(self):
        WriteTestCase.setUp(self)
        blocked = _UnwritableSession(self._tmp.name)
        (blocked.craft_dir / "wall").write_text("not a directory", encoding="utf-8")
        self.server.session = blocked

    def test_a_draft_that_cannot_be_written_is_a_clean_500(self):
        error = self.rejected("PATCH", "/api/draft", {"round": 1, "answers": {}})
        self.assertEqual(error.code, 500)
        body = error.read().decode("utf-8", "replace")
        self.assertIn("round-001.draft.json", body)
        self.assertNotIn("Traceback", body)

    def test_a_submission_that_cannot_be_written_is_a_clean_500(self):
        error = self.rejected("POST", "/api/submit", {"round": 1, "answers": {}})
        self.assertEqual(error.code, 500)
        self.assertIn("round-001.answers.json", error.read().decode("utf-8", "replace"))

    def test_a_failed_write_names_the_file_and_not_where_it_lives(self):
        error = self.rejected("POST", "/api/submit", {"round": 1, "answers": {}})
        body = error.read().decode("utf-8", "replace")
        self.assertNamesNoPath(body.replace("round-001.answers.json", ""))

    def test_a_failed_write_does_not_report_success(self):
        """The mutant that matters: swallowing the OSError and answering
        {"ok": true} loses the round in silence."""
        error = self.rejected("POST", "/api/submit", {"round": 1, "answers": {}})
        self.assertNotIn('"ok": true', error.read().decode("utf-8", "replace").lower())

    def test_the_server_survives_a_failed_write(self):
        self.rejected("PATCH", "/api/draft", {"round": 1, "answers": {}})
        self.assertEqual(self.get("/").status, 200)
        self.assertEqual(self.server.handler_errors, 0)


class WriteShapeTest(WriteTestCase):
    """What a body has to be before anything is written from it.

    Both endpoints, every case: a shape check that guards one of them and not
    the other is a hole with a test in front of it.
    """

    ENDPOINTS = (("PATCH", "/api/draft"), ("POST", "/api/submit"))

    def each(self, body=None, raw=None, headers=None):
        for method, path in self.ENDPOINTS:
            yield method, path, self.rejected(
                method, path, body, raw=raw, headers=headers
            )

    def test_a_body_that_is_not_valid_json_is_a_400(self):
        """The last case is the one a decode that replaces cannot answer.

        `b"\\xff\\xfe"` stays invalid JSON however it is decoded, so it says
        nothing about how the bytes were turned into text. The latin-1
        bytes inside the string value below are valid JSON the moment
        `errors="replace"` is used, and what gets stored is then the user's
        sentence with U+FFFD where their letters were. Undecodable is
        refused, not repaired.
        """
        for raw in (b"{", b"", b"\xff\xfe", b'{"round": 1,}', b"{'round': 1}",
                    b'{"round": 1, "answers": {"Q-1": {"text": "caf\xe9 na\xefve"}}}'):
            for method, path, error in self.each(raw=raw):
                self.assertEqual(error.code, 400, (method, raw))
        self.assertEqual(self.written(), [])
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_a_body_that_is_not_a_json_object_is_a_400(self):
        """`json.loads("[]").get(...)` is an AttributeError, which is a crash
        reachable by anyone holding the key."""
        for raw in (b"[]", b'"round"', b"3", b"null", b"true", b"[1,2]"):
            for method, path, error in self.each(raw=raw):
                self.assertEqual(error.code, 400, (method, raw))
        self.assertEqual(self.written(), [])
        self.assertEqual(self.server.handler_errors, 0)

    def test_a_missing_round_is_a_400(self):
        for method, path, error in self.each({"answers": {}}):
            self.assertEqual(error.code, 400, method)
        self.assertEqual(self.written(), [])

    def test_a_round_that_is_not_a_whole_number_is_a_400(self):
        """int() would take 1.9 for round 1 and write a round of answers over
        the wrong one. bool is an int in Python, so True would be round 1."""
        for value in (1.9, 1.0, 0.5, True, False, None, [], {}, [1], {"n": 1}):
            for method, path, error in self.each({"round": value, "answers": {}}):
                self.assertEqual(error.code, 400, (method, repr(value)))
        self.assertEqual(self.written(), [])

    def test_a_round_below_one_is_a_400(self):
        for value in (0, -1, -999, "0", "-1", "00"):
            for method, path, error in self.each({"round": value, "answers": {}}):
                self.assertEqual(error.code, 400, (method, repr(value)))
        self.assertEqual(self.written(), [])

    def test_a_round_beyond_the_three_digit_filename_is_a_400(self):
        """session.ROUND_RE matches exactly three digits, so a round of 1000
        writes a file the rest of the tool can never find again -- and a big
        enough one is a filename the kernel refuses, which would be an OSError
        out of a request holding a valid key."""
        for value in (1000, 10 ** 9, 10 ** 400, "1000", "9999", "10000"):
            for method, path, error in self.each({"round": value, "answers": {}}):
                self.assertEqual(error.code, 400, (method, repr(value)))
        self.assertEqual(self.written(), [])
        self.assertEqual(self.server.handler_errors, 0)

    def test_a_round_spelled_with_leading_zeros_is_a_400(self):
        """One round, one spelling. "0001" and "1" name the same file, so
        accepting both is a way for two callers to believe they are looking
        at different rounds."""
        for value in ("01", "0001", "007", "00"):
            for method, path, error in self.each({"round": value, "answers": {}}):
                self.assertEqual(error.code, 400, (method, repr(value)))
        self.assertEqual(self.written(), [])

    def test_the_edges_of_the_round_range_are_accepted(self):
        """The other half of the bound: a check that refuses everything is
        not a check."""
        for value in (1, 999, "1", "999"):
            for method, path in self.ENDPOINTS:
                self.send(method, path, {"round": value, "answers": {}}).read()
        self.assertTrue(self.session.draft_path(999).exists())
        self.assertTrue(self.session.answers_path(999).exists())

    def test_answers_that_are_not_an_object_are_a_400(self):
        """`body.get("answers") or {}` writes a bare string straight through
        and turns [] into {} without saying so."""
        for value in ([], "hi", 3, True, [{"Q-1": {}}]):
            for method, path, error in self.each({"round": 1, "answers": value}):
                self.assertEqual(error.code, 400, (method, repr(value)))
        self.assertEqual(self.written(), [])

    def test_answers_may_be_absent_or_null(self):
        """An empty round is a legitimate thing to save and to send."""
        for body in ({"round": 1}, {"round": 1, "answers": None}):
            self.assertEqual(self.patch(body), {"ok": True})
            self.assertEqual(read_json(self.session.draft_path(1))["answers"], {})
            self.post(body)
            self.assertEqual(read_json(self.session.answers_path(1))["answers"], {})

    def test_finished_must_be_a_boolean(self):
        """bool("false") is True. A string arriving here would end the
        interview instead of saving a round."""
        for value in ("false", "true", 0, 1, [], {}, "no"):
            error = self.rejected(
                "POST", "/api/submit", {"round": 1, "answers": {}, "finished": value}
            )
            self.assertEqual(error.code, 400, repr(value))
        self.assertEqual(self.written(), [])

    def test_a_refusal_names_no_path_and_carries_the_hardening_headers(self):
        for method, path, error in self.each({"answers": {}}):
            self.assertNamesNoPath(error.read().decode("utf-8", "replace"), method)
            self.assertEqual(error.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(error.headers.get("Referrer-Policy"), "no-referrer")
            self.assertIn("no-store", error.headers.get("Cache-Control", ""))
            self.assertIsNone(error.headers.get("Set-Cookie"))


class WriteAuthTest(WriteTestCase):
    """The write endpoints are their own front door.

    The stdlib answers a method with no do_* itself, before any handler runs,
    so nothing upstream has authenticated a PATCH or a POST. Each has to call
    _authed() first -- before touch(), before parsing, before a byte of body
    is read.
    """

    def test_a_write_without_the_key_is_forbidden(self):
        for method, path in (("PATCH", "/api/draft"), ("POST", "/api/submit")):
            error = self.rejected(method, path, {"round": 1, "answers": {}}, key=False)
            self.assertEqual(error.code, 403, method)
        self.assertEqual(self.written(), [])

    def test_a_write_with_the_wrong_key_is_forbidden(self):
        for key in ("deadbeef", self.key[:-1], self.key + "x", "café☃"):
            error = self.rejected(
                "PATCH", "/api/draft", {"round": 1, "answers": {}}, key=key
            )
            self.assertEqual(error.code, 403, key)
        self.assertEqual(self.written(), [])
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_a_write_with_only_the_cookie_is_forbidden(self):
        """A cookie set by this server was readable by every other listener on
        127.0.0.1. Nothing reads one now, and a write is where that would
        have hurt most."""
        request = urllib.request.Request(
            "{}/api/submit".format(self.base),
            data=b'{"round": 1, "answers": {}}',
            headers={"Content-Type": "application/json",
                     "Cookie": "{}={}".format(COOKIE, self.key)},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.written(), [])

    def test_an_unauthorised_write_cannot_hold_the_session_open(self):
        """touch() before the key check lets any process on the machine keep
        an abandoned session -- and the project lock under it -- alive for
        ever by POSTing at it. Task 5 shipped exactly that on do_GET."""
        for method, path in (("PATCH", "/api/draft"), ("POST", "/api/submit")):
            self.server._last -= 100
            before = self.server.idle_seconds()
            self.rejected(method, path, {"round": 1, "answers": {}}, key=False)
            self.assertGreaterEqual(self.server.idle_seconds(), before, method)

    def test_an_authorised_write_does_hold_the_session_open(self):
        """The other half: autosave is what keeps a session alive while the
        user is typing rather than requesting anything."""
        self.server._last -= 100
        self.assertGreater(self.server.idle_seconds(), 50)
        self.patch({"round": 1, "answers": {}})
        self.assertLess(self.server.idle_seconds(), 50)

    def test_an_unauthorised_write_looks_the_same_whatever_it_aimed_at(self):
        """Auth before routing, so a caller without the key cannot use the
        404 to find out which URLs exist."""
        real = self.rejected("POST", "/api/submit", {}, key=False)
        fake = self.rejected("POST", "/nope", {}, key=False)
        self.assertEqual((real.code, fake.code), (403, 403))
        self.assertEqual(real.read(), fake.read())


class RequestBodyTest(WriteTestCase):
    """How a body is framed, and what may follow it.

    Nothing here read a request body before task 6, and the module docstring
    said so. Reading one turns on the whole class of failure this class is
    about: a length that is a lie, a length that is enormous, two lengths, a
    chunked encoding this server does not speak, and a second request riding
    down the same connection behind any of them.
    """

    def raw(self, headers, body=b"", method="POST", path="/api/submit", key=True):
        """One raw HTTP/1.1 request, and everything sent back before close.

        HTTP/1.1 on purpose: it is the only version whose keep-alive the
        stdlib would honour, so a connection that stays open would stay open
        for this request and no other.
        """
        client = self.raw_connection()
        target = self.url(path, key)[len(self.base):]
        head = "{} {} HTTP/1.1\r\nHost: 127.0.0.1\r\n".format(method, target)
        head += "".join(h + "\r\n" for h in headers) + "\r\n"
        client.sendall(head.encode("utf-8") + body)
        return self.read_answer(client)

    def read_answer(self, client):
        """Everything that arrived before the connection ended, reset or not.

        ServerTestCase.read_to_close cannot be used here. A body this server
        refused without reading is still sitting in the kernel's receive
        queue when the socket closes, and closing on top of unread bytes is
        an RST rather than a clean FIN. Linux hands over what it already
        queued before reporting that, so the response is not lost -- but the
        reset itself is expected here and is not a failure.
        """
        client.settimeout(5)
        received = b""
        while True:
            try:
                chunk = client.recv(4096)
            except ConnectionResetError:
                return received
            if not chunk:
                return received
            received += chunk

    def status(self, received):
        self.assertTrue(received, "the server said nothing at all")
        return received.splitlines()[0]

    def test_a_body_with_no_content_length_is_refused(self):
        """Nothing frames it, so nothing may be read from it."""
        received = self.raw([])
        self.assertIn(b"411", self.status(received), received)
        self.assertEqual(self.written(), [])

    def test_a_content_length_that_is_not_a_length_is_refused(self):
        for value in ("abc", "-1", "+1", "1.5", "0x10", "", " ", "1 2", "1,1",
                      "9" * 25, "٣"):
            received = self.raw(["Content-Length: " + value], b'{"round": 1}')
            self.assertIn(b"400", self.status(received), (value, received))
        self.assertEqual(self.written(), [])
        self.assertEqual(self.server.handler_errors, 0)

    def test_two_content_length_headers_are_refused(self):
        """Two answers to "how long is it" is the oldest smuggling primitive
        there is, and this server picks neither."""
        body = b'{"round": 1, "answers": {}}'
        received = self.raw(
            ["Content-Length: {}".format(len(body)), "Content-Length: 4"], body
        )
        self.assertIn(b"400", self.status(received), received)
        self.assertEqual(self.written(), [])

    def test_a_chunked_body_is_refused(self):
        for headers in (["Transfer-Encoding: chunked"],
                        ["Transfer-Encoding: Chunked"],
                        ["Transfer-Encoding: gzip, chunked"]):
            received = self.raw(headers, b"0\r\n\r\n")
            self.assertIn(b"400", self.status(received), received)
        self.assertEqual(self.written(), [])

    def test_a_content_length_beside_a_transfer_encoding_is_refused(self):
        """The classic desync: two framings, and an attacker choosing which
        one the next reader believes."""
        body = b'{"round": 1, "answers": {}}'
        received = self.raw(
            ["Content-Length: {}".format(len(body)), "Transfer-Encoding: chunked"], body
        )
        self.assertIn(b"400", self.status(received), received)
        self.assertEqual(self.written(), [])

    def test_a_body_larger_than_the_limit_is_refused_on_its_header_alone(self):
        """Refused without reading a byte of it. No body is sent here at all,
        which is the assertion: the answer comes from the announcement."""
        received = self.raw(["Content-Length: {}".format(server_module.MAX_BODY_BYTES + 1)])
        self.assertIn(b"413", self.status(received), received)
        self.assertEqual(self.written(), [])

    def test_the_limit_is_a_bounded_number_of_bytes(self):
        """A ceiling of None, or of sys.maxsize, is no ceiling. This server
        holds a lock on the user's project and runs on their laptop."""
        limit = server_module.MAX_BODY_BYTES
        self.assertIsInstance(limit, int)
        self.assertGreater(limit, 64 * 1024)
        self.assertLessEqual(limit, 16 * 1024 * 1024)

    def test_a_body_of_exactly_the_limit_is_still_served(self):
        """The other half of the bound, and the byte it turns on. A note the
        size of a chapter is a thing a person may legitimately type, and a
        ceiling written `>=` refuses the largest body it advertises."""
        limit = server_module.MAX_BODY_BYTES
        skeleton = json.dumps({"round": 1, "answers": {"Q-1": {"text": ""}}})
        answers = {"Q-1": {"text": "x" * (limit - len(skeleton.encode("utf-8")))}}
        body = json.dumps({"round": 1, "answers": answers}).encode("utf-8")
        self.assertEqual(len(body), limit, "the test did not build a body of the limit")
        self.assertEqual(
            json.loads(self.send("PATCH", "/api/draft", raw=body).read().decode("utf-8")),
            {"ok": True},
        )
        self.assertEqual(
            len(read_json(self.session.draft_path(1))["answers"]["Q-1"]["text"]),
            limit - len(skeleton.encode("utf-8")),
        )

    def test_a_body_over_the_limit_is_refused_however_far_over(self):
        """The byte past the ceiling, and a length nowhere near it.

        A ceiling is not a band. `MAX < length < 2 * MAX` refuses the first
        of these and lets the second through framing, at which point the
        server settles down to read a gigabyte off a laptop socket.
        """
        limit = server_module.MAX_BODY_BYTES
        for length in (limit + 1, 10 ** 9):
            received = self.raw(["Content-Length: {}".format(length)])
            self.assertIn(b"413", self.status(received), (length, received))
        self.assertEqual(self.written(), [])

    def test_a_body_shorter_than_its_content_length_writes_nothing(self):
        """A length that over-promises must not be padded, truncated or
        parsed from what did arrive."""
        self.addCleanup(
            setattr, server_module._Handler, "read_budget",
            server_module._Handler.read_budget,
        )
        server_module._Handler.read_budget = 0.3
        body = b'{"round": 1, "answers": {}}'
        received = self.raw(["Content-Length: {}".format(len(body) + 50)], body)
        self.assertEqual(self.written(), [])
        self.assertIn(b"408", self.status(received), received)

    def test_a_body_that_ends_early_is_refused_rather_than_parsed(self):
        """The other way a length over-promises: the client stops sending and
        half-closes, so the read ends at EOF rather than at the budget. What
        arrived is valid JSON on its own, which is exactly why it must not be
        parsed -- a length that lies is a lie about framing."""
        whole = b'{"round": 1, "answers": {}}   '
        client = self.raw_connection()
        target = self.url("/api/submit")[len(self.base):]
        client.sendall(
            ("POST {} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: {}\r\n\r\n"
             .format(target, len(whole) + 40)).encode("utf-8") + whole
        )
        client.shutdown(socket.SHUT_WR)
        received = self.read_answer(client)
        self.assertIn(b"400", self.status(received), received)
        self.assertEqual(self.written(), [])

    def test_a_body_that_never_arrives_cannot_outlive_the_read_budget(self):
        """The read budget is lifted once the headers are parsed, on the
        grounds that nothing here read a body. Something does now, so a body
        that is announced and then trickled must be bounded by an absolute
        clock and not by the idle one every byte resets."""
        self.addCleanup(
            setattr, server_module._Handler, "read_budget",
            server_module._Handler.read_budget,
        )
        server_module._Handler.read_budget = 0.3
        client = self.raw_connection()
        target = self.url("/api/submit")[len(self.base):]
        client.sendall(
            ("POST {} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 4096\r\n\r\n"
             .format(target)).encode("utf-8")
        )
        started = time.monotonic()
        client.sendall(b"{")
        received = self.read_answer(client)
        self.assertLess(time.monotonic() - started, 5, "the body read was unbounded")
        # Answered, not merely dropped. Letting the socket timeout out of the
        # handler closes the connection with no response at all, and the page
        # cannot tell that from the server having died.
        self.assertIn(b"408", self.status(received), received)
        self.assertTrue(self.wait_until(lambda: self.server.timeouts >= 1))
        self.assertEqual(self.written(), [])

    def test_nothing_follows_a_body_down_the_same_connection(self):
        """Pipelining, which is what makes a mis-framed body dangerous: the
        second request is the one that was never authorised as itself. It
        must not execute, and the way to see that is that its write never
        happened."""
        first = b'{"round": 1, "answers": {}}'
        second_target = self.url("/api/draft")[len(self.base):]
        second_body = b'{"round": 2, "answers": {"Q-1": {"text": "smuggled"}}}'
        second = (
            "PATCH {} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: {}\r\n\r\n"
            .format(second_target, len(second_body)).encode("utf-8")
        ) + second_body
        received = self.raw(
            ["Content-Length: {}".format(len(first)), "Connection: keep-alive"],
            first + second,
        )
        self.assertIn(b"200", self.status(received), received)
        self.assertEqual(received.count(b"HTTP/1."), 1, received)
        self.assertTrue(self.session.answers_path(1).exists())
        self.assertFalse(self.session.draft_path(2).exists())

    def test_the_connection_still_ends_if_this_server_ever_speaks_http_1_1(self):
        """The guard, on its own.

        Today the stdlib closes after every response because
        protocol_version is HTTP/1.0, so the pipelining tests above pass
        whether or not the write handlers close the connection themselves --
        they are pinned by a class attribute in another file. Raise that
        attribute to 1.1 and keep-alive becomes real: the second request
        rides in on a connection nobody authorised it on, framed by whatever
        the first one's Content-Length said. It must still never run.
        """
        self.addCleanup(
            setattr, server_module._Handler, "protocol_version",
            server_module._Handler.protocol_version,
        )
        server_module._Handler.protocol_version = "HTTP/1.1"
        first = b'{"round": 1, "answers": {}}'
        target = self.url("/api/draft")[len(self.base):]
        smuggled = b'{"round": 5, "answers": {"Q-1": {"text": "smuggled"}}}'
        rest = (
            "PATCH {} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: {}\r\n\r\n"
            .format(target, len(smuggled)).encode("utf-8")
        ) + smuggled
        received = self.raw(
            ["Content-Length: {}".format(len(first)), "Connection: keep-alive"],
            first + rest,
        )
        self.assertIn(b"200", self.status(received), received)
        self.assertEqual(received.count(b"HTTP/1."), 1, received)
        self.assertFalse(self.session.draft_path(5).exists())

    def test_the_connection_ends_on_the_path_that_refuses_the_write_too(self):
        """The same guard, on the branch the test above never reaches.

        `close_connection = True` sits ABOVE the key check, so a request
        this server will not serve still ends its connection and takes its
        unread body with it. Move that line below the check and only the
        AUTHORISED path closes -- the refusal is back to resting on
        protocol_version being HTTP/1.0, which is the exact dependency the
        line exists to remove. So it is raised here, and the first request
        carries no key: what follows the 403 down the connection is a body
        nobody read, which the next read takes for a request line.
        """
        self.addCleanup(
            setattr, server_module._Handler, "protocol_version",
            server_module._Handler.protocol_version,
        )
        server_module._Handler.protocol_version = "HTTP/1.1"
        first = b'{"round": 1, "answers": {"Q-1": {"text": "unauthorised"}}}'
        target = self.url("/api/draft")[len(self.base):]
        smuggled = b'{"round": 6, "answers": {"Q-1": {"text": "smuggled"}}}'
        rest = (
            "PATCH {} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: {}\r\n\r\n"
            .format(target, len(smuggled)).encode("utf-8")
        ) + smuggled
        received = self.raw(
            ["Content-Length: {}".format(len(first)), "Connection: keep-alive"],
            first + rest,
            key=False,
        )
        self.assertIn(b"403", self.status(received), received)
        self.assertEqual(received.count(b"HTTP/1."), 1, received)
        self.assertFalse(self.session.draft_path(6).exists())
        self.assertEqual(self.written(), [])

    def test_a_lie_about_the_length_smuggles_nothing_either(self):
        """The same pipelining, framed by a Content-Length that stops short
        so the rest of the bytes look like a fresh request."""
        first = b'{"round": 1, "answers": {}}'
        smuggled_target = self.url("/api/draft")[len(self.base):]
        smuggled_body = b'{"round": 3, "answers": {}}'
        rest = (
            "PATCH {} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: {}\r\n\r\n"
            .format(smuggled_target, len(smuggled_body)).encode("utf-8")
        ) + smuggled_body
        self.raw(["Content-Length: {}".format(len(first))], first + rest)
        self.assertFalse(self.session.draft_path(3).exists())

    def test_a_body_of_zero_length_is_refused_rather_than_invented(self):
        """An empty body is not an empty object.

        Both spellings answer 400, so the status code cannot tell them apart
        and the message is what constrains it: `read(length) if length else
        b"{}"` answers "a round number is required", having parsed a request
        that carried nothing as one that carried {}.
        """
        received = self.raw(["Content-Length: 0"])
        self.assertIn(b"400", self.status(received), received)
        self.assertIn(b"not valid JSON", received, received)
        self.assertNotIn(b"round number", received, received)
        self.assertEqual(self.written(), [])


class WriteTerminalTest(WriteTestCase):
    """The agent's terminal learns no more from a write than from a read."""

    @contextlib.contextmanager
    def captured_stderr(self):
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            yield buffer

    def test_no_shape_of_write_reaches_the_terminal(self):
        """Every refusal above is a branch that could have been an uncaught
        exception instead, and an uncaught exception here is a traceback full
        of absolute paths across the console of whoever started the session.

        The wait is negative and bounded: handle_error runs after the
        response is written, so the only honest way to say "and nothing
        happened afterwards" is to give it a moment to happen in.
        """
        bodies = [b"{", b"[]", b"3", b'{"round": 0}', b'{"round": 1e999}',
                  b'{"round": 1, "answers": []}', b'{"round": 1, "answers": {}}']
        with self.captured_stderr() as buffer:
            for raw in bodies:
                for method, path in (("POST", "/api/submit"), ("PATCH", "/api/draft")):
                    with contextlib.suppress(urllib.error.HTTPError):
                        self.send(method, path, raw=raw).read()
            self.assertFalse(
                self.wait_until(lambda: self.server.handler_errors > 0, timeout=0.5)
            )
        self.assertEqual(buffer.getvalue(), "")
        self.assertEqual(self.server.handler_errors, 0)


class BodyDepthTest(WriteTestCase):
    """What a body may BECOME, which is not what it may carry.

    write_json_atomic serialises with indent=2, and indentation is charged
    per nesting level on every line below it -- so nesting is a multiplier
    on the file that the byte ceiling cannot see. Measured against the code
    before this class existed: a 1,048,384-byte body nested 975 deep wrote a
    685,214,154-byte file into .craft/ in the user's project. 653x, from one
    request, under the ceiling, holding a valid key.

    MAX_BODY_BYTES' own comment says it exists so that nothing "can hand
    this process a body the size of the disk and watch it be written into
    the user's project as a file they never asked for". That was the finding
    almost word for word.
    """

    # What the file may be, as a multiple of the request that produced it.
    # Derived, not guessed: the deepest container an accepted body may have
    # sits at nesting level MAX_BODY_DEPTH, so its items are indented
    # 2 * MAX_BODY_DEPTH, and the cheapest item a caller can send is "1," --
    # two bytes in, (2 * 6) + 1 + len(",\n") = 15 bytes out. 7.5, and the
    # eight below is that with a byte of slack for the wrapper.
    AMPLIFICATION = 8

    def nested(self, depth):
        """A body whose deepest container sits exactly `depth` levels in."""
        value = 1
        # -2: the body itself is level 1 and "answers" is level 2, so two
        # levels are already spent on the shape every honest body has, and
        # the first container added lands under a question id at level 3.
        for _ in range(depth - 2):
            value = [value]
        return {"round": 1, "answers": {"Q-1": value}}

    def test_a_body_nested_deeper_than_the_limit_is_refused(self):
        for depth in (server_module.MAX_BODY_DEPTH + 1, 20, 300, 900):
            for method, path in (("PATCH", "/api/draft"), ("POST", "/api/submit")):
                error = self.rejected(method, path, self.nested(depth))
                self.assertEqual(error.code, 400, (method, depth))
                body = error.read().decode("utf-8", "replace")
                self.assertIn(str(server_module.MAX_BODY_DEPTH), body, depth)
                self.assertNamesNoPath(body, str(depth))
        self.assertEqual(self.written(), [])
        self.assertEqual(self.server.handler_errors, 0)

    def test_a_body_at_the_limit_is_still_accepted(self):
        """The other half of the bound. A limit that refuses everything is
        not a limit, and this one has to leave the page's own bodies alone."""
        depth = server_module.MAX_BODY_DEPTH
        self.assertEqual(self.patch(self.nested(depth)), {"ok": True})
        self.post(dict(self.nested(depth), finished=False))
        self.assertTrue(self.session.answers_path(1).exists())

    def test_the_shape_the_page_actually_sends_is_well_inside_the_limit(self):
        """The limit is a number chosen against a real body, so the real body
        is what pins it. Every answer state the page can produce, at once."""
        answers = {
            "Q-1": {"choice": ["email", "sso"], "other": "passkeys", "note": "later"},
            "Q-2": {"delegated": True},
            "Q-3": {"skipped": True},
            "Q-4": {"text": "a sentence"},
        }
        self.post({"round": 1, "answers": answers, "finished": True})
        self.assertEqual(read_json(self.session.answers_path(1))["answers"], answers)

    def test_the_depth_limit_is_a_small_number(self):
        """A limit of None, or of 980, is the finding again with a number in
        front of it: the amplification is linear in this value."""
        depth = server_module.MAX_BODY_DEPTH
        self.assertIsInstance(depth, int)
        self.assertTrue(4 <= depth <= 16, depth)

    def test_the_file_a_body_can_write_is_bounded_by_the_body(self):
        """The property, asserted directly rather than through the mechanism.

        Not "a deep body is refused" -- that is how the bound happens to be
        implemented today. This is the bound itself: the worst body this
        server will accept, sent to a real server, and then the size of what
        it left on disk. It survives any future rewrite of how the limit is
        reached, and it is the assertion the finding was actually about.

        The body is hand-written rather than json.dumps'd because
        json.dumps separates with ", " and a caller writes ",", and the
        worst case is the caller's.
        """
        depth = server_module.MAX_BODY_DEPTH
        head = b'{"round":1,"answers":{"Q-1":' + b"[" * (depth - 2)
        tail = b"]" * (depth - 2) + b"}}"
        room = server_module.MAX_BODY_BYTES - len(head) - len(tail)
        body = head + b"1," * ((room - 1) // 2) + b"1" + tail
        self.assertLessEqual(len(body), server_module.MAX_BODY_BYTES)
        self.assertEqual(
            json.loads(self.send("PATCH", "/api/draft", raw=body).read().decode("utf-8")),
            {"ok": True},
        )
        written = self.session.draft_path(1).stat().st_size
        self.assertLessEqual(
            written,
            self.AMPLIFICATION * len(body),
            "{} bytes of request wrote {} bytes of file".format(len(body), written),
        )


class SilentFailureTest(WriteTestCase):
    """Two ordinary inputs that produced no HTTP response at all.

    _store caught OSError and _read_body caught ValueError, and neither of
    these is either. What failed was never the storing -- the temp file was
    cleaned up both times -- it was the acknowledgement, which is the exact
    failure _store's own docstring describes: "The browser sees a reset
    connection, and the person at it has no reason to think the answers they
    just sent were not saved."
    """

    SURROGATE_BODIES = (
        # In a value, and in a question id, because the writer encodes keys
        # as well as values and the guard has to walk both.
        b'{"round": 1, "answers": {"Q-1": {"text": "\\ud800"}}}',
        b'{"round": 1, "answers": {"\\ud800": {"text": "x"}}}',
        b'{"round": 1, "answers": {"Q-1": {"choice": ["a", "\\udfff"]}}}',
    )

    def test_a_lone_surrogate_is_answered_rather_than_dropped(self):
        """A browser produces this on its own: ES2019 JSON.stringify escapes
        a lone surrogate as \\ud800 and json.loads decodes it straight back,
        so no attacker is needed. Writing it to a UTF-8 file then raises
        UnicodeEncodeError -- a ValueError, not an OSError -- which escaped
        _store and left the request with no response at all.

        assertRaises(HTTPError) is doing the work here: against the code
        before the fix urllib raises RemoteDisconnected instead, because
        there is no response to parse.
        """
        for raw in self.SURROGATE_BODIES:
            for method, path in (("PATCH", "/api/draft"), ("POST", "/api/submit")):
                error = self.rejected(method, path, raw=raw)
                self.assertEqual(error.code, 400, (method, raw))
                self.assertNamesNoPath(error.read().decode("utf-8", "replace"))
        self.assertEqual(self.written(), [])
        self.assertEqual(self.server.handler_errors, 0)

    def test_a_body_the_decoder_cannot_read_is_answered_rather_than_dropped(self):
        """json.loads raises RecursionError past roughly 980 levels, and a
        RecursionError is not a ValueError. Measured on the code before the
        fix: 980 was answered, 985 was silence.

        The depth limit does NOT close this one and must not be credited
        with it. It is checked on a body that has already been decoded, so
        the decoder always runs first; the catch in _read_body is the whole
        of the guard.
        """
        for depth in (985, 2000, 20000):
            raw = (b'{"round": 1, "answers": {"Q-1": '
                   + b"[" * depth + b"]" * depth + b"}}")
            for method, path in (("PATCH", "/api/draft"), ("POST", "/api/submit")):
                error = self.rejected(method, path, raw=raw)
                self.assertEqual(error.code, 400, (method, depth))
                self.assertNamesNoPath(error.read().decode("utf-8", "replace"))
        self.assertEqual(self.written(), [])
        self.assertEqual(self.server.handler_errors, 0)

    def test_the_boundary_the_decoder_used_to_answer_is_still_answered(self):
        """980 levels was served before the fix and is refused after it, and
        both are responses. What must never come back is nothing."""
        raw = b'{"round": 1, "answers": {"Q-1": ' + b"[" * 980 + b"]" * 980 + b"}}"
        self.assertEqual(self.rejected("PATCH", "/api/draft", raw=raw).code, 400)
        self.assertEqual(self.server.handler_errors, 0)

    def test_neither_input_reaches_the_agents_terminal(self):
        """Both used to arrive as handler_errors with a line on stderr. The
        wait is negative and bounded, like WriteTerminalTest's: handle_error
        runs after the response, so the only honest way to say nothing
        happened afterwards is to give it a moment to happen in."""
        deep = b'{"round": 1, "answers": {"Q-1": ' + b"[" * 5000 + b"]" * 5000 + b"}}"
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            for raw in self.SURROGATE_BODIES + (deep,):
                for method, path in (("POST", "/api/submit"), ("PATCH", "/api/draft")):
                    with contextlib.suppress(urllib.error.HTTPError):
                        self.send(method, path, raw=raw).read()
            self.assertFalse(
                self.wait_until(lambda: self.server.handler_errors > 0, timeout=0.5)
            )
        self.assertEqual(buffer.getvalue(), "")
        self.assertEqual(self.server.handler_errors, 0)

    def test_the_writer_is_guarded_and_not_merely_preceded_by_a_check(self):
        """A limit in front of a call is not a guard around it.

        The check in _read_body should mean nothing ever reaches _store
        carrying either of these, and "should mean" is why _store catches
        them anyway. Reached here by making the writer itself raise, which
        is the only way in once the door is shut -- and the point: whatever
        else ever makes write_json_atomic raise one of these, the browser
        gets an answer and the agent's terminal gets nothing.
        """
        # Captured once, before the loop: taking it inside would restore the
        # first iteration's replacement on the way out.
        self.addCleanup(
            setattr, server_module, "write_json_atomic",
            server_module.write_json_atomic,
        )
        for exc in (UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed"),
                    RecursionError("maximum recursion depth exceeded")):
            def explode(path, payload, exc=exc):
                raise exc

            server_module.write_json_atomic = explode
            error = self.rejected("PATCH", "/api/draft", {"round": 1, "answers": {}})
            self.assertEqual(error.code, 500, repr(exc))
            body = error.read().decode("utf-8", "replace")
            self.assertIn("round-001.draft.json", body)
            self.assertNotIn("Traceback", body)
            self.assertNamesNoPath(body.replace("round-001.draft.json", ""))
            self.assertNotIn('"ok": true', body.lower())
        self.assertEqual(self.server.handler_errors, 0)


class TempSweepTest(WriteTestCase):
    """The .tmp- files a killed session leaves in the user's project.

    write_json_atomic cleans up in an except clause, and process death does
    not run one: measured, twelve SIGKILLs during writes left forty-four
    orphans, and SIGTERM, SIGHUP and Ctrl-C all leak too -- the last because
    KeyboardInterrupt lands on the main thread while writer threads are
    somewhere else entirely. Nothing ever removed one, session.ROUND_RE does
    not match one, and each holds whatever the user had typed.
    """

    def orphan(self, name=".tmp-abc123.json", age=None):
        """A temp file of the shape write_json_atomic leaves behind."""
        path = self.session.craft_dir / name
        path.write_text('{"round": 1, "answers": {"Q-1": {"text": "typed"}}}',
                        encoding="utf-8")
        if age is not None:
            # Aged by hand rather than by waiting: the sweep's own grace
            # period is seconds, and a suite that sleeps them is a suite
            # nobody runs.
            stamp = time.time() - age
            os.utime(str(path), (stamp, stamp))
        return path

    def old(self):
        return server_module.TMP_GRACE_S + 60

    def test_a_start_removes_the_temp_files_a_killed_session_left(self):
        paths = [self.orphan(".tmp-{}.json".format(n), age=self.old()) for n in "abc"]
        server = self.start_server()
        self.assertEqual(server.swept, len(paths))
        for path in paths:
            self.assertFalse(path.exists(), path.name)

    def test_a_start_leaves_alone_a_temp_file_a_live_write_may_be_using(self):
        """An orphan and a temp file another process is mid-write on are the
        same file on disk, so the sweep does not guess: it removes only what
        nothing has touched for TMP_GRACE_S. A write here is one dump, one
        fsync and one rename, so anything that old is not one in flight."""
        fresh = self.orphan(".tmp-live.json")
        server = self.start_server()
        self.assertEqual(server.swept, 0)
        self.assertTrue(fresh.exists())

    def test_the_sweep_removes_nothing_else_in_the_session_directory(self):
        """Only that exact shape, and only in .craft/. Every one of these is
        aged past the grace period, so surviving is about the NAME."""
        keep = []
        for name in ("round-001.questions.json", "round-001.draft.json",
                     "round-001.answers.json", "session.lock", "tmp-abc.json",
                     ".tmp-abc.txt", ".tmpabc.json", "notes.json"):
            keep.append(self.orphan(name, age=self.old()))
        outside = Path(self._tmp.name) / ".tmp-outside.json"
        outside.write_text("{}", encoding="utf-8")
        os.utime(str(outside), (0, 0))
        server = self.start_server()
        self.assertEqual(server.swept, 0)
        for path in keep:
            self.assertTrue(path.exists(), path.name)
        self.assertTrue(outside.exists())

    def test_the_sweep_does_not_remove_a_directory_wearing_that_name(self):
        directory = self.session.craft_dir / ".tmp-adirectory.json"
        directory.mkdir()
        os.utime(str(directory), (0, 0))
        server = self.start_server()
        self.assertEqual(server.swept, 0)
        self.assertTrue(directory.is_dir())

    def test_the_sweep_does_not_follow_a_symlink_wearing_that_name(self):
        """mkstemp cannot produce a symlink, so anything wearing this name
        and pointing somewhere else was put there by something that is not
        this tool -- and unlinking through it is not ours to do."""
        target = Path(self._tmp.name) / "elsewhere.json"
        target.write_text('{"keep": true}', encoding="utf-8")
        link = self.session.craft_dir / ".tmp-link.json"
        link.symlink_to(target)
        server = self.start_server()
        self.assertEqual(server.swept, 0)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), '{"keep": true}')

    def test_a_session_directory_that_cannot_be_swept_still_starts(self):
        """The sweep is housekeeping. It may not be the reason a session
        refuses to start, so every filesystem error in it is absorbed."""
        self.session.craft_dir.chmod(0o000)
        self.addCleanup(self.session.craft_dir.chmod, 0o755)
        try:
            list(self.session.craft_dir.iterdir())
        except PermissionError:
            pass
        else:
            self.skipTest("this user can list a mode-000 directory; probably root")
        server = self.start_server()
        self.assertEqual(server.swept, 0)
        self.session.craft_dir.chmod(0o755)
        self.assertEqual(self.get("/").status, 200)  # and it serves

    def test_a_missing_session_directory_does_not_stop_a_start(self):
        import shutil

        shutil.rmtree(str(self.session.craft_dir))
        server = self.start_server()
        self.assertEqual(server.swept, 0)

    def test_the_sweep_leaves_a_real_draft_recoverable(self):
        """The whole reason autosave exists. Sweeping the wreckage of a
        killed session must not sweep what that session actually saved."""
        self.patch({"round": 1, "answers": {"Q-1": {"text": "typed"}}})
        self.orphan(age=self.old())
        self.server.shutdown()
        self.server = self.start_server()
        self.base = "http://127.0.0.1:{}".format(self.server.port)
        self.assertEqual(
            self.get_json("/api/draft?round=1")["answers"]["Q-1"]["text"], "typed"
        )

    def test_the_grace_period_is_a_bounded_number_of_seconds(self):
        """A grace of a day is a leak with a delay on it; a grace of zero is
        a race against another process's write."""
        grace = server_module.TMP_GRACE_S
        self.assertIsInstance(grace, (int, float))
        self.assertTrue(0 < grace <= 300, grace)


class DraftSequenceTest(WriteTestCase):
    """Autosave fires per keystroke, so two PATCHes for one round overlap as
    the ordinary case rather than as an edge one: HTTP/1.0 means a connection
    per request and ThreadingHTTPServer runs them side by side. Measured
    before this class existed: "hello world" typed once, two saves
    acknowledged 200, and "hel" left on disk.
    """

    def draft(self, round_number=1):
        return read_json(self.session.draft_path(round_number))["answers"]["Q-1"]["text"]

    def patch_seq(self, text, seq=None, round_number=1):
        body = {"round": round_number, "answers": {"Q-1": {"text": text}}}
        if seq is not None:
            body["seq"] = seq
        return self.patch(body)

    def test_an_older_patch_does_not_overwrite_a_newer_one(self):
        """The finding itself: the older keystroke arrives last and wins."""
        self.patch_seq("hello world", 7)
        self.patch_seq("hel", 3)
        self.assertEqual(self.draft(), "hello world")

    def test_a_newer_patch_does_overwrite_an_older_one(self):
        """The other half of the bound. Sequencing that refuses everything
        after the first write is not sequencing, it is a broken autosave."""
        self.patch_seq("hel", 3)
        self.patch_seq("hello world", 7)
        self.assertEqual(self.draft(), "hello world")

    def test_an_ignored_patch_is_a_success_and_not_an_error(self):
        """The client is not wrong -- it sent what it had when it had it, and
        the newer draft is already on disk, which is what the user wanted. An
        error here would put a failure in front of somebody who is typing."""
        self.patch_seq("hello world", 7)
        response = self.send("PATCH", "/api/draft",
                             {"round": 1, "answers": {}, "seq": 3})
        self.assertEqual(response.status, 200)
        payload = json.loads(response.read().decode("utf-8"))
        self.assertIs(payload["ok"], True)
        self.assertIs(payload["stale"], True)

    def test_the_same_seq_twice_is_a_retry_and_not_a_stale_write(self):
        """Equal is not lower. A client that retries one keystroke -- which
        is what a dropped connection looks like from the page -- must not be
        told its own write is out of date."""
        self.patch_seq("hello", 7)
        self.assertEqual(self.patch_seq("hello!", 7), {"ok": True})
        self.assertEqual(self.draft(), "hello!")

    def test_a_patch_with_no_seq_keeps_last_writer_wins(self):
        """Nothing may break in the window before a client sends one, so a
        body with no seq behaves exactly as it did before seq existed."""
        self.patch_seq("one")
        self.patch_seq("two")
        self.assertEqual(self.draft(), "two")

    def test_a_patch_with_no_seq_wins_over_a_sequenced_one(self):
        """The mixed case, in the direction that could have been an
        accident: an unsequenced PATCH is not compared, so it lands."""
        self.patch_seq("sequenced", 7)
        self.patch_seq("unsequenced")
        self.assertEqual(self.draft(), "unsequenced")

    def test_an_unsequenced_patch_does_not_reset_the_ordering(self):
        """The other direction of the mixed case, and the one a mutant gets
        wrong: writing without a seq must not forget the mark, or the next
        stale keystroke walks straight over the newest text."""
        self.patch_seq("hello world", 7)
        self.patch_seq("unsequenced")
        self.patch_seq("hel", 3)
        self.assertEqual(self.draft(), "unsequenced")

    def test_the_ordering_is_kept_per_round(self):
        """One mark for the whole server would make round 2's first
        keystroke stale because round 1 is further along."""
        self.patch_seq("round one", 7, round_number=1)
        self.patch_seq("round two", 3, round_number=2)
        self.assertEqual(self.draft(2), "round two")

    def test_the_seq_is_stored_beside_the_draft(self):
        self.patch_seq("hi", 7)
        self.assertEqual(read_json(self.session.draft_path(1))["seq"], 7)

    def test_a_draft_with_no_seq_is_written_with_the_keys_it_always_had(self):
        """A seq invented for a client that did not send one is a number the
        server made up, and the next PATCH would be compared against it."""
        self.patch_seq("hi")
        self.assertEqual(set(read_json(self.session.draft_path(1))), {"round", "answers"})

    def test_reading_a_draft_back_is_the_same_shape_it_always_was(self):
        """The stored seq is the server's bookkeeping, not the page's."""
        self.patch_seq("hi", 7)
        self.assertEqual(
            self.get_json("/api/draft?round=1"),
            {"round": 1, "answers": {"Q-1": {"text": "hi"}}},
        )

    def test_a_seq_that_is_not_a_whole_number_is_a_400(self):
        """bool is an int in Python, so True would order as seq 1. A float
        or a digit string is a client that believes it is sequencing and is
        not, which is worse than one that does not try."""
        for value in ("3", "abc", 3.0, 0.5, True, False, [], {}, [3]):
            error = self.rejected("PATCH", "/api/draft",
                                  {"round": 1, "answers": {}, "seq": value})
            self.assertEqual(error.code, 400, repr(value))
        self.assertEqual(self.written(), [])

    def test_a_null_seq_is_the_same_as_no_seq(self):
        """JSON.stringify writes null for an absent field often enough that
        refusing it would refuse an honest client."""
        self.assertEqual(self.patch({"round": 1, "answers": {}, "seq": None}),
                         {"ok": True})

    def test_a_seq_is_only_remembered_once_its_write_has_landed(self):
        """A write that failed must not make the next one look out of date.

        Otherwise one unwritable moment turns every later keystroke into a
        silent no-op answered 200: the user keeps typing, the page keeps
        saying saved, and nothing reaches the file again.

        Asserted through the NEXT patch rather than by reading the mark.
        _store sends its own 500 from inside the lock, before do_PATCH gets
        as far as recording anything, so a test that reads the mark the
        moment that response arrives is racing the handler thread -- and a
        racing test lets the mutant through most of the time. The patch
        below is not racing it: it waits on the same lock the recording
        would have happened under.
        """
        blocked = _UnwritableSession(self._tmp.name)
        (blocked.craft_dir / "wall").write_text("not a directory", encoding="utf-8")
        self.server.session = blocked
        self.assertEqual(
            self.rejected("PATCH", "/api/draft",
                          {"round": 1, "answers": {}, "seq": 9}).code,
            500,
        )
        self.server.session = self.session  # the disk comes back
        self.assertEqual(self.patch_seq("typed again", 5), {"ok": True})
        self.assertEqual(self.draft(), "typed again")

    def test_a_write_in_progress_cannot_be_overtaken_by_a_newer_one(self):
        """The lock has to cover the WRITE and not only the comparison.

        Two PATCHes can pass an ordering check in the right order and still
        reach os.replace in the wrong one, which is the finding again with a
        smaller window. On loopback that window is microseconds, so a test
        that hopes to hit it is a test that passes against the bug -- the
        mutation run confirmed exactly that. So the window is opened by
        hand: the older write is held inside write_json_atomic until the
        newer one has had its chance to overtake it.

        Under a lock that spans the write, the newer PATCH is still waiting
        when the older one finishes, and lands after it. Under one that
        spans only the comparison, it lands FIRST and the older content is
        written over the top of it -- which is what the file then holds.
        """
        real = server_module.write_json_atomic
        self.addCleanup(setattr, server_module, "write_json_atomic", real)
        started = threading.Event()
        release = threading.Event()
        # Before anything that can fail: a parked writer thread outlives the
        # assertion that parked it.
        self.addCleanup(release.set)
        held = []

        def slow(path, payload):
            if not held:  # the first write only, which is the older one
                held.append(True)
                started.set()
                release.wait(timeout=10)
            return real(path, payload)

        server_module.write_json_atomic = slow
        failures = []

        def send(text, seq):
            try:
                self.patch_seq(text, seq)
            except Exception as exc:  # recorded, not raised, off the main thread
                failures.append(exc)

        older = threading.Thread(target=send, args=("older", 3))
        older.start()
        newer = None
        try:
            self.assertTrue(started.wait(timeout=5), "the first write never began")
            newer = threading.Thread(target=send, args=("newer", 7))
            newer.start()
            # Bounded, and its result is not asserted: under a correct lock
            # the newer write cannot land yet and this simply runs out,
            # which is the point of waiting on the file rather than sleeping.
            self.wait_until(lambda: self.session.draft_path(1).exists(), timeout=0.5)
        finally:
            release.set()
            for thread in (older, newer):
                if thread is not None:
                    thread.join(timeout=10)
                    self.assertFalse(thread.is_alive(), "a PATCH never finished")
        self.assertEqual(failures, [])
        self.assertEqual(self.draft(), "newer")

    def test_the_newest_keystroke_survives_whatever_order_they_land_in(self):
        """The property, rather than the two orderings that demonstrate it.

        Twenty overlapping PATCHes with shuffled sequence numbers, against a
        ThreadingHTTPServer that really does run them at once. Whatever order
        they arrive in, the file has to end up holding the highest seq: the
        comparison and the write it guards are one step under one lock, so
        nothing lower can land after something higher.
        """
        import random

        order = list(range(1, 21))
        random.Random(20260825).shuffle(order)
        failures = []

        def send(seq):
            try:
                self.patch_seq("seq {}".format(seq), seq)
            except Exception as exc:  # recorded, not raised, off the main thread
                failures.append(exc)

        threads = [threading.Thread(target=send, args=(seq,)) for seq in order]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive(), "a PATCH never finished")
        self.assertEqual(failures, [])
        self.assertEqual(self.draft(), "seq 20")
        self.assertEqual(self.server.draft_seq(1), 20)


class WriteGateTest(WriteTestCase):
    """The gate the shutdown drain is built on.

    daemon_threads = True, so server_close() joins nothing and a handler
    inside write_json_atomic outlives the server that accepted it. The
    shutdown path has to be able to say "no more writes" and then wait for
    the ones already started, and _store is the only place this server writes
    anything, so that is where the gate is.
    """

    def test_a_fresh_server_is_open_for_writes(self):
        self.assertFalse(self.server.writes_closed)
        self.assertEqual(self.server.writes_in_flight, 0)
        self.assertEqual(self.server.refused_writes, 0)

    def test_a_finished_write_leaves_nothing_in_flight(self):
        self.post({"round": 1, "answers": {}})
        self.assertEqual(self.server.writes_in_flight, 0)

    def test_a_failed_write_leaves_nothing_in_flight(self):
        """The mutant that matters: end_write outside the finally. Every
        failed write would then leak a slot, and every later drain would
        time out on a write that finished minutes ago."""
        blocked = _UnwritableSession(self._tmp.name)
        (blocked.craft_dir / "wall").write_text("not a directory", encoding="utf-8")
        self.server.session = blocked
        self.rejected("POST", "/api/submit", {"round": 1, "answers": {}})
        self.assertEqual(self.server.writes_in_flight, 0)
        self.assertTrue(self.server.drain_writes(1.0))

    def test_a_closed_gate_refuses_a_write_and_writes_nothing(self):
        before = self.written()
        self.server.close_writes()
        error = self.rejected("POST", "/api/submit", {"round": 1, "answers": {}})
        self.assertEqual(error.code, 503)
        body = error.read().decode("utf-8", "replace")
        self.assertNotIn('"ok": true', body.lower())
        self.assertNamesNoPath(body)
        self.assertEqual(self.written(), before)
        self.assertEqual(self.server.refused_writes, 1)

    def test_a_closed_gate_refuses_an_autosave_too(self):
        self.server.close_writes()
        self.assertEqual(
            self.rejected("PATCH", "/api/draft", {"round": 1, "answers": {}}).code, 503)
        self.assertFalse(self.session.draft_path(1).exists())

    def test_a_closed_gate_still_serves_reads(self):
        """Shutting the gate must not turn the page into a 503 while the
        drain finishes -- a browser mid-poll should see the session end, not
        an error it will report as a bug."""
        self.server.close_writes()
        self.assertEqual(self.get("/").status, 200)
        self.assertEqual(self.get("/api/round").status, 200)

    def test_draining_an_idle_server_returns_at_once(self):
        started = time.monotonic()
        self.assertTrue(self.server.drain_writes(30.0))
        self.assertLess(time.monotonic() - started, 5)

    def test_draining_shuts_the_gate(self):
        self.server.drain_writes(1.0)
        self.assertTrue(self.server.writes_closed)
        self.assertEqual(
            self.rejected("POST", "/api/submit", {"round": 1, "answers": {}}).code, 503)

    def test_a_drain_waits_for_a_slot_that_is_still_out(self):
        self.assertTrue(self.server.begin_write())
        started = time.monotonic()
        self.assertFalse(self.server.drain_writes(0.3))
        self.assertGreaterEqual(time.monotonic() - started, 0.3)
        self.server.end_write()

    def test_a_drain_returns_the_moment_the_last_slot_comes_back(self):
        self.assertTrue(self.server.begin_write())
        threading.Timer(0.2, self.server.end_write).start()
        started = time.monotonic()
        self.assertTrue(self.server.drain_writes(30.0))
        self.assertLess(time.monotonic() - started, 10, "the drain slept out its timeout")

    def test_a_negative_timeout_does_not_hang(self):
        self.assertTrue(self.server.begin_write())
        self.assertFalse(self.server.drain_writes(-1))
        self.server.end_write()

    def test_the_gate_counts_every_writer(self):
        self.assertTrue(self.server.begin_write())
        self.assertTrue(self.server.begin_write())
        self.assertEqual(self.server.writes_in_flight, 2)
        self.server.end_write()
        self.assertEqual(self.server.writes_in_flight, 1)
        self.assertFalse(self.server.drain_writes(0.05))
        self.server.end_write()
        self.assertTrue(self.server.drain_writes(5.0))


# ---------------------------------------------------------------------------
# The page itself. Three layers, because no one of them can carry it alone.
#
#   PageContractTest      reads the served source. Cheap, always runs, and
#                         proves only that the text says what it should.
#   AnswerStateMirrorTest runs the page's own answerState in node against
#                         schema.answer_state. Real behaviour; skipped where
#                         node is absent.
#   RenderedPageTest      loads the page in a headless browser and reads the
#                         DOM the page built. Real behaviour, end to end;
#                         skipped where no browser is installed.
#
# unittest DOES report a skip -- an `s` in the dot stream and `OK (skipped=N)`
# on the last line -- so a machine running the string layer only says so, and
# nothing here needs a mechanism to make it say so. What IS lossy is the
# shape of the skip: RenderedPageTest and DrivenPageTest raise SkipTest in
# setUpClass, so each collapses its whole class into a single `s`. A reader
# counting skips is counting classes, not tests, and the number is smaller
# than the coverage that went missing. Read it here: with neither node nor a
# browser installed, the string layer is all that runs, and the string layer
# cannot catch a syntax error in the page's script.
# ---------------------------------------------------------------------------

# The markers app.html puts around the one function that has a Python twin.
# Slicing the real file is what makes the differential test differential: a
# copy of the function in this file would pass for ever while the page rotted.
MIRROR_BEGIN = "// ---- mirror of schema.answer_state: begin ----"
MIRROR_END = "// ---- mirror of schema.answer_state: end ----"

# An assignment to innerHTML or outerHTML, however it is spelled. This was
# `\.(inner|outer)HTML\s*=`, and `h3.innerHTML += q.title` -- a second
# injection sink, reachable from a title the agent wrote into a JSON file --
# passed it, caught only by the browser layer, which is the layer that skips.
# So: the dot form and the bracket form that reaches the same setter without
# ever writing a dot, plain `=` and every compound assignment, and never a
# comparison.
HTML_SINK = re.compile(
    r"""(?:\.\s*|\[\s*["'`]\s*)(?:inner|outer)HTML(?:\s*["'`]\s*\])?\s*"""
    r"""(?:\*\*|<<|>>>?|\|\||&&|\?\?|[-+*/%&|^])?=(?!=)"""
)

# Every browser name that would do. The test skips rather than fails when none
# of them is installed: a laptop with no chromium must not turn red.
BROWSERS = ("chromium", "chromium-browser", "google-chrome",
            "google-chrome-stable", "chrome")


def find_browser():
    for name in BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    return None


def run_headless(browser, url, budget=8000):
    """One headless chromium run over `url`, returning what it printed.

    --user-data-dir is a throwaway on purpose: the URL carries the session
    key, and the default profile would keep it in a history file.

    `budget` is VIRTUAL milliseconds, not wall clock. The clock runs as fast
    as the page will let it and pauses while a fetch is outstanding, so a
    page that waits four seconds for its own autosave costs a few
    milliseconds of real time -- and a test may not coordinate with the
    browser by sleeping in Python, because the two clocks are unrelated. The
    tests that need the server to change under a running page do it from
    inside a request handler instead.
    """
    with tempfile.TemporaryDirectory() as profile:
        return subprocess.run(
            [browser, "--headless", "--no-sandbox", "--disable-gpu",
             "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--user-data-dir=" + profile,
             "--virtual-time-budget={}".format(budget), "--dump-dom", url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
        )


class PageContractTest(ServerTestCase):
    """The page's wiring contract: it is self-contained, it exposes the mount
    points Task 11 attaches to, and it references the endpoints it depends on.

    These assert on the served source, so they catch a deleted mount point, a
    renamed hook, or a smuggled-in CDN script. They do NOT prove the page
    behaves -- a page whose script throws on line one passes every one of
    them. That is what the two classes below are for.
    """

    def page(self):
        return self.get("/").read().decode("utf-8")

    def test_the_page_is_self_contained(self):
        html = self.page()
        self.assertNotIn("<script src=", html)
        self.assertNotIn("https://", html.split("</head>")[0])

    def test_the_page_has_every_mount_point(self):
        html = self.page()
        for element_id in ("questions", "brief", "ledger", "filters",
                           "counts", "send", "finish", "overlay", "waiting"):
            self.assertIn('id="{}"'.format(element_id), html)

    def test_the_page_declares_the_four_importance_levels(self):
        html = self.page()
        for level in ("REQUIRED", "IMPORTANT", "PREFERENCE", "OPTIONAL"):
            self.assertIn(level, html)

    def test_the_page_offers_delegation_and_notes(self):
        """Assert on the writer, not on the reader.

        `data-note` appears twice in this page -- on the input that creates
        the field and on the querySelector that reads it back -- so deleting
        the note input from every card left the two loose assertions below
        green while removing one of the two things the brief insisted on.
        The rest of this test names the calls that BUILD them.
        """
        html = self.page()
        self.assertIn("you decide", html)
        self.assertIn("data-note", html)
        # The note input, at the point questionCard builds it.
        self.assertIn('"data-note": "1"', html)
        self.assertIn('placeholder: "Note', html)
        # ...and the delegate button, likewise. A reader of either would be
        # satisfied by the querySelector that goes looking for one.
        self.assertIn('class: "delegate"', html)
        self.assertIn('text: "you decide"', html)

    def test_contradictions_link_to_the_questions_they_are_between(self):
        html = self.page()
        self.assertIn('"#q-" + ref', html)
        self.assertIn("c.between", html)

    def test_the_page_exports_the_hooks_task_11_calls(self):
        html = self.page()
        for name in ("function renderRound(", "function applyFilter(",
                     "function collectAnswers("):
            self.assertIn(name, html)

    def test_the_only_innerhtml_is_the_server_rendered_brief(self):
        """A lint, and the most valuable one here.

        markdown.py escapes before it transforms and allowlists link schemes,
        so the brief is the one string on this page that may be assigned as
        HTML. Everything else -- a question title, an option label, a line of
        the ledger -- is text the agent wrote into a JSON file, and a second
        innerHTML is how it stops being text.
        """
        # Comment lines are dropped first: this file explains the rule in
        # prose beside the one line that keeps it, and a lint that cannot
        # tell an explanation from an assignment is a lint nobody can write
        # a comment near.
        code = "\n".join(line for line in self.page().splitlines()
                         if not line.strip().startswith("//"))
        assigns = [line.strip() for line in code.splitlines()
                   if HTML_SINK.search(line)]
        self.assertEqual(len(assigns), 1, assigns)
        self.assertIn("brief", assigns[0])
        for banned in ("insertAdjacentHTML", "document.write", "outerHTML"):
            self.assertNotIn(banned, code)

    # Every spelling of an assignment to innerHTML, and the reads and
    # comparisons that are not one. `+=` is here because it was the mutant
    # that walked past the first version of the lint.
    SINKS = (
        "node.innerHTML = x;",
        "node.innerHTML=x;",
        "h3.innerHTML += q.title;",
        "node . innerHTML = x;",
        'node["innerHTML"] = x;',
        "node['innerHTML'] += x;",
        'node[ "innerHTML" ] = x;',
        "node.outerHTML = x;",
        'node["outerHTML"] += x;',
        "node.innerHTML ||= x;",
        "node.innerHTML ??= x;",
    )
    NOT_SINKS = (
        'if (node.innerHTML === "") return;',
        "const held = node.innerHTML;",
        "const same = a.innerHTML == b.innerHTML;",
        "node.textContent = x;",
        'const key = "innerHTML";',
    )

    def test_the_innerhtml_lint_catches_every_spelling_of_the_sink(self):
        """Teeth for the lint above, which is the only always-running defence
        against a second injection sink: the browser layer that would also
        catch one is the layer that skips when chromium is absent."""
        for line in self.SINKS:
            self.assertTrue(HTML_SINK.search(line), line)
        for line in self.NOT_SINKS:
            self.assertIsNone(HTML_SINK.search(line), line)

    def test_every_fetch_carries_the_session_key(self):
        """There is no cookie -- see the module docstring -- so a fetch that
        forgets the key is a 403 the user sees as an empty panel. api() is the
        only thing that appends it, so every fetch must go through it."""
        calls = re.findall(r"fetch\(\s*([^\s,)]+)", self.page())
        self.assertTrue(calls, "no fetch call found at all")
        for call in calls:
            self.assertTrue(call.startswith("api("), call)

    def test_the_page_does_not_erase_the_key_from_its_own_url(self):
        """history.replaceState tidying the key away looks like hygiene and
        costs the user every reload: there is no cookie to fall back on."""
        self.assertNotIn("replaceState", self.page())


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class AnswerStateMirrorTest(unittest.TestCase):
    """The page's answerState against schema.answer_state, case for case.

    This is the one piece of the page with a Python twin, and the twin decides
    what the agent is told the user meant. The two must agree on every shape a
    draft file can hold -- and a draft file is JSON on disk that a person may
    have hand-edited, so "the page only ever writes strings and arrays" is not
    a defence.

    The function is sliced out of the real app.html between the markers above
    and run in node. What this does NOT cover: everything else on the page.
    """

    @classmethod
    def setUpClass(cls):
        source = APP_HTML.read_text(encoding="utf-8")
        begin = source.find(MIRROR_BEGIN)
        end = source.find(MIRROR_END)
        if begin < 0 or end < 0:
            raise AssertionError(
                "app.html no longer marks the mirror of schema.answer_state; "
                "the markers are {!r} and {!r}".format(MIRROR_BEGIN, MIRROR_END)
            )
        cls.mirror = source[begin:end]

    HARNESS = """
const chunks = [];
process.stdin.on("data", (c) => chunks.push(c));
process.stdin.on("end", () => {
  const cases = JSON.parse(chunks.join(""));
  const out = cases.map((c) => {
    try { return answerState(c); }
    catch (e) { return "threw " + e.constructor.name + ": " + e.message; }
  });
  process.stdout.write(JSON.stringify(out));
});
"""

    def states(self, cases):
        """What the page's answerState says about each case."""
        script = self.mirror + "\n" + self.HARNESS
        proc = subprocess.run(
            ["node", "-e", script],
            input=json.dumps(cases).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
        )
        self.assertEqual(
            proc.returncode, 0,
            "node refused the page's answerState: {}".format(
                proc.stderr.decode("utf-8", "replace")),
        )
        return json.loads(proc.stdout.decode("utf-8"))

    def assertMirrors(self, cases):
        got = self.states(cases)
        self.assertEqual(len(got), len(cases))
        for case, state in zip(cases, got):
            with self.subTest(answer=case):
                self.assertEqual(state, schema.answer_state(case))

    # The cases test_schema.py pins, restated here so that the JS is held to
    # the same line rather than to a looser one somebody wrote for it.
    NAMED_CASES = [
        None, "yes", ["email"], {}, 0, False, True, 1.5, "",
        {"skipped": True},
        {"delegated": True},
        {"delegated": True, "choice": ["a"]},
        {"delegated": True, "skipped": True},
        {"delegated": True, "text": "maybe email"},
        {"delegated": False, "text": "yes"},
        {"delegated": "yes", "text": "email"},
        {"delegated": 1},
        {"skipped": False, "choice": ["a"]},
        {"skipped": "true", "text": "email"},
        {"skipped": True, "text": "old draft"},
        {"skipped": True, "choice": ["a"]},
        {"choice": ["email"]},
        {"choice": []},
        {"choice": "email"},
        {"choice": "   "},
        {"choice": ""},
        {"choice": [""]},
        {"choice": ["", "   ", "\n\t"]},
        {"choice": ["", "email"]},
        {"choice": ["email", ""]},
        {"choice": [""], "other": "passkeys"},
        {"choice": 0},
        {"choice": {"value": "email"}},
        {"choice": [None]},
        {"choice": [0]},
        {"choice": [False]},
        {"choice": [{"value": "email"}]},
        {"text": "yes"},
        {"text": "   "},
        {"text": ""},
        {"text": "0"},
        {"text": 0},
        {"text": False},
        {"text": True},
        {"text": ["yes"]},
        {"text": {"a": 1}},
        {"other": "   "},
        {"other": 7},
        {"note": "thinking about it"},
        {"note": "   "},
        {"note": "x", "choice": ["a"]},
        {"choice": [], "other": "passkeys"},
        # The six codepoints str.strip() and String.prototype.trim() disagree
        # about, one per line so that a failure names the one that moved.
        # U+001C-001F and U+0085 are blank to Python and content to
        # JavaScript; U+FEFF is the reverse. Nothing the page can type
        # reaches them -- collectAnswers trims -- but a hand-edited or
        # agent-written draft is read by the same two functions, which is
        # what this whole class is about.
        {"text": "\u001c"},
        {"text": "\u001d"},
        {"text": "\u001e"},
        {"text": "\u001f"},
        {"text": "\u0085"},
        {"text": "\ufeff"},
        {"other": "\u0085"},
        {"other": "\ufeff"},
        {"choice": "\u001c"},
        {"choice": "\ufeff"},
        {"choice": ["\u001f"]},
        {"choice": ["\ufeff"]},
        {"choice": ["\u0085", "\u001c"]},
        {"choice": ["\u001c", "email"]},
        {"text": "\ufeffemail"},
        {"text": "email\u0085"},
    ]

    def test_the_named_cases_agree(self):
        self.assertMirrors(self.NAMED_CASES)

    def test_a_thousand_generated_answers_agree(self):
        """Seeded, so a disagreement is reproducible and is not a flake.

        The generator is the point: the three divergences a review found in
        this function were all shapes nobody thought to write a case for.
        """
        rng = random.Random(20260826)
        # Every value here used to be ASCII, which made the whitespace
        # divergence unreachable by construction: the two functions disagree
        # on six codepoints and not one of them could ever be generated. A
        # corpus that cannot express the bug cannot find it in a thousand
        # tries or in a million.
        values = [None, True, False, 0, 1, "", "   ", "\n\t", "email", "0",
                  "\u001c", "\u001d", "\u001e", "\u001f", "\u0085", "\ufeff",
                  "\ufeff email", "email\u001e", "\u0085\ufeff",
                  [], [""], ["email"], ["", "email"], ["email", None], [None],
                  ["\u001c"], ["\ufeff"], ["\u0085", ""], ["\u001f", "email"],
                  [0], [{"value": "email"}], {"value": "email"}, {}, 1.5]
        keys = ["choice", "text", "other", "note", "delegated", "skipped",
                "answered", "value"]
        cases = []
        for _ in range(1000):
            case = {}
            for key in keys:
                if rng.random() < 0.4:
                    case[key] = rng.choice(values)
            cases.append(case)
        self.assertMirrors(cases)

    def test_the_harness_would_notice_a_divergence(self):
        """Teeth. If the slice ever came back empty, or node quietly returned
        the same string for everything, every assertion above would pass."""
        got = self.states([{"delegated": True}, {"text": "yes"}, {}])
        self.assertEqual(got, ["delegated", "answered", "skipped"])


class RenderedPageTest(ServerTestCase):
    """The page in a real browser, reading back the DOM it built.

    Everything here is downstream of the script having run at all, so this is
    the layer that catches a syntax error, a fetch that forgot the key, and a
    title the page wrote as HTML instead of as text. It is skipped when no
    browser is installed, which is a hole -- see the note at the top of this
    section.

    Not covered: anything needing a click. The importance filter, the "you
    decide" latch and the counter's response to typing are verified by hand.
    """

    HOSTILE = '<img src=x onerror="document.title=\'pwned\'">'

    ROUND = {
        "round": 1,
        "project": "music-app",
        "questions": [
            {"id": "Q-1", "importance": "REQUIRED", "area": "Accounts",
             "title": "How should users authenticate?",
             "why": "Decides onboarding, recovery and identity for good.",
             "type": "single", "allow_other": True,
             "options": [
                 {"value": "email", "label": "Email and password",
                  "detail": "Simplest. Needs a reset flow."},
                 {"value": "magic", "label": "Magic link",
                  "detail": "No passwords. Needs outbound email."}]},
            {"id": "Q-2", "importance": "OPTIONAL", "area": "Accounts",
             "title": HOSTILE, "type": "longtext"},
        ],
        "ledger": {
            "contradictions": [
                {"id": "CON-002", "between": ["Q-1", "Q-404"],
                 "text": "Offline-first conflicts with streaming-only."}],
            "decisions": [{"id": "DEC-014", "title": "Playlists are private"}],
        },
    }

    @classmethod
    def setUpClass(cls):
        cls.browser = find_browser()
        if not cls.browser:
            raise unittest.SkipTest("no chromium or chrome on this machine")

    def dump_dom(self):
        """The DOM after the page's script has run and its fetches returned."""
        proc = run_headless(self.browser, self.url("/"))
        self.assertEqual(
            proc.returncode, 0,
            "the browser failed: {}".format(proc.stderr.decode("utf-8", "replace")))
        return proc.stdout.decode("utf-8", "replace")

    def rendered(self):
        """The dumped DOM with the page's own source removed.

        This is not tidying. --dump-dom includes the <script> element's text,
        so "No questions yet" -- a string the script CONTAINS -- was found in
        the dump of a page whose script had a syntax error and never ran. An
        assertion that a string appears somewhere in a file is not an
        assertion that a browser built it, and every check below is only
        worth writing if it can tell those two apart.
        """
        dom = self.dump_dom()
        cleaned = re.sub(r"(?s)<script>.*?</script>", "<script></script>", dom)
        cleaned = re.sub(r"(?s)<style>.*?</style>", "<style></style>", cleaned)
        return re.sub(r"(?s)<!--.*?-->", "", cleaned)

    def test_the_reader_cannot_see_the_page_source(self):
        """Teeth for rendered(). These three strings exist in app.html and
        nowhere in the DOM a working page builds; if any of them survives,
        every assertion in this class has stopped meaning anything.

        A round is posted first so that "No questions yet" is a string the
        working page does NOT build -- which is the state the syntax-error
        mutant was caught in."""
        write_json_atomic(self.session.questions_path(1), self.ROUND)
        cleaned = self.rendered()
        for source_only in ("function renderRound(", "addEventListener",
                            "No questions yet"):
            self.assertNotIn(source_only, cleaned, source_only)

    def test_a_round_becomes_cards_a_ledger_and_a_brief(self):
        write_json_atomic(self.session.questions_path(1), self.ROUND)
        self.session.brief_path.write_text(
            "# Vision\n\nA small music player.\n\n- local files\n",
            encoding="utf-8")
        dom = self.rendered()

        # The script ran, the fetch carried the key, and renderRound built
        # cards. None of this is reachable without all three.
        self.assertIn('id="q-Q-1"', dom)
        self.assertIn("How should users authenticate?", dom)
        self.assertIn("Decides onboarding, recovery and identity for good.", dom)
        self.assertIn('value="magic"', dom)
        self.assertIn("Needs outbound email.", dom)
        self.assertIn("you decide", dom)
        self.assertIn('data-importance="OPTIONAL"', dom)

        # The contradiction pins to the top of the ledger and links to the
        # question it is between -- and not to the one that is not on the page.
        self.assertIn('href="#q-Q-1"', dom)
        self.assertIn("Offline-first conflicts with streaming-only.", dom)
        self.assertNotIn("#q-Q-404", dom)
        self.assertIn("DEC-014", dom)

        # The brief is the one thing rendered as HTML, and it did render.
        self.assertIn("<h1>Vision</h1>", dom)
        self.assertIn("<li>local files</li>", dom)

        # The counter ran, which means answerState and the round agreed.
        self.assertIn("0 answered", dom)
        self.assertIn("1 REQUIRED", dom)

    def test_a_question_title_is_never_parsed_as_html(self):
        """The agent writes the round file; the page must treat every string
        in it as text. A title is the shortest path from a JSON file in the
        project to script execution in a page holding the session key."""
        write_json_atomic(self.session.questions_path(1), self.ROUND)
        dom = self.rendered()
        # The escaped text is allowed to READ like an attack -- that is what
        # inert means. What must not exist is the element: no <img> node, and
        # a document.title the injected handler never got to change.
        self.assertIn("&lt;img", dom)
        self.assertNotIn("<img", dom)
        self.assertIn("<title>craft</title>", dom)

    def test_the_brief_is_escaped_before_it_is_rendered(self):
        """innerHTML is used on exactly one string. markdown.py escapes it
        first; this is the end-to-end proof that it does, in a browser."""
        write_json_atomic(self.session.questions_path(1), self.ROUND)
        self.session.brief_path.write_text(
            "# Vision\n\n<script>document.title='pwned'</script>\n",
            encoding="utf-8")
        raw = self.dump_dom()
        dom = re.sub(r"(?s)<!--.*?-->", "", raw)
        self.assertIn("&lt;script&gt;", dom)
        # One <script> element in the document: the page's own. The brief's
        # is text inside #brief, and text does not run.
        self.assertEqual(dom.count("<script>"), 1)
        self.assertIn("<title>craft</title>", dom)

    def test_an_unreadable_round_is_shown_to_the_user_not_swallowed(self):
        """The failure the agent causes most often: a half-written or
        hand-edited round file. A blank page would be indistinguishable from
        'no questions yet', and the user would sit and wait for ever."""
        self.session.questions_path(1).write_text("{not json", encoding="utf-8")
        dom = self.rendered()
        self.assertIn("is not valid JSON", dom)
        # ...and the panel beside it says what it is, for the same reason.
        # The error path wrote into #questions and left the Ledger an empty
        # box -- next to a message saying the round could not be read, which
        # is exactly where a reader starts wondering what else is broken.
        self.assertIn("Nothing recorded yet.", dom)

    def test_no_round_yet_says_so(self):
        """An empty .craft/ is the state the page opens in, and a blank panel
        would be indistinguishable from a page that failed to load."""
        dom = self.rendered()
        self.assertIn("No questions yet", dom)
        self.assertIn("Nothing recorded yet.", dom)


# The driver appended to a copy of the page. It runs after the page's own
# script, waits for renderRound to have built the cards -- loadRound is a
# fetch, so the first tick is always too early -- runs the test's body, and
# leaves the result where --dump-dom can read it back. A throw is RECORDED
# rather than lost: an error nobody sees is the failure this whole class was
# added for, and a driver that swallowed one would be repeating it.
DRIVER = """
<pre id="probe"></pre>
<script>
(function () {
  const probe = document.getElementById("probe");
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  // Waits on the page's OWN clock. Under --virtual-time-budget that clock
  // runs far faster than wall time and pauses while a fetch is outstanding,
  // so this both settles quickly and never observes a half-finished round
  // trip. It returns what the predicate returned, or null on the deadline.
  const waitFor = async (predicate, ms) => {
    const deadline = Date.now() + (ms || 4000);
    for (;;) {
      const value = predicate();
      if (value) return value;
      if (Date.now() >= deadline) return null;
      await sleep(20);
    }
  };
  const run = () => {
// DRIVER BODY
  };
  let tries = 0;
  const step = () => {
    if (!document.querySelector("#questions .question") && tries++ < 80) {
      setTimeout(step, 25);
      return;
    }
    let value;
    try {
      value = run();
    } catch (e) {
      probe.textContent = JSON.stringify({ driverError: String(e) });
      return;
    }
    // Promise.resolve so a body may be `return (async () => {...})()`. A
    // synchronous body is unaffected, and a rejection is RECORDED: an error
    // nobody sees is the failure this whole class was added for.
    Promise.resolve(value).then(
      (settled) => { probe.textContent = JSON.stringify({ ok: settled }); },
      (e) => { probe.textContent = JSON.stringify({ driverError: String(e) }); });
  };
  step();
})();
</script>
"""


class DrivenTestCase(ServerTestCase):
    """The machinery for driving the real page: a copy of app.html, byte for
    byte, with a driver appended that presses things and records what the
    page then produced. Subclasses supply a ROUND and the bodies.
    """

    ROUND = None
    BUDGET = 8000

    @classmethod
    def setUpClass(cls):
        cls.browser = find_browser()
        if not cls.browser:
            raise unittest.SkipTest("no chromium or chrome on this machine")

    def drive(self, body, round_obj=None, budget=None):
        """Serve the page with `body` appended as a driver, and return what
        it recorded."""
        write_json_atomic(self.session.questions_path(1),
                          self.ROUND if round_obj is None else round_obj)
        source = APP_HTML.read_text(encoding="utf-8")
        self.assertEqual(source.count("</body>"), 1, "cannot place the driver")
        pages = tempfile.TemporaryDirectory()
        self.addCleanup(pages.cleanup)
        page = Path(pages.name) / "driven.html"
        page.write_text(
            source.replace("</body>",
                           DRIVER.replace("// DRIVER BODY", body) + "</body>"),
            encoding="utf-8")
        server_module.APP_HTML = page
        self.addCleanup(setattr, server_module, "APP_HTML", APP_HTML)

        proc = run_headless(self.browser, self.url("/"),
                            self.BUDGET if budget is None else budget)
        self.assertEqual(
            proc.returncode, 0,
            "the browser failed: {}".format(proc.stderr.decode("utf-8", "replace")))
        dom = proc.stdout.decode("utf-8", "replace")
        found = re.search(r'(?s)<pre id="probe">(.*?)</pre>', dom)
        self.assertIsNotNone(found, "the driven page built no probe at all")
        recorded = unescape(found.group(1))
        self.assertTrue(recorded, "the driver never ran: the page's own script threw")
        result = json.loads(recorded)
        self.assertNotIn("driverError", result, result)
        return result["ok"]


class DrivenPageTest(DrivenTestCase):
    """The page after something has been clicked, which --dump-dom cannot see.

    chromium's headless dump renders a page and prints the DOM; it does not
    interact with one. The alternative was a browser-automation dependency in
    a tool whose whole pitch is the standard library, so the server is instead
    pointed at a COPY of app.html -- the real file, byte for byte, with the
    driver above appended -- which clicks what a user would click and writes
    what the page then produced into a node the dump reads back. The page's
    own script is the one under test; the driver only presses things.

    What that buys is the three failures no other layer here can see. A
    delegate latch that never sets aria-pressed ships {skipped: true} for a
    question the user believes they handed over, so it is ASKED AGAIN -- the
    exact opposite of a Delegated Decision, and invisible without opening the
    draft file. A delegated answer that quietly loses its note drops the one
    sentence saying why Claude was handed the decision. And a ledger the page
    could not render used to take the counter and the filter down with it.
    """

    ROUND = {
        "round": 1,
        "questions": [
            {"id": "Q-1", "importance": "REQUIRED", "title": "How should users authenticate?",
             "type": "single",
             "options": [{"value": "email"}, {"value": "magic"}]},
            {"id": "Q-2", "importance": "OPTIONAL", "title": "Anything else?",
             "type": "text"},
        ],
    }

    LATCH = """
    const card = document.querySelector('.question[data-id="Q-1"]');
    const button = card.querySelector(".delegate");
    const before = collectAnswers()["Q-1"];
    button.click();
    return {
      before: before,
      pressed: button.getAttribute("aria-pressed"),
      delegated: card.dataset.delegated,
      after: collectAnswers()["Q-1"],
      counts: document.getElementById("counts").textContent,
      hint: getComputedStyle(card.querySelector(".hint")).display,
    };
    """

    def test_the_delegate_latch_records_a_delegated_answer(self):
        """A latch that never sets aria-pressed leaves collectAnswers reading
        `false` and posting {skipped: true} for a question the user believes
        they handed over. Claude then asks it again, and nothing anywhere on
        the page says the button did not take."""
        got = self.drive(self.LATCH)
        self.assertEqual(got["before"], {"skipped": True})
        self.assertEqual(got["pressed"], "true")
        self.assertEqual(got["delegated"], "true")
        self.assertEqual(got["after"], {"delegated": True})
        # The counter is the only feedback the press produced, and the hint
        # is the only thing on the card that says what the state means.
        self.assertIn("1 answered", got["counts"])
        self.assertEqual(got["hint"], "inline")

    NOTE = """
    const cards = ["Q-1", "Q-2"].map(
      (id) => document.querySelector('.question[data-id="' + id + '"]'));
    const note = cards[0].querySelector("[data-note]");
    note.value = "  budget, not taste  ";
    cards.forEach((card) => card.querySelector(".delegate").click());
    return { withNote: collectAnswers()["Q-1"], without: collectAnswers()["Q-2"] };
    """

    def test_a_delegated_answer_carries_the_note_written_beside_it(self):
        """Replacing the delegated answer with a bare {delegated: true} left
        every other layer green. The note is the sentence that tells Claude
        WHY it was handed the decision, and dropping it would be the only
        deletion this page makes on the user's behalf -- so it is pinned, and
        so is its absence when nothing was written."""
        got = self.drive(self.NOTE)
        self.assertEqual(got["withNote"],
                         {"delegated": True, "note": "budget, not taste"})
        self.assertEqual(got["without"], {"delegated": True})

    LEDGER = """
    const questions = currentRound.questions;
    const filter = document.querySelector('#filters button[data-level="OPTIONAL"]');
    // The fifth shape is the one renderLedger cannot be written to survive:
    // reading the property is what throws. No JSON file holds this, and that
    // is the point -- it is the only way to ask, from inside the page,
    // whether the SECOND lock works when the first one has been defeated.
    const unreadable = {};
    Object.defineProperty(unreadable, "contradictions", {
      enumerable: true,
      get() { throw new Error("a ledger this page cannot even read"); },
    });
    const shapes = [
      { contradictions: "CON-002 conflicts with DEC-014" },
      { decisions: "DEC-014" },
      { assumptions: { "ASM-1": "guessed" } },
      { contradictions: [{ id: "CON-002", text: "conflict", between: "Q-1" }] },
      unreadable,
    ];
    return shapes.map((ledger) => {
      renderRound({ round: 1, questions: questions, ledger: ledger });
      const optional = document.querySelector('.question[data-id="Q-2"]');
      filter.click();
      const hiddenNow = optional.classList.contains("hidden");
      filter.click();
      return {
        counts: document.getElementById("counts").textContent,
        ledger: document.getElementById("ledger").textContent,
        hiddenNow: hiddenNow,
        shownAgain: !optional.classList.contains("hidden"),
      };
    });
    """

    def test_a_mistyped_ledger_leaves_the_counter_and_the_filter_working(self):
        """The finding this round exists for.

        Four ledger shapes threw inside renderLedger, and the throw escaped
        before applyFilter and updateCounts ran -- so the counter stayed blank
        for the whole hour and the filter never applied, on a page whose cards
        had rendered and looked entirely fine. loadRound is fire-and-forget,
        so it surfaced as an unhandled rejection nobody sees.

        The server now rejects all four before serving them, which is why
        this drives renderRound directly: the server is not the page's only
        caller, and a panel must not be able to cost the page its controls.

        The panel text is asserted too, and that is the half that tells the
        two locks apart. renderLedger being total gives "Nothing recorded
        yet."; renderLedger throwing and showLedger catching gives the
        apology instead; and a driverError -- which drive() refuses -- means
        the throw escaped both and reached renderRound's caller.
        """
        got = self.drive(self.LEDGER)
        self.assertEqual(len(got), 5)
        for index, result in enumerate(got):
            with self.subTest(shape=index):
                self.assertTrue(result["counts"].startswith("0 answered"), result)
                self.assertIn("1 REQUIRED", result["counts"])
                self.assertTrue(result["hiddenNow"], result)
                self.assertTrue(result["shownAgain"], result)
        # Three of the shapes carry nothing renderable, so the panel says so.
        for index in (0, 1, 2):
            self.assertEqual(got[index]["ledger"], "Nothing recorded yet.")
        # The fourth carries a real contradiction beside its bad `between`,
        # and the contradiction still renders: guarding is not discarding.
        self.assertIn("CON-002", got[3]["ledger"])
        self.assertIn("conflict", got[3]["ledger"])
        # The fifth is the one renderLedger cannot survive, so showLedger
        # catches it and the panel apologises -- while the counter and the
        # filter, which are the page itself, carry on above.
        self.assertEqual(got[4]["ledger"], "The ledger could not be shown.")


# ---------------------------------------------------------------------------
# Task 11: the page made live. Autosave, Send, Finish, draft restore, the
# between-rounds state and the connection overlay.
#
# The source lint below always runs and proves only that the text says what it
# should. Everything that decides whether a user's hour of thinking survives is
# in LivePageTest, which drives the real page against this real server and then
# reads the files off the disk -- because "the draft was saved" is a claim
# about a file, and no assertion about the DOM is one.
# ---------------------------------------------------------------------------


class PageWiringContractTest(ServerTestCase):
    """Same contract-not-behaviour caveat as PageContractTest above."""

    def page(self):
        return self.get("/").read().decode("utf-8")

    def test_the_page_wires_autosave_to_the_draft_endpoint(self):
        html = self.page()
        self.assertIn("/api/draft", html)
        self.assertIn('method: "PATCH"', html)

    def test_the_page_wires_both_submit_paths(self):
        html = self.page()
        self.assertIn("/api/submit", html)
        self.assertIn("submit(false)", html)
        self.assertIn("submit(true)", html)

    def test_the_page_wires_the_next_round_poll(self):
        self.assertIn("pollForNextRound", self.page())

    def test_finish_is_wired_through_a_confirmation(self):
        self.assertIn("confirm(", self.page())

    def test_autosave_carries_a_sequence_number(self):
        """Overlapping autosaves are the normal case, not an edge one: every
        keystroke is its own connection and ThreadingHTTPServer runs them in
        parallel. `hello world` typed once was measured leaving `hel` on disk.
        do_PATCH orders them by `seq`, and only if the client sends one."""
        html = self.page()
        self.assertIn("saveSeq += 1", html)
        self.assertIn("seq: seq", html)

    def test_a_refused_save_is_not_reported_as_a_saved_one(self):
        """A 413 or a 400 resolves the fetch promise like any other response.
        A page that only catches rejections tells the user their work is safe
        while the server is refusing to store it."""
        html = self.page()
        self.assertIn("response.ok", html)
        self.assertIn("not saved", html)

    def test_finish_is_carried_as_a_boolean(self):
        """`finished` must be exactly true or false -- "false" is a 400 --
        and bool("false") is True, so the coercion has to happen here."""
        self.assertIn("finished: finished === true", self.page())


class LivePageTest(DrivenTestCase):
    """The page driven against the real server, with the disk as the witness.

    Every test here ends by reading a file the server wrote, because that file
    is the product: `.draft.json` is what a closed tab costs nothing against,
    and `.answers.json` is what the agent folds into CRAFT.md. A DOM that says
    "saved" over an empty directory is the failure this class exists to catch.
    """

    BUDGET = 20000

    ROUND = {
        "round": 1,
        "questions": [
            {"id": "Q-1", "importance": "REQUIRED",
             "title": "How should users authenticate?", "type": "single",
             "allow_other": True,
             "options": [{"value": "email"}, {"value": "magic"}]},
            {"id": "Q-2", "importance": "OPTIONAL", "title": "Anything else?",
             "type": "longtext"},
            {"id": "Q-3", "importance": "IMPORTANT", "title": "Who is it for?",
             "type": "text"},
        ],
    }

    # Typing, twice, waiting for the page to claim each one is saved.
    TYPE = """
    return (async () => {
      const status = document.getElementById("status");
      const field = document.querySelector('.question[data-id="Q-2"] [data-text]');
      const type = async (text) => {
        field.value = text;
        field.dispatchEvent(new Event("input", { bubbles: true }));
        const saved = await waitFor(() => status.textContent === "saved", 6000);
        return !!saved;
      };
      const first = await type("hel");
      const second = await type("hello world");
      return { first: first, second: second, status: status.textContent };
    })();
    """

    def test_typing_is_autosaved_to_the_draft_under_a_rising_seq(self):
        got = self.drive(self.TYPE)
        self.assertTrue(got["first"], got)
        self.assertTrue(got["second"], got)
        stored = read_json(self.session.draft_path(1))
        self.assertEqual(stored["round"], 1)
        self.assertEqual(stored["answers"]["Q-2"], {"text": "hello world"})
        # A constant seq is not a sequence: do_PATCH compares with >=, so a
        # client that sends 1 every time still writes every time and keeps
        # exactly the last-writer-wins bug seq was added to fix.
        self.assertGreaterEqual(stored["seq"], 2)
        # Nothing was submitted. One character in app.html separates the two.
        self.assertFalse(self.session.answers_path(1).exists())

    RESTORE = """
    return (async () => {
      const status = document.getElementById("status");
      await waitFor(() => status.textContent === "draft restored", 6000);
      const one = document.querySelector('.question[data-id="Q-1"]');
      const two = document.querySelector('.question[data-id="Q-2"]');
      const three = document.querySelector('.question[data-id="Q-3"]');
      return {
        status: status.textContent,
        checked: [...one.querySelectorAll("input[type=radio]")]
          .filter((i) => i.checked).map((i) => i.value),
        other: one.querySelector("[data-other]").value,
        note: one.querySelector("[data-note]").value,
        text: two.querySelector("[data-text]").value,
        pressed: two.querySelector(".delegate").getAttribute("aria-pressed"),
        delegated: two.dataset.delegated,
        hint: getComputedStyle(two.querySelector(".hint")).display,
        counts: document.getElementById("counts").textContent,
        threePressed: three.querySelector(".delegate").getAttribute("aria-pressed"),
        threeNote: three.querySelector("[data-note]").value,
      };
    })();
    """

    def test_a_saved_draft_is_restored_into_the_form(self):
        """The entire point of autosave. A draft that is written and never
        read back is a file nobody will ever see."""
        write_json_atomic(self.session.draft_path(1), {
            "round": 1,
            "answers": {
                "Q-1": {"choice": ["magic"], "other": "passkeys",
                        "note": "email, but I want passkeys later"},
                "Q-2": {"delegated": True},
                # Truthy, and not True. `if (answer.delegated)` would latch
                # this and manufacture a Delegated Decision the user never
                # made -- which is never asked again.
                "Q-3": {"delegated": "no", "note": "not a decision"},
            },
        })
        got = self.drive(self.RESTORE)
        self.assertEqual(got["checked"], ["magic"])
        self.assertEqual(got["other"], "passkeys")
        self.assertEqual(got["note"], "email, but I want passkeys later")
        self.assertEqual(got["text"], "")
        # A restored delegation must restore the WHOLE state, not just the
        # button: without data-delegated the card does not grey and the line
        # saying Claude decides this one is invisible, so a user who reloads
        # sees a pressed button and no explanation of it.
        self.assertEqual(got["pressed"], "true")
        self.assertEqual(got["delegated"], "true")
        self.assertEqual(got["hint"], "inline")
        # ...and a `delegated` that is merely truthy latches nothing, while
        # the note written beside it still comes back.
        self.assertEqual(got["threePressed"], "false")
        self.assertEqual(got["threeNote"], "not a decision")
        # The counter counts what was restored, not an empty form.
        self.assertIn("2 answered", got["counts"])
        # ...and the user is told their work came back, which is the only
        # visible difference between a restored form and a page that quietly
        # dropped the file.
        self.assertEqual(got["status"], "draft restored")

    SEND = """
    return (async () => {
      const card = document.querySelector('.question[data-id="Q-1"]');
      card.querySelector('input[value="email"]').checked = true;
      card.dispatchEvent(new Event("change", { bubbles: true }));
      document.getElementById("send").click();
      const waiting = document.getElementById("waiting");
      const shown = await waitFor(() => waiting.hasAttribute("data-on"), 6000);
      return {
        shown: !!shown,
        heading: waiting.querySelector("h2").textContent,
        sendDisabled: document.getElementById("send").disabled,
        problem: document.getElementById("problem").textContent,
      };
    })();
    """

    def test_send_writes_the_answers_and_moves_to_the_waiting_state(self):
        got = self.drive(self.SEND)
        self.assertTrue(got["shown"], got)
        self.assertIn("folding your answers in", got["heading"])
        self.assertTrue(got["sendDisabled"], got)
        self.assertEqual(got["problem"], "")
        submitted = read_json(self.session.answers_path(1))
        self.assertEqual(submitted["round"], 1)
        self.assertIs(submitted["finished"], False)
        self.assertEqual(submitted["answers"]["Q-1"], {"choice": ["email"]})
        self.assertEqual(submitted["answers"]["Q-2"], {"skipped": True})
        # POST never promotes the draft, so Send has to carry the answers in
        # its own body -- and it flushes the draft first, so a Send that
        # failed still leaves the work on the disk.
        self.assertEqual(read_json(self.session.draft_path(1))["answers"],
                         submitted["answers"])

    FINISH_DISMISSED = """
    return (async () => {
      let asked = null;
      window.confirm = (message) => { asked = message; return false; };
      document.getElementById("finish").click();
      await sleep(1500);
      return {
        asked: asked,
        waiting: document.getElementById("waiting").hasAttribute("data-on"),
        sendDisabled: document.getElementById("send").disabled,
      };
    })();
    """

    def test_finish_asks_first_and_a_dismissal_sends_nothing(self):
        """Finish ends the session. A confirm that is decorative -- or one
        whose answer is ignored -- ends it by accident."""
        got = self.drive(self.FINISH_DISMISSED)
        self.assertIsNotNone(got["asked"], got)
        # It shows what is still open, which is the whole reason to ask.
        self.assertIn("REQUIRED", got["asked"])
        self.assertFalse(got["waiting"], got)
        self.assertFalse(got["sendDisabled"], got)
        self.assertFalse(self.session.answers_path(1).exists())

    FINISH_ACCEPTED = """
    return (async () => {
      window.confirm = () => true;
      document.getElementById("finish").click();
      const waiting = document.getElementById("waiting");
      const shown = await waitFor(() => waiting.hasAttribute("data-on"), 6000);
      return { shown: !!shown, heading: waiting.querySelector("h2").textContent };
    })();
    """

    def test_finish_accepted_submits_a_finished_round(self):
        got = self.drive(self.FINISH_ACCEPTED)
        self.assertTrue(got["shown"], got)
        self.assertIn("final brief", got["heading"])
        submitted = read_json(self.session.answers_path(1))
        # Exactly true, not "true": the server answers "false" with a 400,
        # and this is the flag that ends somebody's session.
        self.assertIs(submitted["finished"], True)

    REFUSED = """
    return (async () => {
      const status = document.getElementById("status");
      const field = document.querySelector('.question[data-id="Q-2"] [data-text]');
      field.value = "small";
      field.dispatchEvent(new Event("input", { bubbles: true }));
      await waitFor(() => status.textContent === "saved", 6000);
      field.value = "x".repeat(1100000);
      field.dispatchEvent(new Event("input", { bubbles: true }));
      const refused = await waitFor(
        () => status.textContent.indexOf("not saved") === 0, 8000);
      // Both captured at the moment of the refusal: the recovery below moves
      // them on, and asserting the end state would assert the wrong one.
      const problem = document.getElementById("problem").textContent;
      const refusedStatus = status.textContent;
      // ...and then shrink it back, so a save can land again.
      field.value = "small again";
      field.dispatchEvent(new Event("input", { bubbles: true }));
      const recovered = await waitFor(() => status.textContent === "saved", 8000);
      return {
        refused: !!refused,
        status: refusedStatus,
        problem: problem,
        recovered: !!recovered,
        problemAfter: document.getElementById("problem").textContent,
      };
    })();
    """

    def test_a_refused_autosave_says_so_instead_of_saying_saved(self):
        """A real 413 from the real server: the body limit is 1 MiB and this
        types 1.1 MB. The user must not be told their work is safe while the
        server is refusing to store it -- that is the whole failure this task
        exists to prevent, arriving quietly."""
        got = self.drive(self.REFUSED)
        self.assertTrue(got["refused"], got)
        self.assertIn("too large", got["status"])
        self.assertIn("not been saved", got["problem"])
        # The server's messages are written to be embedded and carry no full
        # stop of their own, so the page supplies one. Without it the user
        # reads "...too large They are still on this page".
        self.assertIn("too large. They are still on this page", got["problem"])
        # A save that lands takes the alarm down again. An alarm that never
        # clears is one the user learns to read past, which costs it the one
        # time it is telling the truth.
        self.assertTrue(got["recovered"], got)
        self.assertEqual(got["problemAfter"], "")
        stored = read_json(self.session.draft_path(1))
        self.assertEqual(stored["answers"]["Q-2"], {"text": "small again"})
        # The 1.1 MB never reached the disk: the server refused it on the
        # Content-Length alone, before a temp file existed.
        self.assertLess(self.session.draft_path(1).stat().st_size, 4096)

    SEND_REFUSED = """
    return (async () => {
      const status = document.getElementById("status");
      const problem = document.getElementById("problem");
      const field = document.querySelector('.question[data-id="Q-2"] [data-text]');
      field.value = "x".repeat(1100000);
      field.dispatchEvent(new Event("input", { bubbles: true }));
      await waitFor(() => status.textContent.indexOf("not saved") === 0, 10000);
      document.getElementById("send").click();
      const refused = await waitFor(
        () => problem.textContent.indexOf("Your answers were NOT sent") === 0,
        12000);
      return {
        refused: !!refused,
        problem: problem.textContent,
        status: status.textContent,
        waiting: document.getElementById("waiting").hasAttribute("data-on"),
        sendDisabled: document.getElementById("send").disabled,
      };
    })();
    """

    def test_a_send_the_server_refuses_does_not_look_like_a_send(self):
        """The worst thing this page could do, and the plan asked for it.

        A 413 RESOLVES the fetch promise like any other response, so a page
        that awaits the POST and then unconditionally shows "Claude is folding
        your answers in…" has taken an hour of somebody's thinking, written
        nothing anywhere, and put a reassuring face over the fact. The user
        closes the tab.

        A real refusal from the real server: 1.1 MB against a 1 MiB body
        limit.
        """
        got = self.drive(self.SEND_REFUSED, budget=30000)
        self.assertTrue(got["refused"], got)
        self.assertIn("too large", got["problem"])
        self.assertIn("Nothing has been lost", got["problem"])
        self.assertIn("not sent", got["status"])
        # No waiting state, and the button works again, because Send is still
        # the thing the user has to do.
        self.assertFalse(got["waiting"], got)
        self.assertFalse(got["sendDisabled"], got)
        # And nothing was written that a fold-in step could pick up.
        self.assertFalse(self.session.answers_path(1).exists())

    # A ledger the page cannot even read, driven straight into renderRound --
    # the shape the review found blanking the counter and the filter.
    LEDGER_THEN_TYPE = """
    return (async () => {
      const unreadable = {};
      Object.defineProperty(unreadable, "contradictions", {
        enumerable: true,
        get() { throw new Error("a ledger this page cannot even read"); },
      });
      renderRound({ round: 1, questions: currentRound.questions,
                    ledger: unreadable });
      const status = document.getElementById("status");
      const field = document.querySelector('.question[data-id="Q-2"] [data-text]');
      field.value = "the ledger is broken and this still has to save";
      field.dispatchEvent(new Event("input", { bubbles: true }));
      const saved = await waitFor(() => status.textContent === "saved", 6000);
      return {
        saved: !!saved,
        counts: document.getElementById("counts").textContent,
        ledger: document.getElementById("ledger").textContent,
      };
    })();
    """

    def test_a_ledger_the_page_cannot_render_does_not_disable_autosave(self):
        """The finding the last round closed, one layer further on. A throw
        inside the ledger used to escape before applyFilter and updateCounts;
        autosave hooks in at exactly that point, and a mistyped sidebar panel
        must not be able to stop a user's answers reaching the disk."""
        got = self.drive(self.LEDGER_THEN_TYPE)
        self.assertTrue(got["saved"], got)
        self.assertEqual(got["ledger"], "The ledger could not be shown.")
        self.assertIn("1 answered", got["counts"])
        self.assertEqual(
            read_json(self.session.draft_path(1))["answers"]["Q-2"],
            {"text": "the ledger is broken and this still has to save"})

    SWAP = """
    return (async () => {
      const card = document.querySelector('.question[data-id="Q-1"]');
      card.querySelector('input[value="email"]').checked = true;
      card.dispatchEvent(new Event("change", { bubbles: true }));
      document.getElementById("send").click();
      const waiting = document.getElementById("waiting");
      const shown = await waitFor(() => waiting.hasAttribute("data-on"), 6000);
      const label = document.getElementById("roundlabel");
      const swapped = await waitFor(
        () => label.textContent.indexOf("round 2") === 0, 12000);
      // The brief is re-read AFTER the questions are swapped, so waiting on
      // the round label alone reads the sidebar one step too early. That is
      // a race in this driver and not in the page; the null waitFor returns
      // on its deadline is what tells the two apart.
      const grew = await waitFor(
        () => document.getElementById("brief").textContent
                .indexOf("Magic links") >= 0, 8000);
      return {
        shown: !!shown,
        swapped: !!swapped,
        grew: !!grew,
        label: label.textContent,
        heading: document.querySelector("#questions h3").textContent,
        waiting: waiting.hasAttribute("data-on"),
        sendDisabled: document.getElementById("send").disabled,
        brief: document.getElementById("brief").textContent,
        counts: document.getElementById("counts").textContent,
      };
    })();
    """

    def test_the_next_round_swaps_itself_in_and_the_brief_grows(self):
        """Round 2 is posted from inside a request handler, the first time the
        page polls after round 1's answers have landed.

        Coordinating on the FILE rather than on a clock is what makes this
        deterministic. The browser runs on a virtual clock that advances far
        faster than wall time, so a Python thread sleeping two seconds before
        writing round 2 would post it long after the page had given up.
        """
        self.session.brief_path.write_text(
            "# Vision\n\nA small music player.\n", encoding="utf-8")
        original = self.server.round_payload

        def post_round_two():
            if self.session.answers_path(1).exists():
                second = json.loads(json.dumps(self.ROUND))
                second["round"] = 2
                second["questions"][0]["title"] = "Which store fronts matter?"
                write_json_atomic(self.session.questions_path(2), second)
                self.session.brief_path.write_text(
                    "# Vision\n\nA small music player.\n\n"
                    "## Accounts\n\nMagic links, decided in round 1.\n",
                    encoding="utf-8")
            return original()

        self.server.round_payload = post_round_two
        got = self.drive(self.SWAP)
        self.assertTrue(got["shown"], got)
        self.assertTrue(got["swapped"], got)
        self.assertEqual(got["heading"], "Which store fronts matter?")
        # The waiting state took itself down, and the page is usable again.
        self.assertFalse(got["waiting"], got)
        self.assertFalse(got["sendDisabled"], got)
        self.assertIn("0 answered", got["counts"])
        # The brief was re-read, so the user watches it grow. A page that
        # swapped the questions and left the brief at round 1's text would
        # look identical until the session ended.
        self.assertTrue(got["grew"], got)
        self.assertIn("Magic links, decided in round 1.", got["brief"])
        # ...and round 1's answers are still the ones that were sent. The
        # swap must not have re-submitted or rewritten anything.
        self.assertEqual(read_json(self.session.answers_path(1))["answers"]["Q-1"],
                         {"choice": ["email"]})

    PAUSED = """
    return (async () => {
      const overlay = document.getElementById("overlay");
      const real = window.fetch;
      window.fetch = () => Promise.reject(new TypeError("Failed to fetch"));
      const paused = await waitFor(() => overlay.hasAttribute("data-on"), 20000);
      const text = overlay.textContent;
      window.fetch = real;
      const cleared = await waitFor(() => !overlay.hasAttribute("data-on"), 20000);
      return { paused: !!paused, text: text, cleared: !!cleared };
    })();
    """

    def test_a_server_that_stops_answering_pauses_the_page_and_it_recovers(self):
        """The page's own dependency is replaced rather than the world: the
        real server cannot be stopped part-way through a browser run without
        coordinating two unrelated clocks. What this constrains is the page's
        reaction to a fetch that rejects, which is what a stopped server
        produces; it does not constrain what the browser does to the socket.
        """
        got = self.drive(self.PAUSED, budget=60000)
        self.assertTrue(got["paused"], got)
        self.assertIn("Connection paused", got["text"])
        self.assertTrue(got["cleared"], got)

    EXPIRED = """
    return (async () => {
      const overlay = document.getElementById("overlay");
      window.fetch = () => Promise.resolve(new Response("forbidden", { status: 403 }));
      const ended = await waitFor(
        () => overlay.textContent.indexOf("session has ended") >= 0, 20000);
      return { ended: !!ended, text: overlay.textContent };
    })();
    """

    PAGEHIDE = """
    return (async () => {
      const status = document.getElementById("status");
      const field = document.querySelector('.question[data-id="Q-2"] [data-text]');
      field.value = "typed, and then the tab was closed";
      field.dispatchEvent(new Event("input", { bubbles: true }));
      window.dispatchEvent(new Event("pagehide"));
      // 200 ms is INSIDE the 400 ms debounce, so only the pagehide flush can
      // have put anything on the disk by the time this settles. The page's
      // clock is virtual and pauses while the request is outstanding, so the
      // network round trip does not eat the window.
      const saved = await waitFor(() => status.textContent === "saved", 200);
      return { saved: !!saved, status: status.textContent };
    })();
    """

    def test_a_tab_closed_inside_the_debounce_window_still_saves(self):
        """The debounce is 400 ms in which a closed tab would cost the user
        their last sentence. The flush uses keepalive so the request outlives
        the page that started it."""
        got = self.drive(self.PAGEHIDE)
        self.assertTrue(got["saved"], got)
        self.assertEqual(
            read_json(self.session.draft_path(1))["answers"]["Q-2"],
            {"text": "typed, and then the tab was closed"})

    CORRUPT = """
    return (async () => {
      const box = document.getElementById("problem");
      const shown = await waitFor(() => box.hasAttribute("data-on"), 6000);
      return {
        shown: !!shown,
        problem: box.textContent,
        text: document.querySelector('.question[data-id="Q-2"] [data-text]').value,
      };
    })();
    """

    def test_a_draft_that_cannot_be_read_is_named_rather_than_dropped(self):
        """The form can only open empty, and an empty form over a draft that
        is sitting on the disk invites the user to retype an hour of their own
        work -- after which the first keystroke overwrites the only copy. The
        server names the file for exactly this; the page has to say it."""
        self.session.draft_path(1).write_text("{not json", encoding="utf-8")
        got = self.drive(self.CORRUPT)
        self.assertTrue(got["shown"], got)
        self.assertIn("round-001.draft.json", got["problem"])
        self.assertIn("could not be read", got["problem"])
        # Named, and the consequence spelled out, because the page is about
        # to overwrite it.
        self.assertIn("overwrite", got["problem"])
        self.assertEqual(got["text"], "")

    def test_a_restarted_server_is_not_described_as_a_pause(self):
        """`serve` mints a new key on every start, so a page whose server was
        restarted gets 403 for ever -- it cannot reconnect, whatever the port
        does. Telling that user the page will recover on its own is the one
        message that guarantees they sit and wait instead of opening the new
        link, and their typing is not being saved the whole time."""
        got = self.drive(self.EXPIRED, budget=60000)
        self.assertTrue(got["ended"], got)
        self.assertNotIn("reconnect on its own", got["text"])


if __name__ == "__main__":
    unittest.main()

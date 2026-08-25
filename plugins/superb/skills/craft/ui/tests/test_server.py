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
import re
import socket
import struct
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
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
        self.patch({"round": 1, "answers": {"Q-1": {"text": "d"}}})
        before = self.session.draft_path(1).read_bytes()
        self.post({"round": 1, "answers": {}, "finished": False})
        self.assertEqual(self.session.draft_path(1).read_bytes(), before)

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
        for raw in (b"{", b"", b"\xff\xfe", b'{"round": 1,}', b"{'round': 1}"):
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

    def test_a_body_one_byte_over_the_limit_is_refused(self):
        limit = server_module.MAX_BODY_BYTES
        received = self.raw(["Content-Length: {}".format(limit + 1)])
        self.assertIn(b"413", self.status(received), received)

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


if __name__ == "__main__":
    unittest.main()

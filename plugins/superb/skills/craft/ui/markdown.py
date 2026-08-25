"""CRAFT.md -> HTML, in about a hundred lines of stdlib.

Escaping happens first, before any transformation, so a brief containing
angle brackets is safe. Covers headings, bold, italic, inline and fenced
code, links, bullet and numbered lists, blockquotes and rules. Not tables.

A link target is the one piece of brief-derived text that lands in an HTML
attribute rather than in text, and html.escape(quote=False) leaves quotes
alone, so it gets its own pass in _href(): a scheme allowlist, control
characters removed, and quotes entity-escaped. A target that fails is left
as the literal markdown the brief contained -- visible, and inert.
"""
# Deliberate: kept so any annotation added later may use `int | None` syntax
# while this project's floor is Python 3.9. Do not delete.
from __future__ import annotations

import html as _html
import re

_FENCE = re.compile(r"^```")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RULE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
_BULLET = re.compile(r"^[-*+]\s+(.*)$")
_NUMBER = re.compile(r"^\d+[.)]\s+(.*)$")
_CODE = re.compile(r"`([^`\n]+?)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+?)\*(?!\*)")
# Bounded, deliberately. Unbounded [^\]]+ is quadratic in a line of
# unmatched brackets -- 40k of them cost ~4.4 s, which is a hang for a
# server that renders on every poll. No real label or URL is this long.
_LINK = re.compile(r"\[([^\]]{1,500})\]\(([^)\s]{1,2000})\)")
# Anything the browser drops before parsing a URL must be dropped before
# the scheme is inspected, or one \x01 walks javascript: past the check.
_URL_NOISE = re.compile(r"[\x00-\x20\x7f]")
_URL_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
_SAFE_SCHEMES = frozenset(("http", "https", "mailto"))


def _href(url):
    """A link target, or None if it may not be one.

    Scheme-less targets (#anchor, ./relative, //host) are fine; a scheme we
    do not know is not, which refuses javascript:, data: and vbscript: by
    construction rather than by blocklist.
    """
    cleaned = _URL_NOISE.sub("", url)
    scheme = _URL_SCHEME.match(cleaned)
    if scheme and scheme.group(1).lower() not in _SAFE_SCHEMES:
        return None
    # & < > are already escaped; " and ' are not, and either one ends the
    # attribute and starts a live one.
    return cleaned.replace('"', "&quot;").replace("'", "&#x27;")


def _anchor(match):
    href = _href(match.group(2))
    if href is None:
        return match.group(0)
    return '<a href="{}" target="_blank" rel="noreferrer">{}</a>'.format(
        href, match.group(1)
    )


def _inline(text):
    text = _CODE.sub(lambda m: "<code>{}</code>".format(m.group(1)), text)
    text = _BOLD.sub(lambda m: "<strong>{}</strong>".format(m.group(1)), text)
    text = _ITALIC.sub(lambda m: "<em>{}</em>".format(m.group(1)), text)
    text = _LINK.sub(_anchor, text)
    return text


def render(text):
    lines = _html.escape(text or "", quote=False).split("\n")
    out = []
    list_tag = [None]

    def close_list():
        if list_tag[0]:
            out.append("</{}>".format(list_tag[0]))
            list_tag[0] = None

    def open_list(tag):
        if list_tag[0] != tag:
            close_list()
            out.append("<{}>".format(tag))
            list_tag[0] = tag

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if _FENCE.match(stripped):
            close_list()
            i += 1
            buffer = []
            while i < len(lines) and not _FENCE.match(lines[i].strip()):
                buffer.append(lines[i])
                i += 1
            i += 1  # step past the closing fence, or past the end
            out.append("<pre><code>{}</code></pre>".format("\n".join(buffer)))
            continue

        if not stripped:
            close_list()
            i += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append("<h{0}>{1}</h{0}>".format(level, _inline(heading.group(2))))
            i += 1
            continue

        if _RULE.match(stripped):
            close_list()
            out.append("<hr>")
            i += 1
            continue

        if stripped.startswith("&gt;"):
            close_list()
            out.append("<blockquote>{}</blockquote>".format(_inline(stripped[4:].strip())))
            i += 1
            continue

        bullet = _BULLET.match(stripped)
        if bullet:
            open_list("ul")
            out.append("<li>{}</li>".format(_inline(bullet.group(1))))
            i += 1
            continue

        number = _NUMBER.match(stripped)
        if number:
            open_list("ol")
            out.append("<li>{}</li>".format(_inline(number.group(1))))
            i += 1
            continue

        close_list()
        out.append("<p>{}</p>".format(_inline(stripped)))
        i += 1

    close_list()
    return "\n".join(out)

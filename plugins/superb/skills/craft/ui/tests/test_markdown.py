import time
import unittest
from html.parser import HTMLParser

from markdown import render


class _Tags(HTMLParser):
    """Reads the rendered fragment the way a browser's tokenizer does.

    Substring assertions cannot tell an inert quote inside an attribute value
    from a quote that ended the value and started a live event handler. This
    can: it reports the attributes the page actually has.
    """

    def __init__(self):
        HTMLParser.__init__(self)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))


def tags_of(fragment):
    parser = _Tags()
    parser.feed(fragment)
    parser.close()
    return parser.tags


class RenderTest(unittest.TestCase):
    def test_empty_input_renders_nothing(self):
        self.assertEqual(render(""), "")
        self.assertEqual(render(None), "")

    def test_headings_map_to_their_level(self):
        self.assertIn("<h1>Vision</h1>", render("# Vision"))
        self.assertIn("<h3>Scope</h3>", render("### Scope"))

    def test_a_paragraph_is_wrapped(self):
        self.assertIn("<p>Just words.</p>", render("Just words."))

    def test_bold_and_italic_and_code(self):
        out = render("**bold** and *thin* and `code`")
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn("<em>thin</em>", out)
        self.assertIn("<code>code</code>", out)

    def test_links_open_in_a_new_tab(self):
        out = render("see [the spec](https://example.com/s)")
        self.assertIn('<a href="https://example.com/s" target="_blank" rel="noreferrer">the spec</a>', out)

    def test_html_in_the_brief_is_escaped_not_executed(self):
        out = render("beware <script>alert(1)</script>")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_a_bullet_list_becomes_a_ul(self):
        out = render("- one\n- two")
        self.assertIn("<ul>", out)
        self.assertEqual(out.count("<li>"), 2)
        self.assertIn("</ul>", out)

    def test_a_numbered_list_becomes_an_ol(self):
        out = render("1. one\n2. two")
        self.assertIn("<ol>", out)
        self.assertEqual(out.count("<li>"), 2)

    def test_a_blank_line_closes_a_list(self):
        out = render("- one\n\nafter")
        self.assertIn("</ul>", out)
        self.assertIn("<p>after</p>", out)
        self.assertTrue(out.index("</ul>") < out.index("<p>after</p>"))

    def test_blockquote(self):
        self.assertIn("<blockquote>quoted</blockquote>", render("> quoted"))

    def test_horizontal_rule(self):
        self.assertIn("<hr>", render("---"))

    def test_fenced_code_is_preserved_and_escaped(self):
        out = render("```\na < b\n**not bold**\n```")
        self.assertIn("<pre><code>", out)
        self.assertIn("a &lt; b", out)
        self.assertIn("**not bold**", out)
        self.assertNotIn("<strong>", out)

    def test_an_unclosed_fence_does_not_hang_or_crash(self):
        out = render("```\nstill open")
        self.assertIn("<pre><code>still open</code></pre>", out)


class EscapingTest(unittest.TestCase):
    """The one property this module exists to hold: CRAFT.md is agent-written
    prose that lands in the user's browser, so every transformation runs on
    already-escaped text. Each test here dies if the escape moves later."""

    def test_ampersands_are_escaped_so_entities_cannot_be_smuggled(self):
        # A renderer that only escapes angle brackets passes the <script>
        # test above and still lets &#60;script&#62; through the browser's
        # entity decoder. Escaping & is what closes that door.
        self.assertIn("A &amp; B", render("A & B"))
        self.assertIn("&amp;#60;script&amp;#62;", render("&#60;script&#62;"))

    def test_escaping_runs_before_inline_rules_not_after(self):
        # If the escape were applied to the finished HTML instead of the raw
        # text, our own generated tags would come back as &lt;a href= and the
        # brief's angle brackets would be the only live markup on the page.
        out = render("a <b> tag and [a link](https://example.com/x)")
        self.assertIn('<a href="https://example.com/x"', out)
        self.assertIn("&lt;b&gt;", out)
        self.assertNotIn("&lt;a href=", out)

    def test_an_unclosed_tag_cannot_reach_the_page(self):
        out = render('trailing <div id="x" onload=alert')
        self.assertNotIn("<div", out)
        self.assertIn("&lt;div", out)

    def test_inline_rules_do_not_run_inside_a_fence(self):
        # The brief's fence test proves bold stays literal. A link is the
        # rule that would emit an attribute, so it is the one worth pinning:
        # nothing inside a fence may become a tag.
        out = render("```\n[x](https://example.com) and <b>\n```")
        self.assertNotIn("<a ", out)
        self.assertIn("[x](https://example.com)", out)
        self.assertIn("&lt;b&gt;", out)


class LinkTargetTest(unittest.TestCase):
    """A link is the only place this renderer puts brief-derived text into an
    HTML attribute, and html.escape(quote=False) does not touch quotes. Every
    test here fails against a renderer that interpolates the target raw."""

    def test_a_quote_in_a_link_target_cannot_open_an_attribute(self):
        # After a quoted attribute value the HTML tokenizer reconsumes in
        # before-attribute-name state, so href="a"onmouseover=... parses as a
        # second, live attribute. No whitespace is needed, and the regex's
        # \s exclusion therefore protects nothing. Verified against the
        # tokenizer rather than against a substring: unescaped, this input
        # parses as ('onmouseover', 'location=name"').
        for target in (
            'https://a"onmouseover=location=name',
            "https://a\'onmouseover=location=name",
            'https://a"autofocus"onfocus=location=name',
        ):
            with self.subTest(target=target):
                out = render("[x]({})".format(target))
                for tag, attrs in tags_of(out):
                    if tag == "a":
                        self.assertEqual(
                            [name for name, _ in attrs],
                            ["href", "target", "rel"],
                            "extra attribute parsed out of the link target",
                        )
        self.assertIn("&quot;", render('[x](https://a"b)'))
        self.assertIn("&#x27;", render("[x](https://a\'b)"))

    def test_dangerous_schemes_are_refused(self):
        for target in (
            "javascript:location=name",
            "JaVaScRiPt:location=name",
            "data:text/html,hi",
            "vbscript:msgbox",
        ):
            with self.subTest(target=target):
                out = render("[click]({})".format(target))
                self.assertEqual(
                    [tag for tag, _ in tags_of(out)],
                    ["p"],
                    "a refused scheme still produced a tag",
                )
                # Refused, not silently swallowed: the user still sees what
                # their brief said, as text.
                self.assertIn("click", out)

    def test_control_characters_cannot_smuggle_a_dangerous_scheme(self):
        # Browsers strip leading C0 controls before parsing a URL, so a naive
        # startswith check on the raw target is bypassed by one \x01.
        for target in (
            "\x01javascript:location=name",
            "\x7fjavascript:location=name",
        ):
            with self.subTest(target=target):
                out = render("[click]({})".format(target))
                self.assertEqual(
                    [tag for tag, _ in tags_of(out)],
                    ["p"],
                    "a refused target still produced a tag",
                )
                self.assertIn("click", out)

    def test_ordinary_and_relative_targets_still_link(self):
        # The other half of the guarantee: the refusal must be narrow. A
        # blanket "no links" fix would pass every test above.
        for target in (
            "https://example.com/s",
            "http://example.com/s",
            "mailto:someone@example.com",
            # Case-folded before the allowlist is consulted: a scheme is
            # case-insensitive, so HTTPS is http.
            "HTTPS://EXAMPLE.COM/a",
            "#a-section",
            "./relative/path.md",
        ):
            with self.subTest(target=target):
                out = render("[label]({})".format(target))
                self.assertIn(
                    '<a href="{}" target="_blank" rel="noreferrer">label</a>'.format(
                        target
                    ),
                    out,
                )

    def test_an_entity_encoded_colon_cannot_revive_a_refused_scheme(self):
        # Escape-first is what makes the scheme allowlist sound: the & of
        # javascript&#58;x is escaped, so the browser decodes one level and
        # gets a literal &#58; -- never a colon, never a scheme.
        out = render("[click](javascript&#58;location=name)")
        self.assertIn("&amp;#58;", out)
        self.assertNotIn("javascript:", out)


class BlockRuleTest(unittest.TestCase):
    def test_every_block_kind_closes_an_open_list(self):
        # Five separate close_list() calls in the source; deleting any one
        # leaks a <ul> that never closes and swallows the rest of the brief
        # into the list. Each case here kills exactly one of them.
        cases = {
            "heading": ("- a\n# H", "<h1>H</h1>"),
            "fence": ("- a\n```\nc\n```", "<pre><code>c</code></pre>"),
            "rule": ("- a\n---", "<hr>"),
            "blockquote": ("- a\n> q", "<blockquote>q</blockquote>"),
            "paragraph": ("- a\nplain", "<p>plain</p>"),
        }
        for name, (source, follower) in cases.items():
            with self.subTest(closed_by=name):
                out = render(source)
                self.assertIn("</ul>", out)
                self.assertIn(follower, out)
                self.assertLess(out.index("</ul>"), out.index(follower))

    def test_end_of_input_closes_an_open_list(self):
        out = render("- a\n- b")
        self.assertTrue(out.endswith("</ul>"), out)
        self.assertEqual(out.count("<ul>"), out.count("</ul>"))

    def test_a_multi_item_list_opens_its_container_exactly_once(self):
        # Counting <li> alone cannot see an open_list that re-opens on every
        # item, which is what dropping its `!= tag` guard would do.
        self.assertEqual(render("- a\n- b\n- c").count("<ul>"), 1)
        self.assertEqual(render("1. a\n2. b\n3. c").count("<ol>"), 1)

    def test_bullets_followed_by_numbers_close_the_ul_before_opening_the_ol(self):
        out = render("- a\n1. b")
        self.assertEqual(out.count("<ul>"), 1)
        self.assertEqual(out.count("<ol>"), 1)
        self.assertLess(out.index("</ul>"), out.index("<ol>"))
        self.assertTrue(out.endswith("</ol>"), out)

    def test_content_after_a_closing_fence_is_not_swallowed(self):
        # Forgetting to step past the closing fence re-enters code mode and
        # eats the rest of the document.
        out = render("```\nc\n```\nafter")
        self.assertIn("<pre><code>c</code></pre>", out)
        self.assertIn("<p>after</p>", out)
        self.assertEqual(out.count("<pre>"), 1)

    def test_a_fence_suppresses_every_block_rule_inside_it(self):
        out = render("```\n# not a heading\n- not a list\n> not a quote\n---\n```")
        for tag in ("<h1>", "<ul>", "<li>", "<blockquote>", "<hr>"):
            self.assertNotIn(tag, out)
        self.assertIn("# not a heading", out)
        self.assertIn("&gt; not a quote", out)

    def test_all_three_rule_markers_are_rules(self):
        for marker in ("---", "***", "___", "-----"):
            with self.subTest(marker=marker):
                self.assertEqual(render(marker), "<hr>")

    def test_all_the_list_markers_are_recognised(self):
        for marker in ("-", "*", "+"):
            with self.subTest(bullet=marker):
                self.assertIn("<ul>", render("{} item".format(marker)))
        for marker in ("1.", "2)"):
            with self.subTest(number=marker):
                self.assertIn("<ol>", render("{} item".format(marker)))

    def test_a_hash_run_is_only_a_heading_at_a_legal_level_with_a_space(self):
        # #{1,6} and \s+ both matter: <h7> is not an element, and #hashtag is
        # ordinary prose.
        seven = render("####### deep")
        self.assertNotIn("<h7>", seven)
        self.assertIn("<p>", seven)
        self.assertIn("<h6>", render("###### deep"))
        self.assertIn("<p>#hashtag</p>", render("#hashtag"))

    def test_inline_markup_is_applied_inside_every_block(self):
        # Five call sites of _inline(); dropping any one leaves raw asterisks
        # in that block kind only.
        cases = {
            "heading": "# **b**",
            "bullet": "- **b**",
            "number": "1. **b**",
            "blockquote": "> **b**",
            "paragraph": "**b**",
        }
        for name, source in cases.items():
            with self.subTest(block=name):
                out = render(source)
                self.assertIn("<strong>b</strong>", out)
                self.assertNotIn("**", out)

    def test_whitespace_only_input_renders_nothing(self):
        # Without the blank-line branch these become empty paragraphs.
        self.assertEqual(render("   \n\t\n  "), "")
        self.assertEqual(render("\n\n\n"), "")
        self.assertNotIn("<p></p>", render("a\n\nb"))


class InlineTest(unittest.TestCase):
    def test_italic_does_not_fire_inside_a_word(self):
        # Product briefs are full of file_names and 2*3 arithmetic; the
        # lookbehind is what keeps them from turning into emphasis.
        self.assertEqual(render("a*b*c"), "<p>a*b*c</p>")
        self.assertIn("<em>thin</em>", render("a *thin* slice"))

    def test_unclosed_markers_are_left_as_text(self):
        # *a** is the case the trailing (?!\*) guard exists for: without it,
        # bold's leftover asterisk turns into <em>a</em>*.
        for source in ("**unclosed", "*also", "`open", "[label](", "a ** b", "*a**"):
            with self.subTest(source=source):
                out = render(source)
                for tag in ("<strong>", "<em>", "<code>", "<a "):
                    self.assertNotIn(tag, out)

    def test_bold_is_matched_before_italic(self):
        # The order is only observable when the two nest. On **bold** alone
        # both orders agree, so that input constrains nothing -- this one
        # does: running italic first leaves the outer emphasis unmarked.
        self.assertIn("<em>a <strong>b</strong> c</em>", render("*a **b** c*"))
        self.assertIn("<strong>a <em>b</em> c</strong>", render("**a *b* c**"))
        out = render("**bold**")
        self.assertIn("<strong>bold</strong>", out)
        self.assertNotIn("<em>", out)


class RobustnessTest(unittest.TestCase):
    def test_rendering_the_same_input_twice_gives_the_same_output(self):
        source = "# H\n\n- a\n- b\n\n```\ncode\n```\n\n> q\n\n[l](https://e.com)"
        self.assertEqual(render(source), render(source))

    def test_a_pathological_line_terminates_quickly(self):
        # The link regex is quadratic in a line of unmatched brackets: 40k of
        # them took ~6s unbounded, which is a hang for a single-threaded
        # server rendering on every poll.
        start = time.time()
        out = render("[" * 40000)
        elapsed = time.time() - start
        self.assertLess(elapsed, 2.0, "took {:.2f}s".format(elapsed))
        self.assertIn("<p>", out)
        start = time.time()
        render("x" * 200000)
        self.assertLess(time.time() - start, 2.0)

    def test_an_indented_closing_fence_still_closes(self):
        # The closing scan strips before matching. Without that, an indented
        # fence never closes and the rest of the brief is swallowed into the
        # code block -- silently, and to the end of the document.
        out = render("```\ncode\n  ```\nafter")
        self.assertIn("<pre><code>code</code></pre>", out)
        self.assertIn("<p>after</p>", out)

    def test_degenerate_fences_terminate(self):
        # Every one of these has hung a hand-rolled fence scanner at some
        # point; the guarantee is only that they finish and stay escaped.
        self.assertIn("<pre><code>``</code></pre>", render("```\n``\n```"))
        self.assertEqual(render("```"), "<pre><code></code></pre>")
        self.assertIn("<pre><code>a &lt; b</code></pre>", render("```\na < b"))
        self.assertIn("<pre><code>", render("```\n" * 500))


if __name__ == "__main__":
    unittest.main()

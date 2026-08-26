import time
import unittest
from html.parser import HTMLParser

from markdown import render


# How much bigger the second input is than the first. Four rather than two,
# because the two hypotheses have to be told apart on a machine that is
# fighting for cache as well as for CPU: quadrupling the input costs 4x if
# the cost is linear in it and 16x if it is quadratic, which is twice the
# separation a doubling gives and the margin is what this test lives on.
GROWTH_FACTOR = 4

# Halfway between the two, on the log scale: sqrt(4 * 16) = 8. Measured
# ratios with the bounds in place run 3.8-5.1, on a quiet machine and under
# five times CPU oversubscription alike; with either bound removed they run
# 16.5-19.1. Both sides clear this by roughly a factor of two.
LINEARISH = 8.0

# Passes over the pair before the ratio is believed, and the ceiling on
# re-sampling when it is not. See growth_ratio for why more samples cannot
# turn a quadratic regex green.
GROWTH_TRIALS = 3
GROWTH_TRIAL_CAP = 8


def growth_ratio(build, n, threshold=LINEARISH):
    """Render `build(n)` and `build(GROWTH_FACTOR * n)`; measure the growth.

    Returns (ratio, cost_n, cost_big, output_at_big) -- the output too, so a
    caller can assert the rendering was still correct without paying for
    another pass over the larger input.

    A ratio near GROWTH_FACTOR means the cost grew with the input; near its
    square means it grew with the square of the input. That, and not any
    number of seconds, is the property these tests exist to hold: a
    wall-clock bound measures the machine as much as the code, passing a
    quadratic regex on a fast idle box and failing a linear one on a loaded
    one -- which is the flake the absolute bound here actually produced.

    Two things make the measurement survive a loaded machine.

    It is CPU time, not wall time. `time.process_time` does not tick while
    this process sits off the run queue waiting its turn, which is most of
    what contention does to a pure-regex workload. Measured against six
    suites and thirty-six busy loops on twelve cores, wall-clock ratios for
    the same unchanged regex ranged 1.2-2.9 on a doubling while CPU ratios
    stayed 1.9-2.4.

    And it is the minimum of several interleaved passes, re-sampled while
    the ratio still looks quadratic, up to GROWTH_TRIAL_CAP. Sampling until
    the answer is believed sounds like sampling until it passes, but the
    estimator is a minimum: every extra pass can only lower one of the two
    readings toward the cost with no interference in it, so more samples
    converge on the true ratio rather than drift toward the threshold. A
    regex that is genuinely quadratic measures ~16 however long you look,
    and burns the whole budget failing.

    What is left is the one asymmetry CPU time does not remove: the larger
    input has the larger working set, so heavy cache contention inflates its
    reading more than the small one's. It is bounded and it is why the
    threshold sits at the geometric mean of the two hypotheses rather than
    anywhere nearer the linear one.
    """
    small = large = out = None
    for trial in range(GROWTH_TRIAL_CAP):
        one, _ = _render_cpu_seconds(build(n))
        two, out = _render_cpu_seconds(build(GROWTH_FACTOR * n))
        small = one if small is None else min(small, one)
        large = two if large is None else min(large, two)
        if trial + 1 >= GROWTH_TRIALS and large / small < threshold:
            break
    return large / small, small, large, out


def _render_cpu_seconds(source):
    started = time.process_time()
    out = render(source)
    return time.process_time() - started, out


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
                # their brief said, as text. Asserting the label alone would
                # not notice a refusal that returned group(1) and threw the
                # target away; the whole original markdown has to survive.
                self.assertIn("click", out)
                self.assertIn("[click]({})".format(target), out)

    def test_an_unlisted_scheme_is_refused_even_though_no_blocklist_names_it(self):
        # The allowlist is the contract, not a three-name blocklist of
        # javascript/data/vbscript -- which would pass every other test here
        # and still link each of these, all of which run or reveal something
        # in some browser.
        for target in (
            "jscript:location=name",
            "livescript:location=name",
            "about:blank",
            "view-source:https://example.com",
            "blob:https://example.com/x",
        ):
            with self.subTest(target=target):
                out = render("[click]({})".format(target))
                self.assertEqual(
                    [tag for tag, _ in tags_of(out)],
                    ["p"],
                    "a scheme outside the allowlist still produced a tag",
                )
                self.assertIn("[click]({})".format(target), out)

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

    def test_a_control_character_inside_a_scheme_is_stripped_not_just_a_leading_one(self):
        # Stripping only a leading run leaves java\x01script: intact, and the
        # scheme regex then matches nothing at all -- so the allowlist is
        # never consulted and the target links. The strip has to run
        # everywhere, not anchored to the start.
        out = render("[click](java\x01script:location=name)")
        self.assertEqual(
            [tag for tag, _ in tags_of(out)],
            ["p"],
            "a control character mid-scheme still produced a tag",
        )

    def test_whitespace_in_a_target_stops_it_being_a_link_at_all(self):
        # The URL class excludes \s, so a target with a space is not a link
        # even when its scheme is one we allow. Widening the class to [^)]
        # would let the noise strip glue the halves back together.
        out = render("[x](https://exa mple.com)")
        self.assertNotIn("<a ", out)
        self.assertIn("[x](https://exa mple.com)", out)

    def test_a_tab_cannot_split_a_scheme_past_both_guards_at_once(self):
        # The one that matters: mid-string stripping and the \s exclusion are
        # each redundant alone, and together they are the whole defence. Undo
        # both and this renders href="java&#9;script:location=name", which a
        # browser strips the tab out of and runs.
        out = render("[x](java\tscript:location=name)")
        self.assertNotIn("<a ", out)
        self.assertEqual([tag for tag, _ in tags_of(out)], ["p"])

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
        # Five separate block-closing calls in the source; deleting any one
        # leaks a <ul> that never closes and swallows the rest of the brief
        # into the list. Each case here kills exactly one of them.
        #
        # The paragraph case is a blank line and THEN prose, not bare prose
        # on the next line. A bare plain line under a list item is that
        # item's lazy continuation now -- it joins the item and the list
        # stays open, which is the wrap-aware behaviour HardWrapTest pins.
        # What survives is the property this case was really testing: once
        # something has ended the list, a paragraph starts outside it.
        cases = {
            "heading": ("- a\n# H", "<h1>H</h1>"),
            "fence": ("- a\n```\nc\n```", "<pre><code>c</code></pre>"),
            "rule": ("- a\n---", "<hr>"),
            "blockquote": ("- a\n> q", "<blockquote>q</blockquote>"),
            "blank line then paragraph": ("- a\n\nplain", "<p>plain</p>"),
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


class HardWrapTest(unittest.TestCase):
    """A brief is hard-wrapped prose. Every test above this class feeds the
    renderer a single line, which is how one <p> per source line survived
    four review rounds: it is invisible until an input wraps."""

    def test_consecutive_lines_are_one_paragraph_not_one_each(self):
        out = render("A music player for people who\nalready own their music.")
        self.assertEqual(out.count("<p>"), 1)
        self.assertEqual(
            out,
            "<p>A music player for people who\nalready own their music.</p>",
        )

    def test_a_blank_line_ends_the_paragraph(self):
        out = render("one\ntwo\n\nthree\nfour")
        self.assertEqual(out, "<p>one\ntwo</p>\n<p>three\nfour</p>")

    def test_a_list_item_continuation_joins_the_item(self):
        # The bug in one input: the second line escaped the list entirely and
        # rendered as a paragraph below the closed </ul>.
        out = render(
            "- Playlists are private by default.\n"
            "  Sharing is a separate decision."
        )
        self.assertEqual(
            out,
            "<ul>\n<li>Playlists are private by default.\n"
            "Sharing is a separate decision.</li>\n</ul>",
        )
        self.assertNotIn("<p>", out)

    def test_a_continuation_does_not_reopen_the_list_or_add_an_item(self):
        # Closing and reopening around each continuation would still show the
        # text inside a list, and count("<li>") alone would not see it. This
        # does: a wrapped two-item list is one <ul> and exactly two items.
        out = render("- one\n  wrapped\n- two\n  wrapped")
        self.assertEqual(out.count("<ul>"), 1)
        self.assertEqual(out.count("</ul>"), 1)
        self.assertEqual(out.count("<li>"), 2)

    def test_a_numbered_list_keeps_its_continuations_in_one_ol(self):
        # A restarted <ol> renumbers from 1 in the browser, so an item that
        # wraps silently changes what the reader sees the steps to be.
        out = render("1. scan the tree\n   in parallel\n2. write the index")
        self.assertEqual(out.count("<ol>"), 1)
        self.assertEqual(out.count("<li>"), 2)

    def test_every_block_kind_still_ends_an_open_paragraph(self):
        # The other half of joining: a paragraph that never ends swallows the
        # heading, fence, rule, quote or list that should have followed it.
        cases = {
            "blank line": ("para\n\nx", "<p>x</p>"),
            "heading": ("para\n# H", "<h1>H</h1>"),
            "fence": ("para\n```\nc\n```", "<pre><code>c</code></pre>"),
            "rule": ("para\n---", "<hr>"),
            "blockquote": ("para\n> q", "<blockquote>q</blockquote>"),
            "bullet": ("para\n- b", "<li>b</li>"),
            "number": ("para\n1. b", "<li>b</li>"),
        }
        for name, (source, follower) in cases.items():
            with self.subTest(ended_by=name):
                out = render(source)
                self.assertIn("<p>para</p>", out)
                self.assertLess(out.index("<p>para</p>"), out.index(follower))
                # Relative order alone is not the property. A paragraph the
                # list never closed is emitted INSIDE the <ul>, still ahead of
                # its own <li> -- which passes the assertion above while the
                # browser renders a <p> as a child of a list. The paragraph
                # has to be CLOSED before the block that ended it OPENS, so
                # it is the first thing in the output and nothing precedes it.
                self.assertTrue(out.startswith("<p>para</p>"), out)

    def test_a_differently_typed_list_still_ends_the_open_item(self):
        out = render("- a\n  wrapped\n1. b")
        self.assertEqual(out.count("<ul>"), 1)
        self.assertEqual(out.count("<ol>"), 1)
        self.assertLess(out.index("</ul>"), out.index("<ol>"))
        self.assertIn("<li>a\nwrapped</li>", out)

    def test_end_of_input_closes_a_paragraph(self):
        self.assertTrue(render("a\nb").endswith("</p>"))

    def test_inline_rules_do_not_reach_across_the_wrap(self):
        # Joining happens after each line is transformed, not before. If a
        # block's lines were concatenated and then passed through _inline,
        # emphasis and links would fuse across the brief's line breaks --
        # and the link label class, [^\]]{1,500}, does match a newline.
        out = render("**bold\ntext**")
        self.assertNotIn("<strong>", out)
        self.assertIn("<p>**bold\ntext**</p>", out)
        out = render("[label\n](https://example.com)")
        self.assertNotIn("<a ", out)

    def test_escaping_still_runs_first_on_a_wrapped_paragraph(self):
        # The XSS defence has to survive the block that spans lines too: a
        # tag split across the wrap must still be text.
        out = render("beware <script>\nalert(1)</script>")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;\nalert(1)&lt;/script&gt;", out)

    def test_a_wrapped_block_does_not_leave_an_empty_paragraph(self):
        self.assertNotIn("<p></p>", render("a\nb\n\n\n   \nc"))
        self.assertEqual(render("- a\n  b\n\n   \n"), "<ul>\n<li>a\nb</li>\n</ul>")


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

    def test_a_pathological_line_grows_linearly_not_quadratically(self):
        # The link regex was quadratic in a line of unmatched brackets: 40k of
        # them cost ~5s unbounded, which is a hang for a single-threaded
        # server rendering on every poll.
        #
        # The property is growth, not duration. An absolute bound on the wall
        # clock measures the machine as much as the code -- it passes a
        # quadratic regex on a fast idle box and fails a linear one on a
        # loaded one, which is exactly the flake it produced here. Growing
        # the input is what separates the two, and growth_ratio explains why
        # the measurement holds on a machine under load.
        ratio, small, large, out = growth_ratio(lambda n: "[" * n, 10000)
        self.assertLess(
            ratio, LINEARISH,
            "{}x the brackets multiplied the CPU cost by {:.2f} "
            "({:.3f}s -> {:.3f}s); linear is ~{}, quadratic is ~{}".format(
                GROWTH_FACTOR, ratio, small, large,
                GROWTH_FACTOR, GROWTH_FACTOR ** 2))
        self.assertIn("<p>", out)
        # Dropped from here: a 200k line of plain "x". Every rule is linear in
        # text that matches none of them, bounds or no bounds, so it cost
        # suite time and constrained nothing. It is no use as a baseline for a
        # ratio either -- 40k of "x" renders in well under a millisecond, so
        # the comparison would be against timer noise.

    def test_a_pathological_link_target_grows_linearly_not_quadratically(self):
        # The bracket line above exercises the label class only: remove the
        # {1,2000} bound from the URL class alone and every other test stays
        # green while "[a](" repeated goes quadratic on its own.
        ratio, small, large, out = growth_ratio(lambda n: "[a](" * n, 2500)
        self.assertLess(
            ratio, LINEARISH,
            "{}x the link targets multiplied the CPU cost by {:.2f} "
            "({:.3f}s -> {:.3f}s); linear is ~{}, quadratic is ~{}".format(
                GROWTH_FACTOR, ratio, small, large,
                GROWTH_FACTOR, GROWTH_FACTOR ** 2))
        self.assertIn("<p>", out)

    def test_a_hard_wrapped_paragraph_grows_linearly_not_quadratically(self):
        # Joining a block that spans lines is where quadratic cost gets
        # reintroduced: appending each line onto an accumulated string, or
        # re-slicing the "<p>...</p>" already in the output to splice the
        # next line in, copies the whole block once per line and costs its
        # square. Accumulating into a list and joining once costs its length.
        #
        # Same estimator as the two regex tests above, and for the same
        # reason -- the property is growth, not seconds.
        line = "the brief wraps at seventy-two columns like every other one\n"
        ratio, small, large, out = growth_ratio(lambda n: line * n, 5000)
        self.assertLess(
            ratio, LINEARISH,
            "{}x the wrapped lines multiplied the CPU cost by {:.2f} "
            "({:.3f}s -> {:.3f}s); linear is ~{}, quadratic is ~{}".format(
                GROWTH_FACTOR, ratio, small, large,
                GROWTH_FACTOR, GROWTH_FACTOR ** 2))
        self.assertEqual(out.count("<p>"), 1)

    def test_a_hard_wrapped_list_item_grows_linearly_not_quadratically(self):
        # The item accumulator is a second, separate buffer; a fix applied to
        # the paragraph path alone would leave this one quadratic and every
        # other test green.
        line = "the brief wraps at seventy-two columns like every other one\n"
        ratio, small, large, out = growth_ratio(
            lambda n: "- first\n" + line * n, 5000)
        self.assertLess(
            ratio, LINEARISH,
            "{}x the continuation lines multiplied the CPU cost by {:.2f} "
            "({:.3f}s -> {:.3f}s); linear is ~{}, quadratic is ~{}".format(
                GROWTH_FACTOR, ratio, small, large,
                GROWTH_FACTOR, GROWTH_FACTOR ** 2))
        self.assertEqual(out.count("<li>"), 1)

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

"""Three-option regressions using synthetic fixtures; nothing is sent."""

from helpers import FIXTURES, OWNER  # sets import path and synthetic config
import copy
import json
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import graphics
from render_brief import COMPOSER, POST_SHAPES, email_html, render, validate
from source_evidence import public_urls

FILL_IN_LINE = "[Your line: what a customer told you about their serving setup]"
CHROME = graphics.chrome_path()


def example_options():
    data = json.loads((FIXTURES / "sample-brief.json").read_text())
    original = data.pop("post")
    url = data.pop("post_url")
    data["posts"] = [
        {"angle": "Audit prep", "shape": "result_first", "voice": "opinion", "text": original, "url": url},
        {
            "angle": "Shared planning assumptions",
            "shape": "old_problem_now",
            "voice": "opinion",
            "text": "Changing a planning assumption shouldn't mean hunting through copied queries.\n\nSnowflake schema variables hold a named, typed value beyond a single session, with separate read and write permissions.\n\nFor example, a finance team could point its scenario queries at one approved exchange-rate assumption instead of editing every copy. The queries still need to be adapted, and this isn't a historical exchange-rate table. If you've already centralized those values in a configuration table, the benefit is smaller.",
            "url": data["features"][1]["sources"][0]["url"],
        },
        {
            "angle": "Feature-serving upkeep",
            "shape": "tried_it",
            "voice": "fill_in",
            "text": "A real-time model needs a way to retrieve its inputs. That service can become another thing for the team to maintain.\n\n" + FILL_IN_LINE + "\n\nSnowflake's Online Feature Store provides low-latency retrieval of feature values for real-time applications. The feature pipeline and model still need work, and serving isn't free. Available in AWS and Azure commercial regions, not Google Cloud.",
            "url": data["features"][2]["sources"][0]["url"],
        },
    ]
    for number, post in enumerate(data["posts"], 1):
        post["model"] = {"url": f"https://www.linkedin.com/posts/example-author-{number}", "author": f"Example Author {number}", "pattern": "outcome hook, three short lines, one honest catch"}
        post["graphic"] = example_graphic(number, post["url"])
    # Scheduled issues need an AI feature; the structural fixture has none, so relabel one.
    data["features"][4]["category"] = "AI"
    return data


def example_graphic(number, url):
    return {
        "title": f"Option {number} in two steps", "subtitle": "A short explainer drawn from the cited page.", "source_url": url,
        "diagram": {"type": "lanes", "lanes": ["You", "Snowflake"], "steps": [
            {"lane": 0, "title": "Turn it on", "note": "One setting on the account"},
            {"lane": 1, "title": "It takes over", "note": "The service handles the rest", "marker": "A"}]},
        "callouts": [{"marker": "A", "title": "One honest limit", "text": "Check the edition and region on the page before you plan around it."}],
    }


def png_bytes(width, height):
    """A small valid PNG built with the standard library."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    rows = b"".join(b"\x00" + b"\xff" * (3 * width) for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


def fake_render(spec, output):
    """Chrome is slow; tests get a valid 1080x1350 PNG instead of a real render."""
    Path(output).write_bytes(png_bytes(1080, 1350))
    return Path(output)


def write_references(directory, data):
    path = Path(directory) / "references.json"
    posts = [{"url": post["model"]["url"], "content": f"Unrelated reference wording number {number} about a different product entirely."} for number, post in enumerate(data["posts"])]
    path.write_text(json.dumps({"posts": posts}))
    return path


def render_scheduled(data, directory, **kwargs):
    output = Path(directory)
    with patch("render_brief.verify_evidence"), patch("render_brief.check_graphic_sources"), patch("graphics.render", fake_render):
        render(data, output, output, "linkedin-test-options", require_three_posts=True, references=write_references(directory, data), **kwargs)
    return json.loads((output / "smtp-message.json").read_text())["messages"][0]


class PostOptionsTests(unittest.TestCase):
    def test_three_options_complete_in_all_outputs(self):
        data = example_options()
        validate(data)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            message = render_scheduled(data, directory)
            from html import unescape
            for content in (unescape(message["html"]), message["text"], (output / "latest-post.md").read_text()):
                for number, post in enumerate(data["posts"], 1):
                    self.assertIn(f"Option {number}: {post['angle']}", content)
                    for paragraph in post["text"].split("\n\n"):
                        self.assertIn(paragraph, content)
                    self.assertIn(post["url"], content)
                self.assertNotIn("One post.", content)
                self.assertNotIn("Review before posting.", content)
            self.assertEqual(message["html"].count('class="post-copy"'), 3)
            self.assertEqual(message["html"].count(f'href="{COMPOSER}"'), 1)
            self.assertLess(message["html"].index("Option 3:"), message["html"].index('class="feature"'))
            copies = (output / "latest-post.md").read_text()
            self.assertNotIn("slack.com", copies)
            self.assertNotIn("seismic.com", copies)

    def test_bad_count_duplicates_and_mixed_schema_rejected(self):
        original = example_options()
        for count in (0, 1, 2, 4):
            data = copy.deepcopy(original)
            data["posts"] = (data["posts"] * 2)[:count]
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "exactly three"):
                validate(data)
        data = copy.deepcopy(original)
        data["posts"][1]["text"] = data["posts"][0]["text"]
        with self.assertRaisesRegex(ValueError, "distinct"):
            validate(data)
        data = copy.deepcopy(original)
        data["post"] = "stale legacy value"
        with self.assertRaisesRegex(ValueError, "legacy"):
            validate(data)

    def test_each_option_needs_included_public_evidence(self):
        for index in range(3):
            data = example_options()
            data["posts"][index]["url"] = "https://www.snowflake.com/en/blog/unreviewed/"
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "included public"):
                validate(data)
            data["posts"][index]["url"] = "https://snowflake.slack.com/archives/C123/p123"
            with self.assertRaisesRegex(ValueError, "Unapproved"):
                validate(data)

    def test_blog_or_guide_can_be_share_link_but_must_be_captured(self):
        data = example_options()
        for index, url in enumerate(("https://www.snowflake.com/en/blog/example/", "https://developers.snowflake.com/guides/example/", "https://docs.snowflake.com/en/user-guide/example")):
            data["posts"][index]["url"] = url
            data["features"][index]["sources"].append({"url": url, "label": "Walkthrough", "method": "page_text", "excerpt": "Example source text used only in this structural unit test."})
        validate(data)
        urls = public_urls(data)
        for post in data["posts"]:
            self.assertIn(post["url"], urls)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                render(data, Path(directory) / "out", Path(directory), "linkedin-test-options", True, references=write_references(directory, data))
            self.assertFalse((Path(directory) / "out").exists())

    def test_scheduled_flag_rejects_legacy_before_output(self):
        data = json.loads((FIXTURES / "sample-brief.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "require three"):
                render(data, Path(directory), require_three_posts=True)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_shapes_label_options_in_all_outputs(self):
        data = example_options()
        with tempfile.TemporaryDirectory() as directory:
            message = render_scheduled(data, directory)
            from html import unescape
            for content in (unescape(message["html"]), message["text"], (Path(directory) / "latest-post.md").read_text()):
                self.assertIn(f"Option 1: Audit prep ({POST_SHAPES['result_first']})", content)
                self.assertIn(f"Option 3: Feature-serving upkeep ({POST_SHAPES['tried_it']}, needs your line)", content)

    def test_shapes_must_be_known_distinct_and_rotated(self):
        data = example_options()
        data["posts"][1]["shape"] = "listicle"
        with self.assertRaisesRegex(ValueError, "shape from"):
            validate(data)
        data["posts"][1]["shape"] = "result_first"
        with self.assertRaisesRegex(ValueError, "different shapes"):
            validate(data)
        data = example_options()
        with self.assertRaisesRegex(ValueError, "Rotate shapes"):
            validate(data, previous_shapes=["tried_it", "result_first", "old_problem_now"])
        validate(data, previous_shapes=["tried_it", "result_first", "roundup"])

    def test_short_take_is_short(self):
        data = example_options()
        data["posts"][0]["shape"] = "short_take"
        with self.assertRaisesRegex(ValueError, "short take"):
            validate(data)

    def test_scheduled_issue_requires_every_shape(self):
        data = example_options()
        del data["posts"][1]["shape"]
        with self.assertRaisesRegex(ValueError, "shape from"):
            validate(data)
        for post in data["posts"]:
            post.pop("shape", None)
        validate(data)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "shape on every"):
                render(data, Path(directory), require_three_posts=True)

    def test_scheduled_issue_requires_checked_models(self):
        data = example_options()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "--references"):
                render(data, Path(directory), require_three_posts=True)
        for post in data["posts"]:
            for key in ("voice", "model"):
                post.pop(key)
        validate(data)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "--references"):
                render(data, Path(directory), require_three_posts=True, references=write_references(directory, example_options()))

    def test_code_and_sql_rejected(self):
        for snippet in ("ALTER FAILOVER GROUP myfg SET READ_ONLY = TRUE;", "Run `SHOW TABLES` first.", "SELECT AI_COMPLETE(model => 'x') FROM t"):
            data = example_options()
            data["posts"][0]["text"] += "\n\n" + snippet
            with self.subTest(snippet=snippet), self.assertRaisesRegex(ValueError, "code or SQL"):
                validate(data)

    def test_two_opinions_and_one_fill_in(self):
        data = example_options()
        data["posts"][2]["voice"] = "opinion"
        with self.assertRaisesRegex(ValueError, "two opinion"):
            validate(data)
        data = example_options()
        data["posts"][2]["text"] = data["posts"][2]["text"].replace(FILL_IN_LINE, "We tried it last week and it worked.")
        with self.assertRaisesRegex(ValueError, "bracketed"):
            validate(data)
        data = example_options()
        data["posts"][0]["text"] += " [add a stat]"
        with self.assertRaisesRegex(ValueError, "ready to paste"):
            validate(data)
        data = example_options()
        data["posts"][0]["shape"], data["posts"][2]["shape"] = "tried_it", "who_for"
        with self.assertRaisesRegex(ValueError, "use fill_in"):
            validate(data)

    def test_model_posts_must_be_real_distinct_and_not_copied(self):
        data = example_options()
        data["posts"][0]["model"]["url"] = "https://example.com/post"
        with self.assertRaisesRegex(ValueError, "LinkedIn post"):
            validate(data)
        data = example_options()
        data["posts"][1]["model"]["url"] = data["posts"][0]["model"]["url"]
        with self.assertRaisesRegex(ValueError, "different post"):
            validate(data)
        data = example_options()
        references = {post["model"]["url"]: {"content": "unrelated"} for post in data["posts"]}
        validate(data, references=references)
        del references[data["posts"][2]["model"]["url"]]
        with self.assertRaisesRegex(ValueError, "this run's references"):
            validate(data, references=references)
        references = {post["model"]["url"]: {"content": "unrelated"} for post in data["posts"]}
        references[data["posts"][1]["model"]["url"]]["content"] = "Intro. " + data["posts"][1]["text"].split("\n\n")[0]
        with self.assertRaisesRegex(ValueError, "copies wording"):
            validate(data, references=references)

    def test_model_post_is_not_shown(self):
        data = example_options()
        with tempfile.TemporaryDirectory() as directory:
            message = render_scheduled(data, directory)
            from html import unescape
            import re
            for content in (re.sub(r"<[^>]+>", "", unescape(message["html"])), message["text"], (Path(directory) / "latest-post.md").read_text()):
                for post in data["posts"]:
                    self.assertNotIn("Modeled on", content)
                    self.assertNotIn(post["model"]["author"], content)
            for post in data["posts"]:
                for content in (message["html"], message["text"], (Path(directory) / "latest-post.md").read_text()):
                    self.assertNotIn(post["model"]["url"], content)

    def test_option_text_is_escaped(self):
        data = example_options()
        data["posts"][1]["angle"] = '<img src=x onerror="bad()">'
        data["posts"][1]["model"]["author"] = '<script>bad()</script>'
        data["posts"][1]["graphic"]["title"] = '"><script>bad()</script>'
        rendered = email_html(data)
        self.assertIn("&lt;img", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn("<script", rendered)
        shown = email_html(data, images=(1, 2, 3))
        self.assertEqual(shown.count("<img"), 3)
        self.assertNotIn("<script", shown)
        self.assertIn("&quot;&gt;&lt;script&gt;", shown)


class GraphicTests(unittest.TestCase):
    def test_graphics_are_png_files_inline_in_the_email(self):
        import base64
        import struct
        data = example_options()
        with tempfile.TemporaryDirectory() as directory:
            message = render_scheduled(data, directory)
            images = message["inline_images"]
            self.assertEqual([image["cid"] for image in images], ["option-1", "option-2", "option-3"])
            for number, image in enumerate(images, 1):
                png = base64.b64decode(image["png_base64"])
                self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(struct.unpack(">II", png[16:24]), (1080, 1350))
                self.assertEqual((Path(directory) / "graphics" / f"option-{number}.png").read_bytes(), png)
                self.assertEqual(message["html"].count(f'src="cid:option-{number}"'), 1)
                self.assertNotIn(f"graphics/option-{number}.png", message["text"])
                self.assertIn(f"graphics/option-{number}.png", (Path(directory) / "latest-post.md").read_text())
                self.assertIn(f"Graphic: Option {number} in two steps", message["text"])
            self.assertLess(message["html"].index('src="cid:option-3"'), message["html"].index('class="feature"'))
            self.assertEqual(message["html"].count("<img"), 3)
            self.assertIn('width="480"', message["html"])
            for gone in ("Image source", "Image idea", "No image", "Right-click", "right-click"):
                self.assertNotIn(gone, message["html"] + message["text"])

    def test_scheduled_issue_needs_a_graphic_on_every_option(self):
        data = example_options()
        del data["posts"][1]["graphic"]
        validate(data)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "graphic spec on every option"):
                render_scheduled(data, directory)
            self.assertFalse((Path(directory) / "graphics").exists())

    def test_graphics_need_captured_evidence(self):
        data = example_options()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "captured evidence"):
                render(data, Path(directory) / "out")
            self.assertFalse((Path(directory) / "out").exists())

    def test_release_screenshots_and_cards_are_retired(self):
        for key, value in (("visual", {"page_url": "x", "image_url": "y", "alt": "z"}), ("visual_gap", "No diagram on the release page at all"),
                           ("card", {"kicker": "Public preview", "headline": "x", "points": ["y", "z"]}),
                           ("image", {"suggestion": "a diagram", "source_url": "https://docs.snowflake.com/"})):
            data = example_options()
            data["posts"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "image cards are retired"):
                validate(data)

    def test_no_status_pill_and_source_from_the_same_feature(self):
        data = example_options()
        data["posts"][0]["graphic"]["status"] = "Generally available"
        with self.assertRaisesRegex(ValueError, "status pill"):
            validate(data)
        data = example_options()
        data["posts"][0]["graphic"]["source_url"] = data["posts"][1]["url"]
        with self.assertRaisesRegex(ValueError, "this option's feature"):
            validate(data)
        data = example_options()
        data["posts"][0]["graphic"]["source_url"] = "https://example.com/page"
        with self.assertRaisesRegex(ValueError, "Unapproved"):
            validate(data)

    def test_graphic_text_limits_are_checked_before_rendering(self):
        data = example_options()
        data["posts"][0]["graphic"]["title"] = "A title " * 12
        with self.assertRaisesRegex(ValueError, "title is over"):
            validate(data)
        data = example_options()
        data["posts"][0]["graphic"]["subtitle"] = "Plain \u2014 dash"
        with self.assertRaisesRegex(ValueError, "em dash"):
            validate(data)

    def test_code_and_quotes_must_be_on_the_cited_pages(self):
        from render_brief import check_graphic_sources
        from source_evidence import source_key
        data = example_options()
        data["posts"][0]["graphic"]["diagram"]["steps"][0]["code"] = "ALTER FAILOVER GROUP <name> REFRESH"
        data["posts"][0]["graphic"]["code"] = {"code": "-- comment only\nSET READ_ONLY = TRUE; -- pauses tasks"}
        with tempfile.TemporaryDirectory() as directory:
            def capture(text):
                for url in {source["url"] for item in data["features"] for source in item["sources"]} | {post["url"] for post in data["posts"]}:
                    (Path(directory) / f"{source_key(url)}.json").write_text(json.dumps({"text": text}))
            capture("Run ALTER FAILOVER GROUP myfg REFRESH on the target. ALTER FAILOVER GROUP myfg SET READ_ONLY = TRUE;")
            check_graphic_sources(data, directory)
            capture("Run ALTER FAILOVER GROUP myfg REFRESH on the target.")
            with self.assertRaisesRegex(ValueError, "Option 1 graphic shows text that is not on"):
                check_graphic_sources(data, directory)

    def test_one_option_models_a_fixed_reference(self):
        data = example_options()
        references = {post["model"]["url"]: {"content": "unrelated"} for post in data["posts"]}
        references["https://www.linkedin.com/posts/fixed-author-1"] = {"content": "unrelated", "fixed": True}
        with self.assertRaisesRegex(ValueError, "fixed reference"):
            validate(data, references=references)
        references[data["posts"][2]["model"]["url"]]["fixed"] = True
        validate(data, references=references)

    def test_logo_is_optional(self):
        import graphics
        spec = json.loads((FIXTURES / "graphic-example.json").read_text())
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ):
            os.environ.pop("LINKEDIN_DIGEST_LOGO", None)
            self.assertNotIn("<img", graphics.page_html(spec))
            os.environ["LINKEDIN_DIGEST_LOGO"] = str(Path(directory) / "missing.png")
            self.assertNotIn("<img", graphics.page_html(spec))
            logo = Path(directory) / "logo.png"
            logo.write_bytes(png_bytes(4, 4))
            os.environ["LINKEDIN_DIGEST_LOGO"] = str(logo)
            self.assertEqual(graphics.page_html(spec).count('<img class="logo" src="data:image/png;base64,'), 1)
            logo.write_text("not a png")
            with self.assertRaisesRegex(ValueError, "PNG"):
                graphics.page_html(spec)

    def test_chrome_path_can_be_overridden(self):
        import graphics
        with patch.dict(os.environ, {"CHROME_PATH": "/opt/chrome/chrome"}):
            self.assertEqual(graphics.chrome_path(), Path("/opt/chrome/chrome"))
        with patch.dict(os.environ):
            os.environ.pop("CHROME_PATH", None)
            self.assertEqual(graphics.chrome_path(), Path(graphics.CHROME))

    @unittest.skipUnless(CHROME.is_file(), "Google Chrome not found; set CHROME_PATH to run the real render")
    def test_real_render_is_a_full_graphic(self):
        import graphics
        import struct
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ):
            os.environ.pop("LINKEDIN_DIGEST_LOGO", None)
            spec = json.loads((FIXTURES / "graphic-example.json").read_text())
            path = graphics.render(spec, Path(directory) / "graphic.png")
            png = path.read_bytes()
            self.assertEqual(struct.unpack(">II", png[16:24]), (1080, 1350))

    def test_graphic_html_passes_the_sender_allowlist(self):
        import sys
        sender = Path(__file__).resolve().parents[3] / "vendor" / "safe-email-send" / "src"
        if not sender.exists():
            self.skipTest("vendored safe-email-send not present")
        sys.path.insert(0, str(sender))
        try:
            from safe_email_send.message import validate_html
        finally:
            sys.path.remove(str(sender))
        data = example_options()
        with tempfile.TemporaryDirectory() as directory:
            message = render_scheduled(data, directory)
            validate_html(message["html"], inline_ids=frozenset(image["cid"] for image in message["inline_images"]))


class LineBreakTests(unittest.TestCase):
    def test_single_line_breaks_in_posts_survive_in_html(self):
        data = example_options()
        data["posts"][0]["text"] += "\n\nWhat changed:\n\u2192 one setting\n\u2192 reads keep working"
        rendered = email_html(data)
        self.assertIn("What changed:<br>\n\u2192 one setting<br>\n\u2192 reads keep working", rendered)


class AIFeatureTests(unittest.TestCase):
    def test_scheduled_issue_needs_an_ai_feature(self):
        data = example_options()
        data["features"][4]["category"] = "Data Science & ML"
        validate(data)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "AI feature"):
                render_scheduled(data, directory)
            self.assertFalse((Path(directory) / "smtp-message.json").exists())


if __name__ == "__main__":
    unittest.main()

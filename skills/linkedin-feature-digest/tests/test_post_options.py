"""Three-option regressions using synthetic fixtures; nothing is sent."""

from helpers import FIXTURES, OWNER  # sets import path and synthetic config
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from render_brief import COMPOSER, POST_SHAPES, email_html, render, validate
from source_evidence import public_urls


def example_options():
    data = json.loads((FIXTURES / "sample-brief.json").read_text())
    original = data.pop("post")
    url = data.pop("post_url")
    data["posts"] = [
        {"angle": "Audit prep", "shape": "problem_fix", "text": original, "url": url},
        {
            "angle": "Shared planning assumptions",
            "shape": "no_longer",
            "text": "Changing a planning assumption shouldn't mean hunting through copied queries.\n\nSnowflake schema variables hold a named, typed value beyond a single session, with separate read and write permissions.\n\nFor example, a finance team could point its scenario queries at one approved exchange-rate assumption instead of editing every copy. The queries still need to be adapted, and this isn't a historical exchange-rate table. If you've already centralized those values in a configuration table, the benefit is smaller.",
            "url": data["features"][1]["sources"][0]["url"],
        },
        {
            "angle": "Feature-serving upkeep",
            "shape": "who_for",
            "text": "A real-time model needs a way to retrieve its inputs. That service can become another thing for the team to maintain.\n\nSnowflake's Online Feature Store provides low-latency retrieval of feature values for real-time applications. For example, a fraud team could use it to retrieve customer-spending signals while scoring a transaction.\n\nThe feature pipeline and model still need work, and serving isn't free. It gives teams a managed option to consider before building another serving layer. Available in AWS and Azure commercial regions, not Google Cloud.",
            "url": data["features"][2]["sources"][0]["url"],
        },
    ]
    return data


class PostOptionsTests(unittest.TestCase):
    def test_three_options_complete_in_all_outputs(self):
        data = example_options()
        validate(data)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch("render_brief.verify_evidence"):
                render(data, output, output, "linkedin-test-options", require_three_posts=True)
            message = json.loads((output / "smtp-message.json").read_text())["messages"][0]
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
            data["posts"][index]["url"] = "https://example.slack.com/archives/C123/p123"
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
                render(data, Path(directory) / "out", Path(directory), "linkedin-test-options", True)
            self.assertFalse((Path(directory) / "out").exists())

    def test_scheduled_flag_rejects_legacy_before_output(self):
        data = json.loads((FIXTURES / "sample-brief.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "require three"):
                render(data, Path(directory), require_three_posts=True)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_option_text_is_escaped(self):
        data = example_options()
        data["posts"][1]["angle"] = '<img src=x onerror="bad()">'
        rendered = email_html(data)
        self.assertIn("&lt;img", rendered)
        self.assertNotIn("<img", rendered)

    def test_shapes_label_options_in_all_outputs(self):
        data = example_options()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch("render_brief.verify_evidence"):
                render(data, output, output, "linkedin-test-options", require_three_posts=True)
            message = json.loads((output / "smtp-message.json").read_text())["messages"][0]
            from html import unescape
            for content in (unescape(message["html"]), message["text"], (output / "latest-post.md").read_text()):
                for number, post in enumerate(data["posts"], 1):
                    self.assertIn(f"Option {number}: {post['angle']} ({POST_SHAPES[post['shape']]})", content)

    def test_shapes_must_be_known_distinct_and_rotated(self):
        data = example_options()
        data["posts"][2]["shape"] = "listicle"
        with self.assertRaisesRegex(ValueError, "shape from"):
            validate(data)
        data["posts"][2]["shape"] = "problem_fix"
        with self.assertRaisesRegex(ValueError, "different shapes"):
            validate(data)
        data = example_options()
        with self.assertRaisesRegex(ValueError, "Rotate shapes"):
            validate(data, previous_shapes=["who_for", "problem_fix", "no_longer"])
        validate(data, previous_shapes=["who_for", "problem_fix", "command"])

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


if __name__ == "__main__":
    unittest.main()

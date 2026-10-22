from helpers import FIXTURES, OWNER  # sets import path and synthetic config
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from render_brief import ROOT, FEATURE_FIELDS, email_html, estimate, render, resource_rows, resource_url, source_url, validate


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((FIXTURES / "example-brief.json").read_text())

    def test_example_and_math(self):
        validate(self.data)
        label, result = estimate(self.data["features"][0]["impact"])
        self.assertEqual("Example scenario", label)
        self.assertIn("8 engineering hours per month", result)

    def test_missing_business_example_is_rejected(self):
        self.data["features"][0]["business_example"] = ""
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_sales_fields_are_required(self):
        for key in ("buyer", "pain", "talk_track"):
            for value in (None, "", "   "):
                with self.subTest(key=key, value=value):
                    data = copy.deepcopy(self.data)
                    data["features"][0][key] = value
                    with self.assertRaises(ValueError):
                        validate(data)

    def test_measurement_only_impact_is_rejected(self):
        self.data["features"][0]["impact"] = {"kind": "measure", "detail": "Track hours."}
        with self.assertRaisesRegex(ValueError, "measurement-only"):
            validate(self.data)

    def test_status_quo_only_does_not_invent_savings(self):
        impact = copy.deepcopy(self.data["features"][0]["impact"])
        del impact["proposed"]
        label, result = estimate(impact)
        self.assertEqual("Example scenario", label)
        self.assertIn("Status quo: 12 engineering hours per month", result)
        self.assertIn("not the amount Snowflake will remove", result)
        self.assertNotIn("difference is", result)

    def test_zero_volume_zero_baseline_and_higher_effort_rejected(self):
        for key, value in (("volume", 0), ("baseline", 0), ("proposed", 4)):
            with self.subTest(key=key):
                impact = copy.deepcopy(self.data["features"][0]["impact"])
                impact[key] = value
                with self.assertRaises(ValueError):
                    estimate(impact)

    def test_overflow_is_rejected(self):
        impact = copy.deepcopy(self.data["features"][0]["impact"])
        impact.update(baseline=1e308, volume=1e308)
        with self.assertRaisesRegex(ValueError, "finite"):
            estimate(impact)

    def test_qualitative_value_requires_limits(self):
        impact = {"kind": "qualitative", "detail": "Removes repeated manual report assembly.", "exclusions": "Access review remains manual."}
        self.assertIn("Access review remains manual.", estimate(impact)[1])
        impact["exclusions"] = ""
        with self.assertRaises(ValueError):
            estimate(impact)

    def test_review_fixture_has_correct_value_math(self):
        data = json.loads((FIXTURES / "sample-brief.json").read_text())
        validate(data)
        outcomes = [estimate(item["impact"])[1] for item in data["features"]]
        self.assertIn("Status quo: 24 engineering hours per year", outcomes[0])
        self.assertIn("difference is 16 engineering hours per year", outcomes[0])
        self.assertIn("difference is 9 analyst hours per quarter", outcomes[1])
        self.assertIn("Status quo: 32 engineering hours per planning month", outcomes[2])
        self.assertNotIn("difference is", outcomes[2])

    def test_unverified_sources_are_rejected(self):
        self.data["features"][0]["sources"][0]["method"] = "search_snippet"
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_internal_channel_link_is_rejected(self):
        with self.assertRaises(ValueError):
            source_url("https://example.slack.com/archives/C123", True)

    def test_specific_internal_link_is_accepted(self):
        source_url("https://example.slack.com/archives/C123/p1792622451193719", True)

    def test_external_source_is_rejected(self):
        with self.assertRaises(ValueError):
            source_url("https://docs.snowflake.com.evil.test/release")

    def test_invalid_math_is_rejected(self):
        for value in [-1, float("nan"), float("inf"), True]:
            impact = copy.deepcopy(self.data["features"][0]["impact"])
            impact["baseline"] = value
            with self.assertRaises(ValueError):
                estimate(impact)

    def test_email_only_preserves_complete_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            render(self.data, output)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"email-body.md", "email-payload.json", "latest-post.md"},
            )
            email = (output / "email-body.md").read_text()
            self.assertIn("**Business example:**", email)
            self.assertIn("**Example scenario:**", email)
            self.assertNotIn("not a measured result", email)
            self.assertTrue(email.startswith(
                "# Weekly Feature Digest | " + self.data["date"]
                + "\n\n## Your next LinkedIn post\n\n" + self.data["post"]
            ))
            self.assertEqual(email.count("**Business example:**"), 3)
            self.assertNotIn("INTERNAL ONLY", email)
            self.assertNotIn(".html", email)
            self.assertNotIn("#/workspaces/", email)
            payload = json.loads((output / "email-payload.json").read_text())
            self.assertEqual(payload["body_markdown"], email)
            self.assertNotIn("](", email)
            for feature in self.data["features"]:
                for _, field in FEATURE_FIELDS:
                    self.assertIn(feature[field], email)

    def test_html_and_text_preserve_all_sales_content(self):
        from html.parser import HTMLParser

        class VisibleText(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.parts = []

            def handle_data(self, data):
                self.parts.append(data)

        with tempfile.TemporaryDirectory() as directory:
            render(self.data, Path(directory))
            email = (Path(directory) / "email-body.md").read_text()
            parser = VisibleText()
            parser.feed(email_html(self.data))
            visible = " ".join(" ".join(parser.parts).split())
            for item in self.data["features"]:
                for _, key in FEATURE_FIELDS:
                    self.assertIn(item[key], visible)
                    self.assertIn(item[key], email)
                self.assertIn(estimate(item["impact"])[1], visible)
                self.assertIn(estimate(item["impact"])[1], email)
            self.assertNotIn("What to measure", visible + email)
            self.assertNotIn("engineering hours", self.data["post"])

    def test_more_than_five_features_rejected_without_truncation(self):
        self.data["features"] *= 2
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(ValueError, "1-5"):
                render(self.data, output)
            self.assertEqual(list(output.iterdir()), [])

    def test_one_to_five_features_allowed_without_padding(self):
        for count in range(1, 6):
            with self.subTest(count=count):
                data = json.loads((FIXTURES / "sample-brief.json").read_text())
                data["features"] = data["features"][:count]
                validate(data)

    def test_empty_features_rejected(self):
        self.data["features"] = []
        with self.assertRaisesRegex(ValueError, "1-5"):
            validate(self.data)

    def test_post_cannot_be_an_extra_topic(self):
        self.data["post_url"] = "https://docs.snowflake.com/unlisted-topic"
        with self.assertRaisesRegex(ValueError, "included public features"):
            validate(self.data)

    def test_internal_features_share_the_five_item_limit(self):
        self.data = json.loads((FIXTURES / "sample-brief.json").read_text())
        internal = self.data["features"][4]
        internal["classification"] = "internal"
        internal["sources"][0].update({
            "url": "https://example.slack.com/archives/C123/p1792622451193719",
            "method": "slack_message",
        })
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            render(self.data, output)
            email = (output / "email-body.md").read_text()
            self.assertEqual(email.count("**Business example:**"), 5)
            self.assertIn("INTERNAL ONLY - DO NOT POST OR FORWARD EXTERNALLY", email)
            self.assertGreater(email.index(internal["title"]), email.index("INTERNAL ONLY"))
        self.data["features"].append(copy.deepcopy(internal))
        with self.assertRaisesRegex(ValueError, "1-5"):
            validate(self.data)

    def test_duplicate_features_are_not_padding(self):
        self.data["features"].append(copy.deepcopy(self.data["features"][0]))
        with self.assertRaisesRegex(ValueError, "distinct features"):
            validate(self.data)

    def test_category_and_resource_checks_required(self):
        for field, value in (("category", None), ("category", "misc"), ("sales_resources", None)):
            with self.subTest(field=field, value=value):
                data = copy.deepcopy(self.data)
                data["features"][0][field] = value
                with self.assertRaises(ValueError):
                    validate(data)

    def test_resource_links_reject_unsafe_or_wrong_destinations(self):
        for url, kind in (
            ("javascript:alert(1)", "slide"),
            ("https://example.seismic.com.evil.test/Link/Content/DC123", "slide"),
            ("https://example.seismic.com:444/Link/Content/DC123", "slide"),
            ("https://example.seismic.com/Link/Content/DC123?tracking=1", "slide"),
            ("https://example.slack.com/messages/U123?text=hello", "pm"),
            ("https://example.slack.com/archives/C123/p123", "channel"),
            ("https://example.slack.com/archives/C123", "pm"),
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                resource_url(url, kind)

    def test_pm_identity_and_ownership_evidence_required(self):
        original = json.loads((FIXTURES / "sample-brief.json").read_text())
        for field, value in (("user_id", "U999"), ("evidence_url", "https://example.slack.com/archives/C123"), ("excerpt", "not proof"), ("role", "")):
            data = copy.deepcopy(original)
            data["features"][0]["sales_resources"]["pm"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(data)

    def test_deck_sharing_and_relevance_required(self):
        original = json.loads((FIXTURES / "sample-brief.json").read_text())
        for field, value in (("sharing", "public"), ("sharing_basis", ""), ("relevance", ""), ("excerpt", "")):
            data = copy.deepcopy(original)
            data["features"][0]["sales_resources"]["slides"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(data)

    def test_resource_dates_and_duplicate_decks_rejected(self):
        original = json.loads((FIXTURES / "sample-brief.json").read_text())
        original["features"][0]["sales_resources"]["checked_on"] = "2099-01-01"
        with self.assertRaisesRegex(ValueError, "after briefing date"):
            validate(original)
        original["features"][0]["sales_resources"]["checked_on"] = original["date"]
        original["features"][0]["sales_resources"]["slides"] *= 2
        with self.assertRaisesRegex(ValueError, "Deduplicate"):
            validate(original)

    def test_missing_resources_are_visible_in_both_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            render(self.data, Path(directory))
            plain = (Path(directory) / "email-body.md").read_text()
            content = email_html(self.data)
            for label in ("no relevant deck verified", "PM: not verified", "Feature channel: not verified"):
                self.assertIn(label, plain)
                self.assertIn(label, content)

    def test_five_feature_resources_and_subject_match(self):
        from html import unescape

        data = json.loads((FIXTURES / "sample-brief.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch("render_brief.verify_evidence"):
                render(data, output, output, "linkedin-weekly-2026-W43")
            record = json.loads((output / "email-payload.json").read_text())
            message = json.loads((output / "smtp-message.json").read_text())["messages"][0]
            self.assertEqual(message["subject"], "Weekly Feature Digest | 2026-10-22")
            self.assertEqual(record["subject"], message["subject"])
            self.assertEqual(message["html"].count('class="feature"'), 5)
            self.assertEqual(message["html"].count('class="sales-resources"'), 5)
            for item in data["features"]:
                self.assertIn(item["category"], unescape(message["html"]))
                self.assertIn(item["category"], message["text"])
                for label, url, detail in resource_rows(item["sales_resources"]):
                    for value in (label, url, detail):
                        if value:
                            self.assertIn(value, message["text"])
                            self.assertIn(value, unescape(message["html"]))
            self.assertNotIn("seismic.com", (output / "latest-post.md").read_text())
            self.assertNotIn("slack.com", (output / "latest-post.md").read_text())

    def test_evidence_gate_failure_prevents_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch("render_brief.verify_evidence", side_effect=ValueError("missing proof")) as verify:
                with self.assertRaisesRegex(ValueError, "missing proof"):
                    render(self.data, output, evidence_dir=output / "evidence")
                verify.assert_called_once_with(self.data, output / "evidence")
            self.assertEqual(list(output.iterdir()), [])

    def test_smtp_requires_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "requires captured evidence"):
                render(self.data, Path(directory), smtp_source_id="linkedin-test-example")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_smtp_payload_is_self_only_complete_and_not_attachment(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch("render_brief.verify_evidence") as verify:
                render(self.data, output, output / "evidence", "linkedin-test-example")
                verify.assert_called_once()
            batch = json.loads((output / "smtp-message.json").read_text())
            self.assertEqual(batch["scope"], "individual")
            self.assertEqual(len(batch["messages"]), 1)
            item = batch["messages"][0]
            self.assertEqual(item["to"], OWNER)
            self.assertEqual(set(item), {"to", "subject", "text", "html", "source_id"})
            self.assertTrue(item["subject"].startswith("[Test]"))
            self.assertEqual(item["text"], (output / "email-body.md").read_text())
            self.assertEqual(item["html"].count("<strong>Business example:</strong>"), 3)
            self.assertEqual(list(output.glob("*.html")), [])

    def test_smtp_html_escapes_source_text(self):
        self.data["features"][0]["business_example"] = '<img src=x onerror="bad()">'
        content = email_html(self.data)
        self.assertIn("&lt;img", content)
        self.assertNotIn("<img", content)
        self.assertNotIn("<script", content)
        self.assertNotIn("<!doctype", content.lower())

    def test_banner_and_numbered_sales_sections(self):
        from html import unescape

        for count in range(1, 6):
            data = json.loads((FIXTURES / "sample-brief.json").read_text())
            data["features"] = data["features"][:count]
            with self.subTest(count=count):
                content = unescape(email_html(data))
                self.assertEqual(content.count('class="digest-banner"'), 1)
                self.assertIn("background-color:#123548", content)
                self.assertNotIn("One post.", content)
                self.assertLess(content.index('class="digest-banner"'), content.index('class="post-copy"'))
                self.assertLess(content.index('class="post-copy"'), content.index('class="feature"'))
                self.assertNotIn("not a measured result", content)
                for number, feature in enumerate(data["features"], 1):
                    self.assertIn(f"{number}. {feature['title']}", content)
                for label in ("What to say", "The pain", "The value", "Useful links", "Example scenario"):
                    self.assertEqual(content.count(f">{label}</p>"), count)

    def test_no_intro_fluff_in_either_format(self):
        for count in range(1, 6):
            data = json.loads((FIXTURES / "sample-brief.json").read_text())
            data["features"] = data["features"][:count]
            with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
                render(data, Path(directory))
                for content in (email_html(data), (Path(directory) / "email-body.md").read_text()):
                    for removed in ("One post.", "Review before posting.", "Nothing is published automatically."):
                        self.assertNotIn(removed, content)
                    self.assertIn("Weekly Feature Digest", content)
                    self.assertIn("https://www.linkedin.com/sharing/compose", content)

    def test_sales_reading_order_matches_both_formats(self):
        from html import unescape

        with tempfile.TemporaryDirectory() as directory:
            render(self.data, Path(directory))
            plain = (Path(directory) / "email-body.md").read_text()
            content = unescape(email_html(self.data))
            for item in self.data["features"]:
                for output in (plain, content):
                    positions = [output.index(item[key]) for key in (
                        "title", "change", "talk_track", "buyer", "pain",
                        "enables", "before", "business_example",
                    )]
                    self.assertEqual(positions, sorted(positions))
                    self.assertIn("Assumptions:", output)
                    self.assertIn("Time returned is capacity", output)

    def test_internal_numbering_and_post_separation(self):
        data = json.loads((FIXTURES / "sample-brief.json").read_text())
        internal = data["features"].pop(1)
        internal["classification"] = "internal"
        internal["sources"][0].update({
            "url": "https://example.slack.com/archives/C123/p1792622451193719",
            "method": "slack_message",
        })
        data["features"].insert(0, internal)
        with tempfile.TemporaryDirectory() as directory:
            render(data, Path(directory))
            for output in (email_html(data), (Path(directory) / "email-body.md").read_text()):
                self.assertIn("5. " + internal["title"], output)
                self.assertGreater(output.index(internal["title"]), output.index("INTERNAL ONLY"))
                self.assertLess(output.index(data["post_url"]), output.index("INTERNAL ONLY"))

    def test_compact_resources_keep_evidence_out_of_email(self):
        data = json.loads((FIXTURES / "sample-brief.json").read_text())
        resources = data["features"][0]["sales_resources"]
        with tempfile.TemporaryDirectory() as directory:
            render(data, Path(directory))
            for content in (email_html(data), (Path(directory) / "email-body.md").read_text()):
                for removed in ("Resources checked", "PM ownership evidence", resources["pm"]["role"],
                                "Internal sales prep.", "Private sales prep.", "Sharing basis:"):
                    self.assertNotIn(removed, content)
                self.assertIn("https://app.slack.com/client/TEXAMPLE1/UEXAMPLE01", content)
                self.assertIn("Internal only - do not forward to customers", content)
                self.assertIn("Assumptions:", content)
        self.assertIn("role", resources["pm"])
        self.assertIn("sharing_basis", resources["slides"][0])

    def test_workspace_scoped_pm_links_and_identity(self):
        data = json.loads((FIXTURES / "sample-brief.json").read_text())
        pm = data["features"][0]["sales_resources"]["pm"]
        pm["url"] = "https://app.slack.com/client/TEXAMPLE1/" + pm["user_id"]
        validate(data)
        for url in ("https://app.slack.com/client/TWRONG/UEXAMPLE01",
                    "https://app.slack.com.evil.test/client/TEXAMPLE1/UEXAMPLE01",
                    pm["url"] + "?text=hello", pm["url"] + "#fragment"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                resource_url(url, "pm")
        pm["url"] = "https://app.slack.com/client/TEXAMPLE1/U999"
        with self.assertRaisesRegex(ValueError, "match the verified"):
            validate(data)

    def test_compact_typography(self):
        content = email_html(self.data)
        self.assertIn("font-size:14px;color:#253F4D", content)
        self.assertIn("font-size:15px;color:#123548", content)
        self.assertIn("font-size:18px;line-height:1.25", content)
        self.assertNotIn("font-size:30px", content)
        self.assertNotIn("font-size:26px", content)

    def test_visible_release_urls_and_composer_label(self):
        from html.parser import HTMLParser

        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []
                self.current = None

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self.current = [dict(attrs)["href"], ""]

            def handle_data(self, data):
                if self.current is not None:
                    self.current[1] += data

            def handle_endtag(self, tag):
                if tag == "a":
                    self.links.append(tuple(self.current))
                    self.current = None

        parser = Links()
        parser.feed(email_html(self.data))
        self.assertIn((self.data["post_url"], self.data["post_url"]), parser.links)
        for feature in self.data["features"]:
            for source in feature["sources"]:
                self.assertIn((source["url"], source["url"]), parser.links)
        self.assertEqual([item for item in parser.links if "linkedin.com" in item[0]],
                         [("https://www.linkedin.com/sharing/compose", "Post to Linkedin")])
        with tempfile.TemporaryDirectory() as directory:
            render(self.data, Path(directory))
            plain = (Path(directory) / "email-body.md").read_text()
            self.assertIn("Post to Linkedin: https://www.linkedin.com/sharing/compose", plain)
            self.assertNotIn("Open LinkedIn composer", plain)

    def test_smtp_source_id_is_restricted(self):
        for source_id in ("another-campaign", "linkedin-bad\nID", "linkedin-" + "x" * 121):
            with self.subTest(source_id=source_id), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, "source ID"):
                    render(self.data, Path(directory), Path(directory), source_id)


if __name__ == "__main__":
    unittest.main()
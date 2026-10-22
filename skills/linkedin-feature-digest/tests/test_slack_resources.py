"""Synthetic Slack resource fixtures; no connector or mail side effects."""

from helpers import FIXTURES, OWNER  # sets import path and synthetic config
import json
import tempfile
import unittest
from pathlib import Path

from render_brief import ROOT, email_html, render, resource_url, validate


class SlackResourceTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((FIXTURES / "example-brief.json").read_text())

    def slack_deck(self):
        return {
            "title": "Feature Store enablement",
            "url": "https://docs.google.com/presentation/d/test_deck-123/edit",
            "pages": "Slide numbers not verified", "sharing": "unverified",
            "sharing_basis": "Original message does not establish customer sharing permission.",
            "relevance": "The original share describes Feature Store migration enablement.",
            "excerpt": "Sharing Feature Store migration slides for internal enablement.",
            "discovered_via": "slack", "shared_on": "2026-10-21",
            "evidence_url": "https://example.enterprise.slack.com/archives/C123/p1792647907672709",
            "evidence_excerpt": "Sharing Feature Store migration slides for internal enablement.",
            "content_status": "not_accessible",
        }

    def test_slack_deck_link_formats(self):
        for url in (
            self.slack_deck()["url"],
            "https://drive.google.com/file/d/test_deck-123/view",
            "https://example.slack.com/files/U123/F123/slides.pdf",
            "https://example.enterprise.slack.com/files/W123/F123",
            "https://example.enterprise.slack.com/archives/C123/p1792647907672709",
            "https://example.seismic.com/Link/Content/DC123",
        ):
            with self.subTest(url=url):
                self.data["features"][0]["sales_resources"]["slides"] = [dict(self.slack_deck(), url=url)]
                validate(self.data)

    def test_slack_deck_unsafe_links_rejected(self):
        for url in (
            "https://docs.google.com.evil.test/presentation/d/test/edit",
            "https://docs.google.com@evil.test/presentation/d/test/edit",
            "https://drive.google.com/drive/folders/test",
            "https://docs.google.com/document/d/test/edit",
            "https://files.slack.com/files-pri/T123-F123/slides.pdf",
            "https://example.slack.com/archives/C123",
            "https://example.slack.com/files/U123/F123/../other",
            "https://docs.google.com/presentation/d/test/edit?token=secret",
            "https://docs.google.com/presentation/d/test/edit#slide=id.guessed",
            "https://docs.google.com/presentation/d/test/edit\n",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                resource_url(url, "slide")

    def test_slack_deck_requires_provenance_and_review_state(self):
        for field, value in (
            ("discovered_via", "compass"), ("discovered_via", "unknown"),
            ("evidence_url", "https://example.slack.com/archives/C123"),
            ("evidence_url", "https://example.slack.com/archives/C123/p123?token=x"),
            ("evidence_excerpt", "not evidence"), ("shared_on", "2026-10-23"),
            ("content_status", "guessed"),
        ):
            deck = dict(self.slack_deck(), **{field: value})
            self.data["features"][0]["sales_resources"]["slides"] = [deck]
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate(self.data)

    def test_unread_slack_decks_cannot_claim_pages_or_customer_sharing(self):
        for field, value in (("pages", "Slide 5"), ("sharing", "external")):
            self.data["features"][0]["sales_resources"]["slides"] = [dict(self.slack_deck(), **{field: value})]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Unread decks"):
                validate(self.data)
        self.data["features"][0]["sales_resources"]["slides"] = [dict(
            self.slack_deck(), content_status="reviewed", pages="Slide 5",
        )]
        validate(self.data)

    def test_combined_deck_cap_and_cross_source_duplicates(self):
        resource = self.data["features"][0]["sales_resources"]
        resource["slides"] = [dict(self.slack_deck(), url=f"https://docs.google.com/presentation/d/test{index}/edit") for index in range(3)]
        with self.assertRaisesRegex(ValueError, "zero to two"):
            validate(self.data)
        compass = json.loads((FIXTURES / "sample-brief.json").read_text())["features"][0]["sales_resources"]["slides"][0]
        resource["slides"] = [compass, dict(self.slack_deck(), url=compass["url"])]
        with self.assertRaisesRegex(ValueError, "Deduplicate"):
            validate(self.data)

    def test_slack_provenance_and_access_caveat_in_both_formats(self):
        deck = self.slack_deck()
        self.data["features"][0]["sales_resources"]["slides"] = [deck]
        with tempfile.TemporaryDirectory() as directory:
            render(self.data, Path(directory))
            plain = (Path(directory) / "email-body.md").read_text()
            content = email_html(self.data)
            for value in (deck["url"], deck["evidence_url"], "Shared in Slack on 2026-10-21", "Deck content not reviewed; access required", "Sharing unverified - internal use only"):
                self.assertIn(value, plain)
                self.assertIn(value, content)
            post = (Path(directory) / "latest-post.md").read_text()
            self.assertNotIn("docs.google.com", post)
            self.assertNotIn("slack.com", post)


if __name__ == "__main__":
    unittest.main()
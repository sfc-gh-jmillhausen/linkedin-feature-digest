from helpers import FIXTURES, OWNER  # sets import path and synthetic config
import json
import tempfile
import unittest
from pathlib import Path

import digest_config


class ConfigTests(unittest.TestCase):
    def write(self, directory, **changes):
        raw = json.loads((FIXTURES / "test-config.json").read_text())
        raw.update(changes)
        path = Path(directory) / "config.json"
        path.write_text(json.dumps(raw))
        return str(path)

    def test_synthetic_config_loads(self):
        config = digest_config.load()
        self.assertEqual(config["owner"], OWNER)
        self.assertEqual(config["weekdays"], (0, 3))
        self.assertEqual((config["hour"], config["minute"]), (8, 0))

    def test_missing_config_points_to_example(self):
        with self.assertRaisesRegex(ValueError, "config.example.json"):
            digest_config.load("/nonexistent/linkedin-digest/config.json")

    def test_invalid_values_rejected(self):
        cases = (
            {"owner_email": "Not An Email"},
            {"owner_email": "a@example.com, b@example.com"},
            {"timezone": "Mars/Base"},
            {"issue_weekdays": [7]},
            {"issue_weekdays": []},
            {"issue_time": "25:00"},
            {"slack": {"team_id": "bad", "hosts": ["example.slack.com"]}},
            {"public_hosts": ["https://docs.snowflake.com"]},
        )
        for change in cases:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(Exception):
                    digest_config.load(self.write(directory, **change))

    def test_example_config_is_a_valid_template(self):
        example = Path(__file__).resolve().parents[1] / "config.example.json"
        config = digest_config.load(str(example))
        self.assertNotIn("snowflake.com", config["owner"])
        self.assertEqual(config["fixed_reference_profiles"], ())
        self.assertIsNone(config["graphic_logo"])

    def test_optional_graphic_and_reference_keys_default_off(self):
        config = digest_config.load()
        self.assertEqual(config["fixed_reference_profiles"], ())
        self.assertEqual(config["fixed_reference_keep"], 5)
        self.assertIsNone(config["graphic_logo"])
        self.assertIsNone(config["chrome_path"])

    def test_fixed_reference_profiles_are_validated(self):
        good = [{"url": "https://www.linkedin.com/in/example-author/", "name": "Example Author"}]
        with tempfile.TemporaryDirectory() as directory:
            config = digest_config.load(self.write(directory, fixed_reference_profiles=good, fixed_reference_keep=3,
                                                   graphic_logo="~/logo.png"))
            self.assertEqual(config["fixed_reference_profiles"], tuple(good))
            self.assertEqual(config["fixed_reference_keep"], 3)
            self.assertEqual(config["graphic_logo"], Path.home() / "logo.png")
        cases = (
            {"fixed_reference_profiles": "https://www.linkedin.com/in/example-author/"},
            {"fixed_reference_profiles": [{"url": "https://example.com/in/someone/", "name": "Someone"}]},
            {"fixed_reference_profiles": [{"url": "https://www.linkedin.com/in/example-author/"}]},
            {"fixed_reference_profiles": [{"url": "https://www.linkedin.com/in/example-author/", "name": " "}]},
            {"fixed_reference_profiles": good * 2},
            {"fixed_reference_keep": 0},
            {"fixed_reference_keep": "5"},
            {"graphic_logo": 7},
            {"chrome_path": ""},
        )
        for change in cases:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    digest_config.load(self.write(directory, **change))


class FixedReferenceTests(unittest.TestCase):
    def test_no_profiles_means_no_profile_queries(self):
        import reference_posts
        self.assertEqual(reference_posts.fixed_profiles(), ({}, 5))
        plan = reference_posts.queries(reference_posts.DEFAULT_COMPANY, ["Snowflake Cortex"], "week")
        self.assertFalse(any("profile" in params for params in plan))

    def test_fixed_posts_come_first_and_are_marked(self):
        import reference_posts
        profile = "https://www.linkedin.com/in/example-author/"
        plan = reference_posts.queries(reference_posts.DEFAULT_COMPANY, ["Snowflake Cortex"], "week", {profile: "Example Author"})
        self.assertEqual(plan[0], {"profile": profile, "page": "1"})
        found = {f"https://www.linkedin.com/posts/other-{n}": {"url": f"https://www.linkedin.com/posts/other-{n}", "score": 100 + n} for n in range(4)}
        fixed = {f"https://www.linkedin.com/posts/fixed-{n}": {"url": f"https://www.linkedin.com/posts/fixed-{n}", "score": n} for n in range(3)}
        found["https://www.linkedin.com/posts/fixed-2"] = dict(fixed["https://www.linkedin.com/posts/fixed-2"])
        ranked = reference_posts.rank(found, fixed, 2)
        self.assertEqual([post["url"] for post in ranked[:2]], ["https://www.linkedin.com/posts/fixed-2", "https://www.linkedin.com/posts/fixed-1"])
        self.assertTrue(all(post.get("fixed") for post in ranked[:2]))
        self.assertEqual(len(ranked), 6)
        self.assertFalse(any(post.get("fixed") for post in ranked[2:]))


if __name__ == "__main__":
    unittest.main()

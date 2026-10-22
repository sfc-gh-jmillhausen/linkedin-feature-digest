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


if __name__ == "__main__":
    unittest.main()

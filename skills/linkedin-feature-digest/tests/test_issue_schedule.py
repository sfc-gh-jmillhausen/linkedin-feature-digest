from helpers import FIXTURES, OWNER  # sets import path and synthetic config
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from issue_schedule import issue_context, issue_slot, load_or_create_issue


class IssueScheduleTests(unittest.TestCase):
    def context(self, value):
        return issue_context(datetime.fromisoformat(value))

    def test_monday_and_thursday_have_distinct_ids(self):
        self.assertEqual(self.context("2026-10-26T08:00:00-07:00")["source_id"], "linkedin-digest-2026-10-26")
        self.assertEqual(self.context("2026-10-29T08:00:00-07:00")["source_id"], "linkedin-digest-2026-10-29")

    def test_retry_and_catchup_keep_issue_id(self):
        monday = self.context("2026-10-26T08:00:00-07:00")["source_id"]
        for value in ("2026-10-26T12:00:00-07:00", "2026-10-27T09:00:00-07:00", "2026-10-29T07:59:59-07:00"):
            with self.subTest(value=value):
                self.assertEqual(self.context(value)["source_id"], monday)

    def test_before_monday_run_uses_previous_thursday(self):
        self.assertEqual(self.context("2026-10-26T07:59:59-07:00")["issue_date"], "2026-10-22")

    def test_dst_uses_pacific_wall_clock(self):
        self.assertEqual(self.context("2026-11-02T16:00:00+00:00")["scheduled_at"], "2026-11-02T08:00:00-08:00")
        self.assertEqual(self.context("2027-03-15T15:00:00+00:00")["scheduled_at"], "2027-03-15T08:00:00-07:00")

    def test_year_boundary_and_run_date(self):
        context = self.context("2027-01-01T10:00:00-08:00")
        self.assertEqual(context["source_id"], "linkedin-digest-2026-12-31")
        self.assertEqual(context["run_date"], "2027-01-01")

    def test_naive_datetime_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            issue_slot(datetime(2026, 10, 26, 8))

    def test_saved_retry_keeps_identity_past_next_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "issue.json"
            original = load_or_create_issue(path, datetime.fromisoformat("2026-10-26T08:00:00-07:00"))
            before = path.read_bytes()
            resumed = load_or_create_issue(path, datetime.fromisoformat("2026-11-02T10:00:00-08:00"))
            self.assertEqual(resumed, original)
            self.assertEqual(path.read_bytes(), before)

    def test_corrupt_or_future_identity_stops_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "issue.json"
            saved = self.context("2026-10-29T08:00:00-07:00")
            path.write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError, "not due"):
                load_or_create_issue(path, datetime.fromisoformat("2026-10-26T08:00:00-07:00"))
            saved["source_id"] = "linkedin-digest-2026-10-26"
            path.write_text(json.dumps(saved))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "identity"):
                load_or_create_issue(path, datetime.fromisoformat("2026-11-02T08:00:00-08:00"))
            self.assertEqual(path.read_bytes(), before)
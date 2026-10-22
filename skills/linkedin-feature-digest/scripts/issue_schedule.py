"""Resolve the latest due issue slot without reading or sending mail."""

import argparse
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import digest_config


def schedule():
    config = digest_config.load()
    return ZoneInfo(config["timezone"]), config["weekdays"], time(config["hour"], config["minute"])


def issue_slot(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Issue scheduling requires a timezone-aware datetime")
    zone, weekdays, at = schedule()
    local_now = now.astimezone(zone)
    for offset in range(8):
        candidate_date = local_now.date() - timedelta(days=offset)
        candidate = datetime.combine(candidate_date, at, zone)
        if candidate.weekday() in weekdays and candidate <= local_now:
            return candidate
    raise ValueError("No due issue found")


def issue_context(now):
    slot = issue_slot(now)
    return {
        "issue_date": slot.date().isoformat(),
        "scheduled_at": slot.isoformat(),
        "run_date": now.astimezone(schedule()[0]).date().isoformat(),
        "source_id": f"linkedin-digest-{slot.date().isoformat()}",
    }


def load_or_create_issue(path, now):
    """Pin the original slot so a resumed run cannot become a different issue."""
    context = issue_context(now)
    try:
        with path.open("x", encoding="utf-8") as manifest:
            json.dump(context, manifest, indent=2)
            manifest.write("\n")
        return context
    except FileExistsError:
        saved = json.loads(path.read_text(encoding="utf-8"))
        scheduled_at = datetime.fromisoformat(saved["scheduled_at"])
        expected = issue_context(scheduled_at)
        if any(saved.get(key) != expected[key] for key in ("issue_date", "scheduled_at", "source_id")):
            raise ValueError("Saved issue identity does not match its scheduled slot")
        if scheduled_at > now:
            raise ValueError("Saved issue is not due yet")
        return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", type=datetime.fromisoformat, help="Optional aware ISO timestamp for checks")
    parser.add_argument("--issue-file", type=Path, help="Persist/reuse issue.json in an existing run folder")
    args = parser.parse_args()
    now = args.at or datetime.now(schedule()[0])
    context = load_or_create_issue(args.issue_file, now) if args.issue_file else issue_context(now)
    print(json.dumps(context, indent=2))
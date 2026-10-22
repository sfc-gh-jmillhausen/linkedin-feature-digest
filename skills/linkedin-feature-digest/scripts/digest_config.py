"""Per-user settings for the digest. Nothing personal is stored in the repository.

Lookup order: --config argument, LINKEDIN_DIGEST_CONFIG, then
~/.config/linkedin-feature-digest/config.json. See config.example.json.
"""

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_PATH = Path.home() / ".config" / "linkedin-feature-digest" / "config.json"
EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,63}")
HOST = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")


def config_path(path=None):
    return Path(path or os.environ.get("LINKEDIN_DIGEST_CONFIG") or DEFAULT_PATH).expanduser()


def _hosts(values, name):
    if not isinstance(values, list) or not values or not all(isinstance(v, str) and HOST.fullmatch(v) for v in values):
        raise ValueError(f"{name} must be a nonempty list of lowercase hostnames")
    return frozenset(values)


@lru_cache(maxsize=None)
def load(path=None):
    file = config_path(path)
    if not file.is_file():
        raise ValueError(f"Missing digest config at {file}; copy config.example.json and fill in your own values")
    raw = json.loads(file.read_text())
    owner = raw.get("owner_email", "")
    if not isinstance(owner, str) or not EMAIL.fullmatch(owner):
        raise ValueError("owner_email must be one lowercase email address")
    ZoneInfo(raw.get("timezone", ""))
    weekdays = raw.get("issue_weekdays")
    if not isinstance(weekdays, list) or not weekdays or not all(type(d) is int and 0 <= d <= 6 for d in weekdays):
        raise ValueError("issue_weekdays must list Python weekdays 0 (Monday) to 6 (Sunday)")
    hour, minute = (int(part) for part in raw.get("issue_time", "").split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("issue_time must be HH:MM")
    slack = raw.get("slack", {})
    team = slack.get("team_id", "")
    if not re.fullmatch(r"[TE][A-Z0-9]+", team):
        raise ValueError("slack.team_id must be your workspace ID (starts with T or E)")
    return {
        "owner": owner,
        "timezone": raw["timezone"],
        "weekdays": tuple(sorted(set(weekdays))),
        "hour": hour,
        "minute": minute,
        "slack_team": team,
        "slack_hosts": _hosts(slack.get("hosts"), "slack.hosts"),
        "compass_hosts": _hosts(raw.get("compass_hosts"), "compass_hosts"),
        "public_hosts": _hosts(raw.get("public_hosts"), "public_hosts"),
    }

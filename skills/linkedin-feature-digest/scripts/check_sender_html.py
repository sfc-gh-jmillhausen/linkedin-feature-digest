"""Read-only SMTP-fragment check using the existing sender's HTML validator."""

import argparse
import json
from pathlib import Path

from safe_email_send.message import validate_html

import digest_config


def check(path):
    batch = json.loads(path.read_text())
    if batch["scope"] != "individual" or len(batch["messages"]) != 1:
        raise ValueError("Expected a single individual message")
    message = batch["messages"][0]
    if message["to"] != digest_config.load()["owner"]:
        raise ValueError("Expected owner-only preview")
    if set(message) != {"to", "subject", "text", "html", "source_id"}:
        raise ValueError("Unexpected SMTP fields")
    if not 0 < len(message["text"]) <= 50000 or not 0 < len(message["html"]) <= 100000:
        raise ValueError("Body size outside sender limits")
    validate_html(message["html"])
    print(json.dumps({
        "html_validation": "passed",
        "text_characters": len(message["text"]),
        "html_characters": len(message["html"]),
        "scope": "unsigned body only; no preparation, queue access, or send",
    }))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    check(parser.parse_args().input)
"""Pull recent high-engagement LinkedIn posts about Snowflake products via HarvestAPI.

Writes <output>/references.json: product/feature posts ranked by engagement, used only
as structural models for the digest's post options (never copied). Authors in the config's
optional fixed_reference_profiles are pulled every run whatever this week's ranking says;
their best fixed_reference_keep posts carry "fixed": true and at least one option must be
modeled on one. Read-only, capped at MAX_PAGES search pages (a few cents).
Key: HARVEST_API_KEY or ~/.config/harvestapi/key.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import digest_config

API = "https://api.harvestapi.io/linkedin/post-search"
DEFAULT_COMPANY = "https://www.linkedin.com/company/snowflake-computing"
DEFAULT_KEYWORDS = ["Snowflake Cortex", "Snowflake new feature", "Snowflake data engineering"]
MAX_PAGES = 8
KEEP = 15
PRODUCT = re.compile(r"cortex|semantic view|dbt|iceberg|openflow|snowpark|dynamic table|preview|generally available|"
                     r"\bGA\b|feature|release|pipeline|agent|warehouse|horizon|notebook|streamlit|query|benchmark", re.I)
PERSONAL = re.compile(r"hiring|open position|anniversar|new position|first day|new chapter|years at|apply now|"
                      r"joined|join our|my chapter|congrat|wedding|last day", re.I)


def api_key():
    if os.environ.get("HARVEST_API_KEY"):
        return os.environ["HARVEST_API_KEY"].strip()
    return (Path.home() / ".config/harvestapi/key").read_text().strip()


def fetch(params, key):
    request = urllib.request.Request(API + "?" + urllib.parse.urlencode(params),
                                     headers={"X-API-Key": key, "User-Agent": "linkedin-feature-digest/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def score(engagement):
    return (engagement.get("likes") or 0) + 3 * (engagement.get("comments") or 0) + 2 * (engagement.get("shares") or 0)


def keep(element):
    content = element.get("content") or ""
    return (not element.get("repostId") and len(content.split()) >= 40 and "snowflake" in content.casefold()
            and PRODUCT.search(content) and not PERSONAL.search(content))


def fixed_profiles():
    """({profile URL: name}, posts to keep) from the config; empty without one."""
    config = digest_config.load_if_present()
    if not config:
        return {}, 0
    return {profile["url"]: profile["name"] for profile in config["fixed_reference_profiles"]}, config["fixed_reference_keep"]


def queries(company, keywords, posted, fixed=()):
    plan = [{"profile": profile, "page": "1"} for profile in fixed]
    plan += [{"authorsCompany": company, "postedLimit": posted, "sortBy": "relevance", "page": str(page)} for page in (1, 2, 3)]
    plan += [{"search": keyword, "postedLimit": posted, "sortBy": "relevance", "page": "1"} for keyword in keywords]
    return plan[:MAX_PAGES]


def record(element):
    author = element.get("author") or {}
    return {
        "url": element["linkedinUrl"], "author": author.get("name"), "author_info": author.get("info"),
        "posted": (element.get("postedAt") or {}).get("date"), "score": score(element.get("engagement") or {}),
        "engagement": {k: (element.get("engagement") or {}).get(k) for k in ("likes", "comments", "shares")},
        "has_image": bool(element.get("postImages")), "words": len(element["content"].split()),
        "content": element["content"],
    }


def rank(found, fixed_found, fixed_keep):
    """Fixed authors' recent best first, marked so the renderer can require one as a model."""
    best_fixed = sorted(fixed_found.values(), key=lambda post: post["score"], reverse=True)[:fixed_keep]
    for post in best_fixed:
        post["fixed"] = True
    return best_fixed + sorted((post for url, post in found.items() if url not in fixed_found),
                               key=lambda post: post["score"], reverse=True)[:KEEP]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Run folder; writes references.json and raw pages")
    parser.add_argument("--company", default=DEFAULT_COMPANY, help="LinkedIn company URL whose employees' posts to include")
    parser.add_argument("--keyword", action="append", help="Extra search keyword (repeatable); defaults cover Snowflake features")
    parser.add_argument("--posted", default="week", choices=["24h", "week", "month"])
    args = parser.parse_args()
    raw = args.output / "references-raw"
    raw.mkdir(parents=True, exist_ok=True)
    key = api_key()
    fixed, fixed_keep = fixed_profiles()
    found, fixed_found = {}, {}
    for number, params in enumerate(queries(args.company, args.keyword or DEFAULT_KEYWORDS, args.posted, fixed), 1):
        data = fetch(params, key)
        (raw / f"page-{number}.json").write_text(json.dumps({"params": params, "response": data}, indent=2))
        for element in data.get("elements", []):
            if keep(element):
                target = fixed_found if params.get("profile") in fixed else found
                target[element["linkedinUrl"]] = record(element)
        time.sleep(1)
    ranked = rank(found, fixed_found, fixed_keep)
    fixed_urls = [post["url"] for post in ranked if post.get("fixed")]
    if len(ranked) - len(fixed_urls) < 3:
        raise SystemExit(f"Only {len(ranked) - len(fixed_urls)} usable reference posts; widen --posted")
    if fixed and not fixed_urls:
        raise SystemExit("No usable posts from the fixed reference authors; check fixed_reference_profiles")
    (args.output / "references.json").write_text(json.dumps(
        {"pulled_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "posted": args.posted, "posts": ranked}, indent=2, ensure_ascii=False) + "\n")
    summary = {"references": str(args.output / "references.json"), "posts": len(ranked),
               "top_scores": [post["score"] for post in ranked if not post.get("fixed")][:5]}
    if fixed:
        summary["fixed"] = fixed_urls
    print(json.dumps(summary))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        sys.exit(f"HarvestAPI error {error.code}; no references written")

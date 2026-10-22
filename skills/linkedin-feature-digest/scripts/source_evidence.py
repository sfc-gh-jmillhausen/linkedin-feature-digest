"""Capture approved public pages locally and verify quotes before rendering."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import digest_config

MAX_BYTES = 2_000_000


def approved(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in digest_config.load()["public_hosts"] or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Source must use an approved official HTTPS host")
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        approved(new_url)
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, value):
        if not self.skip:
            self.parts.append(value)


def normalize(value):
    return re.sub(r"\s+", " ", value).strip()


def source_key(url):
    return hashlib.sha256(url.encode()).hexdigest()


def public_urls(data):
    posts = data.get("posts", [{"url": data.get("post_url")}])
    urls = {approved(post["url"]) for post in posts}
    for feature in data["features"]:
        if feature["classification"] == "public":
            urls.update(approved(source["url"]) for source in feature["sources"])
        if feature["impact"]["kind"] == "published":
            urls.add(approved(feature["impact"]["source_url"]))
    return sorted(urls)


def capture(data, directory):
    urls = public_urls(data)
    directory.mkdir(parents=True, exist_ok=True)
    opener = build_opener(SafeRedirect())
    for url in urls:
        request = Request(url, headers={"User-Agent": "Snowflake-Weekly-Brief-Source-Check/1.0"})
        with opener.open(request, timeout=30) as response:
            approved(response.url)
            if response.status != 200:
                raise ValueError(f"Source HTTP status: {response.status}")
            payload = response.read(MAX_BYTES + 1)
            if len(payload) > MAX_BYTES:
                raise ValueError("Source exceeds capture size limit")
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "text/plain", "text/markdown"}:
                raise ValueError(f"Unsupported source type: {content_type}")
            encoding = response.headers.get_content_charset() or "utf-8"
            raw = payload.decode(encoding)
            parser = PageText()
            if content_type == "text/html":
                parser.feed(raw)
                content = normalize(" ".join(parser.parts))
            else:
                content = normalize(raw)
            if len(content) < 100:
                raise ValueError("Source text is empty or too short")
            record = {"url": url, "final_url": response.url, "status": response.status,
                      "fetched_at": datetime.now(timezone.utc).isoformat(),
                      "content_type": content_type, "encoding": encoding, "sha256": hashlib.sha256(payload).hexdigest(),
                      "text": content}
        key = source_key(url)
        (directory / f"{key}.raw").write_bytes(payload)
        (directory / f"{key}.json").write_text(json.dumps(record, ensure_ascii=True, indent=2))
        print(json.dumps({"url": url, "status": 200, "evidence": str(directory / f"{key}.json")}))


def verify_evidence(data, directory):
    records = {}
    for url in public_urls(data):
        key = source_key(url)
        record = json.loads((directory / f"{key}.json").read_text())
        payload = (directory / f"{key}.raw").read_bytes()
        if record["url"] != url or record["status"] != 200 or record["sha256"] != hashlib.sha256(payload).hexdigest():
            raise ValueError(f"Invalid capture for {url}")
        approved(record["final_url"])
        parser = PageText()
        if record["content_type"] == "text/html":
            parser.feed(payload.decode(record.get("encoding", "utf-8")))
            actual = normalize(" ".join(parser.parts))
        else:
            actual = normalize(payload.decode(record.get("encoding", "utf-8")))
        if actual != record["text"]:
            raise ValueError(f"Captured text differs from raw source for {url}")
        records[url] = record
    for feature in data["features"]:
        if feature["classification"] != "public":
            continue
        for source in feature["sources"]:
            quote = normalize(source["excerpt"])
            if len(quote) < 30 or quote not in records[source["url"]]["text"]:
                raise ValueError(f"Use a verbatim excerpt from captured page: {feature['title']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture(json.loads(args.input.read_text()), args.output)
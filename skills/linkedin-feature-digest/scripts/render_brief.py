"""Validate up to five sourced features and prepare an email-only brief. No network."""

import argparse
import base64
import html
import json
import math
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from source_evidence import source_key, verify_evidence
import digest_config
import graphics

ROOT = Path(__file__).resolve().parent
COMPOSER = "https://www.linkedin.com/sharing/compose"
MAX_FEATURES = 5
CATEGORIES = {"Data Engineering", "Data Science & ML", "Security & Governance", "AI", "Analytics", "Platform & Applications"}


def settings():
    return digest_config.load()
SHARING_LABELS = {
    "internal": "Internal only - do not forward to customers",
    "external": "Marked for external sharing - review before sharing",
    "unverified": "Sharing unverified - internal use only",
}
FEATURE_FIELDS = (
    ("Who cares", "buyer"),
    ("The pain", "pain"),
    ("Business example", "business_example"),
    ("Common alternative", "before"),
    ("What Snowflake simplifies", "enables"),
    ("How to sell it", "talk_track"),
)
POST_SHAPES = {
    # Structures seen in high-engagement Snowflake product posts.
    "result_first": "Result first",
    "old_problem_now": "Old problem, now",
    "tried_it": "I tried it",
    "question_then_facts": "Question, then facts",
    "roundup": "Short roundup",
    "short_take": "Short take",
    "who_for": "Who it's for",
}
SHORT_TAKE_MAX_WORDS = 60
POST_WORDS = (40, 220)
# Two ready-to-paste opinions and one draft with a line only the user can write.
VOICES = {"opinion": 2, "fill_in": 1}
FILL_IN = re.compile(r"\[[^\[\]]{8,160}\]")
CODE = re.compile(r"`|;\s*$|=>|\b(?:SELECT|ALTER|CREATE|CALL|INSERT|UPDATE|GRANT|DROP)\s+[A-Z_(*]", re.M)
LINKEDIN_POST = "https://www.linkedin.com/posts/"
COPY_WORDS = 7
# Every scheduled issue carries at least one AI feature; the prompt aims for two.
AI_CATEGORY = "AI"
MIN_AI_FEATURES = 1
SALES_GROUPS = (
    ("The pain", (("Who cares", "buyer"), ("The pain", "pain"))),
    ("The value", (
        ("What Snowflake simplifies", "enables"),
        ("Common alternative", "before"),
        ("Business example", "business_example"),
    )),
)


def post_options(data):
    """Keep historical single-post fixtures readable; new issues use posts."""
    return data.get("posts", [{"text": data.get("post"), "url": data.get("post_url")}])


def option_title(number, post):
    """The shape label shows the issue's variety at a glance."""
    title = f"Option {number}: {post['angle']}"
    if not post.get("shape"):
        return title
    label = POST_SHAPES[post["shape"]]
    return f"{title} ({label}, needs your line)" if post.get("voice") == "fill_in" else f"{title} ({label})"


def image_id(number):
    return f"option-{number}"


def feature_sources(post, features):
    """Public source URLs of the feature this option is about, including its link."""
    related = {post["url"]}
    for item in features:
        sources = {source["url"] for source in item["sources"]}
        if item["classification"] == "public" and post["url"] in sources:
            related |= sources
    return related


def validate_graphic(post, features):
    """A made explainer diagram about this option's feature; never a page screenshot."""
    if any(key in post for key in ("visual", "visual_gap", "card", "image")):
        raise ValueError("Release screenshots and image cards are retired; give each option a graphic spec")
    spec = post.get("graphic")
    if spec is None:
        return
    if not isinstance(spec, dict) or "status" in spec:
        raise ValueError("A graphic is a spec without a status pill: title, subtitle, source_url, diagram, callouts, code, caption")
    source_url(spec.get("source_url"))
    if spec["source_url"] not in feature_sources(post, features):
        raise ValueError("Graphic source_url must be a captured source of this option's feature")
    # Builds the graphic HTML without rendering, so length and structure errors surface early.
    graphics.page_html(spec)


def verbatim(value, page_text):
    """value occurs in the page text; <placeholder> tokens stand for any value.

    Whitespace is ignored: captured code blocks space out every token (t . customer_id).
    """
    def squash(item):
        return re.sub(r"\s+", "", item.replace("\u2019", "'"))
    parts = re.split(r"<[^>]+>", squash(value))
    # A placeholder stands for one short value, not a stretch of the page.
    pattern = r"(?:<[^>]+>|.{1,60}?)".join(re.escape(part) for part in parts)
    return re.search(pattern, squash(page_text)) is not None


def check_graphic_sources(data, evidence_dir):
    """Every code line and quote on a graphic is verbatim on one of its feature's captured pages."""
    for number, post in enumerate(post_options(data), 1):
        if not post.get("graphic"):
            continue
        pages = []
        for url in sorted(feature_sources(post, data["features"])):
            record = json.loads((Path(evidence_dir) / f"{source_key(url)}.json").read_text())
            pages.append(record["text"])
        for value in graphics.verbatim_strings(post["graphic"]):
            if not any(verbatim(value, page) for page in pages):
                raise ValueError(f"Option {number} graphic shows text that is not on its feature's captured pages: {value}")


def render_graphics(data, output):
    """{option number: PNG bytes}, saved as graphics/option-N.png."""
    rendered = {}
    folder = output / "graphics"
    for number, post in enumerate(post_options(data), 1):
        if post.get("graphic"):
            folder.mkdir(exist_ok=True)
            path = folder / f"{image_id(number)}.png"
            graphics.render(post["graphic"], path)
            rendered[number] = path.read_bytes()
    return rendered


def phrases(value):
    words = re.findall(r"[a-z0-9']+", value.casefold())
    return {tuple(words[index:index + COPY_WORDS]) for index in range(len(words) - COPY_WORDS + 1)}


def load_references(path):
    posts = json.loads(Path(path).read_text())["posts"]
    return {post["url"]: post for post in posts}


def validate_modeling(posts, public, references=None):
    """Voice mix, fill-in slot, no code, a real reference post, one on a fixed reference."""
    if not any(post.get("voice") or post.get("model") for post in posts):
        return
    voices = [post.get("voice") for post in posts]
    if sorted(voices, key=str) != sorted([voice for voice, count in VOICES.items() for _ in range(count)]):
        raise ValueError("Use two opinion options and one fill_in option")
    models = []
    for post in posts:
        if post["voice"] == "fill_in" and len(FILL_IN.findall(post["text"])) != 1:
            raise ValueError("A fill_in option needs exactly one [bracketed line] for the user")
        if post["voice"] == "opinion" and ("[" in post["text"] or "]" in post["text"]):
            raise ValueError("Opinion options must be ready to paste, without brackets")
        if post.get("shape") == "tried_it" and post["voice"] != "fill_in":
            raise ValueError("I tried it needs the user's own line; use fill_in")
        model = post.get("model") or {}
        for key in ("author", "pattern"):
            text(model.get(key))
        if not str(model.get("url", "")).startswith(LINKEDIN_POST):
            raise ValueError("Each option must name the LinkedIn post it is modeled on")
        if references is not None:
            if model["url"] not in references:
                raise ValueError("Model post must come from this run's references")
            if phrases(post["text"]) & phrases(references[model["url"]]["content"]):
                raise ValueError("Option copies wording from its model post; borrow the structure only")
        models.append(model["url"])
    if len(set(models)) != len(models):
        raise ValueError("Model each option on a different post")
    # Set only when the config names fixed_reference_profiles; then one option must use them.
    fixed = {url for url, post in (references or {}).items() if post.get("fixed")}
    if fixed and not fixed & set(models):
        raise ValueError("Model at least one option on a fixed reference author's post")


def validate_shapes(posts, previous_shapes=None):
    shapes = [post.get("shape") for post in posts]
    if not any(shapes):
        return
    if not all(shape in POST_SHAPES for shape in shapes):
        raise ValueError("Each post needs a shape from: " + ", ".join(POST_SHAPES))
    if len(set(shapes)) != len(shapes):
        raise ValueError("Post options must use different shapes")
    for post in posts:
        if post["shape"] == "short_take" and len(post["text"].split()) > SHORT_TAKE_MAX_WORDS:
            raise ValueError(f"A short take must be {SHORT_TAKE_MAX_WORDS} words or fewer")
    if previous_shapes and set(shapes) == set(previous_shapes):
        raise ValueError("Rotate shapes: this issue repeats the previous issue's exact mix")


def email_html(data, images=()):
    """SMTP body fragment, not a standalone report; compatible with SafeHTML.

    images lists option numbers whose graphic travels inline as cid:option-N.
    """
    def paragraph(value, style=""):
        return f'<p style="margin:0 0 12px;line-height:1.55;{style}">{html.escape(value)}</p>'

    def link(label, url):
        return (
            '<p style="margin:0 0 8px;font-size:14px;line-height:1.6;">'
            f'<a href="{html.escape(url, quote=True)}" '
            'style="color:#0879A5;text-decoration:underline;overflow-wrap:anywhere;">'
            f'{html.escape(label)}</a></p>'
        )

    def field(heading, value):
        return (
            '<p style="margin:0 0 12px;line-height:1.55;"><strong>'
            + html.escape(heading) + ':</strong> ' + html.escape(value) + '</p>'
        )

    def heading(value):
        return paragraph(value, "margin:20px 0 8px;font-size:16px;line-height:1.3;font-weight:bold;color:#123548;")

    issue_date = date.fromisoformat(data["date"]).strftime("%B %d, %Y")
    rule = '<hr style="border:0;border-top:1px solid #DAE5EB;margin:32px 0;">'
    parts = [
        '<div class="weekly-brief" style="max-width:660px;box-sizing:border-box;'
        'margin:0 auto;font-family:Arial,Helvetica,sans-serif;'
        'font-size:14px;color:#253F4D;background-color:#FFFFFF;overflow-wrap:anywhere;'
        '">',
        '<table class="digest-banner" role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="background-color:#123548;border-top:6px solid #29B5E8;">'
        '<tr><td style="padding:20px;">',
        paragraph("Weekly Feature Digest", "font-size:24px;line-height:1.2;font-weight:bold;color:#FFFFFF;margin:0 0 12px;"),
        paragraph(f"Snowflake / {issue_date}", "font-size:14px;color:#D3EBF5;margin:0;"),
        '</td></tr></table>',
        '<div style="padding:20px;">',
        paragraph("Your LinkedIn options" if "posts" in data else "Your next LinkedIn post", "font-size:20px;line-height:1.25;font-weight:bold;color:#123548;margin:0 0 20px;"),
    ]
    for number, post in enumerate(post_options(data), 1):
        if "posts" in data:
            parts.append(heading(option_title(number, post)))
        parts.append('<div class="post-copy">')
        # Keep single line breaks (arrow/list lines) so the copied post matches the plain text.
        parts.extend(paragraph(value, "font-size:15px;color:#123548;").replace("\n", "<br>\n") for value in post["text"].split("\n\n"))
        parts += ['</div>', link(post["url"], post["url"])]
        if number in images:
            # 1080x1350 portrait graphic, shown at 480 px so the next option stays in reach.
            parts.append(
                '<p class="option-image" style="margin:8px 0 12px;">'
                f'<img src="cid:{image_id(number)}" alt="{html.escape(graphics.alt_text(post["graphic"]), quote=True)}" '
                'width="480" style="width:100%;max-width:480px;height:auto;border:1px solid #DAE5EB;"></p>'
            )
    parts += [
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0;">'
        '<tr><td style="background-color:#29B5E8;border-radius:4px;">'
        f'<a href="{COMPOSER}" style="color:#093047;font-size:16px;font-weight:bold;'
        'text-decoration:none;line-height:48px;padding:14px 20px;">Post to Linkedin</a>'
        '</td></tr></table>',
        rule,
        paragraph("This week's sales brief", "font-size:20px;line-height:1.25;font-weight:bold;color:#123548;margin:0 0 12px;"),
    ]
    feature_number = 0
    for classification in ("public", "internal"):
        items = [item for item in data["features"] if item["classification"] == classification]
        if classification == "internal" and items:
            parts.append(paragraph("INTERNAL ONLY - DO NOT POST OR FORWARD EXTERNALLY", "font-size:16px;font-weight:bold;color:#123548;"))
        for item in items:
            feature_number += 1
            label, impact_paragraphs = estimate_parts(item["impact"])
            parts += [
                '<div class="feature" style="margin:32px 0 0;">',
                '<div class="feature-header" style="padding:16px;background-color:#F2F8FB;">',
                paragraph(f"{feature_number}. {item['title']}", "font-size:18px;line-height:1.25;font-weight:bold;color:#123548;margin:0 0 12px;"),
                paragraph(item["category"], "font-size:14px;font-weight:bold;color:#0879A5;margin:0 0 4px;"),
                paragraph(item["date"] + " / " + item["status"], "font-size:14px;color:#536A78;margin:0;"),
                '</div><div style="padding-top:20px;">',
                paragraph(item["change"]),
                '</div><div class="talk-track">', heading("What to say"),
                paragraph(item["talk_track"], "font-size:15px;color:#123548;"),
                '</div>',
            ]
            for group_title, fields in SALES_GROUPS:
                parts += ['<div class="sales-group">', heading(group_title)]
                for field_title, key in fields:
                    parts.append(paragraph(item[key]) if key == "pain" else field(field_title, item[key]))
                parts.append('</div>')
            parts += [
                '<div class="pain-value" style="margin:24px 0;padding:20px 0;border-top:1px solid #DAE5EB;border-bottom:1px solid #DAE5EB;">',
                paragraph(label, "font-size:16px;font-weight:bold;color:#123548;margin:0 0 8px;"),
                paragraph(impact_paragraphs[0], "font-size:14px;color:#253F4D;margin:0;"),
            ]
            parts.extend(paragraph(value, "font-size:14px;color:#536A78;margin:12px 0 0;") for value in impact_paragraphs[1:])
            parts += ['</div>', '<div class="sales-resources">', heading("Useful links")]
            parts.extend(link(source["url"] if classification == "public" else source["label"], source["url"]) for source in item["sources"])
            if item["impact"]["kind"] == "published":
                parts.append(link("Impact source", item["impact"]["source_url"]))
            parts.append(paragraph("Slides and people", "margin:20px 0 12px;font-size:16px;font-weight:bold;color:#123548;"))
            for resource_label, resource_link, detail in resource_rows(item["sales_resources"]):
                parts.append('<div style="margin:0 0 16px;">')
                parts.append(link(resource_label, resource_link) if resource_link else paragraph(resource_label, "font-size:14px;color:#536A78;"))
                if detail:
                    parts.append(paragraph(detail, "font-size:14px;color:#536A78;margin:0;"))
                parts.append('</div>')
            parts.append('</div>')
            parts += ['</div>', rule]
    parts += [paragraph("Coverage: " + data["coverage"], "font-size:13px;color:#536A78;"), '</div></div>']
    return "\n".join(parts)


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonempty text")
    if "\u2014" in value:
        raise ValueError("Use a plain hyphen, not an em dash")
    return value.strip()


def source_url(value, internal=False):
    value = text(value)
    parsed = urlsplit(value)
    allowed = settings()["slack_hosts"] if internal else settings()["public_hosts"]
    if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.password:
        raise ValueError(f"Unapproved source URL: {value}")
    if internal:
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "archives" or not parts[1].startswith("C") or not parts[2].startswith("p") or not parts[2][1:].isdigit():
            raise ValueError("Internal sources require a specific Slack message permalink")
    return value


def resource_url(value, kind):
    """Resource links are not public product evidence; allow only known destinations."""
    if isinstance(value, str) and (any(ord(char) < 32 for char in value) or "\\" in value):
        raise ValueError("Invalid resource URL")
    value = text(value)
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.query or parsed.fragment:
        raise ValueError("Resources require canonical HTTPS links without query parameters")
    slack_hosts, team = settings()["slack_hosts"], settings()["slack_team"]
    if kind == "slide":
        valid = (
            (parsed.hostname in settings()["compass_hosts"] and re.fullmatch(r"/Link/Content/[A-Za-z0-9]+", parsed.path))
            or (parsed.hostname == "docs.google.com" and re.fullmatch(r"/presentation/d/[A-Za-z0-9_-]+/edit", parsed.path))
            or (parsed.hostname == "drive.google.com" and re.fullmatch(r"/file/d/[A-Za-z0-9_-]+/view", parsed.path))
            or (parsed.hostname in slack_hosts and re.fullmatch(r"/files/[UW][A-Z0-9]+/F[A-Z0-9]+(?:/[A-Za-z0-9_.-]+)?", parsed.path))
            or (parsed.hostname in slack_hosts and re.fullmatch(r"/archives/C[A-Z0-9]+/p[0-9]+", parsed.path))
        )
    elif kind == "slack_message":
        valid = parsed.hostname in slack_hosts and re.fullmatch(r"/archives/C[A-Z0-9]+/p[0-9]+", parsed.path)
    elif kind == "pm":
        valid = (
            (parsed.hostname in slack_hosts and re.fullmatch(r"/messages/[UW][A-Z0-9]+", parsed.path))
            or (parsed.hostname == "app.slack.com" and re.fullmatch(rf"/client/{team}/[UW][A-Z0-9]+", parsed.path))
        )
    elif kind == "channel":
        valid = parsed.hostname in slack_hosts and re.fullmatch(r"/archives/C[A-Z0-9]+", parsed.path)
    else:
        valid = False
    if not valid:
        raise ValueError(f"Unapproved {kind} resource URL")
    return value


def validate_resources(resources, briefing_date):
    if not isinstance(resources, dict):
        raise ValueError("Every feature needs sales_resources, including explicit gaps")
    checked = date.fromisoformat(text(resources.get("checked_on")))
    if checked > briefing_date:
        raise ValueError("Resource check cannot be after briefing date")
    text(resources.get("notes"))
    slides = resources.get("slides")
    if not isinstance(slides, list) or len(slides) > 2:
        raise ValueError("Include zero to two relevant decks total per feature")
    seen = set()
    for slide in slides:
        url = resource_url(slide["url"], "slide")
        if url in seen:
            raise ValueError("Deduplicate decks across Compass and Slack")
        seen.add(url)
        for field in ("title", "pages", "relevance", "sharing_basis", "excerpt"):
            text(slide.get(field))
        if slide.get("sharing") not in SHARING_LABELS:
            raise ValueError("Deck sharing must be internal, external, or unverified")
        origin = slide.get("discovered_via", "compass")
        if origin not in {"compass", "slack"}:
            raise ValueError("Deck discovered_via must be compass or slack")
        if origin == "compass" and urlsplit(url).hostname not in settings()["compass_hosts"]:
            raise ValueError("Non-Compass decks require Slack provenance")
        if origin == "slack":
            resource_url(slide.get("evidence_url"), "slack_message")
            if len(text(slide.get("evidence_excerpt"))) < 30:
                raise ValueError("Slack deck needs original-message evidence")
            shared_on = date.fromisoformat(text(slide.get("shared_on")))
            if shared_on > checked:
                raise ValueError("Deck share date cannot be after its resource check")
            if slide.get("content_status") not in {"reviewed", "not_accessible"}:
                raise ValueError("Slack deck content_status must be reviewed or not_accessible")
            if slide["content_status"] == "not_accessible":
                if slide["pages"] != "Slide numbers not verified" or slide["sharing"] == "external":
                    raise ValueError("Unread decks cannot claim verified slides or external sharing")
    for kind in ("pm", "channel"):
        if kind not in resources:
            raise ValueError(f"Missing {kind} resource; use null when unverified")
        item = resources[kind]
        if item is None:
            continue
        if not isinstance(item, dict):
            raise ValueError(f"Invalid {kind} resource")
        text(item.get("name"))
        resource_url(item["url"], kind)
        if len(text(item.get("excerpt"))) < 30:
            raise ValueError("Resource ownership/relevance needs supporting evidence")
        if kind == "pm":
            user_id = text(item.get("user_id"))
            if not re.fullmatch(r"[UW][A-Z0-9]+", user_id) or urlsplit(item["url"]).path not in (f"/messages/{user_id}", f"/client/{settings()['slack_team']}/{user_id}"):
                raise ValueError("PM link must match the verified Slack user ID")
            text(item.get("role"))
            source_url(item["evidence_url"], internal=True)


def resource_rows(resources):
    """Shared labels and details keep HTML and plain-text resources in sync."""
    rows = []
    for slide in resources["slides"]:
        origin = slide.get("discovered_via", "compass")
        provenance = ""
        if origin == "slack":
            review = "" if slide["content_status"] == "reviewed" else " Deck content not reviewed; access required."
            provenance = f" Shared in Slack on {slide['shared_on']}.{review}"
        rows.append((
            f"{slide['title']} | {slide['pages']}", slide["url"],
            f"{SHARING_LABELS[slide['sharing']]}.{provenance} {slide['relevance']}",
        ))
        if origin == "slack":
            rows.append(("Original Slack share", slide["evidence_url"], ""))
    if not resources["slides"]:
        rows.append(("Slides: no relevant deck verified.", None, ""))
    pm = resources["pm"]
    if pm:
        rows.append((f"Product contact: {pm['name']}", f"https://app.slack.com/client/{settings()['slack_team']}/{pm['user_id']}", ""))
    else:
        rows.append(("PM: not verified.", None, ""))
    channel = resources["channel"]
    if channel:
        rows.append((f"Feature channel: {channel['name']}", channel["url"], ""))
    else:
        rows.append(("Feature channel: not verified.", None, ""))
    return rows


def estimate_parts(impact):
    kind = impact["kind"]
    if kind == "published":
        source_url(impact["source_url"])
        return "Published evidence", [text(impact["detail"]), "Context: " + text(impact["context"])]
    if kind == "qualitative":
        return "Value without a made-up number", [text(impact["detail"]), "Limits: " + text(impact["exclusions"])]
    if kind != "illustrative":
        raise ValueError("Impact kind must be illustrative, published, or qualitative; measurement-only briefs are not supported")
    values = [impact[name] for name in ("baseline", "volume")]
    if "proposed" in impact:
        values.append(impact["proposed"])
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Scenario inputs must be finite, nonnegative numbers")
    baseline, volume = impact["baseline"], impact["volume"]
    proposed = impact.get("proposed")
    if baseline == 0 or volume == 0 or (proposed is not None and proposed > baseline):
        raise ValueError("Avoid negative savings or empty scenarios")
    unit, period = text(impact["unit"]), text(impact["period"])
    baseline_total = baseline * volume
    proposed_total = None if proposed is None else proposed * volume
    if not math.isfinite(baseline_total) or (proposed_total is not None and not math.isfinite(proposed_total)):
        raise ValueError("Scenario totals must be finite")
    result = (
        f"Status quo: {baseline_total:g} {unit} per {period} "
        f"({baseline:g} x {volume:g}). "
    )
    if proposed is not None:
        result += (
            f"Conditional scenario: {proposed_total:g} {unit} per {period} "
            f"({proposed:g} x {volume:g}); "
            f"the difference is {(baseline - proposed) * volume:g} {unit} per {period}. "
        )
    else:
        result += "This sizes the existing burden, not the amount Snowflake will remove. "
    return "Example scenario", [
        result.strip(), "Assumptions: " + text(impact["assumptions"]),
        "Limits: " + text(impact["exclusions"])
        + " Time returned is capacity, not automatic cash savings.",
    ]


def estimate(impact):
    label, paragraphs = estimate_parts(impact)
    return label, " ".join(paragraphs)


def validate(data, previous_shapes=None, references=None):
    date.fromisoformat(data["date"])
    posts = post_options(data)
    if "posts" in data:
        if not isinstance(posts, list) or len(posts) != 3:
            raise ValueError("Include exactly three post options")
        if "post" in data or "post_url" in data:
            raise ValueError("Use posts instead of mixing legacy post fields")
        for post in posts:
            text(post.get("angle"))
        if len({text(post.get("text")).casefold() for post in posts}) != 3:
            raise ValueError("Post options must be distinct")
        if len({text(post["angle"]).casefold() for post in posts}) != 3:
            raise ValueError("Post option angles must be distinct")
        validate_shapes(posts, previous_shapes)
    for post in posts:
        low, high = POST_WORDS
        if not low <= len(text(post["text"]).split()) <= high:
            raise ValueError(f"Post must be {low}-{high} words, excluding the link")
        if CODE.search(post["text"]):
            raise ValueError("Posts must not include code or SQL")
        source_url(post["url"])
    text(data["coverage"])
    if not 1 <= len(data["features"]) <= MAX_FEATURES:
        raise ValueError("Include 1-5 fully sourced features total, including internal items")
    titles = [text(item.get("title")).casefold() for item in data["features"]]
    if len(set(titles)) != len(titles):
        raise ValueError("Include distinct features, not duplicate padding")
    for post in posts:
        if not any(
            item["classification"] == "public"
            and any(source["url"] == post["url"] for source in item["sources"])
            for item in data["features"]
        ):
            raise ValueError("Post must cover one of the included public features")
    if "posts" in data:
        public = {source["url"] for item in data["features"] if item["classification"] == "public" for source in item["sources"]}
        validate_modeling(posts, public, references)
        for post in posts:
            validate_graphic(post, data["features"])
    for item in data["features"]:
        internal = item["classification"] == "internal"
        if item["classification"] not in {"public", "internal"}:
            raise ValueError("Feature must be public or internal")
        for field in ("title", "status", "change", *(key for _, key in FEATURE_FIELDS)):
            text(item.get(field))
        if item.get("category") not in CATEGORIES:
            raise ValueError("Feature category must use an approved sales category")
        validate_resources(item.get("sales_resources"), date.fromisoformat(data["date"]))
        date.fromisoformat(item["date"])
        if not item["sources"]:
            raise ValueError("Every feature needs evidence")
        for source in item["sources"]:
            source_url(source["url"], internal)
            text(source["label"])
            text(source["excerpt"])
            if source["method"] not in {"page_text", "slack_message"}:
                raise ValueError("Search snippets and index-only summaries are not evidence")
            if internal != (source["method"] == "slack_message"):
                raise ValueError("Source method must match feature classification")
        estimate(item["impact"])
    return data


def render(data, output, evidence_dir=None, smtp_source_id=None, require_three_posts=False, previous_shapes=None, references=None):
    reference_posts = load_references(references) if references else None
    validate(data, previous_shapes, reference_posts)
    if require_three_posts and "posts" not in data:
        raise ValueError("Scheduled issues require three post options")
    if require_three_posts and not all(post.get("shape") for post in data["posts"]):
        raise ValueError("Scheduled issues require a shape on every post option")
    if require_three_posts and (reference_posts is None or not all(post.get("voice") for post in data["posts"])):
        raise ValueError("Scheduled issues require voices and model posts checked against --references")
    if require_three_posts and not all(post.get("graphic") for post in data["posts"]):
        raise ValueError("Scheduled issues require a graphic spec on every option")
    if require_three_posts and sum(item["category"] == AI_CATEGORY for item in data["features"]) < MIN_AI_FEATURES:
        raise ValueError("Scheduled issues require at least one AI feature; widen the AI lookback before sending without one")
    if smtp_source_id is not None:
        if evidence_dir is None:
            raise ValueError("SMTP output requires captured evidence")
        if not smtp_source_id.startswith("linkedin-") or not all(
            char.isascii() and (char.isalnum() or char in "-_") for char in smtp_source_id
        ) or len(smtp_source_id) > 120:
            raise ValueError("SMTP source ID must be a short linkedin- identifier")
    if evidence_dir is not None:
        verify_evidence(data, evidence_dir)
        check_graphic_sources(data, evidence_dir)
    elif any(post.get("graphic") for post in post_options(data)):
        raise ValueError("Graphics require captured evidence for their code and quotes")
    output.mkdir(parents=True, exist_ok=True)
    visuals = render_graphics(data, output)
    image_paths = {number: output.resolve() / "graphics" / f"{image_id(number)}.png" for number in visuals}
    public = [item for item in data["features"] if item["classification"] == "public"]
    internal = [item for item in data["features"] if item["classification"] == "internal"]
    lines = [
        "# Weekly Feature Digest | " + data["date"],
        "## Your LinkedIn options" if "posts" in data else "## Your next LinkedIn post",
    ]
    for number, post in enumerate(post_options(data), 1):
        if "posts" in data:
            lines.append(f"### {option_title(number, post)}")
        lines.extend([post["text"], post["url"]])
        if number in image_paths:
            lines.append(f"Graphic: {graphics.alt_text(post['graphic'])}")
    lines.extend([f"Post to Linkedin: {COMPOSER}", "---", "## This week's sales brief"])
    feature_number = 0
    for section, items in [("Public features", public), ("INTERNAL ONLY - DO NOT POST OR FORWARD EXTERNALLY", internal)]:
        if not items:
            continue
        lines += [f"## {section}"]
        for item in items:
            feature_number += 1
            label, impact = estimate(item["impact"])
            lines += [f"### {feature_number}. {item['title']}", f"Category: {item['category']}", f"{item['date']} / {item['status']}", item["change"]]
            lines += ["**What to say**", item["talk_track"]]
            for group_title, fields in SALES_GROUPS:
                lines.append(f"**{group_title}**")
                for heading, key in fields:
                    lines.append(item[key] if key == "pain" else f"**{heading}:** {item[key]}")
            lines += [f"**{label}:** {impact}", "**Useful links**"]
            lines += [f"{source['label']}: {source['url']}" for source in item["sources"]]
            if item["impact"]["kind"] == "published":
                lines += [f"Impact source: {item['impact']['source_url']}"]
            lines.append("**Slides and people**")
            for resource_label, resource_link, detail in resource_rows(item["sales_resources"]):
                lines.append(f"{resource_label}: {resource_link}" if resource_link else resource_label)
                if detail:
                    lines.append(detail)
    lines += ["---", "### Coverage", data["coverage"]]
    email = "\n\n".join(lines) + "\n"
    (output / "email-body.md").write_text(email)
    (output / "email-payload.json").write_text(json.dumps({
        "subject": "Weekly Feature Digest | " + data["date"],
        "body_markdown": email,
    }, ensure_ascii=True, indent=2) + "\n")
    copies = []
    for number, post in enumerate(post_options(data), 1):
        label = f"## {option_title(number, post)}\n\n" if "posts" in data else ""
        notes = f"\n\nGraphic: {image_paths[number]}" if number in image_paths else ""
        copies.append(label + post["text"] + "\n\n" + post["url"] + notes)
    (output / "latest-post.md").write_text("\n\n".join(copies) + "\n")
    if smtp_source_id is not None:
        subject = "Weekly Feature Digest | " + data["date"]
        if smtp_source_id.startswith("linkedin-test-"):
            subject = "[Test] " + subject
        message = {
            "to": settings()["owner"], "subject": subject, "text": email,
            "html": email_html(data, visuals), "source_id": smtp_source_id,
        }
        if visuals:
            # Inline (cid) PNGs inside the message; safe-email-send rejects remote body images.
            message["inline_images"] = [{"cid": image_id(number), "png_base64": base64.b64encode(png).decode("ascii")}
                                        for number, png in visuals.items()]
        batch = {"scope": "individual", "messages": [message]}
        (output / "smtp-message.json").write_text(json.dumps(batch, ensure_ascii=True, indent=2) + "\n")
    print(json.dumps({"email_payload": str(output / "email-payload.json"), "features": len(data["features"]), "post_words": [len(post["text"].split()) for post in post_options(data)], "post_shapes": [post.get("shape") for post in post_options(data)], "images": [str(path) for path in image_paths.values()], "ai_features": sum(item["category"] == AI_CATEGORY for item in data["features"]), "validation": "passed"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, help="Require captured public source text and verbatim excerpts")
    parser.add_argument("--smtp-source-id", help="Build self-only SMTP payload; stable issue ID prevents duplicate sends")
    parser.add_argument("--require-three-posts", action="store_true", help="Require the current three-option issue schema")
    parser.add_argument("--previous-shapes", help="Comma-separated shapes from the last issue in history.json; an identical mix is rejected")
    parser.add_argument("--references", type=Path, help="references.json from reference_posts.py; model posts must come from it")
    args = parser.parse_args()
    previous = [shape.strip() for shape in args.previous_shapes.split(",") if shape.strip()] if args.previous_shapes else None
    render(json.loads(args.input.read_text()), args.output, args.evidence_dir, args.smtp_source_id, args.require_three_posts, previous, args.references)
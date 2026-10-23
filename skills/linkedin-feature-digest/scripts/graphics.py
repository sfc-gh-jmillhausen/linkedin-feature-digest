"""Render a post graphic spec to a 1080x1350 PNG explainer built around one
diagram: nodes and drawn connectors, optional numbered callouts and a short code
strip. Every string comes from the spec; the renderer adds layout and, when
configured, a logo. source_url is validated but not printed.

Needs Google Chrome (headless). CHROME_PATH or the config's chrome_path overrides
the macOS default. The optional logo is a PNG named by LINKEDIN_DIGEST_LOGO or the
config's graphic_logo; without one the header stays empty. Fonts are bundled.

Spec: {title, subtitle?, source_url, diagram, callouts?, code?, caption?}

diagram is one of:
  {"type": "lanes", "lanes": [a, b], "steps": [{lane, title, note?, code?, row?, from?, alt?, marker?}]}
      A two-actor sequence. Steps are numbered in order; alt steps are dashed and
      unnumbered. from is the 0-based index of the step an arrow comes from.
  {"type": "fanout", "input": {title, note?, quote?}, "hub": {title, note?},
   "side"?: {title, note?}, "outputs": [{title, note?, code?}]}          2-4 outputs
  {"type": "graph", "cols": 2-4, "mono"?: bool, "nodes": [{id, label, col, row, note?,
   badge?: {text, tone}, tag?, state?: error|selected, marker?}], "edges": [[from, to]],
   "region"?: {"nodes": [ids], "label", "code"?}}                       tone: good|warn|bad
callouts: [{marker, title, text}] up to 3; markers are A-C and match diagram markers.
code: {"code"} up to 5 lines of verbatim source code.
"""

import argparse
import base64
import html
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import digest_config

HERE = Path(__file__).resolve().parent
FONTS = HERE / "fonts"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WIDTH, HEIGHT = 1080, 1350
# Used only when no digest config exists (standalone CLI use).
HOSTS = frozenset({"docs.snowflake.com", "www.snowflake.com", "developers.snowflake.com"})
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SQL_WORDS = re.compile(r"\b(ALTER|SET|UNSET|CREATE|SELECT|FROM|WHERE|TABLE|GROUP|FAILOVER|REFRESH|"
                       r"PRIMARY|TRUE|FALSE|SHOW|GRANT|INSERT|UPDATE|INTO|VALUES|AND|OR|NOT|NULL)\b")
LIMITS = {"title": 70, "subtitle": 150, "node": 30, "note": 70, "inline_code": 40,
          "quote": 150, "lane": 28, "label": 28, "badge": 14, "tag": 24, "region": 40,
          "callout_title": 34, "callout_text": 110, "caption": 90, "code_lines": 5, "code_width": 56}


def settings():
    return digest_config.load_if_present() or {}


def chrome_path():
    return Path(os.environ.get("CHROME_PATH") or settings().get("chrome_path") or CHROME).expanduser()


def public_hosts():
    return settings().get("public_hosts") or HOSTS


def logo_data():
    """Base64 PNG for the header, or None when no logo is configured or the file is absent."""
    path = os.environ.get("LINKEDIN_DIGEST_LOGO") or settings().get("graphic_logo")
    if not path or not Path(path).expanduser().is_file():
        return None
    data = Path(path).expanduser().read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Graphic logo must be a PNG file")
    return base64.b64encode(data).decode()


def esc(value):
    return html.escape(str(value), quote=True)


def check(value, field, limit):
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"Graphic {field} is empty")
    if len(value) > limit:
        raise ValueError(f"Graphic {field} is over {limit} characters: {value[:40]}...")
    if "\u2014" in value:
        raise ValueError(f"Graphic {field} uses an em dash")
    return value


def text(value, field, limit=None):
    return esc(check(value, field, limit or LIMITS[field]))


def opt(item, key, field, cls, tag="div"):
    if not item.get(key):
        return ""
    return f'<{tag} class="{cls}">{text(item[key], field)}</{tag}>'


def inline_code(item):
    return f'<code>{text(item["code"], "inline_code")}</code>' if item.get("code") else ""


def marker(item):
    if item.get("marker") is None:
        return ""
    letter = str(item["marker"])
    if letter not in ("A", "B", "C"):
        raise ValueError("Graphic markers are A, B or C")
    return f'<span class="marker">{letter}</span>'


def highlight(code):
    lines = code.strip("\n").split("\n")
    if len(lines) > LIMITS["code_lines"] or max(len(line) for line in lines) > LIMITS["code_width"]:
        raise ValueError("Graphic code strip is too long for the card")
    out = []
    for line in lines:
        body, dash, comment = esc(line).partition("--")
        body = SQL_WORDS.sub(r'<span class="kw">\1</span>', body)
        out.append(body + (f'<span class="cm">--{comment}</span>' if dash else ""))
    return "\n".join(out)


def lanes_html(diagram):
    lanes, steps = diagram["lanes"], diagram["steps"]
    if len(lanes) != 2 or not 2 <= len(steps) <= 6:
        raise ValueError("Graphic lanes need 2 lanes and 2-6 steps")
    heads = "".join(f'<div class="lane-head" style="grid-column:{i + 1}">{text(name, "lane")}</div>'
                    for i, name in enumerate(lanes))
    cells, edges, row, number = [], [], 1, 0
    for index, step in enumerate(steps):
        lane = int(step["lane"])
        if lane not in (0, 1):
            raise ValueError("Graphic step lane must be 0 or 1")
        row = int(step.get("row", row + (1 if index else 0)))
        alt = bool(step.get("alt"))
        if not alt:
            number += 1
        badge = "" if alt else f'<span class="seq">{number}</span>'
        cells.append(
            f'<div class="node step{" alt" if alt else ""}" id="n{index}" '
            f'style="grid-column:{lane + 1};grid-row:{row + 1}">{marker(step)}'
            f'<div class="node-title">{badge}{text(step["title"], "node")}</div>'
            f'{inline_code(step)}{opt(step, "note", "note", "node-note")}</div>')
        if index:
            source = int(step.get("from", index - 1))
            if not 0 <= source < index:
                raise ValueError("Graphic step 'from' must point to an earlier step")
            edges.append((f"n{source}", f"n{index}", ("alt" if alt else "") + (" elbow" if int(steps[source]["lane"]) != lane else "")))
    rows = max(int(cell.split("grid-row:")[1].split('"')[0]) for cell in cells)
    body = (f'<div class="lane-bg" style="grid-column:1;grid-row:1/span {rows}"></div>'
            f'<div class="lane-bg" style="grid-column:2;grid-row:1/span {rows}"></div>{heads}{"".join(cells)}')
    return f'<div class="lanes" style="grid-template-rows:repeat({rows}, auto)">{body}</div>', edges


def fanout_html(diagram):
    outputs = diagram["outputs"]
    if not 2 <= len(outputs) <= 4:
        raise ValueError("Graphic fanout needs 2-4 outputs")
    source = diagram["input"]
    quote = f'<p class="quote">&ldquo;{text(source["quote"], "quote")}&rdquo;</p>' if source.get("quote") else ""
    hub = diagram["hub"]
    side = diagram.get("side")
    side_html = (f'<div class="node side" id="side">{marker(side)}<div class="node-title">{text(side["title"], "node")}</div>'
                 f'{opt(side, "note", "note", "node-note")}</div>') if side else '<div></div>'
    outs = "".join(
        f'<div class="node out" id="o{i}">{marker(o)}<div class="node-title">{text(o["title"], "node")}</div>'
        f'{inline_code(o)}{opt(o, "note", "note", "node-note")}</div>' for i, o in enumerate(outputs))
    edges = [("in", "hub", "v")] + [("hub", f"o{i}", "v") for i in range(len(outputs))]
    if side:
        edges.append(("side", "hub", "alt h"))
    return (f'<div class="fanout">'
            f'<div class="node input" id="in">{marker(source)}<div class="node-title">{text(source["title"], "node")}</div>'
            f'{quote}{opt(source, "note", "note", "node-note")}</div>'
            f'<div class="hub-row"><div></div><div class="node hub" id="hub">{marker(hub)}'
            f'<div class="node-title">{text(hub["title"], "node")}</div>{opt(hub, "note", "note", "node-note")}</div>'
            f'{side_html}</div>'
            f'<div class="outs" style="grid-template-columns:repeat({len(outputs)},1fr)">{outs}</div></div>'), edges


def graph_html(diagram):
    cols = int(diagram["cols"])
    nodes = diagram["nodes"]
    if not 2 <= cols <= 4 or not 3 <= len(nodes) <= 10:
        raise ValueError("Graphic graph needs 2-4 columns and 3-10 nodes")
    ids = {n["id"] for n in nodes}
    tones = {"good", "warn", "bad"}
    cells = []
    for node in nodes:
        state = node.get("state", "")
        if state not in ("", "error", "selected"):
            raise ValueError("Graphic node state must be error or selected")
        badge = ""
        if node.get("badge"):
            if node["badge"]["tone"] not in tones:
                raise ValueError("Graphic badge tone must be good, warn or bad")
            badge = f'<span class="badge {node["badge"]["tone"]}">{text(node["badge"]["text"], "badge")}</span>'
        tag = opt(node, "tag", "tag", "tag", "span")
        cells.append(
            f'<div class="node gnode {state}" id="g-{esc(node["id"])}" '
            f'style="grid-column:{int(node["col"]) + 1};grid-row:{int(node["row"]) + 1}">{marker(node)}'
            f'{tag}<div class="node-title{" mono" if diagram.get("mono") else ""}">{text(node["label"], "label")}</div>'
            f'{badge}{opt(node, "note", "note", "node-note")}</div>')
    edges = []
    for start, end in diagram["edges"]:
        if start not in ids or end not in ids:
            raise ValueError(f"Graphic edge {start} -> {end} names an unknown node")
        edges.append((f"g-{start}", f"g-{end}", "h"))
    region = ""
    if diagram.get("region"):
        r = diagram["region"]
        if not set(r["nodes"]) <= ids:
            raise ValueError("Graphic region names an unknown node")
        code = f' <code>{text(r["code"], "inline_code")}</code>' if r.get("code") else ""
        members = " ".join(f"g-{esc(n)}" for n in r["nodes"])
        region = f'<div class="region" data-nodes="{members}"><span>{text(r["label"], "region")}{code}</span></div>'
    return (f'<div class="graph" style="grid-template-columns:repeat({cols},1fr)">{"".join(cells)}</div>{region}'), edges


DIAGRAMS = {"lanes": lanes_html, "fanout": fanout_html, "graph": graph_html}


def verbatim_strings(spec):
    """Code and quotes the graphic prints as-is; each must appear on a cited page.

    Code strips are checked line by line. <placeholder> tokens stand for any value.
    """
    diagram = spec.get("diagram") or {}
    items = list(diagram.get("steps") or []) + list(diagram.get("outputs") or [])
    found = [item["code"] for item in items if item.get("code")]
    if (diagram.get("region") or {}).get("code"):
        found.append(diagram["region"]["code"])
    if (diagram.get("input") or {}).get("quote"):
        found.append(diagram["input"]["quote"])
    if spec.get("code"):
        # Comments are the card's own annotation; the statement itself must be quoted.
        found += [line.split("--")[0].strip() for line in spec["code"]["code"].split("\n") if line.split("--")[0].strip()]
    return found


def alt_text(spec):
    return spec["title"] + (". " + spec["subtitle"] if spec.get("subtitle") else "")


def font_face(name, file, weight):
    data = base64.b64encode((FONTS / file).read_bytes()).decode()
    return f'@font-face{{font-family:"{name}";src:url(data:font/ttf;base64,{data});font-weight:{weight}}}'


def page_html(spec):
    host = urlsplit(spec["source_url"]).hostname or ""
    if host not in public_hosts():
        raise ValueError("Graphic source_url must be a page on an approved public host")
    diagram = spec["diagram"]
    if diagram.get("type") not in DIAGRAMS:
        raise ValueError(f"Unknown graphic diagram type: {diagram.get('type')}")
    body, edges = DIAGRAMS[diagram["type"]](diagram)
    callouts = spec.get("callouts") or []
    if len(callouts) > 3:
        raise ValueError("Graphic allows at most 3 callouts")
    notes = "".join(
        f'<div class="callout">{marker(c)}<div><div class="c-title">{text(c["title"], "callout_title")}</div>'
        f'<div class="c-text">{text(c["text"], "callout_text")}</div></div></div>' for c in callouts)
    notes = f'<section class="callouts">{notes}</section>' if notes else ""
    code = f'<pre>{highlight(spec["code"]["code"])}</pre>' if spec.get("code") else ""
    caption = f'<p class="caption">{text(spec["caption"], "caption")}</p>' if spec.get("caption") else ""
    subtitle = f'<p class="sub">{text(spec["subtitle"], "subtitle")}</p>' if spec.get("subtitle") else ""
    edge_data = json.dumps(edges)
    logo = logo_data()
    # The header keeps its height without a logo, so layout and fit checks do not change.
    logo = f'<img class="logo" src="data:image/png;base64,{logo}" alt="">' if logo else ""
    fonts = (font_face("Lato", "Lato-Regular.ttf", 400) + font_face("Lato", "Lato-Bold.ttf", 700)
             + font_face("Lato", "Lato-Black.ttf", 900) + font_face("Mono", "JetBrainsMono.ttf", "100 800"))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{fonts}
*{{box-sizing:border-box;margin:0;padding:0;font-variant-ligatures:none;font-feature-settings:"calt" 0,"liga" 0}}
html,body{{width:{WIDTH}px;height:{HEIGHT}px;background:#FFFFFF;overflow:hidden}}
body{{font-variant-ligatures:none;font-feature-settings:"liga" 0,"calt" 0;font-family:Lato,sans-serif;color:#0E2433;padding:56px 64px 40px;display:flex;flex-direction:column}}
header{{display:flex;justify-content:space-between;align-items:center;height:38px;margin-bottom:44px}}
.logo{{height:38px}}
h1{{font-size:66px;line-height:1.04;font-weight:900;letter-spacing:-0.02em;margin-bottom:20px;text-wrap:balance}}
.sub{{font-size:29px;line-height:1.38;color:#4D6576;margin-bottom:8px;text-wrap:pretty}}
main{{flex:1;min-height:0;display:flex;flex-direction:column;justify-content:safe center;gap:28px;padding:26px 0 30px}}
.stage{{position:relative}}
svg.wires{{position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none}}
.wire{{fill:none;stroke:#29B5E8;stroke-width:3}}
.wire.alt{{stroke:#8FB3C6;stroke-dasharray:9 8}}
.node{{position:relative;background:#FFFFFF;border:2px solid #C9DCE6;border-radius:16px;padding:18px 20px;z-index:1}}
.node-title{{font-size:28px;font-weight:700;line-height:1.2;display:flex;align-items:center;gap:12px}}
.node-title.mono{{font-family:Mono;font-size:20px;font-weight:600}}
.node-note{{font-size:22px;line-height:1.35;color:#4D6576;margin-top:8px}}
code{{display:inline-block;white-space:nowrap;font-family:Mono;font-size:20px;font-weight:600;color:#11567F;background:#EEF5F9;border-radius:8px;padding:4px 10px;margin-top:10px}}
.seq{{flex:none;width:36px;height:36px;border-radius:50%;background:#0E2433;color:#FFF;font-size:20px;font-weight:900;display:grid;place-items:center}}
.marker{{position:absolute;top:-16px;right:-14px;width:34px;height:34px;border-radius:50%;background:#29B5E8;color:#0E2433;font-size:19px;font-weight:900;display:grid;place-items:center;border:3px solid #FFF;z-index:2}}
.lanes{{display:grid;grid-template-columns:1fr 1fr;column-gap:48px;row-gap:24px;position:relative}}
.lane-bg{{background:#F3F8FB;border-radius:22px;margin:-14px -22px;z-index:0}}
.lane-head{{grid-row:1;font-size:22px;font-weight:900;letter-spacing:.06em;text-transform:uppercase;color:#11567F;padding-top:6px;z-index:1}}
.step.alt{{border-style:dashed;background:#FBFDFE}}
.fanout{{display:flex;flex-direction:column;gap:64px}}
.input{{background:#F3F8FB;border-color:#F3F8FB}}
.quote{{font-size:27px;line-height:1.4;margin-top:10px;color:#0E2433}}
.hub-row{{display:grid;grid-template-columns:1fr 1.25fr 1fr;gap:40px;align-items:center}}
.hub{{background:#11567F;border-color:#11567F;text-align:center}}
.hub .node-title{{color:#FFF;justify-content:center;font-size:32px;font-weight:900}}
.hub .node-note{{color:#D3EBF5}}
.side{{border-style:dashed}} .side .node-title{{font-size:24px}} .side .node-note{{font-size:20px}}
.outs{{display:grid;gap:18px}}
.out{{text-align:center;padding:20px 12px}} .out .node-title{{justify-content:center}} .out .node-note{{font-size:21px}}
.graph{{display:grid;column-gap:80px;row-gap:46px;align-items:center;position:relative;z-index:1}}
.gnode{{padding:14px 14px}}
.gnode.error{{border-color:#C8312F;background:#FDF1F0}}
.gnode.error .node-title{{color:#8E1F1D}}
.tag{{display:block;font-size:17px;font-weight:900;letter-spacing:.05em;text-transform:uppercase;color:#11567F;margin-bottom:6px}}
.badge{{display:inline-block;margin-top:10px;font-size:19px;font-weight:900;border-radius:999px;padding:4px 14px}}
.badge.good{{background:#E3F4EA;color:#17663A}} .badge.warn{{background:#FFF1D6;color:#7A4A00}} .badge.bad{{background:#FDE7E5;color:#A3241B}}
.region{{position:absolute;border:2.5px dashed #29B5E8;background:rgba(41,181,232,.07);border-radius:22px;z-index:0}}
.region span{{position:absolute;right:18px;top:-19px;background:#FFF;padding:2px 10px;font-size:21px;font-weight:900;color:#11567F;white-space:nowrap;display:flex;align-items:center;gap:8px}}
.region code{{margin:0;font-size:19px}}
.callouts{{display:flex;flex-direction:column;gap:18px;border-top:2px solid #E3EDF2;padding-top:26px}}
.callout{{display:flex;gap:18px;align-items:flex-start}}
.callout .marker{{position:static;flex:none;border:none;margin-top:2px}}
.c-title{{font-size:25px;font-weight:900;line-height:1.25}}
.c-text{{font-size:23px;line-height:1.38;color:#4D6576}}
pre{{font-family:Mono;font-size:25px;line-height:1.55;background:#F3F8FB;border-radius:16px;padding:20px 26px;color:#0E2433;white-space:pre}}
.kw{{color:#11567F;font-weight:800}} .cm{{color:#5E7A8A}}
.caption{{font-size:19px;color:#6B8291;margin-top:-14px}}
</style></head><body>
<header>{logo}</header>
<h1>{text(spec["title"], "title")}</h1>{subtitle}
<main><div class="stage">{body}<svg class="wires"><defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5"
markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#29B5E8"/></marker>
<marker id="arrow-alt" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
<path d="M0,0 L10,5 L0,10 z" fill="#8FB3C6"/></marker></defs></svg></div>{caption}{code}{notes}</main>
<script>
document.fonts.ready.then(() => {{
const stage = document.querySelector('.stage'), svg = stage.querySelector('svg'), base = stage.getBoundingClientRect();
const box = el => {{ const r = el.getBoundingClientRect(); return {{l:r.left-base.left, t:r.top-base.top, r:r.right-base.left, b:r.bottom-base.top}}; }};
document.querySelectorAll('.region').forEach(reg => {{
  const bs = reg.dataset.nodes.split(' ').map(id => box(document.getElementById(id)));
  const l = Math.min(...bs.map(b=>b.l))-20, t = Math.min(...bs.map(b=>b.t))-26, r = Math.max(...bs.map(b=>b.r))+20, b = Math.max(...bs.map(b=>b.b))+24;
  Object.assign(reg.style, {{left:l+'px', top:t+'px', width:(r-l)+'px', height:(b-t)+'px'}});
}});
for (const [from, to, kind] of {edge_data}) {{
  const a = box(document.getElementById(from)), z = box(document.getElementById(to));
  const vertical = !kind.includes('elbow') && (kind.includes('v') || (!kind.includes('h') && !(z.l >= a.r - 4) && z.t >= a.b - 4));
  let d;
  if (kind.includes('elbow')) {{ const right = z.l >= a.r - 4, x1 = right ? a.r+4 : a.l-4, x2 = right ? z.l-8 : z.r+8,
    y1 = a.t + Math.min(44, (a.b-a.t)/2), y2 = z.t + Math.min(44, (z.b-z.t)/2), mx = (x1+x2)/2, r = 14, s = right ? 1 : -1;
    d = `M${{x1}},${{y1}} H${{mx-s*r}} Q${{mx}},${{y1}} ${{mx}},${{y1+r}} V${{y2-r}} Q${{mx}},${{y2}} ${{mx+s*r}},${{y2}} H${{x2}}`; }}
  else if (!vertical && z.l >= a.r - 4) {{ const y1=(a.t+a.b)/2, y2=(z.t+z.b)/2, x1=a.r+4, x2=z.l-8, m=(x2-x1)/2; d=`M${{x1}},${{y1}} C${{x1+m}},${{y1}} ${{x2-m}},${{y2}} ${{x2}},${{y2}}`; }}
  else if (!vertical && z.r <= a.l + 4) {{ const y1=(a.t+a.b)/2, y2=(z.t+z.b)/2, x1=a.l-4, x2=z.r+8, m=(x1-x2)/2; d=`M${{x1}},${{y1}} C${{x1-m}},${{y1}} ${{x2+m}},${{y2}} ${{x2}},${{y2}}`; }}
  else {{ const x1=(a.l+a.r)/2, x2=(z.l+z.r)/2, down=z.t >= a.b-4, y1=down?a.b+4:a.t-4, y2=down?z.t-8:z.b+8, m=(y2-y1)/2; d=`M${{x1}},${{y1}} C${{x1}},${{y1+m}} ${{x2}},${{y2-m}} ${{x2}},${{y2}}`; }}
  const p = document.createElementNS('http://www.w3.org/2000/svg','path');
  p.setAttribute('d', d); p.setAttribute('class', 'wire' + (kind.includes('alt') ? ' alt' : ''));
  p.setAttribute('marker-end', kind.includes('alt') ? 'url(#arrow-alt)' : 'url(#arrow)'); svg.appendChild(p);
}}
const m = document.querySelector('main'), h = document.querySelector('h1');
const nodes = [...document.querySelectorAll('.node, .callout, pre')];
const clipped = nodes.some(n => [...n.children].some(c => !c.classList.contains('marker') &&
  (c.scrollWidth > c.clientWidth + 1 || c.getBoundingClientRect().right > n.getBoundingClientRect().right + 1)));
const rects = [...document.querySelectorAll('.node')].map(n => n.getBoundingClientRect());
const overlap = rects.some((a, i) => rects.some((b, j) => j > i && a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom));
const used = [...m.children].reduce((s, c) => s + c.getBoundingClientRect().height, 0);
const why = [m.scrollHeight > m.clientHeight + 1 && 'main', clipped && 'clipped', overlap && 'overlap',
  h.getBoundingClientRect().height > 220 && 'title'].filter(Boolean);
document.body.dataset.why = why.join(',');
document.body.dataset.fit = why.length ? 'overflow' : (used < 0.62 * m.clientHeight ? 'sparse' : 'ok');
}});
</script>
</body></html>"""


def render(spec, output):
    output = Path(output).resolve()
    chrome = chrome_path()
    if not chrome.is_file():
        raise RuntimeError(f"Google Chrome not found at {chrome}; set CHROME_PATH or chrome_path in the config")
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "graphic.html"
        page.write_text(page_html(spec), encoding="utf-8")
        dom = subprocess.run([str(chrome), "--headless=new", "--disable-gpu", f"--window-size={WIDTH},{HEIGHT}",
                              "--virtual-time-budget=3000", "--dump-dom", page.as_uri()],
                             check=True, capture_output=True, text=True, timeout=60).stdout
        if 'data-fit="sparse"' in dom:
            raise ValueError("Graphic leaves the card mostly empty; add a callout, a code strip or more nodes")
        if 'data-fit="ok"' not in dom:
            why = re.search(r'data-why="([^"]*)"', dom)
            raise ValueError("Graphic content does not fit the card; cut a node or callout or shorten the text"
                             f" ({why.group(1) if why else 'no layout result'})")
        subprocess.run([str(chrome), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--virtual-time-budget=3000", f"--window-size={WIDTH},{HEIGHT}", f"--screenshot={output}",
                        page.as_uri()], check=True, capture_output=True, timeout=60)
    if not output.exists() or output.stat().st_size < 10_000:
        raise RuntimeError("Graphic render produced no image")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(render(json.loads(args.spec.read_text()), args.output))


if __name__ == "__main__":
    main()

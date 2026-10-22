---
name: linkedin-feature-digest
description: "Build and self-email a twice-weekly Snowflake Weekly Feature Digest: three copy-ready LinkedIn post options (each with a business example and the best public reading link, preferring a useful blog or guide over a bare release note) plus up to five sales feature briefs (buyer, pain, value, alternative, talk track, honest illustrative math) with decks from Compass and public Slack, product contacts, and feature channels. Evidence-gated against official public pages; sent only to the owner via safe-email-send; never posts to LinkedIn. Use whenever the user asks for a feature digest, weekly/Monday/Thursday feature brief, what shipped in Snowflake for sales, LinkedIn post ideas about new Snowflake features, release-note posts, or to set up, run, test, or schedule this digest, even if they don't name the skill."
---

# LinkedIn Feature Digest

Turns recent Snowflake releases into one email for the user: three LinkedIn post
options to choose from and a short sales brief per feature. Research is
read-only; the only side effect is one self-addressed email.

## When to use

- "Run my feature digest", "send this week's digest", "send an example/test".
- "Set up the LinkedIn feature digest" or "schedule it Monday and Thursday".
- Questions about the digest format, fixtures, or a failed run.

Not for publishing to LinkedIn (it never posts), customer newsletters, or mass email.

## Intent routing

| Intent | Go to |
|---|---|
| First use, no config at `~/.config/linkedin-feature-digest/config.json` | Setup |
| Run an issue now (scheduled or ad hoc) | Run |
| "Send an example / test" | Run, test mode |
| Schedule or change the schedule | Schedule |

## Prerequisites

- Python 3.11+ with `certifi` (for TLS evidence capture), `uv`, and `node` 18+
  (optional, for visual QA).
- The safe-email-send CLI 0.1.x on PATH. This repo vendors it:
  `uv tool install <REPO>/vendor/safe-email-send`, then follow its
  `docs/setup.md`. Register `<REPO>/skills/safe-email-send` as a local skill too.
- Connected read-only tools: Slack (public search, channel/thread read, users)
  and Compass/Seismic content search. Gmail read tools are optional (inbox
  verification). Missing tools produce visible gaps, not a failed brief.

## Setup

1. **Check** `command -v safe-email-send && safe-email-send --version` and
   `safe-email-send status`. If absent or unconfigured, stop and point to the
   vendored sender's `README.md` and `docs/setup.md`; the user runs
   `credential-set` themselves. Never handle passwords in chat.
2. **Ask** (one `ask_user_question` call) for: owner email (must equal the
   sender's configured From address), timezone, issue days and time (default
   Monday and Thursday 08:00), work folder (default `~/linkedin-feature-digest-runs`).
3. **Discover** the Slack workspace ID, workspace hosts, and the release-feed /
   doc-update / product channels the user wants scanned. Resolve channel IDs with
   Slack channel search and show them to the user to confirm. If a workspace ID
   cannot be verified, ask the user to paste one from their Slack URL
   (`app.slack.com/client/<TEAM_ID>/...`). Ask for the Compass/Seismic tenant host.
4. **Write** `~/.config/linkedin-feature-digest/config.json` from
   `config.example.json`, then load it once to validate:
   ```bash
   LINKEDIN_DIGEST_CONFIG=~/.config/linkedin-feature-digest/config.json \
     python3 -c "import sys; sys.path.insert(0, '<SKILL_DIR>/scripts'); import digest_config; print(digest_config.load())"
   ```
5. **Ask** whether the user wants unattended self-only sending. Explain that it
   lets scheduled runs approve a message only when sender, owner, and sole
   recipient are the same address, and that saying no means each issue waits for
   their approval of the exact preview. Record the answer only as the sender
   skill describes (its "Self-only standing consent" section). Never assume yes.

**Stop** after setup: show the config path (not secret values), channels, and
consent choice. Offer a test send.

## Run

1. **Load** `references/workflow.md` and follow it end to end.
2. Scripts (always absolute paths; set `LINKEDIN_DIGEST_CONFIG` if non-default):
   - `scripts/issue_schedule.py [--issue-file <RUN_DIR>/issue.json]`: latest due
     slot and stable `source_id`; persists/reuses the manifest so retries never
     double-send.
   - `scripts/source_evidence.py <candidate.json> --output <RUN_DIR>/evidence`:
     fetches each public URL on the allowlisted hosts with TLS, stores bytes,
     text, and sha256.
   - `scripts/render_brief.py <candidate.json> --output <RUN_DIR> --evidence-dir
     <RUN_DIR>/evidence --smtp-source-id <source_id> --require-three-posts`:
     validates schema, evidence quotes, resource links, and copy rules; writes
     `email-body.md`, `email-payload.json`, `smtp-message.json`, `latest-post.md`.
   - `scripts/check_sender_html.py <RUN_DIR>/smtp-message.json` (run with the
     sender's environment): confirms the HTML passes the sender allowlist.
   - `scripts/preview_qa.mjs`: optional visual QA via local Chrome DevTools.
3. **Deliver** with the safe-email-send skill, self-only, exactly as
   `references/workflow.md` step 5 describes.

**Test mode** ("send an example"): use a source ID of the form
`linkedin-test-<label>-<date>` instead of `issue_schedule.py`, render into a new
folder under `<WORKDIR>/tests/`, and use `send-now` only because the user asked.
Never reuse a test source ID or send to anyone but the owner.

## Schedule

Use a local Desktop automation (`manage_automation`), not a cloud task: runs need
the user's local sender and connectors. Create it with frequency
`{"type": "custom", "interval": 1, "intervalUnit": "week", "daysOfWeek": [1, 4], "time": "08:00"}`
(adjust to the config) and this prompt:

```
Run the linkedin-feature-digest skill for the latest due issue. Follow
references/workflow.md exactly, using config <CONFIG_PATH>. Do not ask questions;
on any blocker save local status and report it.
```

`manage_automation` asks the user to confirm. The config weekdays use Python
numbering (0 = Monday); automation `daysOfWeek` uses 0 = Sunday. Keep both in
sync when either changes.

## Stopping points

- Setup: after collecting identity/channels, and before recording self-only consent.
- Before any send when self-only consent is absent or any condition fails.
- On UNKNOWN/IN_FLIGHT/HELD/FAILED tracked messages, unrelated queued mail, or a
  user pause: stop for review; never resend or change the source ID.
- Evidence capture failure: report it; never fabricate captures.

## Output

- One email to the owner: three post options with full public links and a single
  "Post to Linkedin" button (opens the empty composer), then up to five briefs.
- Run folder with `issue.json`, candidate JSON, evidence, `resource-evidence.json`,
  `posting-check.md`, rendered outputs, `delivery.json`; `history.json` updated.
- Final line `LINKEDIN_FEATURE_DIGEST_OK ...` or `LINKEDIN_FEATURE_DIGEST_FAILED:<reason>`.

## Troubleshooting

- `Missing digest config`: run Setup or set `LINKEDIN_DIGEST_CONFIG`.
- `Unapproved source host`: the URL is not on `public_hosts`; find an official page
  rather than widening the allowlist unattended.
- Sender HTML rejected: do not edit the sender; fix the content or renderer.
- Tests: `cd <SKILL_DIR> && python3 -m unittest discover -s tests` (synthetic
  config, no network, no mail).

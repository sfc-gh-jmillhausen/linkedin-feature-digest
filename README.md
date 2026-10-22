# linkedin-feature-digest

A Cortex Code (CoCo) skill that emails you a twice-weekly Snowflake feature
digest. Each issue has:

- **Three LinkedIn post options** to pick from. Each is short and plain, uses a
  different post shape (a useful command, before/now, roundup, short take, and
  more) that rotates between issues so they don't read like a template, and links
  the most useful official public page (a blog or guide when it explains more than
  the release note).
- **Up to five sales feature briefs** covering the buyer, pain, value, fair
  alternative, a talk track, and honest illustrative math, plus relevant decks
  (Compass/Seismic and public Slack), a product contact, and the feature's channel.

Every public claim is checked against a captured copy of an official Snowflake
page. The email goes only to you. Nothing is ever posted to LinkedIn; the email's
"Post to Linkedin" button opens an empty composer.

## Layout

```
skills/
  linkedin-feature-digest/   # the digest skill: SKILL.md, scripts, references, fixtures, tests
  safe-email-send/           # skill for the bundled approval-gated sender
vendor/safe-email-send/      # vendored SMTP queue CLI (upstream: smtp-safe-email-send)
```

## Install

Requires macOS, Python 3.11+, [uv](https://docs.astral.sh/uv/), and a Gmail or
Google Workspace account that permits app passwords and IMAP.

1. Clone this repo anywhere.
2. Install the sender and finish its setup (identity, signature, Keychain
   credential, which you enter yourself in a terminal):
   ```sh
   uv tool install /absolute/path/to/linkedin-feature-digest/vendor/safe-email-send
   safe-email-send --version
   ```
   See `vendor/safe-email-send/docs/setup.md`.
3. In CoCo Desktop: Agent Settings > Skills > Add Local Skill, and pick this repo's
   top-level `skills` folder. Both skills register.
4. Connect Slack and Compass (Seismic) in CoCo for deck and contact research.
   Gmail read access is optional, for inbox verification.
5. Ask CoCo: "set up the linkedin feature digest". It writes your settings to
   `~/.config/linkedin-feature-digest/config.json` (see
   `skills/linkedin-feature-digest/config.example.json`) and asks whether you
   want unattended self-only sending. Then ask it to "send an example digest" or
   to schedule it.

## Privacy

The repo holds no personal identity, Slack workspace or channel IDs, credentials,
or internal links. Fixtures are synthetic. Your config, consent record, run
folders, evidence, and history stay on your machine outside the repo. Review
`git status` before pushing a fork.

## Tests

No network, no mail:

```sh
cd skills/linkedin-feature-digest && python3 -m unittest discover -s tests
uv run --project vendor/safe-email-send pytest vendor/safe-email-send/tests
```

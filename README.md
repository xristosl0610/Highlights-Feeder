# Highlights feeder

Syncs book highlights from a Notion database into SQLite and emails a daily digest
(a free, self-hosted Readwise-style review). Runs for free on GitHub Actions.

```mermaid
flowchart LR
  A[Notion] -->|every run| B[Sync]
  B -->|new page| C[insert]
  B -->|edited page| D[update]
  B -->|gone from Notion| E[mark deleted]
  F[data/state.enc<br/>sent history] --> G[(SQLite)]
  C & D & E --> G --> H[Pick highlights]
  H --> I[HTML email]
  H --> J[Record delivery history]
  J --> F
```

- **Notion is read-only** and the source of truth for highlights.
- **SQLite** (`data/highlights.db`, gitignored) is a cache rebuilt from Notion on each run.
  Every run first syncs: new pages are inserted, edited pages (by `last_edited_time`) updated,
  removed pages marked deleted. Page bodies (full highlight + comments) are fetched lazily,
  only for picked highlights.
- **Review history** (which highlights were sent when) is the only state that can't be
  rebuilt, so it is encrypted with `STATE_KEY` and committed as `data/state.enc`. It is keyed
  by Notion page ID, so new highlights simply start with 0 showings next to existing ones.
  This keeps the repo safe to be public, and the daily commit keeps the scheduled workflow alive.
- **Eligibility**: with `require_keywords = true`, only highlights with at least one keyword
  (i.e. ones you've processed) are sent. Adding a keyword in Notion makes it eligible next run.
- **Selection**: weighted random. Favorites get `favorite_weight`x the chance, each previous
  showing lowers the chance (new highlights are favoured), nothing repeats within
  `cooldown_days`, max `max_per_book` per digest.

## Configuration

| Where | What | Committed |
|---|---|---|
| [`feeder.toml`](feeder.toml) | Non-secret settings: digest size, schedule, property names... | Yes: edit, commit, push to change the daily run |
| `.env` (local) / repo **Secrets** (Actions) | Tokens, IDs, passwords, `STATE_KEY` | Never |

Precedence: environment variables > `.env` > `feeder.toml` > code defaults.
Change `sender_name` and `subject_prefix` in `feeder.toml` to customize the email header.
For example, the defaults produce `Highlights Feeder <your-sender@gmail.com>` and
`Daily Digest | Monday, 26 October 2026`. The actual sender address comes from
`SMTP_USER` (or an `EMAIL_FROM` override); Gmail may display a saved contact name instead.

## Notion databases

**Highlights** (`HIGHLIGHTS_DATABASE_ID`)

| Property   | Type         | `feeder.toml` key         | Use                       |
|------------|--------------|---------------------------|---------------------------|
| `Name`     | Title        | `prop_highlight_name`     | Condensed highlight       |
| `Keywords` | Multi-select | `prop_highlight_keywords` | Tags; required to be sent |
| `Favorite` | Checkbox     | `prop_highlight_favorite` | Boosts selection weight   |
| `Page`     | Number       | `prop_highlight_page`     | Page in the book          |
| `Source`   | Relation     | `prop_highlight_source`   | Book in Library           |
| page body  | blocks       | -                         | Full highlight + comments |

**Library** (`LIBRARY_DATABASE_ID`): `Name` (Title, `prop_book_name`).

Property names are case-sensitive. Run `uv run feeder check` to validate them.

## Setup

### 1. Notion integration (free)

1. Go to <https://www.notion.so/profile/integrations> -> **New integration**.
   Type: *Internal*, pick your workspace. Capabilities: **Read content** only.
2. Copy the **Internal Integration Secret** -> `NOTION_TOKEN`.
3. Open the **Highlights** database as a full page -> `...` menu -> **Connections** ->
   add your integration. Repeat for **Library** (needed to resolve book names).
4. Database IDs: easiest is to run `uv run feeder check` after sharing; if an ID is wrong it
   lists the databases the integration can see. Note: the ID in the URL is the 32-char part
   *before* `?v=` (the part after `?v=` is a view ID and won't work).

### 2. Gmail App Password (free)

1. Enable 2-Step Verification: <https://myaccount.google.com/signinoptions/twosv>.
2. Create an App Password: <https://myaccount.google.com/apppasswords>.
3. Use your Gmail address as `SMTP_USER` and the 16-char password (no spaces) as `SMTP_PASSWORD`.

### 3. Local run

Requires [uv](https://docs.astral.sh/uv/).

**First-time setup** (not needed for every preview):

```powershell
uv sync                       # install dependencies; uv run also syncs if needed
if (-not (Test-Path .env)) { Copy-Item .env.example .env }  # then fill in credentials
uv run feeder keygen           # only for a new history: save in .env and GitHub's STATE_KEY secret
uv run feeder check            # once, or after changing Notion access/property names
```

If the repo already has `data/state.enc`, keep the same `STATE_KEY` in `.env` so the
preview can read the existing review history. Do not generate a replacement key.

**Every time you want a local HTML preview:**

```powershell
uv run feeder preview
```

This syncs new and edited Notion entries, picks highlights, fetches their page bodies,
and writes `digest_preview.html`. Open that file in a browser. It does **not** send an
email or record a delivery; it does not show the email's sender or subject headers.
You do not need to run `sync` separately first.

Optional commands: `uv run feeder sync` updates just the local SQLite cache without
building a digest; `uv run feeder stats` shows counts. `uv run feeder sync --bodies`
also downloads every page body (first time ~10 min for ~1,500 highlights due to
Notion's 3 req/s rate limit) if you want a complete local database.

To test **actual email delivery and headers**, run **Actions -> Daily highlights -> Run
workflow** in GitHub. With *force* unchecked it skips if today's digest was already
sent; with *force* checked it sends an extra email today. Avoid local `feeder send
--force` for routine tests: it changes your local encrypted review history, which
can diverge from the history GitHub Actions commits daily.

### 4. GitHub Actions (free)

1. Create an empty GitHub repository and push this project.
2. **Settings -> Secrets and variables -> Actions -> Secrets**: add `NOTION_TOKEN`,
   `HIGHLIGHTS_DATABASE_ID`, `LIBRARY_DATABASE_ID`, `STATE_KEY`, `SMTP_USER`,
   `SMTP_PASSWORD`, `EMAIL_TO`.
3. Non-secret settings come from the committed `feeder.toml`; no Variables needed.
4. **Actions -> Daily highlights -> Run workflow** (tick *force*) to test.

GitHub's scheduled events are a best-effort fallback: they can arrive hours late or be
dropped. The two UTC schedules cover daylight saving time; the app sends only once per
local day after `SEND_TIME`. For a more punctual trigger while your PC is off, set up
an external scheduler below.

### 5. More punctual off-PC delivery (free)

[cron-job.org](https://cron-job.org/en/) can send an HTTP request at 06:05
Europe/Amsterdam to start this same GitHub workflow. It needs only permission to trigger
Actions, not your Notion or email secrets. GitHub's own schedule remains a late fallback;
the encrypted sent history and daily date check prevent a second email once the first
run has finished. Neither provider guarantees exact delivery to the minute. Set the job's
time in your cron-job.org account as well; changing this file does not update that account.

1. From your **personal** GitHub account, create a [fine-grained token](https://github.com/settings/personal-access-tokens/new)
  restricted to **Only select repositories** -> `Highlights-Feeder`, with repository
  permission **Actions: Read and write** and no other write permissions. Choose an
  expiration you can renew, and keep the token private.
2. Create a free cron-job.org account and a job. Fill in its form as follows:

  | Field | Value |
  |---|---|
  | Title | `Daily highlights` |
  | URL | `https://api.github.com/repos/xristosl0610/Highlights-Feeder/actions/workflows/daily.yml/dispatches` |
  | Schedule | Every day at **06:05** (five minutes after the app's 06:00 gate) |
  | Time zone | `Europe/Amsterdam` (automatically follows CET/CEST) |
  | Request method | `POST` |
  | Request body | `{"ref":"main","inputs":{"force":false}}` (raw JSON, not form fields) |
  | Timeout | **30 seconds** (GitHub should accept the dispatch much sooner) |
  | Treat HTTP 3xx redirects as success | **Off**; the GitHub API should return a 2xx status |

3. Under **Headers**, use **Add** for each separate name/value pair:

  | Header name | Header value |
  |---|---|
  | `Authorization` | `Bearer YOUR_FINE_GRAINED_TOKEN` (replace the placeholder; keep the space after `Bearer`) |
  | `Accept` | `application/vnd.github+json` |
  | `Content-Type` | `application/json` |

  Enter the token **only** in the scheduler's private header settings, never in the URL,
  README, workflow file, issue, or a public log. Enable failure notifications.
4. Check the scheduler's upcoming execution preview spans the March/October DST change.
  If its timezone is UTC-only, make two daily jobs at **04:05 UTC** and **05:05 UTC**
  with the same request. The app skips the early winter run and the later summer run.
5. Use the scheduler's test request once, with `force: false`. GitHub should return
  HTTP 200 (or 204 on older API versions); then check **Actions -> Daily highlights**
  for a `workflow_dispatch` run and its result. A 2xx response means GitHub accepted
  the request, **not** that the email was sent. If today's digest is already recorded,
  the run should skip it; otherwise a test after 06:00 may send today's real email.

If an email is missing, inspect the Actions run (or trigger **Run workflow** manually
with **force unchecked**). Rotate the token when it expires or if it is exposed.

> Public repo: workflow logs are public. The app only logs counts, never highlight content.
> Don't add debug prints of highlights to the `send` path.

## Development

```powershell
uv run pytest
uv run ruff check .
uv run ruff format .
```

| Module         | Responsibility                                      |
|----------------|-----------------------------------------------------|
| `config.py`    | Settings from env / `.env` / `feeder.toml`          |
| `notion.py`    | Read-only Notion API client (version `2025-09-03`)  |
| `db.py`        | SQLite schema                                       |
| `sync.py`      | Notion -> SQLite, lazy page bodies                  |
| `selector.py`  | Weighted selection, digest recording                |
| `state.py`     | Encrypted review-history export/import              |
| `mailer.py`    | Email rendering (Jinja2) and SMTP sending           |
| `cli.py`       | `feeder` command line                               |

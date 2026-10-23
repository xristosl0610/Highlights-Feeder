# Highlights feeder

Syncs book highlights from a Notion database into SQLite and emails a daily digest
(a free, self-hosted Readwise-style review). Runs for free on GitHub Actions.

```
Notion (Highlights + Library) --API--> SQLite cache --pick--> HTML email (Gmail SMTP)
                                            |
                         review history -> data/state.enc (encrypted, committed daily)
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

```powershell
uv sync
Copy-Item .env.example .env   # then fill it in
uv run feeder keygen          # paste output into STATE_KEY (keep it safe!)
uv run feeder check           # verify Notion access + property names
uv run feeder sync            # pull everything into data/highlights.db
uv run feeder preview         # writes digest_preview.html, sends nothing
uv run feeder send --force    # send a real email now
uv run feeder stats
```

`uv run feeder sync --bodies` also downloads every page body (first time ~10 min for
~1,500 highlights due to Notion's 3 req/s rate limit) if you want a complete local database.

### 4. GitHub Actions (free)

1. Create an empty GitHub repository and push this project.
2. **Settings -> Secrets and variables -> Actions -> Secrets**: add `NOTION_TOKEN`,
   `HIGHLIGHTS_DATABASE_ID`, `LIBRARY_DATABASE_ID`, `STATE_KEY`, `SMTP_USER`,
   `SMTP_PASSWORD`, `EMAIL_TO`.
3. Non-secret settings come from the committed `feeder.toml`; no Variables needed.
4. **Actions -> Daily highlights -> Run workflow** (tick *force*) to test.

The workflow runs at 05:30 and 06:30 UTC; the app sends only once per local day after
`SEND_TIME`, so delivery stays at 07:30 Europe/Amsterdam across DST changes. GitHub may delay
scheduled runs by a few minutes.

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

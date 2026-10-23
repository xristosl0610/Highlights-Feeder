import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    last_edited TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS highlights (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    body         TEXT,  -- JSON list of {"type", "text"} blocks; NULL = not fetched yet
    favorite     INTEGER NOT NULL DEFAULT 0,
    page         INTEGER,
    book_id      TEXT REFERENCES books(id),
    url          TEXT,
    created_time TEXT,
    last_edited  TEXT NOT NULL,
    deleted      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS keywords (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS highlight_keywords (
    highlight_id TEXT NOT NULL REFERENCES highlights(id) ON DELETE CASCADE,
    keyword_id   INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    PRIMARY KEY (highlight_id, keyword_id)
);

CREATE TABLE IF NOT EXISTS digests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at    TEXT NOT NULL,
    local_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
    digest_id    INTEGER NOT NULL REFERENCES digests(id) ON DELETE CASCADE,
    highlight_id TEXT NOT NULL,  -- no FK: history outlives the highlights cache
    PRIMARY KEY (digest_id, highlight_id)
);

CREATE INDEX IF NOT EXISTS idx_highlights_book ON highlights(book_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_highlight ON deliveries(highlight_id);
CREATE INDEX IF NOT EXISTS idx_digests_local_date ON digests(local_date);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn

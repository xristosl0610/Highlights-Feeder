"""Pick which highlights go into today's digest and record what was sent."""

import json
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .config import Settings


@dataclass
class Highlight:
    id: str
    name: str
    body: list[dict[str, str]]
    favorite: bool
    page: int | None
    book_id: str | None
    book_name: str | None
    url: str | None
    keywords: list[str] = field(default_factory=list)
    times_shown: int = 0
    last_shown: datetime | None = None


CANDIDATES_SQL = """
SELECT h.id, h.name, h.body, h.favorite, h.page, h.book_id, h.url, b.name AS book_name,
       COUNT(d.digest_id) AS times_shown,
       MAX(g.sent_at) AS last_shown,
       (SELECT json_group_array(k.name)
          FROM highlight_keywords hk JOIN keywords k ON k.id = hk.keyword_id
         WHERE hk.highlight_id = h.id) AS keywords
  FROM highlights h
  LEFT JOIN books b ON b.id = h.book_id
  LEFT JOIN deliveries d ON d.highlight_id = h.id
  LEFT JOIN digests g ON g.id = d.digest_id
 WHERE h.deleted = 0
   AND (:require_keywords = 0
        OR EXISTS (SELECT 1 FROM highlight_keywords hk WHERE hk.highlight_id = h.id))
 GROUP BY h.id
"""


def load_candidates(conn: sqlite3.Connection, require_keywords: bool = False) -> list[Highlight]:
    return [
        Highlight(
            id=row["id"],
            name=row["name"],
            body=json.loads(row["body"]) if row["body"] else [],
            favorite=bool(row["favorite"]),
            page=row["page"],
            book_id=row["book_id"],
            book_name=row["book_name"],
            url=row["url"],
            keywords=json.loads(row["keywords"]),
            times_shown=row["times_shown"],
            last_shown=datetime.fromisoformat(row["last_shown"]) if row["last_shown"] else None,
        )
        for row in conn.execute(CANDIDATES_SQL, {"require_keywords": int(require_keywords)})
    ]


def weight(h: Highlight, s: Settings) -> float:
    """Favorites are boosted; every past showing reduces the chance of being picked again."""
    return (s.favorite_weight if h.favorite else 1.0) / (1 + h.times_shown)


def pick(
    candidates: list[Highlight], s: Settings, now: datetime, rng: random.Random | None = None
) -> list[Highlight]:
    rng = rng or random.Random()
    n = s.digest_size
    cutoff = now - timedelta(days=s.cooldown_days)
    eligible = [h for h in candidates if h.last_shown is None or h.last_shown < cutoff]
    if len(eligible) < n:
        eligible = candidates

    # Weighted sampling without replacement (Efraimidis-Spirakis): sort by u^(1/w).
    ranked = sorted(eligible, key=lambda h: rng.random() ** (1 / weight(h, s)), reverse=True)

    chosen: list[Highlight] = []
    skipped: list[Highlight] = []
    per_book: dict[str, int] = {}
    for h in ranked:
        if len(chosen) == n:
            break
        group = h.book_id or h.id
        if per_book.get(group, 0) >= s.max_per_book:
            skipped.append(h)
            continue
        per_book[group] = per_book.get(group, 0) + 1
        chosen.append(h)
    # Not enough distinct books: fill up with the best of the rest.
    chosen.extend(skipped[: n - len(chosen)])
    return chosen


def refresh_bodies(conn: sqlite3.Connection, highlights: list[Highlight]) -> None:
    for h in highlights:
        row = conn.execute("SELECT body FROM highlights WHERE id = ?", (h.id,)).fetchone()
        h.body = json.loads(row["body"]) if row and row["body"] else []


def already_sent(conn: sqlite3.Connection, local_date: date) -> bool:
    row = conn.execute(
        "SELECT 1 FROM digests WHERE local_date = ? LIMIT 1", (local_date.isoformat(),)
    ).fetchone()
    return row is not None


def record_digest(
    conn: sqlite3.Connection, highlights: list[Highlight], sent_at: datetime, local_date: date
) -> None:
    cur = conn.execute(
        "INSERT INTO digests (sent_at, local_date) VALUES (?, ?)",
        (sent_at.isoformat(), local_date.isoformat()),
    )
    conn.executemany(
        "INSERT INTO deliveries (digest_id, highlight_id) VALUES (?, ?)",
        [(cur.lastrowid, h.id) for h in highlights],
    )
    conn.commit()

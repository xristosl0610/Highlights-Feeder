"""Pull the Notion "Highlights" and "Library" databases into SQLite."""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .notion import NotionClient, NotionError

TEXT_BLOCK_TYPES = {
    "paragraph",
    "quote",
    "callout",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "code",
}


@dataclass
class SyncStats:
    books: int = 0
    highlights_seen: int = 0
    highlights_updated: int = 0
    highlights_deleted: int = 0


def _plain_text(rich_text: list[dict[str, Any]]) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text).strip()


def _prop(page: dict[str, Any], name: str) -> dict[str, Any]:
    try:
        return page["properties"][name]
    except KeyError as exc:
        raise NotionError(f"Property '{name}' not found on page {page['id']}") from exc


def _text_value(prop: dict[str, Any]) -> str:
    return _plain_text(prop.get(prop["type"]) or [])


def check_schema(data_source: dict[str, Any], expected: dict[str, set[str]]) -> None:
    props = data_source["properties"]
    problems = []
    for name, types in expected.items():
        if name not in props:
            problems.append(f"missing property '{name}' (available: {sorted(props)})")
        elif props[name]["type"] not in types:
            problems.append(f"'{name}' has type {props[name]['type']}, expected one of {types}")
    if problems:
        raise NotionError("Schema mismatch: " + "; ".join(problems))


def highlights_schema(s: Settings) -> dict[str, set[str]]:
    return {
        s.prop_highlight_name: {"title", "rich_text"},
        s.prop_highlight_keywords: {"multi_select"},
        s.prop_highlight_favorite: {"checkbox"},
        s.prop_highlight_page: {"number"},
        s.prop_highlight_source: {"relation"},
    }


def library_schema(s: Settings) -> dict[str, set[str]]:
    return {s.prop_book_name: {"title", "rich_text"}}


ANNOTATIONS = ("bold", "italic", "strikethrough", "underline", "code")


def _spans(rich_text: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact rich-text segments: text plus only the non-default formatting."""
    spans = []
    for part in rich_text:
        text = part.get("plain_text", "")
        if not text:
            continue
        ann = part.get("annotations") or {}
        span: dict[str, Any] = {"text": text}
        span.update({k: True for k in ANNOTATIONS if ann.get(k)})
        if ann.get("color", "default") != "default":
            span["color"] = ann["color"]
        if part.get("href"):
            span["href"] = part["href"]
        spans.append(span)
    return spans


def blocks_to_body(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    body = []
    for block in blocks:
        btype = block["type"]
        if btype not in TEXT_BLOCK_TYPES:
            continue
        rich_text = block[btype].get("rich_text", [])
        text = _plain_text(rich_text)
        if not text:
            continue
        item: dict[str, Any] = {"type": btype, "text": text, "spans": _spans(rich_text)}
        if block[btype].get("color", "default") != "default":
            item["color"] = block[btype]["color"]
        body.append(item)
    return body


def sync_books(conn: sqlite3.Connection, client: NotionClient, s: Settings) -> int:
    source = client.get_data_source(s.library_database_id)
    check_schema(source, library_schema(s))
    count = 0
    for page in client.query_data_source(source["id"]):
        conn.execute(
            """INSERT INTO books (id, name, last_edited) VALUES (?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name = excluded.name,
                                             last_edited = excluded.last_edited""",
            (page["id"], _text_value(_prop(page, s.prop_book_name)), page["last_edited_time"]),
        )
        count += 1
    return count


def _set_keywords(conn: sqlite3.Connection, highlight_id: str, names: list[str]) -> None:
    conn.execute("DELETE FROM highlight_keywords WHERE highlight_id = ?", (highlight_id,))
    for name in names:
        conn.execute("INSERT OR IGNORE INTO keywords (name) VALUES (?)", (name,))
        conn.execute(
            """INSERT INTO highlight_keywords (highlight_id, keyword_id)
               SELECT ?, id FROM keywords WHERE name = ?""",
            (highlight_id, name),
        )


def sync_highlights(
    conn: sqlite3.Connection, client: NotionClient, s: Settings, full: bool = False
) -> SyncStats:
    source = client.get_data_source(s.highlights_database_id)
    check_schema(source, highlights_schema(s))
    known = {
        row["id"]: row["last_edited"]
        for row in conn.execute("SELECT id, last_edited FROM highlights WHERE deleted = 0")
    }
    book_ids = {row["id"] for row in conn.execute("SELECT id FROM books")}
    stats = SyncStats()
    seen: set[str] = set()

    for page in client.query_data_source(source["id"]):
        stats.highlights_seen += 1
        hid = page["id"]
        seen.add(hid)
        if not full and known.get(hid) == page["last_edited_time"]:
            continue

        sources = _prop(page, s.prop_highlight_source)["relation"]
        book_id = sources[0]["id"] if sources else None
        page_no = _prop(page, s.prop_highlight_page)["number"]

        conn.execute(
            """INSERT INTO highlights
                 (id, name, favorite, page, book_id, url, created_time, last_edited, deleted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
               ON CONFLICT(id) DO UPDATE SET
                 body = CASE WHEN last_edited = excluded.last_edited THEN body END,
                 name = excluded.name, favorite = excluded.favorite,
                 page = excluded.page, book_id = excluded.book_id, url = excluded.url,
                 created_time = excluded.created_time, last_edited = excluded.last_edited,
                 deleted = 0""",
            (
                hid,
                _text_value(_prop(page, s.prop_highlight_name)),
                int(bool(_prop(page, s.prop_highlight_favorite)["checkbox"])),
                int(page_no) if page_no is not None else None,
                book_id if book_id in book_ids else None,
                page.get("url"),
                page.get("created_time"),
                page["last_edited_time"],
            ),
        )
        _set_keywords(
            conn,
            hid,
            [opt["name"] for opt in _prop(page, s.prop_highlight_keywords)["multi_select"]],
        )
        stats.highlights_updated += 1

    removed = [hid for hid in known if hid not in seen]
    conn.executemany("UPDATE highlights SET deleted = 1 WHERE id = ?", [(h,) for h in removed])
    stats.highlights_deleted = len(removed)
    return stats


def fetch_bodies(
    conn: sqlite3.Connection, client: NotionClient, ids: list[str] | None = None
) -> int:
    """Fetch page bodies (full highlight + comments) that are missing or stale."""
    query = "SELECT id FROM highlights WHERE body IS NULL AND deleted = 0"
    todo = [row["id"] for row in conn.execute(query)]
    if ids is not None:
        wanted = set(ids)
        todo = [hid for hid in todo if hid in wanted]
    for i, hid in enumerate(todo, 1):
        body = blocks_to_body(list(client.list_block_children(hid)))
        conn.execute(
            "UPDATE highlights SET body = ? WHERE id = ?",
            (json.dumps(body, ensure_ascii=False), hid),
        )
        if i % 50 == 0:
            conn.commit()
    conn.commit()
    return len(todo)


def sync_all(
    conn: sqlite3.Connection, client: NotionClient, s: Settings, full: bool = False
) -> SyncStats:
    books = sync_books(conn, client, s)
    stats = sync_highlights(conn, client, s, full=full)
    conn.commit()
    stats.books = books
    return stats

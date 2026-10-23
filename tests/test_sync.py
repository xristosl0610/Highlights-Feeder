import json

import pytest
from conftest import FakeNotion, book_page, highlight_page

from highlights_feeder.notion import NotionError
from highlights_feeder.sync import blocks_to_body, fetch_bodies, sync_all


def block(btype: str, text: str) -> dict:
    return {"type": btype, btype: {"rich_text": [{"plain_text": text}]}}


def test_blocks_to_body_keeps_text_blocks_only():
    blocks = [
        block("quote", "Full quote"),
        block("paragraph", ""),
        {"type": "image", "image": {}},
        block("paragraph", "My comment"),
    ]
    assert [(b["type"], b["text"]) for b in blocks_to_body(blocks)] == [
        ("quote", "Full quote"),
        ("paragraph", "My comment"),
    ]


def test_blocks_to_body_keeps_formatting():
    blocks = [
        {
            "type": "quote",
            "quote": {
                "color": "gray_background",
                "rich_text": [
                    {"plain_text": "plain ", "annotations": {"color": "default"}},
                    {
                        "plain_text": "key idea",
                        "annotations": {"bold": True, "color": "yellow_background"},
                        "href": "https://example.com",
                    },
                ],
            },
        }
    ]
    [b] = blocks_to_body(blocks)
    assert b["color"] == "gray_background"
    assert b["spans"] == [
        {"text": "plain "},
        {
            "text": "key idea",
            "bold": True,
            "color": "yellow_background",
            "href": "https://example.com",
        },
    ]


def test_sync_inserts_and_lazy_bodies(conn, settings):
    fake = FakeNotion(
        [highlight_page("h1", "Short", favorite=True, keywords=("stoic", "time"))],
        [book_page("book-1", "Meditations")],
        bodies={"h1": [block("quote", "Long text")]},
    )
    stats = sync_all(conn, fake, settings)
    assert (stats.books, stats.highlights_seen, stats.highlights_updated) == (1, 1, 1)
    assert fake.body_calls == []

    row = conn.execute("SELECT * FROM highlights WHERE id = 'h1'").fetchone()
    assert (row["name"], row["favorite"], row["page"], row["book_id"], row["body"]) == (
        "Short",
        1,
        10,
        "book-1",
        None,
    )
    kws = {
        r[0]
        for r in conn.execute(
            "SELECT k.name FROM keywords k JOIN highlight_keywords hk ON hk.keyword_id = k.id"
        )
    }
    assert kws == {"stoic", "time"}

    assert fetch_bodies(conn, fake, ["h1"]) == 1
    body = conn.execute("SELECT body FROM highlights WHERE id = 'h1'").fetchone()[0]
    assert [b["text"] for b in json.loads(body)] == ["Long text"]


def test_sync_is_incremental_and_invalidates_edited_bodies(conn, settings):
    fake = FakeNotion(
        [highlight_page("h1", "A"), highlight_page("h2", "B")], [book_page("book-1", "X")]
    )
    sync_all(conn, fake, settings)
    conn.execute("UPDATE highlights SET body = '[]'")

    fake.highlights = [
        highlight_page("h1", "A"),
        highlight_page("h2", "B2", edited="2026-02-01T00:00:00.000Z"),
    ]
    stats = sync_all(conn, fake, settings)
    assert stats.highlights_updated == 1
    bodies = dict(conn.execute("SELECT id, body FROM highlights").fetchall())
    assert bodies == {"h1": "[]", "h2": None}


def test_sync_marks_removed_pages_deleted(conn, settings):
    fake = FakeNotion(
        [highlight_page("h1", "A"), highlight_page("h2", "B")], [book_page("book-1", "X")]
    )
    sync_all(conn, fake, settings)
    fake.highlights = [highlight_page("h1", "A")]
    assert sync_all(conn, fake, settings).highlights_deleted == 1
    assert conn.execute("SELECT deleted FROM highlights WHERE id = 'h2'").fetchone()[0] == 1


def test_unknown_book_relation_is_nulled(conn, settings):
    fake = FakeNotion([highlight_page("h1", "A", book="not-shared")], [])
    sync_all(conn, fake, settings)
    assert conn.execute("SELECT book_id FROM highlights").fetchone()[0] is None


def test_schema_mismatch_is_reported(conn, settings):
    settings.prop_highlight_page = "Page"
    with pytest.raises(NotionError, match="missing property 'Page'"):
        sync_all(conn, FakeNotion([], []), settings)

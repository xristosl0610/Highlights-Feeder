import random
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from highlights_feeder import db, mailer, state
from highlights_feeder.selector import (
    Highlight,
    already_sent,
    load_candidates,
    pick,
    record_digest,
)

NOW = datetime(2026, 10, 23, 5, 30, tzinfo=UTC)


def hl(i: int, **kw) -> Highlight:
    return Highlight(
        id=f"h{i}",
        name=f"Highlight {i}",
        body=[],
        favorite=kw.pop("favorite", False),
        page=None,
        book_id=kw.pop("book_id", f"b{i}"),
        book_name=None,
        url=None,
        **kw,
    )


def test_pick_returns_requested_size_without_duplicates(settings):
    chosen = pick([hl(i) for i in range(20)], settings, NOW, random.Random(1))
    assert len(chosen) == settings.digest_size
    assert len({h.id for h in chosen}) == settings.digest_size


def test_favorites_are_picked_more_often(settings):
    settings.digest_size = 1
    pool = [hl(0, favorite=True)] + [hl(i) for i in range(1, 4)]
    rng = random.Random(42)
    counts = Counter(pick(pool, settings, NOW, rng)[0].id for _ in range(3000))
    assert counts["h0"] > 2 * counts["h1"]


def test_cooldown_excludes_recently_shown(settings):
    recent = hl(0, last_shown=NOW - timedelta(days=1), times_shown=1)
    pool = [recent] + [hl(i) for i in range(1, 10)]
    for seed in range(50):
        assert "h0" not in {h.id for h in pick(pool, settings, NOW, random.Random(seed))}


def test_cooldown_falls_back_when_pool_too_small(settings):
    pool = [hl(i, last_shown=NOW, times_shown=1) for i in range(3)]
    assert len(pick(pool, settings, NOW, random.Random(0))) == 3


def test_max_per_book_with_fill_up(settings):
    settings.digest_size = 4
    settings.max_per_book = 1
    pool = [hl(i, book_id="same") for i in range(5)] + [hl(9, book_id="other")]
    chosen = pick(pool, settings, NOW, random.Random(0))
    assert len(chosen) == 4
    assert "h9" in {h.id for h in chosen}


def test_record_and_state_roundtrip(conn, settings, tmp_path):
    conn.execute(
        "INSERT INTO highlights (id, name, last_edited) VALUES ('h1', 'A', 'x'), ('h2', 'B', 'x')"
    )
    picked = load_candidates(conn)
    record_digest(conn, picked, NOW, date(2026, 10, 23))
    assert already_sent(conn, date(2026, 10, 23))
    assert not already_sent(conn, date(2026, 10, 24))

    key = state.generate_key()
    state.save_encrypted(conn, settings.state_path, key)
    assert b"h1" not in settings.state_path.read_bytes()

    fresh = db.connect(tmp_path / "fresh.db")
    fresh.execute("INSERT INTO highlights (id, name, last_edited) VALUES ('h1', 'A', 'x')")
    state.load_encrypted(fresh, settings.state_path, key)
    cand = {h.id: h for h in load_candidates(fresh)}
    assert cand["h1"].times_shown == 1
    assert cand["h1"].last_shown == NOW
    assert already_sent(fresh, date(2026, 10, 23))


def test_render_escapes_html():
    h = hl(1)
    h.name = "<script>alert(1)</script>"
    h.body = [{"type": "quote", "text": "a & b"}]
    _, text, html = mailer.render([h], date(2026, 10, 23))
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "a & b" in text


def test_render_rich_formatting():
    h = hl(1)
    h.body = [
        {
            "type": "paragraph",
            "text": "x",
            "color": "blue_background",
            "spans": [
                {"text": "<b>", "bold": True, "color": "yellow_background"},
                {"text": "link", "href": "javascript:alert(1)"},
                {"text": "ok", "italic": True, "href": "https://example.com/?a=1&b=2"},
            ],
        }
    ]
    _, _, html = mailer.render([h], date(2026, 10, 23))
    assert '<span style="background-color:#fbf3db;' in html
    assert "<strong>&lt;b&gt;</strong>" in html
    assert "javascript:" not in html
    assert '<a href="https://example.com/?a=1&amp;b=2"' in html
    assert "background-color:#e7f3f8;" in html

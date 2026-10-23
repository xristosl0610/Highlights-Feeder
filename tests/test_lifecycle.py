from datetime import UTC, date, datetime

from conftest import FakeNotion, book_page, highlight_page

from highlights_feeder.config import Settings
from highlights_feeder.selector import load_candidates, record_digest
from highlights_feeder.sync import sync_all

REQUIRED = {"NOTION_TOKEN": "t", "HIGHLIGHTS_DATABASE_ID": "h", "LIBRARY_DATABASE_ID": "l"}


def test_toml_settings_with_env_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "feeder.toml").write_text('digest_size = 3\nsend_time = "08:15"\n')
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)

    s = Settings(_env_file=None)
    assert s.digest_size == 3
    assert s.send_time.hour == 8 and s.send_time.minute == 15

    monkeypatch.setenv("DIGEST_SIZE", "7")
    assert Settings(_env_file=None).digest_size == 7


def test_require_keywords_filters_unprocessed(conn, settings):
    fake = FakeNotion(
        [highlight_page("h1", "Processed", keywords=("habits",)), highlight_page("h2", "Raw")],
        [book_page("book-1", "X")],
    )
    sync_all(conn, fake, settings)
    assert {h.id for h in load_candidates(conn, require_keywords=True)} == {"h1"}
    assert {h.id for h in load_candidates(conn)} == {"h1", "h2"}

    # Adding a keyword in Notion bumps last_edited_time; the next sync makes it eligible.
    fake.highlights[1] = highlight_page(
        "h2", "Raw", keywords=("focus",), edited="2026-03-01T00:00:00.000Z"
    )
    sync_all(conn, fake, settings)
    assert {h.id for h in load_candidates(conn, require_keywords=True)} == {"h1", "h2"}


def test_new_notion_entries_join_existing_history(conn, settings):
    fake = FakeNotion([highlight_page("h1", "Old", keywords=("a",))], [book_page("book-1", "X")])
    sync_all(conn, fake, settings)
    record_digest(conn, load_candidates(conn), datetime(2026, 10, 1, tzinfo=UTC), date(2026, 10, 1))

    fake.highlights.append(highlight_page("h2", "New", keywords=("b",)))
    stats = sync_all(conn, fake, settings)
    assert stats.highlights_updated == 1

    shown = {h.id: h.times_shown for h in load_candidates(conn, require_keywords=True)}
    assert shown == {"h1": 1, "h2": 0}

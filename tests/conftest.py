import pytest

from highlights_feeder import db
from highlights_feeder.config import Settings


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.chdir(tmp_path)  # don't pick up the repo's feeder.toml / .env
    return Settings(
        _env_file=None,
        notion_token="secret",
        highlights_database_id="hl-db",
        library_database_id="lib-db",
        db_path=tmp_path / "test.db",
        state_path=tmp_path / "state.enc",
    )


@pytest.fixture
def conn(settings):
    c = db.connect(settings.db_path)
    yield c
    c.close()


def rich(text: str) -> list[dict]:
    return [{"plain_text": text}]


def highlight_page(
    pid: str,
    name: str,
    *,
    edited: str = "2026-01-01T00:00:00.000Z",
    favorite: bool = False,
    page: float | None = 10,
    book: str | None = "book-1",
    keywords: tuple[str, ...] = (),
) -> dict:
    return {
        "id": pid,
        "url": f"https://www.notion.so/{pid}",
        "created_time": "2026-01-01T00:00:00.000Z",
        "last_edited_time": edited,
        "properties": {
            "Name": {"type": "title", "title": rich(name)},
            "Keywords": {"type": "multi_select", "multi_select": [{"name": k} for k in keywords]},
            "Favorite": {"type": "checkbox", "checkbox": favorite},
            "Page": {"type": "number", "number": page},
            "Source": {"type": "relation", "relation": [{"id": book}] if book else []},
        },
    }


def book_page(pid: str, name: str) -> dict:
    return {
        "id": pid,
        "last_edited_time": "2026-01-01T00:00:00.000Z",
        "properties": {"Name": {"type": "title", "title": rich(name)}},
    }


class FakeNotion:
    HL_SCHEMA = {
        "Name": {"type": "title"},
        "Keywords": {"type": "multi_select"},
        "Favorite": {"type": "checkbox"},
        "Page": {"type": "number"},
        "Source": {"type": "relation"},
    }
    LIB_SCHEMA = {"Name": {"type": "title"}}

    def __init__(
        self, highlights: list[dict], books: list[dict], bodies: dict[str, list] | None = None
    ):
        self.highlights = highlights
        self.books = books
        self.bodies = bodies or {}
        self.body_calls: list[str] = []

    def get_data_source(self, database_id: str) -> dict:
        if database_id == "hl-db":
            return {"id": "hl-ds", "properties": self.HL_SCHEMA}
        return {"id": "lib-ds", "properties": self.LIB_SCHEMA}

    def query_data_source(self, data_source_id: str):
        yield from (self.highlights if data_source_id == "hl-ds" else self.books)

    def list_block_children(self, block_id: str):
        self.body_calls.append(block_id)
        yield from self.bodies.get(block_id, [])

"""Minimal read-only Notion API client (API version 2025-09-03, data sources)."""

import time
from collections.abc import Iterator
from typing import Any

import httpx

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
MAX_RETRIES = 5


class NotionError(RuntimeError):
    pass


class NotionClient:
    def __init__(self, token: str, timeout: float = 30.0) -> None:
        self._http = httpx.Client(
            base_url=NOTION_API,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        )

    def __enter__(self) -> "NotionClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in range(MAX_RETRIES):
            resp = self._http.request(method, path, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(float(resp.headers.get("Retry-After", 2**attempt)))
                continue
            if resp.is_error:
                try:
                    detail = resp.json().get("message", resp.text)
                except ValueError:
                    detail = resp.text
                raise NotionError(f"{method} {path} -> {resp.status_code}: {detail}")
            return resp.json()
        raise NotionError(f"{method} {path} failed after {MAX_RETRIES} retries")

    def get_data_source(self, database_id: str) -> dict[str, Any]:
        """Resolve a database ID to its (first) data source, including the property schema."""
        database = self._request("GET", f"/databases/{database_id}")
        sources = database.get("data_sources") or []
        if not sources:
            raise NotionError(f"Database {database_id} has no data sources")
        return self._request("GET", f"/data_sources/{sources[0]['id']}")

    def query_data_source(self, data_source_id: str) -> Iterator[dict[str, Any]]:
        body: dict[str, Any] = {"page_size": 100}
        while True:
            data = self._request("POST", f"/data_sources/{data_source_id}/query", json=body)
            yield from data["results"]
            if not data.get("has_more"):
                return
            body["start_cursor"] = data["next_cursor"]

    def list_block_children(self, block_id: str) -> Iterator[dict[str, Any]]:
        params: dict[str, Any] = {"page_size": 100}
        while True:
            data = self._request("GET", f"/blocks/{block_id}/children", params=params)
            yield from data["results"]
            if not data.get("has_more"):
                return
            params["start_cursor"] = data["next_cursor"]

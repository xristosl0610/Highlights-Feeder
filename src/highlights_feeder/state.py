"""Review history (what was sent when) persisted as an encrypted file safe for a public repo.

Highlights themselves are a cache rebuilt from Notion; only this history is irreplaceable.
"""

import json
import sqlite3
import zlib
from pathlib import Path

from cryptography.fernet import Fernet

STATE_VERSION = 1


def generate_key() -> str:
    return Fernet.generate_key().decode()


def export_state(conn: sqlite3.Connection) -> dict:
    digests = []
    for d in conn.execute("SELECT id, sent_at, local_date FROM digests ORDER BY id"):
        ids = [
            r["highlight_id"]
            for r in conn.execute(
                "SELECT highlight_id FROM deliveries WHERE digest_id = ? ORDER BY rowid", (d["id"],)
            )
        ]
        digests.append(
            {"sent_at": d["sent_at"], "local_date": d["local_date"], "highlight_ids": ids}
        )
    return {"version": STATE_VERSION, "digests": digests}


def import_state(conn: sqlite3.Connection, state: dict) -> None:
    if state.get("version") != STATE_VERSION:
        raise ValueError(f"Unsupported state version: {state.get('version')}")
    with conn:
        conn.execute("DELETE FROM deliveries")
        conn.execute("DELETE FROM digests")
        for d in state["digests"]:
            cur = conn.execute(
                "INSERT INTO digests (sent_at, local_date) VALUES (?, ?)",
                (d["sent_at"], d["local_date"]),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO deliveries (digest_id, highlight_id) VALUES (?, ?)",
                [(cur.lastrowid, hid) for hid in d["highlight_ids"]],
            )


def save_encrypted(conn: sqlite3.Connection, path: Path, key: str) -> None:
    raw = json.dumps(export_state(conn), separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(Fernet(key.encode()).encrypt(zlib.compress(raw, level=9)))


def load_encrypted(conn: sqlite3.Connection, path: Path, key: str) -> None:
    raw = zlib.decompress(Fernet(key.encode()).decrypt(path.read_bytes()))
    import_state(conn, json.loads(raw))

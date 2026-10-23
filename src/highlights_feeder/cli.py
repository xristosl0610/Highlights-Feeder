import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from pydantic import ValidationError

from . import db, mailer, selector, state
from .config import Settings, get_settings
from .notion import NotionClient, NotionError
from .sync import check_schema, fetch_bodies, highlights_schema, library_schema, sync_all

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Notion highlights feeder.")


def _settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as exc:
        missing = ", ".join(str(e["loc"][0]).upper() for e in exc.errors())
        typer.secho(f"Invalid or missing settings: {missing} (see .env.example)", fg="red")
        raise typer.Exit(1) from exc


def _open_db(s: Settings) -> sqlite3.Connection:
    conn = db.connect(s.db_path)
    if s.state_key and s.state_path.exists():
        state.load_encrypted(conn, s.state_path, s.state_key.get_secret_value())
    return conn


def _client(s: Settings) -> NotionClient:
    return NotionClient(s.notion_token.get_secret_value())


@app.command()
def keygen() -> None:
    """Generate a STATE_KEY for encrypting the review history."""
    typer.echo(state.generate_key())


@app.command()
def check() -> None:
    """Verify Notion access and that the configured property names/types exist."""
    s = _settings()
    try:
        with _client(s) as client:
            for label, db_id, expected in (
                ("Highlights", s.highlights_database_id, highlights_schema(s)),
                ("Library", s.library_database_id, library_schema(s)),
            ):
                source = client.get_data_source(db_id)
                typer.echo(f"{label}: data source {source['id']}")
                for name, prop in sorted(source["properties"].items()):
                    typer.echo(f"  - {name!r}: {prop['type']}")
                check_schema(source, expected)
                typer.secho(f"  OK, all configured {label} properties found", fg="green")
    except NotionError as exc:
        typer.secho(str(exc), fg="red")
        with _client(s) as client:
            typer.echo("Databases shared with the integration (use the database ID):")
            for ds in client.search_data_sources():
                title = "".join(t.get("plain_text", "") for t in ds.get("title", []))
                db_id = ds.get("parent", {}).get("database_id", "?")
                typer.echo(f"  {title!r}: {db_id.replace('-', '')}")
        raise typer.Exit(1) from exc


@app.command()
def sync(
    full: Annotated[
        bool, typer.Option(help="Re-process every page, not just edited ones.")
    ] = False,
    bodies: Annotated[
        bool, typer.Option(help="Also fetch all page bodies (slow first time).")
    ] = False,
) -> None:
    """Pull Notion databases into the local SQLite cache."""
    s = _settings()
    conn = _open_db(s)
    with _client(s) as client:
        stats = sync_all(conn, client, s, full=full)
        typer.echo(
            f"Books: {stats.books} | highlights: {stats.highlights_seen} seen, "
            f"{stats.highlights_updated} updated, {stats.highlights_deleted} removed"
        )
        if bodies:
            typer.echo(f"Fetched {fetch_bodies(conn, client)} page bodies")


def _build_digest(conn: sqlite3.Connection, s: Settings, now: datetime) -> list[selector.Highlight]:
    with _client(s) as client:
        sync_all(conn, client, s)
        picked = selector.pick(selector.load_candidates(conn), s, now)
        fetch_bodies(conn, client, [h.id for h in picked])
    selector.refresh_bodies(conn, picked)
    return picked


@app.command()
def preview(
    out: Annotated[Path, typer.Option(help="Where to write the HTML preview.")] = Path(
        "digest_preview.html"
    ),
) -> None:
    """Build a digest and write it to an HTML file without sending or recording it."""
    s = _settings()
    conn = _open_db(s)
    now = datetime.now(UTC)
    picked = _build_digest(conn, s, now)
    _, _, html = mailer.render(picked, now.astimezone(ZoneInfo(s.timezone)).date())
    out.write_text(html, encoding="utf-8")
    typer.echo(f"Preview with {len(picked)} highlights written to {out}")


@app.command()
def send(
    force: Annotated[
        bool, typer.Option(help="Ignore send time and already-sent-today checks.")
    ] = False,
) -> None:
    """Daily job: sync, pick highlights, email them, and record the review history."""
    s = _settings()
    conn = _open_db(s)
    now = datetime.now(UTC)
    local = now.astimezone(ZoneInfo(s.timezone))

    if not force:
        if local.time() < s.send_time:
            typer.echo(f"Not yet {s.send_time:%H:%M} in {s.timezone}; skipping.")
            return
        if selector.already_sent(conn, local.date()):
            typer.echo(f"Digest for {local.date()} already sent; skipping.")
            return

    picked = _build_digest(conn, s, now)
    if not picked:
        typer.secho("No highlights available to send.", fg="red")
        raise typer.Exit(1)

    mailer.send(s, *mailer.render(picked, local.date()))
    selector.record_digest(conn, picked, now, local.date())
    if s.state_key:
        state.save_encrypted(conn, s.state_path, s.state_key.get_secret_value())
    else:
        typer.secho("STATE_KEY not set: review history kept only in the local DB.", fg="yellow")
    typer.secho(f"Sent digest with {len(picked)} highlights.", fg="green")


@app.command()
def stats() -> None:
    """Show counts (safe for public CI logs: no highlight content)."""
    conn = _open_db(_settings())
    rows = {
        "Books": "SELECT COUNT(*) FROM books",
        "Highlights": "SELECT COUNT(*) FROM highlights WHERE deleted = 0",
        "Favorites": "SELECT COUNT(*) FROM highlights WHERE deleted = 0 AND favorite = 1",
        "Digests sent": "SELECT COUNT(*) FROM digests",
        "Distinct shown": "SELECT COUNT(DISTINCT highlight_id) FROM deliveries",
    }
    for label, sql in rows.items():
        typer.echo(f"{label + ':':<16}{conn.execute(sql).fetchone()[0]}")

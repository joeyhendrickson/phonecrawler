from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.crawler.url_queue import QueueItem
from app.models.records import PageRecord, PhoneOccurrence, QueueKind
from app.utils.helpers import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS pending (
    normalized_url TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    depth INTEGER NOT NULL,
    kind TEXT NOT NULL,
    referring_url TEXT,
    source TEXT,
    enqueued_at TEXT
);
CREATE TABLE IF NOT EXISTS visited (
    normalized_url TEXT PRIMARY KEY,
    kind TEXT,
    status TEXT,
    final_url TEXT,
    http_status INTEGER,
    processed_at TEXT,
    page_json TEXT
);
CREATE TABLE IF NOT EXISTS occurrences (
    occurrence_id TEXT PRIMARY KEY,
    normalized_url TEXT,
    payload TEXT
);
"""


class CrawlState:
    """SQLite crawl checkpoint so interrupted jobs can resume."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def add_pending(self, item: QueueItem) -> None:
        self._conn.execute(
            """
            INSERT INTO pending(normalized_url, url, depth, kind, referring_url, source, enqueued_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_url) DO NOTHING
            """,
            (
                item.normalized_url,
                item.url,
                item.depth,
                item.kind.value,
                item.referring_url,
                item.source,
                utcnow().isoformat(),
            ),
        )
        self._conn.commit()

    def complete(
        self,
        *,
        item: QueueItem,
        page: PageRecord,
        occurrences: list[PhoneOccurrence],
    ) -> None:
        self._conn.execute("DELETE FROM pending WHERE normalized_url=?", (item.normalized_url,))
        self._conn.execute(
            """
            INSERT INTO visited(normalized_url, kind, status, final_url, http_status, processed_at, page_json)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_url) DO UPDATE SET
                kind=excluded.kind,
                status=excluded.status,
                final_url=excluded.final_url,
                http_status=excluded.http_status,
                processed_at=excluded.processed_at,
                page_json=excluded.page_json
            """,
            (
                item.normalized_url,
                page.kind.value,
                page.status.value,
                page.final_url,
                page.http_status,
                utcnow().isoformat(),
                page.model_dump_json(),
            ),
        )
        for occurrence in occurrences:
            self._conn.execute(
                """
                INSERT INTO occurrences(occurrence_id, normalized_url, payload)
                VALUES(?, ?, ?)
                ON CONFLICT(occurrence_id) DO NOTHING
                """,
                (occurrence.occurrence_id, item.normalized_url, occurrence.model_dump_json()),
            )
        self._conn.commit()

    def pending_items(self) -> list[QueueItem]:
        rows = self._conn.execute(
            "SELECT url, normalized_url, depth, kind, referring_url, source FROM pending"
        ).fetchall()
        return [
            QueueItem(
                url=row["url"],
                normalized_url=row["normalized_url"],
                depth=int(row["depth"]),
                kind=QueueKind(row["kind"]),
                referring_url=row["referring_url"],
                source=row["source"] or "resume",
            )
            for row in rows
        ]

    def visited_items(self) -> list[tuple[str, QueueKind]]:
        rows = self._conn.execute("SELECT normalized_url, kind FROM visited").fetchall()
        return [(row["normalized_url"], QueueKind(row["kind"])) for row in rows]

    def load_pages(self) -> list[PageRecord]:
        rows = self._conn.execute("SELECT page_json FROM visited WHERE page_json IS NOT NULL").fetchall()
        return [PageRecord.model_validate_json(row["page_json"]) for row in rows]

    def load_occurrences(self) -> list[PhoneOccurrence]:
        rows = self._conn.execute("SELECT payload FROM occurrences").fetchall()
        return [PhoneOccurrence.model_validate_json(row["payload"]) for row in rows]

    def close(self) -> None:
        self._conn.close()

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.models.records import QueueKind


@dataclass(frozen=True)
class QueueItem:
    url: str
    normalized_url: str
    depth: int
    kind: QueueKind
    referring_url: str | None = None
    source: str = "crawl"


class UrlQueue:
    """Async FIFO queue with URL deduplication and HTML/PDF scheduling caps."""

    def __init__(self, *, max_pages: int, max_pdfs: int) -> None:
        self.max_pages = max_pages
        self.max_pdfs = max_pdfs
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue()
        self._seen: set[str] = set()
        self._lock = asyncio.Lock()
        self.html_scheduled = 0
        self.pdf_scheduled = 0
        self._active_workers = 0

    @property
    def seen_count(self) -> int:
        return len(self._seen)

    def qsize(self) -> int:
        return self._queue.qsize()

    def note_seen(self, url: str, kind: QueueKind) -> None:
        """Mark a URL as already processed (resume). Does not enqueue."""
        if url in self._seen:
            return
        self._seen.add(url)
        if kind == QueueKind.HTML:
            self.html_scheduled += 1
        else:
            self.pdf_scheduled += 1

    async def push(self, item: QueueItem) -> bool:
        async with self._lock:
            if item.normalized_url in self._seen:
                return False
            if item.kind == QueueKind.HTML:
                if self.max_pages and self.html_scheduled >= self.max_pages:
                    return False
                self.html_scheduled += 1
            else:
                if self.max_pdfs and self.pdf_scheduled >= self.max_pdfs:
                    return False
                self.pdf_scheduled += 1
            self._seen.add(item.normalized_url)
            await self._queue.put(item)
            return True

    async def put_sentinel(self) -> None:
        await self._queue.put(
            QueueItem(url="", normalized_url="", depth=0, kind=QueueKind.HTML, source="sentinel")
        )

    async def get(self) -> QueueItem:
        item = await self._queue.get()
        async with self._lock:
            self._active_workers += 1
        return item

    def task_done(self) -> None:
        self._queue.task_done()
        # active_workers is decremented in worker finally via mark_idle

    async def mark_idle(self) -> None:
        async with self._lock:
            self._active_workers = max(0, self._active_workers - 1)

    async def join(self) -> None:
        await self._queue.join()

    async def is_idle(self) -> bool:
        async with self._lock:
            return self._queue.empty() and self._active_workers == 0

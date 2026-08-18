from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import CrawlConfig
from app.crawler.robots import RobotsRules, load_robots
from app.crawler.sitemap import discover_sitemaps
from app.crawler.state import CrawlState
from app.crawler.url_normalizer import (
    DomainScope,
    compile_patterns,
    is_internal,
    normalize_url,
    parse_scope,
    should_skip_url,
)
from app.crawler.url_queue import QueueItem, UrlQueue
from app.extractors.context_extractor import context_for_candidate, context_for_tel_element, find_element_for_raw
from app.extractors.html_extractor import PageExtraction, extract_page, should_render_javascript
from app.extractors.js_renderer import JavascriptRenderer
from app.extractors.pdf_extractor import extract_pdf_bytes
from app.extractors.phone_extractor import PhoneCandidate, extract_phones_from_text, parse_candidate, parse_tel_href
from app.models.records import (
    CrawlEvent,
    CrawlResult,
    ExtractionMethod,
    PageRecord,
    PageStatus,
    PhoneOccurrence,
    QueueKind,
    SitemapUrl,
    SourceType,
)
from app.processing.reconciliation import reconcile_occurrences
from app.utils.helpers import (
    content_type_is_html,
    content_type_is_pdf,
    filename_from_url,
    looks_like_pdf_url,
    new_id,
    utcnow,
)
from app.utils.logging import announce, get_logger

logger = get_logger(__name__)

RETRYABLE = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


class PhoneCrawler:
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.scope: DomainScope = parse_scope(
            config.start_url, allow_subdomains=config.allow_subdomains
        )
        self.queue = UrlQueue(max_pages=config.max_pages, max_pdfs=config.max_pdfs)
        self.robots = RobotsRules()
        self.renderer = JavascriptRenderer(
            timeout_ms=config.timeout * 1000, user_agent=config.user_agent
        )
        self.exclude_patterns = compile_patterns(config.exclude_url_patterns)
        self.include_patterns = compile_patterns(config.include_url_patterns)
        self.pages: list[PageRecord] = []
        self.occurrences: list[PhoneOccurrence] = []
        self.events: list[CrawlEvent] = []
        self.sitemaps = []
        self.sitemap_urls: list[SitemapUrl] = []
        self.state: CrawlState | None = None
        self._audit_path = config.output_dir / "audit.jsonl"
        self._delay = config.delay

    async def run(self) -> CrawlResult:
        started = utcnow()
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        state_path = self.config.output_dir / "crawl_state.sqlite"
        if self.config.resume and state_path.exists():
            self.state = CrawlState(state_path)
            self.pages = self.state.load_pages()
            self.occurrences = self.state.load_occurrences()
            for url, kind in self.state.visited_items():
                self.queue.note_seen(url, kind)
            for item in self.state.pending_items():
                await self.queue.push(item)
            announce("RESUME", f"visited={len(self.pages)} pending={self.queue.qsize()}")
        else:
            if state_path.exists():
                state_path.unlink()
                for suffix in ("-wal", "-shm"):
                    extra = Path(str(state_path) + suffix)
                    if extra.exists():
                        extra.unlink()
            self.state = CrawlState(state_path)
            self.state.set_meta("start_url", self.scope.start_url)
            self.state.set_meta("started_at", started.isoformat())

        limits = httpx.Limits(
            max_connections=self.config.concurrency + 4,
            max_keepalive_connections=self.config.concurrency,
        )
        timeout = httpx.Timeout(self.config.timeout, connect=min(10.0, self.config.timeout))
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(
            headers=headers,
            limits=limits,
            timeout=timeout,
            follow_redirects=True,
            http2=False,
        ) as client:
            self.client = client
            if self.config.respect_robots:
                self.robots = await load_robots(
                    client, self.scope.start_url, user_agent=self.config.user_agent
                )
                if self.robots.crawl_delay:
                    self._delay = max(self._delay, self.robots.crawl_delay)

            sitemap_urls = []
            if self.config.discover_sitemaps:
                records, sitemap_urls = await discover_sitemaps(
                    client,
                    self.scope.start_url,
                    self.scope,
                    extra_sitemap_urls=self.robots.sitemaps,
                    strip_query_params=self.config.strip_query_params,
                )
                self.sitemaps = records
                self.sitemap_urls = sitemap_urls
                for record in records:
                    announce("DISCOVER", f"{record.sitemap_url} — {record.url_count:,} URLs")
            else:
                self.sitemaps = []
                self.sitemap_urls = []

            seed = normalize_url(
                self.scope.start_url, strip_query_params=self.config.strip_query_params
            )
            if seed:
                await self._enqueue(
                    seed,
                    depth=0,
                    kind=QueueKind.HTML,
                    source="seed",
                    referring_url=None,
                )
            for item in sitemap_urls:
                normalized = normalize_url(
                    item.url, strip_query_params=self.config.strip_query_params
                )
                if not normalized:
                    continue
                kind = QueueKind.PDF if looks_like_pdf_url(normalized) else QueueKind.HTML
                await self._enqueue(
                    normalized,
                    depth=0,
                    kind=kind,
                    source="sitemap",
                    referring_url=item.sitemap_source,
                )

            workers = [
                asyncio.create_task(self._worker(index))
                for index in range(self.config.concurrency)
            ]
            await self.queue.join()
            for _ in workers:
                await self.queue.put_sentinel()
            await asyncio.gather(*workers, return_exceptions=True)
            await self.renderer.close()
            if self.state is not None:
                self.state.close()

        result = CrawlResult(
            start_url=self.scope.start_url,
            allowed_hosts=[self.scope.hostname]
            + ([self.scope.registrable_domain] if self.config.allow_subdomains else []),
            registrable_domain=self.scope.registrable_domain,
            pages=self.pages,
            occurrences=self.occurrences,
            sitemaps=self.sitemaps,
            sitemap_urls=self.sitemap_urls,
            events=self.events,
            started_at=started,
            finished_at=utcnow(),
        )
        return result

    async def _enqueue(
        self,
        url: str,
        *,
        depth: int,
        kind: QueueKind,
        source: str,
        referring_url: str | None,
    ) -> bool:
        if depth > self.config.max_depth:
            self._event(url, PageStatus.SKIPPED_MAX_DEPTH, source)
            return False
        skip, reason = should_skip_url(
            url,
            exclude_patterns=self.exclude_patterns,
            include_patterns=self.include_patterns or None,
        )
        if skip:
            self._event(url, PageStatus.SKIPPED_PATTERN, reason)
            return False
        if self.config.respect_robots and not self.robots.can_fetch(
            self.config.user_agent, url, respect=True
        ):
            self._event(url, PageStatus.SKIPPED_ROBOTS, "robots.txt")
            return False
        item = QueueItem(
            url=url,
            normalized_url=url,
            depth=depth,
            kind=kind,
            referring_url=referring_url,
            source=source,
        )
        pushed = await self.queue.push(item)
        if pushed and self.state is not None:
            self.state.add_pending(item)
        return pushed

    async def _worker(self, index: int) -> None:
        while True:
            item = await self.queue.get()
            if not item.normalized_url or item.source == "sentinel":
                self.queue.task_done()
                await self.queue.mark_idle()
                break
            try:
                if self._delay:
                    await asyncio.sleep(self._delay)
                await self._process(item)
            except Exception as exc:
                logger.exception("worker_error", url=item.url, error=str(exc))
                self._record_page(
                    item,
                    status=PageStatus.FAILED_PARSE,
                    error=str(exc),
                    final_url=item.url,
                )
            finally:
                self.queue.task_done()
                await self.queue.mark_idle()

    async def _process(self, item: QueueItem) -> None:
        if item.kind == QueueKind.PDF:
            await self._process_pdf(item)
            return
        await self._process_html(item)

    async def _fetch(self, url: str) -> tuple[httpx.Response | None, float, PageStatus | None, str | None]:
        started = time.perf_counter()

        @retry(
            stop=stop_after_attempt(self.config.retries),
            wait=wait_exponential(multiplier=0.6, min=0.6, max=8),
            retry=retry_if_exception_type(RETRYABLE),
            reraise=True,
        )
        async def _once() -> httpx.Response:
            return await self.client.get(url)

        try:
            response = await _once()
        except httpx.TimeoutException as exc:
            return None, (time.perf_counter() - started) * 1000, PageStatus.FAILED_TIMEOUT, str(exc)
        except httpx.HTTPError as exc:
            return None, (time.perf_counter() - started) * 1000, PageStatus.FAILED_NETWORK, str(exc)
        elapsed = (time.perf_counter() - started) * 1000
        return response, elapsed, None, None

    async def _process_html(self, item: QueueItem) -> None:
        response, elapsed, fail_status, error = await self._fetch(item.url)
        if response is None:
            self._record_page(
                item, status=fail_status or PageStatus.FAILED_NETWORK, error=error, response_time_ms=elapsed
            )
            return
        final_url = str(response.url)
        if not is_internal(final_url, self.scope):
            self._record_page(
                item,
                status=PageStatus.SKIPPED_EXTERNAL_REDIRECT,
                http_status=response.status_code,
                final_url=final_url,
                content_type=response.headers.get("content-type"),
                response_time_ms=elapsed,
                bytes_count=len(response.content),
            )
            return
        content_type = response.headers.get("content-type", "")
        size = len(response.content)
        if size > self.config.max_file_size:
            self._record_page(
                item,
                status=PageStatus.SKIPPED_TOO_LARGE,
                http_status=response.status_code,
                final_url=final_url,
                content_type=content_type,
                response_time_ms=elapsed,
                bytes_count=size,
            )
            return
        if response.status_code >= 400:
            self._record_page(
                item,
                status=PageStatus.FAILED_HTTP,
                http_status=response.status_code,
                final_url=final_url,
                content_type=content_type,
                response_time_ms=elapsed,
                bytes_count=size,
                error=f"HTTP {response.status_code}",
            )
            return
        if content_type_is_pdf(content_type) or looks_like_pdf_url(final_url):
            await self._ingest_pdf(
                item,
                data=response.content,
                final_url=final_url,
                http_status=response.status_code,
                content_type=content_type,
                elapsed=elapsed,
            )
            return
        if not content_type_is_html(content_type) and not _looks_like_html(response.content):
            self._record_page(
                item,
                status=PageStatus.SKIPPED_CONTENT_TYPE,
                http_status=response.status_code,
                final_url=final_url,
                content_type=content_type,
                response_time_ms=elapsed,
                bytes_count=size,
            )
            return

        html = response.text
        extraction = extract_page(
            html, final_url, self.scope, strip_query_params=self.config.strip_query_params
        )
        static_occurrences = self._occurrences_from_html(
            extraction,
            source_url=item.url,
            final_url=final_url,
            http_status=response.status_code,
            referring_url=item.referring_url,
            source_type=SourceType.HTML,
        )
        rendered = False
        render_reason = None
        need_js, render_reason = should_render_javascript(extraction, mode=self.config.render_js)
        if need_js:
            announce("JS", f"Rendering {final_url}")
            rendered_html = await self.renderer.render(final_url)
            if rendered_html is None:
                self._event(final_url, PageStatus.RENDER_UNAVAILABLE, self.renderer.error)
            else:
                rendered = True
                rendered_extraction = extract_page(
                    rendered_html.html,
                    rendered_html.final_url or final_url,
                    self.scope,
                    strip_query_params=self.config.strip_query_params,
                )
                js_occurrences = self._occurrences_from_html(
                    rendered_extraction,
                    source_url=item.url,
                    final_url=rendered_html.final_url or final_url,
                    http_status=response.status_code,
                    referring_url=item.referring_url,
                    source_type=SourceType.JAVASCRIPT_RENDERED,
                )
                static_occurrences = reconcile_occurrences(static_occurrences, js_occurrences)
                extraction = rendered_extraction
                final_url = rendered_html.final_url or final_url

        self.occurrences.extend(static_occurrences)
        await self._enqueue_links(extraction, depth=item.depth + 1, referring_url=final_url)
        self._record_page(
            item,
            status=PageStatus.SUCCESS_RENDERED if rendered else PageStatus.SUCCESS,
            http_status=response.status_code,
            final_url=final_url,
            content_type=content_type,
            response_time_ms=elapsed,
            bytes_count=size,
            title=extraction.title,
            h1=extraction.h1,
            canonical=extraction.canonical_url,
            visible_text_length=extraction.visible_text_length,
            phone_count=len(static_occurrences),
            link_count=len(extraction.internal_links),
            pdf_link_count=len(extraction.pdf_links),
            rendered_js=rendered,
            js_render_reason=render_reason if rendered else None,
            occurrences=static_occurrences,
        )

    async def _enqueue_links(self, extraction: PageExtraction, *, depth: int, referring_url: str) -> None:
        for url in extraction.internal_links:
            await self._enqueue(
                url, depth=depth, kind=QueueKind.HTML, source="html_link", referring_url=referring_url
            )
        if self.config.include_pdfs:
            for url in extraction.pdf_links:
                await self._enqueue(
                    url, depth=depth, kind=QueueKind.PDF, source="html_pdf_link", referring_url=referring_url
                )

    async def _process_pdf(self, item: QueueItem) -> None:
        if not self.config.include_pdfs:
            return
        response, elapsed, fail_status, error = await self._fetch(item.url)
        if response is None:
            self._record_page(
                item, status=fail_status or PageStatus.FAILED_NETWORK, error=error, response_time_ms=elapsed
            )
            return
        final_url = str(response.url)
        if not is_internal(final_url, self.scope):
            self._record_page(
                item,
                status=PageStatus.SKIPPED_EXTERNAL_REDIRECT,
                http_status=response.status_code,
                final_url=final_url,
                response_time_ms=elapsed,
            )
            return
        if response.status_code >= 400:
            self._record_page(
                item,
                status=PageStatus.FAILED_HTTP,
                http_status=response.status_code,
                final_url=final_url,
                error=f"HTTP {response.status_code}",
                response_time_ms=elapsed,
            )
            return
        await self._ingest_pdf(
            item,
            data=response.content,
            final_url=final_url,
            http_status=response.status_code,
            content_type=response.headers.get("content-type"),
            elapsed=elapsed,
        )

    async def _ingest_pdf(
        self,
        item: QueueItem,
        *,
        data: bytes,
        final_url: str,
        http_status: int,
        content_type: str | None,
        elapsed: float,
    ) -> None:
        filename = filename_from_url(final_url)
        extracted = extract_pdf_bytes(data, filename)
        found: list[PhoneOccurrence] = []
        if extracted.text_unavailable:
            status = PageStatus.PDF_TEXT_UNAVAILABLE
        else:
            status = PageStatus.SUCCESS
            for page in extracted.pages:
                for candidate in extract_phones_from_text(page.text, self.config.country):
                    context = _pdf_context(page.text, candidate)
                    found.append(
                        self._occurrence_from_candidate(
                            candidate,
                            source_url=item.url,
                            final_url=final_url,
                            source_type=SourceType.PDF,
                            extraction_method=ExtractionMethod.PDF_TEXT,
                            page_title=filename,
                            referring_url=item.referring_url,
                            http_status=http_status,
                            context=context,
                            pdf_page_number=page.page_number,
                            pdf_filename=filename,
                        )
                    )
        self.occurrences.extend(found)
        if found:
            announce("PDF", f"{final_url} — {len(found)} numbers")
        self._record_page(
            item,
            status=status,
            http_status=http_status,
            final_url=final_url,
            content_type=content_type,
            response_time_ms=elapsed,
            bytes_count=len(data),
            title=filename,
            phone_count=len(found),
            notes=extracted.notes,
            kind=QueueKind.PDF,
            occurrences=found,
        )

    def _occurrences_from_html(
        self,
        extraction: PageExtraction,
        *,
        source_url: str,
        final_url: str,
        http_status: int,
        referring_url: str | None,
        source_type: SourceType,
    ) -> list[PhoneOccurrence]:
        occurrences: list[PhoneOccurrence] = []
        seen: set[str] = set()

        def add(
            candidate: PhoneCandidate,
            *,
            stype: SourceType,
            method: ExtractionMethod,
            context: str | None,
            heading: str | None = None,
            container: str | None = None,
        ) -> None:
            key = f"{candidate.e164 or candidate.normalized or candidate.raw_phone}|{candidate.extension or ''}|{method.value}"
            if key in seen:
                return
            seen.add(key)
            occurrences.append(
                self._occurrence_from_candidate(
                    candidate,
                    source_url=source_url,
                    final_url=final_url,
                    source_type=stype,
                    extraction_method=method,
                    page_title=extraction.title,
                    page_h1=extraction.h1,
                    referring_url=referring_url,
                    http_status=http_status,
                    context=context,
                    nearest_heading=heading,
                    nearest_container=container,
                )
            )

        for tel in extraction.tel_links:
            candidate = parse_tel_href(tel.raw_number, self.config.country)
            element = find_element_for_raw(extraction.soup, tel.raw_number or tel.text)
            context, heading = context_for_tel_element(
                element, fallback_text=" ".join(part for part in (tel.text, tel.raw_number) if part)
            )
            add(
                candidate,
                stype=SourceType.HTML_TEL_LINK if source_type != SourceType.JAVASCRIPT_RENDERED else source_type,
                method=ExtractionMethod.TEL_LINK,
                context=context,
                heading=heading,
                container=context,
            )
        for raw in extraction.schema_phones:
            candidate = parse_candidate(raw, self.config.country)
            context, heading, _ = context_for_candidate(
                candidate, text=extraction.text, soup=extraction.soup
            )
            add(
                candidate,
                stype=SourceType.HTML_SCHEMA if source_type != SourceType.JAVASCRIPT_RENDERED else source_type,
                method=ExtractionMethod.SCHEMA,
                context=context,
                heading=heading,
            )
        combined_text = " ".join(
            part
            for part in (
                extraction.text,
                extraction.header_text,
                extraction.footer_text,
                extraction.nav_text,
            )
            if part
        )
        method = (
            ExtractionMethod.JS_TEXT
            if source_type == SourceType.JAVASCRIPT_RENDERED
            else ExtractionMethod.TEXT
        )
        for candidate in extract_phones_from_text(combined_text, self.config.country):
            context, heading, _ = context_for_candidate(
                candidate, text=combined_text, soup=extraction.soup
            )
            add(
                candidate,
                stype=source_type,
                method=method,
                context=context,
                heading=heading or (extraction.headings[0] if extraction.headings else None),
            )
        return occurrences

    def _occurrence_from_candidate(
        self,
        candidate: PhoneCandidate,
        *,
        source_url: str,
        final_url: str,
        source_type: SourceType,
        extraction_method: ExtractionMethod,
        page_title: str | None = None,
        page_h1: str | None = None,
        referring_url: str | None = None,
        http_status: int | None = None,
        context: str | None = None,
        nearest_heading: str | None = None,
        nearest_container: str | None = None,
        pdf_page_number: int | None = None,
        pdf_filename: str | None = None,
    ) -> PhoneOccurrence:
        return PhoneOccurrence(
            occurrence_id=new_id(),
            raw_phone=candidate.raw_phone,
            normalized_phone=candidate.normalized,
            e164_phone=candidate.e164,
            national_format=candidate.national,
            extension=candidate.extension,
            country_code=candidate.country_code,
            validation_status=candidate.validation_status,
            source_url=source_url,
            final_url=final_url,
            source_type=source_type,
            page_title=page_title,
            page_h1=page_h1,
            context=context,
            nearest_heading=nearest_heading,
            nearest_container=nearest_container,
            pdf_page_number=pdf_page_number,
            pdf_filename=pdf_filename,
            referring_url=referring_url,
            crawl_timestamp=utcnow(),
            http_status=http_status,
            extraction_method=extraction_method,
            notes=candidate.notes,
        )

    def _record_page(
        self,
        item: QueueItem,
        *,
        status: PageStatus,
        http_status: int | None = None,
        final_url: str | None = None,
        content_type: str | None = None,
        response_time_ms: float | None = None,
        bytes_count: int | None = None,
        title: str | None = None,
        h1: str | None = None,
        canonical: str | None = None,
        error: str | None = None,
        visible_text_length: int = 0,
        phone_count: int = 0,
        link_count: int = 0,
        pdf_link_count: int = 0,
        rendered_js: bool = False,
        js_render_reason: str | None = None,
        notes: str | None = None,
        kind: QueueKind | None = None,
        occurrences: list[PhoneOccurrence] | None = None,
    ) -> None:
        record = PageRecord(
            requested_url=item.url,
            final_url=final_url,
            normalized_url=item.normalized_url,
            kind=kind or item.kind,
            http_status=http_status,
            content_type=content_type,
            response_time_ms=round(response_time_ms, 2) if response_time_ms is not None else None,
            crawl_timestamp=utcnow(),
            page_title=title,
            page_h1=h1,
            canonical_url=canonical,
            depth=item.depth,
            referring_url=item.referring_url,
            source=item.source,
            status=status,
            error=error,
            visible_text_length=visible_text_length,
            phone_count=phone_count,
            link_count=link_count,
            pdf_link_count=pdf_link_count,
            rendered_js=rendered_js,
            js_render_reason=js_render_reason,
            bytes=bytes_count,
            notes=notes,
        )
        self.pages.append(record)
        self._event(item.url, status, error)
        self._write_audit(record)
        scheduled = max(self.queue.html_scheduled + self.queue.pdf_scheduled, 1)
        announce("CRAWL", f"{len(self.pages)}/{scheduled} {item.url}")
        if status.value.startswith("FAILED") or (http_status is not None and http_status >= 400):
            announce("ERROR", f"{http_status or status.value} {item.url}")
        seen_phones: set[str] = set()
        for occurrence in occurrences or []:
            label = occurrence.e164_phone or occurrence.normalized_phone or occurrence.raw_phone
            if not label or label in seen_phones:
                continue
            seen_phones.add(label)
            announce("PHONE", f"{label} — {record.page_title or item.url}")
        if self.state is not None:
            self.state.complete(item=item, page=record, occurrences=occurrences or [])

    def _event(self, url: str, status: PageStatus, detail: str | None = None) -> None:
        self.events.append(
            CrawlEvent(timestamp=utcnow(), url=url, status=status, detail=detail)
        )
        logger.info("crawl_event", url=url, status=status.value, detail=detail)

    def _write_audit(self, record: PageRecord) -> None:
        try:
            with self._audit_path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
        except OSError as exc:
            logger.warning("audit_write_failed", error=str(exc))


def _looks_like_html(content: bytes) -> bool:
    snippet = content[:512].lstrip().lower()
    return snippet.startswith(b"<!doctype html") or snippet.startswith(b"<html")


def _pdf_context(text: str, candidate: PhoneCandidate, radius: int = 150) -> str:
    if candidate.start is None or candidate.end is None:
        return text[:300]
    left = max(0, candidate.start - radius)
    right = min(len(text), candidate.end + radius)
    return " ".join(text[left:right].split())

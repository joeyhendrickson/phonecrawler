from __future__ import annotations

from app.crawler.url_normalizer import normalize_url
from app.models.records import (
    CoverageStatus,
    CrawlEvent,
    CrawlResult,
    PageRecord,
    PageStatus,
    SitemapUrl,
    UrlInventoryRecord,
)

SUCCESS = {PageStatus.SUCCESS, PageStatus.SUCCESS_RENDERED, PageStatus.PDF_TEXT_UNAVAILABLE}
FAILED = {
    PageStatus.FAILED_HTTP,
    PageStatus.FAILED_TIMEOUT,
    PageStatus.FAILED_NETWORK,
    PageStatus.FAILED_PARSE,
}
REDIRECTED = {PageStatus.SKIPPED_EXTERNAL_REDIRECT}
EXCLUDED = {
    PageStatus.SKIPPED_ROBOTS,
    PageStatus.SKIPPED_PATTERN,
    PageStatus.SKIPPED_EXTERNAL,
    PageStatus.SKIPPED_CONTENT_TYPE,
    PageStatus.SKIPPED_MAX_PAGES,
    PageStatus.SKIPPED_MAX_DEPTH,
    PageStatus.SKIPPED_TOO_LARGE,
}


def _status_for(*, in_sitemap: bool, page: PageRecord | None) -> CoverageStatus:
    if page is None:
        return CoverageStatus.SITEMAP_NOT_CRAWLED if in_sitemap else CoverageStatus.EXCLUDED
    if page.status in SUCCESS:
        return CoverageStatus.SITEMAP_AND_CRAWLED if in_sitemap else CoverageStatus.CRAWLED_NOT_IN_SITEMAP
    if page.status in REDIRECTED:
        return CoverageStatus.REDIRECTED
    if page.status in FAILED:
        return CoverageStatus.DISCOVERED_BUT_FAILED
    if page.status in EXCLUDED:
        return CoverageStatus.EXCLUDED
    return CoverageStatus.DISCOVERED_BUT_FAILED


def build_url_inventory(
    *,
    pages: list[PageRecord],
    sitemap_urls: list[SitemapUrl],
    events: list[CrawlEvent],
    strip_query_params: list[str] | None = None,
) -> list[UrlInventoryRecord]:
    """Reconcile sitemap URLs, crawled URLs, and link-discovered URLs."""
    sitemap_meta: dict[str, SitemapUrl] = {}
    for item in sitemap_urls:
        key = normalize_url(item.url, strip_query_params=strip_query_params) or item.url
        sitemap_meta.setdefault(key, item)

    pages_by_url: dict[str, PageRecord] = {}
    for page in pages:
        key = page.normalized_url or page.requested_url
        existing = pages_by_url.get(key)
        if existing is None or page.crawl_timestamp >= existing.crawl_timestamp:
            pages_by_url[key] = page

    excluded_events: dict[str, CrawlEvent] = {}
    for event in events:
        status = event.status if isinstance(event.status, PageStatus) else None
        if status in EXCLUDED or status in REDIRECTED:
            key = normalize_url(event.url, strip_query_params=strip_query_params) or event.url
            excluded_events.setdefault(key, event)

    keys = set(sitemap_meta) | set(pages_by_url) | set(excluded_events)
    records: list[UrlInventoryRecord] = []
    for key in sorted(keys):
        page = pages_by_url.get(key)
        sitemap_item = sitemap_meta.get(key)
        event = excluded_events.get(key)
        in_sitemap = sitemap_item is not None
        if page is not None:
            status = _status_for(in_sitemap=in_sitemap, page=page)
            records.append(
                UrlInventoryRecord(
                    url=page.requested_url,
                    normalized_url=key,
                    final_url=page.final_url,
                    coverage_status=status,
                    discovery_source=page.source,
                    in_sitemap=in_sitemap,
                    crawled=page.status in SUCCESS,
                    http_status=page.http_status,
                    page_status=page.status.value,
                    lastmod=sitemap_item.lastmod if sitemap_item else None,
                    referring_url=page.referring_url,
                    error=page.error,
                    kind=page.kind.value,
                )
            )
        elif event is not None:
            event_status = event.status if isinstance(event.status, PageStatus) else PageStatus.SKIPPED_PATTERN
            coverage = (
                CoverageStatus.REDIRECTED
                if event_status in REDIRECTED
                else CoverageStatus.EXCLUDED
            )
            records.append(
                UrlInventoryRecord(
                    url=event.url,
                    normalized_url=key,
                    coverage_status=coverage if not in_sitemap else (
                        CoverageStatus.EXCLUDED if coverage == CoverageStatus.EXCLUDED else coverage
                    ),
                    discovery_source=event.detail or "event",
                    in_sitemap=in_sitemap,
                    crawled=False,
                    page_status=event_status.value if isinstance(event_status, PageStatus) else str(event.status),
                    lastmod=sitemap_item.lastmod if sitemap_item else None,
                    error=event.detail,
                )
            )
        else:
            records.append(
                UrlInventoryRecord(
                    url=sitemap_item.url if sitemap_item else key,
                    normalized_url=key,
                    coverage_status=CoverageStatus.SITEMAP_NOT_CRAWLED,
                    discovery_source="sitemap",
                    in_sitemap=True,
                    crawled=False,
                    lastmod=sitemap_item.lastmod if sitemap_item else None,
                )
            )
    return records


def attach_coverage(result: CrawlResult, strip_query_params: list[str] | None = None) -> CrawlResult:
    result.url_inventory = build_url_inventory(
        pages=result.pages,
        sitemap_urls=result.sitemap_urls,
        events=result.events,
        strip_query_params=strip_query_params,
    )
    return result

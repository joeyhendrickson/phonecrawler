from __future__ import annotations

from datetime import datetime, timezone

from app.crawler.url_normalizer import normalize_url
from app.models.records import (
    CoverageStatus,
    CrawlEvent,
    PageRecord,
    PageStatus,
    QueueKind,
    SitemapUrl,
)
from app.processing.coverage import build_url_inventory


def _page(url: str, status: PageStatus, source: str = "html_link") -> PageRecord:
    return PageRecord(
        requested_url=url,
        final_url=url,
        normalized_url=normalize_url(url) or url,
        kind=QueueKind.HTML,
        crawl_timestamp=datetime.now(timezone.utc),
        source=source,
        status=status,
        http_status=200 if status.value.startswith("SUCCESS") else 500,
    )


def test_sitemap_reconciliation_classifications():
    sitemap = [
        SitemapUrl(url="https://www.example.edu/", lastmod="2026-01-01", sitemap_source="sitemap.xml"),
        SitemapUrl(url="https://www.example.edu/missing", sitemap_source="sitemap.xml"),
        SitemapUrl(url="https://www.example.edu/broken", sitemap_source="sitemap.xml"),
    ]
    pages = [
        _page("https://www.example.edu/", PageStatus.SUCCESS, source="sitemap"),
        _page("https://www.example.edu/directory", PageStatus.SUCCESS, source="html_link"),
        _page("https://www.example.edu/broken", PageStatus.FAILED_HTTP, source="sitemap"),
        _page("https://www.example.edu/old", PageStatus.SKIPPED_EXTERNAL_REDIRECT, source="html_link"),
    ]
    events = [
        CrawlEvent(
            timestamp=datetime.now(timezone.utc),
            url="https://www.example.edu/login",
            status=PageStatus.SKIPPED_PATTERN,
            detail="exclude_pattern",
        )
    ]
    inventory = build_url_inventory(pages=pages, sitemap_urls=sitemap, events=events)
    by_url = {item.normalized_url: item.coverage_status for item in inventory}
    home = normalize_url("https://www.example.edu/") or "https://www.example.edu/"
    assert by_url[home] == CoverageStatus.SITEMAP_AND_CRAWLED
    assert by_url[normalize_url("https://www.example.edu/missing") or ""] == CoverageStatus.SITEMAP_NOT_CRAWLED
    assert by_url[normalize_url("https://www.example.edu/directory") or ""] == CoverageStatus.CRAWLED_NOT_IN_SITEMAP
    assert by_url[normalize_url("https://www.example.edu/broken") or ""] == CoverageStatus.DISCOVERED_BUT_FAILED
    assert by_url[normalize_url("https://www.example.edu/old") or ""] == CoverageStatus.REDIRECTED
    assert by_url[normalize_url("https://www.example.edu/login") or ""] == CoverageStatus.EXCLUDED

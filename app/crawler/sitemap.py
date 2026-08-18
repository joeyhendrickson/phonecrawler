from __future__ import annotations

import gzip
from urllib.parse import urljoin, urlparse

import httpx
from lxml import etree

from app.crawler.url_normalizer import DomainScope, is_internal, normalize_url
from app.models.records import SitemapRecord, SitemapUrl
from app.utils.logging import get_logger

logger = get_logger(__name__)

MAX_SITEMAP_DEPTH = 8
MAX_SITEMAP_URLS = 100_000


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def parse_sitemap_xml(content: bytes, sitemap_url: str) -> tuple[list[str], list[SitemapUrl]]:
    """Return (child_sitemap_urls, page_urls)."""
    child_sitemaps: list[str] = []
    urls: list[SitemapUrl] = []
    try:
        root = etree.fromstring(content)
    except etree.XMLSyntaxError:
        return child_sitemaps, urls

    root_name = _local(root.tag).lower()
    if root_name == "sitemapindex":
        for node in root.iter():
            if _local(node.tag).lower() == "loc" and node.text:
                child_sitemaps.append(node.text.strip())
        return child_sitemaps, urls

    for url_node in root.iter():
        if _local(url_node.tag).lower() != "url":
            continue
        loc = None
        lastmod = None
        for child in url_node:
            name = _local(child.tag).lower()
            if name == "loc" and child.text:
                loc = child.text.strip()
            elif name == "lastmod" and child.text:
                lastmod = child.text.strip()
        if loc:
            urls.append(SitemapUrl(url=loc, lastmod=lastmod, sitemap_source=sitemap_url))
    # Some malformed sitemaps put <loc> directly under urlset
    if not urls:
        for node in root.iter():
            if _local(node.tag).lower() == "loc" and node.text:
                loc = node.text.strip()
                if loc:
                    urls.append(SitemapUrl(url=loc, lastmod=None, sitemap_source=sitemap_url))
    return child_sitemaps, urls


def maybe_decompress(url: str, content: bytes) -> bytes:
    if url.lower().endswith(".gz") or content[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(content)
        except OSError:
            return content
    return content


async def fetch_sitemap_bytes(client: httpx.AsyncClient, url: str) -> tuple[bytes | None, str | None]:
    try:
        response = await client.get(url, timeout=30.0, follow_redirects=True)
        if response.status_code >= 400:
            return None, f"HTTP {response.status_code}"
        return maybe_decompress(str(response.url), response.content), None
    except httpx.HTTPError as exc:
        return None, str(exc)


async def discover_sitemaps(
    client: httpx.AsyncClient,
    start_url: str,
    scope: DomainScope,
    *,
    extra_sitemap_urls: list[str] | None = None,
    strip_query_params: list[str] | None = None,
) -> tuple[list[SitemapRecord], list[SitemapUrl]]:
    origin = scope.origin
    seeds = [
        urljoin(origin, "/sitemap.xml"),
        urljoin(origin, "/sitemap_index.xml"),
    ]
    if extra_sitemap_urls:
        seeds.extend(extra_sitemap_urls)

    records: list[SitemapRecord] = []
    collected: list[SitemapUrl] = []
    seen_sitemaps: set[str] = set()
    queue: list[tuple[str, str, int]] = [(url, "seed", 0) for url in seeds]
    # source label, depth

    while queue and len(collected) < MAX_SITEMAP_URLS:
        sitemap_url, source, depth = queue.pop(0)
        normalized = normalize_url(sitemap_url, strip_query_params=strip_query_params) or sitemap_url
        if normalized in seen_sitemaps:
            continue
        seen_sitemaps.add(normalized)
        if depth > MAX_SITEMAP_DEPTH:
            records.append(
                SitemapRecord(
                    sitemap_url=normalized,
                    source=source,
                    status="SKIPPED_DEPTH",
                    nested=depth > 0,
                )
            )
            continue

        content, error = await fetch_sitemap_bytes(client, normalized)
        if error or content is None:
            records.append(
                SitemapRecord(
                    sitemap_url=normalized,
                    source=source,
                    status="FAILED",
                    error=error,
                    nested=depth > 0,
                )
            )
            continue

        child_sitemaps, urls = parse_sitemap_xml(content, normalized)
        in_scope: list[SitemapUrl] = []
        for item in urls:
            abs_url = item.url
            parsed = urlparse(abs_url)
            if not parsed.scheme:
                abs_url = urljoin(normalized, abs_url)
            if not is_internal(abs_url, scope):
                continue
            in_scope.append(
                SitemapUrl(url=abs_url, lastmod=item.lastmod, sitemap_source=normalized)
            )
        collected.extend(in_scope)
        records.append(
            SitemapRecord(
                sitemap_url=normalized,
                source=source,
                status="SUCCESS",
                url_count=len(in_scope),
                nested=depth > 0,
            )
        )
        logger.info("sitemap_parsed", url=normalized, urls=len(in_scope), children=len(child_sitemaps))
        for child in child_sitemaps:
            child_abs = child if urlparse(child).scheme else urljoin(normalized, child)
            queue.append((child_abs, normalized, depth + 1))

    return records, collected

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ValidationStatus(StrEnum):
    VALID = "VALID"
    POSSIBLE = "POSSIBLE"
    INVALID = "INVALID"


class SourceType(StrEnum):
    HTML = "HTML"
    HTML_TEL_LINK = "HTML_TEL_LINK"
    HTML_SCHEMA = "HTML_SCHEMA"
    JAVASCRIPT_RENDERED = "JAVASCRIPT_RENDERED"
    PDF = "PDF"


class NumberKind(StrEnum):
    VOICE = "VOICE"
    FAX = "FAX"
    UNKNOWN = "UNKNOWN"


class ClassificationSource(StrEnum):
    RULES = "RULES"
    AI = "AI"
    UNCLASSIFIED = "UNCLASSIFIED"


class PageStatus(StrEnum):
    SUCCESS = "SUCCESS"
    SUCCESS_RENDERED = "SUCCESS_RENDERED"
    SKIPPED_ROBOTS = "SKIPPED_ROBOTS"
    SKIPPED_PATTERN = "SKIPPED_PATTERN"
    SKIPPED_EXTERNAL = "SKIPPED_EXTERNAL"
    SKIPPED_EXTERNAL_REDIRECT = "SKIPPED_EXTERNAL_REDIRECT"
    SKIPPED_CONTENT_TYPE = "SKIPPED_CONTENT_TYPE"
    SKIPPED_MAX_PAGES = "SKIPPED_MAX_PAGES"
    SKIPPED_MAX_DEPTH = "SKIPPED_MAX_DEPTH"
    SKIPPED_TOO_LARGE = "SKIPPED_TOO_LARGE"
    FAILED_HTTP = "FAILED_HTTP"
    FAILED_TIMEOUT = "FAILED_TIMEOUT"
    FAILED_NETWORK = "FAILED_NETWORK"
    FAILED_PARSE = "FAILED_PARSE"
    PDF_TEXT_UNAVAILABLE = "PDF_TEXT_UNAVAILABLE"
    RENDER_UNAVAILABLE = "RENDER_UNAVAILABLE"


class ExtractionMethod(StrEnum):
    TEL_LINK = "TEL_LINK"
    SCHEMA = "SCHEMA"
    TEXT = "TEXT"
    JS_TEXT = "JS_TEXT"
    PDF_TEXT = "PDF_TEXT"


class QueueKind(StrEnum):
    HTML = "HTML"
    PDF = "PDF"


class CoverageStatus(StrEnum):
    SITEMAP_AND_CRAWLED = "SITEMAP_AND_CRAWLED"
    SITEMAP_NOT_CRAWLED = "SITEMAP_NOT_CRAWLED"
    CRAWLED_NOT_IN_SITEMAP = "CRAWLED_NOT_IN_SITEMAP"
    DISCOVERED_BUT_FAILED = "DISCOVERED_BUT_FAILED"
    EXCLUDED = "EXCLUDED"
    REDIRECTED = "REDIRECTED"


class PhoneOccurrence(BaseModel):
    occurrence_id: str
    raw_phone: str
    normalized_phone: str | None = None
    e164_phone: str | None = None
    national_format: str | None = None
    extension: str | None = None
    country_code: int | None = None
    validation_status: ValidationStatus = ValidationStatus.INVALID
    source_url: str
    final_url: str
    source_type: SourceType
    page_title: str | None = None
    page_h1: str | None = None
    context: str | None = None
    nearest_heading: str | None = None
    nearest_container: str | None = None
    pdf_page_number: int | None = None
    pdf_filename: str | None = None
    referring_url: str | None = None
    crawl_timestamp: datetime
    http_status: int | None = None
    extraction_method: ExtractionMethod
    js_confirmed: bool = False
    notes: str | None = None


class UniquePhone(BaseModel):
    normalized_phone: str | None = None
    e164_phone: str | None = None
    national_format: str | None = None
    extension: str | None = None
    country_code: int | None = None
    validation_status: ValidationStatus = ValidationStatus.INVALID
    occurrence_count: int = 0
    unique_url_count: int = 0
    source_count: int = 0
    source_urls: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    page_titles: list[str] = Field(default_factory=list)
    sample_contexts: list[str] = Field(default_factory=list)
    nearest_headings: list[str] = Field(default_factory=list)
    number_kind: NumberKind = NumberKind.UNKNOWN
    category: str = "Unknown"
    classification: str = "Unknown"
    classification_source: ClassificationSource = ClassificationSource.UNCLASSIFIED
    classification_confidence: float | None = None
    departments_or_context: str | None = None
    first_seen_url: str | None = None
    notes: str | None = None


class UrlInventoryRecord(BaseModel):
    url: str
    normalized_url: str
    final_url: str | None = None
    coverage_status: CoverageStatus
    discovery_source: str = "unknown"
    in_sitemap: bool = False
    crawled: bool = False
    http_status: int | None = None
    page_status: str | None = None
    lastmod: str | None = None
    referring_url: str | None = None
    error: str | None = None
    kind: str | None = None


class PageRecord(BaseModel):
    requested_url: str
    final_url: str | None = None
    normalized_url: str
    kind: QueueKind = QueueKind.HTML
    http_status: int | None = None
    content_type: str | None = None
    response_time_ms: float | None = None
    crawl_timestamp: datetime
    page_title: str | None = None
    page_h1: str | None = None
    canonical_url: str | None = None
    depth: int = 0
    referring_url: str | None = None
    source: str = "crawl"
    status: PageStatus
    error: str | None = None
    visible_text_length: int = 0
    phone_count: int = 0
    link_count: int = 0
    pdf_link_count: int = 0
    rendered_js: bool = False
    js_render_reason: str | None = None
    bytes: int | None = None
    notes: str | None = None


class SitemapRecord(BaseModel):
    sitemap_url: str
    source: str
    status: str
    url_count: int = 0
    lastmod: str | None = None
    error: str | None = None
    nested: bool = False


class SitemapUrl(BaseModel):
    url: str
    lastmod: str | None = None
    sitemap_source: str


class CrawlEvent(BaseModel):
    timestamp: datetime
    url: str
    status: PageStatus | str
    detail: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class CrawlResult(BaseModel):
    start_url: str
    allowed_hosts: list[str] = Field(default_factory=list)
    registrable_domain: str | None = None
    pages: list[PageRecord] = Field(default_factory=list)
    occurrences: list[PhoneOccurrence] = Field(default_factory=list)
    unique_phones: list[UniquePhone] = Field(default_factory=list)
    sitemaps: list[SitemapRecord] = Field(default_factory=list)
    sitemap_urls: list[SitemapUrl] = Field(default_factory=list)
    url_inventory: list[UrlInventoryRecord] = Field(default_factory=list)
    events: list[CrawlEvent] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime | None = None

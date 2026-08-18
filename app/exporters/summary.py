from __future__ import annotations

from collections import Counter

from app.models.records import (
    CoverageStatus,
    CrawlResult,
    PageStatus,
    QueueKind,
    UniquePhone,
    ValidationStatus,
)

SUCCESS = {PageStatus.SUCCESS, PageStatus.SUCCESS_RENDERED, PageStatus.PDF_TEXT_UNAVAILABLE}


def summary_rows(result: CrawlResult) -> list[dict[str, object]]:
    pages = result.pages
    phones = result.unique_phones
    inventory = result.url_inventory
    html_success = [
        page for page in pages if page.kind == QueueKind.HTML and page.status in SUCCESS
    ]
    pdfs = [page for page in pages if page.kind == QueueKind.PDF]
    pdf_success = [page for page in pdfs if page.status in SUCCESS]
    js_pages = [page for page in pages if page.rendered_js]
    failed = [page for page in pages if page.status.value.startswith("FAILED")]
    excluded = [
        row
        for row in inventory
        if row.coverage_status == CoverageStatus.EXCLUDED
    ]
    pages_with_phones = {occ.final_url or occ.source_url for occ in result.occurrences if occ.source_type.value != "PDF"}
    pdfs_with_phones = {
        occ.final_url or occ.source_url
        for occ in result.occurrences
        if occ.source_type.value == "PDF"
    }
    sitemap_url_count = len(result.sitemap_urls)
    crawled = sum(1 for page in pages if page.status in SUCCESS)
    discovered = len(inventory) or (len(pages) + sitemap_url_count)

    def _count(status: ValidationStatus) -> int:
        return sum(1 for phone in phones if phone.validation_status == status)

    rows: list[dict[str, object]] = [
        {"metric": "Domain", "value": result.registrable_domain or result.start_url},
        {"metric": "Start URL", "value": result.start_url},
        {"metric": "Crawl start time", "value": result.started_at.isoformat() if result.started_at else ""},
        {"metric": "Crawl completion time", "value": result.finished_at.isoformat() if result.finished_at else ""},
        {"metric": "URLs discovered", "value": discovered},
        {"metric": "URLs crawled", "value": crawled},
        {"metric": "URLs from sitemap", "value": sitemap_url_count},
        {"metric": "HTML pages processed", "value": len(html_success)},
        {"metric": "JavaScript-rendered pages", "value": len(js_pages)},
        {"metric": "PDFs processed", "value": len(pdf_success)},
        {"metric": "Unique phone numbers", "value": len(phones)},
        {"metric": "Total phone occurrences", "value": len(result.occurrences)},
        {"metric": "Valid phone numbers", "value": _count(ValidationStatus.VALID)},
        {"metric": "Possible phone numbers", "value": _count(ValidationStatus.POSSIBLE)},
        {"metric": "Invalid candidates", "value": _count(ValidationStatus.INVALID)},
        {"metric": "Pages containing phone numbers", "value": len(pages_with_phones)},
        {"metric": "PDFs containing phone numbers", "value": len(pdfs_with_phones)},
        {"metric": "Failed URLs", "value": len(failed)},
        {"metric": "Excluded URLs", "value": len(excluded)},
    ]
    coverage_counts = Counter(row.coverage_status.value for row in inventory)
    for status, count in sorted(coverage_counts.items()):
        rows.append({"metric": f"Coverage {status}", "value": count})
    return rows


def top_phones_by_occurrences(phones: list[UniquePhone], limit: int = 15) -> list[dict[str, object]]:
    ranked = sorted(phones, key=lambda item: (-item.occurrence_count, item.e164_phone or ""))
    return [
        {
            "rank": index,
            "e164_phone": item.e164_phone,
            "normalized_phone": item.normalized_phone,
            "occurrence_count": item.occurrence_count,
            "unique_url_count": item.unique_url_count,
            "category": item.category,
        }
        for index, item in enumerate(ranked[:limit], start=1)
    ]


def top_phones_by_urls(phones: list[UniquePhone], limit: int = 15) -> list[dict[str, object]]:
    ranked = sorted(phones, key=lambda item: (-item.unique_url_count, item.e164_phone or ""))
    return [
        {
            "rank": index,
            "e164_phone": item.e164_phone,
            "normalized_phone": item.normalized_phone,
            "unique_url_count": item.unique_url_count,
            "occurrence_count": item.occurrence_count,
            "category": item.category,
        }
        for index, item in enumerate(ranked[:limit], start=1)
    ]

from __future__ import annotations

from pathlib import Path

from app.exporters.summary import summary_rows
from app.models.records import (
    CrawlResult,
    PageRecord,
    PhoneOccurrence,
    UniquePhone,
    UrlInventoryRecord,
)


def _join(values: list[str] | None) -> str:
    return " | ".join(values or [])


def occurrences_to_rows(occurrences: list[PhoneOccurrence]) -> list[dict]:
    rows = []
    for item in occurrences:
        rows.append(
            {
                "occurrence_id": item.occurrence_id,
                "raw_phone": item.raw_phone,
                "normalized_phone": item.normalized_phone,
                "e164_phone": item.e164_phone,
                "national_format": item.national_format,
                "extension": item.extension,
                "country_code": item.country_code,
                "validation_status": item.validation_status.value,
                "source_url": item.source_url,
                "final_url": item.final_url,
                "source_type": item.source_type.value,
                "page_title": item.page_title,
                "page_h1": item.page_h1,
                "context": item.context,
                "nearest_heading": item.nearest_heading,
                "nearest_container": item.nearest_container,
                "pdf_page_number": item.pdf_page_number,
                "pdf_filename": item.pdf_filename,
                "referring_url": item.referring_url,
                "crawl_timestamp": item.crawl_timestamp.isoformat(),
                "http_status": item.http_status,
                "extraction_method": item.extraction_method.value,
                "js_confirmed": item.js_confirmed,
                "notes": item.notes,
            }
        )
    return rows


def inventory_to_rows(phones: list[UniquePhone]) -> list[dict]:
    rows = []
    for item in phones:
        rows.append(
            {
                "normalized_phone": item.normalized_phone,
                "e164_phone": item.e164_phone,
                "national_format": item.national_format,
                "extension": item.extension,
                "country_code": item.country_code,
                "validation_status": item.validation_status.value,
                "occurrence_count": item.occurrence_count,
                "unique_url_count": item.unique_url_count,
                "source_count": item.source_count,
                "source_urls": _join(item.source_urls),
                "source_types": _join(item.source_types),
                "page_titles": _join(item.page_titles),
                "sample_contexts": _join(item.sample_contexts),
                "nearest_headings": _join(item.nearest_headings),
                "departments_or_context": item.departments_or_context,
                "number_kind": item.number_kind.value,
                "category": item.category,
                "classification": item.classification,
                "classification_source": item.classification_source.value,
                "classification_confidence": item.classification_confidence,
                "first_seen_url": item.first_seen_url,
                "notes": item.notes,
            }
        )
    return rows


def pages_to_rows(pages: list[PageRecord]) -> list[dict]:
    rows = []
    for item in pages:
        rows.append(
            {
                "requested_url": item.requested_url,
                "final_url": item.final_url,
                "normalized_url": item.normalized_url,
                "kind": item.kind.value,
                "http_status": item.http_status,
                "content_type": item.content_type,
                "response_time_ms": item.response_time_ms,
                "crawl_timestamp": item.crawl_timestamp.isoformat(),
                "page_title": item.page_title,
                "page_h1": item.page_h1,
                "canonical_url": item.canonical_url,
                "depth": item.depth,
                "referring_url": item.referring_url,
                "source": item.source,
                "status": item.status.value,
                "error": item.error,
                "visible_text_length": item.visible_text_length,
                "phone_count": item.phone_count,
                "link_count": item.link_count,
                "pdf_link_count": item.pdf_link_count,
                "rendered_js": item.rendered_js,
                "js_render_reason": item.js_render_reason,
                "bytes": item.bytes,
                "notes": item.notes,
            }
        )
    return rows


def url_inventory_to_rows(rows: list[UrlInventoryRecord]) -> list[dict]:
    return [
        {
            "url": item.url,
            "normalized_url": item.normalized_url,
            "final_url": item.final_url,
            "coverage_status": item.coverage_status.value,
            "discovery_source": item.discovery_source,
            "in_sitemap": item.in_sitemap,
            "crawled": item.crawled,
            "http_status": item.http_status,
            "page_status": item.page_status,
            "lastmod": item.lastmod,
            "referring_url": item.referring_url,
            "error": item.error,
            "kind": item.kind,
        }
        for item in rows
    ]


def errors_to_rows(result: CrawlResult) -> list[dict]:
    rows = []
    for page in result.pages:
        if page.status.value.startswith("FAILED") or page.status.value == "PDF_TEXT_UNAVAILABLE":
            rows.append(
                {
                    "url": page.requested_url,
                    "final_url": page.final_url,
                    "status": page.status.value,
                    "http_status": page.http_status,
                    "error": page.error or page.notes,
                    "kind": page.kind.value,
                    "crawl_timestamp": page.crawl_timestamp.isoformat(),
                }
            )
    return rows


def export_csvs(result: CrawlResult, output_dir: Path) -> dict[str, Path]:
    import pandas as pd

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "inventory": output_dir / "phone_inventory.csv",
        "occurrences": output_dir / "phone_occurrences.csv",
        "url_inventory": output_dir / "url_inventory.csv",
        "crawl_report": output_dir / "crawl_report.csv",
        "crawl_errors": output_dir / "crawl_errors.csv",
        "pages": output_dir / "pages.csv",
        "sitemaps": output_dir / "sitemaps.csv",
    }
    pd.DataFrame(inventory_to_rows(result.unique_phones)).to_csv(paths["inventory"], index=False)
    pd.DataFrame(occurrences_to_rows(result.occurrences)).to_csv(paths["occurrences"], index=False)
    pd.DataFrame(url_inventory_to_rows(result.url_inventory)).to_csv(paths["url_inventory"], index=False)
    pd.DataFrame(summary_rows(result)).to_csv(paths["crawl_report"], index=False)
    pd.DataFrame(errors_to_rows(result)).to_csv(paths["crawl_errors"], index=False)
    pd.DataFrame(pages_to_rows(result.pages)).to_csv(paths["pages"], index=False)
    pd.DataFrame([item.model_dump() for item in result.sitemaps]).to_csv(paths["sitemaps"], index=False)
    return paths

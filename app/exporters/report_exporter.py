from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.exporters.summary import summary_rows
from app.models.records import CrawlResult, ValidationStatus
from app.utils.helpers import utcnow


def export_report(result: CrawlResult, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "crawl_report.json"
    md_path = output_dir / "crawl_report.md"
    payload = _report_payload(result)
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def _report_payload(result: CrawlResult) -> dict:
    status_counts = Counter(page.status.value for page in result.pages)
    validation_counts = Counter(item.validation_status.value for item in result.occurrences)
    source_counts = Counter(item.source_type.value for item in result.occurrences)
    kind_counts = Counter(item.kind.value for item in result.pages)
    duration = None
    if result.started_at and result.finished_at:
        duration = (result.finished_at - result.started_at).total_seconds()
    valid = sum(1 for item in result.unique_phones if item.validation_status == ValidationStatus.VALID)
    return {
        "generated_at": utcnow().isoformat(),
        "start_url": result.start_url,
        "registrable_domain": result.registrable_domain,
        "allowed_hosts": result.allowed_hosts,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "finished_at": result.finished_at.isoformat() if result.finished_at else None,
        "duration_seconds": duration,
        "unique_phones": len(result.unique_phones),
        "valid_unique_phones": valid,
        "occurrences": len(result.occurrences),
        "pages": len(result.pages),
        "sitemaps": len(result.sitemaps),
        "status_counts": dict(status_counts),
        "validation_counts": dict(validation_counts),
        "source_type_counts": dict(source_counts),
        "page_kind_counts": dict(kind_counts),
        "coverage_counts": dict(
            Counter(row.coverage_status.value for row in result.url_inventory)
        ),
        "summary": summary_rows(result),
        "sitemap_status": [
            {
                "url": item.sitemap_url,
                "status": item.status,
                "url_count": item.url_count,
                "error": item.error,
            }
            for item in result.sitemaps
        ],
    }


def _markdown(payload: dict) -> str:
    lines = [
        "# Crawl coverage report",
        "",
        f"- Start URL: `{payload['start_url']}`",
        f"- Domain: `{payload.get('registrable_domain')}`",
        f"- Started: {payload.get('started_at')}",
        f"- Finished: {payload.get('finished_at')}",
        f"- Duration (s): {payload.get('duration_seconds')}",
        f"- Unique phones: **{payload['unique_phones']}** ({payload['valid_unique_phones']} valid)",
        f"- Occurrences: {payload['occurrences']}",
        f"- Pages / documents processed: {payload['pages']}",
        "",
        "## Status counts",
        "",
    ]
    for key, value in sorted((payload.get("status_counts") or {}).items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Extraction source types", ""])
    for key, value in sorted((payload.get("source_type_counts") or {}).items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Coverage", ""])
    for key, value in sorted((payload.get("coverage_counts") or {}).items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Sitemaps", ""])
    for item in payload.get("sitemap_status") or []:
        lines.append(
            f"- `{item['url']}` — {item['status']} ({item['url_count']} URLs)"
            + (f" — {item['error']}" if item.get("error") else "")
        )
    lines.append("")
    return "\n".join(lines)

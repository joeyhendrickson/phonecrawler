from __future__ import annotations

from app.models.records import PhoneOccurrence, UniquePhone
from app.processing.normalization import dedupe_key, status_rank
from app.utils.helpers import join_unique


def build_unique_inventory(occurrences: list[PhoneOccurrence]) -> list[UniquePhone]:
    buckets: dict[str, list[PhoneOccurrence]] = {}
    order: list[str] = []
    for occurrence in occurrences:
        key = dedupe_key(
            occurrence.e164_phone,
            occurrence.normalized_phone,
            occurrence.extension,
            occurrence.raw_phone,
        )
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(occurrence)

    inventory: list[UniquePhone] = []
    for key in order:
        group = buckets[key]
        best = max(
            group,
            key=lambda item: (
                status_rank(item.validation_status),
                1 if item.e164_phone else 0,
                len(item.context or ""),
            ),
        )
        urls = join_unique([item.final_url or item.source_url for item in group])
        titles = join_unique([item.page_title or "" for item in group if item.page_title], limit=12)
        contexts = join_unique([item.context or "" for item in group if item.context], limit=8)
        headings = join_unique(
            [item.nearest_heading or "" for item in group if item.nearest_heading], limit=8
        )
        source_types = join_unique([item.source_type.value for item in group])
        inventory.append(
            UniquePhone(
                normalized_phone=best.normalized_phone,
                e164_phone=best.e164_phone,
                national_format=best.national_format,
                extension=best.extension,
                country_code=best.country_code,
                validation_status=best.validation_status,
                occurrence_count=len(group),
                unique_url_count=len(urls),
                source_count=len(urls),
                source_urls=urls,
                source_types=source_types,
                page_titles=titles,
                sample_contexts=contexts,
                nearest_headings=headings,
                first_seen_url=group[0].source_url,
            )
        )
    inventory.sort(
        key=lambda item: (-item.occurrence_count, item.e164_phone or item.normalized_phone or "")
    )
    return inventory

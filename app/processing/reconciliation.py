from __future__ import annotations

from app.models.records import ExtractionMethod, PhoneOccurrence, SourceType
from app.processing.normalization import dedupe_key


def reconcile_occurrences(
    static: list[PhoneOccurrence],
    rendered: list[PhoneOccurrence],
) -> list[PhoneOccurrence]:
    """Merge static HTML and JS-rendered extractions for the same page.

    Provenance is preserved. If the same number is found in both, keep a single
    occurrence and mark js_confirmed. JS-only numbers keep JAVASCRIPT_RENDERED.
    """
    index: dict[str, PhoneOccurrence] = {}
    order: list[str] = []

    def key_of(item: PhoneOccurrence) -> str:
        return dedupe_key(item.e164_phone, item.normalized_phone, item.extension, item.raw_phone)

    for item in static:
        key = key_of(item)
        if key not in index:
            index[key] = item
            order.append(key)
    for item in rendered:
        key = key_of(item)
        if key in index:
            existing = index[key]
            existing.js_confirmed = True
            if (len(item.context or "") > len(existing.context or "")) and item.context:
                existing.context = item.context
                existing.nearest_heading = item.nearest_heading or existing.nearest_heading
                existing.nearest_container = item.nearest_container or existing.nearest_container
        else:
            item.source_type = SourceType.JAVASCRIPT_RENDERED
            item.extraction_method = ExtractionMethod.JS_TEXT
            index[key] = item
            order.append(key)
    return [index[key] for key in order]

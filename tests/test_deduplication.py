from __future__ import annotations

from datetime import datetime, timezone

from app.models.records import (
    ExtractionMethod,
    PhoneOccurrence,
    SourceType,
    ValidationStatus,
)
from app.processing.classification import classify_inventory
from app.processing.deduplication import build_unique_inventory
from app.processing.normalization import dedupe_key


def _occ(**kwargs) -> PhoneOccurrence:
    defaults = dict(
        occurrence_id="x",
        raw_phone="(614) 555-1234",
        normalized_phone="614-555-1234",
        e164_phone="+16145551234",
        extension=None,
        validation_status=ValidationStatus.VALID,
        source_url="https://www.example.edu/a",
        final_url="https://www.example.edu/a",
        source_type=SourceType.HTML,
        page_title="Admissions",
        context="Jane Smith Director of Admissions 614-555-1234",
        nearest_heading="Office of Admissions",
        crawl_timestamp=datetime.now(timezone.utc),
        extraction_method=ExtractionMethod.TEXT,
    )
    defaults.update(kwargs)
    defaults["occurrence_id"] = kwargs.get("occurrence_id", defaults["source_url"] + defaults["raw_phone"])
    return PhoneOccurrence(**defaults)


def test_e164_is_primary_dedupe_key():
    items = [
        _occ(
            raw_phone="(614) 555-1234",
            source_url="https://www.example.edu/a",
            final_url="https://www.example.edu/a",
        ),
        _occ(
            raw_phone="614-555-1234",
            source_url="https://www.example.edu/b",
            final_url="https://www.example.edu/b",
            source_type=SourceType.PDF,
        ),
        _occ(
            raw_phone="+1 614 555 1234",
            source_url="https://www.example.edu/a",
            final_url="https://www.example.edu/a",
        ),
    ]
    inventory = build_unique_inventory(items)
    assert len(inventory) == 1
    unique = inventory[0]
    assert unique.e164_phone == "+16145551234"
    assert unique.occurrence_count == 3
    assert unique.source_count == 2
    assert unique.unique_url_count == 2
    assert unique.normalized_phone == "614-555-1234"


def test_extensions_are_distinct_keys():
    items = [
        _occ(extension=None),
        _occ(extension="321", source_url="https://www.example.edu/c"),
    ]
    inventory = build_unique_inventory(items)
    assert len(inventory) == 2
    assert {item.extension for item in inventory} == {None, "321"}


def test_dedupe_key_falls_back_when_e164_missing():
    assert dedupe_key(None, "614-555-0000", None, "raw") == "614-555-0000|"
    assert dedupe_key(None, None, None, "weird") == "raw:weird|"


def test_rule_based_classification_from_context():
    inventory = build_unique_inventory(
        [_occ(context="Contact the Office of Admissions at (614) 555-1234")]
    )
    classified = classify_inventory(inventory)
    assert classified[0].classification == "Admissions"
    assert classified[0].classification_source.value == "RULES"

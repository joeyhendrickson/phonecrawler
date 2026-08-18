from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.crawler.state import CrawlState
from app.crawler.url_queue import QueueItem
from app.models.records import (
    ExtractionMethod,
    PageRecord,
    PageStatus,
    PhoneOccurrence,
    QueueKind,
    SourceType,
    ValidationStatus,
)


def test_state_round_trip(tmp_path: Path):
    state = CrawlState(tmp_path / "crawl_state.sqlite")
    item = QueueItem(
        url="https://www.example.edu/admissions",
        normalized_url="https://www.example.edu/admissions",
        depth=0,
        kind=QueueKind.HTML,
        source="seed",
    )
    state.add_pending(item)
    assert len(state.pending_items()) == 1
    page = PageRecord(
        requested_url=item.url,
        final_url=item.url,
        normalized_url=item.normalized_url,
        crawl_timestamp=datetime.now(timezone.utc),
        status=PageStatus.SUCCESS,
        source="seed",
    )
    occ = PhoneOccurrence(
        occurrence_id="abc",
        raw_phone="(614) 555-1234",
        e164_phone="+16145551234",
        validation_status=ValidationStatus.VALID,
        source_url=item.url,
        final_url=item.url,
        source_type=SourceType.HTML,
        crawl_timestamp=datetime.now(timezone.utc),
        extraction_method=ExtractionMethod.TEXT,
    )
    state.complete(item=item, page=page, occurrences=[occ])
    assert state.pending_items() == []
    assert state.visited_items()[0][0] == item.normalized_url
    assert state.load_pages()[0].requested_url == item.url
    assert state.load_occurrences()[0].e164_phone == "+16145551234"
    state.close()

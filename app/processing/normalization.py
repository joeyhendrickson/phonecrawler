from __future__ import annotations

from app.extractors.phone_extractor import PhoneCandidate, parse_candidate
from app.models.records import ValidationStatus


def normalize_phone(raw: str, default_region: str = "US") -> PhoneCandidate:
    """Parse and normalize a raw phone string into standard fields."""
    return parse_candidate(raw, default_region=default_region)


def dedupe_key(e164: str | None, normalized: str | None, extension: str | None, raw: str) -> str:
    ext = (extension or "").strip()
    if e164:
        return f"{e164}|{ext}"
    if normalized:
        return f"{normalized}|{ext}"
    return f"raw:{raw.strip()}|{ext}"


def status_rank(status: ValidationStatus) -> int:
    return {
        ValidationStatus.VALID: 3,
        ValidationStatus.POSSIBLE: 2,
        ValidationStatus.INVALID: 1,
    }[status]

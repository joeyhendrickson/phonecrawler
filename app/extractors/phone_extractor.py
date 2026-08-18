from __future__ import annotations

import re
from dataclasses import dataclass

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberMatcher

from app.models.records import ValidationStatus

# Complementary regex for explicit tel-like tokens and extension tails.
US_LIKE_RE = re.compile(
    r"""
    (?<!\w)
    (?:
        \+?1[\s.\-()] *
    )?
    (?:\(?\d{3}\)?[\s.\-]*)\d{3}[\s.\-]*\d{4}
    (?:\s*(?:ext\.?|extension|x)\s*\.?\s*\d{1,6})?
    (?!\w)
    """,
    re.IGNORECASE | re.VERBOSE,
)
EXTENSION_RE = re.compile(
    r"(?:ext(?:ension)?\.?|x)\s*\.?\s*(\d{1,6})\b",
    re.IGNORECASE,
)
TEL_SEPARATOR_RE = re.compile(r"[;,]?(?:ext(?:ension)?|ext\.?|x)=?", re.I)
FALSE_POSITIVE_HINTS = re.compile(
    r"\b(zip(?:\s*code)?|isbn|invoice|order\s*#|student\s*id|ip\s*address|year)\b",
    re.I,
)
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
DATE_RE = re.compile(r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/](?:19|20)\d{2}\b")


@dataclass
class PhoneCandidate:
    raw_phone: str
    start: int | None = None
    end: int | None = None
    parsed: phonenumbers.PhoneNumber | None = None
    validation_status: ValidationStatus = ValidationStatus.INVALID
    extension: str | None = None
    e164: str | None = None
    national: str | None = None
    normalized: str | None = None
    country_code: int | None = None
    notes: str | None = None


def parse_tel_href(href: str, default_region: str = "US") -> PhoneCandidate:
    raw = href
    if raw.lower().startswith("tel:"):
        raw = raw.split(":", 1)[1]
    raw = raw.strip().replace("%20", " ")
    extension = None
    # tel:+16145551234;ext=321 or tel:+16145551234,321
    parts = re.split(r"[;,]", raw, maxsplit=1)
    number_part = parts[0]
    if len(parts) > 1:
        tail = parts[1]
        ext_match = re.search(r"(\d{1,6})", tail)
        if ext_match:
            extension = ext_match.group(1)
        ext_eq = re.search(r"ext(?:ension)?=(\d{1,6})", tail, re.I)
        if ext_eq:
            extension = ext_eq.group(1)
    return parse_candidate(number_part, default_region=default_region, extension=extension)


def parse_candidate(
    raw: str,
    default_region: str = "US",
    *,
    extension: str | None = None,
    start: int | None = None,
    end: int | None = None,
) -> PhoneCandidate:
    candidate = PhoneCandidate(raw_phone=raw.strip(), start=start, end=end, extension=extension)
    text = candidate.raw_phone
    ext_match = EXTENSION_RE.search(text)
    if ext_match and not candidate.extension:
        candidate.extension = ext_match.group(1)
        text = text[: ext_match.start()].strip()
        candidate.raw_phone = candidate.raw_phone.strip()
    try:
        parsed = phonenumbers.parse(text, default_region)
    except NumberParseException:
        candidate.notes = "parse_failed"
        return candidate
    candidate.parsed = parsed
    if parsed.extension and not candidate.extension:
        candidate.extension = str(parsed.extension)
    if phonenumbers.is_valid_number(parsed):
        candidate.validation_status = ValidationStatus.VALID
    elif phonenumbers.is_possible_number(parsed):
        candidate.validation_status = ValidationStatus.POSSIBLE
        candidate.notes = "possible_not_fully_valid"
    else:
        candidate.validation_status = ValidationStatus.INVALID
        candidate.notes = "invalid_number"
    if phonenumbers.is_possible_number(parsed):
        try:
            candidate.e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            candidate.national = phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.NATIONAL
            )
            candidate.normalized = _national_dashed(parsed, candidate.national)
            candidate.country_code = parsed.country_code
        except Exception:
            pass
    return candidate


def _national_dashed(parsed: phonenumbers.PhoneNumber, national: str | None) -> str | None:
    if parsed.country_code == 1:
        national_number = phonenumbers.national_significant_number(parsed)
        if len(national_number) == 10:
            return f"{national_number[:3]}-{national_number[3:6]}-{national_number[6:]}"
    if national:
        digits = re.sub(r"\D", "", national)
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        return re.sub(r"\s+", " ", national).strip()
    return None


def _looks_like_false_positive(raw: str, surrounding: str) -> bool:
    if IP_RE.search(raw):
        return True
    if DATE_RE.search(raw):
        return True
    digits = re.sub(r"\D", "", raw)
    if len(digits) in {4, 5} and not raw.strip().startswith("+"):
        return True
    if FALSE_POSITIVE_HINTS.search(surrounding):
        return True
    return False


def extract_phones_from_text(text: str, default_region: str = "US") -> list[PhoneCandidate]:
    if not text:
        return []
    candidates: list[PhoneCandidate] = []
    occupied: list[tuple[int, int]] = []

    for match in PhoneNumberMatcher(text, default_region):
        raw = match.raw_string
        start, end = match.start, match.end
        window = text[max(0, start - 40) : min(len(text), end + 40)]
        if _looks_like_false_positive(raw, window):
            candidate = PhoneCandidate(
                raw_phone=raw,
                start=start,
                end=end,
                validation_status=ValidationStatus.INVALID,
                notes="false_positive_hint",
            )
            candidates.append(candidate)
            occupied.append((start, end))
            continue
        extension = None
        tail = text[end : end + 24]
        ext_match = EXTENSION_RE.match(tail.strip()) if tail.strip() else None
        if not ext_match:
            ext_match = EXTENSION_RE.search(tail)
        if ext_match:
            extension = ext_match.group(1)
        parsed_candidate = parse_candidate(
            raw, default_region=default_region, extension=extension, start=start, end=end
        )
        if match.number.extension and not parsed_candidate.extension:
            parsed_candidate.extension = str(match.number.extension)
        candidates.append(parsed_candidate)
        occupied.append((start, end))

    def overlaps(start: int, end: int) -> bool:
        return any(start < existing_end and end > existing_start for existing_start, existing_end in occupied)

    for match in US_LIKE_RE.finditer(text):
        if overlaps(match.start(), match.end()):
            continue
        raw = match.group(0)
        window = text[max(0, match.start() - 40) : min(len(text), match.end() + 40)]
        if _looks_like_false_positive(raw, window):
            candidates.append(
                PhoneCandidate(
                    raw_phone=raw,
                    start=match.start(),
                    end=match.end(),
                    validation_status=ValidationStatus.INVALID,
                    notes="false_positive_hint",
                )
            )
            continue
        candidates.append(
            parse_candidate(raw, default_region=default_region, start=match.start(), end=match.end())
        )
    return candidates

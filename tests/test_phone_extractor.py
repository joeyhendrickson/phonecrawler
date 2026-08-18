from __future__ import annotations

from app.extractors.phone_extractor import extract_phones_from_text, parse_candidate, parse_tel_href
from app.models.records import ValidationStatus


def _by_e164(candidates):
    return {item.e164: item for item in candidates if item.e164}


def test_common_us_formats():
    text = """
    Call 614-555-1234 or 614.555.1234 or 614 555 1234
    or (614) 555-1234 or +1 614 555 1234 or 1-614-555-1234.
    """
    found = _by_e164(extract_phones_from_text(text, "US"))
    assert "+16145551234" in found
    assert found["+16145551234"].validation_status == ValidationStatus.VALID
    assert found["+16145551234"].normalized == "614-555-1234"


def test_extension_formats():
    dotted = parse_candidate("614-555-1234 ext. 321", "US")
    assert dotted.e164 == "+16145551234"
    assert dotted.extension == "321"

    x_form = parse_candidate("614-555-1234 x321", "US")
    assert x_form.extension == "321"

    ext542 = parse_candidate("614-555-1234 ext 542", "US")
    assert ext542.e164 == "+16145551234"
    assert ext542.extension == "542"

    text = "Office line 614-555-1234 ext. 321 is staffed weekdays."
    found = extract_phones_from_text(text, "US")
    assert any(item.e164 == "+16145551234" and item.extension == "321" for item in found)


def test_tel_href_parsing():
    candidate = parse_tel_href("tel:+16145551234;ext=321", "US")
    assert candidate.e164 == "+16145551234"
    assert candidate.extension == "321"
    assert candidate.validation_status == ValidationStatus.VALID


def test_does_not_silently_drop_uncertain_candidates():
    # 10-digit sequence that is possible but we still retain it
    found = extract_phones_from_text("Reference 000-000-0000 in the footer", "US")
    assert found
    assert all(item.validation_status in ValidationStatus for item in found)


def test_false_positives_are_marked_not_valid():
    text = "ZIP 43210 was issued in 2024. Invoice 123456789 and IP 192.168.1.1."
    found = extract_phones_from_text(text, "US")
    valid = [item for item in found if item.validation_status == ValidationStatus.VALID]
    assert valid == []


def test_national_and_e164_fields():
    candidate = parse_candidate("(614) 555-1234", "US")
    assert candidate.raw_phone == "(614) 555-1234"
    assert candidate.normalized == "614-555-1234"
    assert candidate.e164 == "+16145551234"
    assert candidate.national is not None
    assert candidate.country_code == 1

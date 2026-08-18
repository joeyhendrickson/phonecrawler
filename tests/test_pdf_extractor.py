from __future__ import annotations

from app.extractors.pdf_extractor import PDF_TEXT_UNAVAILABLE, extract_pdf_bytes
from app.extractors.phone_extractor import extract_phones_from_text


def _pdf_with_text(text: str) -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def test_pdf_extracts_phone_and_page_number():
    data = _pdf_with_text("Directory — Call (614) 555-1234 ext 542 for Admissions.")
    extracted = extract_pdf_bytes(data, "directory.pdf")
    assert extracted.text_unavailable is False
    assert extracted.page_count == 1
    found = extract_phones_from_text(extracted.pages[0].text, "US")
    assert any(item.e164 == "+16145551234" and item.extension == "542" for item in found)


def test_empty_pdf_is_marked_unavailable():
    import fitz

    document = fitz.open()
    document.new_page()
    data = document.tobytes()
    document.close()
    extracted = extract_pdf_bytes(data, "scanned.pdf")
    assert extracted.text_unavailable is True
    assert extracted.notes == PDF_TEXT_UNAVAILABLE

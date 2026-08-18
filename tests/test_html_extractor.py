from pathlib import Path

from app.crawler.url_normalizer import parse_scope
from app.extractors.context_extractor import context_for_candidate
from app.extractors.html_extractor import extract_page
from app.extractors.phone_extractor import extract_phones_from_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_html_extraction_captures_tel_schema_links_and_context():
    html = (FIXTURES / "sample.html").read_text(encoding="utf-8")
    scope = parse_scope("https://www.example.edu")
    page = extract_page(html, "https://www.example.edu/admissions/staff", scope)
    assert page.title == "Admissions Staff Directory"
    assert page.h1 == "Office of Admissions"
    assert page.canonical_url == "https://www.example.edu/admissions/staff"
    assert page.tel_links
    assert any("+16145551234" in tel.raw_number or "6145551234" in tel.raw_number.replace("-", "") for tel in page.tel_links)
    assert any("614-555-0199" in value or "6145550199" in value.replace("-", "") for value in page.schema_phones)
    assert any(link.endswith("/admissions/viewbook.pdf") for link in page.pdf_links)
    assert all("external.example.com" not in link for link in page.internal_links)

    jane = next(
        item
        for item in extract_phones_from_text(page.text, "US")
        if item.e164 == "+16145551234"
    )
    context, heading, kind = context_for_candidate(jane, text=page.text, soup=page.soup)
    assert "Jane Smith" in context
    assert "Director of Admissions" in context
    assert kind == "semantic_dom"
    assert heading in {"Jane Smith", "Office of Admissions"}

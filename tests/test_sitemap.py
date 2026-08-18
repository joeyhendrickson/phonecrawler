from __future__ import annotations

from pathlib import Path

from app.crawler.sitemap import parse_sitemap_xml
from app.crawler.url_normalizer import parse_scope

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_standard_urlset():
    xml = (FIXTURES / "sitemap.xml").read_bytes()
    children, urls = parse_sitemap_xml(xml, "https://www.example.edu/sitemap.xml")
    assert children == []
    locs = [item.url for item in urls]
    assert "https://www.example.edu/" in locs
    assert "https://www.example.edu/admissions" in locs
    assert "https://other.edu/should-skip" in locs  # filter happens later in discover
    assert any(item.lastmod == "2026-01-01" for item in urls)


def test_parse_sitemap_index():
    xml = (FIXTURES / "sitemap_index.xml").read_bytes()
    children, urls = parse_sitemap_xml(xml, "https://www.example.edu/sitemap_index.xml")
    assert urls == []
    assert "https://www.example.edu/sitemap-pages.xml" in children
    assert "/sitemap-staff.xml" in children


def test_scope_filters_external_sitemap_urls():
    scope = parse_scope("https://www.example.edu")
    xml = (FIXTURES / "sitemap.xml").read_bytes()
    _, urls = parse_sitemap_xml(xml, "https://www.example.edu/sitemap.xml")
    internal = [item for item in urls if item.url.startswith("https://www.example.edu")]
    assert len(internal) >= 2
    assert all("other.edu" not in item.url for item in internal)
    assert scope.registrable_domain == "example.edu"

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.crawler.url_normalizer import DomainScope, is_internal, normalize_url
from app.utils.helpers import looks_like_pdf_url

SCRIPT_STYLE_TAGS = ("script", "style", "template", "noscript")
SPA_ROOT_SELECTORS = "#root, #app, #__next, #__nuxt, [data-reactroot], [ng-version]"
FRAMEWORK_HINTS = ("react", "vue", "angular", "next/static", "nuxt", "ember", "svelte")


@dataclass
class TelLink:
    href: str
    text: str
    raw_number: str


@dataclass
class PageExtraction:
    title: str | None = None
    h1: str | None = None
    headings: list[str] = field(default_factory=list)
    canonical_url: str | None = None
    text: str = ""
    header_text: str = ""
    footer_text: str = ""
    nav_text: str = ""
    internal_links: list[str] = field(default_factory=list)
    pdf_links: list[str] = field(default_factory=list)
    tel_links: list[TelLink] = field(default_factory=list)
    schema_phones: list[str] = field(default_factory=list)
    soup: BeautifulSoup | None = None
    spa_signals: list[str] = field(default_factory=list)
    visible_text_length: int = 0


def parse_html(html: str, base_url: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def extract_page(
    html: str,
    base_url: str,
    scope: DomainScope,
    *,
    strip_query_params: list[str] | None = None,
) -> PageExtraction:
    soup = parse_html(html, base_url)
    working = BeautifulSoup(html, "lxml")
    for tag in working(SCRIPT_STYLE_TAGS):
        tag.decompose()

    title = None
    if working.title and working.title.string:
        title = working.title.string.strip()
    h1_tag = working.find("h1")
    h1 = h1_tag.get_text(" ", strip=True) if h1_tag else None
    headings = [
        tag.get_text(" ", strip=True)
        for tag in working.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        if tag.get_text(" ", strip=True)
    ]
    canonical = _canonical_url(working, base_url)
    text = _visible_text(working)
    header_text = _region_text(working, ["header", "[role=banner]"])
    footer_text = _region_text(working, ["footer", "[role=contentinfo]"])
    nav_text = _region_text(working, ["nav", "[role=navigation]"])

    internal_links, pdf_links = _collect_links(working, base_url, scope, strip_query_params)
    tel_links = _collect_tel_links(working)
    schema_phones = extract_schema_phones(soup)

    return PageExtraction(
        title=title,
        h1=h1,
        headings=headings,
        canonical_url=canonical,
        text=text,
        header_text=header_text,
        footer_text=footer_text,
        nav_text=nav_text,
        internal_links=internal_links,
        pdf_links=pdf_links,
        tel_links=tel_links,
        schema_phones=schema_phones,
        soup=working,
        spa_signals=detect_spa_signals(soup, text),
        visible_text_length=len(text),
    )


def _canonical_url(soup: BeautifulSoup, base_url: str) -> str | None:
    link = soup.find("link", rel=lambda value: value and "canonical" in value)
    if isinstance(link, Tag):
        href = link.get("href")
        if href:
            return urljoin(base_url, str(href).strip())
    return None


def _visible_text(soup: BeautifulSoup) -> str:
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def _region_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    chunks: list[str] = []
    for selector in selectors:
        for node in soup.select(selector):
            text = node.get_text(" ", strip=True)
            if text:
                chunks.append(text)
    return re.sub(r"\s+", " ", " ".join(chunks)).strip()


def _collect_links(
    soup: BeautifulSoup,
    base_url: str,
    scope: DomainScope,
    strip_query_params: list[str] | None,
) -> tuple[list[str], list[str]]:
    internal: list[str] = []
    pdfs: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "data:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        normalized = normalize_url(absolute, strip_query_params=strip_query_params)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        path = parsed.path.lower()
        if looks_like_pdf_url(absolute) or path.endswith(".pdf"):
            if is_internal(normalized, scope):
                pdfs.append(normalized)
            continue
        if is_internal(normalized, scope):
            internal.append(normalized)
    return internal, pdfs


def _collect_tel_links(soup: BeautifulSoup) -> list[TelLink]:
    links: list[TelLink] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href.lower().startswith("tel:"):
            continue
        raw = href.split(":", 1)[1].strip()
        text = anchor.get_text(" ", strip=True)
        links.append(TelLink(href=href, text=text, raw_number=raw))
    return links


def _walk_json(value: object, phones: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in {"telephone", "faxnumber", "phone", "phoneNumber"}:
                if isinstance(nested, str):
                    phones.append(nested)
                elif isinstance(nested, list):
                    phones.extend(str(item) for item in nested)
            else:
                _walk_json(nested, phones)
    elif isinstance(value, list):
        for item in value:
            _walk_json(item, phones)


def extract_schema_phones(soup: BeautifulSoup) -> list[str]:
    phones: list[str] = []
    for script in soup.find_all("script", type=lambda value: value and "ld+json" in str(value).lower()):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _walk_json(data, phones)
    for node in soup.find_all(attrs={"itemprop": re.compile(r"^(telephone|faxNumber)$", re.I)}):
        content = node.get("content") or node.get_text(" ", strip=True)
        if content:
            phones.append(str(content).strip())
    # dedupe preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for phone in phones:
        if phone not in seen:
            seen.add(phone)
            unique.append(phone)
    return unique


def detect_spa_signals(soup: BeautifulSoup, visible_text: str) -> list[str]:
    signals: list[str] = []
    if soup.select_one(SPA_ROOT_SELECTORS):
        signals.append("spa_root")
    sources = " ".join(str(tag.get("src", "")).lower() for tag in soup.find_all("script", src=True))
    if any(hint in sources for hint in FRAMEWORK_HINTS):
        signals.append("js_framework")
    if visible_text and len(visible_text) < 250:
        signals.append("thin_content")
    body = soup.find("body")
    if body and len(body.get_text(" ", strip=True)) < 120:
        signals.append("empty_body")
    return signals


def should_render_javascript(extraction: PageExtraction, *, mode: str) -> tuple[bool, str | None]:
    if mode == "off":
        return False, None
    if mode == "always":
        return True, "always"
    # auto
    if "thin_content" in extraction.spa_signals or "empty_body" in extraction.spa_signals:
        return True, "thin_content"
    if "spa_root" in extraction.spa_signals and extraction.visible_text_length < 1500:
        return True, "spa_root"
    if "js_framework" in extraction.spa_signals and extraction.visible_text_length < 800:
        return True, "js_framework"
    return False, None

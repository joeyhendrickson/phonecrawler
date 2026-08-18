from __future__ import annotations

import re
from bs4 import BeautifulSoup, NavigableString, Tag

from app.extractors.phone_extractor import PhoneCandidate
from app.utils.helpers import truncate

SEMANTIC_HINTS = re.compile(
    r"(card|profile|staff|person|people|employee|contact|directory|member|bio|vcard|listing)",
    re.I,
)
BLOCK_TAGS = {"div", "article", "section", "li", "tr", "td", "figure", "aside", "p", "header", "footer"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def window_context(text: str, start: int | None, end: int | None, radius: int = 150) -> str:
    if not text:
        return ""
    if start is None or end is None:
        return truncate(text, radius * 2) or ""
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right]
    if left > 0:
        snippet = "…" + snippet
    if right < len(text):
        snippet = snippet + "…"
    return re.sub(r"\s+", " ", snippet).strip()


def nearest_heading(element: Tag | None) -> str | None:
    if element is None:
        return None
    current: Tag | None = element
    while current is not None:
        previous = current.find_previous(list(HEADING_TAGS))
        if previous:
            text = previous.get_text(" ", strip=True)
            if text:
                return text
        current = current.parent if isinstance(current.parent, Tag) else None
    return None


def semantic_container_text(element: Tag | None) -> tuple[str | None, str | None]:
    """Return (container_text, nearest_heading) preferring cards / rows / list items."""
    if element is None:
        return None, None
    node: Tag | None = element if isinstance(element, Tag) else None
    chosen: Tag | None = None
    while node is not None:
        name = node.name.lower() if node.name else ""
        classes = " ".join(node.get("class", []) if isinstance(node.get("class"), list) else [])
        identity = f"{name} {classes} {node.get('id', '')}"
        if name in {"li", "tr", "article", "figure"} or SEMANTIC_HINTS.search(identity):
            chosen = node
            break
        if name in BLOCK_TAGS and chosen is None:
            text_len = len(node.get_text(" ", strip=True))
            if 20 < text_len < 800:
                chosen = node
        node = node.parent if isinstance(node.parent, Tag) else None
    heading = nearest_heading(element if isinstance(element, Tag) else chosen)
    if chosen is None:
        return None, heading
    text = re.sub(r"\s+", " ", chosen.get_text(" ", strip=True)).strip()
    return truncate(text, 600), heading


def find_element_for_raw(soup: BeautifulSoup | None, raw: str) -> Tag | None:
    if soup is None or not raw:
        return None
    # Prefer tel links containing this number's digits
    digits = re.sub(r"\D", "", raw)
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", ""))
        if href.lower().startswith("tel:") and digits and re.sub(r"\D", "", href).endswith(digits[-10:]):
            return anchor
    needle = raw.strip()
    match = soup.find(string=lambda value: isinstance(value, NavigableString) and needle in value)
    if match and isinstance(match.parent, Tag):
        return match.parent
    # Looser: search for the last 4 digits plus preceding token
    if len(digits) >= 10:
        compact_variants = [
            f"{digits[-10:-7]}-{digits[-7:-4]}-{digits[-4:]}",
            f"({digits[-10:-7]}) {digits[-7:-4]}-{digits[-4:]}",
            f"{digits[-10:-7]}.{digits[-7:-4]}.{digits[-4:]}",
        ]
        for variant in compact_variants:
            match = soup.find(string=lambda value, v=variant: isinstance(value, NavigableString) and v in value)
            if match and isinstance(match.parent, Tag):
                return match.parent
    return None


def context_for_candidate(
    candidate: PhoneCandidate,
    *,
    text: str,
    soup: BeautifulSoup | None = None,
) -> tuple[str, str | None, str | None]:
    element = find_element_for_raw(soup, candidate.raw_phone)
    container_text, heading = semantic_container_text(element)
    if container_text:
        return container_text, heading, "semantic_dom"
    snippet = window_context(text, candidate.start, candidate.end)
    return snippet, heading, "text_window"


def context_for_tel_element(element: Tag | None, fallback_text: str) -> tuple[str, str | None]:
    container_text, heading = semantic_container_text(element)
    if container_text:
        return container_text, heading
    return truncate(fallback_text, 400) or "", heading

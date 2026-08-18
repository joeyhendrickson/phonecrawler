from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

CONTENT_TYPE_HTML = re.compile(r"text/html|application/xhtml\+xml", re.I)
CONTENT_TYPE_PDF = re.compile(r"application/pdf|application/x-pdf", re.I)
CONTENT_TYPE_XML = re.compile(r"xml|gzip", re.I)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


def truncate(text: str | None, limit: int = 500) -> str | None:
    if text is None:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1]
    return name or "document.pdf"


def looks_like_pdf_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or ".pdf?" in url.lower()


def content_type_is_html(content_type: str | None) -> bool:
    return bool(content_type and CONTENT_TYPE_HTML.search(content_type))


def content_type_is_pdf(content_type: str | None) -> bool:
    return bool(content_type and CONTENT_TYPE_PDF.search(content_type))


def content_type_is_xml(content_type: str | None) -> bool:
    return bool(content_type and CONTENT_TYPE_XML.search(content_type))


def join_unique(values: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if limit is not None and len(out) >= limit:
            break
    return out

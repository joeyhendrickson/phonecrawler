from __future__ import annotations

from dataclasses import dataclass, field

from app.utils.logging import get_logger

logger = get_logger(__name__)

PDF_TEXT_UNAVAILABLE = "PDF_TEXT_UNAVAILABLE"


@dataclass
class PdfPage:
    page_number: int
    text: str


@dataclass
class PdfExtraction:
    filename: str
    page_count: int
    pages: list[PdfPage] = field(default_factory=list)
    text_unavailable: bool = False
    notes: str | None = None

    @property
    def full_text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)


def extract_pdf_bytes(data: bytes, filename: str) -> PdfExtraction:
    """Extract selectable text. OCR is intentionally not used."""
    try:
        import fitz
    except ImportError as exc:
        return PdfExtraction(
            filename=filename,
            page_count=0,
            text_unavailable=True,
            notes=f"pymupdf_missing: {exc}",
        )
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        logger.warning("pdf_open_failed", filename=filename, error=str(exc))
        return PdfExtraction(
            filename=filename,
            page_count=0,
            text_unavailable=True,
            notes=f"pdf_open_failed: {exc}",
        )
    pages: list[PdfPage] = []
    try:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text") or ""
            pages.append(PdfPage(page_number=index, text=text))
    finally:
        document.close()
    unavailable = all(not page.text.strip() for page in pages)
    return PdfExtraction(
        filename=filename,
        page_count=len(pages),
        pages=pages,
        text_unavailable=unavailable,
        notes=PDF_TEXT_UNAVAILABLE if unavailable else None,
    )

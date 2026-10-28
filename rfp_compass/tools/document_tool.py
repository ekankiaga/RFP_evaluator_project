"""Page-aware PDF extraction with PyMuPDF and pypdf fallback."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ExtractedDocument:
    pages: list[dict[str, object]]
    text: str
    document_hash: str
    page_count: int
    scanned: bool
    warnings: list[str]


class DocumentTool:
    """Extract page-preserving text, detect likely scanned documents, and chunk."""

    def extract(self, source: bytes | str | Path, chunk_chars: int = 12000) -> ExtractedDocument:
        raw = source if isinstance(source, bytes) else Path(source).read_bytes()
        warnings: list[str] = []
        pages: list[dict[str, object]] = []
        try:
            import pymupdf
            doc = pymupdf.open(stream=raw, filetype="pdf")
            for idx, page in enumerate(doc):
                pages.append({"page": idx + 1, "text": page.get_text("text").strip()})
            doc.close()
        except Exception as first_error:
            try:
                from pypdf import PdfReader
                import io
                reader = PdfReader(io.BytesIO(raw), strict=False)
                pages = [{"page": i + 1, "text": (p.extract_text() or "").strip()} for i, p in enumerate(reader.pages)]
                warnings.append(f"PyMuPDF extraction failed; used pypdf fallback: {type(first_error).__name__}")
            except Exception as fallback_error:
                raise ValueError(f"Unable to read PDF: {fallback_error}") from fallback_error
        if not pages:
            raise ValueError("PDF contains no pages")
        text = "\n\n".join(f"[Page {p['page']}]\n{p['text']}" for p in pages)
        scanned = sum(len(str(p["text"])) for p in pages) < 40
        if scanned:
            warnings.append("PDF appears scanned or image-only; OCR is not enabled, so evidence extraction may be incomplete.")
        if not text.strip():
            warnings.append("PDF contains no extractable text.")
        chunks: list[dict[str, object]] = []
        for page in pages:
            page_text = str(page["text"])
            for start in range(0, len(page_text), chunk_chars):
                chunks.append({"page": page["page"], "chunk": page_text[start:start + chunk_chars]})
        return ExtractedDocument(pages, text, hashlib.sha256(raw).hexdigest(), len(pages), scanned, warnings)


def verify_quote(quote: str, pages: list[dict[str, object]]) -> tuple[bool, int | None]:
    """Check exact then normalized substring evidence and return matching page."""
    if not quote.strip():
        return False, None
    normalized_quote = " ".join(quote.casefold().split())
    for item in pages:
        body = str(item.get("text", ""))
        if quote in body or normalized_quote in " ".join(body.casefold().split()):
            return True, int(item["page"])
    return False, None

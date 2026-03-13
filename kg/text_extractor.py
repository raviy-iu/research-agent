"""
kg/text_extractor.py – Extract plain text from downloaded corpus files.

Priority order per article:
  1. paper.pdf  (if download_status = "pdf")   -> pdfplumber page extraction
  2. fulltext.txt (if download_status = "fulltext") -> direct read
  3. metadata_only / failed                     -> title + abstract concatenated

The extracted text is passed to embedder.chunk_text() for vectorisation.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PDF extraction helpers
# ---------------------------------------------------------------------------

def _extract_pdf(pdf_path: Path, max_pages: int | None = None) -> str:
    """
    Extract text from a PDF using pdfplumber.

    Returns plain text with page breaks replaced by newlines.
    Returns empty string on any extraction error.
    """
    try:
        import pdfplumber  # lazy import – heavy dependency
    except ImportError:
        logger.warning("pdfplumber not installed; cannot extract PDF text")
        return ""

    try:
        parts: list[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages = pdf.pages[:max_pages] if max_pages else pdf.pages
            for page in pages:
                text = page.extract_text(layout=False)
                if text:
                    parts.append(text)
        return "\n".join(parts)
    except Exception as exc:
        logger.warning("PDF extraction failed for %s: %s", pdf_path, exc)
        return ""


def _clean_text(text: str) -> str:
    """
    Light cleaning: collapse runs of whitespace/newlines, strip ligatures.
    """
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Replace common PDF ligatures
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    return text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_text(
    local_path: str,
    download_status: str,
    title: str,
    abstract: str,
    kb_dir: Path | None = None,
) -> str:
    """
    Return the best available text for an article.

    Parameters
    ----------
    local_path      : Relative path from kb_dir (e.g. "papers/IEEE/safe_id_abc")
    download_status : "pdf" | "fulltext" | "metadata_only" | "failed"
    title           : Article title (always available)
    abstract        : Article abstract (may be empty)
    kb_dir          : Root of the knowledge_base directory (default: cwd)

    Returns
    -------
    str – Extracted plain text (may be a single short sentence for metadata-only)
    """
    from config import settings

    base = Path(kb_dir) if kb_dir else settings.kb_dir

    if download_status == "pdf" and local_path:
        pdf_file = base / local_path / "paper.pdf"
        if pdf_file.exists():
            text = _extract_pdf(pdf_file)
            if text.strip():
                return _clean_text(text)
            logger.warning("PDF extraction returned empty for %s", pdf_file)

    if download_status == "fulltext" and local_path:
        txt_file = base / local_path / "fulltext.txt"
        if txt_file.exists():
            try:
                text = txt_file.read_text(encoding="utf-8", errors="replace")
                return _clean_text(text)
            except Exception as exc:
                logger.warning("Cannot read fulltext.txt at %s: %s", txt_file, exc)

    # Fallback: title + abstract
    parts = [p for p in (title, abstract) if p and p.strip()]
    return " ".join(parts)

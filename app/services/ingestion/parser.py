"""PDF text extraction using pdfplumber.

Single responsibility: turn a file path into a list of (page_text, page_number) pairs.
All error cases raise PDFParseError so the worker can handle them uniformly.
"""

import logging
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


class PDFParseError(Exception):
    """Raised when a PDF cannot be parsed or yields no extractable text."""


def extract_pages_from_pdf(filepath: str) -> list[tuple[str, int]]:
    """Extract text from a PDF, returning one entry per page that has content.

    Returns:
        List of (page_text, page_number) tuples. page_number is 1-indexed.

    Raises:
        PDFParseError: if the file does not exist, is corrupt, is encrypted,
                       or contains no extractable text.
    """
    path = Path(filepath)
    if not path.exists():
        raise PDFParseError(f"File not found: {filepath}")

    try:
        with pdfplumber.open(filepath) as pdf:
            if not pdf.pages:
                raise PDFParseError(f"PDF has no pages: {filepath}")

            pages: list[tuple[str, int]] = []
            for i, page in enumerate(pdf.pages):
                try:
                    text = page.extract_text()
                except Exception as page_exc:
                    logger.warning(
                        "Could not extract text from page %d of %s: %s", i + 1, filepath, page_exc
                    )
                    continue
                if text and text.strip():
                    pages.append((text.strip(), i + 1))  # page_number is 1-indexed

    except PDFParseError:
        raise
    except Exception as exc:
        raise PDFParseError(f"Failed to open or read PDF '{filepath}': {exc}") from exc

    if not pages:
        raise PDFParseError(f"PDF '{filepath}' contains no extractable text")

    total_chars = sum(len(t) for t, _ in pages)
    logger.debug("Extracted %d characters across %d pages from %s", total_chars, len(pages), filepath)
    return pages

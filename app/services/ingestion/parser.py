"""PDF text extraction using pdfplumber.

Single responsibility: turn a file path into a plain-text string.
All error cases raise PDFParseError so the worker can handle them uniformly.
"""

import logging
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


class PDFParseError(Exception):
    """Raised when a PDF cannot be parsed or yields no extractable text."""


def extract_text_from_pdf(filepath: str) -> str:
    """Extract plain text from a PDF file.

    Concatenates text from all pages, separated by double newlines so that
    the chunker can later split on paragraph boundaries.

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

            page_texts: list[str] = []
            for i, page in enumerate(pdf.pages):
                try:
                    text = page.extract_text()
                except Exception as page_exc:
                    logger.warning("Could not extract text from page %d of %s: %s", i, filepath, page_exc)
                    continue
                if text and text.strip():
                    page_texts.append(text.strip())

    except PDFParseError:
        raise
    except Exception as exc:
        # Catches pdfplumber errors for encrypted, corrupt, or truncated files.
        raise PDFParseError(f"Failed to open or read PDF '{filepath}': {exc}") from exc

    full_text = "\n\n".join(page_texts).strip()
    if not full_text:
        raise PDFParseError(f"PDF '{filepath}' contains no extractable text")

    logger.debug("Extracted %d characters from %s", len(full_text), filepath)
    return full_text

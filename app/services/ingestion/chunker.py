"""Text chunking using tiktoken for accurate token counting.

Strategy:
  1. Accept a list of (page_text, page_number) pairs from the parser.
  2. Split each page on paragraph boundaries (\\n\\n) to respect document structure,
     keeping each paragraph tagged with its source page number.
  3. Greedily accumulate whole paragraphs into a token buffer up to chunk_size.
  4. When adding the next paragraph would overflow the buffer, flush the current
     buffer as a chunk and carry the last `overlap` tokens into the next buffer
     (so consecutive chunks share context).
  5. Paragraphs that exceed chunk_size on their own are sub-split using the same
     token window logic.

Each chunk records the page_number of the first paragraph that contributed new
content to that chunk (i.e. not the carry-over overlap from the previous chunk).
"""

import logging
from dataclasses import dataclass

import tiktoken

logger = logging.getLogger(__name__)

_ENCODING_NAME = "cl100k_base"


@dataclass
class ChunkData:
    chunk_index: int
    chunk_text: str
    token_count: int
    page_number: int  # 1-indexed page where this chunk primarily originates


def chunk_pages(
    pages: list[tuple[str, int]],
    chunk_size: int = 512,
    overlap: int = 50,
) -> list[ChunkData]:
    """Split page-tagged text into token-bounded, paragraph-aware chunks.

    Args:
        pages:      List of (page_text, page_number) pairs from the parser.
        chunk_size: Maximum tokens per chunk (inclusive).
        overlap:    Tokens from the end of each chunk carried into the next
                    chunk for context continuity.

    Returns:
        Ordered list of ChunkData, one entry per chunk.
    """
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be less than chunk_size ({chunk_size})")

    enc = tiktoken.get_encoding(_ENCODING_NAME)

    # Build a flat paragraph list preserving page provenance.
    tagged: list[tuple[list[int], int]] = []  # (tokens, page_number)
    for page_text, page_num in pages:
        for para in page_text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            toks = enc.encode(para)
            if toks:
                tagged.append((toks, page_num))

    if not tagged:
        return []

    result: list[ChunkData] = []
    buffer: list[int] = []
    chunk_page: int = tagged[0][1]
    idx = 0

    def flush(next_page: int) -> None:
        """Emit the current buffer as a chunk, carry overlap, update chunk_page."""
        nonlocal buffer, idx, chunk_page
        decoded = enc.decode(buffer).strip()
        if decoded:
            result.append(
                ChunkData(
                    chunk_index=idx,
                    chunk_text=decoded,
                    token_count=len(buffer),
                    page_number=chunk_page,
                )
            )
            idx += 1
        buffer = buffer[-overlap:] if overlap > 0 else []
        # The new chunk's page is set to the page of the next paragraph being added.
        chunk_page = next_page

    def push(tokens: list[int], page_num: int) -> None:
        """Append tokens to the buffer, flushing at every chunk_size boundary."""
        nonlocal buffer
        pos = 0
        while pos < len(tokens):
            space = chunk_size - len(buffer)
            if space <= 0:
                flush(page_num)
                space = chunk_size - len(buffer)
            take = tokens[pos : pos + space]
            buffer.extend(take)
            pos += space
            if len(buffer) >= chunk_size:
                flush(page_num)

    for toks, page_num in tagged:
        if len(buffer) + len(toks) <= chunk_size:
            buffer.extend(toks)
        else:
            if len(buffer) > overlap:
                flush(page_num)
            push(toks, page_num)

    # Emit any tokens still in the buffer.
    if buffer:
        decoded = enc.decode(buffer).strip()
        if decoded:
            result.append(
                ChunkData(
                    chunk_index=idx,
                    chunk_text=decoded,
                    token_count=len(buffer),
                    page_number=chunk_page,
                )
            )

    logger.debug(
        "Produced %d chunks from %d pages (%d paragraphs)",
        len(result),
        len(pages),
        len(tagged),
    )
    return result

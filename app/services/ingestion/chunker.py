"""Text chunking using tiktoken for accurate token counting.

Strategy:
  1. Split the input on paragraph boundaries (\\n\\n) to respect document structure.
  2. Greedily accumulate whole paragraphs into a token buffer up to chunk_size.
  3. When adding the next paragraph would overflow the buffer, flush the current
     buffer as a chunk and carry the last `overlap` tokens into the next buffer
     (so consecutive chunks share context).
  4. Paragraphs that exceed chunk_size on their own are sub-split using the same
     token window logic.

The overlap tokens in consecutive chunks give the LLM enough context to answer
questions that span a chunk boundary.
"""

import logging
from dataclasses import dataclass

import tiktoken

logger = logging.getLogger(__name__)

# cl100k_base is the tokenizer used by text-embedding-3-small and GPT-4.
_ENCODING_NAME = "cl100k_base"


@dataclass
class ChunkData:
    chunk_index: int
    chunk_text: str
    token_count: int


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 50,
) -> list[ChunkData]:
    """Split *text* into token-bounded, paragraph-aware chunks.

    Args:
        text:       The full document text.
        chunk_size: Maximum tokens per chunk (inclusive).
        overlap:    Number of tokens from the end of each chunk carried into
                    the start of the next chunk for context continuity.

    Returns:
        Ordered list of ChunkData, one entry per chunk.
    """
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be less than chunk_size ({chunk_size})")

    enc = tiktoken.get_encoding(_ENCODING_NAME)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    result: list[ChunkData] = []
    buffer: list[int] = []  # current token accumulation
    idx = 0

    def flush() -> None:
        """Emit the current buffer as a chunk and retain the overlap tail."""
        nonlocal buffer, idx
        decoded = enc.decode(buffer).strip()
        if decoded:
            result.append(ChunkData(chunk_index=idx, chunk_text=decoded, token_count=len(buffer)))
            idx += 1
        # Carry the last `overlap` tokens into the next chunk for continuity.
        buffer = buffer[-overlap:] if overlap > 0 else []

    def push(tokens: list[int]) -> None:
        """Append *tokens* to the buffer, flushing at every chunk_size boundary."""
        nonlocal buffer
        pos = 0
        while pos < len(tokens):
            space = chunk_size - len(buffer)
            if space <= 0:
                flush()
                space = chunk_size - len(buffer)
            take = tokens[pos : pos + space]
            buffer.extend(take)
            pos += space
            if len(buffer) >= chunk_size:
                flush()

    for para in paragraphs:
        toks = enc.encode(para)
        if not toks:
            continue

        if len(buffer) + len(toks) <= chunk_size:
            # Paragraph fits in the remaining buffer space — keep it whole.
            buffer.extend(toks)
        else:
            # Paragraph would overflow.  Flush first (if there's real content
            # beyond just the carry-over overlap), then push the paragraph.
            if len(buffer) > overlap:
                flush()
            # push() handles both normal-sized and oversized paragraphs.
            push(toks)

    # Emit any tokens still in the buffer.
    if buffer:
        decoded = enc.decode(buffer).strip()
        if decoded:
            result.append(ChunkData(chunk_index=idx, chunk_text=decoded, token_count=len(buffer)))

    logger.debug("Produced %d chunks from %d paragraphs", len(result), len(paragraphs))
    return result

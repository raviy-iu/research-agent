"""
kg/embedder.py – OpenAI embedding wrapper and text chunker.

Embedding model : text-embedding-3-small  (1536-dim, OpenAI API)
Chunking        : sliding window over words (default 400 words, 50-word overlap)

Requires OPENAI_API_KEY in .env (or environment).

Public API (unchanged from previous SentenceTransformer version):
  chunk_text(text, words, overlap)  -> list[str]
  embed_texts(texts, batch_size)    -> list[list[float]]
  embed_query(query)                -> list[float]
  embedding_dim()                   -> int   (1536)
"""
from __future__ import annotations

import logging

from openai import OpenAI

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding dimension constant
# ---------------------------------------------------------------------------

_EMBEDDING_DIM = 1536   # text-embedding-3-small default output dimension


def embedding_dim() -> int:
    """Return the output vector dimension (1536 for text-embedding-3-small)."""
    return _EMBEDDING_DIM


# ---------------------------------------------------------------------------
# OpenAI client (created per call - stateless, thread-safe)
# ---------------------------------------------------------------------------

def _get_client() -> OpenAI:
    """Return an OpenAI client using the API key from settings."""
    if not settings.openai_api_key:
        raise ValueError(
            "OPENAI_API_KEY is not set. "
            "Add it to your .env file:  OPENAI_API_KEY=sk-..."
        )
    return OpenAI(api_key=settings.openai_api_key)


# ---------------------------------------------------------------------------
# Text chunking  (no model dependency - unchanged from previous version)
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    words: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """
    Split text into overlapping word-based chunks.

    Parameters
    ----------
    text    : Input text.
    words   : Words per chunk (default: settings.kg_chunk_words = 400).
    overlap : Word overlap between consecutive chunks
              (default: settings.kg_chunk_overlap = 50).

    Returns
    -------
    list[str] - At least one chunk (may be shorter than `words` for short texts).
    """
    words   = words   or settings.kg_chunk_words
    overlap = overlap or settings.kg_chunk_overlap

    if not text or not text.strip():
        return []

    tokens = text.strip().split()
    if not tokens:
        return []

    if len(tokens) <= words:
        return [" ".join(tokens)]

    chunks: list[str] = []
    step = max(1, words - overlap)
    for start in range(0, len(tokens), step):
        chunk_tokens = tokens[start : start + words]
        chunks.append(" ".join(chunk_tokens))
        if start + words >= len(tokens):
            break

    return chunks


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str], batch_size: int = 100) -> list[list[float]]:
    """
    Encode a list of strings into 1536-dim float vectors via OpenAI API.

    Parameters
    ----------
    texts      : Strings to embed (titles, abstracts, chunk text, queries).
    batch_size : How many strings to send per API request (max 2048 for OpenAI).

    Returns
    -------
    list[list[float]] - One 1536-dim vector per input string.

    Notes
    -----
    - Newlines are replaced with spaces (OpenAI recommendation).
    - text-embedding-3-small vectors are unit-normalised by the API,
      so cosine similarity == dot product.
    """
    if not texts:
        return []

    client  = _get_client()
    results: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = [t.replace("\n", " ").strip() or " " for t in texts[i : i + batch_size]]
        logger.debug(
            "Embedding batch %d-%d of %d via %s",
            i, i + len(batch), len(texts), settings.embedding_model,
        )
        response = client.embeddings.create(
            input=batch,
            model=settings.embedding_model,
        )
        # response.data is sorted by index, matching input order
        results.extend([item.embedding for item in response.data])

    return results


def embed_query(query: str) -> list[float]:
    """Embed a single query string. Returns a 1536-dim float list."""
    return embed_texts([query])[0]

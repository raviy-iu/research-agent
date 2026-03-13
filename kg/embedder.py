"""
kg/embedder.py – SentenceTransformer wrapper and text chunker.

Embedding model: all-MiniLM-L6-v2  (384 dims, local, free, fast)
Chunking:        sliding window over words (default 400 words, 50-word overlap)

The model is loaded lazily on first use and cached for the process lifetime.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model singleton
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_model(model_name: str) -> SentenceTransformer:
    logger.info("Loading embedding model: %s (first call only)", model_name)
    return SentenceTransformer(model_name)


def get_model() -> SentenceTransformer:
    """Return the cached SentenceTransformer model."""
    return _get_model(settings.embedding_model)


def embedding_dim() -> int:
    """Return the output vector dimension (384 for all-MiniLM-L6-v2)."""
    return get_model().get_sentence_embedding_dimension()


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------

def _tokenize_words(text: str) -> list[str]:
    """Split text into whitespace-separated tokens (words)."""
    return text.split()


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
    list[str] – At least one chunk (may be shorter than `words` for short texts).
    """
    words = words or settings.kg_chunk_words
    overlap = overlap or settings.kg_chunk_overlap

    if not text or not text.strip():
        return []

    tokens = _tokenize_words(text.strip())
    if not tokens:
        return []

    if len(tokens) <= words:
        return [" ".join(tokens)]

    chunks: list[str] = []
    step = max(1, words - overlap)
    for start in range(0, len(tokens), step):
        chunk_tokens = tokens[start: start + words]
        chunks.append(" ".join(chunk_tokens))
        if start + words >= len(tokens):
            break

    return chunks


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """
    Encode a list of strings into 384-dim float vectors.

    Parameters
    ----------
    texts      : Strings to embed (titles, abstracts, chunk text, queries).
    batch_size : How many strings to encode per GPU/CPU batch.

    Returns
    -------
    list[list[float]] – One vector per input string.
    """
    if not texts:
        return []

    model = get_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        show_progress_bar=len(texts) > 20,
        normalize_embeddings=True,   # cosine similarity via dot product after normalization
    )
    return [emb.tolist() for emb in embeddings]


def embed_query(query: str) -> list[float]:
    """Embed a single query string. Returns a 384-dim float list."""
    return embed_texts([query])[0]

"""
kg/qdrant_manager.py – Qdrant collection management, chunk upsert, filtered search.

Each point in the collection represents one text chunk from an article.
Payload fields: article_id, title, source, doi, url, year, chunk_index, text_preview

Filtered search restricts cosine similarity to chunk IDs belonging to
Neo4j-selected articles, avoiding a full-corpus scan.

Start Qdrant: docker compose up -d qdrant
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    PointStruct,
    VectorParams,
)

from config import settings
from kg.embedder import embedding_dim

logger = logging.getLogger(__name__)

_TEXT_PREVIEW_LEN = 300   # chars stored in Qdrant payload as text_preview


def _chunk_point_id(chunk_id: str) -> int:
    """
    Deterministic integer Qdrant point ID derived from the chunk's string ID.
    Uses the first 8 bytes of the MD5 hash (safe for Qdrant's uint64 range).
    """
    return int(hashlib.md5(chunk_id.encode()).hexdigest()[:16], 16) % (2**63)


class QdrantManager:
    """
    Thin wrapper around QdrantClient for the manufacturing-research collection.

    Usage:
        qm = QdrantManager()
        qm.ensure_collection()
        qm.upsert_chunks(chunks, vectors)
        results = qm.search(query_vector, article_ids=["doi:...", "url:..."])
    """

    def __init__(self) -> None:
        self._client = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            timeout=30,
        )
        self._collection = settings.qdrant_collection

    # ── Collection lifecycle ─────────────────────────────────────────────────

    def ensure_collection(self) -> None:
        """
        Create the collection if it does not yet exist.
        If it already exists with the correct vector size, do nothing.
        """
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection in existing:
            logger.info("Qdrant collection '%s' already exists", self._collection)
            return

        dim = embedding_dim()
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        # Payload index on article_id for fast filtering
        self._client.create_payload_index(
            collection_name=self._collection,
            field_name="article_id",
            field_schema="keyword",
        )
        logger.info(
            "Created Qdrant collection '%s' (dim=%d, cosine)", self._collection, dim
        )

    def delete_collection(self) -> None:
        """Delete the entire collection (for reset / re-index)."""
        self._client.delete_collection(self._collection)
        logger.info("Deleted Qdrant collection '%s'", self._collection)

    # ── Upsert ───────────────────────────────────────────────────────────────

    def upsert_chunks(
        self,
        chunks: list[dict[str, Any]],
        vectors: list[list[float]],
        batch_size: int = 100,
    ) -> None:
        """
        Upsert chunk embeddings into Qdrant.

        Parameters
        ----------
        chunks  : List of dicts with keys:
                    id (str), article_id, title, source, doi, url,
                    year, chunk_index, text
        vectors : Corresponding embedding vectors (same order as chunks).
        """
        if not chunks:
            return

        points = [
            PointStruct(
                id=_chunk_point_id(c["id"]),
                vector=vec,
                payload={
                    "chunk_id":    c["id"],
                    "article_id":  c["article_id"],
                    "title":       c.get("title", ""),
                    "source":      c.get("source", ""),
                    "doi":         c.get("doi", ""),
                    "url":         c.get("url", ""),
                    "year":        c.get("year") or 0,
                    "chunk_index": c.get("chunk_index", 0),
                    "text_preview": c["text"][:_TEXT_PREVIEW_LEN],
                },
            )
            for c, vec in zip(chunks, vectors)
        ]

        # Upload in batches to avoid oversized HTTP requests
        for i in range(0, len(points), batch_size):
            self._client.upsert(
                collection_name=self._collection,
                points=points[i: i + batch_size],
            )
        logger.info("Upserted %d chunks to Qdrant", len(points))

    # ── Search ───────────────────────────────────────────────────────────────

    def search(
        self,
        query_vector: list[float],
        article_ids: list[str],
        top_k: int = 10,
        score_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Cosine similarity search restricted to chunks belonging to `article_ids`.

        Parameters
        ----------
        query_vector   : Embedded user query (384-dim float list).
        article_ids    : List of article_id strings from Neo4j results.
                         Empty list means search the entire collection.
        top_k          : Maximum results to return.
        score_threshold: Minimum cosine similarity (0.0 = return all).

        Returns
        -------
        List of dicts with keys: score, chunk_id, article_id, title, source,
        doi, url, year, chunk_index, text_preview
        """
        query_filter: Filter | None = None
        if article_ids:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="article_id",
                        match=MatchAny(any=article_ids),
                    )
                ]
            )

        response = self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            score_threshold=score_threshold if score_threshold > 0 else None,
            with_payload=True,
        )

        return [
            {
                "score": hit.score,
                **hit.payload,
            }
            for hit in response.points
        ]

    def search_all(
        self,
        query_vector: list[float],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Full-corpus vector search (no article_id filter)."""
        return self.search(query_vector, article_ids=[], top_k=top_k)

    # ── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return collection info (vector count, etc.)."""
        try:
            info = self._client.get_collection(self._collection)
            # In qdrant-client >= 1.13, vectors config may be a VectorParams
            # object (unnamed) or a dict (named vectors) - handle both.
            vectors_config = info.config.params.vectors
            if hasattr(vectors_config, "size"):
                vector_size = vectors_config.size
                distance    = str(vectors_config.distance)
            else:
                first = next(iter(vectors_config.values()))
                vector_size = first.size
                distance    = str(first.distance)
            return {
                "collection":   self._collection,
                "total_chunks": info.points_count,
                "vector_size":  vector_size,
                "distance":     distance,
                "status":       str(info.status),
            }
        except Exception as exc:
            return {"error": str(exc)}

"""
kg/graph_search.py – Two-stage search: Neo4j graph filter -> Qdrant vector similarity.

Pipeline
--------
1. Rule-based term extraction  (regex vs TOPIC_TERMS / INDUSTRY_TERMS from config.py)
2. Neo4j graph query           (weighted topic + industry match, scored Cypher)
   fallback: full-text index   (when no terms match)
3. Qdrant filtered search      (cosine similarity restricted to Neo4j article IDs)
4. Result merging              (Qdrant score + Neo4j article metadata)

Returns [] if Neo4j has no matching articles (caller handles auto-expand).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from config import TOPIC_TERMS, INDUSTRY_TERMS
from kg.embedder import embed_query
from kg.neo4j_manager import Neo4jManager
from kg.qdrant_manager import QdrantManager

logger = logging.getLogger(__name__)

# Pre-compiled patterns (same approach as graph_builder.py)
_TOPIC_PATTERNS    = [(t, re.compile(r"\b" + re.escape(t) + r"\b", re.I)) for t in TOPIC_TERMS]
_INDUSTRY_PATTERNS = [(t, re.compile(r"\b" + re.escape(t) + r"\b", re.I)) for t in INDUSTRY_TERMS]


def _extract_topics(text: str) -> list[str]:
    return [t for t, pat in _TOPIC_PATTERNS if pat.search(text)]


def _extract_industries(text: str) -> list[str]:
    return [t for t, pat in _INDUSTRY_PATTERNS if pat.search(text)]


class GraphSearcher:
    """
    Two-stage search: Neo4j graph traversal + Qdrant vector similarity.

    Usage:
        async with Neo4jManager() as neo4j:
            qdrant = QdrantManager()
            searcher = GraphSearcher(neo4j, qdrant)
            results = await searcher.search("FMEA cement kiln")
    """

    def __init__(self, neo4j: Neo4jManager, qdrant: QdrantManager) -> None:
        self.neo4j  = neo4j
        self.qdrant = qdrant

    async def search(
        self,
        query: str,
        top_k: int = 10,
        neo4j_limit: int = 20,
        score_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Run the two-stage search pipeline.

        Parameters
        ----------
        query           : Free-text user query.
        top_k           : Number of results to return (Qdrant top-k).
        neo4j_limit     : Max articles from Neo4j graph stage (default 20).
        score_threshold : Minimum Qdrant cosine similarity (0 = no filter).

        Returns
        -------
        list[dict] – Ranked results. Empty list if nothing found in Neo4j.
        Each dict: {score, chunk_id, article_id, title, source, doi, url,
                    year, chunk_index, text_preview}
        """
        # ── Stage 1: extract terms ─────────────────────────────────────────
        topics     = _extract_topics(query)
        industries = _extract_industries(query)
        logger.info(
            "Query terms extracted - topics: %s | industries: %s",
            topics, industries,
        )

        # ── Stage 2: Neo4j graph search ────────────────────────────────────
        neo4j_results = await self.neo4j.search_by_topics_industries(
            topics, industries, limit=neo4j_limit
        )

        # Fallback: full-text index when no term matches
        if not neo4j_results:
            logger.info("No graph results; trying full-text index fallback")
            neo4j_results = await self.neo4j.fulltext_search(query, limit=neo4j_limit)

        if not neo4j_results:
            logger.info("Neo4j returned no results for: %s", query)
            return []

        article_ids = [r["article_id"] for r in neo4j_results]
        logger.info("Neo4j returned %d candidate articles", len(article_ids))

        # ── Stage 3: Qdrant filtered vector search ─────────────────────────
        query_vec = embed_query(query)
        qdrant_hits = self.qdrant.search(
            query_vector=query_vec,
            article_ids=article_ids,
            top_k=top_k,
            score_threshold=score_threshold,
        )

        if not qdrant_hits:
            # Qdrant returned nothing for these articles – fall back to
            # returning Neo4j metadata directly (articles may have no chunks yet)
            logger.info("Qdrant returned no hits; returning Neo4j metadata")
            return [
                {
                    "score":        r.get("score", 0.0),
                    "article_id":   r["article_id"],
                    "title":        r.get("title", ""),
                    "source":       r.get("source", ""),
                    "doi":          r.get("doi", ""),
                    "url":          r.get("url", ""),
                    "year":         r.get("year"),
                    "chunk_index":  0,
                    "text_preview": r.get("abstract", "")[:300],
                    "chunk_id":     "",
                }
                for r in neo4j_results[:top_k]
            ]

        # ── Stage 4: Enrich Qdrant hits with Neo4j article metadata ────────
        neo4j_by_id = {r["article_id"]: r for r in neo4j_results}
        enriched: list[dict] = []
        for hit in qdrant_hits:
            aid = hit.get("article_id", "")
            neo4j_meta = neo4j_by_id.get(aid, {})
            enriched.append({
                **hit,
                # Add Neo4j fields not stored in Qdrant payload
                "graph_score":    neo4j_meta.get("score", 0),
                "download_status": neo4j_meta.get("download_status", ""),
                "local_path":     neo4j_meta.get("local_path", ""),
            })

        return enriched

    async def search_all(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Full-corpus vector search (no Neo4j pre-filter).
        Use when you want raw semantic similarity without graph traversal.
        """
        query_vec = embed_query(query)
        return self.qdrant.search_all(query_vec, top_k=top_k)

    def extract_terms(self, query: str) -> dict[str, list[str]]:
        """Expose term extraction for debugging / logging."""
        return {
            "topics":     _extract_topics(query),
            "industries": _extract_industries(query),
        }

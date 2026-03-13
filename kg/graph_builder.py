"""
kg/graph_builder.py – Corpus -> Neo4j + Qdrant ingestion pipeline.

Two entry points:
  GraphBuilder.build(kb_dir)         – ingest everything in knowledge_base/index.json
  GraphBuilder.ingest_articles(list) – ingest a fresh list of article dicts
                                       (called by KnowledgeAgent auto-expand fallback)

Entity extraction is rule-based: regex match title+abstract against
config.TOPIC_TERMS and config.INDUSTRY_TERMS (no LLM needed).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from config import settings, TOPIC_TERMS, INDUSTRY_TERMS
from kg.embedder import chunk_text, embed_texts
from kg.neo4j_manager import Neo4jManager
from kg.qdrant_manager import QdrantManager
from kg.text_extractor import extract_text

logger = logging.getLogger(__name__)
console = Console()

# Pre-compile one regex pattern per term (case-insensitive, word boundary aware)
_TOPIC_PATTERNS    = [(t, re.compile(r"\b" + re.escape(t) + r"\b", re.I)) for t in TOPIC_TERMS]
_INDUSTRY_PATTERNS = [(t, re.compile(r"\b" + re.escape(t) + r"\b", re.I)) for t in INDUSTRY_TERMS]


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_topics(text: str) -> list[str]:
    return [t for t, pat in _TOPIC_PATTERNS if pat.search(text)]


def _extract_industries(text: str) -> list[str]:
    return [t for t, pat in _INDUSTRY_PATTERNS if pat.search(text)]


def _article_id(entry: dict) -> str:
    """Derive a stable article ID (mirrors downloader._dedup_key logic)."""
    doi = (entry.get("doi") or "").strip()
    url = (entry.get("url") or "").strip()
    return f"doi:{doi.lower()}" if doi else f"url:{url.lower()}"


# ---------------------------------------------------------------------------
# GraphBuilder
# ---------------------------------------------------------------------------

class GraphBuilder:
    """
    Reads the local corpus and populates Neo4j + Qdrant.

    Usage:
        async with Neo4jManager() as neo4j:
            qdrant = QdrantManager()
            qdrant.ensure_collection()
            builder = GraphBuilder(neo4j, qdrant)
            await builder.build()
    """

    def __init__(self, neo4j: Neo4jManager, qdrant: QdrantManager) -> None:
        self.neo4j  = neo4j
        self.qdrant = qdrant

    # ── Public entry points ──────────────────────────────────────────────────

    async def build(
        self,
        kb_dir: Path | None = None,
        skip_existing: bool = True,
    ) -> dict[str, int]:
        """
        Ingest all articles from knowledge_base/index.json.

        Parameters
        ----------
        kb_dir         : knowledge_base root (default: settings.kb_dir)
        skip_existing  : Skip articles already present in Neo4j (incremental).

        Returns
        -------
        dict with counts: {total, ingested, skipped, failed}
        """
        kb_dir = Path(kb_dir) if kb_dir else settings.kb_dir
        index_file = kb_dir / "index.json"

        if not index_file.exists():
            console.print(
                f"[yellow]knowledge_base/index.json not found at {kb_dir}. "
                "Run 'uv run main.py \"your query\" --download' first.[/yellow]"
            )
            return {"total": 0, "ingested": 0, "skipped": 0, "failed": 0}

        index: dict[str, dict] = json.loads(index_file.read_text(encoding="utf-8"))
        articles = list(index.values())
        console.print(f"[bold]Loaded {len(articles)} articles from index.json[/bold]")

        return await self._ingest_list(articles, skip_existing=skip_existing, kb_dir=kb_dir)

    async def ingest_articles(
        self,
        articles: list[dict],
        kb_dir: Path | None = None,
    ) -> dict[str, int]:
        """
        Ingest a list of article dicts directly (e.g. freshly searched results).
        Always skips articles already in Neo4j.
        """
        kb_dir = Path(kb_dir) if kb_dir else settings.kb_dir
        return await self._ingest_list(articles, skip_existing=True, kb_dir=kb_dir)

    # ── Core pipeline ────────────────────────────────────────────────────────

    async def _ingest_list(
        self,
        articles: list[dict],
        skip_existing: bool,
        kb_dir: Path,
    ) -> dict[str, int]:

        counts = {"total": len(articles), "ingested": 0, "skipped": 0, "failed": 0}

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Ingesting articles...", total=len(articles))

            for entry in articles:
                article_id = _article_id(entry)
                progress.advance(task)

                try:
                    if skip_existing and await self.neo4j.article_exists(article_id):
                        counts["skipped"] += 1
                        continue

                    await self._ingest_one(entry, article_id, kb_dir)
                    counts["ingested"] += 1

                except Exception as exc:
                    logger.error("Failed to ingest %s: %s", article_id, exc)
                    counts["failed"] += 1

        console.print(
            f"[green]Ingestion complete:[/green] "
            f"ingested={counts['ingested']}  "
            f"skipped={counts['skipped']}  "
            f"failed={counts['failed']}"
        )
        return counts

    async def _ingest_one(
        self,
        entry: dict,
        article_id: str,
        kb_dir: Path,
    ) -> None:
        """Full ingestion pipeline for a single article."""

        title   = (entry.get("title")   or "").strip()
        doi     = (entry.get("doi")     or "").strip()
        url     = (entry.get("url")     or "").strip()
        source  = (entry.get("source")  or "Unknown")
        year    = entry.get("year")
        abstract = (entry.get("abstract") or "").strip()
        authors  = entry.get("authors") or []
        dl_status = entry.get("download_status") or "metadata_only"
        local_path = entry.get("local_path") or ""

        has_pdf      = dl_status == "pdf"
        has_fulltext = dl_status == "fulltext"

        # ── 1. Upsert Article node ─────────────────────────────────────────
        await self.neo4j.upsert_article({
            "id":              article_id,
            "title":           title,
            "doi":             doi,
            "url":             url,
            "source":          source,
            "year":            year,
            "abstract":        abstract,
            "download_status": dl_status,
            "has_pdf":         has_pdf,
            "has_fulltext":    has_fulltext,
            "local_path":      local_path,
        })

        # ── 2. Link Authors, Publisher ─────────────────────────────────────
        await self.neo4j.link_authors(article_id, authors)
        await self.neo4j.link_publisher(article_id, source)

        # ── 3. Extract & link Topics / Industries ─────────────────────────
        search_text = f"{title} {abstract}"
        topics     = _extract_topics(search_text)
        industries = _extract_industries(search_text)

        await self.neo4j.link_topics(article_id, topics)
        await self.neo4j.link_industries(article_id, industries)

        # ── 4. Extract text, chunk, embed, upsert to Qdrant ───────────────
        full_text = extract_text(local_path, dl_status, title, abstract, kb_dir)
        if not full_text.strip():
            full_text = title  # absolute fallback

        chunks_text = chunk_text(full_text)
        if not chunks_text:
            return

        vectors = embed_texts(chunks_text)

        chunk_dicts = []
        for idx, (ctext, vec) in enumerate(zip(chunks_text, vectors)):
            chunk_id = f"{article_id}__chunk_{idx}"
            chunk_dicts.append({
                "id":          chunk_id,
                "article_id":  article_id,
                "title":       title,
                "source":      source,
                "doi":         doi,
                "url":         url,
                "year":        year,
                "chunk_index": idx,
                "text":        ctext,
            })
            # Register Chunk node in Neo4j (metadata; vector stored in Qdrant)
            await self.neo4j.upsert_chunk({
                "id":          chunk_id,
                "text":        ctext[:500],   # short preview in graph
                "chunk_index": idx,
                "article_id":  article_id,
            })

        self.qdrant.upsert_chunks(chunk_dicts, vectors)
        logger.debug(
            "Ingested %s: %d chunks, topics=%s, industries=%s",
            article_id, len(chunk_dicts), topics, industries,
        )

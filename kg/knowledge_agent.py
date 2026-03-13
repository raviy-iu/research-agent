"""
kg/knowledge_agent.py – Full orchestration: search -> auto-download -> ingest -> retry.

KnowledgeAgent.ask(query) is the single entry point for end-users.

Flow
----
1. GraphSearcher.search(query)
     -> results found? -> return enriched results
     -> no results?
          a. Run research agent (agent.run()) to find new papers
          b. Download open-access PDFs + web articles (downloader.download_corpus())
          c. Ingest new articles into Neo4j + Qdrant (GraphBuilder.ingest_articles())
          d. Retry GraphSearcher.search(query) once
          e. Return results (may still be empty if very niche query)
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import settings

logger = logging.getLogger(__name__)
console = Console()


class KnowledgeAgent:
    """
    Top-level orchestrator: graph search + auto-expand on cache miss.

    Usage:
        async with Neo4jManager() as neo4j:
            qdrant = QdrantManager()
            qdrant.ensure_collection()
            builder  = GraphBuilder(neo4j, qdrant)
            searcher = GraphSearcher(neo4j, qdrant)
            agent    = KnowledgeAgent(neo4j, qdrant, builder, searcher)
            results  = await agent.ask("FMEA cement kiln")
    """

    def __init__(self, neo4j, qdrant, builder, searcher) -> None:
        self._neo4j    = neo4j
        self._qdrant   = qdrant
        self._builder  = builder
        self._searcher = searcher

    async def ask(
        self,
        query: str,
        top_k: int = 10,
        auto_download: bool = True,
        max_download_results: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Search the knowledge graph.  If nothing is found and auto_download=True,
        run the research agent to find + download new papers, ingest them, and retry.

        Parameters
        ----------
        query                : Free-text user query.
        top_k                : Number of results to return.
        auto_download        : Trigger research agent + downloader on cache miss.
        max_download_results : How many new papers to search for if auto-expanding.

        Returns
        -------
        list[dict] – Ranked search results (may be empty for very niche queries).
        """
        # ── Stage 1: graph search ──────────────────────────────────────────
        results = await self._searcher.search(query, top_k=top_k)
        if results:
            return results

        if not auto_download:
            logger.info("No results and auto_download=False; returning empty list")
            return []

        # ── Stage 2: auto-expand (research agent + downloader + ingest) ───
        console.print(
            "[yellow]No results found in the knowledge graph. "
            "Searching and downloading new papers...[/yellow]"
        )

        try:
            await self._auto_expand(query, max_results=max_download_results)
        except Exception as exc:
            logger.error("Auto-expand failed: %s", exc)
            console.print(f"[red]Auto-expand error:[/red] {exc}")
            return []

        # ── Stage 3: retry search after ingestion ──────────────────────────
        console.print("[cyan]Retrying search after ingestion...[/cyan]")
        results = await self._searcher.search(query, top_k=top_k)
        if not results:
            console.print(
                "[yellow]Still no results after downloading new papers. "
                "Try broadening your query.[/yellow]"
            )
        return results

    async def _auto_expand(self, query: str, max_results: int) -> None:
        """Run research agent, download, and ingest new articles."""
        import agent as research_agent
        from downloader import download_corpus

        # 1. Run the research agent to search for new papers
        console.print(f"[bold]Searching research databases for:[/bold] {query}")
        articles = await research_agent.run(
            query_text=query,
            max_results=max_results,
        )

        if not articles:
            console.print("[yellow]Research agent found no new articles.[/yellow]")
            return

        console.print(f"[green]Found {len(articles)} new articles[/green]")

        # 2. Download open-access PDFs + web articles
        console.print("[bold]Downloading available full text...[/bold]")
        counts = await download_corpus(
            articles=[a.to_dict() for a in articles],
            kb_dir=settings.kb_dir,
            email=settings.crossref_email,
        )
        console.print(
            f"Download complete: PDF={counts.get('pdf', 0)} | "
            f"Fulltext={counts.get('fulltext', 0)} | "
            f"Metadata-only={counts.get('metadata_only', 0)}"
        )

        # 3. Ingest into Neo4j + Qdrant
        console.print("[bold]Ingesting into knowledge graph...[/bold]")
        article_dicts = [a.to_dict() for a in articles]
        # Merge download_status from corpus index into article dicts
        _merge_download_status(article_dicts, settings.kb_dir)

        await self._builder.ingest_articles(article_dicts, kb_dir=settings.kb_dir)


def _merge_download_status(articles: list[dict], kb_dir: Path) -> None:
    """
    Enrich article dicts with download_status / local_path from the corpus index.
    This is needed because agent.run() returns Article objects without those fields.
    """
    import json

    index_file = Path(kb_dir) / "index.json"
    if not index_file.exists():
        return

    try:
        index = json.loads(index_file.read_text(encoding="utf-8"))
    except Exception:
        return

    for art in articles:
        doi = (art.get("doi") or "").strip().lower()
        url = (art.get("url") or "").strip().lower()
        key = f"doi:{doi}" if doi else f"url:{url}"
        entry = index.get(key, {})
        art.setdefault("download_status", entry.get("download_status", "metadata_only"))
        art.setdefault("local_path", entry.get("local_path", ""))

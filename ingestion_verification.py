"""
ingestion_verification.py - Diagnostic tool to verify Neo4j + Qdrant ingestion.

Runs a query through each pipeline stage EXPLICITLY and prints all intermediate
results - not a black box. Shows raw Neo4j node properties + relationships
followed by Qdrant chunk-level similarity search results.

Usage
-----
    # Run 3 built-in sample queries (recommended after ingestion)
    uv run ingestion_verification.py

    # Custom query
    uv run ingestion_verification.py "FMEA cement kiln ring formation"

    # Neo4j stage only (skip Qdrant)
    uv run ingestion_verification.py "predictive maintenance" --stage neo4j

    # Qdrant stage only
    uv run ingestion_verification.py "digital twin steel" --stage qdrant

    # Control result count and similarity threshold
    uv run ingestion_verification.py "energy optimization" --top 10 --neo4j-limit 20
    uv run ingestion_verification.py "anomaly detection" --score-threshold 0.4

Pipeline stages shown
---------------------
  [1] Term Extraction   - topics and industries matched from the query
  [2] Neo4j Search      - graph-weighted article nodes + linked topics/industries
  [3] Qdrant Search     - cosine similarity chunks with score, chunk_id, text
  [4] Summary           - counts and top score for the query
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from config import settings
from kg.embedder import embed_query
from kg.graph_search import _extract_topics, _extract_industries
from kg.neo4j_manager import Neo4jManager
from kg.qdrant_manager import QdrantManager

console = Console()

# ---------------------------------------------------------------------------
# Built-in sample queries used when the user does not supply one
# ---------------------------------------------------------------------------
SAMPLE_QUERIES: list[str] = [
    "FMEA cement kiln ring formation",
    "predictive maintenance aluminum smelter fault detection",
    "digital twin energy optimization steel blast furnace",
]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ingestion_verification",
        description=(
            "Verify Neo4j + Qdrant ingestion by running a query through each "
            "pipeline stage and printing all intermediate results."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        type=str,
        help=(
            "Query to test. If omitted, runs 3 built-in sample queries: "
            + " | ".join(f'\"{q}\"' for q in SAMPLE_QUERIES)
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        metavar="N",
        help="Max Qdrant results (chunks) to return (default: 5).",
    )
    parser.add_argument(
        "--neo4j-limit",
        type=int,
        default=10,
        metavar="N",
        help="Max Neo4j candidate articles (default: 10).",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.0,
        metavar="F",
        help="Minimum Qdrant cosine similarity score to include (default: 0.0 = all).",
    )
    parser.add_argument(
        "--stage",
        choices=["both", "neo4j", "qdrant"],
        default="both",
        help="Which pipeline stage to run (default: both).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return parser


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Neo4j helpers (direct Cypher - shows raw node + relationship data)
# ---------------------------------------------------------------------------

async def _get_article_relationships(
    neo4j: Neo4jManager,
    article_id: str,
) -> dict[str, list[str]]:
    """
    Query linked topics and industries for a single article node.
    Returns {"topics": [...], "industries": [...]}
    """
    cql = """
    MATCH (a:Article {id: $id})
    OPTIONAL MATCH (a)-[:COVERS_TOPIC]->(t:Topic)
    OPTIONAL MATCH (a)-[:RELEVANT_TO]->(i:Industry)
    RETURN
      collect(DISTINCT t.name) AS topics,
      collect(DISTINCT i.name) AS industries
    """
    async with neo4j._driver.session() as s:
        result = await s.run(cql, id=article_id)
        record = await result.single()
        if record:
            return {
                "topics":     list(record["topics"]),
                "industries": list(record["industries"]),
            }
        return {"topics": [], "industries": []}


async def _get_chunk_count(neo4j: Neo4jManager, article_id: str) -> int:
    """Return the number of Chunk nodes linked to this article."""
    cql = """
    MATCH (a:Article {id: $id})-[:HAS_CHUNK]->(c:Chunk)
    RETURN count(c) AS n
    """
    async with neo4j._driver.session() as s:
        result = await s.run(cql, id=article_id)
        record = await result.single()
        return record["n"] if record else 0


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_term_extraction(query: str, topics: list[str], industries: list[str]) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="cyan",  no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Query",      query)
    table.add_row(
        "Topics",
        ("  |  ".join(topics)) if topics else "[dim](none matched)[/dim]",
    )
    table.add_row(
        "Industries",
        ("  |  ".join(industries)) if industries else "[dim](none matched)[/dim]",
    )

    console.print(
        Panel(
            table,
            title="[bold magenta]Stage 1  |  Term Extraction[/bold magenta]",
            border_style="magenta",
        )
    )


def _print_neo4j_results(
    articles: list[dict],
    relationships: list[dict[str, list[str]]],
    chunk_counts: list[int],
    search_method: str,
) -> None:
    """Print one Rich panel per Neo4j article node with all properties."""

    method_label = (
        "[green]graph filter[/green]"
        if search_method == "graph"
        else "[yellow]fulltext fallback[/yellow]"
    )
    console.print()
    console.print(
        Rule(
            f"[bold green]Stage 2  |  Neo4j Graph Results "
            f"({len(articles)} article(s) via {method_label})[/bold green]"
        )
    )

    if not articles:
        console.print(
            "  [yellow]No articles found in Neo4j for this query.[/yellow]\n"
            "  Run [bold]uv run manual_ingestion.py[/bold] first, or broaden the query."
        )
        return

    for rank, (art, rels, n_chunks) in enumerate(
        zip(articles, relationships, chunk_counts), start=1
    ):
        score = art.get("score", 0)
        title = art.get("title") or "(no title)"

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Property",  style="cyan",  no_wrap=True, min_width=18)
        table.add_column("Value",     style="white")

        # -- Node properties --
        table.add_row("article_id",      str(art.get("article_id", "")))
        table.add_row("source",          str(art.get("source", "")))
        table.add_row("year",            str(art.get("year", "")))
        table.add_row("doi",             str(art.get("doi", "")) or "[dim]n/a[/dim]")
        table.add_row("url",             str(art.get("url", "")) or "[dim]n/a[/dim]")
        table.add_row("download_status", str(art.get("download_status", "")))
        table.add_row("has_pdf",         str(art.get("has_pdf", "")))
        table.add_row("has_fulltext",    str(art.get("has_fulltext", "")))
        table.add_row("local_path",      str(art.get("local_path", "")) or "[dim]n/a[/dim]")

        # -- Graph score --
        table.add_row(
            "graph_score",
            f"[bold yellow]{score}[/bold yellow]  "
            "(topics*3 + related_topics + industries*2)",
        )

        # -- Relationships --
        table.add_row(
            "linked_topics",
            ("  |  ".join(rels["topics"])) if rels["topics"] else "[dim](none)[/dim]",
        )
        table.add_row(
            "linked_industries",
            ("  |  ".join(rels["industries"])) if rels["industries"] else "[dim](none)[/dim]",
        )
        table.add_row(
            "chunk_nodes",
            f"[cyan]{n_chunks}[/cyan]  (HAS_CHUNK relationships in Neo4j)",
        )

        # -- Abstract preview --
        abstract = (art.get("abstract") or "").strip()
        if abstract:
            preview = abstract[:300] + ("..." if len(abstract) > 300 else "")
            table.add_row("abstract", f"[dim]{preview}[/dim]")

        # Truncate title for panel header
        short_title = title if len(title) <= 80 else title[:77] + "..."
        console.print(
            Panel(
                table,
                title=f"[bold]#{rank}[/bold]  {short_title}",
                border_style="green",
            )
        )


def _print_qdrant_results(hits: list[dict]) -> None:
    """Print one Rich panel per Qdrant chunk hit with all metadata + text."""

    console.print()
    console.print(
        Rule(
            f"[bold blue]Stage 3  |  Qdrant Similarity Search "
            f"({len(hits)} chunk(s) retrieved)[/bold blue]"
        )
    )

    if not hits:
        console.print(
            "  [yellow]No Qdrant chunks returned.[/yellow]\n"
            "  Articles may have been ingested as metadata-only (no full text to chunk).\n"
            "  Download full text first: [bold]uv run main.py \"query\" --download[/bold]\n"
            "  Then re-ingest:           [bold]uv run manual_ingestion.py --force[/bold]"
        )
        return

    for rank, hit in enumerate(hits, start=1):
        score         = hit.get("score", 0.0)
        chunk_id      = hit.get("chunk_id", "")
        article_id    = hit.get("article_id", "")
        title         = hit.get("title", "") or "(no title)"
        source        = hit.get("source", "")
        year          = hit.get("year", "")
        doi           = hit.get("doi", "") or "n/a"
        url           = hit.get("url", "") or "n/a"
        chunk_index   = hit.get("chunk_index", 0)
        text_preview  = hit.get("text_preview", "") or ""

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Field",  style="cyan",  no_wrap=True, min_width=18)
        table.add_column("Value",  style="white")

        # Score (highlighted)
        score_color = (
            "green"  if score >= 0.7 else
            "yellow" if score >= 0.4 else
            "red"
        )
        table.add_row(
            "similarity_score",
            f"[bold {score_color}]{score:.6f}[/bold {score_color}]",
        )

        table.add_row("chunk_id",     chunk_id     or "[dim]n/a[/dim]")
        table.add_row("chunk_index",  str(chunk_index))
        table.add_row("article_id",   article_id   or "[dim]n/a[/dim]")
        table.add_row("source",       source       or "[dim]n/a[/dim]")
        table.add_row("year",         str(year)    or "[dim]n/a[/dim]")
        table.add_row("doi",          doi)
        table.add_row("url",          url)

        # Full retrieved text (word-wrapped by Rich automatically)
        if text_preview:
            table.add_row("retrieved_text", f"[italic]{text_preview}[/italic]")
        else:
            table.add_row("retrieved_text", "[dim](empty)[/dim]")

        short_title = title if len(title) <= 70 else title[:67] + "..."
        console.print(
            Panel(
                table,
                title=(
                    f"[bold]Rank #{rank}[/bold]  |  "
                    f"score=[bold]{score:.4f}[/bold]  |  {short_title}"
                ),
                border_style="blue",
            )
        )


def _print_summary(
    query: str,
    topics: list[str],
    industries: list[str],
    neo4j_count: int,
    qdrant_count: int,
    qdrant_hits: list[dict],
    search_method: str,
) -> None:
    """Print a final summary table for this query."""
    table = Table(
        title="Verification Summary",
        show_header=False,
        box=None,
        padding=(0, 2),
    )
    table.add_column("Metric", style="cyan",  no_wrap=True)
    table.add_column("Value",  style="white")

    table.add_row("Query",                  query)
    table.add_row("Topics extracted",       str(len(topics)))
    table.add_row("Industries extracted",   str(len(industries)))
    table.add_row(
        "Neo4j articles found",
        f"{neo4j_count}  (via [green]{search_method}[/green])",
    )
    table.add_row("Qdrant chunks returned", str(qdrant_count))

    if qdrant_hits:
        scores = [h.get("score", 0.0) for h in qdrant_hits]
        table.add_row("Top similarity score",    f"{max(scores):.6f}")
        table.add_row("Bottom similarity score", f"{min(scores):.6f}")
        avg_score = sum(scores) / len(scores)
        table.add_row("Average similarity score", f"{avg_score:.6f}")

    console.print()
    console.print(Panel(table, border_style="dim"))


# ---------------------------------------------------------------------------
# Core verification runner (one query)
# ---------------------------------------------------------------------------

async def verify_query(
    query: str,
    neo4j: Neo4jManager,
    qdrant: QdrantManager,
    top: int,
    neo4j_limit: int,
    score_threshold: float,
    stage: str,
) -> None:
    """Run the full verification pipeline for a single query."""

    console.print()
    console.print(
        Panel.fit(
            f'[bold white]Query:[/bold white] [italic cyan]"{query}"[/italic cyan]',
            border_style="white",
        )
    )

    # ── Stage 1: Term extraction ───────────────────────────────────────────
    topics     = _extract_topics(query)
    industries = _extract_industries(query)
    _print_term_extraction(query, topics, industries)

    neo4j_articles:   list[dict[str, Any]] = []
    relationships:    list[dict[str, list[str]]] = []
    chunk_counts:     list[int] = []
    search_method:    str = "none"
    qdrant_hits:      list[dict[str, Any]] = []

    # ── Stage 2: Neo4j graph search ────────────────────────────────────────
    if stage in ("both", "neo4j"):
        # Primary: weighted graph traversal by topics + industries
        neo4j_articles = await neo4j.search_by_topics_industries(
            topics, industries, limit=neo4j_limit
        )
        search_method = "graph filter"

        # Fallback: full-text index when topic/industry extraction yields nothing
        if not neo4j_articles:
            neo4j_articles = await neo4j.fulltext_search(query, limit=neo4j_limit)
            search_method = "fulltext fallback"

        # Enrich each article with its linked topics, industries, and chunk count
        for art in neo4j_articles:
            aid  = art.get("article_id", "")
            rels = await _get_article_relationships(neo4j, aid)
            n    = await _get_chunk_count(neo4j, aid)
            relationships.append(rels)
            chunk_counts.append(n)

        _print_neo4j_results(neo4j_articles, relationships, chunk_counts, search_method)

    # ── Stage 3: Qdrant similarity search ─────────────────────────────────
    if stage in ("both", "qdrant"):
        article_ids = [a.get("article_id", "") for a in neo4j_articles]

        console.print()
        console.print(
            f"  [dim]Embedding query with [cyan]{settings.embedding_model}[/cyan]...[/dim]"
        )
        query_vec = embed_query(query)

        if article_ids:
            console.print(
                f"  [dim]Searching Qdrant (filtered to {len(article_ids)} article IDs "
                f"from Neo4j, top {top})...[/dim]"
            )
        else:
            console.print(
                "  [dim]Neo4j returned no articles; running full-corpus Qdrant search...[/dim]"
            )

        qdrant_hits = qdrant.search(
            query_vector=query_vec,
            article_ids=article_ids,       # empty list = full-corpus scan
            top_k=top,
            score_threshold=score_threshold,
        )
        _print_qdrant_results(qdrant_hits)

    # ── Stage 4: Summary ───────────────────────────────────────────────────
    _print_summary(
        query=query,
        topics=topics,
        industries=industries,
        neo4j_count=len(neo4j_articles),
        qdrant_count=len(qdrant_hits),
        qdrant_hits=qdrant_hits,
        search_method=search_method,
    )


# ---------------------------------------------------------------------------
# Main async runner
# ---------------------------------------------------------------------------

async def run(args: argparse.Namespace) -> int:
    console.print(
        Panel.fit(
            "[bold blue]Ingestion Verification[/bold blue]\n"
            "[dim]Neo4j graph nodes  ->  Qdrant vector similarity  (stage-by-stage)[/dim]",
            border_style="blue",
        )
    )

    # Determine queries to run
    queries = [args.query] if args.query else SAMPLE_QUERIES

    if not args.query:
        console.print(
            f"\n[dim]No query supplied - running [bold]{len(SAMPLE_QUERIES)}[/bold] "
            "built-in sample queries.[/dim]\n"
            "[dim]Supply a query to test a specific one:  "
            "uv run ingestion_verification.py \"your query\"[/dim]"
        )

    # Connect to Neo4j + Qdrant once, reuse for all queries
    async with Neo4jManager() as neo4j:
        qdrant = QdrantManager()

        # Quick connectivity check before running queries
        try:
            await neo4j.get_status()
        except Exception as exc:
            console.print(
                f"\n[red]Cannot connect to Neo4j:[/red] {exc}\n"
                f"  URI:  {settings.neo4j_uri}\n"
                f"  User: {settings.neo4j_user}\n"
                "  Ensure Neo4j is running and credentials are set in .env"
            )
            return 1

        try:
            qdrant.get_status()
        except Exception as exc:
            console.print(
                f"\n[red]Cannot connect to Qdrant:[/red] {exc}\n"
                f"  Host: {settings.qdrant_host}:{settings.qdrant_port}\n"
                "  Ensure Docker is running:  [bold]docker compose up -d qdrant[/bold]"
            )
            return 1

        # Run verification for each query
        for i, query in enumerate(queries, start=1):
            if len(queries) > 1:
                console.print()
                console.rule(
                    f"[bold white]Query {i}/{len(queries)}[/bold white]",
                    style="white",
                )

            try:
                await verify_query(
                    query=query,
                    neo4j=neo4j,
                    qdrant=qdrant,
                    top=args.top,
                    neo4j_limit=args.neo4j_limit,
                    score_threshold=args.score_threshold,
                    stage=args.stage,
                )
            except Exception as exc:
                console.print(f"\n[red]Error verifying query '{query}':[/red] {exc}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()

    # Final tips
    console.print()
    console.print(
        Panel(
            "[bold]Tips[/bold]\n\n"
            "  Low similarity scores or no results?\n"
            "    - Run [bold]uv run manual_ingestion.py[/bold] to ingest the corpus first\n"
            "    - Use [bold]--download[/bold] with main.py to add full text (not just metadata)\n"
            "    - Use [bold]--force[/bold] with manual_ingestion.py to re-embed after adding files\n\n"
            "  See stats:  [bold]uv run kg_main.py status[/bold]\n"
            "  Re-ingest:  [bold]uv run manual_ingestion.py --force[/bold]",
            border_style="dim",
        )
    )

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()
    _setup_logging(args.verbose)

    try:
        code = asyncio.run(run(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        code = 130
    except Exception as exc:
        console.print(f"\n[red]Unexpected error:[/red] {exc}")
        if "--verbose" in sys.argv or "-v" in sys.argv:
            import traceback
            traceback.print_exc()
        code = 1

    sys.exit(code)


if __name__ == "__main__":
    main()

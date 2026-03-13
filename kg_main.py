"""
kg_main.py – CLI entry point for the Neo4j + Qdrant knowledge-graph pipeline.

Subcommands
-----------
    build       Ingest knowledge_base/ corpus into Neo4j + Qdrant
    search      Two-stage search: Neo4j graph -> Qdrant vector similarity
    status      Show graph and vector-store statistics
    ingest      Ingest articles from a specific search-output JSON file

Usage examples
--------------
    # One-time: start Qdrant (Docker)
    docker compose up -d qdrant

    # Build graph from existing corpus
    uv run kg_main.py build

    # Search the knowledge graph
    uv run kg_main.py search "FMEA cement kiln ring formation"
    uv run kg_main.py search "predictive maintenance aluminum smelter" --top 5

    # Show graph stats
    uv run kg_main.py status

    # Ingest from a specific output JSON (without re-downloading)
    uv run kg_main.py ingest outputs/20260310_170704_fmea_cement_kiln.json

    # Rebuild from scratch (clears Qdrant, keeps Neo4j schema)
    uv run kg_main.py build --force

    # Search without auto-download fallback
    uv run kg_main.py search "ring formation" --no-auto-download

    # Debug logging
    uv run kg_main.py search "FMEA" -v
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import settings
from kg.graph_builder import GraphBuilder
from kg.graph_search import GraphSearcher
from kg.knowledge_agent import KnowledgeAgent
from kg.neo4j_manager import Neo4jManager
from kg.qdrant_manager import QdrantManager

console = Console()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kg",
        description="Manufacturing Research Agent – Knowledge Graph (Neo4j + Qdrant)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    sub = parser.add_subparsers(dest="command", required=True)

    # ── build ──────────────────────────────────────────────────────────────
    p_build = sub.add_parser(
        "build",
        help="Ingest knowledge_base/ corpus into Neo4j + Qdrant",
    )
    p_build.add_argument(
        "--kb-dir",
        type=Path,
        default=settings.kb_dir,
        metavar="DIR",
        help=f"knowledge_base root (default: {settings.kb_dir})",
    )
    p_build.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest all articles (ignore skip-existing). Clears Qdrant collection first.",
    )

    # ── search ─────────────────────────────────────────────────────────────
    p_search = sub.add_parser(
        "search",
        help="Search the knowledge graph (Neo4j graph + Qdrant vector)",
    )
    p_search.add_argument("query", type=str, help="Free-text research query")
    p_search.add_argument(
        "--top", type=int, default=10, metavar="N",
        help="Number of results to return (default: 10)",
    )
    p_search.add_argument(
        "--no-auto-download",
        action="store_true",
        help="Disable auto research-agent + downloader fallback on cache miss",
    )
    p_search.add_argument(
        "--show-terms",
        action="store_true",
        help="Show extracted topics and industries before searching",
    )

    # ── status ─────────────────────────────────────────────────────────────
    sub.add_parser("status", help="Show Neo4j + Qdrant statistics")

    # ── ingest ─────────────────────────────────────────────────────────────
    p_ingest = sub.add_parser(
        "ingest",
        help="Ingest articles from a research-agent output JSON file",
    )
    p_ingest.add_argument(
        "json_files",
        nargs="+",
        type=Path,
        metavar="JSON_FILE",
        help="One or more output JSON files (from outputs/)",
    )
    p_ingest.add_argument(
        "--kb-dir",
        type=Path,
        default=settings.kb_dir,
        metavar="DIR",
        help=f"knowledge_base root (default: {settings.kb_dir})",
    )

    return parser


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

async def cmd_build(args: argparse.Namespace) -> int:
    async with Neo4jManager() as neo4j:
        await neo4j.setup_schema()

        qdrant = QdrantManager()
        if args.force:
            console.print("[yellow]--force: deleting and recreating Qdrant collection...[/yellow]")
            try:
                qdrant.delete_collection()
            except Exception:
                pass
        qdrant.ensure_collection()

        builder = GraphBuilder(neo4j, qdrant)
        counts = await builder.build(
            kb_dir=args.kb_dir,
            skip_existing=(not args.force),
        )

    _print_build_summary(counts)
    return 0


async def cmd_search(args: argparse.Namespace) -> int:
    async with Neo4jManager() as neo4j:
        qdrant   = QdrantManager()
        qdrant.ensure_collection()
        builder  = GraphBuilder(neo4j, qdrant)
        searcher = GraphSearcher(neo4j, qdrant)
        ka       = KnowledgeAgent(neo4j, qdrant, builder, searcher)

        if args.show_terms:
            terms = searcher.extract_terms(args.query)
            console.print(f"[bold]Topics:[/bold]     {terms['topics']}")
            console.print(f"[bold]Industries:[/bold] {terms['industries']}")
            console.print()

        results = await ka.ask(
            query=args.query,
            top_k=args.top,
            auto_download=(not args.no_auto_download),
        )

    _print_search_results(args.query, results)
    return 0 if results else 1


async def cmd_status(_args: argparse.Namespace) -> int:
    async with Neo4jManager() as neo4j:
        neo4j_stats = await neo4j.get_status()

    qdrant = QdrantManager()
    qdrant_stats = qdrant.get_status()

    # Neo4j table
    neo4j_table = Table(title="Neo4j Graph", show_lines=False, box=None, padding=(0, 2))
    neo4j_table.add_column("Metric",  style="cyan", no_wrap=True)
    neo4j_table.add_column("Count",   justify="right", style="bold")

    labels = {
        "total_articles":  "Total Articles",
        "pdf_count":       "  PDF downloaded",
        "fulltext_count":  "  Full text scraped",
        "meta_count":      "  Metadata only",
        "total_chunks":    "Chunks",
        "total_topics":    "Topic nodes",
        "total_industries":"Industry nodes",
    }
    for key, label in labels.items():
        val = neo4j_stats.get(key)
        if val is not None:
            neo4j_table.add_row(label, str(val))

    # Qdrant table
    qdrant_table = Table(title="Qdrant Vector Store", show_lines=False, box=None, padding=(0, 2))
    qdrant_table.add_column("Metric",  style="cyan", no_wrap=True)
    qdrant_table.add_column("Value",   style="bold")

    for key, val in qdrant_stats.items():
        qdrant_table.add_row(key, str(val))

    console.print()
    console.print(neo4j_table)
    console.print()
    console.print(qdrant_table)
    console.print()
    return 0


async def cmd_ingest(args: argparse.Namespace) -> int:
    # Load articles from JSON files
    seen: set[str] = set()
    articles: list[dict] = []

    for path in args.json_files:
        if not path.exists():
            console.print(f"[red]File not found:[/red] {path}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            console.print(f"[red]Cannot read {path}:[/red] {exc}")
            continue

        for art in data.get("results", []):
            doi = (art.get("doi") or "").strip().lower()
            url = (art.get("url") or "").strip().lower()
            key = f"doi:{doi}" if doi else f"url:{url}"
            if key not in seen:
                seen.add(key)
                articles.append(art)

    if not articles:
        console.print("[yellow]No articles found in the specified files.[/yellow]")
        return 1

    console.print(f"[bold]Ingesting {len(articles)} articles...[/bold]")

    async with Neo4jManager() as neo4j:
        await neo4j.setup_schema()
        qdrant = QdrantManager()
        qdrant.ensure_collection()
        builder = GraphBuilder(neo4j, qdrant)
        counts = await builder.ingest_articles(articles, kb_dir=args.kb_dir)

    _print_build_summary(counts)
    return 0


# ---------------------------------------------------------------------------
# Rich output helpers
# ---------------------------------------------------------------------------

def _print_build_summary(counts: dict) -> None:
    table = Table(title="Ingestion Summary", show_lines=False, box=None, padding=(0, 2))
    table.add_column("Status", style="cyan", no_wrap=True)
    table.add_column("Count",  justify="right", style="bold")

    for key, label in [
        ("total",    "[bold]Total[/bold]"),
        ("ingested", "[green]Ingested[/green]"),
        ("skipped",  "[dim]Skipped (already in graph)[/dim]"),
        ("failed",   "[red]Failed[/red]"),
    ]:
        n = counts.get(key, 0)
        if n:
            table.add_row(label, str(n))

    console.print()
    console.print(table)


def _print_search_results(query: str, results: list[dict]) -> None:
    if not results:
        console.print(f"\n[yellow]No results found for:[/yellow] {query}")
        return

    console.print(
        f"\n[bold green]{len(results)} result(s)[/bold green] for: [italic]{query}[/italic]\n"
    )
    for i, r in enumerate(results, 1):
        score    = r.get("score", 0.0)
        title    = r.get("title", "(no title)")
        source   = r.get("source", "")
        year     = r.get("year") or ""
        url      = r.get("url", "")
        preview  = r.get("text_preview", "")[:200].replace("\n", " ")

        console.print(
            f"[bold cyan]{i}.[/bold cyan] "
            f"[bold]{title}[/bold] "
            f"[dim]({source}, {year})[/dim]  "
            f"[dim]score={score:.3f}[/dim]"
        )
        if url:
            console.print(f"   [link={url}]{url}[/link]")
        if preview:
            console.print(f"   [dim]{preview}...[/dim]")
        console.print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()
    _setup_logging(args.verbose)

    console.print(
        Panel.fit(
            "[bold blue]Manufacturing Knowledge Graph[/bold blue]\n"
            "[dim]Neo4j graph traversal + Qdrant vector similarity[/dim]",
            border_style="blue",
        )
    )

    dispatch = {
        "build":  cmd_build,
        "search": cmd_search,
        "status": cmd_status,
        "ingest": cmd_ingest,
    }
    handler = dispatch[args.command]

    try:
        code = asyncio.run(handler(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        code = 130
    except Exception as exc:
        console.print(f"\n[red]Error:[/red] {exc}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        code = 1

    sys.exit(code)


if __name__ == "__main__":
    main()

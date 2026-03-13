"""
manual_ingestion.py - Standalone ingestion script: knowledge_base/ -> Neo4j + Qdrant.

Reads knowledge_base/index.json and populates:
  Neo4j   - Article, Author, Publisher, Topic, Industry, Chunk nodes + relationships
  Qdrant  - Chunk embeddings (all-MiniLM-L6-v2, 384-dim, cosine similarity)

This script exposes every step explicitly with detailed logging and statistics.
It is equivalent to 'uv run kg_main.py build' but with richer pre/post diagnostics.

Usage
-----
    uv run manual_ingestion.py                    # incremental (skip already-ingested)
    uv run manual_ingestion.py --force            # wipe Qdrant collection, re-ingest all
    uv run manual_ingestion.py --kb-dir path/kb   # custom corpus location
    uv run manual_ingestion.py -v                 # verbose / debug logging

What it does
------------
  Step 1 - Print config summary and corpus preview (article count + status breakdown)
  Step 2 - Connect to Neo4j, bootstrap schema (constraints, indexes, seed nodes)
  Step 3 - Create/ensure Qdrant collection (or wipe + recreate if --force)
  Step 4 - Run GraphBuilder.build(): extract text, chunk, embed, upsert to both stores
  Step 5 - Print ingestion summary + post-ingestion statistics from Neo4j and Qdrant
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import settings
from kg.graph_builder import GraphBuilder
from kg.neo4j_manager import Neo4jManager
from kg.qdrant_manager import QdrantManager

console = Console()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manual_ingestion",
        description=(
            "Ingest the local knowledge_base/ corpus into Neo4j (graph) "
            "and Qdrant (vector store)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--kb-dir",
        type=Path,
        default=settings.kb_dir,
        metavar="DIR",
        help=f"knowledge_base root directory (default: {settings.kb_dir})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Delete and recreate the Qdrant collection before ingesting. "
            "All articles will be re-ingested even if already in Neo4j."
        ),
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
# Display helpers
# ---------------------------------------------------------------------------

def _print_config(kb_dir: Path, force: bool) -> None:
    """Print a startup configuration panel."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key",   style="cyan",  no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Neo4j URI",         settings.neo4j_uri)
    table.add_row("Neo4j User",        settings.neo4j_user)
    table.add_row("Qdrant",            f"{settings.qdrant_host}:{settings.qdrant_port}")
    table.add_row("Collection",        settings.qdrant_collection)
    table.add_row("Embedding Model",   settings.embedding_model)
    table.add_row("Chunk Size",        f"{settings.kg_chunk_words} words  (overlap: {settings.kg_chunk_overlap})")
    table.add_row("Knowledge Base",    str(kb_dir.resolve()))
    table.add_row(
        "Mode",
        "[red bold]FORCE  (re-ingest all, Qdrant wiped)[/red bold]"
        if force
        else "[green]Incremental  (skip already-ingested articles)[/green]",
    )

    console.print(Panel(table, title="[bold blue]Ingestion Configuration[/bold blue]", border_style="blue"))


def _print_corpus_preview(kb_dir: Path) -> int:
    """
    Read index.json, print a status breakdown table, and return total article count.
    Exits with code 1 if index.json is missing.
    """
    index_file = kb_dir / "index.json"
    if not index_file.exists():
        console.print(
            f"\n[red]Error:[/red] index.json not found at "
            f"[underline]{kb_dir}[/underline]\n\n"
            "Build the corpus first:\n"
            "  [bold]uv run main.py \"your query\" --download[/bold]"
        )
        sys.exit(1)

    index: dict = json.loads(index_file.read_text(encoding="utf-8"))
    articles = list(index.values())
    total = len(articles)

    # Breakdown by download_status
    status_counts: dict[str, int] = {}
    for art in articles:
        s = art.get("download_status") or "metadata_only"
        status_counts[s] = status_counts.get(s, 0) + 1

    table = Table(
        title=f"Corpus Preview  ({index_file})",
        show_lines=False,
        box=None,
        padding=(0, 2),
    )
    table.add_column("Download Status", style="cyan", no_wrap=True)
    table.add_column("Count",           justify="right", style="bold")
    table.add_column("Notes",           style="dim")

    rows = [
        ("pdf",           "[green]PDF[/green]",                "Full paper PDF available"),
        ("fulltext",      "[blue]Full text[/blue]",            "HTML full text scraped"),
        ("metadata_only", "[yellow]Metadata only[/yellow]",    "Title + abstract only (paywalled)"),
        ("failed",        "[red]Failed[/red]",                 "Download failed"),
    ]
    for key, label, desc in rows:
        n = status_counts.get(key, 0)
        if n:
            table.add_row(label, str(n), desc)
    table.add_row("[bold]Total[/bold]", str(total), "")

    console.print()
    console.print(table)
    return total


def _print_ingestion_summary(counts: dict) -> None:
    """Print the ingestion result counts in a simple table."""
    table = Table(
        title="Ingestion Result",
        show_lines=False,
        box=None,
        padding=(0, 2),
    )
    table.add_column("Status", style="cyan", no_wrap=True)
    table.add_column("Count",  justify="right", style="bold")

    rows = [
        ("total",    "[bold]Total processed[/bold]"),
        ("ingested", "[green]Ingested[/green]"),
        ("skipped",  "[dim]Skipped (already in graph)[/dim]"),
        ("failed",   "[red]Failed[/red]"),
    ]
    for key, label in rows:
        n = counts.get(key, 0)
        if n:
            table.add_row(label, str(n))

    console.print()
    console.print(table)


def _print_post_stats(neo4j_stats: dict, qdrant_stats: dict) -> None:
    """Print Neo4j and Qdrant post-ingestion statistics side by side."""

    # --- Neo4j table ---
    n4j = Table(title="Neo4j Graph", show_lines=False, box=None, padding=(0, 2))
    n4j.add_column("Metric", style="cyan",  no_wrap=True)
    n4j.add_column("Count",  style="bold",  justify="right")

    neo4j_rows = [
        ("total_articles",   "Articles (total)"),
        ("pdf_count",        "  with PDF"),
        ("fulltext_count",   "  with full text"),
        ("meta_count",       "  metadata only"),
        ("total_chunks",     "Chunk nodes"),
        ("total_topics",     "Topic nodes"),
        ("total_industries", "Industry nodes"),
    ]
    for key, label in neo4j_rows:
        val = neo4j_stats.get(key)
        if val is not None:
            n4j.add_row(label, str(val))

    # --- Qdrant table ---
    qd = Table(title="Qdrant Vector Store", show_lines=False, box=None, padding=(0, 2))
    qd.add_column("Metric", style="cyan", no_wrap=True)
    qd.add_column("Value",  style="bold")

    for key, val in qdrant_stats.items():
        qd.add_row(key.replace("_", " ").title(), str(val))

    console.print()
    console.print(
        Columns(
            [
                Panel(n4j, border_style="green"),
                Panel(qd,  border_style="magenta"),
            ]
        )
    )


# ---------------------------------------------------------------------------
# Main async runner
# ---------------------------------------------------------------------------

async def run(args: argparse.Namespace) -> int:
    counts: dict[str, int] = {}

    # ── Banner + config ────────────────────────────────────────────────────
    console.print(
        Panel.fit(
            "[bold blue]Manual Ingestion[/bold blue]\n"
            "[dim]knowledge_base/  ->  Neo4j graph  +  Qdrant vector store[/dim]",
            border_style="blue",
        )
    )
    _print_config(args.kb_dir, args.force)

    # ── Corpus preview ─────────────────────────────────────────────────────
    total = _print_corpus_preview(args.kb_dir)
    console.print(
        f"\n[bold]Ready to process [cyan]{total}[/cyan] article(s) from the corpus.[/bold]"
    )

    # ── Connect Neo4j + bootstrap schema ──────────────────────────────────
    console.rule("[bold]Step 1  |  Neo4j Connection and Schema Bootstrap[/bold]")
    async with Neo4jManager() as neo4j:
        try:
            await neo4j.setup_schema()
            console.print(
                "  [green]Schema ready[/green]  "
                "(constraints, indexes, Topic/Industry seed nodes)"
            )
        except Exception as exc:
            console.print(f"\n[red]Neo4j setup failed:[/red] {exc}")
            console.print(
                "  Ensure Neo4j is running and credentials are correct in .env\n"
                f"  URI:  {settings.neo4j_uri}\n"
                f"  User: {settings.neo4j_user}"
            )
            return 1

        # ── Qdrant collection ──────────────────────────────────────────────
        console.rule("[bold]Step 2  |  Qdrant Collection Setup[/bold]")
        qdrant = QdrantManager()

        if args.force:
            console.print(
                "  [yellow]--force set: deleting existing Qdrant collection...[/yellow]"
            )
            try:
                qdrant.delete_collection()
                console.print("  [yellow]  Existing collection deleted.[/yellow]")
            except Exception:
                console.print("  [dim]  (No existing collection to delete.)[/dim]")

        try:
            qdrant.ensure_collection()
            console.print(
                f"  [green]Qdrant collection[/green] "
                f"'[cyan]{settings.qdrant_collection}[/cyan]' ready  "
                f"(dim=384, cosine similarity)"
            )
        except Exception as exc:
            console.print(f"\n[red]Qdrant setup failed:[/red] {exc}")
            console.print(
                "  Ensure Docker is running and Qdrant is up:\n"
                "  [bold]docker compose up -d qdrant[/bold]"
            )
            return 1

        # ── Ingestion pipeline ─────────────────────────────────────────────
        console.rule("[bold]Step 3  |  Ingestion Pipeline[/bold]")
        console.print(
            f"  Extracting text -> chunking -> embedding -> "
            f"upserting to Neo4j + Qdrant..."
        )
        if args.force:
            console.print("  [yellow]  --force: all articles will be re-ingested.[/yellow]")
        else:
            console.print("  [dim]  Incremental: articles already in Neo4j will be skipped.[/dim]")

        builder = GraphBuilder(neo4j, qdrant)
        try:
            counts = await builder.build(
                kb_dir=args.kb_dir,
                skip_existing=(not args.force),
            )
        except Exception as exc:
            console.print(f"\n[red]Ingestion pipeline failed:[/red] {exc}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            return 1

        _print_ingestion_summary(counts)

        # ── Post-ingestion statistics ─────────────────────────────────────
        console.rule("[bold]Step 4  |  Post-Ingestion Statistics[/bold]")
        try:
            neo4j_stats  = await neo4j.get_status()
            qdrant_stats = qdrant.get_status()
            _print_post_stats(neo4j_stats, qdrant_stats)
        except Exception as exc:
            console.print(f"[yellow]Could not retrieve statistics:[/yellow] {exc}")

    # ── Final banner ───────────────────────────────────────────────────────
    failed = counts.get("failed", 0)
    if failed:
        console.print(
            Panel.fit(
                f"[yellow]Ingestion finished with [bold]{failed}[/bold] failure(s).[/yellow]\n"
                "Run with [bold]-v[/bold] for debug details.",
                border_style="yellow",
            )
        )
    else:
        console.print(
            Panel.fit(
                "[bold green]Ingestion complete  -  all articles processed successfully.[/bold green]\n"
                "Verify results:  [bold]uv run ingestion_verification.py[/bold]",
                border_style="green",
            )
        )

    return 0 if failed == 0 else 1


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

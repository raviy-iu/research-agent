"""
download.py – Standalone CLI to build a local knowledge-base corpus from
              research-agent output JSON files.

Usage
-----
    # Process a single output file
    uv run download.py outputs/20260310_170704_fmea_cement_kiln.json

    # Process the three most recent output files
    uv run download.py outputs/file1.json outputs/file2.json outputs/file3.json

    # Process ALL JSON files in outputs/ at once
    uv run download.py --all

    # Choose a custom knowledge-base directory (default: knowledge_base/)
    uv run download.py --all --kb-dir my_corpus

    # Set the Unpaywall email (any email works; default: value from .env)
    uv run download.py --all --email you@yourorg.com

    # Limit concurrency to avoid hammering servers (default: 4)
    uv run download.py --all --max-concurrent 2

    # Skip sources you don't want to scrape
    uv run download.py --all --skip-sources SlideShare,Medium

    # Verbose debug output
    uv run download.py --all -v

What it does
------------
- Medium / SlideShare  : scrapes full article text and saves as fulltext.txt
- MDPI (10.3390)       : retrieves open-access PDF via Unpaywall, saves as paper.pdf
- IEEE / Springer / etc: queries Unpaywall for any legal OA copy; metadata-only if none
- Academic (S2)        : tries Unpaywall, then direct URL scrape as fallback
- Paywalled content is NEVER bypassed – only legally accessible copies are saved
- Incremental: already-downloaded articles are skipped on re-runs
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
from downloader import download_corpus

console = Console()


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="download",
        description=(
            "Build a local knowledge-base corpus from research-agent output JSON."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "json_files",
        nargs="*",
        type=Path,
        metavar="JSON_FILE",
        help="One or more output JSON files to process.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every *.json file found in --output-dir (default: outputs/).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=settings.output_dir,
        metavar="DIR",
        help=(
            f"Directory to scan when --all is used "
            f"(default: {settings.output_dir})."
        ),
    )
    parser.add_argument(
        "--kb-dir",
        type=Path,
        default=Path("knowledge_base"),
        metavar="DIR",
        help="Root directory for the local corpus (default: knowledge_base/).",
    )
    parser.add_argument(
        "--email",
        type=str,
        default=settings.crossref_email,
        metavar="EMAIL",
        help=(
            "Email address for Unpaywall API – any email works "
            f"(default: {settings.crossref_email})."
        ),
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=4,
        metavar="N",
        help="Maximum simultaneous downloads (default: 4).",
    )
    parser.add_argument(
        "--skip-sources",
        type=str,
        default="",
        metavar="SOURCES",
        help=(
            "Comma-separated source names to skip entirely. "
            "Options: IEEE, ScienceDirect, TaylorFrancis, MDPI, Springer, "
            "ACS, Wiley, Academic, Medium, SlideShare."
        ),
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging (shows per-article decisions).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _collect_articles(json_files: list[Path]) -> list[dict]:
    """
    Load and merge articles from one or more agent output JSON files.
    Deduplicates across files by DOI (preferred) or URL.
    """
    seen_keys: set[str] = set()
    articles: list[dict] = []

    for path in json_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            console.print(f"[red]Cannot read {path}: {exc}[/red]")
            continue

        raw_results = data.get("results", [])
        for art in raw_results:
            doi = (art.get("doi") or "").strip().lower()
            url = (art.get("url") or "").strip().lower()
            key = f"doi:{doi}" if doi else f"url:{url}"
            if key not in seen_keys:
                seen_keys.add(key)
                articles.append(art)

        console.print(
            f"  [dim]Loaded {len(raw_results)} articles from {path.name}[/dim]"
        )

    return articles


# ---------------------------------------------------------------------------
# Main async entrypoint
# ---------------------------------------------------------------------------

async def _main(args: argparse.Namespace) -> int:
    console.print(
        Panel.fit(
            "[bold blue]Research Agent – Knowledge Base Builder[/bold blue]\n"
            "[dim]Downloads open-access PDFs and web article text[/dim]",
            border_style="blue",
        )
    )

    # ── Collect JSON files to process ───────────────────────────────────────
    json_files: list[Path] = list(args.json_files)
    if args.all:
        found = sorted(args.output_dir.glob("*.json"))
        if not found:
            console.print(
                f"[yellow]No JSON files found in {args.output_dir}/[/yellow]"
            )
        json_files = found + [f for f in json_files if f not in found]

    if not json_files:
        console.print(
            "[red]Error:[/red] Provide at least one JSON file or use --all.\n"
            "  uv run download.py outputs/20260310_170704_fmea_cement_kiln.json\n"
            "  uv run download.py --all"
        )
        return 1

    console.print(f"\n[bold]Loading articles from {len(json_files)} file(s)...[/bold]")
    articles = _collect_articles(json_files)

    if not articles:
        console.print("[yellow]No articles found in the specified files.[/yellow]")
        return 1

    skip_sources = [s.strip() for s in args.skip_sources.split(",") if s.strip()]

    console.print(
        f"\n  [bold]Articles to process:[/bold]  {len(articles)}\n"
        f"  [bold]Knowledge-base dir: [/bold]  {args.kb_dir}\n"
        f"  [bold]Unpaywall email:    [/bold]  {args.email}\n"
        f"  [bold]Max concurrent:     [/bold]  {args.max_concurrent}"
        + (
            f"\n  [bold]Skipping sources:   [/bold]  {', '.join(skip_sources)}"
            if skip_sources
            else ""
        )
    )
    console.print()

    # ── Run downloader ───────────────────────────────────────────────────────
    counts = await download_corpus(
        articles=articles,
        kb_dir=args.kb_dir,
        email=args.email,
        max_concurrent=args.max_concurrent,
        skip_sources=skip_sources or None,
    )

    # ── Summary table ────────────────────────────────────────────────────────
    table = Table(title="Download Summary", show_lines=False, box=None, padding=(0, 2))
    table.add_column("Status",  style="cyan",  no_wrap=True)
    table.add_column("Count",   justify="right", style="bold")

    label_map = {
        "pdf":           "[green]PDF downloaded (open-access)[/green]",
        "fulltext":      "[blue]Full text scraped (web)[/blue]",
        "metadata_only": "[yellow]Metadata + abstract only (paywalled)[/yellow]",
        "failed":        "[red]Failed[/red]",
        "skipped":       "[dim]Skipped (already in corpus)[/dim]",
        "total":         "[bold]Total processed[/bold]",
    }
    for key, label in label_map.items():
        n = counts.get(key, 0)
        if n:
            table.add_row(label, str(n))

    console.print()
    console.print(table)
    console.print(
        f"\n[bold green]Corpus saved ->[/bold green] "
        f"[underline]{args.kb_dir.resolve()}[/underline]\n"
        f"[dim]Master index: {args.kb_dir / 'index.json'}[/dim]\n"
        f"[dim]Per-article folders: {args.kb_dir}/papers/<Source>/<id>/[/dim]"
    )
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    _setup_logging(args.verbose)
    try:
        code = asyncio.run(_main(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()

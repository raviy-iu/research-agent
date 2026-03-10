"""
main.py - CLI entry point for the Manufacturing Research Agent.

Usage - Raw query
-----------------
    uv run main.py "FMEA in cement manufacturing digital twin"
    uv run main.py "energy optimization steel plant" --max-results 50
    uv run main.py "digital twin hybrid modeling" --sources ieee,mdpi,medium

Usage - Prompt templates
------------------------
    uv run main.py --list-templates
    uv run main.py --template fmea --set industry=cement --set equipment=kiln
    uv run main.py --template energy_opt --set industry=steel --set process=blast_furnace
    uv run main.py --template digital_twin --set industry=aluminum --set asset=smelter --max-results 40

Arguments
---------
    query           (optional) Raw research query. Not needed when --template is used.

Options
-------
    --template      Name of prompt template from prompts.json
    --set KEY=VALUE Fill a template placeholder (repeatable)
    --list-templates  Print all available templates and exit
    --max-results   Maximum number of results to return (default: 25)
    --sources       Comma-separated list of sources:
                    Academic (via CrossRef): ieee, sciencedirect, taylorfrancis, mdpi, springer, acs, wiley
                    Other: medium, slideshare, all
    --output-dir    Directory to save JSON output (default: outputs/)
    -v, --verbose   Enable debug logging

Output JSON schema
------------------
    {
      "query": "<rendered query>",
      "expanded_query": "<query with manufacturing context>",
      "template": { "name": "fmea", "version": 1, "keys": {...} } | null,
      "timestamp": "<ISO 8601>",
      "total_results": N,
      "results": [
        {
          "title": "...",
          "source": "IEEE | ScienceDirect | TaylorFrancis | MDPI | Medium | Academic",
          "url": "https://...",
          "doi": "10.xxxx/...",
          "abstract": "...",
          "year": 2024,
          "authors": ["Author Name", ...]
        }
      ]
    }
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

import agent
from config import settings
from prompt_template import (
    list_templates,
    parse_set_args,
    render,
    show_template_preview,
    get_template,
)
from query_builder import build_query

console = Console()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="research-agent",
        description=(
            "Manufacturing Research Agent - searches IEEE, ScienceDirect, "
            "Taylor & Francis, MDPI, and Medium for relevant articles."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Positional query – optional when --template is used
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        type=str,
        help=(
            "Raw research query. Wrap in quotes for multi-word queries. "
            "Not needed when --template is used. "
            "Examples: \"FMEA cement kiln\" | \"digital twin steel plant\""
        ),
    )

    # Template flags
    parser.add_argument(
        "--template",
        type=str,
        default=None,
        metavar="NAME",
        help=(
            "Use a named prompt template from prompts.json. "
            "Run --list-templates to see all options."
        ),
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        dest="set_args",
        help=(
            "Set a template placeholder value. Repeatable. "
            "Example: --set industry=cement --set equipment=kiln"
        ),
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="Print all available templates with their keys and exit.",
    )

    # Search options
    parser.add_argument(
        "--max-results",
        type=int,
        default=settings.results_per_source,
        metavar="N",
        help=f"Maximum total results to return (default: {settings.results_per_source})",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="all",
        metavar="SOURCES",
        help=(
            "Comma-separated sources to query. "
            "Academic publishers (via CrossRef): ieee, sciencedirect, taylorfrancis, mdpi, springer, acs, wiley. "
            "Other: medium, slideshare, all. "
            "(default: all)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=settings.output_dir,
        metavar="DIR",
        help=f"Directory to save JSON results (default: {settings.output_dir})",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    # Downloader flags
    parser.add_argument(
        "--download",
        action="store_true",
        help=(
            "After searching, download open-access PDFs and web article text "
            "to --kb-dir.  Uses Unpaywall for academic papers and HTTP scraping "
            "for Medium / SlideShare.  Paywalled content is never bypassed."
        ),
    )
    parser.add_argument(
        "--kb-dir",
        type=Path,
        default=Path("knowledge_base"),
        metavar="DIR",
        help=(
            "Root directory for the local knowledge-base corpus "
            "(default: knowledge_base/).  Only used when --download is set."
        ),
    )

    return parser.parse_args()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _parse_sources(sources_str: str) -> list[str] | None:
    if sources_str.strip().lower() == "all":
        return None
    return [s.strip().lower() for s in sources_str.split(",") if s.strip()]


def _resolve_query(args: argparse.Namespace) -> tuple[str, dict | None]:
    """
    Determine the final query string and optional template metadata.

    Returns
    -------
    (query_text, template_meta)
        template_meta is None for raw queries, or a dict for template-based queries.
    """
    if args.template:
        kv = parse_set_args(args.set_args)
        try:
            show_template_preview(args.template, kv)
            query_text = render(args.template, kv)
        except KeyError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            sys.exit(1)
        tpl = get_template(args.template)
        template_meta = {
            "name": args.template,
            "version": tpl.version,
            "keys": kv,
            "template_string": tpl.template,
        }
        return query_text, template_meta

    if not args.query:
        console.print(
            "[red]Error:[/red] Provide a query or use --template.\n"
            "  uv run main.py \"FMEA cement kiln\"\n"
            "  uv run main.py --template fmea --set industry=cement --set equipment=kiln\n"
            "  uv run main.py --list-templates"
        )
        sys.exit(1)

    return args.query, None


async def _main(args: argparse.Namespace) -> int:
    console.print(
        Panel.fit(
            "[bold blue]Manufacturing Research Agent[/bold blue]\n"
            "[dim]IEEE | ScienceDirect | T&F | MDPI | Springer | ACS | Wiley | SlideShare | Medium[/dim]",
            border_style="blue",
        )
    )

    query_text, template_meta = _resolve_query(args)
    source_filter = _parse_sources(args.sources)
    bundle = build_query(query_text)

    articles = await agent.run(
        query_text=query_text,
        max_results=args.max_results,
        source_filter=source_filter,
    )

    if not articles:
        console.print("[yellow]No results found. Try broadening your query.[/yellow]")
        return 1

    out_path = agent.save_results(
        articles=articles,
        query=bundle.raw,
        expanded_query=bundle.expanded,
        output_dir=args.output_dir,
        template_meta=template_meta,
    )

    console.print(
        f"\n[bold green]Results saved ->[/bold green] [underline]{out_path}[/underline]"
    )

    # ── Optional: build / update local knowledge-base corpus ────────────────
    if args.download:
        from downloader import download_corpus
        from rich.table import Table

        console.print(
            f"\n[bold cyan]Building knowledge-base corpus in "
            f"[underline]{args.kb_dir}[/underline]...[/bold cyan]"
        )
        counts = await download_corpus(
            articles=[a.to_dict() for a in articles],
            kb_dir=args.kb_dir,
            email=settings.crossref_email,
        )

        summary = Table(title="Download Summary", show_lines=False, box=None, padding=(0, 2))
        summary.add_column("Status",  style="cyan", no_wrap=True)
        summary.add_column("Count",   justify="right", style="bold")
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
                summary.add_row(label, str(n))
        console.print()
        console.print(summary)
        console.print(
            f"\n[bold green]Corpus saved ->[/bold green] "
            f"[underline]{args.kb_dir.resolve()}[/underline]"
        )

    return 0


def main() -> None:
    args = _parse_args()
    _setup_logging(args.verbose)

    # Handle --list-templates before anything else
    if args.list_templates:
        list_templates()
        sys.exit(0)

    try:
        exit_code = asyncio.run(_main(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        exit_code = 130

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

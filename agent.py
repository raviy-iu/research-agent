"""
agent.py – Orchestrates all sources, deduplicates results, and saves JSON.

Flow:
  1. Build a QueryBundle from the user's raw query text.
  2. Instantiate all active sources (CrossRef, Semantic Scholar, SlideShare, Medium).
  3. Fire all source.fetch() calls concurrently via asyncio.gather.
  4. Merge results; deduplicate by DOI (primary) or URL (fallback).
  5. Interleave by source for diversity, then truncate to max_results.
  6. Return the final Article list.

Deduplication priority (lower index = higher priority, kept on clash):
  IEEE > ScienceDirect > TaylorFrancis > MDPI > Springer > ACS > Wiley
  > Academic > SlideShare > Medium
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from config import settings
from query_builder import QueryBundle, build_query
from sources.base import Article
from sources.crossref import CrossRefSource
from sources.medium import MediumSource
from sources.semantic_scholar import SemanticScholarSource
from sources.slideshare import SlideShareSource

logger = logging.getLogger(__name__)
console = Console()

# Source priority for deduplication (lower index → preferred)
_SOURCE_PRIORITY = [
    "IEEE",
    "ScienceDirect",
    "TaylorFrancis",
    "MDPI",
    "Springer",
    "ACS",
    "Wiley",
    "Academic",
    "SlideShare",
    "Medium",
]


def _source_rank(source_name: str) -> int:
    try:
        return _SOURCE_PRIORITY.index(source_name)
    except ValueError:
        return len(_SOURCE_PRIORITY)


async def run(
    query_text: str,
    max_results: int = 25,
    source_filter: list[str] | None = None,
) -> list[Article]:
    """
    Execute the full research pipeline and return deduplicated Article list.

    Parameters
    ----------
    query_text : str
        Raw user query from the terminal.
    max_results : int
        Maximum number of results to return (after deduplication).
    source_filter : list[str] | None
        If provided, only sources whose name matches one of these strings
        (case-insensitive prefix match) are included.
        E.g. ["ieee", "mdpi"] → includes CrossRef-IEEE, CrossRef-MDPI, Medium skipped.

    Returns
    -------
    list[Article]
    """
    bundle = build_query(query_text)

    console.print(f"\n[bold cyan]Query:[/bold cyan] {bundle.raw}")
    if bundle.expanded != bundle.raw:
        console.print(
            f"[dim]Expanded:[/dim] {bundle.expanded}"
        )

    sources = _build_sources(source_filter)
    source_names = [type(s).__name__.replace("Source", "") for s in sources]
    console.print(
        f"[bold]Searching {len(sources)} source(s):[/bold] "
        + ", ".join(source_names)
    )

    raw_articles: list[list[Article]] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Fetching articles...", total=None)
        raw_articles = await asyncio.gather(
            *[src.fetch(bundle) for src in sources],
            return_exceptions=True,
        )
        progress.update(task, description="Done fetching.")

    all_articles: list[Article] = []
    for result in raw_articles:
        if isinstance(result, Exception):
            logger.warning("Source error: %s", result)
        else:
            all_articles.extend(result)

    console.print(
        f"[green]Collected {len(all_articles)} raw results[/green] "
        f"(before deduplication)"
    )

    deduped = _deduplicate(all_articles)
    unique_count = len(deduped)
    console.print(
        f"[green]{unique_count} unique articles[/green] found across all sources"
    )

    # Interleave across sources for diversity, then truncate
    interleaved = _interleave_by_source(deduped)
    if max_results and len(interleaved) > max_results:
        interleaved = interleaved[:max_results]

    console.print(
        f"[bold green]{len(interleaved)} articles[/bold green] returned "
        f"(max-results={max_results})"
    )
    _print_summary_table(interleaved)
    return interleaved


def _build_sources(source_filter: list[str] | None) -> list:
    """Build the list of active source objects respecting source_filter.

    CrossRef covers all academic publishers (IEEE/ScienceDirect/T&F/MDPI/
    Springer/ACS/Wiley) via DOI-prefix filtering — a single CrossRefSource
    instance handles all of them.  When the user requests a specific academic
    publisher via --sources, include_crossref is set and CrossRef will filter
    internally to return only that publisher's articles.
    """
    all_sources = [
        CrossRefSource(),
        SemanticScholarSource(),
        SlideShareSource(),
        MediumSource(),
    ]

    if not source_filter:
        return all_sources

    filter_lower = {f.lower() for f in source_filter}

    # All academic publishers route through CrossRef
    academic_tokens = {
        "ieee", "sciencedirect", "taylorfrancis", "mdpi",
        "springer", "acs", "wiley",
        "elsevier", "taylor", "crossref", "academic",
    }
    include_crossref  = bool(academic_tokens & filter_lower)
    include_s2        = bool({"semantic", "semanticscholar", "academic", "scholar"} & filter_lower)
    include_slideshare = bool({"slideshare"} & filter_lower)
    include_medium    = bool({"medium"} & filter_lower)

    # Default: if no known token matched, return everything
    if not (include_crossref or include_s2 or include_slideshare or include_medium):
        return all_sources

    result = []
    if include_crossref:
        result.append(CrossRefSource())
    if include_s2:
        result.append(SemanticScholarSource())
    if include_slideshare:
        result.append(SlideShareSource())
    if include_medium:
        result.append(MediumSource())
    return result


def _deduplicate(articles: list[Article]) -> list[Article]:
    """
    Remove duplicate articles, preferring higher-priority sources.

    Uses DOI as the primary dedup key (case-insensitive), URL as fallback.
    When two articles share a key, keep the one from the higher-priority source.
    """
    # Sort by priority first so we can just keep first-seen
    articles_sorted = sorted(articles, key=lambda a: _source_rank(a.source))
    seen: dict[str, Article] = {}

    for art in articles_sorted:
        key = art.dedup_key()
        if not key:
            # No reliable key – include but track by object id to avoid dropping
            key = f"_nokey_{id(art)}"
        if key not in seen:
            seen[key] = art

    return list(seen.values())


def _sort(articles: list[Article]) -> list[Article]:
    """Sort by source priority (asc) then year (desc, None last)."""
    return sorted(
        articles,
        key=lambda a: (_source_rank(a.source), -(a.year or 0)),
    )


def _interleave_by_source(articles: list[Article]) -> list[Article]:
    """
    Interleave articles round-robin across sources so the final list
    has diversity instead of all articles from one source at the top.

    Within each source, articles are ordered by year (descending).
    Source order follows _SOURCE_PRIORITY.
    """
    from collections import defaultdict

    buckets: dict[str, list[Article]] = defaultdict(list)
    for art in articles:
        buckets[art.source].append(art)

    # Sort each bucket by year descending
    for src in buckets:
        buckets[src].sort(key=lambda a: -(a.year or 0))

    # Determine source order (priority order, then alphabetical for unknowns)
    ordered_sources = [s for s in _SOURCE_PRIORITY if s in buckets]
    ordered_sources += sorted(s for s in buckets if s not in _SOURCE_PRIORITY)

    result: list[Article] = []
    queues = [buckets[s] for s in ordered_sources]
    while any(queues):
        for q in queues:
            if q:
                result.append(q.pop(0))
    return result


def _print_summary_table(articles: list[Article]) -> None:
    table = Table(title="Results Summary", show_lines=False, box=None)
    table.add_column("Source", style="cyan", no_wrap=True)
    table.add_column("Count", justify="right", style="green")

    counts: dict[str, int] = {}
    for art in articles:
        counts[art.source] = counts.get(art.source, 0) + 1

    for src in _SOURCE_PRIORITY:
        if src in counts:
            table.add_row(src, str(counts[src]))
    for src, count in sorted(counts.items()):
        if src not in _SOURCE_PRIORITY:
            table.add_row(src, str(count))

    console.print(table)


def save_results(
    articles: list[Article],
    query: str,
    expanded_query: str,
    output_dir: Path,
    slug: str = "",
    template_meta: dict | None = None,
) -> Path:
    """
    Serialise articles to a timestamped JSON file and return its path.

    JSON schema:
    {
      "query": "...",
      "expanded_query": "...",
      "template": { "name": "fmea", "version": 1, "keys": {...}, "template_string": "..." } | null,
      "timestamp": "ISO 8601",
      "total_results": N,
      "results": [ { "title", "source", "url", "doi", "abstract", "year", "authors" } ]
    }
    """
    import re as _re

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now()
    ts_str = timestamp.strftime("%Y%m%d_%H%M%S")

    if not slug:
        # Use template name as slug prefix when available
        prefix = (template_meta or {}).get("name", "")
        base = prefix + "_" + query if prefix else query
        slug = _re.sub(r"[^a-z0-9]+", "_", base.lower())[:40].strip("_")

    filename = f"{ts_str}_{slug}.json" if slug else f"{ts_str}_results.json"
    out_path = output_dir / filename

    payload = {
        "query": query,
        "expanded_query": expanded_query,
        "template": template_meta,
        "timestamp": timestamp.isoformat(),
        "total_results": len(articles),
        "results": [a.to_dict() for a in articles],
    }

    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out_path

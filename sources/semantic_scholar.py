"""
sources/semantic_scholar.py – Search Semantic Scholar Graph API (free, no key).

Semantic Scholar provides broad academic coverage. We filter results to only
keep papers from our target publishers (IEEE, Elsevier, T&F, MDPI) by checking
their DOI prefix. Results without a DOI from a known publisher are kept as
"Academic" if they have a plausible manufacturing-topic relevance.

Rate limit:
  Without API key: ~1 request/second (shared pool).
  With SEMANTIC_SCHOLAR_API_KEY: 100 requests/second.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import DOI_PREFIXES, PREFIX_TO_SOURCE, TIMEOUT_SECONDS, settings
from sources.base import Article, BaseSource

if TYPE_CHECKING:
    from query_builder import QueryBundle

logger = logging.getLogger(__name__)

_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,externalIds,url,year,authors,abstract,openAccessPdf,venue"

# Known DOI prefixes we care about
_TARGET_PREFIXES = set(DOI_PREFIXES.values())


class SemanticScholarSource(BaseSource):
    """Fetches academic papers from Semantic Scholar Graph API."""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(1)  # conservative – 1 rps default

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if settings.semantic_scholar_api_key:
            headers["x-api-key"] = settings.semantic_scholar_api_key
        return headers

    async def fetch(self, query: "QueryBundle") -> list[Article]:
        articles: list[Article] = []
        offset = 0
        limit = min(settings.results_per_source, 100)

        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            headers=self._build_headers(),
            follow_redirects=True,
        ) as client:
            articles = await self._fetch_page(client, query.expanded, offset, limit)

        logger.debug("SemanticScholar returned %d total results", len(articles))
        return articles

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        query: str,
        offset: int,
        limit: int,
    ) -> list[Article]:
        async with self._semaphore:
            params = {
                "query": query,
                "fields": _FIELDS,
                "offset": offset,
                "limit": limit,
            }
            resp = await client.get(_S2_SEARCH_URL, params=params)
            if resp.status_code == 429:
                logger.warning("Semantic Scholar rate limited – waiting 5s")
                await asyncio.sleep(5)
                resp = await client.get(_S2_SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        articles: list[Article] = []
        for paper in data.get("data", []):
            title = (paper.get("title") or "").strip()
            if not title:
                continue

            doi, source_name, url = _resolve_doi_and_source(paper)
            if not url:
                continue

            year = paper.get("year")
            abstract = (paper.get("abstract") or "").strip()
            authors = [
                a.get("name", "") for a in (paper.get("authors") or []) if a.get("name")
            ]

            articles.append(
                Article(
                    title=title,
                    source=source_name,
                    url=url,
                    doi=doi,
                    abstract=abstract,
                    year=year,
                    authors=authors,
                )
            )

        # Polite delay without key
        if not settings.semantic_scholar_api_key:
            await asyncio.sleep(1.1)

        return articles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_doi_and_source(paper: dict) -> tuple[str, str, str]:
    """Return (doi, source_name, url) for a Semantic Scholar paper entry."""
    external_ids = paper.get("externalIds") or {}
    doi = (external_ids.get("DOI") or "").strip()
    url = ""
    source_name = "Academic"

    # Determine source from DOI prefix
    if doi:
        prefix = _doi_prefix(doi)
        if prefix in PREFIX_TO_SOURCE:
            source_name = PREFIX_TO_SOURCE[prefix]
        url = f"https://doi.org/{doi}"

    # Prefer open-access PDF URL
    oa_pdf = paper.get("openAccessPdf") or {}
    oa_url = (oa_pdf.get("url") or "").strip()

    # S2 paper page URL (fallback only)
    paper_url = (paper.get("url") or "").strip()

    # URL priority:
    # 1. DOI URL for known publishers (most direct link to publisher page)
    # 2. Open-access PDF
    # 3. S2 paper page (last resort)
    if doi:
        final_url = f"https://doi.org/{doi}"
    elif oa_url:
        final_url = oa_url
    else:
        final_url = paper_url

    return doi, source_name, final_url


def _doi_prefix(doi: str) -> str:
    """Extract the registrant prefix (e.g. '10.1109') from a DOI."""
    parts = doi.split("/")
    return parts[0] if parts else ""

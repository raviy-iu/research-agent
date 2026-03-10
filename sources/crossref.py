"""
sources/crossref.py – Search CrossRef API filtered by publisher DOI prefix.

CrossRef is the primary free source. It indexes all major academic publishers
and allows filtering by DOI prefix, giving us clean per-publisher buckets:
  IEEE          → 10.1109
  ScienceDirect → 10.1016
  Taylor&Francis→ 10.1080
  MDPI          → 10.3390

No API key needed. Providing an email address via the User-Agent polite-pool
header significantly improves rate limits (documented: up to 50 rps).
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

_CROSSREF_URL = "https://api.crossref.org/works"


class CrossRefSource(BaseSource):
    """Fetches articles from IEEE, ScienceDirect, Taylor & Francis, and MDPI
    via the CrossRef works API, one parallel request per publisher prefix."""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(3)

    async def fetch(self, query: "QueryBundle") -> list[Article]:
        headers = {
            "User-Agent": (
                f"ResearchAgent/0.1 (mailto:{settings.crossref_email})"
            )
        }
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, headers=headers, follow_redirects=True
        ) as client:
            tasks = [
                self._fetch_prefix(client, query.expanded, prefix, source_name)
                for source_name, prefix in DOI_PREFIXES.items()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        articles: list[Article] = []
        for res in results:
            if isinstance(res, Exception):
                logger.warning("CrossRef fetch error: %s", res)
            else:
                articles.extend(res)
        return articles

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _fetch_prefix(
        self,
        client: httpx.AsyncClient,
        query: str,
        prefix: str,
        source_name: str,
    ) -> list[Article]:
        async with self._semaphore:
            params = {
                "query": query,
                "filter": f"prefix:{prefix}",
                "rows": settings.results_per_source,
                "select": "DOI,title,author,published,abstract,link,URL",
            }
            resp = await client.get(_CROSSREF_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        items = data.get("message", {}).get("items", [])
        articles: list[Article] = []
        for item in items:
            title = _extract_title(item)
            doi = item.get("DOI", "")
            url = _extract_url(item, doi)
            if not title or not url:
                continue
            articles.append(
                Article(
                    title=title,
                    source=source_name,
                    url=url,
                    doi=doi,
                    abstract=_extract_abstract(item),
                    year=_extract_year(item),
                    authors=_extract_authors(item),
                )
            )
        logger.debug("CrossRef [%s] returned %d results", source_name, len(articles))
        return articles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_title(item: dict) -> str:
    titles = item.get("title", [])
    return titles[0].strip() if titles else ""


def _extract_url(item: dict, doi: str) -> str:
    """
    Return the best viewer URL for an article.

    Priority:
    1. DOI URL (stable, redirects to publisher) – always preferred
    2. Direct publisher HTML link from CrossRef 'link' array
    3. CrossRef item URL field
    """
    import re

    # Always construct a DOI URL if we have a DOI – most stable
    if doi:
        doi_url = f"https://doi.org/{doi}"
        # For IEEE: also try to build a clean ieeexplore.ieee.org/document/ URL
        if doi.startswith("10.1109/"):
            for link in item.get("link", []):
                raw = link.get("URL", "")
                m = re.search(r"arnumber=(\d+)", raw)
                if m:
                    return f"https://ieeexplore.ieee.org/document/{m.group(1)}"
        return doi_url

    # No DOI – fall back to item URL
    if item.get("URL"):
        return item["URL"]

    # Last resort: parse link array
    for link in item.get("link", []):
        content_type = link.get("content-type", "")
        if "html" in content_type or content_type == "unspecified":
            url = link.get("URL", "")
            if url:
                return url

    return ""


def _extract_abstract(item: dict) -> str:
    abstract = item.get("abstract", "")
    if abstract:
        # CrossRef sometimes wraps abstract in <jats:p> tags
        import re
        abstract = re.sub(r"<[^>]+>", " ", abstract).strip()
    return abstract


def _extract_year(item: dict) -> int | None:
    pub = item.get("published", {}) or item.get("published-print", {}) or {}
    parts = pub.get("date-parts", [[]])
    if parts and parts[0]:
        try:
            return int(parts[0][0])
        except (ValueError, TypeError):
            pass
    return None


def _extract_authors(item: dict) -> list[str]:
    authors = []
    for a in item.get("author", []):
        given = a.get("given", "")
        family = a.get("family", "")
        name = f"{given} {family}".strip() if given or family else ""
        if name:
            authors.append(name)
    return authors

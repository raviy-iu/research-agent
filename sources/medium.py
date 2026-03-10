"""
sources/medium.py – Fetch industry articles from Medium via RSS tag feeds.

Medium provides RSS feeds for every tag at:
    https://medium.com/feed/tag/<tag-slug>

We iterate over a curated list of manufacturing/industry tags, parse each feed
with feedparser, and de-duplicate by URL before returning results.

No API key or authentication required.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import feedparser
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import MEDIUM_TAGS, TIMEOUT_SECONDS, settings
from sources.base import Article, BaseSource

if TYPE_CHECKING:
    from query_builder import QueryBundle

logger = logging.getLogger(__name__)

_MEDIUM_RSS = "https://medium.com/feed/tag/{tag}"

# Keywords used to filter Medium articles so only relevant ones are included
_RELEVANCE_TERMS = {
    "manufactur", "industri", "fmea", "pfmea", "digital twin",
    "predictive", "maintenance", "energy", "optimization", "process",
    "quality", "efficiency", "sustainability", "esg", "root cause",
    "anomaly", "fault", "sensor", "iot", "iiot", "ai", "ml",
    "machine learning", "deep learning", "neural", "data-driven",
    "physics", "hybrid model", "cement", "steel", "aluminum",
    "aluminium", "tyre", "tire", "chemical", "mining", "automobile",
    "automotive", "oil", "gas", "refin", "paper mill", "pulp",
}


class MediumSource(BaseSource):
    """Fetches manufacturing-relevant articles from Medium RSS tag feeds."""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(3)

    async def fetch(self, query: "QueryBundle") -> list[Article]:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            tasks = [
                self._fetch_tag(client, tag, query)
                for tag in MEDIUM_TAGS
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        seen_urls: set[str] = set()
        articles: list[Article] = []
        for res in results:
            if isinstance(res, Exception):
                logger.debug("Medium tag fetch error: %s", res)
                continue
            for art in res:
                if art.url not in seen_urls:
                    seen_urls.add(art.url)
                    articles.append(art)

        logger.debug("Medium returned %d unique results", len(articles))
        return articles

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
    async def _fetch_tag(
        self,
        client: httpx.AsyncClient,
        tag: str,
        query: "QueryBundle",
    ) -> list[Article]:
        url = _MEDIUM_RSS.format(tag=tag)
        async with self._semaphore:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                raw_content = resp.text
            except httpx.HTTPStatusError as exc:
                logger.debug("Medium RSS %s → HTTP %d", tag, exc.response.status_code)
                return []
            except Exception as exc:
                logger.debug("Medium RSS %s error: %s", tag, exc)
                return []

        feed = feedparser.parse(raw_content)
        articles: list[Article] = []
        query_terms = set(query.keywords) | {query.raw.lower()}

        for entry in feed.entries:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            summary = (entry.get("summary") or "").strip()

            if not title or not link:
                continue

            # Only keep articles relevant to the query or manufacturing domain
            combined_text = (title + " " + summary).lower()
            if not _is_relevant(combined_text, query_terms):
                continue

            year = _extract_year(entry)
            author = _extract_author(entry)

            articles.append(
                Article(
                    title=title,
                    source="Medium",
                    url=link,
                    doi="",
                    abstract=_clean_html(summary)[:500],
                    year=year,
                    authors=[author] if author else [],
                )
            )

        return articles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_relevant(text: str, query_terms: set[str]) -> bool:
    """Return True if text contains any manufacturing relevance term or query token."""
    for term in _RELEVANCE_TERMS:
        if term in text:
            return True
    for term in query_terms:
        if term and len(term) > 3 and term in text:
            return True
    return False


def _extract_year(entry: dict) -> int | None:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published:
        try:
            return int(published.tm_year)
        except (AttributeError, TypeError):
            pass
    return None


def _extract_author(entry: dict) -> str:
    author = entry.get("author") or ""
    if not author:
        authors = entry.get("authors", [])
        if authors:
            author = authors[0].get("name", "")
    return author.strip()


def _clean_html(html: str) -> str:
    """Strip HTML tags from a string."""
    import re
    return re.sub(r"<[^>]+>", " ", html).strip()

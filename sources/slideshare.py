"""
sources/slideshare.py – Fetch industry presentations from SlideShare.

SlideShare has no public API; we scrape its search results page using
httpx + BeautifulSoup. This is valuable because SlideShare hosts many
industrial/operational presentations that do NOT appear in academic databases
(e.g., plant operator guides, process sensor alert strategies, OEM manuals,
conference workshop slides on CO monitoring, back-pressure indicators, etc.).

Search endpoint:
    https://www.slideshare.net/search/slideshow?q=<query>

Rate limiting: 2 concurrent requests, 1 s polite delay between calls.
Bot-block (403/429/captcha redirect): logged and returns empty list.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from config import TIMEOUT_SECONDS, settings
from sources.base import Article, BaseSource

if TYPE_CHECKING:
    from query_builder import QueryBundle

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.slideshare.net"
_SEARCH_URL = "https://www.slideshare.net/search/slideshow?q={query}&searchfrom=header&ss_search_type=presentation"

# Browser-like headers to reduce bot detection
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
}

# Manufacturing relevance filter (shared with medium.py pattern)
_RELEVANCE_TERMS = {
    "manufactur", "industri", "fmea", "pfmea", "digital twin",
    "predictive", "maintenance", "energy", "optimiz", "process",
    "quality", "efficiency", "sustainab", "esg", "root cause",
    "anomaly", "fault", "sensor", "iot", "iiot", "kiln", "ring",
    "furnace", "rotary", "cement", "steel", "aluminum", "alumin",
    "tyre", "tire", "chemical", "mining", "automobile", "automot",
    "oil", "gas", "refin", "paper mill", "pulp", "smelter",
    "compressor", "pump", "bearing", "vibration", "temperature",
    "pressure", "flow", "thermal", "emission", "carbon", "heat",
    "combustion", "calcin", "pyrolysis", "clinker", "lime",
    "back pressure", "co content", "shell temperature",
}


class SlideShareSource(BaseSource):
    """Fetches manufacturing-relevant presentations from SlideShare search."""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(2)

    async def fetch(self, query: "QueryBundle") -> list[Article]:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            headers=_HEADERS,
            follow_redirects=True,
        ) as client:
            articles = await self._search(client, query)

        logger.debug("SlideShare returned %d relevant results", len(articles))
        return articles

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
    async def _search(
        self, client: httpx.AsyncClient, query: "QueryBundle"
    ) -> list[Article]:
        url = _SEARCH_URL.format(query=quote_plus(query.expanded))

        async with self._semaphore:
            try:
                resp = await client.get(url)
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                logger.debug("SlideShare connection error: %s", exc)
                return []

        if resp.status_code in (403, 429):
            logger.info(
                "SlideShare returned %d – bot detection or rate limit. "
                "Results unavailable for this query.",
                resp.status_code,
            )
            return []
        if resp.status_code != 200:
            logger.debug("SlideShare HTTP %d for query: %s", resp.status_code, query.raw)
            return []

        # Polite delay
        await asyncio.sleep(1.0)

        return _parse_results(resp.text, query)


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def _parse_results(html: str, query: "QueryBundle") -> list[Article]:
    """Extract SlideShare presentation cards from search result HTML."""
    soup = BeautifulSoup(html, "lxml")
    articles: list[Article] = []
    query_terms = {t.lower() for t in query.keywords if len(t) > 3}

    # SlideShare search results are rendered in <li> or article elements
    # The page structure may vary; we try multiple selector patterns for resilience.
    cards = (
        soup.select("li.slide-item")
        or soup.select("article.slide-item")
        or soup.select("div[data-testid='search-result-item']")
        or _fallback_cards(soup)
    )

    for card in cards:
        title, url = _extract_title_url(card)
        if not title or not url:
            continue

        description = _extract_description(card)
        author = _extract_author(card)
        year = _extract_year(card)

        combined = (title + " " + description).lower()
        if not _is_relevant(combined, query_terms):
            continue

        articles.append(
            Article(
                title=title,
                source="SlideShare",
                url=url,
                doi="",
                abstract=description[:500],
                year=year,
                authors=[author] if author else [],
            )
        )

    return articles[: settings.results_per_source]


def _fallback_cards(soup: BeautifulSoup) -> list:
    """
    Fallback extractor: find all <a> tags that look like SlideShare
    presentation links and return their parent containers.
    """
    seen: set[str] = set()
    containers = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # SlideShare presentation URLs look like /<username>/<slug>
        if re.match(r"^/[^/]+/[^/]+$", href) and href not in seen:
            seen.add(href)
            containers.append(a.parent or a)
    return containers


def _extract_title_url(card) -> tuple[str, str]:
    """Return (title, absolute_url) from a card element."""
    # Try common title link selectors
    for selector in (
        "a.slide-title",
        "h3 a",
        "h2 a",
        "a[href]",
    ):
        el = card.select_one(selector)
        if el:
            title = el.get_text(strip=True)
            href = el.get("href", "")
            if href and title:
                url = href if href.startswith("http") else urljoin(_BASE_URL, href)
                return title, url

    # Last resort: the element itself might be an <a>
    if card.name == "a":
        title = card.get_text(strip=True)
        href = card.get("href", "")
        if href and title:
            return title, href if href.startswith("http") else urljoin(_BASE_URL, href)

    return "", ""


def _extract_description(card) -> str:
    """Extract short description/summary text from a card."""
    for selector in ("p.description", "p.slide-description", "p", "span.description"):
        el = card.select_one(selector)
        if el:
            text = el.get_text(strip=True)
            if len(text) > 20:
                return text
    return ""


def _extract_author(card) -> str:
    for selector in ("span.username", "a.username", "span.author", ".author-name", "cite"):
        el = card.select_one(selector)
        if el:
            return el.get_text(strip=True)
    return ""


def _extract_year(card) -> int | None:
    text = card.get_text()
    m = re.search(r"\b(20\d{2})\b", text)
    if m:
        return int(m.group(1))
    return None


def _is_relevant(text: str, query_terms: set[str]) -> bool:
    for term in _RELEVANCE_TERMS:
        if term in text:
            return True
    for term in query_terms:
        if term and term in text:
            return True
    return False
